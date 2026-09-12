"""Protocol A/B evaluation pilot scaffolding (issue #47, methodology #50).

Builds on the #46 benchmark harness to provide an arm runner for
controlled A/B comparisons of ATLAS vs plain agent (ReAct) execution.
The pilot scaffolding is deterministic-testable with fake workers and
graders; live model runs are the orchestrator's post-merge step through
``ATLAS_*`` environment configuration.

Key types:

- :class:`ArmSpec` — names an arm and its kind (``"react"`` or
  ``"atlas"``).  ``react`` is the plain tool-loop baseline prompt; the
  model runs unconstrained.  ``atlas`` is the sealed-program arm where
  the program is authored IN-LOOP by the model under test, and every
  authoring attempt is COUNTED as a charged step per #50's
  authoring-parity clause.
- :class:`TrialRecord` — a durable per-trial record (task id, arm name,
  result, failure class, usage dict, wall time, authoring attempts,
  event-store reference) that is JSON-serializable and roundtrips.
- :func:`run_pilot` — executes a manifest of tasks across arms with
  the given model/worker configuration and returns a
  :class:`PilotReport` with per-task results and a
  :meth:`PilotReport.to_json` / :meth:`PilotReport.to_markdown` pair
  mirroring #46's report pattern.
- :class:`ProgrammaticGrader` — the grader interface: a callable that
  receives the final state/result of a trial and returns a boolean
  pass/fail plus an optional detail string.  The documented example
  grader is a tau-bench-style DB-state matcher
  (:class:`DBStateGrader`).

Authoring parity (#50 section 4):

Every arm uses the same model/version, tools, environment, grader and
resource ceilings.  The ``"atlas"`` arm's program is authored IN-LOOP
by the model under test through the T3 authoring loop (``delegate``);
each authoring attempt is charged as a step.  The ``"react"`` arm gets
a plain tool-loop baseline prompt with no sealed-program scaffolding.
Both arms' usage (tokens, cost, wall) is recorded on the same
:class:`TrialRecord` shape for direct comparison.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from atlas.budgets import ExecutionBudget
from atlas.registry import builtin_registry
from atlas.runtime import EventStore, SequentialCoordinator
from atlas.runtime.coordinator import DeterministicWorker
from atlas.syntax import parse_program

__all__ = [
    "ArmKind",
    "ArmSpec",
    "DBStateGrader",
    "PilotReport",
    "ProgrammaticGrader",
    "TaskManifest",
    "TrialRecord",
    "TrialResult",
    "run_pilot",
]


ArmKind = str  # "react" | "atlas"


@dataclasses.dataclass(frozen=True)
class ArmSpec:
    """One experimental arm in an A/B pilot.

    ``name`` is a short identifier (e.g. ``"react-baseline"``).
    ``kind`` is ``"react"`` (plain tool-loop baseline prompt) or
    ``"atlas"`` (sealed-program arm; authoring attempts via the T3
    authoring loop COUNTED as charged steps per #50's authoring-parity
    clause).
    ``worker_factory`` builds the worker for this arm; ``None`` uses a
    deterministic sleep-simulated worker (the scaffold path).
    ``prompt_template`` is an optional override for the react arm's
    system prompt (the atlas arm derives its program from the task
    manifest).
    ``max_workers`` and ``budget`` configure execution parallelism for
    the arm (defaults: 1 worker, no budget cap — the pilot measures
    sequential execution for both arms to isolate language effects).
    """

    name: str
    kind: ArmKind
    worker_factory: Callable[[], Any] | None = None
    prompt_template: str | None = None
    max_workers: int = 1
    budget: ExecutionBudget | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ArmSpec.name must be nonempty")
        if self.kind not in ("react", "atlas"):
            raise ValueError(
                f'ArmSpec.kind must be "react" or "atlas", got {self.kind!r}'
            )
        if not isinstance(self.max_workers, int) or isinstance(
            self.max_workers, bool
        ) or self.max_workers < 1:
            raise ValueError(
                f"ArmSpec.max_workers must be int >= 1, got {self.max_workers!r}"
            )


@dataclasses.dataclass(frozen=True)
class TaskManifest:
    """One task in a pilot manifest.

    ``task_id`` is the benchmark task identifier (e.g. a tau-bench
    task id).
    ``description`` is the natural-language task description given to
    both arms.
    ``expected_state`` is the expected final state (e.g. DB rows for
    tau-bench); passed to the grader.
    ``program_source`` is the ATLAS program source for the atlas
    arm (pre-authored for the scaffold path; in live runs this is
    authored IN-LOOP by the model via the delegate authoring loop).
    ``protocols`` maps protocol stems to source for programs that CALL.
    ``authoring_attempts_expected`` is the expected number of authoring
    attempts for the atlas arm (for testing; in live runs the actual
    count is observed and charged).
    """

    task_id: str
    description: str
    expected_state: Any = None
    program_source: str = ""
    protocols: Mapping[str, str] = dataclasses.field(default_factory=dict)
    authoring_attempts_expected: int = 0

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.strip():
            raise ValueError("TaskManifest.task_id must be nonempty")
        if not isinstance(self.authoring_attempts_expected, int) or isinstance(
            self.authoring_attempts_expected, bool
        ) or self.authoring_attempts_expected < 0:
            raise ValueError(
                "authoring_attempts_expected must be int >= 0,"
                f" got {self.authoring_attempts_expected!r}"
            )


@dataclasses.dataclass(frozen=True)
class TrialResult:
    """Outcome of a single trial (pass/fail + detail).

    ``passed`` is the grader's boolean verdict.
    ``detail`` is an optional human-readable string from the grader.
    ``failure_class`` is a short failure category (e.g.
    ``"wrong_state"``, ``"timeout"``, ``"crash"``) or ``"succeeded"``
    when ``passed`` is True.
    """

    passed: bool
    detail: str = ""
    failure_class: str = "succeeded"

    @classmethod
    def success(cls, detail: str = "") -> "TrialResult":
        return cls(passed=True, detail=detail, failure_class="succeeded")

    @classmethod
    def failure(
        cls, failure_class: str, detail: str = ""
    ) -> "TrialResult":
        return cls(passed=False, detail=detail, failure_class=failure_class)


ProgrammaticGrader = Callable[[Any, Any], TrialResult]
"""Grader callable: ``(actual_result, expected_state) -> TrialResult``.

