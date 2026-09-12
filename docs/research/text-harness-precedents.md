# Text Harness and AI Language Precedents

Futuris and GLM-5.3-Flash research sessions were used on 2026-09-12 to compare public
systems with the project's live text-harness goal.

## Live and Executable Documents

Literate programming and Org Babel show that prose and executable blocks can coexist in a
single source. Jupyter shows the risk of hidden mutable state and out-of-order execution.
Reactive notebooks such as Pluto and marimo improve this by deriving execution from data
dependencies and invalidating affected cells after edits.

Hazel and typed holes show that incomplete source can remain structurally meaningful. The
project adopts a stricter boundary: incomplete program regions may be parsed and linted,
but cannot dispatch. Terraform's plan/apply distinction inspires separate `SEAL` and `RUN`
gates. Incremental systems such as Salsa and hermetic build systems inspire digest-based,
dependency-scoped invalidation.

Sources:

- [Knuth, Literate Programming](https://www.literateprogramming.com/knuthweb.pdf)
- [Org Babel](https://orgmode.org/worg/org-contrib/babel/intro.html)
- [marimo reactivity](https://docs.marimo.io/guides/reactivity/)
- [Pluto](https://plutojl.org/)
- [Hazel](https://hazel.org/)
- [GHC typed holes](https://downloads.haskell.org/ghc/latest/docs/users_guide/exts/typed_holes.html)
- [Tree-sitter](https://tree-sitter.github.io/tree-sitter/)
- [Salsa](https://github.com/salsa-rs/salsa)
- [Terraform planning behavior](https://github.com/hashicorp/terraform/blob/main/docs/planning-behaviors.md)
- [Bazel hermeticity](https://bazel.build/basics/hermeticity)

## AI-Oriented Languages

| System | Useful idea | Missing relative to this project |
| --- | --- | --- |
| LMQL | Generation variables and inline constraints | Durable orchestration and epistemic state |
| Guidance | Fixed and constrained generated text; grammar testing | Multi-agent state and effect policy |
| DSPy | Typed signatures and metric-driven optimization | Textual runtime and durable event timeline |
| BAML | Prompt functions with typed generated clients | Multi-step orchestration and graph memory |
| IBM PDL | Interpreted prompt document, schema, and replay trace | Atomic reasoning contracts and effect safety |
| Prompt Flow | DAG execution, tracing, and evaluation | Readable epistemic reasoning language |
| Semantic Kernel | Described typed tool functions | Text-level program and strict completion semantics |
| LangGraph | Stateful graph, checkpointing, interrupts | Language syntax and bounded atomicity contracts |
| ReWOO | Planner writes symbolic evidence slots for workers | Typed state, validation, and durable failure policy |
| LLMCompiler | Parallel task DAG reduces latency and cost | Stable textual semantics and effect governance |
| CodeAct | Executable code reduces tool-call turns | Restricted readability, safety, and replayability |

Sources:

- [LMQL](https://arxiv.org/abs/2212.06094)
- [Guidance](https://github.com/guidance-ai/guidance)
- [DSPy](https://arxiv.org/abs/2310.03714)
- [BAML](https://docs.boundaryml.com/guide/introduction/what-is-baml)
- [IBM Prompt Declaration Language](https://arxiv.org/abs/2410.19135)
- [Prompt Flow](https://github.com/microsoft/promptflow)
- [Semantic Kernel](https://github.com/microsoft/semantic-kernel)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [ReWOO](https://arxiv.org/abs/2305.18323)
- [LLMCompiler](https://arxiv.org/abs/2312.04511)
- [CodeAct](https://arxiv.org/abs/2402.01030)

## Distinctive Combination

No reviewed system combines all of these properties:

- plain-text source intended for both people and AI agents;
- first-class facts, evidence, assumptions, hypotheses, unknowns, and decisions;
- incremental authoring with inert drafts and immutable executable seals;
- live overlap between smart-model planning and cheap-worker execution;
- deterministic coordinator over probabilistic workers;
- per-command contracts, evidence, failure, and completion;
- durable replay, dependency-scoped invalidation, approval, and compensation;
- quality-preserving model routing measured per command.

The project's novelty is not a new general-purpose programming language. It is a compact
textual discipline that converts expensive model attention into an inspectable program and
lets cheaper agents execute its bounded semantic operations without weakening quality.

## Design Lessons

1. Generated syntax should be small and predictable; deterministic text should not consume
   model reasoning.
2. Named output slots reduce repeated observation and context, as demonstrated by ReWOO.
3. Static task dependencies permit parallel dispatch, as demonstrated by LLMCompiler.
4. Typed signatures and metrics make model substitution testable, as demonstrated by DSPy.
5. Schema validity does not prove truth; semantic checks and evidence remain necessary.
6. Notebook hidden state must be avoided through immutable events and dependency replay.
7. A live edit must create a new revision, never patch an in-flight program.
8. Execution requires a positive gate; apparent textual completeness is insufficient.
