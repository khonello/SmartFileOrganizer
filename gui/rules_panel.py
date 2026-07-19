"""The Rules page: where each file type goes.

The whole model (see ``mappings.py``): files are sorted into folders by type,
each type with a sensible default the user can override. No patterns, no
priorities, no templates — pick a type, change where it goes, or reset it. It
works out of the box, so there is nothing to set up before organizing.

Greybox: structure and behaviour, no styling.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import mappings

_CATEGORY_ROLE = Qt.ItemDataRole.UserRole


class RulesPanel(QWidget):
    """The type → folder table. Change where a type goes, or reset to default."""

    # Kept name: the window re-plans the diff whenever this fires.
    rules_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overrides: dict[str, str] = {}

        layout = QVBoxLayout(self)
        header = QLabel(
            "Files are sorted into folders by type. Change where any type goes, "
            "or reset it to the default — changed rows are shown in bold. This "
            "works out of the box; there's nothing to set up."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["File type", "Goes to"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._tree.setUniformRowHeights(True)
        self._tree.itemSelectionChanged.connect(self._sync_buttons)
        self._tree.itemDoubleClicked.connect(lambda *_: self._change())
        head = self._tree.header()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._tree, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._btn_change = QPushButton("Change…")
        self._btn_change.clicked.connect(self._change)
        self._btn_reset = QPushButton("Reset to default")
        self._btn_reset.clicked.connect(self._reset)
        buttons.addWidget(self._btn_change)
        buttons.addWidget(self._btn_reset)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        """Reload the overrides and rebuild the table."""
        self._overrides = mappings.load_mappings()
        resolved = mappings.effective(self._overrides)
        self._tree.clear()
        for category in mappings.categories():
            label = "Everything else" if category == "Others" else category
            item = QTreeWidgetItem(self._tree, [label, resolved[category]])
            item.setData(0, _CATEGORY_ROLE, category)
            if category in self._overrides:  # a changed row stands out
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)
        self._sync_buttons()

    # -- editing -----------------------------------------------------------

    def _selected_category(self) -> str | None:
        items = self._tree.selectedItems()
        return items[0].data(0, _CATEGORY_ROLE) if items else None

    def _change(self) -> None:
        category = self._selected_category()
        if category is None:
            return
        current = mappings.effective(self._overrides)[category]
        text, ok = QInputDialog.getText(
            self, "Change destination", f"Folder for {category}:", text=current
        )
        if not ok:
            return
        folder = mappings.clean_destination(text)
        # Empty, or set back to the default, clears the override.
        if not folder or folder == mappings.default_destination(category):
            self._overrides.pop(category, None)
        else:
            self._overrides[category] = folder
        self._save()

    def _reset(self) -> None:
        category = self._selected_category()
        if category is not None and category in self._overrides:
            del self._overrides[category]
            self._save()

    def _save(self) -> None:
        mappings.save_mappings(self._overrides)
        self.refresh()
        self.rules_changed.emit()

    def _sync_buttons(self) -> None:
        category = self._selected_category()
        self._btn_change.setEnabled(category is not None)
        self._btn_reset.setEnabled(
            category is not None and category in self._overrides
        )
