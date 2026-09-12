"""Benchmark harness for the tikhon execution model (issue #26, epic #27 step 6).

Measures the same program under a sequential baseline and a configured
bounded-parallel variant in fresh temporary :class:`EventStore` s, with
deterministic sleep-simulated workers (each handler sleeps a fixed
per-step latency, so wall-time differences come from the coordinator's
overlap behavior alone — frontier dispatch for linear programs, the PAR
branch pool for heterogeneous branches).  Per run it records wall time
(``time.perf_counter``), tree-wide event and task counts, worker-dispatch
count, the CONTEXT cost proxy (summed :meth:`TaskEnvelope.to_json` byte
length over every worker dispatch reconstructed from the DISPATCHED
events' recorded resolved arguments), and delegation granularity (child
runs, per-child steps from ``CHILD_PLAN_AUTHORED`` + child ledgers).

All numbers are averaged over repeated trials with min/max spread.
Deterministic sleep-simulated evidence only: live OpenCode/model numbers
require operator credentials (``TIKHON_*`` environment) and are produced
by the same harness — same programs, same accounting — once configured.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tikhon.budgets import ExecutionBudget
from tikhon.envelope import build_task_envelope
from tikhon.registry import builtin_registry
from tikhon.runtime import EventStore, SequentialCoordinator
from tikhon.runtime.coordinator import DeterministicWorker, count_plan_steps
from tikhon.syntax import parse_program
from tikhon.syntax.model import Invocation, Program

__all__ = [
    "BenchmarkCase",
    "BenchmarkReport",
    "CaseRegistry",
    "CaseResult",
    "RunMetrics",
    "SideSummary",
    "UsageStats",
    "builtin_cases",
    "builtin_registry_names",
    "register_case",
    "run_benchmark",
    "sleep_worker",
]


#: The deterministic delegate handler's fixed canonical sample plan (the
#: same artifact cli.py's handler returns): three authored steps bound to
#: two declared INPUT placeholders, so delegation-granularity numbers are
#: reproducible without a model.
DELEGATE_SAMPLE_PLAN = (
    "PROGRAM delegated_child VERSION 1.0\n"
    "\n"
    "INPUT\n"
    "    G.goal = \"\"\n"
    "    C.constraints = \"\"\n"
    "\n"
    "step.frame: DO define(request = G.goal) -> P.plan\n"
    "step.measure: DO calculate(expression = \"goal_units\","
    " values = {\"units\": 3}) -> F.metrics\n"
    "step.check: DO check(artifact = P.plan, predicate ="
    " \"nonempty\") -> V.verdict\n"
    "\n"
    "RETURN P.plan, F.metrics\n"
)


@dataclasses.dataclass(frozen=True)
class UsageStats:
    """Usage telemetry from a worker's RESULT_RECEIVED receipt.

    Default zero-shaped so the deterministic sleep-simulated path is
    unaffected; a live worker factory that reports usage in its result
    dict populates these fields, which flow into ``RunMetrics`` and
    through to the JSON/markdown outputs.  All fields default to 0/0.0
    so a ``UsageStats()`` is a valid "no usage reported" sentinel.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def zero(cls) -> "UsageStats":
        """A zero-shaped sentinel for runs that report no usage."""
        return cls()

    @classmethod
    def from_result(cls, result: Any) -> "UsageStats | None":
        """Extract usage from a worker's RESULT_RECEIVED result value.

        A usage-reporting worker factory includes a ``"usage"`` key in
        the result dict returned by each handler; the value is a mapping
        with optional ``prompt_tokens``, ``completion_tokens``,
        ``total_tokens`` (ints) and ``cost_usd`` (float).  Returns
        ``None`` when no usage key is present (the deterministic path).
        """
        if not isinstance(result, dict):
            return None
        usage = result.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, dict):
            return None
        return cls(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            cost_usd=float(usage.get("cost_usd", 0.0)),
        )


