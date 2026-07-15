"""Before/after tree comparison widget.

Renders the classifier's proposed plan as a folder tree with per-folder file
counts, and marks pending-move and conflict rows per DESIGN_SPEC.md §4:

  * pending-move rows: leading 6px brass dot + faint brass row wash;
  * conflict rows (name collision): rust warning glyph + rust filename.

Row reveal animates staggered (180ms/row, 600ms cap) — implemented in code via
QPropertyAnimation, not QSS. STUB.
"""

from __future__ import annotations

from models import ClassificationResult


def build_tree_model(plan: list[ClassificationResult]) -> dict:
    """Fold a flat plan into a nested ``{folder: {...}, "__files__": [...]}`` dict.

    UI-agnostic so it can be unit-tested without Qt; the QTreeView adapter
    consumes this. TODO: attach per-row state (pending/conflict) flags.
    """
    root: dict = {}
    for result in plan:
        parts = result.destination.parts
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append(result)
    return root
