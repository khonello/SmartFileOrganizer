"""The body: two panes read as a diff.

Per ``UI_STRUCTURE.md`` — this is *not* two file browsers. The value is
answering "where did this file go, and why", so the panes are linked: selecting
a file on one side highlights its counterpart on the other, and every row on the
right carries the badge of the rule layer that decided it.

Greybox: structure and behaviour only, no styling.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from gui import theme
from models import ClassificationResult, RuleLayer

# The rule engine, made legible on every row. If a whole plan reads "E", the
# rules aren't firing and the preset is doing nothing -- the diagnostic a
# details-on-click panel could never give you.
_BADGE = {
    RuleLayer.CUSTOM: "C",
    RuleLayer.PATTERN: "P",
    RuleLayer.METADATA: "M",
    RuleLayer.EXTENSION: "E",
}

_RESULT_ROLE = Qt.ItemDataRole.UserRole


class DiffPanes(QSplitter):
    """Before/after panes with linked selection.

    Pane meanings shift by state, deliberately — it's the same question each
    time (see ``UI_STRUCTURE.md``):

    * Preview: left = the folder as it is now, right = the proposed tree.
    * Review:  left = the real ``before/``, right = the real ``after/``.
    """

    selection_changed = Signal(object)  # ClassificationResult | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.before = self._make_tree("Before")
        self.after = self._make_tree("After (proposed)")
        self.addWidget(self.before)
        self.addWidget(self.after)
        # Equal halves: a diff's two sides are peers. An unequal split would
        # quietly tell the eye one side matters more, undercutting "compare".
        self.setSizes([500, 500])

        # Counterpart lookup, both directions -- this is what makes the panes a
        # diff rather than two independent lists.
        self._twin: dict[QTreeWidgetItem, QTreeWidgetItem] = {}
        self._syncing = False

        self.before.itemSelectionChanged.connect(
            lambda: self._mirror(self.before, self.after)
        )
        self.after.itemSelectionChanged.connect(
            lambda: self._mirror(self.after, self.before)
        )

    # -- population ----------------------------------------------------------

    def show_plan(
        self,
        plan: list[ClassificationResult],
        *,
        before_root: Path,
        after_root: Path,
    ) -> None:
        """Render a plan into both panes as a diff.

        The two panes have different roots, so they are passed explicitly:

        * Preview — ``before_root`` is the folder itself (originals sit at the
          root), ``after_root`` is the proposed ``after/`` tree.
        * Review/Resume — ``before_root`` is the real ``before/`` and
          ``after_root`` the real ``after/``; the plan is reconstructed from
          disk by :meth:`organizer.Organizer.review_plan`.

        Either way each ``result`` carries the rule layer, so the badges and the
        inspector trace work identically in both states.
        """
        self.clear_panes()

        before_nodes: dict[Path, QTreeWidgetItem] = {}
        after_nodes: dict[Path, QTreeWidgetItem] = {}

        for result in plan:
            source_rel = result.entry.path.relative_to(before_root)
            left = self._ensure_path(self.before, before_nodes, source_rel)

            dest_rel = result.destination.relative_to(after_root)
            right = self._ensure_path(self.after, after_nodes, dest_rel)
            letter = _BADGE.get(result.layer, "?")
            right.setText(1, letter)
            right.setToolTip(1, f"{result.layer.value} — {result.rule_name}")
            self._paint_badge(right, letter)

            for item in (left, right):
                item.setData(0, _RESULT_ROLE, result)
            self._twin[left] = right
            self._twin[right] = left

        self.before.expandAll()
        self.after.expandAll()

    def show_message(self, left: str, right: str = "") -> None:
        """Put a single explanatory row in each pane (empty / error states)."""
        self.clear_panes()
        QTreeWidgetItem(self.before, [left])
        QTreeWidgetItem(self.after, [right or left])

    def clear_panes(self) -> None:
        self._twin.clear()
        self.before.clear()
        self.after.clear()

    def set_headings(self, left: str, right: str) -> None:
        """Pane meanings shift by state; the headings must say which one holds."""
        self.before.setHeaderLabels([left, "Rule"])
        self.after.setHeaderLabels([right, "Rule"])

    def collapse_to_one(self, collapsed: bool) -> None:
        """Committed: nothing left to compare, so don't keep an empty half."""
        self.before.setVisible(not collapsed)

    # -- internals -----------------------------------------------------------

    def _make_tree(self, heading: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels([heading, "Rule"])
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    def _paint_badge(self, item: QTreeWidgetItem, letter: str) -> None:
        """Colour a badge cell from the active theme — QSS can't reach it, as
        the badge is tree-cell text (see ``gui.theme``)."""
        bg, fg, bold = theme.badge_style(letter)
        item.setForeground(1, QColor(fg))
        if bg is not None:
            item.setBackground(1, QColor(bg))
        font = item.font(1)
        font.setBold(bold)
        item.setFont(1, font)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)

    def _ensure_path(
        self,
        tree: QTreeWidget,
        nodes: dict[Path, QTreeWidgetItem],
        rel: Path,
    ) -> QTreeWidgetItem:
        """Create (or reuse) the nested items for ``rel``; return its leaf."""
        current = Path()
        parent: QTreeWidgetItem | None = None
        for part in rel.parts:
            current = current / part
            existing = nodes.get(current)
            if existing is None:
                existing = (
                    QTreeWidgetItem(parent, [part])
                    if parent is not None
                    else QTreeWidgetItem(tree, [part])
                )
                nodes[current] = existing
            parent = existing
        assert parent is not None  # rel always names a file, never empty
        return parent

    def _mirror(self, source: QTreeWidget, target: QTreeWidget) -> None:
        """Reflect the selection into the other pane, and report it upward."""
        if self._syncing:
            return
        items = source.selectedItems()
        if not items:
            return
        item = items[0]

        self._syncing = True
        try:
            twin = self._twin.get(item)
            target.clearSelection()
            if twin is not None:
                twin.setSelected(True)
                target.scrollToItem(twin)
        finally:
            self._syncing = False

        self.selection_changed.emit(item.data(0, _RESULT_ROLE))