def sleep_worker(latency_seconds: float = 0.04) -> DeterministicWorker:
    """A deterministic worker covering every registered command.

    Each handler sleeps ``latency_seconds`` (the simulated per-step model
    latency) and returns a deterministic echo of its resolved arguments;
    ``delegate`` returns the fixed canonical sample plan.  The echo shape
    is JSON-serializable so committed deltas and the envelope proxy stay
    deterministic.
    """
    if (
        not isinstance(latency_seconds, (int, float))
        or isinstance(latency_seconds, bool)
        or latency_seconds < 0
    ):
        raise ValueError(
            "latency_seconds must be a non-negative number, got"
            f" {latency_seconds!r}"
        )
    delay = float(latency_seconds)

    def make(name: str) -> Callable[..., Any]:
        def handler(**kwargs: Any) -> Any:
            time.sleep(delay)
            return {"command": name, "echo": kwargs}

        return handler

    def _delegate(**kwargs: Any) -> Any:
        goal = kwargs.get("goal")
        if not isinstance(goal, (str, dict, list)) or (
            isinstance(goal, str) and not goal.strip()
        ):
            raise ValueError(
                "delegate requires a nonempty committed goal argument"
            )
        time.sleep(delay)
        return DELEGATE_SAMPLE_PLAN

    handlers: dict[str, Callable[..., Any]] = {
        name: make(name) for name in builtin_registry().names()
    }
    handlers["delegate"] = _delegate
    return DeterministicWorker(handlers=handlers)


