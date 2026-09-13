# Formal Operational Semantics for TAHOE

- Status: Draft 0.1
- Source: issue #70 (formal semantics); issues #68 (LOOP), #83 (IF/ELSE)
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
- type(eᵢ) ∈ {DISPATCH, RESULT, COMMIT, SUCCEEDED, REJECTED, VALIDATION_PASSED, VALIDATION_FAILED, SCATTER_DISPATCH, GATHER_COMMIT, LOOP_STARTED, LOOP_ITERATION, LOOP_EXITED, LOOP_EXHAUSTED, CHILD_STARTED, CHILD_TERMINAL, CHILD_ADOPTED, RUN_FINISHED, FAILED, BLOCKED}
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

---

## 5. Soundness Discussion

### 5.1 Determinism of the Coordinator

The coordinator is deterministic: given the same program P and event log E, it produces the same state projection σ = project(σ₀, E). This follows from:

- The transition rules are syntax-directed: at most one rule applies for any configuration.
- State mutations occur only through COMMIT events, which are ordered by seq.
- The state projection replays COMMIT events in seq order, which is deterministic.

This holds even though worker output is non-deterministic: the event log records what was actually returned, so replay is deterministic given the log.

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
