"""The Rules page: see what applies, and create/edit your own rules.

Two layers, shown as two layers — the model that was easy to miss (see
``UI_STRUCTURE.md``): a read-only **rule set** (a shipped preset) underneath,
and **your rules** on top, which always apply and win on conflicts. Only your
rules are editable; they are saved to a single managed file in ``config/rules/``
and merged above the preset by ``rule_loader.load_effective_rules``.

Greybox: structure and behaviour, no styling.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import MatchType, Rule
from rules import rule_loader

_RULE_ROLE = Qt.ItemDataRole.UserRole
_COLUMNS = ["Rule", "Match", "Pattern", "Destination", "Pri"]


class RulesPanel(QWidget):
    """See the effective rules; add / edit / delete your own.

    Emits :attr:`rules_changed` after any save, so the window can re-plan — your
    rules always apply, so editing them changes the proposed tree.
    """

    rules_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preset: str | None = None
        self._user_rules: list[Rule] = []

        layout = QVBoxLayout(self)
        header = QLabel(
            "Your rules always apply on top of the rule set and win on "
            "conflicts. The rule set is read-only; your rules are yours to edit."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # -- your rules: editable ------------------------------------------
        self._your_box = QGroupBox("Your rules")
        your = QVBoxLayout(self._your_box)
        self._your_tree = self._make_tree()
        self._your_tree.itemSelectionChanged.connect(self._sync_buttons)
        self._your_tree.itemDoubleClicked.connect(lambda *_: self._edit())
        your.addWidget(self._your_tree)

        buttons = QHBoxLayout()
        self._empty_hint = QLabel("No rules yet — Add one to override the set.")
        buttons.addWidget(self._empty_hint, 1)
        self._btn_add = QPushButton("Add rule")
        self._btn_add.clicked.connect(self._add)
        self._btn_edit = QPushButton("Edit")
        self._btn_edit.clicked.connect(self._edit)
        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._delete)
        for btn in (self._btn_add, self._btn_edit, self._btn_delete):
            buttons.addWidget(btn)
        your.addLayout(buttons)
        layout.addWidget(self._your_box, 1)

        # -- the rule set: read-only ---------------------------------------
        self._set_box = QGroupBox("Rule set")
        rule_set = QVBoxLayout(self._set_box)
        self._set_tree = self._make_tree()
        self._set_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._set_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rule_set.addWidget(self._set_tree)
        layout.addWidget(self._set_box, 1)

    # -- public ------------------------------------------------------------

    def set_rule_set(self, preset: str | None) -> None:
        """Point the read-only section at ``preset`` and reload everything."""
        self._preset = preset
        self.refresh()

    def refresh(self) -> None:
        """Reload from disk and rebuild both trees."""
        self._user_rules = self._load_user_rules()
        preset_rules = (
            rule_loader.load_preset(self._preset) if self._preset else []
        )
        self._fill(self._your_tree, self._user_rules)
        self._fill(self._set_tree, preset_rules)
        self._your_box.setTitle(f"Your rules  ({len(self._user_rules)})")
        self._set_box.setTitle(
            f"Rule set  ·  {self._preset or '(none)'}  ({len(preset_rules)})"
        )
        self._empty_hint.setVisible(not self._user_rules)
        self._sync_buttons()

    # -- editing -----------------------------------------------------------

    def _add(self) -> None:
        dialog = _RuleDialog(self, taken_ids=self._ids())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._user_rules.append(dialog.result_rule())
            self._save()

    def _edit(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        dialog = _RuleDialog(
            self, rule=rule, taken_ids=self._ids() - {rule.rule}
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            index = self._user_rules.index(rule)
            self._user_rules[index] = dialog.result_rule()
            self._save()

    def _delete(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete rule?",
            f"Delete your rule {rule.rule!r}? The rule set is untouched.",
        )
        if confirm is QMessageBox.StandardButton.Yes:
            self._user_rules.remove(rule)
            self._save()

    def _save(self) -> None:
        rule_loader.save_user_rules(self._user_rules)
        self.refresh()
        self.rules_changed.emit()

    # -- internals ---------------------------------------------------------

    def _load_user_rules(self) -> list[Rule]:
        """The managed file's rules, or none if it is absent or unreadable."""
        path = rule_loader.USER_RULES_FILE
        if not path.exists():
            return []
        try:
            return rule_loader.load_rules(path)
        except (rule_loader.RuleValidationError, OSError):
            # A hand-edited file with a syntax error: don't crash the page.
            return []

    def _ids(self) -> set[str]:
        return {r.rule for r in self._user_rules}

    def _selected_rule(self) -> Rule | None:
        items = self._your_tree.selectedItems()
        return items[0].data(0, _RULE_ROLE) if items else None

    def _sync_buttons(self) -> None:
        has_selection = self._selected_rule() is not None
        self._btn_edit.setEnabled(has_selection)
        self._btn_delete.setEnabled(has_selection)

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(len(_COLUMNS))
        tree.setHeaderLabels(_COLUMNS)
        tree.setRootIsDecorated(False)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        return tree

    def _fill(self, tree: QTreeWidget, rules: list[Rule]) -> None:
        tree.clear()
        for rule in sorted(rules, key=lambda r: (-r.priority, r.rule)):
            item = QTreeWidgetItem(
                tree,
                [
                    rule.rule,
                    rule.match_type.value,
                    rule.pattern,
                    rule.destination,
                    str(rule.priority),
                ],
            )
            item.setData(0, _RULE_ROLE, rule)


