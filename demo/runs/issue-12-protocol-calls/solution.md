# solution.md — issue #12: protocol calls (CALL protocol.name with sealed protocol files)

## What was built

Procedural memory (CoALA) for Tikhon: recurring step sequences become
reusable, sealed sub-programs living in `protocols/`, invoked with

```
CALL protocol.framing(request = G.probe, scope = "src/tikhon") -> G.plan, V.analysis
```

## Grammar (src/tikhon/syntax/parser.py)

- `CALL` removed from `_UNSUPPORTED`; new `_CALL_RE` parses
  `CALL protocol.<segments>(args) -> refs` as a standalone statement.
  Protocol reference = mandatory `protocol.` prefix + dot-separated
  `[a-z][a-z0-9_]*` segments (docs/spec/01-language-and-state.md:
  `protocol = "protocol.", name`); arguments parse like invocation
  arguments (JSON literals, typed refs, ref lists); targets parse like
  invocation targets.
- New frozen dataclass `Call(protocol, args, targets, line)` in
  `src/tikhon/syntax/model.py`, exported from `tikhon.syntax` together
  with `load_protocol` / `protocol_file_path`.
- Canonical JSON gains a `"kind": "call"` statement form (source line
  excluded, like invocations), so CALL programs seal deterministically.

## Validation contract (validate_program, new `protocols_dir` parameter)

Default protocols dir: `protocols/` under the current working directory
(the repo root for CLI usage); overridable per call and via
`SequentialCoordinator(protocols_dir=...)`. For every CALL:

1. **Existence + lint**: `protocol.framing` loads
   `<protocols_dir>/framing.think` (deeper names keep dots in the stem:
   `protocol.ops.framing` → `ops.framing.think`); the file must parse and
   itself validate (recursively, sharing `known_commands`), and must end
   with RETURN (a CALL commits the protocol's RETURN refs) and contain at
   least one invocation.
2. **Argument arity**: CALL args resolve like invocation args (refs must
   be defined earlier; KB.* allowed) and must exactly cover the
   protocol's INPUT leaf names — every INPUT bound exactly once, no
   unknown or duplicate argument names.
3. **Target subset (the sound arity rule)**: CALL targets must be a
   subset (string equality) of the protocol's RETURN refs, so every
   committed target is a ref the protocol actually returns. Targets join
   the caller's available refs for later steps.
4. **Bounded recursion**: a protocol-name stack during validation rejects
   direct and transitive self-calls; nested protocol-call chains are
   capped at depth 8 (`_MAX_PROTOCOL_DEPTH`).

## Runtime (src/tikhon/runtime/coordinator.py)

`SequentialCoordinator.execute` builds a flat execution plan
(`_build_plan` → `_PlanEntry`): caller invocations keep their positions;
each CALL expands the protocol's invocations inline at the call site.

- **Ledger**: protocol tasks are created in the same up-front batch as
  caller tasks with text prefixed `protocol.framing:` (e.g.
  `protocol.framing: step.frame: DO define`); invocation ids continue the
  parent sequence (`inv-1..inv-n` across the protocol boundary) — no child
  namespace.
- **Binding**: the first entry of an expansion carries a bind tuple;
  before that step's own args resolve, the protocol's INPUT declarations
  are written into the shared run-state from the resolved CALL args
  (`_bind_protocol_inputs`), exactly like program declarations.
- **Commit**: the last entry of an expansion carries a finalize tuple (the
  closure mapping protocol RETURN refs → caller targets; identity under
  the subset rule). After that step's own targets commit, each caller
  target is committed from the value the protocol produced under the same
  reference (`_apply_call_finalizes`), merged into the step's SUCCEEDED
  delta. Finalizes run before VALIDATION_PASSED so a commit failure keeps
  the truthful event order.
- **Invariants preserved**: every event still binds task_id /
  invocation_id; exactly one RUN_FINISHED; failures (handler raise, arg
  resolution, binding, finalize) take the existing atomic failure path —
  the failing task and all pending protocol + caller tasks cancel
  together, state commits nothing beyond the failure point, replay after
  reopen is identical, `tikhon audit` returns OK.

## Deterministic loading / sealing

`load_protocol` is deterministic (same name + dir → same parsed program).
A caller's seal composition changes when a protocol changes: composite
seal hashing is deliberately NOT implemented (per the issue); callers
must re-seal after editing a protocol. This is documented in
`protocols/framing.think` and in `load_protocol`'s docstring.

## Files changed

- `src/tikhon/syntax/model.py` — frozen `Call` dataclass.
- `src/tikhon/syntax/parser.py` — CALL grammar, `_validate_call_contract`
  (existence, lint, arg arity, RETURN-subset targets, cycle + depth 8),
  `protocol_file_path`, `load_protocol`, canonical-JSON call form.
- `src/tikhon/syntax/__init__.py` — exports Call, load_protocol,
  protocol_file_path.
- `src/tikhon/runtime/coordinator.py` — `protocols_dir` constructor param,
  `_PlanEntry`, `_build_plan`, `_bind_protocol_inputs`,
  `_apply_call_finalizes`, plan-driven loop (task-text prefix, continuing
  invocation ids, finalize commit), unchanged failure path.
- `tests/test_syntax.py` — 19 new CALL tests (parse, seal, malformed,
  unknown protocol, arity, target subset, direct/transitive self-call,
  depth limit, nested chain, KB-target rejection, path mapping).
- `tests/test_coordinator.py` — 7 new tests (execution + prefixed ledger
  tasks, continuing invocation ids, replay after reopen, clean audit,
  atomic protocol-step failure, missing protocol before run creation,
  nested protocol call).
- `protocols/framing.think` — the example protocol (lints and seals).
- `demo/runs/issue-12-protocol-calls/` — protocol program, seal.txt,
  WORKLOG.md, call-demo.think (+ its seal) as live CLI evidence.

## Not touched (per constraints)

`src/tikhon/cli.py`, `src/tikhon/registry/`, `src/tikhon/runtime/events.py`,
`src/tikhon/runtime/tasks.py`, `src/tikhon/audit.py`, other `demo/runs/`,
`.opencode/`, `docs/`. The concurrent issue-#9 agent's coordinator/CLI/
registry edits were preserved; the full suite (397) is green with both
change sets in place.
