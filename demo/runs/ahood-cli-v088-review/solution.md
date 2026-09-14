# Review of ahood-cli `v0.8.0..HEAD` (released as v0.8.1–v0.8.8)

Run `ahood-cli-v088-review` · seal `fbd37c6685180dd68133d82cdecbc0978cdca4dcf7088a89f0a139f1aca061a4`
Target `87d7d21` · 32 commits · 10 source files / 846 insertions · suite 581 green

Eight findings survived challenge. Every one was re-derived from source by the
orchestrator, not accepted from a reviewer's write-up; six were reproduced on the wire
or on disk. The reviewing session authored the code under review, which is why the
sealed plan made `challenge` a distinct gate.

---

## 1. HIGH — a failed lockfile write during `skill add` strands a plaintext secret with no CLI recovery

`src/commands/add.ts:719`

```js
} catch (error) {
  if (!(error instanceof LockfileChecksumConflictError)) throw error;   // no rollback
```

`updateMcpEntry:826` rolls back for **every** lockfile failure, and the comment there
names this exact hazard. `installMcpEntry` never got the same widening.

**Reproduced.** Seed `.mcp.json` with an mcp entry holding a secret and an empty
lockfile — the state a `withLock` timeout or ENOSPC leaves behind:

```
$ ahood skill remove alice/weather --yes
alice/weather was not installed -- nothing to remove.      [exit 1]
$ grep -o sk-live-SECRET .mcp.json
sk-live-SECRET
```

`remove` bails at `remove.ts:28` because there is no lockfile entry; `add` refuses at
`assertNoCollision`. The credential is removable only by hand-editing `.mcp.json`, and
nothing tells the user it is there. **Fix:** widen the guard to match `updateMcpEntry`.

## 2. HIGH — `ahood skill read` writes unbounded, unsanitized remote content to a terminal

`src/commands/read.ts:88` — `process.stdout.write(content)`, `grep -c isTTY` → **0**.

This is the command the CLI advertises for inspecting a skill *before* installing it.
A published SKILL.md containing `ESC]52;c;<base64> BEL` overwrites the reader's system
clipboard on xterm/kitty/wezterm/foot; cheaper variants retitle the window or clear the
screen and forge "verified safe" output.

The piping rationale is sound — `read` exists to be redirected — but it only holds when
stdout is not a TTY, and that distinction is never made. **Fix:** sanitize when
`process.stdout.isTTY`, leave the piped path byte-exact.

## 3. HIGH — `snap create` silently corrupts the note body

`src/commands/snap.ts:100-102`. Wire-confirmed:

```
$ ahood snap create "note" --tags deploy bugfix
  → POST {"content":"note bugfix","tags":["deploy"]}
```

`bugfix` lands in the **content**. The user sees an id and exit 0; the stored note is
not the note they wrote. Same shape for any unrecognized flag:

```
$ ahood snap create "my note" --tag deploy
  → POST {"content":"my note --tag deploy"}
```

Commit `4574cb5` fixed precisely this class for `snap tags` and did not carry it to
`snap create`. Freeform content makes a blanket `--` rejection wrong, but a leading-`--`
token that is not `--json`/`--tags` should be refused.

## 4. MEDIUM-HIGH — `snap list` presents an unfiltered list as a filtered one

`src/commands/snap.ts:147-161` — no unknown-flag check. Wire-confirmed:

```
$ ahood snap list --tag ci        # singular typo
  → GET /api/v1/snaps             # no tags param at all
You have no snaps yet…            [exit 0]
```

`snap search --tag ci` correctly errors. Two sibling commands sharing one flag diverge
on the identical typo, and the one that stays silent returns *everything* as though it
were the filtered set — the exact failure the verbatim-pass-through design was chosen to
avoid ("dropping a term would silently broaden the result set"). The CLI defended the
server's contract and left the larger hole — the flag never arriving — open.

## 5. MEDIUM — a repeated `--tags` drops its value and eats the next token

`src/flags.ts:54` + `flagValue` returning the first match. Wire-confirmed:

```
$ ahood snap search foo --tags a --tags bar
  → GET /api/v1/snaps?q=foo&tags=a          # "bar" gone from the query
```

Last-wins or an explicit error are both defensible; silently keeping the first *and*
deleting the neighbouring word is not.

## 6. MEDIUM — space-separated tags become one multi-word tag

`src/commands/snap.ts:296-297`. Wire-confirmed: `snap tags snap_123 deploy bugfix` →
`PATCH {"tags":["deploy bugfix"]}`. The join-then-split rescues unquoted `"tag1, tag2"`
but cannot distinguish it from space separators, and the echoed line
`Tags for snap_123: deploy bugfix` looks identical to two correct tags.

## 7. MEDIUM — `snap tags <id>` wipes every tag, and it is the natural "show my tags" command

`src/commands/snap.ts:304-311`. No `confirm()` gate, unlike `removeSnap` and
`unshareSnap`. What makes the accident plausible: **there is no read-only way to see one
snap's tags** — `snap show` prints content only. A user asking "what tags does this
have?" reaches for `snap tags <id>` and destroys the answer by asking. `git tag`,
`docker tag` and `hg tags` all read on the bare form.

## 8. MEDIUM — mcp cannot self-heal a deleted `.mcp.json` entry once it is at latest

`src/commands/update.ts:137-146` short-circuits before `updateMcpEntry`, so the
self-heal path documented at `add.ts:745` only runs when a newer version exists. A
skill or agent in the same state is repaired, because `update` calls `add()`
unconditionally. `.mcp.json` is a shared, commonly-committed file, so losing an entry
to a merge is ordinary.

---

## Demoted, with evidence — recorded rather than dropped

- **multi-package + single-remote manifest** (reviewer: reachability UNKNOWN). Settled
  against the server repo the reviewer lacked: `parse-server-manifest.ts:106-110`
  rejects `hasPackages === hasRemotes` and requires exactly one `packages` entry, so the
  shape cannot be published. Defense-in-depth only.
- **required non-secret aborts an unattended batch update** — confirmed behavior, but
  `tests/mcp-lifecycle.test.ts:335` pins it deliberately. A design disagreement.
- **secret prompt phishable in plain ASCII**, **newline flattening defeated by wrap** —
  critiques of the threat model's scope, not gaps in the implemented control.

## The pattern worth naming

Five of eight findings are the same shape: **a fix applied to one path and not its
sibling.** Rollback widened in `update` but not `install`; unknown-flag rejection added
to `snap tags` but not `snap create` or `snap list`; sanitization applied to archive
content but not to the registry-JSON display surface. Each was a correct local fix whose
symmetric case was never checked — which is a review-process gap, not a coding one.
