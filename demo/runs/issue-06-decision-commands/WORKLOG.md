# Worklog: issue-06-decision-commands

Seal: `bfbefbcf0964134aa3987eaae8c380694b89283e84315f6cf91e5790537b56e9`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to registry contracts only: six decision commands (decompose, hypothesize, compare, rank, challenge, choose) in src/tikhon/registry/builtins.py plus registry tests; no syntax, runtime, or CLI changes.
Outputs: `G.plan` = confirm baseline, write sealed program, extend builtins, extend tests, run full suite.
Evidence: Baseline run showed `163 passed in 0.46s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Located the contract factories and registry assembly in builtins.py, the frozen CommandSpec/Budget/FailureSpec/RoutingPolicy records in registry/spec.py, the closed enums in registry/enums.py, and the spec-02 catalog rows for the six verbs.
Outputs: `E.patterns` = builtins.py factory pattern, spec.py validators, enum vocabulary, catalog done-conditions.
Evidence: docs/spec/02-command-catalog.md lists decompose (children cover parent with stop checks), hypothesize (alternatives distinct and falsifiable), challenge (strongest plausible failure cases checked), compare (constraints before preferences; unknown cells explicit), rank (tie and missing-evidence policy applied), choose (accepted with one option or blocked with typed reason).

## step.read
Status: succeeded
Inputs: `E.patterns`
Actions: Read all nine existing CommandSpec factories end to end and the registry-wide invariants in tests/test_registry.py.
Outputs: `ART.sources` = complete existing-contract context.
Evidence: Existing tests assert `registry.names() == BUILTIN_NAMES`, so the BUILTIN_NAMES tuple in tests/test_registry.py must be extended together with the registry or the suite breaks.

## step.contracts
Status: succeeded
Inputs: `ART.sources`
Actions: Mapped every mandatory contract field (purpose, inputs, parameters, preconditions, outputs, effects, done, failures, effect_class, execution, capabilities, evidence, budget, idempotency, compensation, routing) onto the six decision verbs per the catalog rows and ADR-0003 tier semantics.
Outputs: `E.fields` = draft contracts: decompose PURE/T0, hypothesize READ_ONLY/T1 (language_model), compare PURE/T1, rank PURE/T0, challenge READ_ONLY/T1 (language_model), choose READ_ONLY/T1 (language_model); INPUT_DIGEST where inputs fully determine outputs.
Evidence: RoutingPolicy validation requires minimum, preferred, and validator tiers to be members of permitted_tiers; budgets and failure vocabularies follow the existing nine factories.

## step.draft
Status: succeeded
Inputs: `E.fields`
Actions: Wrote six complete factories (_decompose, _hypothesize, _compare, _rank, _challenge, _choose) in the exact style of the existing nine, and registered them in BUILTIN_FACTORIES ahead of load_builtin_registry.
Outputs: `P.specs` = six CommandSpec factories added to builtins.py.
Evidence: File diff confined to src/tikhon/registry/builtins.py.

## step.register
Status: succeeded
Inputs: `P.specs`
Actions: Extended tests/test_registry.py: BUILTIN_NAMES grew to the fifteen catalog names, the exactly-nine test was generalized to the full catalog, and new tests assert resolution, complete contracts, and presence in builtin_registry().names() for each new verb.
Outputs: `ART.registry` = updated builtins.py and tests/test_registry.py.
Evidence: Sealed program.think (digest in seal.txt) was written and hashed before the first source edit; program.think was never modified afterwards.

## step.check
Status: succeeded
Inputs: `ART.registry`, `C.done`
Actions: Linted a scratch program inside this run dir that invokes all six new commands, then ran the full pytest suite.
Outputs: `V.tests` = all checks passed.
Evidence: `scratch-program.think` lints `valid` against the local source (PYTHONPATH=src); full suite `200 passed` (163 baseline + 37 new or extended registry tests).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the program seal and checked every acceptance condition against the goal.
Outputs: `V.result` = goal satisfied.
Evidence: Seal digest recomputed after all edits equals `seal.txt` (`bfbefbcf...37b56e9`); program.think unchanged since sealing; all six commands resolve with complete contracts and registry invariants hold.
