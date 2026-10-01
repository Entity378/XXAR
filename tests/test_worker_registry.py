import threading
import time
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent

from src.gui.backend import base_worker
from src.gui.backend.base_worker import (
    BaseWorker,
    FunctionWorker,
    WorkerRegistry,
    game_lock_holder,
    game_write_state,
    shutdown_all_workers,
)
from helpers import record_signal, wait_until

GATE_TIMEOUT_SECONDS = 10


@pytest.fixture
def workers(qapp, monkeypatch):
    # Each test gets fresh module state, so no registry from another test can hold the game lock.
    monkeypatch.setattr(base_worker, "_registries", [])
    monkeypatch.setattr(base_worker, "_game_write_state", None)
    registries = []
    gates = []

    def make_registry(owner_name="tests"):
        registry = WorkerRegistry(owner_name)
        registries.append(registry)
        return registry

    def make_gate():
        gate = threading.Event()
        gates.append(gate)
        return gate

    yield SimpleNamespace(registry=make_registry, gate=make_gate)
    for gate in gates:
        gate.set()
    for registry in registries:
        registry.shutdown(timeout_ms=5000)
    QCoreApplication.processEvents()


def gated_worker(gate):
    return FunctionWorker(lambda: gate.wait(GATE_TIMEOUT_SECONDS))


class PollingWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        self.saw_cancel = None

    def work(self):
        deadline = time.monotonic() + GATE_TIMEOUT_SECONDS
        while not self.is_cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.saw_cancel = self.is_cancelled()


class FailingWorker(BaseWorker):
    def work(self):
        raise ValueError("pck header is truncated")


class FakeChildProcess:
    def __init__(self, still_running):
        self.still_running = still_running
        self.terminate_calls = 0

    def poll(self):
        return None if self.still_running else 0

    def terminate(self):
        self.terminate_calls += 1


def test_function_worker_runs_off_the_gui_thread(workers):
    registry = workers.registry()
    observed_threads = []
    worker = FunctionWorker(lambda: observed_threads.append(threading.get_ident()))
    finished = record_signal(worker.workerFinished)
    errors = record_signal(worker.error)
    assert registry.start("job", worker)
    assert wait_until(lambda: registry.get("job") is None)
    assert len(observed_threads) == 1
    assert observed_threads[0] != threading.get_ident()
    assert len(finished) == 1
    assert errors == []


def test_exception_in_work_is_reported_and_still_finishes(workers):
    registry = workers.registry()
    worker = FailingWorker()
    errors = record_signal(worker.error)
    finished = record_signal(worker.workerFinished)
    assert registry.start("failing", worker)
    assert wait_until(lambda: registry.get("failing") is None)
    assert errors == [("pck header is truncated",)]
    assert len(finished) == 1


def test_base_worker_without_work_reports_an_error(workers):
    registry = workers.registry()
    worker = BaseWorker()
    errors = record_signal(worker.error)
    assert registry.start("abstract", worker)
    assert wait_until(lambda: registry.get("abstract") is None)
    assert len(errors) == 1


def test_start_refuses_a_second_worker_with_the_same_name(workers):
    registry = workers.registry()
    gate = workers.gate()
    second_worker_ran = []
    assert registry.start("apply", gated_worker(gate))
    assert registry.is_running("apply")
    assert not registry.start("apply", FunctionWorker(lambda: second_worker_ran.append(True)))
    assert registry.start("other", FunctionWorker(lambda: None))
    gate.set()
    assert wait_until(lambda: not registry.is_running("apply"))
    assert second_worker_ran == []
    assert registry.start("apply", FunctionWorker(lambda: second_worker_ran.append(True)))
    assert wait_until(lambda: second_worker_ran == [True])


def test_finished_worker_is_released_and_deleted(workers):
    registry = workers.registry()
    worker = FunctionWorker(lambda: None)
    assert registry.start("job", worker)
    assert registry.get("job") is worker
    assert worker.parent() is registry
    assert worker.objectName() == "job"
    assert wait_until(lambda: registry.get("job") is None)
    assert not registry.is_running("job")
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert sip.isdeleted(worker)


