# Formal Operational Semantics for TAHOE

- Status: Draft 0.1
- Source: issue #70 (formal semantics); issues #68 (LOOP), #69 (TRY), #24 (PAR), #76 (FIRST), #77 (AWAIT), #78 (APPROVE), #80 (REFORMULATE), #81 (history), #83 (IF/ELSE)
- Scope: mathematical foundations for the TAHOE executable thinking language
- References:
  - [ADR-0001: Graph-Based Language](adr-0001-ai-thinking-language.md) — node and link types
  - [ADR-0002: Executable Thinking Language](adr-0002-executable-thinking-language.md) — execution model
  - [Reasoning Language Foundation](reasoning-language-foundation.md) — design thesis and experiment register

---

## 1. State Model

### 1.1 Typed Graph State

**Definition (State).** A state is a typed graph σ = (N, L) where:

- N is a set of typed nodes. Each node n ∈ N carries:
  - A type τ(n) ∈ {G, Q, CTX, C, P, PF, F, E, A, H, O, K, D, X, V, R, U, OUT, ART, PR}
  - An identifier id(n), unique within σ
  - A value val(n), drawn from the domain of τ(n)
  - A revision rev(n) ∈ ℕ, incremented on each mutation
- L is a set of typed links. Each link ℓ ∈ L carries:
  - A source node src(ℓ) ∈ N
  - A target node tgt(ℓ) ∈ N
  - A link type λ(ℓ) ∈ {supports, contradicts, depends_on, constrains, answers, derived_from, tests, mitigates, selects, rejects, precedes, refines, produces}

The node types and their roles are defined in ADR-0001 §Core Node Types.

### 1.2 EventLog

**Definition (EventLog).** An event log E = e₁ · e₂ · ··· · eₙ is an append-only sequence of events. Each event eᵢ carries:

- seq(eᵢ) = i (logical sequence number)
- type(eᵢ) ∈ {DISPATCH, RESULT, COMMIT, SUCCEEDED, REJECTED, VALIDATION_PASSED, VALIDATION_FAILED, SCATTER_DISPATCH, GATHER_COMMIT, LOOP_STARTED, LOOP_ITERATION, LOOP_EXITED, LOOP_EXHAUSTED, CHILD_STARTED, CHILD_TERMINAL, CHILD_ADOPTED, RUN_FINISHED, FAILED, BLOCKED, TRY_STARTED, TRY_BRANCH_SUCCEEDED, TRY_BRANCH_CANCELLED, TRY_COMPLETED, PAR_JOINED, FIRST_EVENT_MATCHED, AWAIT_SUSPENDED, AWAIT_RESUMED, APPROVAL_REQUESTED, APPROVAL_GRANTED, APPROVAL_DENIED, EXTERNAL_EVENT, PLAN_REFORMULATED}
- payload(eᵢ): typed data associated with the event
- causation(eᵢ): the seq of the event that caused this one (forming a causal chain)

Append is denoted E · e, yielding E' = e₁ · ··· · eₙ · e.

### 1.3 Configuration

**Definition (Configuration).** A configuration is a triple:

⟨P, σ, E⟩

where:

- P is the program (a sequence of instructions, possibly with a remaining-work suffix)
- σ is the current committed state
- E is the current event log

A terminal configuration is one where P = ε (empty program) or P = STOP kind(ref).

### 1.4 State Projection

The committed state σ is a deterministic projection of the event log given the initial state:

σ = project(σ₀, E)

where project replays COMMIT events in sequence order. This ensures the coordinator is deterministic given E, as established in ADR-0002 §Determinism and Reproducibility.

---

## 2. Small-Step Operational Semantics

We define transition rules of the form:

⟨P :: σ, E⟩ → ⟨P' :: σ', E'⟩

where P :: σ denotes the program P operating on state σ, and E is the event log. A rule fires when its premises (above the line) are satisfied.

### 2.1 DO Invocation

A DO command dispatches a bounded unit of work to a worker agent, validates the result, and commits the delta.

```
preconditions(σ) hold
──────────────────────────────────────────────  (DO-DISPATCH)
⟨DO cmd(args) -> targets :: σ, E⟩ → ⟨σ, E · DISPATCH(σ, cmd, args)⟩
```

The coordinator dispatches cmd with resolved args and the relevant state slice to a worker. The state σ does not change; only an event is appended. The configuration now waits for a result event.

```
worker returns value v
validate(v, cmd, σ) = ok
δ = {targets ↦ v}
──────────────────────────────────────────────  (DO-COMMIT)
⟨σ, E · RESULT(v)⟩ → ⟨σ ∪ δ, E · COMMIT(δ) · SUCCEEDED⟩
```

The worker returns a value v. The validator checks v against the command contract (type, schema, evidence, done condition — see ADR-0002 §Definition of Done for an Atomic Invocation). If validation passes, the delta δ is committed: σ ∪ δ means applying new nodes and links, incrementing revisions of any modified nodes. The SUCCEEDED event marks the terminal state of this invocation.

```
worker returns value v
validate(v, cmd, σ) = fail(reason)
──────────────────────────────────────────────  (DO-REJECT)
⟨σ, E · RESULT(v)⟩ → ⟨σ, E · REJECTED(reason)⟩
```

If validation fails, no state change occurs. The REJECTED event carries the failure reason. Recovery is governed by the retry policy (ADR-0002 §Failure Semantics): a retry must change conditions (different source, larger budget, repaired input).

### 2.2 DONE Predicate

A DONE predicate evaluates a boolean condition over the committed state. It is a deterministic check, not a worker call.

```
eval(δ, σ ∪ δ) = true
──────────────────────────────────────────────  (DONE-PASS)
⟨DONE δ :: σ', E⟩ → ⟨σ', E · VALIDATION_PASSED⟩
```

```
eval(δ, σ ∪ δ) = false
──────────────────────────────────────────────  (DONE-FAIL)
⟨DONE δ :: σ', E⟩ → ⟨σ', E · VALIDATION_FAILED · REJECTED⟩
```

Here δ is the set of refs produced by the preceding DO, σ' = σ ∪ δ is the state after commit, and eval applies the predicate logic (equals, in, count, matched, AND, OR, NOT) over the committed state. The predicate references only committed refs, so evaluation is deterministic. See `src/tahoe/syntax/parser.py:590-647` for the implemented predicate grammar.

### 2.3 IF Conditional (with ELSE, issue #83)

The IF instruction evaluates a condition over committed state and selects one of two branches. The coordinator applies the branch; a worker may recommend but cannot choose.

