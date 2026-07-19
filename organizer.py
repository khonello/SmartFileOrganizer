"""Pipeline orchestration for the in-place before/after model.

Lifecycle over one selected folder:

    check_space(folder)   # bail if the organized copy won't fit
    build_plan(folder)    # classify -> proposed "after" tree (touches nothing)
    apply(folder, plan)   # move originals -> before/, copy -> after/ (logged)
    commit(folder)        # discard before/, offload after/ into the root
      -- or --
    rollback(folder)      # discard after/, restore before/ into the root

Planning and execution stay separate, mirroring "nothing moves without preview
approval": the GUI renders the plan from ``build_plan`` and only calls ``apply``
after the user approves. ``apply`` and ``commit``/``rollback`` are also two
distinct steps, so the user reviews ``before/`` vs ``after/`` before committing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

from core import file_ops
from core.classifier import Classifier
from core.file_ops import SpaceCheck
from core.scanner import scan
from history.database import HistoryDB
from models import (
    Batch,
    BatchStatus,
    ClassificationResult,
    CollisionStrategy,
    Rule,
)

ProgressCallback = Callable[[int, int], None]

BEFORE_DIR = "before"
AFTER_DIR = "after"


class Organizer:
    """Drives the before/after organization lifecycle for one folder."""

    def __init__(
        self,
        rules: list[Rule] | None = None,
        *,
        collision_strategy: CollisionStrategy = CollisionStrategy.APPEND_SUFFIX,
        history: HistoryDB | None = None,
        preset: str | None = None,
        category_overrides: dict[str, str] | None = None,
        use_pattern_layer: bool = True,
        use_metadata_layer: bool = False,
    ) -> None:
        self.classifier = Classifier(
            rules,
            use_pattern_layer=use_pattern_layer,
            use_metadata_layer=use_metadata_layer,
            category_overrides=category_overrides,
        )
        self.rules = list(rules or [])
        self.collision_strategy = collision_strategy
        self.history = history
        # Files the last apply() couldn't move (locked by another process, etc.)
        # and left in place. The caller reports these; the run still succeeds.
        self.last_skipped: list[Path] = []
        # Recorded onto each batch, so a run's history entry can say which
        # preset it came from rather than just showing the flattened rules.
        self.preset = preset

    def check_space(self, folder: Path | str) -> SpaceCheck:
        """Pre-flight disk-space check. Call before :meth:`apply`; bail if
        ``not result.ok``."""
        return file_ops.check_space(folder)

    def build_plan(self, folder: Path | str) -> list[ClassificationResult]:
        """Scan ``folder`` and return the proposed ``after/`` tree.

        Pure planning — touches no files. Any existing ``before/``/``after/``
        scaffolding is ignored so a re-run doesn't re-organize itself.
        """
        folder = Path(folder)
        base = folder / AFTER_DIR
        return [
            self.classifier.classify(entry, base=base)
            for entry in scan(folder)
            if not self._is_scaffold(entry.path, folder)
        ]

    def apply(
        self,
        folder: Path | str,
        plan: list[ClassificationResult],
        *,
        dry_run: bool = False,
        progress: ProgressCallback | None = None,
    ) -> str:
        """Stage originals into ``before/`` and copy them into ``after/``.

        For each planned file: move the original into ``before/`` (preserving
        its relative path), then copy the staged file into its organized
        ``after/`` destination, logging the copy first. Returns the batch id.

        The run itself is recorded before any file moves, with a snapshot of
        the rules that produced it — a run's trace is only meaningful against
        the rules in force at the time, and presets change.
        """
        folder = Path(folder)
        before = folder / BEFORE_DIR
        batch_id = uuid.uuid4().hex
        total = len(plan)

        if self.history is not None and not dry_run:
            self.history.start_batch(
                Batch(
                    batch_id=batch_id,
                    folder=folder,
                    collision_strategy=self.collision_strategy,
                    rules=self.rules,
                    preset=self.preset,
                    status=BatchStatus.APPLIED,
                )
            )
        self.last_skipped = []
        for index, result in enumerate(plan, start=1):
            rel = result.entry.path.relative_to(folder)
            staged = before / rel
            try:
                file_ops.move(result.entry.path, staged, dry_run=dry_run)
            except OSError:
                # Locked by another process (Windows "file in use") or otherwise
                # unmovable: leave the original where it is and carry on. The
                # original is untouched — the move is the first thing we tried.
                self.last_skipped.append(result.entry.path)
                if progress is not None:
                    progress(index, total)
                continue

            operation = file_ops.plan_copy(
                staged, result, self.collision_strategy, batch_id=batch_id
            )
            if operation is not None:
                try:
                    if self.history is not None and not dry_run:
                        self.history.log(operation)  # log BEFORE the copy
                    file_ops.copy(operation, dry_run=dry_run)
                except OSError:
                    # Couldn't write the organized copy: undo the stage so the
                    # original isn't stranded in before/ with no after/ twin.
                    file_ops.move(staged, result.entry.path, dry_run=dry_run)
                    self.last_skipped.append(result.entry.path)
            if progress is not None:
                progress(index, total)
        return batch_id

    def commit(
        self,
        folder: Path | str,
        *,
        batch_id: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Discard ``before/`` and offload ``after/`` into the folder root.

        The point of no return: the originals are deleted and the folder is
        left holding just the organized structure. Recording the batch as
        committed is what lets undo *refuse* afterwards instead of silently
        doing nothing — the logged ``after/`` paths cease to exist here.

        ``batch_id`` defaults to the folder's pending run, so a resumed session
        that no longer holds the id in memory can still finish the run.
        """
        folder = Path(folder)
        file_ops.remove_tree(folder / BEFORE_DIR, dry_run=dry_run)
        file_ops.promote_children(folder / AFTER_DIR, folder, dry_run=dry_run)
        file_ops.remove_tree(folder / AFTER_DIR, dry_run=dry_run)
        self._finish(folder, batch_id, BatchStatus.COMMITTED, dry_run=dry_run)

    def rollback(
        self,
        folder: Path | str,
        *,
        batch_id: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Discard ``after/`` and restore ``before/``'s contents to the root.

        Returns the folder to its pre-apply state.
        """
        folder = Path(folder)
        file_ops.remove_tree(folder / AFTER_DIR, dry_run=dry_run)
        file_ops.promote_children(folder / BEFORE_DIR, folder, dry_run=dry_run)
        file_ops.remove_tree(folder / BEFORE_DIR, dry_run=dry_run)
        self._finish(folder, batch_id, BatchStatus.ROLLED_BACK, dry_run=dry_run)

    # -- resuming ------------------------------------------------------------

    def pending_batch(self, folder: Path | str) -> Batch | None:
        """The run awaiting a decision on ``folder``, if the history knows one.

        A run's state lives on disk and outlives the app, so a folder can hold
        a half-finished run from a previous session.
        """
        if self.history is None:
            return None
        pending = self.history.pending_batches(Path(folder))
        return pending[0] if pending else None

    def review_plan(self, folder: Path | str) -> list[ClassificationResult]:
        """Rebuild the before/after diff for a run awaiting review, from disk.

        A run's state lives on disk, so a review can be entered with no plan in
        memory — right after a fresh :meth:`apply`, or when resuming a run left
        by an earlier session. The rows are reconstructed from the operation log
        (the actual staged→organized pairs, collision suffix and all), and each
        row's rule layer is re-derived by classifying the staged file against
        the batch's **snapshot** rules, so the badges reflect the rules that
        were in force when the run happened — not today's presets.

        Returns an empty list when there is no history, no pending run, or no
        staged ``before/`` on disk.
        """
        folder = Path(folder)
        before = folder / BEFORE_DIR
        if self.history is None:
            return []
        batch = self.pending_batch(folder)
        if batch is None or not before.exists():
            return []

        # The log holds where each staged file *actually* landed (a collision
        # may have suffixed it); prefer that over the freshly-recomputed path.
        actual_dest = {
            Path(op.source_path): Path(op.destination_path)
            for op in self.history.operations_for_batch(batch.batch_id)
        }
        base = folder / AFTER_DIR
        results: list[ClassificationResult] = []
        for entry in scan(before):
            # Re-derive the badge with this organizer's own classifier; the
            # destination shown always comes from the log (below), so a config
            # drift only affects the badge, never where a file is said to go.
            result = self.classifier.classify(entry, base=base)
            dest = actual_dest.get(entry.path)
            if dest is not None:
                result = replace(result, destination=dest)
            results.append(result)
        return results

    @staticmethod
    def is_scaffolded(folder: Path | str) -> bool:
        """True if ``folder`` already holds ``before/``/``after/`` scaffolding.

        The disk-level counterpart to :meth:`pending_batch`: it spots an
        unfinished run even with no history db. Worth checking before planning
        — a scaffolded folder yields an empty plan (everything in it is
        skipped as scaffolding), which reads as "nothing to organize" while the
        user's files sit staged in ``before/``.
        """
        folder = Path(folder)
        return (folder / BEFORE_DIR).exists() or (folder / AFTER_DIR).exists()

    def _finish(
        self,
        folder: Path,
        batch_id: str | None,
        status: BatchStatus,
        *,
        dry_run: bool,
    ) -> None:
        """Move the run record to its terminal state."""
        if self.history is None or dry_run:
            return
        if batch_id is None:
            batch = self.pending_batch(folder)
            if batch is None:
                return  # no run record (e.g. history added mid-flight)
            batch_id = batch.batch_id
        self.history.set_batch_status(batch_id, status)

    def iter_plan(self, folder: Path | str) -> Iterator[ClassificationResult]:
        """Streaming variant of :meth:`build_plan` for staggered UI reveal."""
        folder = Path(folder)
        base = folder / AFTER_DIR
        for entry in scan(folder):
            if not self._is_scaffold(entry.path, folder):
                yield self.classifier.classify(entry, base=base)

    @staticmethod
    def _is_scaffold(path: Path, folder: Path) -> bool:
        """True if ``path`` lives inside this folder's before/after scaffolding."""
        rel = path.relative_to(folder)
        return bool(rel.parts) and rel.parts[0] in {BEFORE_DIR, AFTER_DIR}
