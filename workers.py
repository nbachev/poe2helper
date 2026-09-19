"""Мелкая обвязка для фоновых задач, чтобы UI не подвисал на сети."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


# Пока задача жива, держим на неё ссылку: иначе Qt успеет удалить
# объект с сигналами раньше, чем очередь доставит результат в UI-поток.
_ACTIVE: set["Worker"] = set()


class Worker(QRunnable):
    """Запускает функцию в пуле потоков и отдаёт результат сигналом."""

    def __init__(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        if self.kwargs.pop("_with_progress", False):
            self.kwargs["progress"] = self.signals.progress.emit

    @Slot()
    def run(self) -> None:  # pragma: no cover - поток
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            log.error("Фоновая задача упала: %s\n%s", exc, traceback.format_exc())
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


def run_async(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    with_progress: bool = False,
    *args,
    **kwargs,
) -> Worker:
    if with_progress:
        kwargs["_with_progress"] = True
    worker = Worker(fn, *args, **kwargs)
    if on_done:
        worker.signals.finished.connect(on_done)
    if on_error:
        worker.signals.failed.connect(on_error)
    if on_progress:
        worker.signals.progress.connect(on_progress)

    _ACTIVE.add(worker)
    worker.signals.finished.connect(lambda *_: _ACTIVE.discard(worker))
    worker.signals.failed.connect(lambda *_: _ACTIVE.discard(worker))

    QThreadPool.globalInstance().start(worker)
    return worker
