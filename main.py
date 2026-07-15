"""Application entry point.

Run with ``python main.py``. Kept import-light at module load so the ``core``
logic can be imported and tested without pulling in Qt — the GUI import happens
inside :func:`main`.
"""

import sys


def main() -> int:
    """Launch the GUI application."""
    from gui.main_window import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
