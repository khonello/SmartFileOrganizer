"""Record-based rollback built on the history log.

Reverses a batch's logged copies in the opposite order they were applied
(newest first), deleting each ``after/`` copy, and marks operations ``undone``
so they aren't rolled back twice. This is the fine-grained / crash-recovery
path; the primary user-facing undo is :meth:`Organizer.rollback`, which also
restores ``before/`` to the folder root. See :func:`file_ops.undo_copy`.
"""

from __future__ import annotations

from core import file_ops
from history.db import HistoryDB


class UndoManager:
    """Coordinates rolling back batches recorded in :class:`HistoryDB`."""

    def __init__(self, db: HistoryDB) -> None:
        self.db = db

    def undo_batch(self, batch_id: str, *, dry_run: bool = False) -> int:
        """Revert every un-undone operation in ``batch_id``.

        Returns the number of operations reverted. A file whose revert fails
        (e.g. it was deleted out from under us) is left un-undone and skipped;
        the rest of the batch still rolls back.
        """
        reverted = 0
        for op in self.db.operations_for_batch(batch_id):
            try:
                file_ops.undo_copy(op, dry_run=dry_run)
            except OSError:
                continue
            if not dry_run and op.id is not None:
                self.db.mark_undone(op.id)
            reverted += 1
        return reverted

    def undo_last(self, *, dry_run: bool = False) -> int:
        """Undo the most recent batch that still has active operations."""
        batches = self.db.batches()
        if not batches:
            return 0
        return self.undo_batch(batches[0], dry_run=dry_run)
