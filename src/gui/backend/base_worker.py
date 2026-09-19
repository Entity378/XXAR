import weakref
from typing import Dict, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.core.logger import get_logger

logger = get_logger(__name__)


# Every live WorkerRegistry registers itself here so shutdown_all_workers can join them at app exit.
_registries: "list[weakref.ref]" = []


class BaseWorker(QThread):
    # Shared base for every background QThread in the app.
    # Subclasses implement work(); run() is the never-die-silently backstop that always reports failure.
    error = pyqtSignal(str)
    # Lifecycle signal the registry keys off, kept separate from any domain 'finished' a subclass may declare.
    # Always fires once run() returns, so deleteLater/slot-clear never depend on a shadowed signal name.
    workerFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None

    def work(self):
        raise NotImplementedError

    def run(self):
        try:
            self.work()
        except Exception as e:
            logger.exception("[%s] unhandled worker error", type(self).__name__)
            self.error.emit(str(e))
        finally:
            self.workerFinished.emit()

    def set_process(self, process):
        # Register a child process so cancel() kills it instead of orphaning it.
        self._process = process

    def is_cancelled(self) -> bool:
        return self.isInterruptionRequested()

    def cancel(self):
        # Cooperative cancel: request interruption and terminate any registered child process.
        self.requestInterruption()
        proc = self._process
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                logger.exception("[%s] failed to terminate child process", type(self).__name__)


class FunctionWorker(BaseWorker):
    # Runs an arbitrary callable off the GUI thread; the callable reports its own results/signals.
    # An optional threading.Event is set by cancel() so a function that polls it stops on shutdown too.
    def __init__(self, fn, cancel_event=None, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel_event = cancel_event

    def work(self):
        self._fn()

    def cancel(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
        super().cancel()


class WorkerRegistry(QObject):
    # One per bridge/connector: tracks live workers by name.
    # Guards double-start, frees each on finish (deleteLater + slot clear), and joins them on shutdown.

    def __init__(self, owner_name: str = ""):
        super().__init__()
        self._owner_name = owner_name or "workers"
        self._workers: Dict[str, QThread] = {}
        self._game_lock_holders: set = set()
        _registries.append(weakref.ref(self))

    def is_running(self, name: str) -> bool:
        worker = self._workers.get(name)
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            # The C++ object was already deleted by deleteLater; the Python ref is stale.
            self._workers.pop(name, None)
            return False

    def get(self, name: str) -> Optional[QThread]:
        return self._workers.get(name)

    def start(self, name: str, worker: QThread, holds_game_lock: bool = False) -> bool:
        # Refuse to start over a still-running worker; the caller should report "busy".
        # Returns True if the worker was started.

        # A worker born on another thread cannot be reparented here, so Qt leaves it unowned.
        # Dropping the Python reference then frees a live QThread: qFatal, process gone, no log.
        if QThread.currentThread() is not self.thread():
            logger.error(
                "[%s] worker '%s' started from a foreign thread; it will run unparented",
                self._owner_name,
                name,
            )

        if self.is_running(name):
            logger.debug("[%s] worker '%s' already running; start refused", self._owner_name, name)
            return False
        if holds_game_lock and game_lock_holder(skip_current_thread=False) is not None:
            logger.debug("[%s] worker '%s' refused; game lock held by '%s'", self._owner_name, name, game_lock_holder(False))
            return False
        # Set parent of worker so it doesn't get destroyed while it's still running
        worker.setParent(self)
        worker.setObjectName(name)
        # Let Qt free the C++ object once run() returns, then drop our Python reference.
        # Keyed off workerFinished (not finished) so a subclass that shadows finished still cleans up.
        worker.workerFinished.connect(worker.deleteLater)
        worker.workerFinished.connect(self._on_finished)
        self._workers[name] = worker
        if holds_game_lock:
            self._game_lock_holders.add(name)
        worker.start()
        return True

    def _on_finished(self):
        worker = self.sender()
        if worker is None:
            return
        name = worker.objectName()
        # Only drop the slot if the finished worker is still the one we hold.
        # A stale (superseded) worker must not clear the pointer to the live one.
        if self._workers.get(name) is worker:
            # run() has returned but the thread may not have terminated yet.
            # An unparented worker is owned by this reference alone, so dropping it now would destroy it live.
            worker.wait()
            self._workers.pop(name, None)
            self._game_lock_holders.discard(name)

    def cancel(self, name: str):
        worker = self._workers.get(name)
        if worker is None:
            return
        try:
            worker.cancel() if hasattr(worker, "cancel") else worker.requestInterruption()
        except RuntimeError:
            self._workers.pop(name, None)

    def running_game_lock_holder(self, skip_current_thread: bool = True) -> Optional[str]:
        # A holder never blocks itself: what it calls on its own thread is part of that same operation.
        # Taking the lock ignores that, so a holder's thread can never open a second one.
        current = QThread.currentThread() if skip_current_thread else None
        for name in list(self._game_lock_holders):
            if not self.is_running(name):
                self._game_lock_holders.discard(name)
                continue
            if self._workers.get(name) is not current:
                return name
        return None

    def shutdown(self, timeout_ms: int = 3000):
        # Cancel, quit, and join every live worker so none is destroyed mid-run.
        # A game-file write is never cancelled and is waited out with no deadline: cutting it
        # short would leave a truncated pck in the game folder. Only killing the process stops it.
        for name, worker in list(self._workers.items()):
            try:
                if not worker.isRunning():
                    continue
                if name in self._game_lock_holders:
                    logger.info("[%s] waiting for '%s' to finish writing game files", self._owner_name, name)
                    worker.quit()
                    while not worker.wait(5000):
                        logger.info("[%s] '%s' is still writing, waiting", self._owner_name, name)
                    continue
                worker.cancel() if hasattr(worker, "cancel") else worker.requestInterruption()
                worker.quit()
                if not worker.wait(timeout_ms):
                    logger.warning(
                        "[%s] worker '%s' did not stop within %dms", self._owner_name, name, timeout_ms
                    )
            except RuntimeError:
                pass
        self._workers.clear()
        self._game_lock_holders.clear()


def shutdown_all_workers(timeout_ms: int = 3000):
    # Join every registry's workers; call once from QApplication.aboutToQuit.
    for ref in list(_registries):
        registry = ref()
        if registry is None:
            continue
        try:
            registry.shutdown(timeout_ms)
        except Exception:
            logger.exception("worker registry shutdown failed")


def game_lock_holder(skip_current_thread: bool = True) -> Optional[str]:
    # Name of the live worker holding the game lock, or None.
    # Game switches and game-file writes hold it, so they can never interleave.
    for ref in list(_registries):
        registry = ref()
        if registry is None:
            continue
        name = registry.running_game_lock_holder(skip_current_thread)
        if name is not None:
            return name
    return None
