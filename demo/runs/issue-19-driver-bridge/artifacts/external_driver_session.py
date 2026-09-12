"""External claim-driver session for the issue-19-driver-bridge demo run.

Drives demo/runs/issue-19-driver-bridge/program.think to completion
through the `tikhon ready` / `tikhon claim` / `tikhon submit
--claim-token` CLI only — no in-process coordinator, no worker holding
the store.  Each step: ready (renders the TaskEnvelope AND records the
fencing claim), craft a ResultEnvelope for it, submit with the claim
token, repeat.  Artifacts (handouts, results, submit outcomes) are
written next to this script.

On the first step the session also demonstrates the fencing semantics:
a second `ready` while the claim is fresh is refused with the same
claim token, and a wrong-token submit appends nothing.
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
RUN_ID = "issue-19-driver-bridge"
SEAL = (RUN_DIR / "seal.txt").read_text(encoding="utf-8").strip()

PAYLOADS = {
    "inv-1": {"plan": "seal program; implement ClaimBridge ready/claim/submit with fencing tokens on top of the Wave 8 driver; test; verify"},
    "inv-2": {"patterns": [
        "Wave 8 next/submit already renders TaskEnvelopes and commits ResultEnvelopes through coordinator machinery",
        "a CLAIMED overlay needs only INVOCATION_CLAIMED events; coordinator/resume already treat such invocations as non-terminal",
        "stale-claim reissue appends a fresh DISPATCHED so the envelope attempt fences the old token",
    ]},
    "inv-3": {"design": "ClaimBridge.ready renders via ExternalDriver.next_envelope then records INVOCATION_CLAIMED (uuid4 token, claimed_at UTC, envelope digest, claimant, claim_attempt); submit validates token + freshness then delegates to submit_result; expired claims re-issue with attempt+1 and the old token rejects"},
    "inv-4": {"patch": "src/tikhon/bridge.py (ClaimBridge), src/tikhon/cli.py (ready/claim subcommands + submit --claim-token), src/tikhon/runtime/events.py (INVOCATION_CLAIMED), tests/test_bridge.py"},
    "inv-5": "pass",
    "inv-6": {
        "patch": "src/tikhon/bridge.py (ClaimBridge), src/tikhon/cli.py (ready/claim subcommands + submit --claim-token), src/tikhon/runtime/events.py (INVOCATION_CLAIMED), tests/test_bridge.py",
        "tests": "pass",
    },
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


def result_for(envelope, payload) -> dict:
    return {
        "schema_version": "1",
        "run_id": envelope["run_id"],
        "invocation_id": envelope["invocation_id"],
        "task_id": envelope["task_id"],
        "attempt": envelope["attempt"],
        "idempotency_key": envelope["idempotency_key"],
        "command": envelope["command"],
        "status": "succeeded",
        "payload": payload,
        "evidence": [f"external-claim-driver-session:{envelope['command']}"],
        "error": None,
        "receipt": {
            "worker": "issue-19-external-claim-driver-session",
            "usage": {"tokens": None, "cost": 0.0, "retries": 0,
                      "elapsed_seconds": 0.4},
        },
    }


def main() -> int:
    step_no = 0
    while True:
        step_no += 1
        # Step 1 is claimed by name; the rest go through plain ready.
        argv = ["claim" if step_no == 1 else "ready"]
        rc, out, err = tikhon(
            *argv, "--db", str(DB), "--run-id", RUN_ID,
            "--program", str(PROGRAM), "--seal", SEAL,
            *(["--claimant", "opencode-agent"] if step_no == 1 else []),
        )
        if rc != 0:
            print(f"ready #{step_no} refused: {err.strip()}")
            return 1
        handout = json.loads(out)
        if handout.get("terminal"):
            (ARTIFACTS / "terminal.json").write_text(
                json.dumps(handout, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"terminal: {handout['status']} after {step_no - 1} steps")
            return 0
        assert handout["ready"] is True, handout
        (ARTIFACTS / f"handout-{step_no}.json").write_text(
            json.dumps(handout, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        envelope = handout["envelope"]
        command = envelope["command"]

        result_path = ARTIFACTS / f"result-{step_no}.json"
        result_path.write_text(
            json.dumps(result_for(envelope, PAYLOADS[envelope["invocation_id"]])),
            encoding="utf-8",
        )

        # Fencing demo (first step only), while the claim is fresh:
        # a second driver's ready is refused with the same claim token,
        # and a wrong-token submit appends nothing.
        if step_no == 1:
            rc, out, err = tikhon(
                "ready", "--db", str(DB), "--run-id", RUN_ID,
                "--program", str(PROGRAM), "--seal", SEAL,
            )
            fenced = json.loads(out)
            assert rc == 0 and fenced["ready"] is False, fenced
            assert (
                fenced["claim"]["claim_token"]
                == handout["claim"]["claim_token"]
            ), fenced
            (ARTIFACTS / "fenced-second-ready.json").write_text(
                json.dumps(fenced, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            rc, out, err = tikhon(
                "submit", "--db", str(DB), "--run-id", RUN_ID,
                "--invocation-id", envelope["invocation_id"],
                "--result-file", str(result_path),
                "--claim-token", "0" * 32,
            )
            assert rc == 1 and "claim token mismatch" in err, (rc, err)
            (ARTIFACTS / "wrong-token-error.txt").write_text(
                err, encoding="utf-8"
            )

        rc, out, err = tikhon(
            "submit", "--db", str(DB), "--run-id", RUN_ID,
            "--invocation-id", envelope["invocation_id"],
            "--result-file", str(result_path),
            "--claim-token", handout["claim"]["claim_token"],
        )
        if rc != 0:
            print(f"submit #{step_no} refused: {err.strip()}")
            return 1
        outcome = json.loads(out)
        (ARTIFACTS / f"submit-outcome-{step_no}.json").write_text(
            json.dumps(outcome, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"step {step_no}: {command} -> {outcome['run_status']}")


if __name__ == "__main__":
    raise SystemExit(main())
