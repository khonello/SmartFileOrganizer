"""Record-based rollback built on the history log.

Reverses a batch's logged copies in the opposite order they were applied
(newest first), deleting each ``after/`` copy, and marks operations ``undone``
so they aren't rolled back twice. This is the fine-grained / crash-recovery
path; the primary user-facing undo is :meth:`Organizer.rollback`, which also
restores ``before/`` to the folder root. See :func:`file_ops.undo_copy`.

**Only an un-committed batch can be undone.** The log records destinations
under ``after/``, but :meth:`Organizer.commit` deletes ``before/`` and moves
those copies up into the folder root — so the logged paths no longer exist and
the originals are gone. Undoing a committed batch is impossible, not merely
unimplemented, and this module refuses rather than silently succeeding.
"""

from __future__ import annotations

from core import file_ops
from history.database import HistoryDB
from models import BatchStatus


class CannotUndoError(RuntimeError):
    """Raised when a batch is past the point where undo could mean anything."""


class UndoManager:
    """Coordinates rolling back batches recorded in :class:`HistoryDB`."""

    def __init__(self, db: HistoryDB) -> None:
        self.db = db

    def undo_batch(self, batch_id: str, *, dry_run: bool = False) -> int:
        """Revert every un-undone operation in ``batch_id``.

        Returns the number of operations reverted. A file whose revert fails
        (e.g. it was deleted out from under us) is left un-undone and skipped;
        the rest of the batch still rolls back.

        Raises :class:`CannotUndoError` for a batch that has already been
        committed or rolled back. A batch with no run record at all is allowed
        through: it predates run records or was logged directly, and refusing
        would disable the crash-recovery path this class exists for.
        """
        self._require_undoable(batch_id)
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
        """Undo the most recent batch that can still be undone.

        Skips batches already committed or rolled back rather than failing on
        them — "undo the last thing" means the last *undoable* thing.
        """
        for batch_id in self.db.batches():
            if self._undoable(batch_id):
                return self.undo_batch(batch_id, dry_run=dry_run)
        return 0

    # -- guards --------------------------------------------------------------

    def _undoable(self, batch_id: str) -> bool:
        batch = self.db.get_batch(batch_id)
        return batch is None or batch.status is BatchStatus.APPLIED

    def _require_undoable(self, batch_id: str) -> None:
        batch = self.db.get_batch(batch_id)
        if batch is None or batch.status is BatchStatus.APPLIED:
            return
        if batch.status is BatchStatus.COMMITTED:
            raise CannotUndoError(
                f"batch {batch_id} was committed: its originals were discarded "
                f"and its copies moved into {batch.folder}, so the logged "
                f"after/ paths no longer exist. There is nothing to undo."
            )
        raise CannotUndoError(
            f"batch {batch_id} was already rolled back; its copies are gone."
        )
