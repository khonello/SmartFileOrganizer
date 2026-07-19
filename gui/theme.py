"""Theme: the palette from ``DESIGN.md`` turned into QSS.

One accent (amber) on a neutral base, in a light and a dark variant chosen from
the OS. QSS has no variables, so the stylesheet is a ``string.Template`` filled
from a token table — the accent lives in exactly one place per theme. Badge
colours can't be reached from QSS (they're tree-cell text), so they travel in
the same token table and are applied in code by ``preview_tree``.

See ``DESIGN.md`` for the reasoning and the contrast rules (chief among them:
never white text on amber — text on amber is always the navy ``on_accent``).
"""

from __future__ import annotations

from string import Template

from PySide6.QtGui import QPalette

# -- token tables ------------------------------------------------------------
# Flat keys feed the QSS template; "badges" is read in code, not substituted.

LIGHT: dict = {
    "bg": "#ffffff",
    "bg_chrome": "#e5e5e5",
    "surface_alt": "#f4f4f4",
    "text": "#14213d",
    "text_strong": "#000000",
    "text_muted": "rgba(20, 33, 61, 0.55)",
    "border": "#e5e5e5",
    "accent": "#fca311",
    "accent_hover": "#e8940c",
    "accent_pressed": "#cc7f08",
    "on_accent": "#14213d",
    "selection": "rgba(252, 163, 17, 0.22)",
    "badges": {
        # (background or None, foreground, bold)
        "C": ("#fca311", "#14213d", True),   # your rule — the amber eye-draw
        "P": ("#14213d", "#ffffff", False),  # built-in pattern — solid chip
        "M": (None, "#14213d", True),        # built-in metadata — bold, no fill
        "E": (None, "#8a90a0", False),       # extension fallback — quiet
    },
}

DARK: dict = {
    "bg": "#14213d",
    "bg_chrome": "#0d1526",
    "surface_alt": "#1c2b4a",
    "text": "#e5e5e5",
    "text_strong": "#ffffff",
    "text_muted": "rgba(229, 229, 229, 0.60)",
    "border": "rgba(229, 229, 229, 0.16)",
    "accent": "#fca311",
    "accent_hover": "#ffb733",
    "accent_pressed": "#e8940c",
    "on_accent": "#14213d",
    "selection": "rgba(252, 163, 17, 0.28)",
    "badges": {
        "C": ("#fca311", "#14213d", True),
        "P": ("#e5e5e5", "#14213d", False),
        "M": (None, "#e5e5e5", True),
        "E": (None, "#7c8aa5", False),
    },
}

# The currently-applied token table (badges read this). Default light until
# apply() runs, so a bare widget in a test still resolves.
_active: dict = LIGHT


