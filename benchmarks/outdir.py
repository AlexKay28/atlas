"""Run-directory helper: every experiment writes into its own directory.

Lesson from the 2026-09-14 session (twice): a later run overwrote an earlier
run's raw data, destroying comparability. Runners must never write to a fixed
filename at the results root.

Usage:
    from outdir import make_run_dir
    out_dir = make_run_dir("skill-cmp-gsm8k")
    # -> benchmarks/results/runs/2026-09-14T2259_skill-cmp-gsm8k/
    (out_dir / "trials.json").write_text(...)

Set RESULTS_ROOT to relocate; set RUN_TAG to label the directory.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

RESULTS_ROOT = Path(
    os.environ.get(
        "RESULTS_ROOT",
        Path(__file__).resolve().parent / "results",
    )
)


def make_run_dir(name: str, results_root: Path | None = None) -> Path:
    """Create and return a unique run directory under results/runs/."""
    root = Path(results_root) if results_root else RESULTS_ROOT
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    tag = os.environ.get("RUN_TAG", "")
    dirname = f"{stamp}_{name}" + (f"_{tag}" if tag else "")
    run_dir = root / "runs" / dirname
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
