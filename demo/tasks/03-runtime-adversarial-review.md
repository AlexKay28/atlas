# Adversarial Runtime Review

## Goal

Find the most consequential correctness risks still present in the Tikhon
MVP after its current test suite passes.

## Scope

Review `src/tikhon/syntax/`, `src/tikhon/runtime/`, and
`src/tikhon/cli.py`. Read existing tests to avoid reporting behavior already
covered or intentional. Do not modify production or test code.

## Deliverable

Write `solution.md` as a findings-first code review containing:

1. Up to five distinct findings ordered by severity.
2. Exact file and line references for every finding.
3. A reachable failure scenario and user-visible consequence for each finding.
4. A minimal executable reproduction or precise regression-test sketch.
5. The smallest credible fix, without implementing it.
6. A final section listing investigated areas where no defect was found.

## Constraints

- Prioritize data corruption, false success, replay divergence, broken seal
  guarantees, and unusable CLI behavior over style concerns.
- Do not count missing future language features as bugs.
- Do not report speculative concurrency problems unless a current API permits
  the interleaving.
- Do not edit `src/`, `tests/`, or this task file.

## Acceptance

- Findings must be reproducible from the current source.
- Duplicate symptoms of one root cause count as one finding.
- If fewer than three real defects exist, say so rather than padding the list.
- Each severity must be justified by concrete impact.