@dataclasses.dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark: a program run sequentially vs bounded-parallel.

    ``program`` is the .think source text (``from_path`` loads a file).
    The baseline side drives the program with ``baseline_max_workers``
    (default 1) under ``baseline_budget`` (default a 1-slot
    :class:`ExecutionBudget`, which serializes PAR branch pools); the
    variant side uses ``max_workers``/``budget``.  ``protocols`` maps
    protocol stems to source text for programs that CALL (written to a
    fresh per-run directory).  ``worker_factory`` builds the worker per
    run; ``None`` uses :func:`sleep_worker` with ``latency_seconds``.
    ``repetitions`` is the case default used when :func:`run_benchmark`
    is not given an explicit count.
    """

    name: str
    program: str
    max_workers: int = 4
    budget: ExecutionBudget | None = None
    baseline_max_workers: int = 1
    baseline_budget: ExecutionBudget | None = None
    protocols: Mapping[str, str] = dataclasses.field(default_factory=dict)
    worker_factory: Callable[[], Any] | None = None
    latency_seconds: float = 0.04
    repetitions: int = 3

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("BenchmarkCase.name must be a nonempty string")
        if not self.program or not self.program.strip():
            raise ValueError("BenchmarkCase.program must be nonempty source")
        for field_name in ("max_workers", "baseline_max_workers", "repetitions"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(
                    f"BenchmarkCase.{field_name} must be an integer >= 1,"
                    f" got {value!r}"
                )

    @classmethod
    def from_path(
        cls, name: str, path: str | os.PathLike[str], **kwargs: Any
    ) -> "BenchmarkCase":
        """Build a case from a .think source file."""
        return cls(
            name=name,
            program=Path(path).read_text(encoding="utf-8"),
            **kwargs,
        )


@dataclasses.dataclass(frozen=True)
class RunMetrics:
    """Measurements of one executed run (tree-wide)."""

    wall_seconds: float
    events: int
    tasks: int
    dispatches: int
    envelope_bytes: int
    child_runs: int
    child_events: int
    child_tasks: int
    authored_plans: int
    authored_steps: int
    usage: UsageStats | None = None


@dataclasses.dataclass(frozen=True)
class SideSummary:
    """One side (sequential baseline or variant) of a case, aggregated."""

    label: str
    max_workers: int
    budget_workers: int | None
    repetitions: int
    wall_mean_seconds: float
    wall_min_seconds: float
    wall_max_seconds: float
    events: int
    tasks: int
    dispatches: int
    envelope_bytes: int
    child_runs: int
    child_events: int
    child_tasks: int
    authored_plans: int
    authored_steps: int
    usage: UsageStats | None = None

    @property
    def avg_steps_per_child(self) -> float:
        if self.child_runs == 0:
            return 0.0
        return self.child_tasks / self.child_runs


@dataclasses.dataclass(frozen=True)
class CaseResult:
    """A benchmarked case: both sides plus the derived headline numbers."""

    name: str
    baseline: SideSummary
    variant: SideSummary

    @property
    def speedup(self) -> float:
        """CRITICAL-PATH speedup: sequential mean wall / variant mean wall."""
        if self.variant.wall_mean_seconds <= 0.0:
            return 0.0
        return self.baseline.wall_mean_seconds / self.variant.wall_mean_seconds

    @property
    def envelope_delta_bytes(self) -> int:
        return self.variant.envelope_bytes - self.baseline.envelope_bytes

    @property
    def usage_delta_tokens(self) -> int:
        """Total-token delta (variant - baseline); 0 when neither reports."""
        base = self.baseline.usage.total_tokens if self.baseline.usage else 0
        var = self.variant.usage.total_tokens if self.variant.usage else 0
        return var - base


@dataclasses.dataclass(frozen=True)
class BenchmarkReport:
    """The full benchmark output: one :class:`CaseResult` per case."""

    cases: tuple[CaseResult, ...]
    repetitions: int

    def to_markdown(self) -> str:
        """Deterministic markdown rendering (pure function of the data)."""
        lines: list[str] = []
        lines.append("# Tikhon Benchmark Report (deterministic, sleep-simulated)")
        lines.append("")
        lines.append(
            "Deterministic **sleep-simulated evidence** produced by"
            " `tikhon bench` (issue #26): every worker handler sleeps a"
            " fixed per-step latency, so measured wall-time differences"
            " isolate the coordinator's overlap behavior (frontier"
            " dispatch, PAR branch pools).  **Live OpenCode/model numbers"
            " require operator credentials (TIKHON_* env) and are produced"
            " by the same harness** — same programs, same accounting —"
            " once configured."
        )
        lines.append("")
        lines.append("## Configuration")
        lines.append("")
        lines.append(
            "| case | sequential (workers/slots) | variant (workers/slots)"
            " | per-step latency | repetitions |"
        )
        lines.append("|---|---|---|---|---|")
        for case in self.cases:
            lines.append(
                f"| {case.name}"
                f" | {case.baseline.max_workers}/"
                f"{case.baseline.budget_workers}"
                f" | {case.variant.max_workers}/"
                f"{case.variant.budget_workers}"
                f" | (case worker factory) | {case.baseline.repetitions} |"
            )
        lines.append("")
        lines.append("## Critical-path speedup (sequential_total / variant_total)")
        lines.append("")
        lines.append(
            "| case | sequential mean (min..max) | variant mean (min..max)"
            " | speedup |"
        )
        lines.append("|---|---|---|---|")
        for case in self.cases:
            base, variant = case.baseline, case.variant
            lines.append(
                f"| {case.name}"
                f" | {_ms(base.wall_mean_seconds)}"
                f" ({_ms(base.wall_min_seconds)}..{_ms(base.wall_max_seconds)})"
                f" | {_ms(variant.wall_mean_seconds)}"
                f" ({_ms(variant.wall_min_seconds)}..{_ms(variant.wall_max_seconds)})"
                f" | **{case.speedup:.2f}x** |"
            )
        lines.append("")
        lines.append(
            "## Context cost (task-envelope bytes per run, `TaskEnvelope.to_json`)"
        )
        lines.append("")
        lines.append(
            "Proxy for serialized dispatch context: every worker dispatch"
            " reconstructed from its DISPATCHED event's recorded resolved"
            " arguments, rendered and summed.  Deterministic programs ship"
            " identical envelopes on both sides — width changes latency,"
            " not per-run context."
        )
        lines.append("")
        lines.append(
            "| case | worker dispatches | sequential bytes | variant bytes"
            " | delta |"
        )
        lines.append("|---|---|---|---|---|")
        for case in self.cases:
            base, variant = case.baseline, case.variant
            lines.append(
                f"| {case.name}"
                f" | {base.dispatches}"
                f" | {base.envelope_bytes}"
                f" | {variant.envelope_bytes}"
                f" | {case.envelope_delta_bytes:+d} |"
            )
        lines.append("")
        lines.append("## Delegation granularity (child runs per execution tree)")
        lines.append("")
        lines.append(
            "| case | child runs | child events | tasks per child (mean)"
            " | authored plans (CHILD_PLAN_AUTHORED) | steps per authored plan |"
        )
        lines.append("|---|---|---|---|---|---|")
        for case in self.cases:
            variant = case.variant
            lines.append(
                f"| {case.name}"
                f" | {variant.child_runs}"
                f" | {variant.child_events}"
                f" | {variant.avg_steps_per_child:.2f}"
                f" | {variant.authored_plans}"
                f" | {variant.authored_steps}"
                f" ({_per_plan(variant.authored_plans, variant.authored_steps)})"
                " |"
            )
        lines.append("")
        lines.append("## Honest caveats")
        lines.append("")
        lines.append(
            "- Wall times are real measurements and vary run to run and"
            " machine to machine; the report publishes mean with min..max"
            " spread over repeated trials.  Counts (events, tasks,"
            " dispatches, envelope bytes) are deterministic."
        )
        lines.append(
            "- SCATTER/GATHER fan-out drives the sequential plan loop by"
            " contract (candidate-order semantics), so width gives it no"
            " latency gain: this is the measured 'where parallel execution"
            " is NOT faster' data point, not a harness defect."
        )
        lines.append(
            "- Fine-grained phase telemetry (queue/startup/worker/join"
            " split, peak concurrency, token/usage accounting, retries and"
            " cancellation waste) requires live-model runs and is recorded"
            " as unknown here; zero-valued usage placeholders are never"
            " presented as measurements."
        )
        lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        """JSON-serializable form of the report.

        Every number in the JSON output is identical to the number
        rendered in :meth:`to_markdown` — wall times, event/task/
        dispatch/envelope counts, child-run accounting, authored-plan
        steps, speedup, envelope delta, and (when present) usage tokens
        and cost.  The output roundtrips through ``json.loads``.
        """
        cases_json: list[dict[str, Any]] = []
        for case in self.cases:
            base, variant = case.baseline, case.variant
            cases_json.append({
                "name": case.name,
                "configuration": {
                    "sequential": {
                        "max_workers": base.max_workers,
                        "budget_workers": base.budget_workers,
                    },
                    "variant": {
                        "max_workers": variant.max_workers,
                        "budget_workers": variant.budget_workers,
                    },
                    "repetitions": base.repetitions,
                },
                "speedup": {
                    "sequential_mean_ms": _round1(base.wall_mean_seconds),
                    "sequential_min_ms": _round1(base.wall_min_seconds),
                    "sequential_max_ms": _round1(base.wall_max_seconds),
                    "variant_mean_ms": _round1(variant.wall_mean_seconds),
                    "variant_min_ms": _round1(variant.wall_min_seconds),
                    "variant_max_ms": _round1(variant.wall_max_seconds),
                    "speedup": round(case.speedup, 2),
                },
                "context_cost": {
                    "dispatches": base.dispatches,
                    "sequential_bytes": base.envelope_bytes,
                    "variant_bytes": variant.envelope_bytes,
                    "delta_bytes": case.envelope_delta_bytes,
                },
                "delegation_granularity": {
                    "child_runs": variant.child_runs,
                    "child_events": variant.child_events,
                    "tasks_per_child_mean": round(variant.avg_steps_per_child, 2),
                    "authored_plans": variant.authored_plans,
                    "authored_steps": variant.authored_steps,
                    "steps_per_plan": (
                        round(variant.authored_steps / variant.authored_plans, 2)
                        if variant.authored_plans > 0
                        else None
                    ),
                },
                "usage": _usage_json(base, variant),
            })
        report = {
            "label": "Tikhon Benchmark Report (deterministic, sleep-simulated)",
            "repetitions": self.repetitions,
            "cases": cases_json,
        }
        return json.dumps(report, indent=2, sort_keys=False)


def _ms(seconds: float) -> str:
    return f"{seconds * 1000.0:.1f} ms"


def _round1(seconds: float) -> float:
    """Round seconds to milliseconds with 1 decimal place (matches _ms)."""
    return round(seconds * 1000.0, 1)


def _per_plan(plans: int, steps: int) -> str:
    if plans == 0:
        return "n/a"
    return f"{steps / plans:.2f} avg"


def _usage_json(base: SideSummary, variant: SideSummary) -> dict[str, Any] | None:
    """Usage block for JSON output; None when neither side reports."""
    base_usage = base.usage if base.usage is not None else UsageStats.zero()
    var_usage = variant.usage if variant.usage is not None else UsageStats.zero()
    if base_usage == UsageStats.zero() and var_usage == UsageStats.zero():
        return None
    return {
        "sequential": {
            "prompt_tokens": base_usage.prompt_tokens,
            "completion_tokens": base_usage.completion_tokens,
            "total_tokens": base_usage.total_tokens,
            "cost_usd": round(base_usage.cost_usd, 6),
        },
        "variant": {
            "prompt_tokens": var_usage.prompt_tokens,
            "completion_tokens": var_usage.completion_tokens,
            "total_tokens": var_usage.total_tokens,
            "cost_usd": round(var_usage.cost_usd, 6),
        },
        "delta_total_tokens": (
            var_usage.total_tokens - base_usage.total_tokens
        ),
    }


def _walk_run_tree(store: EventStore, root_run_id: str) -> list[str]:
    """The run and every descendant run, breadth-first, deterministic.

    Child run ids are read from ``child_run_id`` payload fields (PAR
    branch dispatches, CALL child runs, delegate-authored child runs), so
    the walk needs no store-side run listing.
    """
    seen = [root_run_id]
    frontier = [root_run_id]
    while frontier:
        current = frontier.pop(0)
        try:
            events = store.events(current)
        except KeyError:
            continue
        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            child = payload.get("child_run_id")
            if isinstance(child, str) and child not in seen:
                seen.append(child)
                frontier.append(child)
    return seen


def _invocation_index(*programs: Program) -> dict[str, Invocation]:
    """step_id -> Invocation for plain DO statements (targets for envelopes)."""
    index: dict[str, Invocation] = {}

    def walk(statements: Sequence[Any]) -> None:
        for statement in statements:
            if isinstance(statement, Invocation):
                index.setdefault(statement.step_id, statement)

    for program in programs:
        walk(program.statements)
    return index


def _envelope_proxy(
    store: EventStore,
    root_run_id: str,
    program: Program,
    authored_programs: Sequence[Program],
) -> tuple[int, int]:
    """Reconstruct and sum task envelopes over the run tree's dispatches.

    Counts only real worker dispatches: PAR-branch and CALL bookkeeping
    dispatch events (identified by their ``branch_id``/``child_run_id``
    payload markers and ``protocol.`` instruction ids) are skipped — the
    dispatches they bookkeep happen inside the child runs and are counted
    there.  Command names come from the ledger task texts, targets from
    the parsed parent program and authored plans.  Identity fields that
    embed the root run id (run_id, idempotency_key) are normalized to a
    fixed ``run`` placeholder so byte totals compare context, not
    run-id length between the two sides.
    """
    registry = builtin_registry()
    invocations = _invocation_index(program, *authored_programs)

    def _normalized(value: str) -> str:
        if value == root_run_id:
            return "run"
        if value.startswith(root_run_id + ":"):
            return "run:" + value[len(root_run_id) + 1:]
        return value

    dispatches = 0
    total_bytes = 0
    for run_id in _walk_run_tree(store, root_run_id):
        try:
            events = store.events(run_id)
            ledger = store.task_ledger(run_id)
        except KeyError:
            continue
        for event in events:
            if event.event_type.value != "invocation.dispatched":
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            if "branch_id" in payload or "child_run_id" in payload:
                continue
            if event.instruction_id and event.instruction_id.startswith(
                "protocol."
            ):
                continue
            command = None
            task = ledger.tasks.get(event.task_id)
            if task is not None and " DO " in task.text:
                command = (
                    task.text.split(" DO ", 1)[1]
                    .split(" [candidate", 1)[0]
                    .strip()
                )
            if command is None or command not in registry.names():
                continue
            invocation = invocations.get(event.instruction_id)
            targets = (
                tuple(invocation.targets) if invocation is not None else ()
            )
            envelope = build_task_envelope(
                registry,
                run_id=_normalized(run_id),
                invocation_id=event.invocation_id or "inv-unknown",
                task_id=event.task_id or "task-unknown",
                attempt=1,
                idempotency_key=_normalized(
                    str(payload.get("idempotency_key", "unknown"))
                ),
                command=command,
                arguments=dict(payload.get("args") or {}),
                targets=targets,
            )
            total_bytes += len(envelope.to_json().encode("utf-8"))
            dispatches += 1
    return dispatches, total_bytes


def _measure_run(
    case: BenchmarkCase,
    *,
    run_id: str,
    max_workers: int,
    budget: ExecutionBudget | None,
    workdir: str,
) -> RunMetrics:
    """Execute one run in a fresh temp EventStore and measure it."""
    store_path = os.path.join(workdir, f"{run_id}.events.db")
    protocols_dir: str | None = None
    if case.protocols:
        protocols_dir = os.path.join(workdir, f"{run_id}.protocols")
        os.makedirs(protocols_dir, exist_ok=True)
        for stem, text in case.protocols.items():
            with open(
                os.path.join(protocols_dir, f"{stem}.think"), "w", encoding="utf-8"
            ) as fh:
                fh.write(text)

    program = parse_program(case.program)
    store = EventStore(store_path)
    try:
        if case.worker_factory is not None:
            worker = case.worker_factory()
        else:
            worker = sleep_worker(case.latency_seconds)
        coordinator = SequentialCoordinator(
            store, worker, protocols_dir=protocols_dir
        )
        start = time.perf_counter()
        try:
            result = coordinator.execute(
                program, run_id=run_id, max_workers=max_workers, budget=budget
            )
        except Exception as exc:
            raise ValueError(
                f"benchmark case {case.name!r} run {run_id!r} failed to"
                f" execute: {exc}"
            ) from exc
        wall_seconds = time.perf_counter() - start
        status = result.get("status", "unknown")

        tree = _walk_run_tree(store, run_id)
        events = 0
        tasks = 0
        child_events = 0
        child_tasks = 0
        child_runs = 0
        authored_texts: list[str] = []
        usage_stats: list[UsageStats] = []
        for node_id in tree:
            try:
                node_events = store.events(node_id)
                node_tasks = len(store.task_ledger(node_id).tasks)
            except KeyError:
                continue
            events += len(node_events)
            tasks += node_tasks
            for event in node_events:
                if event.event_type.value == "child_plan.authored":
                    payload = (
                        event.payload if isinstance(event.payload, dict) else {}
                    )
                    if isinstance(payload.get("plan_text"), str):
                        authored_texts.append(payload["plan_text"])
                if event.event_type.value == "invocation.result_received":
                    payload = (
                        event.payload if isinstance(event.payload, dict) else {}
                    )
                    result = payload.get("result")
                    extracted = UsageStats.from_result(result)
                    if extracted is not None:
                        usage_stats.append(extracted)
            if node_id != run_id:
                child_runs += 1
                child_events += len(node_events)
                child_tasks += node_tasks

        authored_programs = [
            parse_program(text) for text in authored_texts
        ]
        authored_steps = sum(
            count_plan_steps(authored) for authored in authored_programs
        )
        dispatches, envelope_bytes = _envelope_proxy(
            store, run_id, program, authored_programs
        )
    finally:
        store.close()

    if status != "succeeded":
        raise ValueError(
            f"benchmark case {case.name!r} run {run_id!r} finished with"
            f" status {status!r}; benchmarks measure succeeded runs only"
        )
    run_usage: UsageStats | None = None
    if usage_stats:
        run_usage = UsageStats(
            prompt_tokens=sum(u.prompt_tokens for u in usage_stats),
            completion_tokens=sum(u.completion_tokens for u in usage_stats),
            total_tokens=sum(u.total_tokens for u in usage_stats),
            cost_usd=sum(u.cost_usd for u in usage_stats),
        )
    return RunMetrics(
        wall_seconds=wall_seconds,
        events=events,
        tasks=tasks,
        dispatches=dispatches,
        envelope_bytes=envelope_bytes,
        child_runs=child_runs,
        child_events=child_events,
        child_tasks=child_tasks,
        authored_plans=len(authored_programs),
        authored_steps=authored_steps,
        usage=run_usage,
    )


def _summarize(
    label: str,
    *,
    max_workers: int,
    budget: ExecutionBudget | None,
    metrics: list[RunMetrics],
) -> SideSummary:
    walls = [run.wall_seconds for run in metrics]
    first = metrics[0]
    any_usage = any(run.usage is not None for run in metrics)
    side_usage: UsageStats | None = None
    if any_usage:
        per_run = [
            run.usage if run.usage is not None else UsageStats.zero()
            for run in metrics
        ]
        side_usage = UsageStats(
            prompt_tokens=sum(u.prompt_tokens for u in per_run),
            completion_tokens=sum(u.completion_tokens for u in per_run),
            total_tokens=sum(u.total_tokens for u in per_run),
            cost_usd=sum(u.cost_usd for u in per_run),
        )
    return SideSummary(
        label=label,
        max_workers=max_workers,
        budget_workers=(
            budget.max_concurrent_workers if budget is not None else None
        ),
        repetitions=len(metrics),
        wall_mean_seconds=sum(walls) / len(walls),
        wall_min_seconds=min(walls),
        wall_max_seconds=max(walls),
        events=first.events,
        tasks=first.tasks,
        dispatches=first.dispatches,
        envelope_bytes=first.envelope_bytes,
        child_runs=first.child_runs,
        child_events=first.child_events,
        child_tasks=first.child_tasks,
        authored_plans=first.authored_plans,
        authored_steps=first.authored_steps,
        usage=side_usage,
    )


def run_benchmark(
    cases: Sequence[BenchmarkCase], repetitions: int | None = None
) -> BenchmarkReport:
    """Run every case sequentially vs its configured variant.

    Each execution gets a fresh temporary directory with its own
    EventStore (and protocols directory when the case CALLs); the two
    sides alternate case by case in the given order, repetitions inner,
    so ordering is deterministic.  ``repetitions`` overrides each case's
    own count when given.
    """
    if not cases:
        raise ValueError("run_benchmark requires at least one case")
    for case in cases:
        if not isinstance(case, BenchmarkCase):
            raise ValueError(
                f"run_benchmark cases must be BenchmarkCase instances, got"
                f" {type(case).__name__}"
            )
    results: list[CaseResult] = []
    with tempfile.TemporaryDirectory(prefix="tikhon-bench-") as workdir:
        for case in cases:
            reps = (
                repetitions if repetitions is not None else case.repetitions
            )
            if not isinstance(reps, int) or isinstance(reps, bool) or reps < 1:
                raise ValueError(
                    f"repetitions must be an integer >= 1, got {reps!r}"
                )
            baseline_budget = (
                case.baseline_budget
                if case.baseline_budget is not None
                else ExecutionBudget(max_concurrent_workers=1)
            )
            baseline_runs = [
                _measure_run(
                    case,
                    run_id=f"{case.name}-baseline-{index}",
                    max_workers=case.baseline_max_workers,
                    budget=baseline_budget,
                    workdir=workdir,
                )
                for index in range(1, reps + 1)
            ]
            variant_runs = [
                _measure_run(
                    case,
                    run_id=f"{case.name}-variant-{index}",
                    max_workers=case.max_workers,
                    budget=case.budget,
                    workdir=workdir,
                )
                for index in range(1, reps + 1)
            ]
            results.append(
                CaseResult(
                    name=case.name,
                    baseline=_summarize(
                        "sequential",
                        max_workers=case.baseline_max_workers,
                        budget=baseline_budget,
                        metrics=baseline_runs,
                    ),
                    variant=_summarize(
                        "variant",
                        max_workers=case.max_workers,
                        budget=case.budget,
                        metrics=variant_runs,
                    ),
                )
            )
    return BenchmarkReport(cases=tuple(results), repetitions=repetitions or 0)


# ----------------------------------------------------------------------
# Built-in cases (issue #26): linear frontier, scatter/gather fan-out,
# heterogeneous PAR.  Sleep-simulated handlers; per-run totals stay well
# under ~2s at the default latency.
# ----------------------------------------------------------------------

_LINEAR_PROGRAM = """\
PROGRAM bench_linear VERSION 1.0
INPUT
    G.goal = "benchmark the concurrent frontier"
