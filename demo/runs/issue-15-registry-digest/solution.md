# solution.md — issue #15: Registry digest in RUN_STARTED + hyphen-tolerant program names

Seal: `3f2c99f04e430fd6b82ea10ecf3a1e924e3e9fafb88ec9e0c7e34edc6eeb5c16`
(program.think sealed before any source edit and never modified afterwards)

## Digest formula

`registry_digest(registry)` in `src/tikhon/registry/registry.py`:

1. For every registered `(name, version)` pair, take the summary tuple
   `(name, version, effect_class.value, execution.value, routing.minimum_tier.value)`.
2. Sort the tuples lexicographically (registration order cannot leak in).
3. Serialize as canonical JSON — `json.dumps(summaries, ensure_ascii=False,
   separators=(",", ":"), sort_keys=True)` — and return
   `sha256(payload.encode("utf-8")).hexdigest()`.

Builtin catalog digest at time of writing:
`9160b5ecc029cd02da9c109fe578c7e1ec1714c6b82267bc17157addb73381b7`.
It is cheap (one small tuple per spec, no full-contract dumps) and any change
to the spec set — a new command, a new version, or a changed effect class /
execution mode / minimum tier — changes the digest.

## Where the digest is recorded

`SequentialCoordinator.execute` (`src/tikhon/runtime/coordinator.py`)
resolves the builtin registry's digest lazily with a module-level cache
(computed once per process) and records it in two places:

- `store.create_run(...)` metadata: `{"program": name, "registry_digest": digest}`;
- the `RUN_STARTED` event payload: `{"program": name, "version": version,
  "registry_digest": digest}` — the key is added alongside the existing
  `program`/`version` keys; no existing assertion on those keys breaks.

## Audit compatibility (requirement 2 — confirmed, no change needed)

`src/tikhon/audit.py` (read-only for this issue) never reads `RUN_STARTED`
contents: `audit_run` checks gapless sequencing, event truthfulness,
invocation-id binding, ledger settlement, and projection determinism only.
Legacy event stores whose `RUN_STARTED` lacks a registry digest therefore
audit clean; `tests/test_audit.py::test_audit_clean_on_legacy_run_without_registry_digest`
proves it with a hand-built pre-digest run.

## Hyphen-tolerant program names

`src/tikhon/syntax/parser.py` now defines `_PROGRAM_NAME = r"[a-z][a-z0-9_-]*"`
used only by `_HEADER_RE`, so PROGRAM header names may contain hyphens after
the first character (`issue-15-registry-digest` is now a legal program name).
Step ids, typed-reference leaf segments, command names, argument names, and
STOP kinds keep the underscore-only `_NAME` pattern. Sealing is unchanged:
`canonical_json` already carries `program.name`, and the digest stays
deterministic (the sealed program re-seals to its recorded digest).

`.opencode/skills/tikhon-demo/SKILL.md` had its PROGRAM/step identifier
sentence replaced: hyphens allowed after the first character of program
names; underscore rule kept for step ids and reference leaf names.

## Tests added

- `tests/test_syntax.py` (5): hyphenated program name parses + seals
  deterministically; leading-hyphen and leading-digit headers rejected;
  hyphenated step id still rejected; underscore names unchanged.
- `tests/test_coordinator.py` (3): RUN_STARTED payload and run metadata
  carry the stable builtin digest; two coordinators on the same registry
  produce equal digests; a registry extended through the Registry API
  (`dataclasses.replace` of a builtin spec under a new name) changes the digest.
- `tests/test_audit.py` (1): legacy run without a registry digest audits clean.

Full suite: **274 passed** (baseline 265 + 9).

## Notes and limitations

- The sealed demo program uses the underscore name `issue_15_registry_digest`:
  the protocol requires sealing before source edits, so it had to parse under
  the pre-change grammar. The hyphenated form is exercised by the new tests
  and a CLI check (`PROGRAM a-b-c` lints and seals deterministically).
- The installed `~/.local/bin/tikhon` console script resolves a stale
  site-packages copy of `tikhon`; repo code was verified via
  `PYTHONPATH=src python3 -m tikhon ...` (the pytest config already injects
  `src` via `pythonpath = ["src"]`). The sealed program's digest is identical
  under both copies.
- Untracked `demo/runs/issue-05-kb-memory/` and `src/tikhon/memory.py` belong
  to the concurrent agent and were left untouched.
