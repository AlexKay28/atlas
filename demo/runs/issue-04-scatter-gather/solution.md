# Solution — issue #4: SCATTER/GATHER bounded fan-out with USING all|any|ranked judges

## Naming resolution (issue #27 alignment, resolved before implementation)

The draft spec's join-rule terminology is canonical; the issue body's names are
accepted aliases, normalized at parse time so both spellings parse and seal
identically:

| Canonical (draft spec) | Accepted alias | Semantics |
|---|---|---|
| `USING all`    | —              | every candidate must succeed; alias = list of candidate values in candidate order |
| `USING any`    | `first`        | first terminal success wins — resolved deterministically as the **lowest candidate index that succeeds** (the spec's "arrival time is not semantic" rule; candidates evaluate in collection order) |
| `USING ranked` | `best`         | an explicit judge invocation scores each candidate; **max score wins, ties break to the lowest candidate index** |

`USING any` additionally implements the spec's loser cancellation: candidates
after the winner are cancelled (`task_cancelled`) without being started, and a
failed candidate is recorded as a loser (its task cancelled with a `reason`
payload; the failure text lands in the gather's selection evidence). To keep
`audit.py`'s truthfulness invariant intact (a run that finishes `succeeded`
may not contain FAILED events — untouchable this run), losers never emit
FAILED events while the run can still succeed; if **all** candidates lose,
each loser records its FAILED event in the final failure batch and the run
finishes failed through the standard path.

CONCURRENCY vs TOTAL-WORK (issue #27): `MAX n` is the total-work bound — a
runtime list longer than `MAX` fails the run, a shorter one iterates its
actual length. Candidate dispatch deliberately executes **sequentially in
collection order** in this run: it makes `any`'s "first success", `ranked`'s
tie-break and replay identity deterministic by construction, keeps the strict
single-IN_PROGRESS ledger invariant intact, and passes the required tests
under any `max_workers` (verified: identical event shapes at `max_workers=1`
and `4`). The Wave 10 budget machinery is still honored at the dispatch
boundary — every candidate and judge worker call goes through
`_execute_worker_call(gate)` (global deadline, per-invocation deadline,
concurrency slot). Parallel fan-out dispatch remains future work (see
limitations).

## Final grammar (as implemented)

```
SCATTER <item-ref> IN <collection-ref> MAX <int>
  step.<id>: DO <command>(args) -> <target>[, <target>...]

GATHER <step-id>|step.<step-id> AS <alias-ref> USING all|any|ranked|first|best [JUDGE step.<id>]
  step.<judge-id>: DO <command>(args) -> <score-target>        # only when JUDGE declared
```

- The SCATTER line is followed by exactly **one indented body step line**
  (mirroring INPUT declarations' indentation rule). The GATHER must
  **directly follow** its SCATTER block. A declared JUDGE step is defined by
  the indented line following the GATHER, whose step id must match.
- `<item-ref>` is a fresh loop-scoped reference (any valid typed ref, e.g.
  `X.part`) bound per candidate inside the body and judge steps only; it is
  never a committed node and not visible after the block. `<collection-ref>`
  must name an existing committed node that is a list at runtime.
- The body step's targets are **candidate-scoped**: each candidate k
  (1-based) commits `<alias>.c<k>.<target-leaf>` nodes — never the raw
  target names. Duplicate target leaves in the body are rejected (they
  would collide in the scoped namespace).
- The judge step (required exactly when the canonical mode is `ranked`;
  rejected for `all`/`any`) is a single-target scoring template executed
  once per candidate with the item ref bound to the candidate's collection
  element and the body's target refs bound to that candidate's produced
  values. Judge targets are never committed. Score extraction
  (`judge_score`): number/bool directly; `"passed"` → 1.0 (any other string
  0.0); mapping prefers a numeric `score` field, else `status == "passed"`
  → 1.0 / 0.0; anything else fails the run through the standard path.
- The body/judge steps cannot carry REVISE/RETIRE (corrections are
  undefined per candidate) or DONE predicates (never attached inside the
  block; the judge ignores none — programmatic `done` on a judge fails the
  gather).
- After the join commits, `<alias-ref>` is a normal committed node (usable
  in RETURN, `count(...)` conditions, later arguments).
- Canonical JSON: `{"kind":"scatter", item_ref, collection_ref, max, body}`
  and `{"kind":"gather", step_id, alias, mode, judge}` with the mode in its
  canonical spelling; pre-#4 programs seal byte-identically (pinned by
  tests, and the sealed demo digest still reproduces).

## Runtime design

- **Plan**: a `Scatter` statement is one plan entry; its `Gather` is the
  next entry. Both get ledger tasks in the up-front creation batch.
- **Expansion**: at execution time the scatter resolves the committed
  collection (non-list or `len > MAX` fails the run atomically), batch-creates
  one ledger task per candidate (`step.<id>: DO <command> [candidate k]`),
  and executes candidates **in collection order** through the normal
  invocation machinery: task start, INVOCATION_READY, INVOCATION_DISPATCHED
  (idempotency key `"<run_id>:inv-<K>.cand<k>"`), RESULT_RECEIVED,
  VALIDATION_PASSED, and the atomic SUCCEEDED batch committing the
  candidate-scoped delta. Candidate invocation ids are
  `inv-<K>.cand<k>` — distinct from all positional ids and derivable from
  the plan alone.
- **Scatter entry terminality**: the scatter's own ledger task stays
  PENDING while candidates run (the strict single-IN_PROGRESS ledger
  invariant forbids overlapping it with candidate tasks) and starts +
  completes in the entry's terminal batch, whose SUCCEEDED carries an empty
  delta plus an expansion record (`candidates`, `winner`, `losers`) that
  the gather reads as the single source of truth.
- **Join**: `all` gathers every candidate's value in candidate order
  (multi-target bodies join a list of `{leaf: value}` mappings); `any`
  commits the winner's value; `ranked` runs the judge per candidate and
  commits the max score (ties → lowest index). The gather's task completion
  evidence records the selection (winner, scores, losers with their errors)
  — "gather records the selection evidence" — and the SUCCEEDED payload
  carries a structured `gather` selection record.
- **Failure**: any candidate failure under `all`/`ranked` fails the run
  atomically (candidate FAILED + scatter task + remaining candidate tasks +
  later plan tasks cancelled, RUN_FINISHED failed). Under `any` a failing
  candidate is a recorded loser; only if all candidates lose does the run
  fail. Collection-level failures (non-list, MAX exceeded, no candidates
  under `any`/`ranked`) fail on the scatter entry itself.
- **Concurrency**: programs containing SCATTER/GATHER always drive the
  sequential plan loop (metadata records the requested `max_workers`
  without switching the plan frontier on); the budget gate still wraps
  every candidate/judge dispatch.
- **Resume/crash**: `_resume_existing_run` splits SUCCEEDED ids into
  positional and `inv-<K>.cand<k>` candidate ids (candidates validated
  against the plan's scatter entries; the positional prefix invariant is
  unchanged), allows extra ledger tasks only when they are candidate tasks
  of the plan's scatter bodies, and re-drives the scatter idempotently:
  committed candidates are skipped (their scoped nodes replay into state),
  an in-flight candidate re-executes at-least-once, under `any` the
  first committed candidate is the winner and remaining candidates are
  cancelled without re-execution. The gather re-derives the join from
  committed events, so gathered state is identical after reopen (tested
  across five crash windows, including mid-scatter and before the gather
  commit).

## Files changed

- `src/tikhon/syntax/model.py` — frozen `Scatter` / `Gather` statement nodes.
- `src/tikhon/syntax/parser.py` — SCATTER/GATHER removed from `_UNSUPPORTED`;
  block parsers (`_parse_scatter_block`, `_parse_gather_line`,
  `_consume_block_line`), alias normalization (`first`→`any`, `best`→`ranked`),
  validation (`_validate_scatter_statement`, `_validate_gather_statement`,
  scatter-aware statement loop), canonical serialization.
- `src/tikhon/syntax/__init__.py` — export `Scatter`, `Gather`.
- `src/tikhon/runtime/coordinator.py` — scatter/gather plan entries and task
  texts, anchor indexing, sequential-drive gating for scatter programs,
  `_execute_scatter_entry` / `_execute_scatter_candidate` /
  `_execute_gather_entry`, failure batches, candidate-id helpers,
  `judge_score`, scatter-aware resume invariants.
- `tests/test_scatter.py` — new (55 tests). `tests/test_syntax.py` — additive
  export/round-trip test. `demo/runs/issue-04-scatter-gather/` — protocol
  artifacts (program.think sealed before any source edit, seal.txt, WORKLOG.md).

## Acceptance (issue #4)

- Reference Program A (research) shape parses and executes with deterministic
  workers: `test_research_style_program_executes_with_deterministic_workers`
  (decompose → SCATTER over parts → gather all → synthesize → report), plus a
  ranked variant. The draft spec's indexed targets (`E.urls[Q.part]`) are a
  draft-spec feature outside the implemented one-line grammar; the equivalent
  unindexed form with candidate-scoped commits is used (see deviations).
- Crash/replay: gathered state identical after reopen
  (`test_gathered_state_identical_after_reopen`,
  `test_replay_identity_across_two_fresh_runs`, parametrized five-window
  crash/resume with no duplicate commits, audit-clean).
- Losers recorded, not committed: `test_using_any_first_success_wins_and_losers_are_cancelled`
  (loser tasks cancelled with reasons, gather evidence carries the failure,
  no FAILED events, winner's value committed).

## Deviations / limitations

1. **Sequential candidate dispatch** (per issue #27's CONCURRENCY/TOTAL-WORK
   split): fan-out parallelism up to `max_workers` is not implemented; the
   budget gate is honored per dispatch and MAX bounds total work. The issue's
   wording is permissive ("may dispatch in parallel"), and determinism,
   replay identity and the strict single-IN_PROGRESS ledger are preserved by
   construction.
2. **No FAILED events for USING-any losers while the run can still succeed**:
   forced by `audit.py`'s `run_finished_status_mismatch` invariant (untouchable
   file). Loser failures are recorded via task cancellation `reason` payloads
   and the gather's selection evidence; retroactive FAILED events are emitted
   only when the whole join fails.
3. **External driver (`tikhon next`/`submit`) does not support scatter
   programs**: `envelope.py` (untouchable) rejects IF/CALL programs before
   plan inspection but has no Scatter branch, so a scatter program driven
   externally raises `AttributeError` instead of a clean `DriverError`.
   Out of scope for #4.
4. **Scatter inside protocols**: not exercised by tests; mechanically a CALL
   child run drives its own plan sequentially, so it should work, but it is
   untested this run.
5. The demo `program.think` intentionally does not use SCATTER/GATHER (the
   sealed program predates the feature, per the run protocol); the registry
   has 17 registered commands (the issue text says 22 — counted discrepancy,
   the program only uses registered commands).