def test_only_one_game_lock_holder_across_registries(workers):
    browser_registry = workers.registry("browser")
    mod_manager_registry = workers.registry("mod_manager")
    gate = workers.gate()
    assert browser_registry.start("apply_changes", gated_worker(gate), holds_game_lock=True)
    assert game_lock_holder() == "apply_changes"
    assert not mod_manager_registry.start("apply_mods", FunctionWorker(lambda: None), holds_game_lock=True)
    assert not browser_registry.start("reset_changes", FunctionWorker(lambda: None), holds_game_lock=True)
    assert mod_manager_registry.start("refresh_list", FunctionWorker(lambda: None))
    gate.set()
    assert wait_until(lambda: game_lock_holder() is None)
    assert mod_manager_registry.start("apply_mods", FunctionWorker(lambda: None), holds_game_lock=True)


def test_game_lock_holder_ignores_its_own_thread_unless_asked(workers):
    registry = workers.registry()
    seen_from_holder_thread = {}

    def record_lock_state():
        seen_from_holder_thread["skipping_current"] = game_lock_holder()
        seen_from_holder_thread["not_skipping"] = game_lock_holder(skip_current_thread=False)
        seen_from_holder_thread["registry_view"] = registry.running_game_lock_holder()

    assert registry.start("switch_game", FunctionWorker(record_lock_state), holds_game_lock=True)
    assert wait_until(lambda: registry.get("switch_game") is None)
    assert seen_from_holder_thread == {"skipping_current": None, "not_skipping": "switch_game", "registry_view": None}


def test_game_lock_holder_sees_the_holder_from_the_gui_thread(workers):
    registry = workers.registry()
    gate = workers.gate()
    assert registry.start("install_mod", gated_worker(gate), holds_game_lock=True)
    assert game_lock_holder() == "install_mod"
    assert game_lock_holder(skip_current_thread=False) == "install_mod"
    assert registry.running_game_lock_holder() == "install_mod"
    gate.set()


def test_game_write_state_tracks_lock_holders(workers):
    registry = workers.registry()
    gate = workers.gate()
    write_state = game_write_state()
    busy_changes = record_signal(write_state.busyChanged)
    assert write_state.busy is False
    assert registry.start("plain_job", FunctionWorker(lambda: None))
    assert write_state.busy is False
    assert busy_changes == []
    assert registry.start("apply_mods", gated_worker(gate), holds_game_lock=True)
    assert write_state.busy is True
    assert len(busy_changes) == 1
    gate.set()
    assert wait_until(lambda: write_state.busy is False)
    assert len(busy_changes) == 2


def test_game_write_state_is_a_qml_property(workers):
    write_state = game_write_state()
    assert game_write_state() is write_state
    assert write_state.property("busy") is False


def test_refused_lock_start_does_not_flip_busy(workers):
    first_registry = workers.registry()
    second_registry = workers.registry()
    gate = workers.gate()
    assert first_registry.start("apply_mods", gated_worker(gate), holds_game_lock=True)
    busy_changes = record_signal(game_write_state().busyChanged)
    assert not second_registry.start("switch_game", FunctionWorker(lambda: None), holds_game_lock=True)
    assert game_write_state().busy is True
    assert busy_changes == []


def test_on_done_runs_with_the_lock_free_before_a_queued_write_can_take_it(workers):
    # A GameBanana install waiting in its queue starts on busyChanged, as soon as the lock is free.
    registry = workers.registry()
    queue_registry = workers.registry()
    gate = workers.gate()
    queued_gate = workers.gate()
    events = []

    def start_queued_write():
        if not game_write_state().busy and "queued write started" not in events:
            queue_registry.start("install", gated_worker(queued_gate), holds_game_lock=True)
            events.append("queued write started")

    game_write_state().busyChanged.connect(start_queued_write)
    assert registry.start("apply", gated_worker(gate), holds_game_lock=True, on_done=lambda: events.append(("on_done", game_lock_holder())))
    gate.set()

    assert wait_until(lambda: "queued write started" in events)
    assert events == [("on_done", None), "queued write started"]


