"""Tests for the new arm kinds and fault-injection types in tahoe.eval.

Follows the deterministic fake-worker pattern from tests/test_eval.py:
no live-model dependency, every run goes through the ONE entry point
(run_pilot) or through ArmSpec validation.

Covers:

- All 6 arm kinds are valid ArmSpec kinds
- Invalid arm kind raises ValueError
- ArmSpec.protocol_dir (str | None, default None)
- FaultInjectionMode enum members
- run_pilot fault_injection / fault_fraction parameters and defaults
- chain_of_draft arm runs on the deterministic scaffold worker
- structured_nl arm runs on the deterministic scaffold worker
- tahoe_learned arm collects .think protocols into usage
- tahoe_parallel arm passes max_workers > 1 to the coordinator
"""

import inspect

import tahoe.eval as eval_module
import pytest

from tahoe.eval import (
    ArmSpec,
    FaultInjectionMode,
    PilotReport,
    TaskManifest,
    run_pilot,
)

ALL_KINDS = (
    "react",
    "chain_of_draft",
    "structured_nl",
    "tahoe",
    "tahoe_learned",
    "tahoe_parallel",
)

_SIMPLE_PROGRAM = (
    "PROGRAM simple VERSION 1.0\n"
    "INPUT\n"
    '    G.task = "Return the order status for order 42"\n'
    "step.understand: DO define(request = G.task) -> P.goal\n"
    'step.report: DO report(committed_refs = P.goal, format = "json") -> OUT.answer\n'
    "RETURN OUT.answer\n"
)

_SIMPLE_TASK = TaskManifest(
    task_id="simple-001",
    description="Return the order status for order 42",
    expected_state={"status": "confirmed"},
    program_source=_SIMPLE_PROGRAM,
    authoring_attempts_expected=0,
)


# -- 1. All 6 arm kinds are valid --------------------------------------


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_all_arm_kinds_are_valid(kind):
    arm = ArmSpec(name=f"arm-{kind}", kind=kind)
    assert arm.kind == kind


# -- 2. Invalid arm kind raises ValueError ------------------------------


def test_arm_spec_rejects_invalid_kind():
    with pytest.raises(ValueError, match="kind"):
        ArmSpec(name="bad", kind="bogus_kind")


# -- 3. ArmSpec.protocol_dir -------------------------------------------


def test_arm_spec_protocol_dir_defaults_to_none():
    assert ArmSpec(name="a", kind="react").protocol_dir is None


def test_arm_spec_accepts_protocol_dir_str():
    arm = ArmSpec(
        name="learned", kind="tahoe_learned", protocol_dir="/tmp/protocols"
    )
    assert arm.protocol_dir == "/tmp/protocols"


# -- 4. FaultInjectionMode enum ----------------------------------------


def test_fault_injection_mode_has_six_members():
    expected = {
        "none",
        "transport_failure",
        "process_loss",
        "delayed_results",
        "stale_submission",
        "lease_expiry",
    }
    members = {m.name: m.value for m in FaultInjectionMode}
    assert len(members) == 6
    assert set(members) == expected
    # Each member's value is its lowercase name string.
    for name, value in members.items():
        assert value == name


@pytest.mark.parametrize(
    "name",
    [
        "none",
        "transport_failure",
        "process_loss",
        "delayed_results",
        "stale_submission",
        "lease_expiry",
    ],
)
def test_fault_injection_mode_lookup_by_value(name):
    assert FaultInjectionMode(name).name == name


# -- 5. run_pilot fault-injection parameters ----------------------------


def test_run_pilot_fault_params_defaults():
    sig = inspect.signature(run_pilot)
    fi = sig.parameters["fault_injection"]
    ff = sig.parameters["fault_fraction"]
    assert fi.default is FaultInjectionMode.none
    assert ff.default == 0.0


def test_run_pilot_accepts_fault_injection_and_fraction():
    report = run_pilot(
        [_SIMPLE_TASK],
        [ArmSpec(name="react-baseline", kind="react")],
        fault_injection=FaultInjectionMode.transport_failure,
        fault_fraction=0.5,
    )
    assert isinstance(report, PilotReport)
    assert len(report.trials) == 1


def test_run_pilot_coerces_fault_injection_string():
    """A plain string mode is coerced into the enum."""
    report = run_pilot(
        [_SIMPLE_TASK],
        [ArmSpec(name="react-baseline", kind="react")],
        fault_injection="process_loss",
        fault_fraction=0.0,
    )
    assert len(report.trials) == 1


def test_run_pilot_rejects_unknown_fault_injection():
    with pytest.raises(ValueError):
        run_pilot(
            [_SIMPLE_TASK],
            [ArmSpec(name="react-baseline", kind="react")],
            fault_injection="bogus_mode",
        )


