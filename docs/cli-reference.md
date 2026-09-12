# CLI Reference

- Status: Draft 0.1
- Source: issue #49 (repo hygiene); command implementations in `src/tikhon/cli.py`

## Overview

The `tikhon` CLI provides 13 subcommands for linting, sealing, executing,
inspecting, and auditing programs, plus external-driver and benchmark
tooling. All subcommands use argparse and the standard library only.

## Subcommand Catalog

| Subcommand | Required flags | Optional flags | Purpose |
| --- | --- | --- | --- |
| `lint` | `program` | — | Parse and validate a `.think` program file against the builtin registry |
| `seal` | `program` | — | Print the sealed SHA-256 digest of a program |
| `run` | `program`, `--db`, `--run-id`, `--seal` | `--workspace`, `--worker` | Execute a sealed program with deterministic or model worker |
| `resume` | `--db`, `--run-id`, `--program`, `--seal` | `--workspace`, `--worker` | Resume an interrupted run after a crash |
| `status` | `--db`, `--run-id` | — | Print run status with progress bar and current task |
| `events` | `--db`, `--run-id` | — | Print ordered event log as JSON lines |
| `audit` | `--db`, `--run-id` | — | Verify a persisted run against audit invariants |
| `learn` | `--runs` | `--out` | Mine a runs directory into protocol candidates and failure clusters |
| `bench` | — | `--repetitions`, `--out`, `--latency-seconds` | Run the deterministic benchmark harness with sleep-simulated workers |
| `next` | `--db`, `--run-id`, `--program`, `--seal` | `--workspace` | Render the task envelope for the next ready invocation (external driver) |
| `submit` | `--db`, `--run-id`, `--invocation-id`, `--result-file` | `--program`, `--seal`, `--claim-token`, `--claim-timeout` | Submit a result envelope for a dispatched invocation |
| `ready` | `--db`, `--run-id`, `--program`, `--seal` | `--workspace`, `--claim-timeout` | Render and claim the next ready invocation as a task envelope + claim token |
| `claim` | `--db`, `--run-id`, `--program`, `--seal` | `--claimant`, `--workspace`, `--claim-timeout` | Like `ready` but records the claimant name on the claim event |

## Command Groups

### Program lifecycle

- `lint` — parse and validate before sealing; rejects unknown commands and
  structural errors.
- `seal` — produces the SHA-256 digest the runtime pins at `RUN_STARTED`.
- `run` — executes a sealed program; verifies the seal before creating any
  run state. Worker selection: `deterministic` (default, CI baseline) or
  `model` (via `TIKHON_*` environment configuration).

### Run inspection

- `status` — progress bar, completed/total counts, current task text.
- `events` — ordered JSON event log (sequence number, event type, task id,
  instruction/invocation id, payload).
- `audit` — re-verify a persisted run against audit invariants; reports
  violations with event sequence numbers.

### Recovery and learning

- `resume` — resume an interrupted run from the last committed step; same
  seal verification and worker configuration as `run`.
- `learn` — mine a `demo/runs/` directory into `ProtocolCandidate` (support
  >= 2 distinct programs) and `FailureCluster` reports; outputs markdown.

### External driver

- `next` — render the `TaskEnvelope` for the next ready invocation; the
  external driver dispatches it to a worker.
- `submit` — commit a `ResultEnvelope` for a dispatched invocation; optional
  claim token validates the invocation's open claim.
- `ready` — atomically render and claim the next ready invocation; returns
  the task envelope with a claim token.
- `claim` — like `ready` but records a named claimant on the
  `INVOCATION_CLAIMED` event.

### Benchmarking

- `bench` — run the deterministic sleep-simulated benchmark harness with
  three built-in cases (linear frontier, scatter/gather, PAR heterogeneous);
  publishes speedup, context-cost, and delegation-granularity tables.

## Registry Vocabulary

The builtin command registry defines the vocabulary for all `DO` steps.
As of v0.1.0 the registry is frozen at **23 commands**: `calculate`,
`challenge`, `check`, `choose`, `compare`, `decompose`, `define`, `delegate`,
`edit`, `extract`, `fetch`, `hypothesize`, `prove`, `rank`, `recall`,
`remember`, `report`, `review`, `search`, `solve`, `summarize`, `test`,
`verify`.

The registry digest is recorded at `RUN_STARTED` and re-verified by
`tikhon audit`. See [02-command-catalog.md](spec/02-command-catalog.md) for
the full command contract specification and
[01-reasoning-language-foundation.md](design/01-reasoning-language-foundation.md)
for the design rationale behind the frozen vocabulary.
