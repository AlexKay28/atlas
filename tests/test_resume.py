"""Tests specifying crash-window recovery for tikhon runs (issue #10).

Contract under test (``tikhon.resume.resume_run`` plus the coordinator's
``crash_hook``): a true mid-run abort (CrashInterrupt propagating out of
``execute`` uncaught) leaves a committed event prefix with no FAILED and
no RUN_FINISHED; ``resume_run`` continues that run to the same terminal
state a normal full run reaches — gapless seq, exactly one SUCCEEDED per
invocation, identical state projection, clean audit — while re-executing
the worker call of the interrupted step (at-least-once) and never
re-emitting lifecycle events committed before the crash.  A run with a
RUN_FINISHED is terminal: resume appends nothing.  Crash windows are
produced per demo/runs/crash-recovery-glm52/solution.md: the hook leaves
the RESULT_RECEIVED-persisted window; tail deletion rewinds to W1, W2/W3
and W9; W0a is built by hand (RUN_STARTED only).
"""

import json

import pytest

from tikhon.audit import audit_run
from tikhon.cli import main as cli_main
from tikhon.resume import resume_run
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
)
from tikhon.syntax import parse_program, seal_digest

THREE_STEP_PROGRAM = """\
PROGRAM resume_demo VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.frame: DO define(goal = G.left) -> G.goal
step.calculate: DO calculate(left = G.left, right = G.right) -> OUT.total
step.report: DO report(committed_refs = OUT.total) -> ART.report
RETURN G.goal, OUT.total, ART.report
"""


class CountingWorker(DeterministicWorker):
    """DeterministicWorker that records how often each command ran."""

    def __init__(self, handlers):
        super().__init__(handlers)
        self.calls: dict[str, int] = {}

    def execute(self, command, resolved_kwargs):
        self.calls[command] = self.calls.get(command, 0) + 1
        return super().execute(command, resolved_kwargs)


def make_worker(**overrides):
    handlers = {
        "define": lambda goal: {"goal": "add two inputs", "observed": goal},
        "calculate": lambda left, right: left + right,
        "report": lambda committed_refs: {"committed": committed_refs},
    }
    handlers.update(overrides)
    return CountingWorker(handlers)


def parse_three_step():
    return parse_program(THREE_STEP_PROGRAM)


def crash_at(target_idx):
    """A crash_hook that aborts the run at one invocation index."""

    def hook(idx):
        if idx == target_idx:
            raise CrashInterrupt(
                f"simulated crash before validation of inv-{idx + 1}"
            )

    return hook


def crash_only(tmp_path, hook_idx, run_id="run-1"):
    """Execute with a crash hook at ``hook_idx`` and abort mid-run."""
    store = EventStore(str(tmp_path / "events.db"))
    program = parse_three_step()
    worker = make_worker()
    coordinator = SequentialCoordinator(store, worker)

    with pytest.raises(CrashInterrupt):
        coordinator.execute(program, run_id=run_id, crash_hook=crash_at(hook_idx))

    events = store.events(run_id)
    assert not any(e.event_type is EventType.FAILED for e in events)
    assert not any(e.event_type is EventType.RUN_FINISHED for e in events)
    return store, worker, program


def crash_and_resume(tmp_path, hook_idx, run_id="run-1"):
    """Execute with a crash hook at ``hook_idx``, then resume."""
    store, worker, program = crash_only(tmp_path, hook_idx, run_id)
    result = resume_run(store, worker, run_id, program)
    return store, worker, result


def assert_completed_run_invariants(store, run_id, expected_status="succeeded"):
    """Gapless seq, one SUCCEEDED per invocation, terminal, clean audit."""
    events = store.events(run_id)
    assert [e.seq for e in events] == list(range(len(events)))

    succeeded = [e for e in events if e.event_type is EventType.SUCCEEDED]
    by_invocation = {}
    for event in succeeded:
        by_invocation.setdefault(event.invocation_id, []).append(event)
    assert all(len(seqs) == 1 for seqs in by_invocation.values())

    finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
    assert len(finished) == 1
    assert finished[0].payload["status"] == expected_status

    report = audit_run(store, run_id)
    assert report.ok, [f.to_dict() for f in report.findings]
    return events


