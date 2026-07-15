"""The inspector: why did this file land here?

A collapsible right panel carrying the full rule trace for the selected file.
The badge in the diff answers *which layer* decided a row; this answers *why*.
Together they are the product's central claim — every decision traces to an
explicit rule — made checkable by the user.

Greybox: structure and content only, no styling.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QWidget

from models import ClassificationResult


class Inspector(QFrame):
    """Rule trace for one file. Empty until something is selected."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(240)

        self._form = QFormLayout(self)
        self._empty = QLabel("Select a file to see why it landed where it did.")
        self._empty.setWordWrap(True)
        self._form.addRow(self._empty)

        self._rows: list[QLabel] = []

    def show_result(self, result: ClassificationResult | None) -> None:
        """Render the trace for ``result``, or the empty state for ``None``."""
        self._clear()
        if result is None:
            self._empty.setVisible(True)
            return
        self._empty.setVisible(False)

        entry = result.entry
        self._add("File", entry.path.name)
        self._add("From", str(entry.path.parent))
        self._add("To", str(result.destination.parent))
        self._add("Decided by", f"{result.layer.value} layer")
        self._add("Rule", result.rule_name)
        self._add("Size", f"{entry.size:,} bytes")
        self._add("Modified", entry.modified.strftime("%Y-%m-%d %H:%M"))

        # Only populated when a rule actually asked for it -- see the laziness
        # constraint in CLAUDE.md. Its absence here is meaningful, not missing.
        if entry.metadata:
            for key, value in sorted(entry.metadata.items()):
                self._add(f"metadata.{key}", str(value))

    # -- internals -----------------------------------------------------------

    def _add(self, label: str, value: str) -> None:
        widget = QLabel(value)
        widget.setWordWrap(True)
        widget.setTextInteractionFlags(
            widget.textInteractionFlags().TextSelectableByMouse
        )
        self._form.addRow(f"{label}:", widget)
        self._rows.append(widget)

    def _clear(self) -> None:
        while self._form.rowCount() > 1:
            self._form.removeRow(1)
        self._rows.clear()
