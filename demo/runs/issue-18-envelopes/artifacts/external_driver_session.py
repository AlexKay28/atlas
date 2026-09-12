"""External driver session for the issue-18-envelopes demo run.

Drives demo/runs/issue-18-envelopes/program.think to completion through
the `tikhon next` / `tikhon submit` CLI only — no in-process coordinator,
no worker holding the store.  Each step: render the TaskEnvelope from the
event store, craft a ResultEnvelope for it, submit, repeat.  Artifacts
(envelopes, results, submit outcomes) are written next to this script.
"""

import json
import subprocess
import sys
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parent
RUN_DIR = ARTIFACTS.parent
REPO = RUN_DIR.parents[2]
PROGRAM = RUN_DIR / "program.think"
DB = RUN_DIR / "run.db"
RUN_ID = "issue-18-envelopes"
SEAL = (RUN_DIR / "seal.txt").read_text(encoding="utf-8").strip()

PAYLOADS = {
    "inv-1": {"plan": "seal program; implement envelope protocol + worker binding + CLI next/submit; test; verify"},
    "inv-2": {"patterns": [
        "coordinator dispatch seam is exactly (command, resolved_kwargs)",
        "map_results_to_targets maps full refs or unique leaf names",
        "atomic SUCCEEDED batch: succeeded + invocation_recorded + task_completed",
    ]},
    "inv-3": {"design": "TaskEnvelope/ResultEnvelope schema v1 dataclasses with strict from_json; external driver reuses coordinator plan/ledger machinery; ModelWorker prompts from TaskEnvelope and parses replies into ResultEnvelope"},
    "inv-4": {"patch": "src/tikhon/envelope.py (protocol + external driver), src/tikhon/worker_adapter.py (envelope binding), src/tikhon/cli.py (next/submit), tests/test_envelope.py"},
    "inv-5": "pass",
    "inv-6": {"verdict": "accepted", "suite": "571 passed", "audit": "OK"},
}


def tikhon(*argv: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "tikhon", *argv],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    artifacts = ARTIFACTS
    step_no = 0
    while True:
        step_no += 1
        rc, out, err = tikhon(
            "next", "--db", str(DB), "--run-id", RUN_ID,
            "--program", str(PROGRAM), "--seal", SEAL,
        )
        if rc != 0:
            print(f"next #{step_no} refused: {err.strip()}")
            return 1 if "terminal" not in err else 0
        envelope = json.loads(out)
        (artifacts / f"envelope-{step_no}.json").write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        command = envelope["command"]
        payload = PAYLOADS[envelope["invocation_id"]]
        result = {
            "schema_version": "1",
            "run_id": envelope["run_id"],
            "invocation_id": envelope["invocation_id"],
            "task_id": envelope["task_id"],
            "attempt": envelope["attempt"],
            "idempotency_key": envelope["idempotency_key"],
            "command": command,
            "status": "succeeded",
            "payload": payload,
            "evidence": [f"external-driver-session:{command}"],
            "error": None,
            "receipt": {
                "worker": "issue-18-external-driver-session",
                "usage": {"tokens": None, "cost": None,
                          "retries": 0, "elapsed_seconds": 0.0},
            },
        }
        result_path = artifacts / f"result-{step_no}.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rc, out, err = tikhon(
            "submit", "--db", str(DB), "--run-id", RUN_ID,
            "--invocation-id", envelope["invocation_id"],
            "--result-file", str(result_path),
        )
        if rc != 0:
            print(f"submit #{step_no} failed: {err.strip()}")
            return 1
        outcome = json.loads(out)
        (artifacts / f"submit-{step_no}.json").write_text(
            json.dumps(outcome, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"step {step_no} ({command}) -> {outcome['run_status']}")
        if outcome["run_status"] != "in_progress":
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
