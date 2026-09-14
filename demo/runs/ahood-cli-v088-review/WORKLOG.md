# WORKLOG — ahood-cli-v088-review

Run id: `ahood-cli-v088-review`
Seal: `fbd37c6685180dd68133d82cdecbc0978cdca4dcf7088a89f0a139f1aca061a4`
Sealed before any review finding was recorded; verified reproducible with
`tahoe seal program.think --check "$(cat seal.txt)"` → `seal matches`, exit 0.

---

## step.frame — `define(request = G.goal)` → `G.plan`

**Status:** done
**Inputs:** G.goal
**Actions:** Framed the task as an adversarial review of ahood-cli `v0.8.0..HEAD`,
with the explicit constraint that the reviewing session also authored the code.
**Outputs:** G.plan — review the merged diff by dimension, re-deriving every finding
from current source rather than from session memory.
**Evidence:** `C.risk` in program.think names the bias threat; `step.challenge` exists
as a separate gate because of it.

## step.surface — `search(query, scope)` → `E.surface`

**Status:** done
**Inputs:** C.scope
**Actions:** `git diff --stat v0.8.0..HEAD`, then narrowed to `-- src/`.
**Outputs:** 41 files / 3986 insertions / 190 deletions overall; 32 commits.
Source-only surface is 10 files / 846 insertions / 118 deletions:

| File | Δ |
|---|---|
| `src/commands/add.ts` | 427 |
| `src/lockfile.ts` | 149 |
| `src/commands/remove.ts` | 127 |
| `src/commands/snap.ts` | 105 |
| `src/help.ts` | 58 |
| `src/terminal-safe.ts` | 29 (new) |
| `src/commands/update.ts` | 29 |
| `src/http.ts` | 23 |
| `src/flags.ts` | 15 |
| `src/index.ts` | 2 |

**Evidence:** commands above, reproducible at `87d7d21`.

## step.read / step.inventory — `fetch` → `ART.sources`, `extract` → `E.inventory`

**Status:** done
**Actions:** Read the changed source regions and classified them by what they change.
**Outputs:** E.inventory — six clusters:
1. mcp env-var resolution (secret + non-secret passes, `is_required`, non-TTY guard)
2. mcp fingerprinting (canonical hash + legacy fallback)
3. atomic write / temp-file lifecycle / permissions
4. terminal sanitization (new shared module + call sites)
5. snap tag surface (`create --tags`, `tags` verb, `list`/`search` filters)
6. test isolation (`restoreMocks`/`clearMocks`)

## step.dimensions — `decompose(goal, protocol = "review_dimensions")` → `G.dimensions`

**Status:** done
**Outputs:** four dimensions, chosen to partition the surface without overlap:
- **D1** correctness/edge cases — `add.ts`, `update.ts`
- **D2** concurrency/filesystem/permissions — `lockfile.ts`, `remove.ts`
- **D3** sanitization/untrusted data — `terminal-safe.ts`, `http.ts`, all call sites
- **D4** CLI parsing/command surface — `flags.ts`, `snap.ts`, `help.ts`, `index.ts`

## step.review — `review(artifact_refs, focus = G.dimensions)` → `ART.candidates`

**Status:** in progress
**Actions:** Dispatched four independent read-only reviewers, one per dimension.
Fresh contexts by design: the orchestrating session authored the code, so recall is
not admissible evidence here (`C.risk`). Each reviewer was told to mark findings
CONFIRMED vs PLAUSIBLE, to cite file:line in current source, and that returning
"no confirmed defects" is a valid outcome rather than a failure to be padded.
**Outputs:** pending
**Evidence:** pending

## step.challenge — `challenge(claim = ART.candidates, evidence)` → `E.survivors`

**Status:** not started — gated on step.review.

---

## step.review — completed for D1, D3, D4

**Status:** done (D2 pending at time of writing; see evaluation.json)
**Actions:** Four independent reviewers ran read-only against `87d7d21`.
**Outputs:** ART.candidates — 9 findings (D1), 13 (D3), 8 (D4).
**Evidence:** task transcripts; each finding carried file:line + CONFIRMED/PLAUSIBLE.

## step.challenge — `challenge(claim = ART.candidates, evidence)` → `E.survivors`

**Status:** done
**Inputs:** ART.candidates, ART.sources, C.risk
**Actions:** Re-derived the highest-severity claims from source rather than accepting
the reviewers' write-ups. Where a claim was empirically testable, it was executed
against the built CLI with a local echo server on 127.0.0.1:8799 (no live registry
mutation). One claim the reviewer could not settle was settled here using the server
repo it lacked access to.

**Survivors (independently re-verified by the orchestrator):**

| ID | Claim | How verified |
|---|---|---|
| D1-1 | `installMcpEntry` rolls back `.mcp.json` only on checksum conflict; any other lockfile failure strands a plaintext secret with no pin and no CLI recovery | read `add.ts:713-728` vs `updateMcpEntry:812-832`; **reproduced live** — seeded the state, `remove` printed "was not installed -- nothing to remove" exit 1, `grep` confirmed `sk-live-SECRET` still on disk |
| D1-4 | mcp cannot self-heal a deleted `.mcp.json` entry when already at latest; skill/agent can | read `update.ts:135-149` — short-circuits before `updateMcpEntry`; skill/agent fall through to unconditional `add()` |
| D3-1 | `read.ts:88` writes unbounded raw registry content to stdout with no `isTTY` check | read source; `grep -c isTTY read.ts` → **0** |
| D4-2 | `snap list` silently ignores unknown flags/positionals, returning the UNFILTERED set as if filtered | wire: `snap list --tag ci` → `GET /api/v1/snaps` (no tags param), exit 0 |
| D4-3 | `snap create` folds unknown flags into the note body | wire: `POST {"content":"my note --tag deploy"}` |
| D4-3b | space-separated tag list corrupts the **content** | wire: `snap create "note" --tags deploy bugfix` → `POST {"content":"note bugfix","tags":["deploy"]}` |
| D4-4 | space-separated tags on the `tags` verb become one multi-word tag | wire: `PATCH {"tags":["deploy bugfix"]}` |
| D4-6 | a repeated `--tags` silently drops the second value and eats the neighbouring token | wire: `snap search foo --tags a --tags bar` → `?q=foo&tags=a` — "bar" gone |

**Demoted / discarded (reported, not silently dropped, per C.done):**

- **D1-8** (multi-package + single-remote manifest prompts for secrets it then discards):
  reviewer marked reachability UNKNOWN for lack of server code. Settled here against
  `AlexKay28/ahood` `lib/publish/parse-server-manifest.ts:106-110`: `hasPackages ===
  hasRemotes` is rejected outright and `packages` must have exactly one entry, so the
  shape cannot be published. **Demoted to defense-in-depth**, not a live defect.
- **D1-5** (required non-secret aborts an unattended batch update): CONFIRMED behavior,
  but `tests/mcp-lifecycle.test.ts:335` pins it deliberately. A design disagreement, not
  a defect — recorded as such rather than counted as a finding.
- **D3-7** (secret prompt phishable with plain printable ASCII) and **D3-8** (newline
  flattening defeated by terminal wrap at the 200-char cap): both are "the stated model
  is too narrow" claims rather than gaps in the implemented control. D3-8 the reviewer
  itself marked PLAUSIBLE. Kept as model critique, not as implementation defects.

## step.test — `test(path = "tests/")` → `V.tests`

**Status:** done. `npm test` → **581 passed / 36 files**.
`DONE matched(V.tests, "passed")` — satisfied.
