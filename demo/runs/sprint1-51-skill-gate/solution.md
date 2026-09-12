# Solution — Issue #51: Skill/MCP Discovery Gate

## Files Changed

1. **`.opencode/skills/tikhon-demo/SKILL.md`** — Added "Step 0 — Skill/MCP
   Inventory" as a MANDATORY pre-plan section with:
   - The one-line decision rule: *local match → load; local miss → ahood
     search → pin → load; no match → proceed and say so*
   - Full procedure (local skills, local MCP/tools, ahood remote fallback,
     no-match case)
   - ahood traps: installed layout `.claude/skills/{owner}@{skill}`,
     publish ≠ public, versioned pins via `ahood skill update`, `AHOOD_TOKEN`
     for CI, worktree workers rely on globally installed skills + ahood
   - Declaration convention: `program.think` records relied-on skills via
     INPUT declarations; WORKLOG Inputs cite loaded skills per step
   - Renumbered Required Workflow steps (now 1-9 with Step 0 as step 3)

2. **`src/tikhon/worker_adapter.py`** — Added inventory-check instruction
   to the T3 delegate authoring prompt (the `if envelope.command ==
   "delegate"` branch in `_build_prompt`). The added text instructs the
   worker to run the Step 0 inventory before authoring a child plan.
   Non-T3 paths are unchanged.

3. **`tests/test_docs.py`** — Added 2 test functions:
   - `test_skill_md_has_step0_inventory_gate`: asserts SKILL.md contains
     "Step 0", "skill/mcp", "local match", "ahood skill search",
     "ahood skill add", "skills.lock.json"
   - `test_worker_adapter_t3_prompt_has_inventory_check`: asserts
     worker_adapter.py contains "Step 0", "ahood skill search",
     "ahood skill add", "skills.lock.json"

## Tests

- Baseline: 854 passed
- After changes: 856 passed (854 + 2 new)
- No regressions

## README Note

The README has "## Agent Demo" (not "## Agent workflow"), so per
instructions no README edit was made.

## Run

- Run ID: sprint1-51-skill-gate
- Seal: 9eff9ca1bada019e5fa7981ec34b7227cdc82f1d7f792e1d6fe5c9c83909b450