step.frame: DO define(request = G.goal) -> P.frame
step.locate: DO search(query = G.goal, scope = "src/") -> E.sites
step.read: DO fetch(resource_refs = G.goal) -> ART.sources
step.analyze: DO extract(artifact = G.goal, schema = "bench") -> E.findings
step.hypothesize: DO hypothesize(question = G.goal, evidence = G.goal) -> H.theses
step.report: DO report(committed_refs = G.goal, format = "markdown") -> ART.report
RETURN P.frame, E.sites, ART.sources, E.findings, H.theses, ART.report
"""

_SCATTER_PROGRAM = """\
PROGRAM bench_scatter VERSION 1.0
INPUT
    Q.parts = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"]
step.prepare: DO define(goal = Q.parts) -> G.goal
SCATTER X.part IN Q.parts MAX 8
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.all USING all
step.final: DO report(inputs = E.all) -> ART.report
RETURN ART.report, E.all
"""

_PAR_PROTOCOL = """\
PROGRAM framing VERSION 1.0
INPUT
    G.request = ""
    C.scope = ""
step.frame: DO define(request = G.request) -> P.frame
step.analyze: DO extract(artifact = C.scope, schema = "context") -> V.analysis
RETURN P.frame, V.analysis
"""

_PAR_PROGRAM = """\
PROGRAM bench_par VERSION 1.0
INPUT
    G.goal = "parallel heterogeneous branches"
    C.scope = "src/"