class _RuleDialog(QDialog):
    """Add or edit one user rule. Validates before it will close on OK."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        rule: Rule | None = None,
        taken_ids: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit rule" if rule else "Add rule")
        self._taken_ids = taken_ids or set()
        self._result: Rule | None = None

        form = QFormLayout(self)

        self.f_rule = QLineEdit()
        self.f_rule.setPlaceholderText("unique id, e.g. my_invoices")
        form.addRow("Rule id", self.f_rule)

        self.f_match = QComboBox()
        self.f_match.addItems([mt.value for mt in MatchType])
        self.f_match.currentTextChanged.connect(self._sync_meta)
        form.addRow("Match", self.f_match)

        self.f_pattern = QLineEdit()
        self.f_pattern.setPlaceholderText("glob, e.g. *invoice*  or  *.pdf")
        form.addRow("Pattern", self.f_pattern)

        self.f_meta = QLineEdit()
        self.f_meta.setPlaceholderText("metadata key, e.g. author")
        form.addRow("Metadata key", self.f_meta)

        self.f_dest = QLineEdit()
        self.f_dest.setPlaceholderText("template, e.g. Documents/Invoices/{year}")
        form.addRow("Destination", self.f_dest)

        self.f_priority = QSpinBox()
        self.f_priority.setRange(0, 999)
        self.f_priority.setValue(10)
        form.addRow("Priority", self.f_priority)

        self.f_case = QCheckBox("Case sensitive")
        form.addRow("", self.f_case)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

        if rule is not None:
            self._load(rule)
        self._sync_meta()

    def result_rule(self) -> Rule:
        """The validated rule (only valid after an accepted dialog)."""
        assert self._result is not None
        return self._result

    # -- internals ---------------------------------------------------------

    def _load(self, rule: Rule) -> None:
        self.f_rule.setText(rule.rule)
        self.f_match.setCurrentText(rule.match_type.value)
        self.f_pattern.setText(rule.pattern)
        self.f_meta.setText(rule.metadata_key or "")
        self.f_dest.setText(rule.destination)
        self.f_priority.setValue(rule.priority)
        self.f_case.setChecked(rule.case_sensitive)

    def _sync_meta(self) -> None:
        is_meta = self.f_match.currentText() == MatchType.METADATA.value
        self.f_meta.setEnabled(is_meta)
        if not is_meta:
            self.f_meta.clear()

    def _build_rule(self) -> Rule:
        return Rule(
            rule=self.f_rule.text().strip(),
            pattern=self.f_pattern.text().strip(),
            destination=self.f_dest.text().strip(),
            match_type=MatchType(self.f_match.currentText()),
            case_sensitive=self.f_case.isChecked(),
            priority=self.f_priority.value(),
            metadata_key=self.f_meta.text().strip() or None,
        )

    def accept(self) -> None:  # noqa: D102 - QDialog override
        rule = self._build_rule()
        try:
            rule_loader.validate_rule(rule)
        except rule_loader.RuleValidationError as exc:
            QMessageBox.warning(self, "Invalid rule", str(exc))
            return
        if rule.rule in self._taken_ids:
            QMessageBox.warning(
                self,
                "Name taken",
                f"A rule named {rule.rule!r} already exists — choose another id.",
            )
            return
        self._result = rule
        super().accept()