A grader receives the final result from the arm's execution and the
task manifest's ``expected_state`` and returns a :class:`TrialResult`.
"""


@dataclasses.dataclass
class DBStateGrader:
    """Tau-bench-style DB-state matcher (documented example grader).

    Compares the arm's final result against the expected state dict.
    By default does a deep equality check; pass ``match_keys`` to check
    only specific keys (partial-credit scenarios).  Returns
    :meth:`TrialResult.success` when the match holds, otherwise
    :meth:`TrialResult.failure` with ``"wrong_state"``.

    Example::

        grader = DBStateGrader()
        result = grader(
            {"order_id": 42, "status": "confirmed"},
            {"order_id": 42, "status": "confirmed"},
        )
        assert result.passed
    """

    match_keys: Sequence[str] | None = None

    def __call__(self, actual: Any, expected: Any) -> TrialResult:
        if self.match_keys is not None:
            keys = list(self.match_keys)
            actual_sub = {k: actual.get(k) for k in keys} if isinstance(
                actual, dict
            ) else None
            expected_sub = {k: expected.get(k) for k in keys} if isinstance(
                expected, dict
            ) else None
            if actual_sub is None or expected_sub is None:
                return TrialResult.failure(
                    "wrong_state",
                    f"expected dict with keys {keys}, got {type(actual).__name__}",
                )
            if actual_sub == expected_sub:
                return TrialResult.success(
                    f"matched keys {keys}"
                )
            return TrialResult.failure(
                "wrong_state",
                f"mismatch on keys {keys}: got {actual_sub}, expected {expected_sub}",
            )
        if actual == expected:
            return TrialResult.success("exact match")
        return TrialResult.failure(
            "wrong_state",
            f"got {actual!r}, expected {expected!r}",
        )


@dataclasses.dataclass(frozen=True)
class TrialRecord:
    """Durable per-trial record (JSON-serializable).

    Fields:

    - ``task_id``: the task manifest's task id.
    - ``arm``: the arm spec's name.
    - ``result``: the :class:`TrialResult` (pass/fail + detail).
    - ``usage``: a dict of usage telemetry (tokens, cost) — may be
      empty for the deterministic path.
    - ``wall_seconds``: wall-clock time of the trial.
    - ``authoring_attempts``: number of authoring attempts (charged
      steps for the atlas arm per #50's authoring-parity clause).
    - ``event_store_path``: path to the event-store DB file for audit.
    - ``run_id``: the run id used in the event store.
    """

    task_id: str
    arm: str
    result: TrialResult
    usage: dict[str, Any] = dataclasses.field(default_factory=dict)
    wall_seconds: float = 0.0
    authoring_attempts: int = 0
    event_store_path: str = ""
    run_id: str = ""

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "arm": self.arm,
            "result": {
                "passed": self.result.passed,
                "detail": self.result.detail,
                "failure_class": self.result.failure_class,
            },
            "usage": dict(self.usage),
            "wall_seconds": self.wall_seconds,
            "authoring_attempts": self.authoring_attempts,
            "event_store_path": self.event_store_path,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "TrialRecord":
        r = d.get("result", {})
        return cls(
            task_id=d["task_id"],
            arm=d["arm"],
            result=TrialResult(
                passed=r.get("passed", False),
                detail=r.get("detail", ""),
                failure_class=r.get("failure_class", "succeeded"),
            ),
            usage=dict(d.get("usage", {})),
            wall_seconds=float(d.get("wall_seconds", 0.0)),
            authoring_attempts=int(d.get("authoring_attempts", 0)),
            event_store_path=d.get("event_store_path", ""),
            run_id=d.get("run_id", ""),
        )

    @classmethod
    def from_json(cls, s: str) -> "TrialRecord":
        return cls.from_dict(json.loads(s))


@dataclasses.dataclass(frozen=True)
class PilotReport:
    """Full pilot output: per-task per-arm trial records + summary.

    Mirrors #46's report pattern with :meth:`to_json` and
    :meth:`to_markdown`.
    """

    trials: tuple[TrialRecord, ...]
    arms: tuple[ArmSpec, ...]
    manifest_name: str = ""

    def to_json(self) -> str:
        report = {
            "manifest": self.manifest_name,
            "arms": [
                {"name": a.name, "kind": a.kind, "max_workers": a.max_workers}
                for a in self.arms
            ],
            "trials": [t.to_dict() for t in self.trials],
            "summary": self._summary_dict(),
        }
        return json.dumps(report, indent=2, sort_keys=False)

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(
            "# ATLAS Eval Pilot Report (scaffold — deterministic"
            " fake-worker evidence)"
        )
        lines.append("")
        lines.append(
            "Protocol A/B evaluation pilot (issue #47, methodology #50)."
            " Arms tested:"
        )
        for a in self.arms:
            lines.append(f"- **{a.name}** ({a.kind})")
        lines.append("")

        lines.append("## Per-task results")
        lines.append("")
        lines.append(
            "| task | arm | passed | failure_class | wall (s) |"
            " authoring attempts | usage tokens |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for t in self.trials:
            tokens = t.usage.get("total_tokens", 0) if t.usage else 0
            lines.append(
                f"| {t.task_id} | {t.arm}"
                f" | {'PASS' if t.result.passed else 'FAIL'}"
                f" | {t.result.failure_class}"
                f" | {t.wall_seconds:.3f}"
                f" | {t.authoring_attempts}"
                f" | {tokens} |"
            )
        lines.append("")

        s = self._summary_dict()
        lines.append("## Summary")
        lines.append("")
        lines.append("| arm | tasks passed | total | pass rate |")
        lines.append("|---|---|---|---|")
        for arm_name, stats in s["per_arm"].items():
            lines.append(
                f"| {arm_name}"
                f" | {stats['passed']}"
                f" | {stats['total']}"
                f" | {stats['pass_rate']:.2%} |"
            )
        lines.append("")

        lines.append("## Authoring parity (#50 section 4)")
        lines.append("")
        lines.append(
            "Authoring attempts are charged as steps for the atlas arm"
            " per #50's authoring-parity clause.  The react arm has zero"
            " authoring attempts (no sealed-program scaffolding)."
        )
        lines.append("")
        lines.append("| arm | total authoring attempts |")
        lines.append("|---|---|")
        for arm_name, stats in s["per_arm"].items():
            lines.append(
                f"| {arm_name} | {stats['authoring_attempts']} |"
            )
        lines.append("")
        lines.append("## Honest caveats")
        lines.append("")
        lines.append(
            "- This is a pilot scaffold: deterministic fake workers and"
            " graders prove the runner end-to-end.  Live model runs"
            " (real tau-bench env + live GLM-5.2) are the orchestrator's"
            " post-merge step with ATLAS_* env."
        )
        lines.append(
            "- Authoring attempts in the scaffold are pre-configured"
            " (the program is provided by the manifest).  In live runs"
            " the atlas arm's program is authored IN-LOOP by the model"
            " via the delegate authoring loop and every attempt is"
            " charged."
        )
        lines.append(
            "- Usage telemetry is zero-filled in the deterministic path."
            " Live workers populate tokens/cost through the same"
            " TrialRecord shape."
        )
        lines.append("")
        return "\n".join(lines)

    def _summary_dict(self) -> dict[str, Any]:
        per_arm: dict[str, dict[str, Any]] = {}
        for arm in self.arms:
            arm_trials = [t for t in self.trials if t.arm == arm.name]
            passed = sum(1 for t in arm_trials if t.result.passed)
            total = len(arm_trials)
            authoring = sum(t.authoring_attempts for t in arm_trials)
            per_arm[arm.name] = {
                "passed": passed,
                "total": total,
                "pass_rate": passed / total if total > 0 else 0.0,
                "authoring_attempts": authoring,
            }
        return {"per_arm": per_arm}


def _run_react_arm(
    task: TaskManifest,
    arm: ArmSpec,
    *,
    workdir: str,
    run_id: str,
) -> tuple[TrialRecord, Any]:
    """Run the react (plain tool-loop baseline) arm.

    In the scaffold path this executes the task through the same
    coordinator with a simple program that uses define/search/fetch/
    report — simulating a plain agent tool loop.  In live runs this
    would dispatch a plain ReAct prompt to the model.
    """
    react_program = (
        "PROGRAM react_arm VERSION 1.0\n"
        "INPUT\n"
        f'    G.task = {json.dumps(task.description)}\n'
        "step.understand: DO define(request = G.task) -> P.goal\n"
        "step.search: DO search(query = G.task, scope = \"env\") -> E.found\n"
        "step.act: DO fetch(resource_refs = E.found) -> ART.result\n"
        "step.report: DO report(committed_refs = ART.result, format = \"json\") -> OUT.answer\n"
        "RETURN OUT.answer\n"
    )
    return _run_atlas_program(
        task=task,
        arm=arm,
        program_source=react_program,
        workdir=workdir,
        run_id=run_id,
        authoring_attempts=0,
    )


def _run_atlas_arm(
    task: TaskManifest,
    arm: ArmSpec,
    *,
    workdir: str,
    run_id: str,
) -> tuple[TrialRecord, Any]:
    """Run the atlas (sealed-program) arm.

    In the scaffold path the program source is provided by the task
    manifest.  In live runs the program is authored IN-LOOP by the
    model via the delegate authoring loop; every attempt is charged
    as a step per #50's authoring-parity clause.
    """
    program_source = task.program_source
    if not program_source:
        raise ValueError(
            f"atlas arm requires program_source in task {task.task_id!r}"
        )
    return _run_atlas_program(
        task=task,
        arm=arm,
        program_source=program_source,
        workdir=workdir,
        run_id=run_id,
        authoring_attempts=task.authoring_attempts_expected,
    )


def _run_atlas_program(
    task: TaskManifest,
    arm: ArmSpec,
    *,
    program_source: str,
    workdir: str,
    run_id: str,
    authoring_attempts: int,
) -> tuple[TrialRecord, Any]:
    """Execute a program and produce a TrialRecord.

    Shared execution path for both arms: parse the program, create a
    fresh EventStore, execute through SequentialCoordinator, and
    record the trial.
    """
    store_path = os.path.join(workdir, f"{run_id}.events.db")
    protocols_dir: str | None = None
    if task.protocols:
        protocols_dir = os.path.join(workdir, f"{run_id}.protocols")
        os.makedirs(protocols_dir, exist_ok=True)
        for stem, text in task.protocols.items():
            with open(
                os.path.join(protocols_dir, f"{stem}.think"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(text)

    program = parse_program(program_source)
    store = EventStore(store_path)
    try:
        if arm.worker_factory is not None:
            worker = arm.worker_factory()
        else:
            worker = _default_eval_worker()
        coordinator = SequentialCoordinator(
            store, worker, protocols_dir=protocols_dir
        )
        start = time.perf_counter()
        try:
            result = coordinator.execute(
                program,
                run_id=run_id,
                max_workers=arm.max_workers,
                budget=arm.budget,
            )
        except Exception as exc:
            wall = time.perf_counter() - start
            record = TrialRecord(
                task_id=task.task_id,
                arm=arm.name,
                result=TrialResult.failure(
                    "crash",
                    f"execution error: {exc}",
                ),
                wall_seconds=wall,
                authoring_attempts=authoring_attempts,
                event_store_path=store_path,
                run_id=run_id,
            )
            return record, None
        wall_seconds = time.perf_counter() - start

        status = result.get("status", "unknown")
        usage: dict[str, Any] = {}
        if status != "succeeded":
            trial_result = TrialResult.failure(
                "execution_failed",
                f"run status: {status}",
            )
        else:
            trial_result = TrialResult.success(
                f"run status: {status}"
            )

        record = TrialRecord(
            task_id=task.task_id,
            arm=arm.name,
            result=trial_result,
            usage=usage,
            wall_seconds=wall_seconds,
            authoring_attempts=authoring_attempts,
            event_store_path=store_path,
            run_id=run_id,
        )
        return record, result
    finally:
        store.close()


def _default_eval_worker() -> DeterministicWorker:
    """A minimal deterministic worker for the eval scaffold path.

    Each handler returns a fixed echo; ``delegate`` returns a fixed
    canonical plan (same as the benchmark harness).
    """
    from atlas.benchmarks import DELEGATE_SAMPLE_PLAN

    registry = builtin_registry()

    def make(name: str) -> Callable[..., Any]:
        def handler(**kwargs: Any) -> Any:
            return {"command": name, "echo": kwargs}

        return handler

    def _delegate(**kwargs: Any) -> Any:
        return DELEGATE_SAMPLE_PLAN

    handlers: dict[str, Callable[..., Any]] = {
        name: make(name) for name in registry.names()
    }
    handlers["delegate"] = _delegate
    return DeterministicWorker(handlers=handlers)


def run_pilot(
    manifest: Sequence[TaskManifest],
    arms: Sequence[ArmSpec],
    model_config: Mapping[str, Any] | None = None,
    *,
    grader: ProgrammaticGrader | None = None,
    repetitions: int = 1,
) -> PilotReport:
    """Run a pilot: every task x every arm, graded.

    This is the ONE entry point for the pilot.  It executes each task
    under each arm, grades the result, and returns a
    :class:`PilotReport` with per-task :class:`TrialRecord` s.

    Args:
        manifest: a sequence of :class:`TaskManifest` entries (the
            task battery).
        arms: a sequence of :class:`ArmSpec` entries (the arms to test;
            minimum arms 1 and 4 per #50 section 4).
        model_config: optional model configuration dict (model name,
            transport, tier models) for live runs; ignored in the
            scaffold path (the arm's ``worker_factory`` controls the
            worker).
        grader: a :data:`ProgrammaticGrader` callable that receives
            ``(actual_result, expected_state)`` and returns a
            :class:`TrialResult`.  When ``None``, a pass is recorded
            if the execution succeeded (status ``"succeeded"``).
        repetitions: number of independent trials per task per arm
            (for pass^k reliability per #50 section 1).

    Returns:
        A :class:`PilotReport` with :meth:`to_json` and
        :meth:`to_markdown`.
    """
    if not manifest:
        raise ValueError("run_pilot requires at least one task")
    if not arms:
        raise ValueError("run_pilot requires at least one arm")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError(
            f"repetitions must be int >= 1, got {repetitions!r}"
        )

    all_trials: list[TrialRecord] = []
    with tempfile.TemporaryDirectory(prefix="atlas-eval-") as workdir:
        for rep in range(1, repetitions + 1):
            for task in manifest:
                for arm in arms:
                    run_id = (
                        f"{task.task_id}-{arm.name}-r{rep}"
                    )
                    if arm.kind == "react":
                        record, raw_result = _run_react_arm(
                            task=task,
                            arm=arm,
                            workdir=workdir,
                            run_id=run_id,
                        )
                    else:
                        record, raw_result = _run_atlas_arm(
                            task=task,
                            arm=arm,
                            workdir=workdir,
                            run_id=run_id,
                        )

                    if grader is not None and record.result.passed:
                        graded = grader(
                            raw_result, task.expected_state
                        )
                        record = dataclasses.replace(
                            record,
                            result=graded,
                        )

                    all_trials.append(record)

    return PilotReport(
        trials=tuple(all_trials),
        arms=tuple(arms),
        manifest_name=getattr(manifest, "__name__", ""),
    )