PAR MAX 4
    step.code: DO search(query = G.goal, scope = C.scope) -> E.code
    step.review: DO summarize(source_refs = G.goal, budget = 50) -> E.review
    CALL protocol.framing(request = G.goal, scope = C.scope) -> P.frame, V.analysis
    step.author: DO delegate(goal = G.goal, constraints = C.scope, max_steps = 6) -> OUT.plan, OUT.metrics
BARRIER -> E.code, E.review, P.frame, V.analysis, OUT.plan, OUT.metrics
step.combine: DO report(committed_refs = [E.code, E.review], format = "markdown") -> ART.report
RETURN ART.report
"""


def builtin_cases(
    latency_seconds: float = 0.04,
) -> list[BenchmarkCase]:
    """The built-in benchmark cases from the case registry (issue #46).

    Returns one :class:`BenchmarkCase` per registered factory, in
    insertion order.  The default registry holds the three built-in
    cases from issue #26:

    1. ``linear-independent-6`` — six independent steps; the concurrent
       frontier overlaps them (speedup case).
    2. ``scatter-gather-8`` — eight fan-out candidates; the scatter
       drives the sequential plan loop by contract, so this measures the
       context-cost fan-out story, not latency (expected speedup ~1).
    3. ``par-heterogeneous-4`` — PAR MAX 4 with two DO branches, one
       CALL branch and one delegate branch; the baseline serializes the
       pool through a 1-slot budget, the variant releases 4 slots.

    Callers can extend the registry via :func:`register_case` before
    calling ``builtin_cases()`` to add custom cases without editing this
    module's internals, or pass an explicit list to
    :func:`run_benchmark` for one-off case sets.
    """
    return _default_registry.build_all(latency_seconds=latency_seconds)


# ----------------------------------------------------------------------
# Case registry (issue #46): builtin_cases() is backed by a registry
# of name → factory that callers can extend without editing this module's
# internals.  register_case() adds a factory; get_case() retrieves one;
# builtin_registry_names() lists registered names.
# ----------------------------------------------------------------------

_CaseFactory = Callable[..., BenchmarkCase]


class CaseRegistry:
    """A name → factory registry for benchmark cases.

    The default registry holds the three built-in cases under their
    canonical names.  Callers extend it via :func:`register_case` or
    by constructing their own ``CaseRegistry`` and calling
    :meth:`register` / :meth:`build` on it.
    """

    def __init__(self) -> None:
        self._factories: dict[str, _CaseFactory] = {}

    def register(
        self, name: str, factory: _CaseFactory
    ) -> None:
        """Register ``factory`` under ``name`` (overwrites if present)."""
        if not name or not name.strip():
            raise ValueError("CaseRegistry.register name must be nonempty")
        if not callable(factory):
            raise ValueError("CaseRegistry.register factory must be callable")
        self._factories[name] = factory

    def names(self) -> list[str]:
        """Registered names in insertion order."""
        return list(self._factories)

    def build(self, name: str, **kwargs: Any) -> BenchmarkCase:
        """Build a case from the factory registered under ``name``."""
        if name not in self._factories:
            raise KeyError(
                f"no benchmark case registered as {name!r};"
                f" known: {', '.join(self._factories) or '(none)'}"
            )
        return self._factories[name](**kwargs)

    def build_all(self, **kwargs: Any) -> list[BenchmarkCase]:
        """Build every registered case (insertion order)."""
        return [self.build(name, **kwargs) for name in self._factories]


_default_registry = CaseRegistry()


def _linear_factory(
    latency_seconds: float = 0.04, **kwargs: Any
) -> BenchmarkCase:
    return BenchmarkCase(
        name="linear-independent-6",
        program=_LINEAR_PROGRAM,
        max_workers=6,
        latency_seconds=latency_seconds,
        **kwargs,
    )


def _scatter_factory(
    latency_seconds: float = 0.04, **kwargs: Any
) -> BenchmarkCase:
    return BenchmarkCase(
        name="scatter-gather-8",
        program=_SCATTER_PROGRAM,
        max_workers=4,
        budget=ExecutionBudget(max_concurrent_workers=4),
        latency_seconds=latency_seconds,
        **kwargs,
    )


def _par_factory(
    latency_seconds: float = 0.04, **kwargs: Any
) -> BenchmarkCase:
    return BenchmarkCase(
        name="par-heterogeneous-4",
        program=_PAR_PROGRAM,
        max_workers=4,
        budget=ExecutionBudget(max_concurrent_workers=4),
        protocols={"framing": _PAR_PROTOCOL},
        latency_seconds=latency_seconds,
        **kwargs,
    )


_default_registry.register("linear-independent-6", _linear_factory)
_default_registry.register("scatter-gather-8", _scatter_factory)
_default_registry.register("par-heterogeneous-4", _par_factory)


def register_case(
    name: str, factory: _CaseFactory, *, registry: CaseRegistry | None = None
) -> None:
    """Register a custom benchmark case factory.

    By default adds to the module-level default registry shared by
    :func:`builtin_cases`; pass ``registry=`` to target a private one.
    """
    target = registry if registry is not None else _default_registry
    target.register(name, factory)


def builtin_registry_names() -> list[str]:
    """Names registered in the default case registry."""
    return _default_registry.names()
