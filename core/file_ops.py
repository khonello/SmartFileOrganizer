"""Filesystem primitives: copy/move, collision handling, staging, space check.

The app uses an in-place **before/after** model, all inside the selected
folder:

  * Apply moves the folder's original contents into ``before/`` (a same-volume
    rename, not a duplication) and builds an organized **copy** into ``after/``.
  * Commit deletes ``before/`` and promotes ``after/``'s contents up into the
    folder root.
  * Cancel/undo deletes ``after/`` and restores ``before/``'s contents.

Because ``before/`` and ``after/`` coexist during review, the organized copy
needs ~1x the source size free — see :func:`check_space`, which callers run
*before* Apply and bail on if it fails.

This module is the only place that mutates the filesystem, and it is the
counterpart to the history log: callers record each planned copy to the undo
log **before** performing it, so a mid-batch crash is still recoverable.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from core.scanner import scan
from models import (
    ClassificationResult,
    CollisionStrategy,
    Operation,
    OperationType,
)

# Extra free space to keep beyond the copy size, so we never fill a volume.
SPACE_MARGIN_BYTES = 256 * 1024 * 1024  # 256 MB


@dataclass
class SpaceCheck:
    """Result of a pre-flight disk-space check."""

    required: int  # bytes the "after" copy will consume (+ margin)
    available: int  # bytes free on the target volume
    ok: bool

    @property
    def shortfall(self) -> int:
        """Bytes we are short by (0 when ``ok``)."""
        return max(0, self.required - self.available)


# -- measurement -------------------------------------------------------------


def directory_size(root: Path | str) -> int:
    """Total size in bytes of all files under ``root`` (uses the scanner)."""
    return sum(entry.size for entry in scan(root))


def free_space(path: Path | str) -> int:
    """Bytes free on the volume that would contain ``path``.

    Walks up to the nearest existing ancestor, since the target folder itself
    may not exist yet.
    """
    probe = Path(path)
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    return shutil.disk_usage(probe).free


def check_space(
    folder: Path | str, *, margin: int = SPACE_MARGIN_BYTES
) -> SpaceCheck:
    """Pre-flight: will an organized copy of ``folder``'s contents fit?

    Call before Apply; bail (don't start) when ``ok`` is False. Only the copy
    into ``after/`` costs space — moving originals into ``before/`` is a
    same-volume rename.
    """
    required = directory_size(folder) + margin
    available = free_space(folder)
    return SpaceCheck(required=required, available=available, ok=available >= required)


# -- collision handling ------------------------------------------------------


def resolve_collision(
    destination: Path, strategy: CollisionStrategy
) -> Path | None:
    """Return the final destination path given a collision ``strategy``.

    * ``APPEND_SUFFIX``: ``file.pdf`` -> ``file (1).pdf`` -> ``file (2).pdf`` …
    * ``OVERWRITE``: returns ``destination`` unchanged.
    * ``SKIP``: returns ``None`` to signal "do not copy this file".
    """
    if not destination.exists():
        return destination
    if strategy is CollisionStrategy.OVERWRITE:
        return destination
    if strategy is CollisionStrategy.SKIP:
        return None

    stem, suffix, parent = destination.stem, destination.suffix, destination.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def plan_copy(
    source: Path,
    result: ClassificationResult,
    strategy: CollisionStrategy,
    *,
    batch_id: str = "",
) -> Operation | None:
    """Build the copy :class:`Operation` from ``source`` into the after-tree.

    ``source`` is the staged path under ``before/`` (the live file to copy);
    ``result.destination`` is the organized target under ``after/``. Returns
    ``None`` when a collision strategy says to skip.
    """
    final = resolve_collision(result.destination, strategy)
    if final is None:
        return None
    return Operation(
        source_path=source,
        destination_path=final,
        operation_type=OperationType.COPY,
        batch_id=batch_id,
    )


# -- mutation primitives -----------------------------------------------------


def copy(operation: Operation, *, dry_run: bool = False) -> None:
    """Perform a logged COPY into the after-tree. No-op on ``dry_run``."""
    if dry_run:
        return
    operation.destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(operation.source_path), str(operation.destination_path))


def undo_copy(operation: Operation, *, dry_run: bool = False) -> None:
    """Reverse a COPY by deleting the after-tree copy (original is intact)."""
    if dry_run:
        return
    operation.destination_path.unlink(missing_ok=True)


def move(src: Path | str, dst: Path | str, *, dry_run: bool = False) -> None:
    """Move a file or directory, creating the destination's parent as needed."""
    if dry_run:
        return
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def promote_children(
    src_dir: Path | str, dst_dir: Path | str, *, dry_run: bool = False
) -> None:
    """Move every direct child of ``src_dir`` up into ``dst_dir``.

    Used to offload ``after/``'s contents into the folder root on commit, and
    to restore ``before/``'s contents on cancel.

    Directories are *merged* into an existing counterpart rather than moved
    into it. Apply stages files, not folders, so the originals' directories
    survive at the root; a plain move would restore ``work/deep.txt`` as
    ``work/work/deep.txt``.
    """
    if dry_run:
        return
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in list(src_dir.iterdir()):
        _promote(child, dst_dir / child.name)


def _promote(src: Path, dst: Path) -> None:
    """Move ``src`` onto ``dst``, recursing when both are directories."""
    if src.is_dir() and dst.is_dir():
        for child in list(src.iterdir()):
            _promote(child, dst / child.name)
        src.rmdir()  # now empty; its contents live under dst
        return
    shutil.move(str(src), str(dst))


def remove_tree(path: Path | str, *, dry_run: bool = False) -> None:
    """Recursively delete ``path`` if it exists (used to discard before/after)."""
    if dry_run:
        return
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