```
eval(cond, σ) = true
──────────────────────────────────────────────  (IF-TRUE)
⟨IF cond S₁ ELSE S₂ :: σ, E⟩ → ⟨S₁ :: σ, E⟩
```

```
eval(cond, σ) = false
──────────────────────────────────────────────  (IF-FALSE)
⟨IF cond S₁ ELSE S₂ :: σ, E⟩ → ⟨S₂ :: σ, E⟩
```

The condition cond is a deterministic expression over committed refs (==, !=, count(), AND, OR, NOT). No worker is involved. The selected branch S₁ or S₂ replaces the IF construct in the remaining program. See `src/tahoe/syntax/parser.py:263-289` for the implemented single-line IF; the ELSE clause extends this to two-branch selection (issue #83).

### 2.4 SCATTER / GATHER

SCATTER dispatches a body for each element of a collection in parallel (bounded by MAX k). GATHER joins the results according to a mode.

```
collection = lookup(ref, σ) = [v₁, ..., vₙ]
──────────────────────────────────────────────  (SCATTER)
⟨SCATTER x IN ref MAX k ... GATHER :: σ, E⟩
  → ⟨[body[x↦v₁], ..., body[x↦vₙ]] :: σ, E · SCATTER_DISPATCH⟩
```

The collection is resolved from the committed state. Each body instance is a copy of the loop body with x bound to a distinct element. The MAX k bound limits concurrency; if n > k, dispatch proceeds in batches. All body instances execute independently; their results become visible only through GATHER.

```
results = [r₁, ..., rₘ]    m = count(SUCCEEDED branches)
join_mode = all:  m = n required
join_mode = any:  m ≥ 1 required
join_mode = k(n): m ≥ n required
──────────────────────────────────────────────  (GATHER)
⟨GATHER results USING mode :: σ, E⟩
  → ⟨σ ∪ {alias ↦ results}, E · GATHER_COMMIT⟩
```

The join mode determines the success requirement (ADR-0002 §Sequential and Parallel Execution):

- **all**: every branch must succeed; partial failure is a program failure.
- **any**: at least one branch must succeed; the first successful result is kept.
- **k(n)**: at least n branches must succeed; the first n successful results are kept.
- **ranked(c)**: the best result by criterion c is selected from successful branches.

The gathered results are committed as a single alias in the state. Partial failure is never silently ignored — a branch that fails contributes to the count m but not to results.

### 2.5 LOOP (issue #68)

A LOOP has an entry condition, a continuation (while) condition, a progress metric, a maximum iteration count, a successful exit condition, and an exhausted-exit behavior. Unbounded loops are invalid (ADR-0002 §Branching and Iteration).

```
eval(entry, σ) = true    iter = 1
──────────────────────────────────────────────  (LOOP-ENTER)
⟨LOOP ... :: σ, E⟩ → ⟨body :: σ, E · LOOP_STARTED(iter=1)⟩
```

The loop enters only if the entry condition holds. The iteration counter starts at 1.

```
eval(while, σ) = true    iter < max
──────────────────────────────────────────────  (LOOP-ITER)
⟨body :: σ, E · LOOP_ITERATION(iter)⟩
  → ⟨body :: σ', E · LOOP_ITERATION(iter+1)⟩
```

After each body execution, the while condition is re-evaluated. If it holds and the iteration count has not reached the maximum, the body runs again. The state σ' is the state after the previous body execution.

```
eval(exit, σ') = true
──────────────────────────────────────────────  (LOOP-EXIT)
⟨body :: σ', E⟩ → ⟨σ', E · LOOP_EXITED⟩
```

If the exit condition is satisfied, the loop terminates successfully. The body is removed from the program; control returns to the instruction following the LOOP.

```
iter = max    eval(exit, σ') = false
──────────────────────────────────────────────  (LOOP-EXHAUSTED)
⟨body :: σ', E⟩ → ⟨exhausted_terminal :: σ', E · LOOP_EXHAUSTED⟩
```

If the maximum iteration count is reached without the exit condition being satisfied, the loop terminates with the exhausted terminal. The exhausted_terminal is a STOP with a typed failure kind (e.g., STOP blocked(U.unresolved)). A loop that makes no progress must stop as BLOCKED (ADR-0002 §Branching and Iteration).

### 2.6 CALL Protocol

CALL loads a named protocol, resolves its inputs from the current state, and expands it inline. The expansion is bounded to depth 8 with no recursion (ADR-0002 §Protocol Layer; `src/tahoe/runtime/coordinator.py:57-67`).

```
protocol = load(name)    inputs = resolve(args, σ)
──────────────────────────────────────────────  (CALL-DISPATCH)
⟨CALL proto(args) -> targets :: σ, E⟩
  → ⟨proto.body[inputs] :: σ, E · CHILD_STARTED⟩
```

The protocol body is substituted into the program with its input args resolved from σ. The CHILD_STARTED event records the beginning of the child protocol execution.

```
child returns refs R    R ⊆ targets
──────────────────────────────────────────────  (CALL-ADOPT)
⟨σ', E · CHILD_TERMINAL(R)⟩
  → ⟨σ ∪ {targets ↦ R}, E · CHILD_ADOPTED⟩
```

When the child protocol reaches a terminal state (RETURN or STOP), its output refs R are adopted into the parent state. The parent state σ is updated with the child's committed results. The CHILD_ADOPTED event records the completion of the child protocol. If the child terminates with STOP (non-succeeded), the parent adopts the terminal kind instead of refs.

### 2.7 RETURN / STOP

RETURN and STOP are terminal instructions. They end the current program (or the current protocol body in a CALL context).

```
refs exist in σ
──────────────────────────────────────────────  (RETURN)
⟨RETURN refs :: σ, E⟩ → ⟨σ, E · RUN_FINISHED(succeeded)⟩
```

RETURN confirms that the named refs exist in the committed state and terminates the run (or protocol) as succeeded. The refs are already in σ; no state change occurs.

```
──────────────────────────────────────────────  (STOP)
⟨STOP kind(ref) :: σ, E⟩ → ⟨σ, E · RUN_FINISHED(kind)⟩
```

STOP terminates the run (or protocol) with a typed kind. The kind is one of:

- `unresolved(ref)`: the goal or question ref could not be resolved.
- `blocked(ref)`: a blocker prevents further progress.
- `failed(ref)`: an unrecoverable failure occurred.
- `denied(ref)`: an approval was denied.

The state σ is not modified; only the terminal event is appended.

### 2.8 TRY / OR (issue #69)

TRY dispatches two or more speculative branches concurrently (bounded by MAX k). The first branch to reach SUCCEEDED wins; all others are cancelled. If all branches fail, the TRY block fails with a composite failure. Only pure and read-only commands are allowed in speculative branches (no writes).

```
branches = [B₁, ..., Bₙ]    n ≥ 2
k = max_count or n
─────────────────────────────────────────────  (TRY-DISPATCH)
⟨TRY MAX k ... OR ... :: σ, E⟩
  → ⟨[B₁, ..., Bₘ] :: σ, E · TRY_STARTED(branches=n, max=k)⟩
```

All branches dispatch concurrently as isolated child runs. The bound k limits concurrency; if n > k, dispatch proceeds in batches. Each branch Bᵢ executes in an isolated child scope `<run_id>:try{i}` with a synthetic program whose INPUT declarations carry the parent state refs the branch reads. The state σ does not change; only the TRY_STARTED event is appended.

*Implementation: `src/tahoe/runtime/driver.py:1693` `_execute_try_entry`.*

```
∃ i: branch Bᵢ reaches SUCCEEDED    winner = min-terminal(i)
─────────────────────────────────────────────  (TRY-SUCCESS)
⟨[B₁, ..., Bₙ] :: σ, E · TRY_BRANCH_SUCCEEDED(i)⟩
  → ⟨σ ∪ δ_winner, E · TRY_BRANCH_CANCELLED(others) · TRY_COMPLETED(succeeded, winner=i) · SUCCEEDED(δ_winner)⟩
```

The first branch to reach SUCCEEDED wins. The winner's committed nodes δ_winner are adopted into the parent run's state. All other branches are cancelled (their futures are cancelled; TRY_BRANCH_CANCELLED is recorded for each). The adoption is atomic: one SUCCEEDED event commits all adopted nodes. The winner is the first branch to complete with status "succeeded"; ties are broken by branch index (lowest wins).

*Implementation: `src/tahoe/runtime/driver.py:1813-1875`.*

```
∀ i: branch Bᵢ reaches FAILED or REJECTED
─────────────────────────────────────────────  (TRY-FAIL)
⟨[B₁, ..., Bₙ] :: σ, E⟩
  → ⟨STOP failed(try_composite) :: σ, E · TRY_COMPLETED(failed, branches=[fail₁, ..., failₙ])⟩
```

If all branches fail, the TRY block fails with a composite failure. The error message aggregates all branch failures. No state change occurs; the run terminates with STOP failed.

*Implementation: `src/tahoe/runtime/driver.py:1837-1854`.*

**Progress.** TRY makes progress because the thread pool ensures at least one branch completes (succeeds or fails) in finite time. If all branches are in flight and none has completed, the coordinator waits; when one completes, exactly one of TRY-SUCCESS or TRY-FAIL fires. If the budget is exhausted before any branch completes, the run is terminated by the budget gate (handled outside these rules).

**Preservation.** TRY-SUCCESS preserves types because the winner's adopted nodes are typed by the branch body's output contract (same typing as DO-COMMIT). TRY-FAIL makes no state change.

### 2.9 PAR / BARRIER (issue #24)

PAR dispatches k heterogeneous branches concurrently (bounded by MAX n). BARRIER blocks until every branch is terminal, then adopts the union of all branch targets. Unlike TRY, PAR requires all branches to succeed; any branch failure fails the entire PAR block.

```
branches = [Br₁, ..., Brₖ]    k ≥ 2
n = max_count
─────────────────────────────────────────────  (PAR-DISPATCH)
⟨PAR MAX n ... BARRIER :: σ, E⟩
  → ⟨[Br₁, ..., Brₖ] :: σ, E · CHILD_STARTED(par₁) · ... · CHILD_STARTED(parₖ)⟩
```

Each branch Brᵢ executes as an isolated child-scoped run `<run_id>:par{i}`. Branches are heterogeneous: each is exactly one DO invocation or one CALL. The concurrency ceiling n limits the thread pool; branches beyond n queue. The state σ does not change.

*Implementation: `src/tahoe/runtime/par.py:103` `_execute_par_entry`.*

```
∀ i: branch Brᵢ is terminal (SUCCEEDED or FAILED)
─────────────────────────────────────────────  (BARRIER-WAIT)
⟨[Br₁, ..., Brₖ] :: σ, E · CHILD_TERMINAL(par₁) · ... · CHILD_TERMINAL(parₖ)⟩
  → ⟨blocked :: σ, E⟩   (not yet committed; waiting for all branches)
```

The barrier blocks until every branch reaches a terminal state. If any branch is still in flight, the coordinator waits. This is not a transition rule per se but a guard: BARRIER-COMMIT fires only when all branches are terminal.

```
∀ i: branch Brᵢ = SUCCEEDED    targets = ⋃ targets(Brᵢ)
published = barrier_targets or targets
published = targets  (validated)
─────────────────────────────────────────────  (BARRIER-COMMIT)
⟨blocked :: σ, E⟩
  → ⟨σ ∪ {published ↦ ⋃ values(Brᵢ)}, E · CHILD_ADOPTED(par₁) · ... · CHILD_ADOPTED(parₖ) · PAR_JOINED · SUCCEEDED(δ)⟩
```

When all branches succeed, their outputs are adopted by explicit target mapping — one CHILD_ADOPTED per branch, then a single SUCCEEDED committing every adopted target in branch order. If barrier_targets is declared, it must equal the union of branch targets exactly (validated at parse time). The artifact merge integrates branch-produced ART.* paths.

*Implementation: `src/tahoe/runtime/par.py:103` `_execute_par_entry` (success path).*

```
∃ i: branch Brᵢ = FAILED
─────────────────────────────────────────────  (PAR-FAIL)
⟨[Br₁, ..., Brₖ] :: σ, E · CHILD_TERMINAL(parᵢ = FAILED)⟩
  → ⟨STOP failed(par_branch_i) :: σ, E · FAILED(parᵢ) · RUN_FINISHED(failed)⟩
```

If any branch fails, the PAR block fails immediately. Sibling branches are cancelled; in-flight pool work is drained and discarded. No sibling results are adopted.

*Implementation: `src/tahoe/runtime/par.py:157` `fail_par`.*

**Progress.** PAR makes progress because the thread pool ensures every branch completes in finite time. BARRIER-COMMIT or PAR-FAIL fires as soon as all branches are terminal.

**Preservation.** BARRIER-COMMIT preserves types because each branch's targets are typed by its invocation or call contract; the union is well-typed by the PAR block's validated barrier_targets.

### 2.10 FIRST (issue #76)

FIRST subscribes to a set of event selectors and waits for the first one to fire. When an event matches a selector, the remaining selectors are cancelled and the body executes sequentially.

```
selectors = [s₁, ..., sₙ]
∃ i: ∃ e ∈ E: match(sᵢ, e)
─────────────────────────────────────────────  (FIRST-FIRE)
⟨FIRST s₁ OR ... OR sₙ ... :: σ, E⟩
  → ⟨body :: σ, E · FIRST_EVENT_MATCHED(selector=i, event=e)⟩
```

The coordinator scans the run's event history for a matching event. A selector `sᵢ` matches an event `e` if `type(e)` equals the selector name or starts with `selector_name + "."`. The first matching selector (in source order) fires; its index and the matched event are recorded. The body statements then execute sequentially (reusing the LOOP body execution path).

*Implementation: `src/tahoe/runtime/driver.py:2433` `_execute_first_entry`.*

```
selectors = [s₁, ..., sₙ]
∀ i: ¬∃ e ∈ E: match(sᵢ, e)
─────────────────────────────────────────────  (FIRST-BLOCK)
⟨FIRST s₁ OR ... OR sₙ ... :: σ, E⟩
  → ⟨STOP blocked(first_no_match) :: σ, E · BLOCKED(reason="no matching event")⟩
```

If no event matches any selector, the FIRST block blocks the run. In the deterministic test harness (where events are pre-injected), this produces a blocked terminal. In a live system, the coordinator would suspend and resume when an external event arrives.

*Implementation: `src/tahoe/runtime/driver.py:2486-2500`.*

**Progress.** FIRST makes progress because event matching is decidable: either a matching event exists (FIRST-FIRE) or it does not (FIRST-BLOCK). In a live system, FIRST-FIRE fires when an external event arrives.

**Preservation.** FIRST-FIRE preserves types because the body is a well-typed sequence of statements (same as LOOP body). FIRST-BLOCK makes no state change.

### 2.11 AWAIT (issue #77)

AWAIT pauses execution until a named event fires or an optional timeout expires. The coordinator records AWAIT_SUSPENDED, blocks the run, and on resume checks for a matching event or timeout.

```
selector = s    timeout = t (optional)
¬∃ e ∈ E: AWAIT_SUSPENDED(invocation_id)
─────────────────────────────────────────────  (AWAIT-SUSPEND)
⟨AWAIT s [TIMEOUT t] :: σ, E⟩
  → ⟨blocked :: σ, E · AWAIT_SUSPENDED(selector=s, timeout=t)⟩
```

On first execution, the coordinator records AWAIT_SUSPENDED and blocks the run (returns a "blocked" result without appending RUN_FINISHED — the run is non-terminal). The state σ does not change.

*Implementation: `src/tahoe/runtime/driver.py:2594-2611`.*

```
∃ e ∈ E, seq(e) > seq(AWAIT_SUSPENDED): match(s, e)
─────────────────────────────────────────────  (AWAIT-RESUME)
⟨blocked :: σ, E · AWAIT_SUSPENDED · EXTERNAL_EVENT(selector=s)⟩
  → ⟨ε :: σ, E · AWAIT_RESUMED(reason="event", matched_seq=seq(e))⟩
```

On resume, the coordinator checks for EXTERNAL_EVENT entries recorded after AWAIT_SUSPENDED whose payload selector matches. If found, AWAIT_RESUMED is recorded and execution continues to the next plan entry (the AWAIT instruction is consumed; P' = ε for this entry).

*Implementation: `src/tahoe/runtime/driver.py:2641-2653`.*

```
timeout = t    deadline = parse(t)
elapsed(now - AWAIT_SUSPENDED.occurred_at) ≥ deadline
¬∃ matching event
─────────────────────────────────────────────  (AWAIT-TIMEOUT)
⟨blocked :: σ, E · AWAIT_SUSPENDED⟩
  → ⟨ε :: σ, E · AWAIT_RESUMED(reason="timeout")⟩
```

If a timeout was set and no matching event arrived before the deadline, AWAIT_RESUMED is recorded with reason "timeout" and execution continues without the event.

*Implementation: `src/tahoe/runtime/driver.py:2654-2664`.*

```
¬∃ matching event    ¬timeout
─────────────────────────────────────────────  (AWAIT-REBLOCK)
⟨blocked :: σ, E · AWAIT_SUSPENDED⟩
  → ⟨blocked :: σ, E⟩   (re-block; no new event)
```

If neither a matching event nor a timeout, the run re-blocks. No new event is appended; the coordinator returns a "blocked" result again.

*Implementation: `src/tahoe/runtime/driver.py:2665-2673`.*

**Progress.** AWAIT makes progress in three ways: a matching event arrives (AWAIT-RESUME), the timeout expires (AWAIT-TIMEOUT), or the run remains blocked (AWAIT-REBLOCK is a stable state, not a stuck state — an external event or timeout will eventually fire in a live system). In the deterministic test harness, events are pre-injected, so AWAIT-RESUME or AWAIT-TIMEOUT fires on the first resume.

**Preservation.** All AWAIT rules make no state change; only events are appended.

### 2.12 APPROVE (issue #78)

APPROVE gates execution on an approval policy. The coordinator computes an SHA-256 digest of the intent expression, records APPROVAL_REQUESTED, and blocks the run. On resume, it checks for APPROVAL_GRANTED (with matching digest) or APPROVAL_DENIED.

```
policy = p    intent = expr    digest = SHA-256(expr)
¬∃ e ∈ E: APPROVAL_REQUESTED(invocation_id)
─────────────────────────────────────────────  (APPROVE-REQUEST)
⟨APPROVE p INTENT expr :: σ, E⟩
  → ⟨blocked :: σ, E · APPROVAL_REQUESTED(policy=p, intent_digest=digest) · RUN_FINISHED(status="blocked", reason="approve")⟩
```

On first execution, the coordinator records APPROVAL_REQUESTED and blocks the run. The intent digest is an SHA-256 hash of the intent expression, ensuring the grant can be verified against the exact request.

*Implementation: `src/tahoe/runtime/driver.py:2724-2754`.*

```
∃ e ∈ E, seq(e) > seq(APPROVAL_REQUESTED): APPROVAL_GRANTED
grant_digest = e.payload.intent_digest
grant_digest = request_digest
─────────────────────────────────────────────  (APPROVE-GRANT)
⟨blocked :: σ, E · APPROVAL_REQUESTED · APPROVAL_GRANTED(digest=grant_digest)⟩
  → ⟨ε :: σ, E⟩   (continue to next plan entry)
```

If APPROVAL_GRANTED is found after APPROVAL_REQUESTED and its intent_digest matches, the run continues to the next plan entry. No state change occurs. A digest mismatch causes a run failure (the approval was for a different intent).

*Implementation: `src/tahoe/runtime/driver.py:2775-2786`.*

```
∃ e ∈ E, seq(e) > seq(APPROVAL_REQUESTED): APPROVAL_DENIED
─────────────────────────────────────────────  (APPROVE-DENY)
⟨blocked :: σ, E · APPROVAL_REQUESTED · APPROVAL_DENIED⟩
  → ⟨STOP denied(policy=p) :: σ, E · RUN_FINISHED(status="denied")⟩
```

If APPROVAL_DENIED is found, the run stops with status "denied". The state σ is not modified.

*Implementation: `src/tahoe/runtime/driver.py:2788-2804`.*

```
¬∃ APPROVAL_GRANTED    ¬∃ APPROVAL_DENIED
─────────────────────────────────────────────  (APPROVE-REBLOCK)
⟨blocked :: σ, E · APPROVAL_REQUESTED⟩
  → ⟨blocked :: σ, E · RUN_FINISHED(status="blocked", reason="approve")⟩
```

If neither grant nor denial has arrived, the run re-blocks.

*Implementation: `src/tahoe/runtime/driver.py:2807-2824`.*

**Progress.** APPROVE makes progress in three ways: APPROVAL_GRANTED (APPROVE-GRANT), APPROVAL_DENIED (APPROVE-DENY), or re-block (APPROVE-REBLOCK). In a live system, an external approver eventually grants or denies; in the test harness, events are pre-injected.

**Preservation.** All APPROVE rules make no state change.

### 2.13 REVISE / RETIRE (issue #7)

A DO invocation may carry a trailing REVISE/RETIRE correction clause. REVISE sets named refs to the step's single target value at commit time (pinning REVISE to single-target steps). RETIRE removes named refs from the projection (history preserved in the event log).

```
validate(v, cmd, σ) = ok    δ = {targets ↦ v}
REVISE refs = {r₁, ..., rₘ}    |targets| = 1
revised_value = v[targets[0]]
─────────────────────────────────────────────  (REVISE-COMMIT)
⟨σ, E · RESULT(v)⟩
  → ⟨σ ∪ δ ∪ {r₁ ↦ revised_value, ..., rₘ ↦ revised_value}, E · SUCCEEDED(δ ∪ revise_nodes)⟩
```

REVISEd refs are set to the step's single target value. The revision commits inside the same SUCCEEDED delta as the step's adds, so later steps observe the corrected state and the version bumps once per step. The revised refs' values are updated in the run-state values mapping in lockstep with the delta.

*Implementation: `src/tahoe/runtime/driver.py:1090-1105` and `src/tahoe/syntax/parser.py:48-61`.*

```
RETIRE refs = {r₁, ..., rₘ}
─────────────────────────────────────────────  (RETIRE-REMOVE)
⟨σ, E · RESULT(v)⟩
  → ⟨σ \ {r₁, ..., rₘ}, E · SUCCEEDED(δ, retire_nodes=[r₁, ..., rₘ])⟩
```

RETIREd refs are removed from the projection. The event log preserves the full history (the ref's add and retire are both in E), so `history(ref)` can reconstruct the ref's past values. The run-state values mapping drops the retired refs so later steps fail coherently if they reference a retired ref.

*Implementation: `src/tahoe/runtime/driver.py:1106-1143` and `src/tahoe/runtime/events.py:601` `ref_history`.*

**Progress.** REVISE-COMMIT and RETIRE-REMOVE are sub-steps of DO-COMMIT; they fire when the DO invocation succeeds. Progress is inherited from DO-COMMIT.

**Preservation.** REVISE-COMMIT preserves types because the revised value comes from the step's single target (already typed by the contract). RETIRE-REMOVE removes refs; the remaining state is still well-typed (removal cannot introduce an ill-typed ref).

### 2.14 REFORMULATE (issue #80)

REFORMULATE allows the model to diagnose a failure, revise invalidated refs, author a new sub-plan, and continue — all within the same run. It has four labeled sections: DIAGNOSE, REVISE, REPLAN, CONTINUE.

```
reformulation_count < 3
─────────────────────────────────────────────  (REFORMULATE-DIAGNOSE)
⟨REFORMULATE ... :: σ, E⟩
  → ⟨σ', E · DISPATCH(σ, diagnose.cmd, diagnose.args)⟩
```

The DIAGNOSE step is a standard DO dispatch. It identifies what went wrong. The reformulation cap is enforced: at most 3 reformulations per run (checked before dispatch). If the cap is exceeded, the run fails.

*Implementation: `src/tahoe/runtime/driver.py:1993-2006` (cap check), `driver.py:2008-2034` (dispatch).*

```
diagnose returns value v    validate(v) = ok
REVISE pairs = [(old₁, new₁), ..., (oldₘ, newₘ)]
─────────────────────────────────────────────  (REFORMULATE-REVISE)
⟨σ', E · RESULT(v)⟩
  → ⟨σ' ∪ {newᵢ ↦ value(oldᵢ)} \ {old₁, ..., oldₘ}, E · SUCCEEDED(δ_revise)⟩
```

For each REVISE pair, the old ref is retired (history preserved) and the new ref is created with the old ref's value as a starting point. The retire and create commit inside the same SUCCEEDED delta.

*Implementation: `src/tahoe/runtime/driver.py:2145-2165`.*

```
replan = DO cmd(args) -> targets
σ'' = σ' after REVISE
─────────────────────────────────────────────  (REFORMULATE-REPLAN)
⟨σ'', E⟩
  → ⟨σ'' ∪ {targets ↦ plan_value}, E · SUCCEEDED(δ_replan) · PLAN_REFORMULATED(new_plan_ref=continue_ref, revised_refs, new_plan_digest)⟩
```

The REPLAN step produces a new sub-plan from the current committed state. Unlike delegate, the child plan inherits ALL committed state from the parent (not isolated namespace). The PLAN_REFORMULATED event records the new plan reference, revised refs, and a digest of the new plan value.

*Implementation: `src/tahoe/runtime/driver.py:2230-2358`.*

```
continue_ref ∈ replan targets
new_plan = replan_targets[continue_ref]
─────────────────────────────────────────────  (REFORMULATE-CONTINUE)
⟨σ'' ∪ {continue_ref ↦ new_plan}, E · PLAN_REFORMULATED⟩
  → ⟨new_plan_entries :: σ'' ∪ {continue_ref ↦ new_plan}, E⟩
```

The new plan's entries replace the remaining steps of the parent plan. Execution continues from the first entry of the new plan. The CONTINUE reference must be produced by the REPLAN step (validated at runtime).

*Implementation: `src/tahoe/runtime/driver.py:2361-2420`.*

**Progress.** REFORMULATE makes progress because each sub-step (DIAGNOSE, REVISE, REPLAN, CONTINUE) is a standard DO dispatch or a state edit. The reformulation cap (3) ensures REFORMULATE cannot loop indefinitely. If the cap is exceeded, the run fails (progress via termination).

**Preservation.** REFORMULATE-REVISE preserves types because the new ref inherits the old ref's type (the old ref is retired, not deleted — history preserves the type lineage). REFORMULATE-REPLAN preserves types because the new plan is produced by a well-typed DO invocation. REFORMULATE-CONTINUE preserves types because the new plan entries are well-typed by the REPLAN step's output contract.

### 2.15 history() Temporal Query (issue #81)

The `history(ref)` DONE predicate queries the revision history of a single ref by replaying all SUCCEEDED deltas in seq order. It is a deterministic check over the event log, not a worker call.

```
ref = r    history = ref_history(E, r)
history ≠ ∅
─────────────────────────────────────────────  (HISTORY-NONEMPTY)
⟨DONE history(r) :: σ, E⟩
  → ⟨σ, E · VALIDATION_PASSED⟩
```

The `ref_history` function replays all SUCCEEDED events in seq order and collects every event that added, revised, or retired ref `r`, producing a chronological list of revision records: `{action: "add"|"revise"|"retire", value: <value>, seq: <int>, invocation_id: "..."}`. A ref that was never touched returns an empty list. The DONE predicate evaluates to true if the history is non-empty (the ref was created at some point), false otherwise.

```
ref = r    history = ref_history(E, r)
history = ∅
─────────────────────────────────────────────  (HISTORY-EMPTY)
⟨DONE history(r) :: σ, E⟩
  → ⟨σ, E · VALIDATION_FAILED · REJECTED⟩
```

*Implementation: `src/tahoe/runtime/events.py:601` `ref_history`; `src/tahoe/syntax/parser.py:2183` `_parse_done_history`; `src/tahoe/runtime/helpers.py:319` `evaluate_done_predicate`.*

**Progress.** history() is a deterministic check over the event log; it always terminates (replay is finite). Exactly one of HISTORY-NONEMPTY or HISTORY-EMPTY fires.

**Preservation.** history() makes no state change; only events are appended (VALIDATION_PASSED or VALIDATION_FAILED).

---

## 3. Type System

> **Implementation.** The subtyping lattice, the `is_subtype` relation, and
> the static type checker are implemented in `src/tahoe/typecheck.py` (issue
> #71). The type checker runs at lint/seal time via `validate_program` in
> `src/tahoe/syntax/parser.py`; type mismatches are emitted as warnings (not
> hard errors) so existing programs continue to parse and seal. The lattice
> edges in code (`SUBLATTICE` dictionary) correspond to the axioms below.

### 3.1 Subtyping Lattice

The node types form a subtyping lattice under the relation ⊑ (read "is a subtype of"). The lattice captures epistemic strength: a stronger type can be used where a weaker type is expected, because it carries more epistemic warrant.

```
                    V (verified — top)
                   / \
                  F   D
                 / \ / \
                E   H   O
               / \ / \ /
              A   U   PF (preference)
               \ / \ /
                Q   C
                 \ /
                  G (goal — bottom)
```

**Reading the lattice.** The upward direction means "stronger evidence." G (goal) is the bottom: any node can be framed as a goal. V (verified) is the top: a verified result can stand in for any weaker epistemic type.

Additional types are orthogonal to the main lattice:

| Type | Role | Relation to lattice |
| --- | --- | --- |
| CTX (context) | Background state | Orthogonal; no subtyping with main lattice |
| K (criterion) | Rule for comparison | Orthogonal |
| X (action) | Executable next step | Orthogonal |
| R (risk) | Possible harmful outcome | Orthogonal |
| OUT (output) | Required response form | Top of a separate output lattice |
| ART (artifact) | Content-addressed data | Orthogonal; content-addressed, not epistemic |
| PR (probability) | Numeric confidence [0,1] | Orthogonal; numeric, not epistemic |

### 3.2 Subtyping Rules

The subtyping relation ⊑ is the reflexive-transitive closure of the following axioms:

```
G ⊑ Q      (a goal is a special kind of question)
G ⊑ C      (a goal can serve as a constraint)
Q ⊑ U      (a question is a special kind of unknown)
Q ⊑ A      (a question can be treated as an assumption)
C ⊑ PF     (a constraint is a strict preference)
PF ⊑ O     (a preference can be an option)
U ⊑ H      (an unknown can be hypothesized)
A ⊑ H      (an assumption is a weaker hypothesis)
A ⊑ E      (an assumption can serve as evidence)
E ⊑ F      (evidence can be promoted to a fact)
H ⊑ F      (a confirmed hypothesis becomes a fact)
H ⊑ D      (a hypothesis can drive a decision)
O ⊑ D      (an option can be selected as a decision)
F ⊑ V      (a fact can be verified)
D ⊑ V      (a decision can be verified)
```

> **Implementation note.** The implemented `SUBLATTICE` in
> `src/tahoe/typecheck.py:32-40` encodes the following edges:
> `E→F`, `F→V`, `A→H`, `H→F`, `U→Q`, `Q→G`, `C→G`. The code treats `PF`,
> `O`, `D`, and `P` as **orthogonal** types (not in the main lattice),
> while the document's axioms include `C⊑PF`, `PF⊑O`, `O⊑D`, `H⊑D`,
> `D⊑V`. This is a known reconciliation gap: the document describes the
> full design lattice; the code implements the core epistemic chain
> (G→Q→U→A→H→E→F→V plus C→G) and defers the preference/decision/option
> branch. The `is_subtype` function is correct for the implemented
> edges; the remaining axioms are design-level specifications for future
> type-checker extensions.

```
G ⊑ Q      (a goal is a special kind of question)
G ⊑ C      (a goal can serve as a constraint)
Q ⊑ U      (a question is a special kind of unknown)
Q ⊑ A      (a question can be treated as an assumption)
C ⊑ PF     (a constraint is a strict preference)
PF ⊑ O     (a preference can be an option)
U ⊑ H      (an unknown can be hypothesized)
A ⊑ H      (an assumption is a weaker hypothesis)
A ⊑ E      (an assumption can serve as evidence)
E ⊑ F      (evidence can be promoted to a fact)
H ⊑ F      (a confirmed hypothesis becomes a fact)
H ⊑ D      (a hypothesis can drive a decision)
O ⊑ D      (an option can be selected as a decision)
F ⊑ V      (a fact can be verified)
D ⊑ V      (a decision can be verified)
```

Key incompatibilities (not comparable under ⊑):

- **D and V are incomparable**: a decision and a verification have different epistemic roles. A decision is a commitment; a verification is a test. Neither subsumes the other.
- **E and D are incomparable**: evidence does not imply a decision, and a decision does not imply evidence.
- **CTX and any lattice type**: context is background, not a claim, so it cannot substitute for an epistemic node.

### 3.3 Typing Judgments

A typing judgment has the form:

```
Γ ⊢ DO cmd(args) : τ_in → τ_out
```

where Γ is the committed state (acting as the typing context), τ_in is the expected input types, and τ_out is the produced output types.

Each command contract (ADR-0002 §Atomic Command Contract) declares:

- **accepted inputs**: node and artifact types it can consume.
- **produced outputs**: node and artifact types it may create.

The type checker verifies:

1. **Input compatibility**: all input refs have types compatible with the contract's accepted types, by subtyping. If the contract expects F (fact) and the ref has type V (verified), this is valid because V ⊑ F.
2. **Output assignment**: output refs are assigned types from the contract's produced types.
3. **DONE predicate well-typedness**: DONE predicates reference refs of compatible types. A DONE over a V ref can test any property that a DONE over an F ref can, because V ⊑ F.

### 3.4 Type Safety (Sketch)

**Theorem (Progress).** A well-typed program either terminates or makes a transition.

*Sketch.* Every non-terminal configuration has at least one applicable rule:

- DO: preconditions are checked before dispatch (DO-DISPATCH); a worker either returns (DO-COMMIT or DO-REJECT) or times out (handled by the retry policy, which produces a terminal or re-dispatch).
- DONE: eval is total over committed refs, so exactly one of DONE-PASS or DONE-FAIL applies.
- IF: eval is total, so exactly one of IF-TRUE or IF-FALSE applies.
- SCATTER/GATHER: the collection is resolved from committed state; GATHER fires when all branches reach a terminal state.
- LOOP: bounded by max iterations; LOOP-EXHAUSTED is the catch-all when max is reached.
- CALL: bounded by depth 8; a child always reaches RETURN or STOP.
- TRY: bounded by MAX k; the thread pool ensures at least one branch completes; TRY-SUCCESS or TRY-FAIL fires.
- PAR: bounded by MAX n; the barrier waits for all branches; BARRIER-COMMIT or PAR-FAIL fires when all are terminal.
- FIRST: event matching is decidable; FIRST-FIRE or FIRST-BLOCK applies.
- AWAIT: event matching or timeout is decidable; AWAIT-RESUME, AWAIT-TIMEOUT, or AWAIT-REBLOCK applies.
- APPROVE: APPROVE-GRANT, APPROVE-DENY, or APPROVE-REBLOCK applies.
- REFORMULATE: bounded by 3 reformulations; each sub-step is a standard DO dispatch.
- REVISE/RETIRE: sub-steps of DO-COMMIT; progress is inherited.
- history(): deterministic replay over finite event log; always terminates.
- RETURN/STOP: terminal by definition.

The only divergence is worker non-determinism, which does not block progress — it only affects the content of v (and hence δ).

**Theorem (Preservation).** If ⟨P, σ⟩ → ⟨P', σ'⟩ and Γ ⊢ P : τ, then Γ ⊢ P' : τ.

*Sketch.* Each transition rule preserves the types of committed refs:

- DO-COMMIT: δ is assigned types from the command contract (typing judgment), so σ ∪ δ is well-typed.
- DONE-PASS/DONE-FAIL: no state change.
- IF-TRUE/IF-FALSE: no state change; the selected branch was already part of the well-typed program.
- GATHER: results come from well-typed branches; the alias is typed from the SCATTER body's output contract.
- LOOP-ITER: σ' is the result of executing a well-typed body, so by induction σ' is well-typed.
- CALL-ADOPT: R ⊆ targets, and targets are typed by the protocol's output contract.
- TRY-SUCCESS: the winner's adopted nodes are typed by the branch body's output contract (same as DO-COMMIT).
- TRY-FAIL: no state change.
- BARRIER-COMMIT: each branch's targets are typed by its invocation or call contract; the union is well-typed by the validated barrier_targets.
- PAR-FAIL: no state change.
- FIRST-FIRE: the body is a well-typed sequence; no state change at the selector match.
- FIRST-BLOCK: no state change.
- AWAIT-*: no state change.
- APPROVE-GRANT/APPROVE-DENY/APPROVE-REBLOCK: no state change.
- REFORMULATE-REVISE: new ref inherits old ref's type (retire preserves history).
- REFORMULATE-REPLAN: new plan is produced by a well-typed DO invocation.
- REFORMULATE-CONTINUE: new plan entries are well-typed by the REPLAN step's output contract.
- REVISE-COMMIT: revised value comes from the step's single target (already typed).
- RETIRE-REMOVE: removal cannot introduce an ill-typed ref.
- history(): no state change.
- RETURN/STOP: no state change.

Therefore, the type of the committed state is preserved across all transitions.

---

## 4. Denotational Semantics (Sketch)

We define a denotational semantics ⟦·⟧ that maps each construct to a state transformer. The denotation is partial: it is undefined if the construct diverges or fails irrecoverably.

```
⟦DO cmd(args) -> targets⟧(σ) = σ ∪ {targets ↦ eval(cmd, args, σ)}
```

The denotation of DO abstracts over worker non-determinism: eval(cmd, args, σ) represents the value returned by a worker for the given command and state slice, after validation.

```
⟦IF cond S₁ ELSE S₂⟧(σ) = ⟦S₁⟧(σ)   if eval(cond, σ)
                          ⟦S₂⟧(σ)   otherwise
```

```
⟦SCATTER x IN c ... GATHER r USING m⟧(σ) = ⋁_m { ⟦body⟧(σ[x ↦ v]) | v ∈ c }
```

Where ⋁_m is the join operator for mode m:

- ⋁_all = merge all results (requires all branches to succeed)
- ⋁_any = first successful result
- ⋁_k(n) = first n successful results
- ⋁_ranked(c) = best result by criteria c

```
⟦LOOP ... body ... EXIT δ⟧(σ) = fix(λσ'. ⟦body⟧(σ') if ¬eval(δ, σ'), else σ')
```

The loop denotation is a fixpoint, bounded by max iterations. If the exit condition is never met within max iterations, the denotation is the state after the last iteration, paired with the exhausted terminal.

```
⟦CALL proto(args) -> targets⟧(σ) = ⟦proto⟧(σ[args])   (bounded depth 8)
```

The call denotation substitutes the protocol body with resolved inputs. The depth bound prevents infinite expansion; at depth 8, a CALL is rejected as a program error.

```
⟦RETURN refs⟧(σ) = σ   (terminal; refs already in σ)
```

```
⟦STOP kind(ref)⟧(σ) = σ   (terminal)
```

Both RETURN and STOP are terminal: they do not transform the state; they only mark the end of execution with a terminal kind.

```
⟦TRY MAX k B₁ OR ... OR Bₙ⟧(σ) = ⟦B_w⟧(σ)   where w = min { i | ⟦Bᵢ⟧(σ) ≠ ⊥ }
```

The TRY denotation selects the first successful branch. If all branches fail (⊥), the denotation is ⊥ (failure). The branches race; the winner is the first to succeed. Worker non-determinism means the winner may vary between runs, but the event log records which branch won.

```
⟦PAR MAX n Br₁ ... BARRIER -> t⟧(σ) = ⋃ { ⟦Brᵢ⟧(σ) | i ∈ [1, n] }
```

The PAR denotation is the union of all branch results. If any branch fails, the denotation is ⊥ (the entire PAR fails). The barrier ensures all branches complete before the union is committed.

```
⟦FIRST s₁ OR ... OR sₙ body⟧(σ) = ⟦body⟧(σ)   if ∃ matching event
                                      ⊥ (blocked)   otherwise
```

```
⟦AWAIT s [TIMEOUT t]⟧(σ) = σ   (suspends; resumes to σ on event or timeout)
```

The AWAIT denotation is the identity on σ: it pauses execution but does not transform the state. The denotation is defined only if a matching event or timeout eventually occurs.

```
⟦APPROVE p INTENT expr⟧(σ) = σ   (if granted; ⊥ if denied)
```

```
⟦REFORMULATE DIAGNOSE ... REVISE ... REPLAN ... CONTINUE r⟧(σ)
  = ⟦new_plan⟧(σ'')   where σ'' = σ after DIAGNOSE, REVISE, REPLAN
```

The REFORMULATE denotation composes the four sub-steps. The denotation is undefined if the reformulation cap (3) is exceeded.

```
⟦DONE history(r)⟧(σ) = σ   if ref_history(E, r) ≠ ∅
                       ⊥   otherwise
```

The history() denotation is a deterministic check: it succeeds (identity) if the ref has a non-empty revision history, and fails (⊥) otherwise.

---

## 5. Soundness Discussion

### 5.1 Determinism of the Coordinator

The coordinator is deterministic: given the same program P and event log E, it produces the same state projection σ = project(σ₀, E). This follows from:

- The transition rules are syntax-directed: at most one rule applies for any configuration.
- State mutations occur only through COMMIT events, which are ordered by seq.
- The state projection replays COMMIT events in seq order, which is deterministic.

This holds even though worker output is non-deterministic: the event log records what was actually returned, so replay is deterministic given the log. For TRY, the event log records which branch won (TRY_BRANCH_SUCCEEDED), so the winning branch is deterministic on replay. For FIRST/AWAIT/APPROVE, the event log records which event fired (FIRST_EVENT_MATCHED, AWAIT_RESUMED, APPROVAL_GRANTED/DENIED), so the control-flow choice is deterministic on replay. For REFORMULATE, the PLAN_REFORMULATED event records the new plan digest, so the plan replacement is deterministic on replay.

### 5.2 Validation Gates and Type Safety

Worker output is non-deterministic, but validation gates ensure type safety:

- **Shape validation**: the returned value must match the declared output schema.
- **Type checking**: the returned refs must have types compatible with the contract's output types.
- **Done condition**: the DONE predicate must evaluate to true.
- **Evidence check**: required evidence must be attached (ADR-0002 §Definition of Done).

Only deltas that pass all gates are committed. A rejected delta produces a REJECTED event but no state change. This ensures that the committed state is always well-typed, regardless of worker behavior.

### 5.3 Causal Ordering

The event log provides causal ordering: every state change has a causation event. The causation field on each event forms a chain from the initial DISPATCH to the final COMMIT. This means:

- Every node in the committed state can be traced to the event that created it.
- Every revision of a node can be traced to the event that modified it.
- The causal chain is acyclic (seq is monotonic), so there are no causal loops.

This is the basis for `tahoe audit`, which verifies that the event log is consistent with the committed state and that all invariants hold (ADR-0002 §Determinism and Reproducibility).

### 5.4 Sealing and Replayability

A sealed program carries a digest of its source text, the registry digest (23 commands at v1.0.0), and the seal timestamp. Given the same program + seal digest, the execution trace is reproducible modulo worker non-determinism:

- **Control flow is deterministic**: the same program + state produces the same sequence of dispatches, branches, and joins.
- **Worker output is recorded**: the event log captures what each worker returned, so a replay reads the recorded results rather than calling workers again.
- **Replay modes** (ADR-0002 §Determinism and Reproducibility):
  - *inspect*: read the timeline without execution.
  - *revalidate*: run validators against stored outputs (deterministic, no workers).
  - *resume*: continue from the last committed state.
  - *reexecute*: call workers again from a selected state version (non-deterministic, but control flow is the same).
  - *fork*: create a new run from a past state with changed instructions.

The seal ensures that the program text cannot be modified after execution begins. Any discrepancy between the sealed program and the event log is an audit failure.

### 5.5 Non-Goals

This formalization does not claim:

- **Worker determinism**: workers are LLM-backed and inherently non-deterministic. The semantics abstracts over this by recording actual outputs in the event log.
- **Convergence**: a program may reach STOP blocked or STOP failed. The semantics guarantees progress (a transition is always possible) but not success.
- **Optimality**: the type system ensures safety (no ill-typed commits), not efficiency. Token efficiency is an empirical property measured by the experiment register (Reasoning Language Foundation §3).
- **Lattice completeness**: the implemented `SUBLATTICE` in `typecheck.py` covers the core epistemic chain (G→Q→U→A→H→E→F→V plus C→G); the preference/decision/option branch (PF, O, D) is specified in §3.2 but deferred in the code. The formal semantics are complete for all implemented constructs.
