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
from pathlib import Path

from core import file_ops
from core.classifier import Classifier
from core.file_ops import SpaceCheck
from core.scanner import scan
from history.db import HistoryDB
from models import ClassificationResult, CollisionStrategy, Rule

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
    ) -> None:
        self.classifier = Classifier(rules)
        self.collision_strategy = collision_strategy
        self.history = history

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
        """
        folder = Path(folder)
        before = folder / BEFORE_DIR
        batch_id = uuid.uuid4().hex
        total = len(plan)
        for index, result in enumerate(plan, start=1):
            rel = result.entry.path.relative_to(folder)
            staged = before / rel
            file_ops.move(result.entry.path, staged, dry_run=dry_run)

            operation = file_ops.plan_copy(
                staged, result, self.collision_strategy, batch_id=batch_id
            )
            if operation is not None:
                if self.history is not None and not dry_run:
                    self.history.log(operation)  # log BEFORE the copy
                file_ops.copy(operation, dry_run=dry_run)
            if progress is not None:
                progress(index, total)
        return batch_id

    def commit(self, folder: Path | str, *, dry_run: bool = False) -> None:
        """Discard ``before/`` and offload ``after/`` into the folder root.

        The point of no return: the originals are deleted and the folder is
        left holding just the organized structure.
        """
        folder = Path(folder)
        file_ops.remove_tree(folder / BEFORE_DIR, dry_run=dry_run)
        file_ops.promote_children(folder / AFTER_DIR, folder, dry_run=dry_run)
        file_ops.remove_tree(folder / AFTER_DIR, dry_run=dry_run)

    def rollback(self, folder: Path | str, *, dry_run: bool = False) -> None:
        """Discard ``after/`` and restore ``before/``'s contents to the root.

        Returns the folder to its pre-apply state.
        """
        folder = Path(folder)
        file_ops.remove_tree(folder / AFTER_DIR, dry_run=dry_run)
        file_ops.promote_children(folder / BEFORE_DIR, folder, dry_run=dry_run)
        file_ops.remove_tree(folder / BEFORE_DIR, dry_run=dry_run)

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