def test_run_pilot_rejects_fault_fraction_out_of_range():
    with pytest.raises(ValueError, match="fault_fraction"):
        run_pilot(
            [_SIMPLE_TASK],
            [ArmSpec(name="react-baseline", kind="react")],
            fault_fraction=1.5,
        )


def test_run_pilot_rejects_negative_fault_fraction():
    with pytest.raises(ValueError, match="fault_fraction"):
        run_pilot(
            [_SIMPLE_TASK],
            [ArmSpec(name="react-baseline", kind="react")],
            fault_fraction=-0.1,
        )


# -- 6. chain_of_draft arm runs on the deterministic fake worker --------


def test_chain_of_draft_arm_runs():
    arm = ArmSpec(name="cod-arm", kind="chain_of_draft")
    report = run_pilot([_SIMPLE_TASK], [arm])
    assert isinstance(report, PilotReport)
    assert [a.kind for a in report.arms] == ["chain_of_draft"]
    assert len(report.trials) == 1
    trial = report.trials[0]
    assert trial.arm == "cod-arm"
    assert trial.task_id == "simple-001"
    assert trial.result.passed
    assert trial.result.failure_class == "succeeded"


def test_chain_of_draft_arm_full_battery_succeeds():
    tasks = [_SIMPLE_TASK]
    arms = [
        ArmSpec(name="cod-arm", kind="chain_of_draft"),
        ArmSpec(name="react-baseline", kind="react"),
    ]
    report = run_pilot(tasks, arms)
    assert len(report.trials) == 2  # 1 task x 2 arms
    assert all(t.result.passed for t in report.trials)


# -- 7. structured_nl arm runs on the deterministic fake worker ---------


def test_structured_nl_arm_runs():
    arm = ArmSpec(name="snl-arm", kind="structured_nl")
    report = run_pilot([_SIMPLE_TASK], [arm])
    assert isinstance(report, PilotReport)
    assert [a.kind for a in report.arms] == ["structured_nl"]
    assert len(report.trials) == 1
    trial = report.trials[0]
    assert trial.arm == "snl-arm"
    assert trial.result.passed
    assert trial.result.failure_class == "succeeded"


# -- 8. tahoe_learned collects .think protocols into usage --------------


def test_tahoe_learned_collects_think_protocols(tmp_path):
    (tmp_path / "alpha.think").write_text("PROGRAM alpha VERSION 1.0\n")
    (tmp_path / "beta.think").write_text("PROGRAM beta VERSION 1.0\n")
    (tmp_path / "notes.txt").write_text("not a protocol")

    arm = ArmSpec(
        name="learned-arm", kind="tahoe_learned", protocol_dir=str(tmp_path)
    )
    report = run_pilot([_SIMPLE_TASK], [arm])
    assert len(report.trials) == 1
    trial = report.trials[0]
    assert trial.result.passed

    expected = sorted(
        [str(tmp_path / "alpha.think"), str(tmp_path / "beta.think")]
    )
    assert trial.usage["available_protocols"] == expected
    assert len(trial.usage["available_protocols"]) == 2


def test_tahoe_learned_without_protocol_dir_has_no_protocols_key():
    arm = ArmSpec(name="learned-arm", kind="tahoe_learned")
    report = run_pilot([_SIMPLE_TASK], [arm])
    trial = report.trials[0]
    assert trial.result.passed
    assert "available_protocols" not in trial.usage


# -- 9. tahoe_parallel respects max_workers > 1 -------------------------


def test_tahoe_parallel_respects_max_workers(monkeypatch):
    """max_workers > 1 flows from ArmSpec through to coordinator.execute."""
    captured = {}
    real_coordinator = eval_module.SequentialCoordinator

    class SpyCoordinator(real_coordinator):
        def execute(self, program, **kwargs):
            captured["max_workers"] = kwargs.get("max_workers")
            return super().execute(program, **kwargs)

    monkeypatch.setattr(eval_module, "SequentialCoordinator", SpyCoordinator)

    arm = ArmSpec(name="parallel-arm", kind="tahoe_parallel", max_workers=3)
    report = run_pilot([_SIMPLE_TASK], [arm])

    assert captured["max_workers"] == 3
    assert len(report.trials) == 1
    trial = report.trials[0]
    assert trial.arm == "parallel-arm"
    assert trial.result.passed
    assert trial.result.failure_class == "succeeded"


def test_tahoe_parallel_arm_runs_end_to_end():
    """tahoe_parallel with max_workers=2 completes a pilot green."""
    arm = ArmSpec(name="parallel-arm", kind="tahoe_parallel", max_workers=2)
    report = run_pilot([_SIMPLE_TASK], [arm])
    assert len(report.trials) == 1
    assert all(t.result.passed for t in report.trials)
