# Eval Pilot — Protocol A/B Evaluation Scaffolding (issue #47, methodology #50)

This directory contains the configuration for the first Tier-B pilot run
of the Tikhon protocol A/B evaluation.

## Contents

- `arms.yaml` — arms 1 (react baseline) and 4 (tikhon core) per #50 section 4
- `tau-bench-retail.yaml` — tau-bench retail subset manifest stub (placeholder task IDs)
- `custom-battery.yaml` — 3 deterministic tasks with fake workers proving the runner end-to-end

## How to run

### Scaffold (deterministic, no live model)

```bash
PYTHONPATH=src python3 -m pytest tests/test_eval.py -q
```

### Live smoke (orchestrator post-merge with TIKHON_* env)

```bash
PYTHONPATH=src TIKHON_WORKER_TRANSPORT=http TIKHON_MODEL=glm-5-2 \
  TIKHON_API_BASE=https://api.example.com TIKHON_API_KEY=$KEY \
  python3 -c "
from tikhon.eval import run_pilot, ArmSpec, TaskManifest, DBStateGrader
import json
tasks = [TaskManifest(task_id='retail-001', description='...', expected_state={...}, program_source='...')]
arms = [ArmSpec(name='react-baseline', kind='react'), ArmSpec(name='tikhon-core', kind='tikhon')]
report = run_pilot(tasks, arms, grader=DBStateGrader())
print(report.to_json())
"
```

See `docs/eval-pilot.md` for full methodology pointers.
