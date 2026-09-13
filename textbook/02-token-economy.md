# Token Economy Without Quality Loss

## Purpose

Token economy means reducing the total communication needed to reach a verified result.
It does not mean using abbreviations everywhere, removing necessary evidence, or asking
for an answer too short to be useful.

## Optimize Total Conversation Cost

Measure the entire interaction:

```text
conversation_cost = prompt + response + corrections + repeated_context + rework
```

The optimal first message contains enough structure to prevent predictable
clarification, but no context that cannot influence the result.

## The Context Relevance Filter

Before including a piece of context, ask:

1. Can it change which options are valid?
2. Can it change how options are ranked?
3. Can it change the required output?
4. Can it change the acceptance check?
5. Can it prevent a material risk or misunderstanding?

If all answers are no, omit it from the active prompt. Keep it in a referenced source if
it may become relevant later.

## Use a Request Envelope

Put control information before supporting material:

```text
G: <one outcome>
C: <hard boundaries>
PF: <soft ranking>
CTX: <decision-shaping facts only>
ASK: <the operation the AI should perform>
OUT: <format, order, and detail>
V: <acceptance condition>
BUDGET: <optional length or effort bound>
```

This reduces the chance that the AI infers the task from a long narrative.

## Progressive Disclosure

Send information in layers:

| Layer | Include | Send when |
| --- | --- | --- |
| L0 | Goal and direct question | Always |
| L1 | Constraints and essential context | Needed to answer correctly |
| L2 | Evidence and examples | Needed to decide or verify |
| L3 | Full source material | Requested or ambiguity remains |

Do not paste L3 by default. Provide identifiers, paths, or summaries and allow the AI to
request the exact source.

## Reference Stable Context

Assign identifiers to facts, decisions, and constraints that recur:

```text
C1: Public API compatibility cannot break.
D3: Use the graph syntax from ADR-0001.
```

Later messages can say:

```text
Keep C1 and D3. Replace only O.parser and re-evaluate V.syntax.
```

Do not renumber identifiers when adding a new item. Stable references make incremental
updates short and safe.

## Delta Communication

After the initial context, communicate changes rather than resending the whole state:

```text
+ F.timeout: The service limit is 30 seconds.
~ C.latency: Change maximum latency from 2s to 1s.
- A.network: Remove the assumption that calls remain in one region.
? D.batch: Re-evaluate using these deltas only.
```

Symbols are optional shorthand:

- `+` adds a node;
- `~` revises a node without changing its identity;
- `-` removes or retires a node;
- `?` asks for an operation.

If a revision changes the concept rather than its value, create a new identifier.

## One Semantic Unit per Node

Bundled statements are difficult to reference and update:

Weak:

```text
CTX: The API is slow, expensive, and owned by Team A.
```

Strong:

```text
F.latency: p95 latency is 2.4 seconds.
F.cost: Monthly cost is $12,000.
F.owner: Team A owns the service.
```

Atomic statements cost slightly more initially but save tokens across revisions.

## Ask for the Output You Will Use

Avoid generic requests such as "explain everything." Define the consumption format:

```text
OUT.review:
- blocking findings first
- file and line references
- no restatement of unchanged code
- maximum 500 words unless a critical issue requires more
```

Useful output controls include:

- audience and assumed expertise;
- ordering by severity, confidence, or actionability;
- maximum length or number of options;
- whether explanation, code, table, or decision is required;
- what should be omitted;
- whether questions should be asked before action.

## Compression That Is Usually Safe

- Remove greetings, apologies, and conversational transitions from task payloads.
- Replace repeated noun phrases with stable identifiers.
- Use tables for repeated attributes across comparable items.
- Use links instead of restating causal or dependency relationships.
- Summarize unchanged context as `unchanged: C1,C2,D3`.
- Request only changed sections when revising an artifact.
- Put examples after rules and limit them to distinct edge cases.
- State defaults once in a protocol or profile instead of every request.

## Compression That Is Usually Unsafe

Do not remove:

- negation, exceptions, or boundary values;
- the difference between fact, assumption, and hypothesis;
- units, dates, versions, environments, or data scope;
- acceptance criteria;
- security, privacy, legal, or safety constraints;
- evidence needed to audit an important claim;
- uncertainty that could change a decision;
- the exact text of errors, contracts, or user requirements when wording matters.

