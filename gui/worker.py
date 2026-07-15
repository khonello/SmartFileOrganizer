"""Off-thread execution for the blocking parts of the pipeline.

``Organizer.build_plan`` and ``apply`` are synchronous loops over the
filesystem. Run on the UI thread they freeze the window solid on any real
folder, so both go through here. This is structural, not polish — see
``UI_STRUCTURE.md``.

``core``/``organizer`` know nothing about Qt; this module is the seam.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    """Runs one callable off the UI thread and reports back via signals.

    Signals are delivered to the UI thread by Qt's queued connections, which is
    what makes ``progress`` safe to emit from inside the worker.
    """

    progress = Signal(int, int)  # (done, total)
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        fn: Callable[..., object],
        *,
        wants_progress: bool = False,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._fn = fn
        self._wants_progress = wants_progress

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = (
                self._fn(self.progress.emit) if self._wants_progress else self._fn()
            )
        except Exception as exc:  # surfaced in the UI rather than killing the app
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(result)
