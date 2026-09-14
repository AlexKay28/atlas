# WORKLOG — ahood-cli-findings-sprint

Seal: `0b5042ca418e5bf9f6782644e97b49dca76db12add0648a1e8144c9dc2e5777e`
Sealed before any source edit; verified reproducible.

## Waves as executed

| Wave | Issues | PRs | Outcome |
|---|---|---|---|
| 1 | 140, 132, 133 | #145, #146, #147 | merged |
| 2 | 141*, 135, 142, 139 | #153, #148, #149, #150 | merged |
| 3 | 144*, 134, 143 | #154, #152, #151 | merged |
| 4 | 136 | #155 | merged |
| 5+6 | 137 + 138 (combined) | #156 | merged |

\* #141 and #144 slipped a wave: both are in the `lockfile.ts` lane behind #140,
and branching either while PR #145 was open would have forked from a base about
to change. Lane serialisation was the binding constraint throughout, not severity.

## Per-step

- **step.frame / locate / read / analyze / lanes / siblings / challenge_siblings** — done.
  The lane partition (lockfile 140→141→144, snap 135→134→137→138, remove 142→143)
  is what the wave table above follows.
- **step.w1_lock / w1_add / w1_read → BARRIER → w1_test** — done. `DONE matched(V.t1,"passed")` satisfied.
  #140 needed a second commit: CI failed where local passed, because `rmSync` on an
  unremovable directory deletes contents first on the GitHub runner but not on local
  ext4, which flipped `isLockStale` false and wiped the remembered reclaim error.
- **step.w2_* → BARRIER → w2_test** — done, gate satisfied.
- **step.w3_* → BARRIER → w3_test** — done, gate satisfied.
- **step.w4_flags → w4_test** — done, gate satisfied.
- **step.w5_snap / w6_snap → tests** — executed as ONE change; see protocol_deviations.
- **step.regress / review / verify / report** — done. 581 → 664 tests, no existing
  test edited to accommodate a fix except where an intended interface change
  invalidated its premise (recorded in evaluation.json).

## C.risk — the sibling-path constraint

Every brief required naming the sibling path. It paid out four times:
- #132 widened the skill/agent rollback paths alongside the mcp one.
- #134 converged on the helper #135 had left unwired rather than adding a variant.
- #136 found `parseSearchQuery` was a second hand-rolled copy carrying the same bug,
  and folded it in; it also fixed `skill search`, outside the issue's scope, and said so.
- #137/#138 folded in `tagsSnap`, the last remaining copy.
