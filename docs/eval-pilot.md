# Eval Pilot — Protocol A/B Evaluation (issue #47, methodology #50)

## Overview

This document describes the Tier-B pilot scaffolding for the first
end-to-end Protocol A/B evaluation: does wrapping the same model in the
TAHOE protocol (sealed plan, registered handlers, DONE gates,
evidence worklog) improve task success, reliability, and recoverability
vs a plain agent loop?

The authoritative methodology lives in issue #50 (six arms, authoring
parity, metrics, analysis rules). This pilot implements **arms 1 and 4**
per #50 section 4:

- **Arm 1 (react-baseline)**: plain agent/ReAct-style execution — no
  sealed-program scaffolding; the model runs unconstrained with a
  tool-loop baseline prompt.
- **Arm 4 (tahoe-core)**: TAHOE core, sequential execution, no learned
  protocols — the program is authored IN-LOOP by the model via the
  delegate authoring loop; every authoring attempt is COUNTED as a
  charged step per #50's authoring-parity clause.

Both arms use the same model/version, tools, environment, grader and
resource ceilings per #50 section 4.

## What is built (scaffolding — no live spend)

### src/tahoe/eval.py

The arm runner module, built on the #46 benchmark harness:

- **`ArmSpec(name, kind)`**: names an arm and its kind (`"react"` or
  `"tahoe"`). Includes `worker_factory`, `max_workers`, `budget`.
- **`TaskManifest`**: one task in a pilot (task_id, description,
  expected_state, program_source, protocols, authoring_attempts_expected).
- **`TrialRecord`**: durable per-trial record (task_id, arm, result,
  failure_class, usage dict, wall, authoring_attempts, event-store ref).
  JSON-serializable; `to_json()` / `from_json()` roundtrip.
- **`TrialResult`**: pass/fail + detail + failure_class.
- **`ProgrammaticGrader`**: grader callable interface
  `(actual_result, expected_state) -> TrialResult`.
- **`DBStateGrader`**: tau-bench-style DB-state matcher (documented
  example grader) with optional `match_keys` for partial-credit.
- **`run_pilot(manifest, arms, model_config, grader, repetitions)`**:
  the ONE entry point — executes each task under each arm, grades the
  result, returns a `PilotReport`.
- **`PilotReport`**: full pilot output with `to_json()` and
  `to_markdown()` (mirroring #46's report pattern).

### eval/

- **`arms.yaml`**: arms 1 and 4 configuration per #50 section 4.
- **`tau-bench-retail.yaml`**: tau-bench retail subset manifest stub
  with pinned task IDs (placeholder list), env/model pinning fields,
  user-simulator freeze fields per #50 section 2.
- **`custom-battery.yaml`**: 3 deterministic tasks with fake workers
  proving the runner end-to-end.
- **`README.md`**: how to run.

### tests/test_eval.py

28 tests: TrialRecord roundtrips, authoring attempts charged on tahoe
arm, report to_json roundtrips, DBStateGrader works, full pilot on
fake workers runs green via ONE entry point, crash handling, validation.

## How to run

### Scaffold (deterministic, no live model)

```bash
PYTHONPATH=src python3 -m pytest tests/test_eval.py -q
```

### Full test suite (baseline 809 + 28 new = 837)

```bash
PYTHONPATH=src python3 -m pytest -q
```

### Live smoke (orchestrator post-merge with TAHOE_* env)

This is the exact one-command invocation the orchestrator should run
with TAHOE_* env to smoke-test the pilot with a live model:

```bash
PYTHONPATH=src \
  TAHOE_WORKER_TRANSPORT=http \
  TAHOE_MODEL=glm-5-2 \
  TAHOE_API_BASE=https://api.example.com \
  TAHOE_API_KEY="$KEY" \
  python3 -c "
from tahoe.eval import run_pilot, ArmSpec, TaskManifest, DBStateGrader

tasks = [
    TaskManifest(
        task_id='retail-001',
        description='Return the order status for order 42',
        expected_state={'order_id': 42, 'status': 'confirmed'},
        program_source='''
PROGRAM task_001 VERSION 1.0
INPUT
    G.task = \"Return the order status for order 42\"
step.understand: DO define(request = G.task) -> P.goal
step.report: DO report(committed_refs = P.goal, format = \"json\") -> OUT.answer
RETURN OUT.answer
''',
    ),
]
arms = [
    ArmSpec(name='react-baseline', kind='react'),
    ArmSpec(name='tahoe-core', kind='tahoe'),
]
report = run_pilot(tasks, arms, grader=DBStateGrader())
print(report.to_json())
"
```

## #50 Methodology pointers

| #50 section | What this pilot addresses |
|---|---|
| §1 Qualities | Correctness (grader), token/cost efficiency (usage dict on TrialRecord), repeated-run reliability (repetitions parameter for pass^k), authoring usability (authoring_attempts charged) |
| §2 Benchmark shortlist | tau-bench retail subset (manifest stub with pinned task IDs placeholder); custom battery for deterministic validation |
| §3 Tiered strategy | Tier B pilot (small real-model pilot); Tier A coverage via deterministic tests |
| §4 Experimental conditions | Arms 1 (react) and 4 (tahoe core, sequential); authoring parity: program authored IN-LOOP, every attempt charged |
| §5 Analysis and reporting | Per-task results, usage/wall deltas, authoring attempts charged; paired task comparisons; pass^k via repetitions |
| §6 Implementation deliverables | Task manifests, shared condition runner, durable trial records, JSON export, human-readable reports |

## What is NOT yet live

- **Real tau-bench environment**: the tau-bench retail manifest is a
  stub with placeholder task IDs; the orchestrator must verify primary
  sources, pin exact versions/task IDs, and configure the tau-bench
  environment before live runs.
- **Live GLM-5.2 smoke**: the scaffold uses deterministic fake workers
  (sleep+echo); the orchestrator runs the live smoke command above with
  TAHOE_* env.
- **Usage telemetry**: zero-filled in the deterministic path; live
  workers populate tokens/cost through the same TrialRecord shape.
- **Arms 2, 3, 5, 6**: concise NL reasoning (Chain-of-Draft-style),
  structured NL state/plan, TAHOE with learned protocols, and TAHOE
  with bounded parallel/nested are future arms per #50 section 4.
- **Confidence intervals**: the pilot scaffolding records per-trial
  results; CI computation is a post-hoc analysis step per #50 section 5.