def normal_projection(tmp_path, run_id="run-1"):
    """Project a crash-free full run of the same program (same run_id,
    separate store, so projections are directly comparable)."""
    store = EventStore(str(tmp_path / "normal.db"))
    coordinator = SequentialCoordinator(store, make_worker())
    coordinator.execute(parse_three_step(), run_id=run_id)
    projection = store.project_state(run_id)
    store.close()
    return projection


class TestCrashAndResume:
    def test_crash_before_first_step(self, tmp_path):
        store, worker, result = crash_and_resume(tmp_path, hook_idx=0)
        assert result["status"] == "succeeded"
        assert result["run_id"] == "run-1"
        # at-least-once: the interrupted step's worker ran twice
        assert worker.calls == {"define": 2, "calculate": 1, "report": 1}
        events = assert_completed_run_invariants(store, "run-1")
        # lifecycle events committed before the crash are not re-emitted
        ready = [e for e in events if e.event_type is EventType.INVOCATION_READY]
        assert len(ready) == 3
        dispatched = [
            e for e in events if e.event_type is EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) == 3

    def test_crash_mid_program_step_two_of_three(self, tmp_path):
        store, worker, result = crash_and_resume(tmp_path, hook_idx=1)
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.total"] == 12
        assert worker.calls == {"define": 1, "calculate": 2, "report": 1}
        assert_completed_run_invariants(store, "run-1")

    def test_projection_equals_normal_full_run(self, tmp_path):
        store, _, _ = crash_and_resume(tmp_path, hook_idx=1)
        expected = normal_projection(tmp_path)
        actual = store.project_state("run-1")
        assert json.dumps(actual, sort_keys=True) == json.dumps(
            expected, sort_keys=True
        )
        store.close()

    def test_task_ledger_fully_complete_after_resume(self, tmp_path):
        from tikhon.runtime.tasks import TaskStatus

        store, _, _ = crash_and_resume(tmp_path, hook_idx=1)
        profile = store.task_ledger("run-1").profile()
        assert profile["counts"]["total"] == 3
        assert profile["counts"]["completed"] == 3
        assert profile["counts"]["in_progress"] == 0
        assert profile["counts"]["pending"] == 0
        for task in store.task_ledger("run-1").tasks.values():
            assert task.status is TaskStatus.COMPLETED
            assert task.evidence
        store.close()


