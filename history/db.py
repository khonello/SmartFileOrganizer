"""SQLite operation log.

Every executed operation is recorded here **before** the file is moved, so undo
works even if the app crashes mid-batch. Operations are grouped by ``batch_id``
so a whole run can be rolled back together.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
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
        self.conn = sqlite3.connect(str(path))
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

    def close(self) -> None:
        self.conn.close()


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
