"""Main application window.

Greybox: **structure only, no styling.** It exists to prove the shape works
before any visual direction is layered on — see ``UI_STRUCTURE.md``, which this
implements and which is the source of truth for every decision here.

The chain, in one direction: **sidebar selects → body follows → buttons follow
the body.** Every enabled/disabled control derives from :class:`AppState` via
:meth:`MainWindow._sync`, so there is exactly one place to answer "is this
legal right now?".
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.preview_tree import DiffPanes
from gui.settings_panel import Inspector
from gui.worker import Worker
from history.database import HistoryDB
from models import Batch, BatchStatus, ClassificationResult
from organizer import Organizer
from rules import rule_loader
from settings import load_settings

DEFAULT_SIZE = (1280, 760)
MINIMUM_SIZE = (960, 600)

_BATCH_ROLE = Qt.ItemDataRole.UserRole
_PAGE_ROLE = Qt.ItemDataRole.UserRole + 1

# PLACEHOLDER colours — throwaway, NOT a palette decision. They exist only so
# the button grouping ("colour groups, fork stays adjacent") can be judged in
# the greybox; real colours arrive with the design anchor (see CLAUDE.md and
# UI_STRUCTURE.md). The grouping they express: Organize + Keep read as filled/
# affirmative ("make it real"), Restore as a recessive ghost (the safe way out);
# Keep is warmed toward caution because it is the one irreversible action.
_PLACEHOLDER_BUTTON_QSS = """
QPushButton { padding: 4px 14px; border-radius: 4px; }
QPushButton[role="affirmative"] {
    background: #3b6db5; color: white; border: 1px solid #2f5896;
}
QPushButton[role="caution"] {
    background: #c9862b; color: white; border: 1px solid #a86f1f;
}
QPushButton[role="quiet"] {
    background: transparent; color: palette(text); border: 1px solid palette(mid);
}
QPushButton:disabled {
    background: palette(button); color: palette(mid); border: 1px solid palette(mid);
}
"""


class AppState(Enum):
    """Facts about the folder, not UI modes. See ``UI_STRUCTURE.md``."""

    EMPTY = auto()  # no folder chosen
    SCANNING = auto()  # building the plan
    PREVIEW = auto()  # plan built, nothing touched
    NO_SPACE = auto()  # check_space failed -- a state, not a dialog
    APPLYING = auto()  # copying
    REVIEW = auto()  # before/ + after/ on disk, awaiting a decision
    RESUME = auto()  # folder was already scaffolded when we found it
    COMMITTED = auto()  # originals gone
    ROLLED_BACK = auto()  # copies gone, originals restored
    HISTORY = auto()  # browsing a past run
    ERROR = auto()


# States where before/ and after/ are live on disk and a decision is owed.
_PENDING = {AppState.REVIEW, AppState.RESUME}


class MainWindow(QMainWindow):
    """The shell: sidebar, top bar, body, bottom bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Smart File Organizer")
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self.settings = load_settings()
        self.db = HistoryDB(self.settings.history_db_path)

        self.state = AppState.EMPTY
        self.folder: Path | None = None
        self.plan: list[ClassificationResult] = []
        self.batch_id: str | None = None
        self.viewing: Batch | None = None  # the history entry being browsed
        self._page = "organize"  # which sidebar page the body is showing
        self._worker: Worker | None = None

        self._build()
        self._refresh_history()
        self._sync()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(self._build_top_bar())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_body())
        self.inspector = Inspector()
        split.addWidget(self.inspector)
        split.setSizes([200, 800, 280])
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        layout.addWidget(self._build_bottom_bar())

    def _build_top_bar(self) -> QWidget:
        """Inputs and view controls — things you choose, never things you commit to."""
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(bar)

        self.folder_label = QLabel("No folder selected")
        row.addWidget(self.folder_label, 1)

        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_folder)
        row.addWidget(choose)

        row.addWidget(QLabel("Rules:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("(none)")
        self.preset_combo.addItems(rule_loader.available_presets())
        default = self.settings.default_preset
        if (index := self.preset_combo.findText(default)) != -1:
            self.preset_combo.setCurrentIndex(index)
        self.preset_combo.currentTextChanged.connect(self._preset_changed)
        row.addWidget(self.preset_combo)
        return bar

    def _build_sidebar(self) -> QWidget:
        """The one navigation system. History is a page that has children."""
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setMinimumWidth(160)

        self.nav_organize = QTreeWidgetItem(self.sidebar, ["Organize"])
        self.nav_organize.setData(0, _PAGE_ROLE, "organize")
        self.nav_history = QTreeWidgetItem(self.sidebar, ["History"])
        self.nav_history.setData(0, _PAGE_ROLE, "history_root")
        for name in ("Rules", "Settings"):
            item = QTreeWidgetItem(self.sidebar, [name])
            item.setData(0, _PAGE_ROLE, name.lower())

        self.sidebar.setCurrentItem(self.nav_organize)
        self.sidebar.itemSelectionChanged.connect(self._nav_changed)
        return self.sidebar

    def _build_body(self) -> QWidget:
        self.body = QStackedWidget()

        self.panes = DiffPanes()
        self.panes.selection_changed.connect(self.inspector_show)
        self.body.addWidget(self.panes)  # 0: organize

        self.history_view = QLabel("Select a run.")
        self.history_view.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_view.setWordWrap(True)
        self.history_view.setMargin(12)
        self.body.addWidget(self.history_view)  # 1: a past run

        self.placeholder = QLabel()
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.placeholder)  # 2: rules / settings
        return self.body

    def _build_bottom_bar(self) -> QWidget:
        """Status left (clickable), actions right.

        Layout follows the "colour groups, fork stays adjacent" decision:
        Organize sits apart from the Restore|Keep pair, and that pair stays
        side by side so the irreversible choice is never seen without its safe
        twin. The Organize↔Keep kinship (both affirmative) is carried by colour
        via the ``role`` property, not by position.
        """
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(bar)

        self.status = QLabel("Choose a folder to begin.")
        row.addWidget(self.status, 1)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        row.addWidget(self.progress)

        # Kept visible and merely disabled, so the legality of each action at
        # each state is observable rather than hidden.
        self.btn_organize = QPushButton("Organize")
        self.btn_organize.clicked.connect(self._apply)
        self.btn_restore = QPushButton("Restore Original")
        self.btn_restore.clicked.connect(self._rollback)
        self.btn_keep = QPushButton("Keep Organized")
        self.btn_keep.clicked.connect(self._commit)

        # role drives the placeholder colour (see _PLACEHOLDER_BUTTON_QSS).
        self.btn_organize.setProperty("role", "affirmative")
        self.btn_keep.setProperty("role", "caution")
        self.btn_restore.setProperty("role", "quiet")

        # status (stretch above) pushes the whole action cluster right; a fixed
        # gap — not a stretch — separates Organize from the Restore|Keep fork so
        # they read as one group on the right rather than Organize floating.
        row.addWidget(self.btn_organize)
        row.addSpacing(20)
        row.addWidget(self.btn_restore)
        row.addWidget(self.btn_keep)

        bar.setStyleSheet(_PLACEHOLDER_BUTTON_QSS)
        return bar

    # -- the chain: state -> what is legal -----------------------------------

    def _sync(self) -> None:
        """The single place that answers "is this action legal right now?"."""
        state = self.state
        pending = state in _PENDING

        self.btn_organize.setEnabled(state is AppState.PREVIEW and bool(self.plan))
        self.btn_restore.setEnabled(pending)
        self.btn_keep.setEnabled(pending)

        # History is read-only: you inspect a past run, you don't act on it.
        # (Undo is impossible past commit; reuse waits for an editable ruleset.)

        self.btn_organize.setText(
            f"Organize {len(self.plan)} Files" if self.plan else "Organize"
        )
        self.progress.setVisible(state is AppState.APPLYING)
        self.panes.collapse_to_one(state is AppState.COMMITTED)

        headings = {
            AppState.PREVIEW: ("Before (now)", "After (proposed)"),
            AppState.REVIEW: ("before/ (originals)", "after/ (organized)"),
            AppState.RESUME: ("before/ (originals)", "after/ (organized)"),
            AppState.COMMITTED: ("", "Organized"),
        }.get(state)
        if headings:
            self.panes.set_headings(*headings)

        self.status.setText(self._status_text())

    def _status_text(self) -> str:
        preset = self.preset_combo.currentText()
        match self.state:
            case AppState.EMPTY:
                return "Choose a folder to begin."
            case AppState.SCANNING:
                return "Scanning…"
            case AppState.PREVIEW:
                folders = len({r.destination.parent for r in self.plan})
                return f"{len(self.plan)} files → {folders} folders · {preset}"
            case AppState.NO_SPACE:
                return self._space_message
            case AppState.APPLYING:
                return "Organizing…"
            case AppState.REVIEW | AppState.RESUME:
                return (
                    "Review before/ vs after/, then keep or restore. "
                    "Nothing is deleted until you keep."
                )
            case AppState.COMMITTED:
                return "Done — originals discarded. This cannot be undone."
            case AppState.ROLLED_BACK:
                return "Restored — the folder is back as it was."
            case AppState.HISTORY:
                if self._page == "rules":
                    return "Rules in effect — read-only in this version."
                if self._page == "settings":
                    return "Settings — read-only in this version."
                return self._history_status()
            case _:
                return self._error_message

    def _history_status(self) -> str:
        if self.viewing is None:
            return "Select a run."
        if self.viewing.status is BatchStatus.COMMITTED:
            return "Committed run — its originals are gone, so it cannot be undone."
        if self.viewing.status is BatchStatus.APPLIED:
            return "This run is still pending — open it under Organize to finish it."
        return "Rolled back — the folder was restored."

    def _set_state(self, state: AppState) -> None:
        self.state = state
        self._sync()

    # -- navigation ----------------------------------------------------------

    def _nav_changed(self) -> None:
        items = self.sidebar.selectedItems()
        if not items:
            return
        page = items[0].data(0, _PAGE_ROLE)
        self._page = page

        if page == "organize":
            self.body.setCurrentIndex(0)
            self.viewing = None
            self._set_state(self._organize_state())
        elif page == "history_root":
            self.body.setCurrentIndex(1)
            self.viewing = None
            self.history_view.setText("Select a run.")
            self._set_state(AppState.HISTORY)
        elif page in {"rules", "settings"}:
            self.body.setCurrentIndex(2)
            self.viewing = None
            self.placeholder.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.placeholder.setText(
                self._rules_text() if page == "rules" else self._settings_text()
            )
            self._set_state(AppState.HISTORY)
        else:  # a run
            self.viewing = items[0].data(0, _BATCH_ROLE)
            self.body.setCurrentIndex(1)
            self._show_batch(self.viewing)
            self._set_state(AppState.HISTORY)

    def _rules_text(self) -> str:
        """The rules that would fire right now — read-only inventory.

        This is where "what's actually in this preset" lives (the top-bar
        dropdown just picks one); the badges then show which of these fired.
        """
        preset = self.preset_combo.currentText()
        preset = None if preset == "(none)" else preset
        rules = rule_loader.load_effective_rules(preset)
        if not rules:
            return (
                f"No rules in effect for {preset or '(none)'}.\n\n"
                "Files fall back to the extension layer (badge E)."
            )
        body = "\n".join(
            f"  {r.priority:>3}  {r.rule}\n"
            f"        [{r.match_type.value}: {r.pattern}]  →  {r.destination}"
            for r in sorted(rules, key=lambda r: (-r.priority, r.rule))
        )
        return (
            f"Rules in effect — {preset or '(none)'}  ({len(rules)} rules)\n"
            f"Higher priority wins within a layer.\n\n{body}\n\n"
            "Read-only in this version."
        )

    def _settings_text(self) -> str:
        """The loaded settings, read-only — the source of the run's defaults."""
        s = self.settings
        return (
            "Settings — read-only in this version.\n\n"
            f"  Default preset:      {s.default_preset}\n"
            f"  Collision strategy:  {s.collision_strategy.value}\n"
            f"  History retention:   {s.history_retention_days} days"
            f"{'  (keep forever)' if s.history_retention_days == 0 else ''}\n"
            f"  History database:    {s.history_db_path}\n"
        )

    def _organize_state(self) -> AppState:
        """The state Organize returns to — the run's state lives on disk."""
        if self.folder is None:
            return AppState.EMPTY
        if self.batch_id is not None and Organizer.is_scaffolded(self.folder):
            return AppState.REVIEW
        if self.plan:
            return AppState.PREVIEW
        return AppState.EMPTY

    def _show_batch(self, batch: Batch | None) -> None:
        if batch is None:
            return
        rules = "\n".join(
            f"    {r.priority:>3}  {r.rule}  ({r.match_type.value}: {r.pattern})"
            f"  →  {r.destination}"
            for r in batch.rules
        )
        self.history_view.setText(
            f"Run {batch.batch_id[:8]}\n"
            f"  Folder:     {batch.folder}\n"
            f"  When:       {batch.started_at:%Y-%m-%d %H:%M}\n"
            f"  Status:     {batch.status.value}\n"
            f"  Preset:     {batch.preset or '(none)'}\n"
            f"  Collisions: {batch.collision_strategy.value}\n\n"
            f"Rules as they were when this run happened "
            f"(a snapshot — editing a preset since then hasn't changed this):\n"
            f"{rules or '    (none)'}"
        )

    def _refresh_history(self) -> None:
        self.nav_history.takeChildren()
        for batch in self.db.recent_batches(limit=25):
            label = f"{batch.folder.name} · {batch.started_at:%d %b %H:%M}"
            if batch.status is BatchStatus.APPLIED:
                label += "  ⬤"  # pending: unfinished business
            item = QTreeWidgetItem(self.nav_history, [label])
            item.setData(0, _BATCH_ROLE, batch)
            item.setData(0, _PAGE_ROLE, "batch")
        self.nav_history.setExpanded(True)

    def inspector_show(self, result: object) -> None:
        self.inspector.show_result(result if result else None)

    # -- the pipeline --------------------------------------------------------

    def _organizer(self) -> Organizer:
        preset = self.preset_combo.currentText()
        preset = None if preset == "(none)" else preset
        rules = rule_loader.load_effective_rules(preset)
        return Organizer(
            rules,
            collision_strategy=self.settings.collision_strategy,
            history=self.db,
            preset=preset,
        )

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder to organize")
        if not chosen:
            return
        self.folder = Path(chosen)
        self.folder_label.setText(str(self.folder))
        self.sidebar.setCurrentItem(self.nav_organize)

        # A run's state lives on disk and outlives the app. A scaffolded folder
        # plans as empty -- which would read as "nothing to organize" while the
        # user's files sit staged in before/. So offer to finish it instead.
        if Organizer.is_scaffolded(self.folder):
            self._offer_resume()
            return
        self._scan()

    def _offer_resume(self) -> None:
        pending = self._organizer().pending_batch(self.folder)
        when = f" from {pending.started_at:%d %b %H:%M}" if pending else ""
        QMessageBox.information(
            self,
            "Unfinished run",
            f"This folder already holds before/ and after/{when}.\n\n"
            "Your files are staged in before/. Keep the organized copy, or "
            "restore the originals.",
        )
        self.batch_id = pending.batch_id if pending else None
        self.plan = []
        self._render_review()  # the staged before/ and after/ are real on disk
        self._set_state(AppState.RESUME)

    def _preset_changed(self) -> None:
        if self.folder is not None and self.state in {
            AppState.PREVIEW,
            AppState.EMPTY,
            AppState.NO_SPACE,
        }:
            self._scan()

    def _scan(self) -> None:
        folder = self.folder
        if folder is None:
            return
        organizer = self._organizer()
        self._set_state(AppState.SCANNING)

        def work() -> tuple[object, list[ClassificationResult]]:
            # Space is checked before the plan is even offered: never start a
            # run that can't finish.
            return organizer.check_space(folder), organizer.build_plan(folder)

        self._run(work, self._scanned)

    def _scanned(self, result: object) -> None:
        space, plan = result  # type: ignore[misc]
        self.plan = plan
        if not space.ok:
            self._space_message = (
                f"Not enough space: needs "
                f"{space.required / 1e9:.1f} GB, "
                f"{space.available / 1e9:.1f} GB free "
                f"(short by {space.shortfall / 1e9:.1f} GB)."
            )
            self.panes.show_message("[run not started]", "[run not started]")
            self._set_state(AppState.NO_SPACE)
            return
        if not plan:
            self.panes.show_message("[folder is empty]", "[nothing to organize]")
            self._set_state(AppState.EMPTY)
            return
        self.panes.show_plan(
            plan, before_root=self.folder, after_root=self.folder / "after"
        )
        self._set_state(AppState.PREVIEW)

    def _apply(self) -> None:
        folder, plan = self.folder, self.plan
        if folder is None or not plan:
            return
        organizer = self._organizer()
        self.progress.setRange(0, len(plan))
        self.progress.setValue(0)
        self._set_state(AppState.APPLYING)

        def work(progress) -> str:
            return organizer.apply(folder, plan, progress=lambda i, n: progress(i, n))

        self._run(work, self._applied, wants_progress=True)

    def _applied(self, batch_id: object) -> None:
        self.batch_id = str(batch_id)
        self._refresh_history()
        self._render_review()  # redraw from the real before/ and after/ on disk
        self._set_state(AppState.REVIEW)

    def _render_review(self) -> None:
        """Draw the real ``before/`` vs ``after/`` — fresh apply or resume.

        Review is a fact about the filesystem, not in-memory state, so it is
        always rendered from disk (via ``Organizer.review_plan``). That way a
        run resumed from a previous session shows the same honest diff, badges
        and all, as one just applied.
        """
        folder = self.folder
        if folder is None:
            return
        results = self._organizer().review_plan(folder)
        if results:
            self.panes.show_plan(
                results,
                before_root=folder / "before",
                after_root=folder / "after",
            )
        else:
            self.panes.show_message(
                "[before/ — nothing staged]", "[after/ — nothing organized]"
            )

    def _commit(self) -> None:
        if self.folder is None:
            return
        confirm = QMessageBox.warning(
            self,
            "Keep organized files?",
            f"This deletes the originals staged in before/ "
            f"({len(self.plan) or 'all'} files) and cannot be undone.\n\n"
            "The organized copy stays.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm is not QMessageBox.StandardButton.Ok:
            return
        self._organizer().commit(self.folder, batch_id=self.batch_id)
        self._finish(AppState.COMMITTED)

    def _rollback(self) -> None:
        if self.folder is None:
            return
        self._organizer().rollback(self.folder, batch_id=self.batch_id)
        self._finish(AppState.ROLLED_BACK)

    def _finish(self, state: AppState) -> None:
        self.batch_id = None
        # before/ and after/ are gone now, so the diff can't be shown; say what
        # the folder holds instead.
        if state is AppState.COMMITTED:
            self.panes.show_message("", "[Organized — moved into the folder root]")
        elif state is AppState.ROLLED_BACK:
            self.panes.show_message("[Restored — the folder is back as it was]", "")
        self._refresh_history()
        self._set_state(state)

    # -- worker plumbing -----------------------------------------------------

    def _run(self, fn, on_done, *, wants_progress: bool = False) -> None:
        worker = Worker(fn, wants_progress=wants_progress, parent=self)
        worker.done.connect(on_done)
        worker.failed.connect(self._failed)
        if wants_progress:
            worker.progress.connect(
                lambda done, total: self.progress.setValue(done)
            )
        worker.finished.connect(self._worker_done)
        self._worker = worker
        worker.start()

    def _worker_done(self) -> None:
        """Drop our handle *before* Qt destroys the thread object.

        Holding a reference past ``deleteLater`` leaves a wrapper around freed
        C++ memory: touching it (``closeEvent`` asking ``isRunning()``) is an
        access violation, not a catchable Python error.
        """
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _failed(self, message: str) -> None:
        self._error_message = message
        self.panes.show_message("[error]", message)
        self._set_state(AppState.ERROR)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # A live worker is one we still own: apply has no cancellation hook, so
        # waiting it out is all we can do (see UI_STRUCTURE.md "Gaps").
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        self.db.close()
        super().closeEvent(event)


def run(argv: list[str]) -> int:
    """Create the QApplication, show the main window, and run the event loop."""
    app = QApplication(argv)
    window = MainWindow()
    window.show()
    return app.exec()
