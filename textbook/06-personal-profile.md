# Personal Thinking Profile

## Purpose

A personal profile adapts the language to one person's stable working preferences. It
should reduce repeated negotiation about response style and process without changing
the meaning of core nodes or links.

The profile is not a personality label and should not attempt to encode every habit. It
contains only preferences that repeatedly improve outcomes across tasks.

## Classification Boundary

When analyzing a personal note, classify it as one of four layers:

| Layer | Test | Example |
| --- | --- | --- |
| Core language | Must mean the same thing for every user | `supports` link semantics |
| Generic protocol | Useful procedure for a task class | Reproduce before debugging |
| Personal profile | Stable individual preference | Findings before summary |
| Task instance | True only for the current problem | Deadline is Friday |

Do not place a rule in the personal profile if it belongs to the core or a reusable
protocol. Do not place temporary project context in the profile.

## Sections to Collect

### Outcome Style

- What should appear first: decision, evidence, plan, or questions?
- Which artifacts are normally useful?
- Which information is usually unwanted?
- When should the AI provide one recommendation versus several options?

### Detail and Compression

- Preferred default response length
- Familiar domains where basic explanation can be omitted
- Terms and abbreviations safe to use without expansion
- Conditions that justify a longer answer
- Preferred use of prose, tables, examples, or graphs

### Challenge Level

- When should assumptions be challenged automatically?
- Should the AI point out conflicts with earlier decisions?
- How much evidence is required before acting?
- When should the AI ask a question rather than choose a reasonable default?

### Decision Style

- Preference for reversible experiments versus upfront analysis
- Tolerance for uncertainty
- Typical ranking criteria
- Conditions requiring explicit alternatives
- Conditions requiring human approval

### Execution Style

- Whether the AI should act autonomously or propose a plan first
- Preferred granularity of actions
- Expected verification before reporting completion
- How blockers and partial results should be reported
- Whether follow-up actions should be proposed automatically

### Learning Style

- Preference for examples, principles, exercises, or analogies
- Whether to test understanding with questions
- Desired balance between direct answer and conceptual explanation
- How corrections should be recorded for later reuse

### Risk and Escalation

- Domains requiring additional caution
- Irreversible actions requiring confirmation
- Sensitive data boundaries
- Cost, time, or token limits
- Conditions that require an independent check

## Observation Before Encoding

Do not ask the user to invent a complete profile from memory. Extract candidate rules
from real sessions:

1. Record the original request and result.
2. Identify clarification, repetition, rework, or excessive detail.
3. Ask which behavior should have been different.
4. Convert that difference into a testable candidate rule.
5. Apply it in another task.
6. Keep it only if it improves repeated outcomes.

Example:

```text
Observation: Long introductions are repeatedly skipped.
Candidate: Return requested artifact before background.
Test: Apply to three different task classes.
Keep if: No required context is lost and review time decreases.
```

## Rule Format

Each personal rule should contain:

```text
RULE.<id>
trigger: <when it applies>
behavior: <observable AI behavior>
unless: <exception or escalation condition>
reason: <what cost or failure it prevents>
check: <how to know the rule helped>
```

Example:

```text
RULE.output_first
trigger: A requested artifact can be produced without clarification.
behavior: Put the artifact before explanation.
unless: A missing constraint could materially change the artifact.
reason: Reduce reading time and repeated requests for the actual result.
check: The first section is directly usable.
```

Rules without triggers become overgeneralized. Rules without exceptions become unsafe.
Rules without checks cannot be improved empirically.

## Conflict Resolution

Apply rules in this priority:

```text
safety and law
> explicit current request
> hard task constraints
> selected protocol
> personal profile
> generic defaults
```

A personal preference never overrides a current explicit instruction or safety boundary.
When two profile rules conflict, select the more specific trigger. If specificity is
equal, prefer the rule preserving correctness and reversibility.

## Candidate Profile Schema

The first profile can remain human-readable:

```text
@profile <name>
version: 0.1

PF.detail: concise
PF.order: result,evidence,next
PF.autonomy: act_when_reversible
PF.challenge: challenge_material_assumptions
PF.questions: ask_only_if_answer_changes_action
PF.options: recommend_one_with_rejected_alternatives
PF.verify: always_report_check
PF.escalate: security,privacy,irreversible,costly
```

This is illustrative, not yet a standardized serialization. Profile keys should be
added only after their behavior is defined by tested rules.

## Questions for the Personal-Sections Session

Use concrete examples rather than abstract preference questions:

1. Show a recent AI answer that felt slow or wasteful. Which part was unnecessary?
2. Show a response that was concise but unusable. What critical detail was missing?
3. When do you want immediate execution, and when do you want a plan first?
4. Which assumptions should an AI be allowed to make without asking?
5. Which mistakes are cheap to repair, and which are unacceptable?
6. Do you prefer one recommendation or a comparison table for important decisions?
7. What evidence makes you trust a conclusion?
8. How should disagreement or contradiction be presented?
9. What must always be verified before the AI says work is complete?
10. Which repeated instructions do you currently give in most sessions?

## Anti-Patterns

Avoid profile rules such as:

- "always be concise," because some tasks require evidence;
- "never ask questions," because missing constraints can invalidate work;
- "always give five options," because option count is not decision quality;
- "agree with my approach," because challenge is sometimes necessary;
- "think step by step," because visible artifacts and checks are more useful than a
  requested private reasoning transcript;
- "remember everything," because temporary context and sensitive information need
  boundaries.

## Profile Maintenance

Review the profile when:

- the same correction occurs twice;
- a rule creates rework in more than one task;
- a preference becomes domain-specific;
- the user's role, risk tolerance, or workflow changes;
- a generic protocol now captures the behavior better.

Version profile changes and record a short reason. Remove rules that no longer produce
an observable benefit. A smaller tested profile is better than a comprehensive but
contradictory one.

## Completion Criteria

The initial personal profile is ready when:

- every rule has a trigger, behavior, exception, reason, and check;
- rules were derived from at least two real task types;
- temporary project facts are absent;
- conflicts have a deterministic priority;
- the profile reduces repeated instructions without lowering acceptance quality;
- another AI can apply the profile consistently from the text alone.
