# solution.md — issue-03-if-branches

GitHub issue #3: **IF branches with deterministic expressions**.

Seal: `e039349fee95f52648bc5d4b52c2eaf744176a0ceb9808d9be94b1effe8fc0bd`
(`demo/runs/issue-03-if-branches/program.think`, sealed with `tikhon lint` +
`tikhon seal` before any source edit; the digest still reproduces after all
edits because the program deliberately uses no `IF` lines).

## Expression grammar implemented

```
IF-line      := "IF" <condition> <statement>
<condition>  := <term> (("AND" | "OR") <term>)*          (left-assoc fold)
<term>       := "NOT"* <comparison>
<comparison> := <ref> ("==" | "!=") <json-literal>
              | "count" "(" <ref> ")" <op> <int>        (op: == != < <= > >=)
<statement>  := "STOP" <kind> "(" <ref>? ")"
              | "RETURN" <refs>
              | "step." <id> ":" "DO" <command>(args) "=>" targets
                  with the full invocation line syntax, including the
                  trailing REVISE/RETIRE correction clause
```

- `<ref>` is a typed reference (`PREFIX.name[.name...]`). A trailing dotted
  segment is the spec's **immutable field selection**: `V.tests.status`
  reads field `status` of the committed node `V.tests` (validation accepts a
  ref when any dotted prefix of it exists at the conditional's source
  position; evaluation resolves the longest committed prefix and walks the
  remaining fields, failing the run loudly on a non-mapping node or a
  missing field).
- Comparisons are JSON-strict (a bool never equals 0/1, same rule as DONE
  predicates). `count` requires a list-valued operand.
- `AND`/`OR` are left-associative (`a AND b OR c == ((a AND b) OR c)`) and
  short-circuit; `NOT` is a repeatable prefix.
- Parentheses are rejected ("parentheses are not supported in IF
  conditions"); ELSE and ELSE IF are rejected ("unsupported control
  construct ELSE"); no worker calls, clocks, or randomness inside
  conditions.

## Model

`Conditional(condition: str, statement: object, line: int)` — frozen
dataclass in `src/tikhon/syntax/model.py`; `condition` keeps the raw source
text, `statement` embeds the parsed `Stop` / `Return` / `Invocation` object.
Stored in `program.statements` in source position. Canonical JSON serializes
it as `{"kind":"conditional","condition":...,"statement":...}` with no line
number, so **pre-IF programs seal byte-identically** (verified against the
digest computed before any edit).

## Coordinator semantics

- STOP/RETURN conditionals may appear anywhere after their condition refs
  are produced (among invocations included). Each is **source-anchored**:
  the anchor is the number of plan entries preceding it, and it is
  evaluated right after that invocation commits (anchor 0 before the loop,
  anchor `len(plan)` after it). A fired terminal cancels every
  created-but-unreached task and finishes the run through the exact bare
  STOP/RETURN handling — `completed` maps to `succeeded`, other kinds are
  recorded verbatim, and a resolvable STOP ref becomes the `reason` payload.
- `IF <expr> DO ...` invocations are validated to appear **after every
  unconditional invocation line**; they occupy a plan entry carrying their
  condition, their ledger task is created lazily only when the branch
  fires, and a fired branch executes the exact invocation lifecycle
  (task_created → task_started → INVOCATION_READY → DISPATCHED →
  RESULT_RECEIVED → VALIDATION_PASSED → SUCCEEDED, state commit).
- A false condition skips its statement entirely: no task, no events, no
  state change; execution continues.
- A condition referencing a node that no longer resolves (e.g. retired
  mid-run) fails the run deterministically (no silent skip).

## Files changed

- `src/tikhon/syntax/parser.py` — IF removed from `_UNSUPPORTED`; ELSE
  rejection; condition scanner + `parse_condition`; `_parse_conditional_line`;
  `_parse_invocation_text` extracted (shared with IF-embedded DO lines);
  conditional validation branch; `_validate_invocation_statement` extracted
  (commit_targets=False for IF-DO); canonical-JSON serialization.
- `src/tikhon/syntax/model.py` — frozen `Conditional` dataclass.
- `src/tikhon/syntax/__init__.py` — exports `Conditional`, `parse_condition`.
- `src/tikhon/runtime/coordinator.py` — `evaluate_condition` (+ pure AST
  evaluator with field selection); `Conditional` plan entries with lazy task
  creation; source-anchored conditional evaluation; extracted
  `_terminal_return`/`_terminal_stop`; unreached-task cancellation.
- `tests/test_syntax.py` — 15 new tests (expression forms, AST shape,
  ref validation incl. field selection, ELSE/paren rejection, IF-DO
  ordering rule, malformed conditions, embedded-statement validation,
  frozen model, canonical JSON determinism, pre-IF seal regression pin,
  DONE-after-conditional rejection, terminal requirement).
- `tests/test_coordinator.py` — 14 new tests (Program-B flows, count over
  ref lists and selected fields, truth tables, missing/non-list operand
  errors, full lifecycle inside a true conditional, skipped false branch,
  atomic failure of a conditional step, conditional RETURN, gate before
  first invocation, resume after crash).
- `demo/runs/issue-03-if-branches/` — sealed `program.think`, `seal.txt`,
  `WORKLOG.md`, this file, `evaluation.json`.

## Full suite

`python3 -m pytest -q` → **540 passed** (baseline 484; the delta includes 29
new issue-#3 tests plus the concurrent issue-#8 wave's tests; no
pre-existing test was modified or dropped).