def test_start_write_refused_by_the_lock_notifies_and_drops_on_done(workers):
    first_registry = workers.registry()
    second_registry = workers.registry()
    gate = workers.gate()
    notified = []
    completions = []

    def notify(*dialog):
        notified.append(dialog)

    assert first_registry.start_write("apply", gated_worker(gate), notify)
    assert not second_registry.start_write("export", FunctionWorker(lambda: None), notify, on_done=lambda: completions.append("export"))
    gate.set()

    assert wait_until(lambda: game_lock_holder(False) is None)
    assert [dialog[0] for dialog in notified] == ["Operation In Progress"]
    assert completions == []


def test_a_failing_on_done_still_releases_busy(workers):
    registry = workers.registry()

    def broken_completion():
        raise RuntimeError("completion failed")

    assert registry.start("apply", FunctionWorker(lambda: None), holds_game_lock=True, on_done=broken_completion)

    assert wait_until(lambda: game_write_state().busy is False and not registry.is_running("apply"))


def test_cancel_sets_the_function_worker_cancel_event(workers):
    registry = workers.registry()
    cancel_event = threading.Event()
    wait_results = []
    worker = FunctionWorker(lambda: wait_results.append(cancel_event.wait(GATE_TIMEOUT_SECONDS)), cancel_event=cancel_event)
    assert registry.start("download", worker)
    registry.cancel("download")
    assert wait_until(lambda: registry.get("download") is None)
    assert wait_results == [True]


def test_cancel_reaches_a_polling_worker(workers):
    registry = workers.registry()
    worker = PollingWorker()
    assert registry.start("scan", worker)
    registry.cancel("scan")
    assert wait_until(lambda: registry.get("scan") is None)
    assert worker.saw_cancel is True


def test_cancel_unknown_name_is_a_noop(workers):
    workers.registry().cancel("never_started")


@pytest.mark.parametrize("still_running, expected_terminate_calls", [(True, 1), (False, 0)])
def test_cancel_terminates_a_live_child_process(workers, still_running, expected_terminate_calls):
    worker = FunctionWorker(lambda: None)
    child_process = FakeChildProcess(still_running)
    worker.set_process(child_process)
    worker.cancel()
    assert child_process.terminate_calls == expected_terminate_calls


def test_shutdown_cancels_and_joins_running_workers(workers):
    registry = workers.registry()
    polling_worker = PollingWorker()
    cancel_event = threading.Event()
    function_worker = FunctionWorker(lambda: cancel_event.wait(GATE_TIMEOUT_SECONDS), cancel_event=cancel_event)
    assert registry.start("scan", polling_worker)
    assert registry.start("download", function_worker)
    started_at = time.monotonic()
    registry.shutdown(timeout_ms=5000)
    assert time.monotonic() - started_at < 5
    assert polling_worker.isFinished()
    assert function_worker.isFinished()
    assert polling_worker.saw_cancel is True
    assert cancel_event.is_set()
    assert registry.get("scan") is None
    assert registry.get("download") is None


def test_shutdown_never_cancels_a_game_write(workers):
    registry = workers.registry()
    gate = workers.gate()
    write_state = {}

    class GameWriteWorker(BaseWorker):
        def work(self):
            gate.wait(GATE_TIMEOUT_SECONDS)
            write_state["cancelled"] = self.is_cancelled()

    worker = GameWriteWorker()
    assert registry.start("apply_mods", worker, holds_game_lock=True)
    release_timer = threading.Timer(0.3, gate.set)
    release_timer.start()
    registry.shutdown(timeout_ms=10)
    release_timer.join()
    assert worker.isFinished()
    assert write_state == {"cancelled": False}
    assert game_lock_holder() is None


def test_shutdown_all_workers_joins_every_registry(workers):
    first_worker = PollingWorker()
    second_worker = PollingWorker()
    assert workers.registry("first").start("scan", first_worker)
    assert workers.registry("second").start("scan", second_worker)
    shutdown_all_workers(timeout_ms=5000)
    assert first_worker.isFinished()
    assert second_worker.isFinished()
    assert first_worker.saw_cancel is True
    assert second_worker.saw_cancel is True


def test_registries_register_themselves_for_shutdown(workers):
    registry = workers.registry()
    assert any(reference() is registry for reference in base_worker._registries)
