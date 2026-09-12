# solution.md — issue-17-reasoning-language

Seal: 4cb5afc1ad0b58ca287b49fee358213edc90defd7f0e3ebf0a9e6433fdca16d5

## Summary of design decisions

**Deliverable.** `docs/design/01-reasoning-language-foundation.md` — a research/design
foundation for issue #17, feeding the #16 roadmap. Docs-only; zero production code; the
540-test baseline is preserved.

**Design thesis.** Tikhon optimizes useful reasoning per token, not visual brevity.
Three commitments: preserve decision-relevant distinctions (the typed-ref namespace
E/A/H/D/V is the payload); expand difficult steps on demand (CALL protocols, DONE
predicates, and event replay all have recoverable expanded forms); and treat historical
inspiration as hypothesis only — every borrowed mechanism must pass a falsifiable
experiment before any grammar change.

**Mechanism table.** One row per issue source bullet (16 rows). Each "exists" claim is
anchored to implemented code: sealed programs (`tikhon lint`/`seal`/`audit`), DONE
predicates (`equals`/`in`/`matched`), single-line IF conditionals with the deterministic
condition grammar, the REVISE/RETIRE correction clause, CALL protocol expansion with a
depth-8 bound, cross-run KB memory, 22-command frozen registry with effect classes/
budgets/routing tiers, and review-only `tikhon learn` mining. SCATTER/GATHER and
envelopes are referenced as planned (#4, #18), never as current.

**Experiment register.** 15 falsifiable experiments, at least one per mechanism.
Russell & Wefald and Pfau share E9 deliberately: value-of-computation gating is the
mechanism, difficulty-stratified evaluation is the required measurement design, and
merging them keeps the register inside the 10-15 target without dropping either claim.
Every experiment declares hypothesis, IV, DV, measurement, an equal-task natural-language
(or specified stronger) baseline, and a numeric pass/fail threshold, on a common
measurement ground (total tokens incl. overhead, wall time, externally checked
correctness, syntax/semantic violation rates, audit pass rate, n >= 5).

**Notation policy.** Tokenizer-empirical, not aesthetic: a symbol replaces a keyword only
after E1 shows >= 10% median token saving on >= 2 model families with unchanged
correctness and syntax-failure rates, plus a documented recoverable expansion. Interim
rule: the current keyword grammar stands (lowercase commands, uppercase control
keywords); structural punctuation (`. : = , -> |`) is exempt because it delimits grammar
rather than abbreviating operations.

**Non-goals.** No self-modifying grammar (the frozen registry digest and audit invariants
are the audit base — auditability is the differentiator), no unverifiable heuristics
(every completion claim is a deterministic predicate or a recorded judgment), no
universal-calculus claims, no reading internal reasoning from traces, no fine-tuning-first
adoption, no uncontrolled macro accumulation.

**Protocol compliance.** program.think was framed, located, designed, produced, checked,
and verified in six steps; it was linted and sealed (digest above) before any deliverable
doc was written and never modified afterwards. WORKLOG.md records each step with
evidence; evaluation.json records acceptance.
