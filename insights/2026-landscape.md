# 2026 Landscape: Who Cites Our Anchor Papers and What's New

> Searched 2026-09-14 via OpenAlex citations API + arxiv UI + live web (Futuris).
> Motivation: it has been ~10 months since FoldGRPO (Oct 2025) — check for
> scoops and successors before building TAHOE-VM.

## Direct successors of Context-Folding (FoldGRPO line)

### FoldAct — arXiv:2512.22733 (Dec 2025)
"Efficient and Stable Context Folding for Long-Horizon Search Agents"
- Fixes RL *training pathologies* of folding: summary tokens get diluted
  gradients; policy updates shift the summary distribution (self-conditioning
  → training collapse); non-stationary observation space violates RL
  assumptions. Solutions: separated loss for summary vs action tokens,
  full-context consistency loss.
- **Still ad-hoc summaries. No language, no typed state, no self-execution.**
- Signal: folding now has serious RL theory — the subfield is heating up.

### U-Fold — arXiv:2601.18285 (Jan 2026)
"Dynamic Intent-Aware Context Folding for User-Centric Agents"
- For multi-intent dialogues (tau-bench etc.): evolving intent summary +
  compact tool log each turn, instead of single irreversible summarization.
- **Their identified failure mode is our thesis:** existing folding
  "irreversibly discards fine-grained constraints and intermediate facts
  that are crucial for later decisions."
- **→ Typed refs ARE the retained fine-grained facts.** U-Fold engineers
  around the problem with heuristics; TAHOE solves it with language
  semantics (refs persist, folding only compresses narrative).

### Earl — DOI:10.1145/3805621.3807632 (2026)
"Efficient Agentic RL Post-Training for LLMs under Dynamic Context Lengths"
- Agentic RL with dynamic context-length management. Adjacent to the
  folding+RL line; confirms context management during RL training is an
  active 2026 problem.

## Other 2026 signals

- **DeepAgent** (DOI:10.1145/3774904.3792460): general reasoning agent with
  scalable toolsets — cites our anchor set; mainstream agent scaling work.
- **Exp²RL** (2026): expert-experience-augmented agent RL.
- Live-web trend check (Futuris): 2026 agent practice consolidates on MCP as
  the tool standard, tool-IDE convergence (Cursor/Claude Code/Codex), and
  token monitoring as standard hygiene (step limits, real-time cost guards).
  No language-layer reasoning protocols in practice.

## What was NOT found (checked, none exist)

Searched arxiv 2026 submissions for: model interpreting its own emitted
program, typed reasoning languages, program-as-protocol self-subcalls,
structured reasoning DSLs with verifiable steps. **Nothing.** The specific
intersection TAHOE-VM occupies — typed language + self-execution + free
machine-verified process rewards — remains unclaimed as of Sep 2026.

## Updated strategic read

The folding line (FoldGRPO → FoldAct → U-Fold → Earl) is industrializing
*ad-hoc* context folding from the RL-engineering side. The field converged on
OUR problem (unbounded context growth) but is solving it with heuristics and
RL machinery around free-text summaries. Nobody connected folding to:
(a) a typed language where "what survives folding" is a semantic property
(refs survive, narrative folds), (b) process rewards that are free because the
language itself verifies steps, (c) model self-execution.

**U-Fold's failure mode is our abstract:** folding that discards facts is a
language-design bug, not an engineering bug. We have the language.

Window assessment: still open, but the folding line ships every ~2 months.
Move fast on Stage 2 pilot.