## Avoid Token-Wasting Interaction Patterns

### Narrative Before Intent

Put the goal and ask first. Supporting history comes afterward.

### Repeated Full Summaries

Request a summary only at phase boundaries or before context may be lost. Within one
phase, use deltas.

### Unbounded Brainstorming

Specify dimensions and a selection rule:

```text
Generate 3 materially different options, reject invalid ones using C1-C3, then
recommend one using K.cost and K.reversibility.
```

### Explanation Before Inspection

If the AI can inspect a file, log, or artifact directly, reference it instead of
describing it incompletely.

### Multiple Goals in One Request

Split unrelated goals. Shared context does not make goals dependent.

### Asking for Private Reasoning

Request conclusions, assumptions, evidence, trade-offs, and checks. Long hidden
reasoning transcripts are neither necessary nor reliably auditable.

## Response Compression Contract

An AI following this language should:

- lead with `OUT` rather than paraphrasing the request;
- state only assumptions that affect the result;
- cite node identifiers when referring to supplied context;
- report unresolved blockers, not every thought considered;
- omit unchanged information;
- use concise evidence sufficient to support each important conclusion;
- stop when the requested artifact and check are complete.

## Token Budget Escalation

Use a staged budget rather than an arbitrary fixed number:

```text
B0 direct: answer from supplied facts
B1 inspect: inspect relevant evidence
B2 compare: generate and compare options
B3 deep: investigate high-impact uncertainty
```

Start at the lowest sufficient budget. Escalate only when a blocker, contradiction, or
high-impact unknown remains. Record the reason for escalation.

## Efficiency Measurement

For pilot tasks, record:

| Metric | Meaning |
| --- | --- |
| Input tokens | Context supplied by the human |
| Output tokens | AI response size |
| Turns | Number of round trips |
| Clarifications | Missing-context repairs |
| Rework | Work repeated because of error or ambiguity |
| Acceptance result | Whether the final verification passed |
| Human effort | Approximate preparation and review time |

Compare protocols using successful tasks of similar difficulty. Token reduction is valid
only when acceptance rate and outcome quality do not decline.

## Minimal Compression Checklist

- Goal and ask appear before background.
- Every included fact can change the result.
- Repeated concepts have stable identifiers.
- The message contains deltas rather than full history.
- Output format and stopping condition are explicit.

## Reasoning Token Economy

The largest token cost in single-call reasoning is not the prompt — it is the
output. A model that meanders through 500 tokens of exploration before
reaching the answer costs more than one that structures its reasoning in 50
tokens and answers directly.

TAHOE's typed refs and protocols reduce reasoning tokens by forcing the model
to commit intermediate values early instead of narrating an open-ended thought
process:

```text
# Without TAHOE: 400 output tokens of exploration
"Well, let me think about this. The question asks about Europa's surface cracks.
I know that Europa is an icy moon... [300 tokens of narrative]... so the answer
is tectonic movements, which is option B."

# With TAHOE: 60 output tokens of structured reasoning
"G.goal: Which process causes Europa's surface cracks?
E.options: A) volcanic B) tectonic C) impacts D) flares
P.eliminate_A: No active volcanoes on Europa — eliminate
P.eliminate_C: Impact cracks would be radial, not patterned — eliminate
P.eliminate_D: Solar flares don't affect ice — eliminate
D.choice: B (tectonic movements of ice produce patterned cracks)
OUT.answer: (B)"
```

The structure forces commitment, eliminates narrative, and produces a checkable
chain of reasoning. Each ref is one semantic unit. The model spends tokens on
the answer, not on telling a story about how it found the answer.

### Protocol Selection Reduces Tokens

Choosing the right protocol at the start prevents the model from exploring
multiple reasoning styles. The protocol tells the model which artifacts to
produce and in what order. This eliminates the "let me try this approach..."
preamble that wastes 50-100 tokens before the real reasoning starts.

### Concrete Values Reduce Tokens

Using concrete numbers (`P.subtotal: 3 * 12 = 36`) instead of variable names
(`P.subtotal: quantity * price`) forces the model to compute immediately rather
than carrying symbols through multiple steps. Each step produces a number, not
a description of a number. This eliminates the "now I need to substitute..."
paragraph that bridges symbolic and numeric reasoning.
- Important uncertainty, evidence, and risk survived compression.
