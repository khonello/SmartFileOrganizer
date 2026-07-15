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

from models import Operation, OperationType

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
        """Return batch ids that still have at least one un-undone operation."""
        rows = self.conn.execute(
            """SELECT batch_id FROM operations WHERE undone = 0
               GROUP BY batch_id ORDER BY MAX(id) DESC"""
        ).fetchall()
        return [r["batch_id"] for r in rows]

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
        disables pruning entirely. ``protect_batches`` shields in-flight batch
        ids — a batch that has been applied but not yet committed or rolled back
        still needs its log, and deleting it would strand the user's files in
        ``after/`` with no record of where they came from.

        Two deliberate choices:

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
        """
        if retention_days <= 0:
            return 0
        cutoff = (now or datetime.now()) - timedelta(days=retention_days)
        protected = set(protect_batches)

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
        cur = self.conn.execute(
            f"DELETE FROM operations WHERE batch_id IN ({','.join('?' * len(stale))})",
            stale,
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
