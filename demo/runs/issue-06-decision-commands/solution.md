# Solution: issue-06-decision-commands

Implements GitHub issue #6: the six decision commands from the spec-02 catalog
now have complete `CommandSpec` contracts in the builtin registry.

## What changed

- `src/tikhon/registry/builtins.py` — added six contract factories in the exact
  style of the existing nine (`_define`, `_search`, ...) and extended
  `BUILTIN_FACTORIES` so `load_builtin_registry()` registers them:
  - `decompose` — goal/protocol -> bounded subgoals; children cover the parent
    and each child declares a stop check. PURE, INPUT_DIGEST, min tier T1,
    preferred T2, capability `goal_decomposition`.
  - `hypothesize` — question + evidence -> distinct falsifiable alternatives
    with falsifiers. READ_ONLY, NONE, `language_model`.
  - `compare` — options + criteria -> comparison; constraints applied before
    preferences, unknown cells explicit. READ_ONLY, INPUT_DIGEST, `language_model`.
  - `rank` — options + criteria -> ordering; tie and missing-evidence policies
    explicit. PURE, INPUT_DIGEST.
  - `challenge` — claim/decision -> counterevidence and ranked risks; strongest
    plausible failure cases checked. READ_ONLY, NONE, `language_model`.
  - `choose` — valid options + evidence -> decision `D` accepting one option or
    blocking with a typed reason. PURE, INPUT_DIGEST, fallback chain
    `("rank@1.0.0",)`.
- `tests/test_registry.py` — `BUILTIN_NAMES` extended to the fifteen catalog
  names, the exactly-nine test generalized to `test_builtin_registry_holds_exactly_the_catalog_commands`,
  and new parametrized tests: complete-contract resolution, presence in
  `builtin_registry().names()`, effect-class intent (decompose/choose PURE),
  and the originals-plus-six invariant. The existing registry-wide invariant
  tests (routing consistency, JSON roundtrip, contract completeness) now run
  over all fifteen names automatically.

## Tikhon protocol

- `program.think` written and sealed before any source edit; digest recorded in
  `seal.txt` and never modified afterwards. It uses only the nine previously
  registered commands.
- `scratch-program.think` (inside this run dir, written after the registry
  change) uses all six new commands and lints `valid` — evidence they resolve.
- `WORKLOG.md` carries one section per step with status, inputs, actions,
  outputs, evidence.

## Verification

- Baseline before edits: `163 passed`.
- Final: `200 passed` (163 baseline + 37 new/extended registry tests).
- Main program seal recomputed after all edits matches `seal.txt`.
