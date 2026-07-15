"""Recursive directory scanning.

Turns a folder on disk into a stream of :class:`FileEntry` objects. This layer
is deterministic and does no classification — it only reads what the filesystem
cheaply provides (size, mtime, extension).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from models import FileEntry


def scan(
    root: Path | str,
    *,
    recursive: bool = True,
    follow_symlinks: bool = False,
) -> Iterator[FileEntry]:
    """Yield a :class:`FileEntry` for every file under ``root``.

    Directories are descended into (when ``recursive``) but not yielded
    themselves. Files that cannot be ``stat``-ed (permission errors, broken
    symlinks) are skipped rather than aborting the whole scan; the GUI surfaces
    per-path errors separately.

    Args:
        root: Folder to scan.
        recursive: Descend into subdirectories.
        follow_symlinks: Whether to traverse symlinked directories.
    """
    root = Path(root)
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if recursive and (follow_symlinks or not entry.is_symlink()):
                        stack.append(entry)
                    continue
                stat = entry.stat()
            except (PermissionError, OSError):
                continue
            yield FileEntry(
                path=entry,
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime),
                extension=entry.suffix.lower().lstrip("."),
            )


def count_files(root: Path | str, *, recursive: bool = True) -> int:
    """Return the number of files under ``root`` (for progress-bar totals)."""
    return sum(1 for _ in scan(root, recursive=recursive))
