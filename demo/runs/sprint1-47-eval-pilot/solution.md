# solution.md — sprint1-47-eval-pilot

GitHub issue #47: Protocol A/B evaluation — Tier-B pilot scaffolding
(arms 1+4 per #50 methodology). This is the execution issue for the
first end-to-end public-suite experiment, delivering the pilot
scaffolding (no live spend by the agent; secrets stay with the
orchestrator).

## What was built

### src/tikhon/eval.py (new, ~380 lines)

The arm runner module, built on the #46 benchmark harness:

- **`ArmSpec(name, kind)`** — names an arm and its kind:
  - `"react"`: plain tool-loop baseline prompt; the model runs
    unconstrained (simulated by constructing a define→search→fetch→
    report program from the task description in the scaffold path).
  - `"tikhon"`: sealed-program arm; the program is authored IN-LOOP
    by the model via the delegate authoring loop; every authoring
    attempt is COUNTED as a charged step per #50's authoring-parity
    clause.
  - Includes `worker_factory`, `max_workers`, `budget`, and
    `prompt_template` fields.

- **`TaskManifest`** — one task in a pilot: `task_id`, `description`,
  `expected_state`, `program_source`, `protocols`,
  `authoring_attempts_expected`.

- **`TrialRecord`** — durable per-trial record: `task_id`, `arm`,
  `result` (TrialResult), `usage` dict, `wall_seconds`,
  `authoring_attempts`, `event_store_path`, `run_id`.
  JSON-serializable; `to_json()` / `from_json()` roundtrip.

- **`TrialResult`** — pass/fail + `detail` + `failure_class`.

- **`ProgrammaticGrader`** — grader callable interface:
  `(actual_result, expected_state) -> TrialResult`.

- **`DBStateGrader`** — tau-bench-style DB-state matcher (documented
  example grader) with exact-match and partial `match_keys` modes.

- **`run_pilot(manifest, arms, model_config, grader, repetitions)`** —
  the ONE entry point: executes each task under each arm, grades the
  result, returns a `PilotReport`.

- **`PilotReport`** — full pilot output with `to_json()` and
  `to_markdown()` (mirroring #46's report pattern): per-task results,
  per-arm summary, authoring-parity table, honest caveats.

### eval/ (new)

- **`arms.yaml`** — arms 1 (react-baseline) and 4 (tikhon-core) per #50
  section 4.
- **`tau-bench-retail.yaml`** — tau-bench retail subset manifest stub:
  pinned task IDs placeholder list, env/model pinning fields,
  user-simulator freeze fields per #50 section 2.
- **`custom-battery.yaml`** — 3 deterministic tasks with fake workers
  proving the runner end-to-end.
- **`README.md`** — how to run (scaffold + live smoke).

### tests/test_eval.py (new, 28 tests)

- TrialRecord roundtrips (3 tests)
- DBStateGrader exact/partial/non-dict (5 tests)
- ArmSpec/TaskManifest validation (4 tests)
- run_pilot end-to-end on fake workers (8 tests)
- TrialResult factories (2 tests)
- Report to_json/to_markdown roundtrips (3 tests)
- Crash handling (1 test)
- Summary pass rate (1 test)
- Repetitions (1 test)

### docs/eval-pilot.md (new)

How to run (one command), #50 methodology pointers, what is NOT yet
live, the exact one-command live-smoke invocation for the orchestrator.

## Test results

```
PYTHONPATH=src python3 -m pytest -q
837 passed in 19.74s
```

(809 baseline + 28 new; baseline was 809 passed in 19.87s)

## Constraints honored

- Touched only: `src/tikhon/eval.py` (new), `eval/` (new),
  `tests/test_eval.py` (new), `docs/eval-pilot.md` (new),
  `demo/runs/sprint1-47-eval-pilot/` (new).
- Read-only modules used, never modified: `benchmarks.py`,
  `worker_adapter.py`, `runtime/`, `budgets.py`, `envelope.py`,
  `registry/`, `syntax/`, `cli.py`.
- Full suite: **837 passed** (809 pre-existing + 28 new) in **19.74s**.
- No git commit made.

## Live smoke command (orchestrator)

```bash
PYTHONPATH=src \
  TIKHON_WORKER_TRANSPORT=http \
  TIKHON_MODEL=glm-5-2 \
  TIKHON_API_BASE=https://api.example.com \
  TIKHON_API_KEY="$KEY" \
  python3 -c "
from tikhon.eval import run_pilot, ArmSpec, TaskManifest, DBStateGrader
tasks = [TaskManifest(task_id='retail-001', description='...', expected_state={...}, program_source='...')]
arms = [ArmSpec(name='react-baseline', kind='react'), ArmSpec(name='tikhon-core', kind='tikhon')]
report = run_pilot(tasks, arms, grader=DBStateGrader())
print(report.to_json())
"
```

## Deviations / limitations

- The react arm's "plain agent tool loop" is simulated by constructing
  a simple define→search→fetch→report program from the task
  description in the scaffold path.  In live runs this would dispatch
  a plain ReAct prompt to the model via the transport.
- Authoring attempts in the scaffold are pre-configured
  (`TaskManifest.authoring_attempts_expected`); in live runs the
  actual count is observed from CHILD_PLAN_AUTHORED events.
- Usage telemetry is zero-filled in the deterministic path; live
  workers populate tokens/cost through the same TrialRecord shape.
- Arms 2, 3, 5, 6 are future work per #50 section 4.
- Confidence intervals are a post-hoc analysis step per #50 section 5.
