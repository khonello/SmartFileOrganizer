"""SQLite operation log.

Every executed operation is recorded here **before** the file is moved, so undo
works even if the app crashes mid-batch. Operations are grouped by ``batch_id``
so a whole run can be rolled back together.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from models import Batch, BatchStatus, CollisionStrategy, Operation, OperationType
from rules import rule_loader

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id         TEXT NOT NULL,
    source_path      TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    operation_type   TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    undone           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_operations_batch ON operations(batch_id);

CREATE TABLE IF NOT EXISTS batches (
    batch_id           TEXT PRIMARY KEY,
    folder             TEXT NOT NULL,
    preset             TEXT,
    collision_strategy TEXT NOT NULL,
    rules_json         TEXT NOT NULL,
    status             TEXT NOT NULL,
    started_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status);
"""


class HistoryDB:
    """Thin wrapper over the SQLite operations table.

    Usable as a context manager. Pass ``":memory:"`` for tests.
    """

    def __init__(self, path: Path | str) -> None:
        # The default db lives under %LOCALAPPDATA% (see settings.default_db_path),
        # which won't exist on first run — sqlite won't create the directory for
        # us, it just fails to open. Skip for ":memory:" and file: URIs.
        text = str(path)
        if text != ":memory:" and not text.startswith("file:"):
            Path(text).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(text)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def __enter__(self) -> HistoryDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def log(self, operation: Operation) -> int:
        """Insert an operation and return its assigned row id."""
        cur = self.conn.execute(
            """INSERT INTO operations
               (batch_id, source_path, destination_path, operation_type,
                timestamp, undone)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                operation.batch_id,
                str(operation.source_path),
                str(operation.destination_path),
                operation.operation_type.value,
                operation.timestamp.isoformat(),
                int(operation.undone),
            ),
        )
        self.conn.commit()
        operation.id = int(cur.lastrowid)
        return operation.id

    def operations_for_batch(
        self, batch_id: str, *, include_undone: bool = False
    ) -> list[Operation]:
        """Return a batch's operations, newest first (undo order)."""
        query = "SELECT * FROM operations WHERE batch_id = ?"
        if not include_undone:
            query += " AND undone = 0"
        query += " ORDER BY id DESC"
        rows = self.conn.execute(query, (batch_id,)).fetchall()
        return [_row_to_operation(r) for r in rows]

    def batches(self) -> list[str]:
        """Batch ids that still have at least one un-undone *operation*.

        Derived from the operations log, so it sees batches logged without a
        :meth:`start_batch` record (crash recovery). For the run records that
        drive the history UI, see :meth:`recent_batches`.
        """
        rows = self.conn.execute(
            """SELECT batch_id FROM operations WHERE undone = 0
               GROUP BY batch_id ORDER BY MAX(id) DESC"""
        ).fetchall()
        return [r["batch_id"] for r in rows]

    # -- run records ---------------------------------------------------------

    def start_batch(self, batch: Batch) -> None:
        """Record a run and the inputs that produced it, before it executes.

        Written before any file is touched, for the same reason operations are
        logged before their copy: a run interrupted mid-batch must still be
        findable afterwards.
        """
        self.conn.execute(
            """INSERT OR REPLACE INTO batches
               (batch_id, folder, preset, collision_strategy, rules_json,
                status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                batch.batch_id,
                str(batch.folder),
                batch.preset,
                batch.collision_strategy.value,
                rule_loader.rules_to_json(batch.rules),
                batch.status.value,
                batch.started_at.isoformat(),
            ),
        )
        self.conn.commit()

    def set_batch_status(self, batch_id: str, status: BatchStatus) -> None:
        """Move a run to its next lifecycle state (committed / rolled back)."""
        self.conn.execute(
            "UPDATE batches SET status = ? WHERE batch_id = ?",
            (status.value, batch_id),
        )
        self.conn.commit()

    def get_batch(self, batch_id: str) -> Batch | None:
        """Return one run record, or ``None`` if it was never recorded."""
        row = self.conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        return _row_to_batch(row) if row is not None else None

    def recent_batches(self, *, limit: int | None = None) -> list[Batch]:
        """Run records, newest first — the history sidebar's source."""
        query = "SELECT * FROM batches ORDER BY started_at DESC, rowid DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        return [_row_to_batch(r) for r in self.conn.execute(query, params)]

    def pending_batches(self, folder: Path | str | None = None) -> list[Batch]:
        """Runs still awaiting a decision (``before/``/``after/`` on disk).

        These are what a "you have an unfinished run" prompt is built from, and
        what pruning must never delete.
        """
        query = "SELECT * FROM batches WHERE status = ?"
        params: list[object] = [BatchStatus.APPLIED.value]
        if folder is not None:
            query += " AND folder = ?"
            params.append(str(folder))
        query += " ORDER BY started_at DESC, rowid DESC"
        return [_row_to_batch(r) for r in self.conn.execute(query, params)]

    def mark_undone(self, operation_id: int) -> None:
        self.conn.execute(
            "UPDATE operations SET undone = 1 WHERE id = ?", (operation_id,)
        )
        self.conn.commit()

    def prune(
        self,
        retention_days: int,
        *,
        now: datetime | None = None,
        protect_batches: Iterable[str] = (),
    ) -> int:
        """Drop operations older than ``retention_days``; return rows deleted.

        Enforces ``Settings.history_retention_days``. ``retention_days=0``
        disables pruning entirely.

        Runs still awaiting a decision are protected automatically: a batch
        recorded as :attr:`~models.BatchStatus.APPLIED` has ``before/`` and
        ``after/`` live on the user's disk, and deleting its log would strand
        those files with no record of where they came from. ``protect_batches``
        shields additional ids on top of that (e.g. a batch logged without a
        run record, which the status check cannot see).

        Three deliberate choices:

        * **Batches are pruned whole or not at all.** A batch is eligible only
          once *every* one of its operations is past the cutoff. Deleting half a
          batch would leave a remnant that :class:`~history.undo_manager.
          UndoManager` would happily "roll back" — partially, and silently.
        * **Age is decided in Python, not by SQL.** ``timestamp`` is TEXT
          isoformat, so ``WHERE timestamp < ?`` compares lexicographically,
          which only matches chronological order while every row shares an
          offset. :meth:`log` writes ``datetime.now()`` — naive local — so that
          holds today, but one aware timestamp (``...+02:00``) would quietly
          sort wrong and delete live history. Parsing costs one row scan and
          removes the whole class of bug.
        * **A run record dies with its operations.** Keeping the batches row
          after its log is gone would leave the history sidebar advertising a
          run it can no longer show.
        """
        if retention_days <= 0:
            return 0
        cutoff = (now or datetime.now()) - timedelta(days=retention_days)
        protected = {b.batch_id for b in self.pending_batches()}
        protected.update(protect_batches)

        newest: dict[str, datetime] = {}
        for row in self.conn.execute("SELECT batch_id, timestamp FROM operations"):
            stamp = _as_naive(datetime.fromisoformat(row["timestamp"]))
            batch = row["batch_id"]
            if batch not in newest or stamp > newest[batch]:
                newest[batch] = stamp

        stale = [
            batch
            for batch, stamp in newest.items()
            if stamp < cutoff and batch not in protected
        ]
        if not stale:
            return 0
        placeholders = ",".join("?" * len(stale))
        cur = self.conn.execute(
            f"DELETE FROM operations WHERE batch_id IN ({placeholders})", stale
        )
        self.conn.execute(
            f"DELETE FROM batches WHERE batch_id IN ({placeholders})", stale
        )
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()


def _as_naive(stamp: datetime) -> datetime:
    """Normalize to naive local time so stored and cutoff values are comparable."""
    if stamp.tzinfo is None:
        return stamp
    return stamp.astimezone().replace(tzinfo=None)


def _row_to_operation(row: sqlite3.Row) -> Operation:
    return Operation(
        id=row["id"],
        batch_id=row["batch_id"],
        source_path=Path(row["source_path"]),
        destination_path=Path(row["destination_path"]),
        operation_type=OperationType(row["operation_type"]),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        undone=bool(row["undone"]),
    )


def _row_to_batch(row: sqlite3.Row) -> Batch:
    return Batch(
        batch_id=row["batch_id"],
        folder=Path(row["folder"]),
        collision_strategy=CollisionStrategy(row["collision_strategy"]),
        rules=rule_loader.rules_from_json(
            row["rules_json"], source=f"batch {row['batch_id']}"
        ),
        preset=row["preset"],
        status=BatchStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
    )