_QSS = Template(
    """
QMainWindow, QDialog, QMessageBox { background: $bg; }
QWidget { color: $text; font-family: "Segoe UI"; font-size: 10pt; }

/* Chrome: top/bottom bars */
QFrame#topBar {
    background: $bg_chrome; border: none; border-bottom: 1px solid $border;
}
QFrame#bottomBar {
    background: $bg_chrome; border: none; border-top: 1px solid $border;
}

/* Sidebar: the one navigation system */
QTreeWidget#sidebar {
    background: $bg_chrome; border: none; border-right: 1px solid $border;
    outline: 0;
}
QTreeWidget#sidebar::item { padding: 6px 8px; border-radius: 4px; }
QTreeWidget#sidebar::item:hover { background: $surface_alt; }
QTreeWidget#sidebar::item:selected { background: $accent; color: $on_accent; }

/* Body trees: the diff, the rules lists */
QTreeWidget {
    background: $bg; border: 1px solid $border; outline: 0;
}
QTreeWidget::item { padding: 3px 4px; }
QTreeWidget::item:selected { background: $selection; color: $text_strong; }
QHeaderView::section {
    background: $bg_chrome; color: $text_muted;
    padding: 4px 6px; border: none; border-bottom: 1px solid $border;
}

/* Inspector + splitter */
QFrame#inspector {
    background: $bg; border: none; border-left: 1px solid $border;
}
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; }

/* Buttons: neutral base */
QPushButton {
    background: $surface_alt; color: $text;
    border: 1px solid $border; border-radius: 4px; padding: 4px 14px;
}
QPushButton:hover { background: $bg_chrome; }
QPushButton:focus { border: 1px solid $accent; }
QPushButton:disabled {
    background: $bg_chrome; color: $text_muted; border: 1px solid $border;
}

/* Affirmative (Organize) and caution (Keep) both read amber; the confirm
   dialog, not a second hue, marks the irreversible one. */
QPushButton[role="affirmative"], QPushButton[role="caution"] {
    background: $accent; color: $on_accent;
    border: 1px solid $accent_pressed; font-weight: 600;
}
QPushButton[role="affirmative"]:hover, QPushButton[role="caution"]:hover {
    background: $accent_hover;
}
QPushButton[role="affirmative"]:pressed, QPushButton[role="caution"]:pressed {
    background: $accent_pressed;
}
QPushButton[role="quiet"] {
    background: transparent; color: $text; border: 1px solid $border;
}
QPushButton[role="quiet"]:hover { background: $surface_alt; }
/* Disabled beats the role fills (more specific selector). */
QPushButton[role="affirmative"]:disabled,
QPushButton[role="caution"]:disabled,
QPushButton[role="quiet"]:disabled {
    background: $bg_chrome; color: $text_muted;
    border: 1px solid $border; font-weight: normal;
}

/* Dropdowns (e.g. match type in the rule dialog) */
QComboBox {
    background: $surface_alt; color: $text;
    border: 1px solid $border; border-radius: 4px; padding: 3px 8px;
}
QComboBox:hover, QComboBox:focus { border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: $bg; color: $text; border: 1px solid $border; outline: 0;
    selection-background-color: $accent; selection-color: $on_accent;
}

/* Inputs (rule dialog) */
QLineEdit, QSpinBox {
    background: $bg; color: $text;
    border: 1px solid $border; border-radius: 4px; padding: 3px 6px;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid $accent; }
QLineEdit:disabled { background: $bg_chrome; color: $text_muted; }
QCheckBox { spacing: 6px; }

/* Grouped sections on the Rules page */
QGroupBox {
    border: 1px solid $border; border-radius: 6px;
    margin-top: 10px; padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $text_muted;
}

/* Progress */
QProgressBar {
    background: $surface_alt; color: $text;
    border: 1px solid $border; border-radius: 4px; text-align: center;
}
QProgressBar::chunk { background: $accent; border-radius: 3px; }

/* Scrollbars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle {
    background: $border; border-radius: 5px; min-height: 24px; min-width: 24px;
}
QScrollBar::handle:hover { background: $text_muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
)


def build_qss(tokens: dict) -> str:
    """Render the stylesheet for a token table."""
    return _QSS.substitute(tokens)


def badge_style(letter: str) -> tuple[str | None, str, bool]:
    """(background|None, foreground, bold) for a rule-layer badge letter."""
    return _active["badges"].get(letter, (None, _active["text"], False))


def is_dark(app) -> bool:
    """Whether the OS wants a dark UI, by hint if available else by palette."""
    hints = app.styleHints()
    if hasattr(hints, "colorScheme"):
        try:
            from PySide6.QtCore import Qt

            return hints.colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            pass
    window = app.palette().color(QPalette.ColorRole.Window)
    return window.lightness() < 128


def apply(app) -> None:
    """Pick the theme from the OS and paint the whole application.

    Re-applies on an OS light/dark switch where Qt exposes the signal; already-
    drawn badges recolour on their next repopulation, which is acceptable for a
    change that is rare and user-initiated.
    """
    global _active
    _active = DARK if is_dark(app) else LIGHT
    app.setStyleSheet(build_qss(_active))

    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: apply(app))
