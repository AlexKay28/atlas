# Insights

> Research dossier extracted 2026-09-14 from a deep web/arxiv search for the
> TAHOE-VM direction (model as compiler+executor of its own reasoning program).
> Every claim verified against the source paper or live experiments in this repo.

## Index

| File | Topic |
|---|---|
| [three-stage-arc.md](three-stage-arc.md) | THE thesis: teach by prompt → practice by execution → internalize by RL |
| [execution-harnesses.md](execution-harnesses.md) | ReWOO, LLMCompiler, StateFlow, CodeAct, SGLang, PAL, TapeAgents, Agent Lightning |
| [self-execution-recursion.md](self-execution-recursion.md) | Recursion of Thought, LAMBADA, Least-to-Most, Atom of Thoughts |
| [rl-trajectories.md](rl-trajectories.md) | Let's Verify, RAGEN/StarPO, MURPHY, FoldGRPO — RL over multi-turn reasoning |
| [token-efficiency.md](token-efficiency.md) | Chain of Draft, L1/LCPO, CoT-Valve, TALE, Stop Overthinking |
| [frontier-lab-insights.md](frontier-lab-insights.md) | Anthropic + OpenAI public research relevant to TAHOE-VM |
| [token-economics.md](token-economics.md) | Our VM token accounting: the 145-token trap and the 4 levers |
| [cross-model-findings.md](cross-model-findings.md) | GLM-5.3-Flash vs gpt-oss-120b: 63,348-trial results and what they mean |
| [grader-lessons.md](grader-lessons.md) | The BBH "(X)" format bug — eval integrity lessons |
| [gap-analysis.md](gap-analysis.md) | Capability matrix, precise novelty statement, risk register |
| [vm-design.md](vm-design.md) | TAHOE-VM architecture and open design decisions |
| [2026-landscape.md](2026-landscape.md) | Who cites our anchors in 2026: FoldAct, U-Fold, Earl — niche still open |

## The one-paragraph summary

TAHOE-VM proposes: model compiles a task into a TAHOE program (typed refs +
protocols), then *executes that program on itself* — one atomic self-subcall per
step, harness holding only refs and validation, context growing O(refs) not
O(history). The whole execution is ONE machine-verified trajectory (DONE
predicates + parse/typecheck = free process rewards), directly consumable by
GRPO-style RL. No published work combines all of these; nearest neighbors are
ReWOO (harness-executed, untyped), Recursion of Thought (self-subcalls, no
program), FoldGRPO (RL folding, no language).
