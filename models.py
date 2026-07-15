"""Shared data model.

These dataclasses are the contract passed between pipeline stages
(scanner -> classifier -> preview -> executor -> history). Keeping them in one
place lets ``core`` logic be imported and tested without Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class MatchType(str, Enum):
    """What part of a file a rule pattern is tested against."""

    FILENAME = "filename"
    EXTENSION = "extension"
    METADATA = "metadata"


class RuleLayer(str, Enum):
    """Classification layers, in precedence order (highest first).

    Custom user rules override pattern rules, which override metadata rules,
    which override the extension fallback. See README "Rule precedence".
    """

    CUSTOM = "custom"
    PATTERN = "pattern"
    METADATA = "metadata"
    EXTENSION = "extension"


class BatchStatus(str, Enum):
    """Where one run sits in the before/after lifecycle.

    The run's state lives on *disk*, not in the app: ``APPLIED`` means
    ``before/`` and ``after/`` are real folders awaiting the user's decision,
    and it survives closing the app. Only an ``APPLIED`` batch can be undone —
    ``commit`` discards the originals and moves the copies to the folder root,
    which is why undoing past that point is impossible rather than merely
    unimplemented.
    """

    APPLIED = "applied"  # before/ + after/ on disk, awaiting review
    COMMITTED = "committed"  # originals discarded — the point of no return
    ROLLED_BACK = "rolled_back"  # copies discarded, originals restored


class OperationType(str, Enum):
    # Apply is copy-based (before/after model): the original is the "before",
    # the copy is the "after". MOVE is used only when discarding the original.
    COPY = "copy"
    MOVE = "move"
    RENAME = "rename"
    MOVE_RENAME = "move+rename"


class CollisionStrategy(str, Enum):
    APPEND_SUFFIX = "append_suffix"
    OVERWRITE = "overwrite"
    SKIP = "skip"


@dataclass
class FileEntry:
    """A single scanned file and the metadata cheaply available at scan time."""

    path: Path
    size: int
    modified: datetime
    extension: str  # lowercased, without leading dot
    # Populated lazily by the metadata layer when a rule needs it.
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class Rule:
    """A single classification rule (user-defined or preset)."""

    rule: str  # unique identifier
    pattern: str  # glob or regex
    destination: str  # template, e.g. "Work/Invoices/{year}/{month}"
    match_type: MatchType = MatchType.FILENAME
    case_sensitive: bool = False
    priority: int = 0  # higher evaluated first within a layer
    # Which metadata key ``pattern`` is tested against, e.g. "author".
    # Required when match_type is METADATA, unused otherwise.
    metadata_key: str | None = None


@dataclass
class ClassificationResult:
    """The classifier's proposed destination for one file.

    A proposal only — nothing is moved until the executor runs.
    """

    entry: FileEntry
    destination: Path
    layer: RuleLayer
    rule_name: str  # which rule fired, for the details panel / traceability


@dataclass
class Batch:
    """One organization run, and the inputs that produced it.

    ``rules`` is a **snapshot**, not a reference. A run's output is only
    explicable in terms of the rules that made it, so the rule set is frozen
    onto the batch: editing a preset afterwards must never rewrite what an
    older run's trace says it did. Same reasoning for ``collision_strategy``.

    Global preferences (retention, db location) are deliberately *not* here —
    they are properties of the app, not of a run.
    """

    batch_id: str
    folder: Path
    collision_strategy: CollisionStrategy
    rules: list[Rule] = field(default_factory=list)
    preset: str | None = None
    status: BatchStatus = BatchStatus.APPLIED
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class Operation:
    """One row of the operation history / undo log."""

    source_path: Path
    destination_path: Path
    operation_type: OperationType
    batch_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    undone: bool = False
    id: int | None = None  # assigned by the history db on insert
