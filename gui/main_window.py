"""Main application window (Ledger theme).

Layout per DESIGN_SPEC.md §2: fixed 5:2 landscape aspect ratio, horizontal
bands — left Rules rail, center Tree/Preview with the Sorting Rail, right
collapsible Details panel, and a fixed status bar (dry-run, progress, undo,
apply).

STUB: wires up the window shell and delegates the pipeline to Organizer.
Widget internals and the QSS/animation work are TODO.
"""

from __future__ import annotations

# Fixed geometry from DESIGN_SPEC.md §2.
ASPECT_RATIO = 0.4  # height = 0.4 * width
DEFAULT_SIZE = (1440, 576)
MINIMUM_SIZE = (1100, 440)


def run(argv: list[str]) -> int:
    """Create the QApplication, show the main window, and run the event loop."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - dependency not installed yet
        raise SystemExit(
            "PySide6 is not installed. Run: pip install -r requirements.txt"
        ) from exc

    app = QApplication(argv)
    window = MainWindow()
    window.show()
    return app.exec()


class MainWindow:  # pragma: no cover - GUI stub
    """Top-level window. TODO: subclass QMainWindow and build the three bands.

    Responsibilities once implemented:
      * host the Rules rail, Preview tree, and Details panel;
      * lock height to ``ASPECT_RATIO * width`` on resize (DESIGN_SPEC §2);
      * drive :class:`~organizer.Organizer` and render its
        plan into the preview tree, applying only on user approval.
    """

    def __init__(self) -> None:
        raise NotImplementedError("MainWindow layout not yet implemented")

    def show(self) -> None:
        raise NotImplementedError
