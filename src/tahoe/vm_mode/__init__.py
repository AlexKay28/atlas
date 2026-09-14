"""TAHOE-VM: model as compiler + executor of its own reasoning program.

Stage 2 of the three-stage arc (see insights/three-stage-arc.md):
the model compiles a task into a TAHOE program, then executes it on itself —
one atomic self-subcall per reasoning step, with the harness holding refs,
validating output, and folding subcall contexts.

Design contract (insights/vm-design.md):
- Harness is dumb plumbing: ref store, parse validation, DONE checks,
  deterministic arithmetic, folding. No intelligence in the harness.
- Main context = task + program + ref table (O(refs) growth).
- Every subcall after the compiler uses a byte-identical static prefix
  (prefix-cache eligible).
- Whole execution is ONE trajectory: per-step verdicts (parse, type, done)
  are machine-computed — free process rewards for RL (Stage 3).
"""

from .executor import VMExecutor, VMResult

__all__ = ["VMExecutor", "VMResult"]