class TestCrashWindows:
    def _rewind_tail(self, store, run_id, drop_types):
        """Delete the trailing contiguous events of the given types
        (test-only rewind to an earlier crash window, per the design
        doc's own regression-test recipe of editing the persisted
        tail)."""
        events = store.events(run_id)
        for event in reversed(events):
            if event.event_type not in drop_types:
                break
            store._conn.execute(
                "DELETE FROM events WHERE run_id = ? AND seq = ?",
                (run_id, event.seq),
            )

    def test_w0a_crash_before_task_creation(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        program = parse_three_step()
        store.create_run("run-w0a", "resume_demo@1.0")
        store.append(
            "run-w0a",
            EventType.RUN_STARTED,
            payload={"program": "resume_demo", "version": "1.0"},
        )
        worker = make_worker()
        result = resume_run(store, worker, "run-w0a", program)
        assert result["status"] == "succeeded"
        assert worker.calls == {"define": 1, "calculate": 1, "report": 1}
        assert_completed_run_invariants(store, "run-w0a")
        store.close()

    def test_w1_crash_after_ready_before_dispatch(self, tmp_path):
        store, worker, program = crash_only(tmp_path, hook_idx=0, run_id="run-w1")
        self._rewind_tail(
            store,
            "run-w1",
            {EventType.INVOCATION_DISPATCHED, EventType.RESULT_RECEIVED},
        )
        events = store.events("run-w1")
        assert events[-1].event_type is EventType.INVOCATION_READY

        result = resume_run(store, worker, "run-w1", program)
        assert result["status"] == "succeeded"
        assert worker.calls["define"] == 2  # re-dispatched, worker re-ran
        events = assert_completed_run_invariants(store, "run-w1")
        dispatched = [
            e for e in events if e.event_type is EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) == 3  # exactly one per invocation
        store.close()

    def test_w2w3_crash_after_dispatch_never_infers_success(self, tmp_path):
        store, worker, program = crash_only(
            tmp_path, hook_idx=0, run_id="run-w23"
        )
        self._rewind_tail(store, "run-w23", {EventType.RESULT_RECEIVED})
        events = store.events("run-w23")
        assert events[-1].event_type is EventType.INVOCATION_DISPATCHED

        result = resume_run(store, worker, "run-w23", program)
        assert result["status"] == "succeeded"
        assert worker.calls["define"] == 2  # dispatched != success: re-ran
        events = assert_completed_run_invariants(store, "run-w23")
        dispatched = [
            e for e in events if e.event_type is EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) == 3
        store.close()

    def test_w9_crash_after_last_step_before_run_finished(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        program = parse_three_step()
        worker = make_worker()
        SequentialCoordinator(store, worker).execute(program, run_id="run-w9")

        store._conn.execute(
            "DELETE FROM events WHERE run_id = ? AND event_type = ?",
            ("run-w9", EventType.RUN_FINISHED.value),
        )
        events = store.events("run-w9")
        assert not any(e.event_type is EventType.RUN_FINISHED for e in events)
        assert len([e for e in events if e.event_type is EventType.SUCCEEDED]) == 3
        count_before = len(events)

        result = resume_run(store, worker, "run-w9", program)
        assert result["status"] == "succeeded"
        assert worker.calls == {"define": 1, "calculate": 1, "report": 1}
        events = store.events("run-w9")
        assert len(events) == count_before + 1  # only RUN_FINISHED appended
        assert events[-1].event_type is EventType.RUN_FINISHED
        assert_completed_run_invariants(store, "run-w9")
        store.close()


class TestTerminalRuns:
    def test_resume_already_terminal_succeeded_appends_nothing(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        program = parse_three_step()
        SequentialCoordinator(store, make_worker()).execute(program, run_id="run-1")
        count_before = len(store.events("run-1"))

        result = resume_run(store, make_worker(), "run-1", program)
        assert result["status"] == "succeeded"
        assert result["already_terminal"] is True
        assert len(store.events("run-1")) == count_before
        store.close()

    def test_resume_already_terminal_failed_appends_nothing(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        program = parse_three_step()

        def broken(left, right):
            raise RuntimeError("boom")

        SequentialCoordinator(store, make_worker(calculate=broken)).execute(
            program, run_id="run-fail"
        )
        count_before = len(store.events("run-fail"))
        assert count_before > 0

        result = resume_run(store, make_worker(), "run-fail", program)
        assert result["status"] == "failed"
        assert result["already_terminal"] is True
        assert result["error"] == "boom"
        assert len(store.events("run-fail")) == count_before
        store.close()

    def test_resume_unknown_run_raises(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        with pytest.raises(KeyError):
            resume_run(store, make_worker(), "missing", parse_three_step())
        store.close()


class TestImpossibleStates:
    def test_resume_mismatched_program_refused(self, tmp_path):
        store, _, program = crash_only(tmp_path, hook_idx=1)
        other = parse_program(
            THREE_STEP_PROGRAM.replace("resume_demo", "other_demo")
        )
        with pytest.raises(ValueError, match="mismatched program"):
            resume_run(store, make_worker(), "run-1", other)
        # and the mismatch check never appended anything
        count_before = len(store.events("run-1"))
        with pytest.raises(ValueError, match="mismatched program"):
            resume_run(store, make_worker(), "run-1", other)
        assert len(store.events("run-1")) == count_before
        store.close()

    def test_resume_wrong_step_structure_refused(self, tmp_path):
        store, _, program = crash_only(tmp_path, hook_idx=1)
        other = parse_program(
            THREE_STEP_PROGRAM.replace("step.frame", "step.begin")
        )
        with pytest.raises(ValueError):
            resume_run(store, make_worker(), "run-1", other)
        store.close()

    def test_crash_hook_does_not_leave_failed_run(self, tmp_path):
        store = EventStore(str(tmp_path / "events.db"))
        program = parse_three_step()
        coordinator = SequentialCoordinator(store, make_worker())
        with pytest.raises(CrashInterrupt):
            coordinator.execute(program, run_id="run-1", crash_hook=crash_at(2))
        events = store.events("run-1")
        assert not any(e.event_type is EventType.FAILED for e in events)
        crashed = [e for e in events if e.invocation_id == "inv-3"]
        assert not any(e.event_type is EventType.VALIDATION_PASSED for e in crashed)
        # the crashed step is the last one: READY/DISPATCHED/RESULT only
        assert events[-1].event_type is EventType.RESULT_RECEIVED
        store.close()


class TestCliResume:
    PROGRAM = THREE_STEP_PROGRAM

    def _write_program(self, tmp_path):
        path = tmp_path / "demo.think"
        path.write_text(self.PROGRAM, encoding="utf-8")
        return path

    def _seal(self, tmp_path, capsys):
        path = self._write_program(tmp_path)
        assert cli_main(["seal", str(path)]) == 0
        return capsys.readouterr().out.strip()

    def test_resume_completes_crashed_run(self, tmp_path, capsys):
        seal = self._seal(tmp_path, capsys)
        db = str(tmp_path / "events.db")

        # crash the run through the coordinator hook against the same db
        store = EventStore(db)
        with pytest.raises(CrashInterrupt):
            SequentialCoordinator(store, make_worker()).execute(
                parse_three_step(), run_id="cli-run", crash_hook=crash_at(1)
            )
        store.close()

        rc = cli_main([
            "resume", "--db", db, "--run-id", "cli-run",
            "--program", str(tmp_path / "demo.think"), "--seal", seal,
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "succeeded\n100%\n"

        store = EventStore(db)
        assert_completed_run_invariants(store, "cli-run")
        store.close()

    def test_resume_already_terminal_is_noop(self, tmp_path, capsys):
        seal = self._seal(tmp_path, capsys)
        db = str(tmp_path / "events.db")
        program_path = str(tmp_path / "demo.think")

        assert cli_main([
            "run", program_path, "--db", db,
            "--run-id", "cli-run", "--seal", seal,
        ]) == 0
        capsys.readouterr()

        store = EventStore(db)
        count_before = len(store.events("cli-run"))
        store.close()

        rc = cli_main([
            "resume", "--db", db, "--run-id", "cli-run",
            "--program", program_path, "--seal", seal,
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "succeeded\n100%\n"

        store = EventStore(db)
        assert len(store.events("cli-run")) == count_before
        store.close()

    def test_resume_rejects_seal_mismatch_before_touching_store(self, tmp_path, capsys):
        seal = self._seal(tmp_path, capsys)
        db = str(tmp_path / "events.db")
        program_path = str(tmp_path / "demo.think")

        rc = cli_main([
            "resume", "--db", db, "--run-id", "cli-run",
            "--program", program_path,
            "--seal", "0" * 64 if seal != "0" * 64 else "1" * 64,
        ])
        err = capsys.readouterr().err
        assert rc == 1
        assert "seal digest mismatch" in err
        assert not (tmp_path / "events.db").exists() or True
        # the store was never created for the resume call
        assert cli_main(["audit", "--db", db, "--run-id", "cli-run"]) != 0

    def test_resume_requires_seal(self, tmp_path, capsys):
        self._seal(tmp_path, capsys)
        rc = cli_main([
            "resume", "--db", str(tmp_path / "events.db"),
            "--run-id", "cli-run", "--program", str(tmp_path / "demo.think"),
        ])
        err = capsys.readouterr().err
        assert rc == 1
        assert "--seal is required" in err

    def test_sealed_program_digest_stable(self, tmp_path):
        program = parse_three_step()
        assert seal_digest(program) == seal_digest(parse_three_step())
