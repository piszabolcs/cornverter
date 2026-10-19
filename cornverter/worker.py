"""
Background conversion thread for the GUI.

A thin Qt wrapper around `engine.run_tasks`: conversion is disk and CPU
heavy, so it runs on a QThread and reports through signals (progress, log
line, one file done, run finished). `finished_all` is emitted in every case -
even if something unexpected breaks - so the window never stays "running".
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .converters import Options
from .converters.base import ConversionResult, Status, request_cancel, reset_cancel
from .engine import RunOutcome, run_tasks
from .scanner import Task

_LOG_TAG = {
    Status.SUCCESS: "OK",
    Status.FAILED: "FAIL",
    Status.SKIPPED: "SKIP",
    Status.UNSUPPORTED: "N/A",
}


class ConvertWorker(QThread):
    progress = Signal(int, int)       # (done, total)
    file_started = Signal(str)        # source file name
    file_done = Signal(object)        # ConversionResult
    log = Signal(str)                 # log line
    finished_all = Signal(object)     # RunOutcome

    def __init__(self, tasks: list[Task], options: Options, parent=None):
        super().__init__(parent)
        self._tasks = tasks
        self._options = options
        self.outcome = RunOutcome()
        reset_cancel()

    def cancel(self) -> None:
        """Stop after the current file; a running LibreOffice call is killed."""
        request_cancel()
        self.log.emit("Cancel requested - stopping after the current file.")

    def _on_start(self, task: Task) -> None:
        self.file_started.emit(task.source.name)

    def _on_result(self, result: ConversionResult, done: int,
                   total: int) -> None:
        tag = _LOG_TAG.get(result.status, "?")
        extra = f" - {result.message}" if result.message else ""
        self.log.emit(f"[{tag}] {result.source.name}  ({result.engine}, "
                      f"{result.duration_s:.1f}s){extra}")
        self.file_done.emit(result)
        self.progress.emit(done, total)

    def run(self) -> None:
        self.log.emit(f"Conversion started: {len(self._tasks)} file(s).")
        try:
            run_tasks(self._tasks, self._options, on_start=self._on_start,
                      on_result=self._on_result, outcome=self.outcome)
        except Exception as exc:  # noqa: BLE001 - never leave the GUI hanging
            self.log.emit(f"Unexpected error, run stopped: {exc}")
        finally:
            if self.outcome.cancelled:
                self.log.emit(f"Run cancelled: {len(self.outcome.cancelled)} "
                              f"file(s) not processed.")
            self.finished_all.emit(self.outcome)
