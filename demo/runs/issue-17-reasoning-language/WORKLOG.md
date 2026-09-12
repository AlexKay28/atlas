# WORKLOG — issue-17-reasoning-language

Seal: 4cb5afc1ad0b58ca287b49fee358213edc90defd7f0e3ebf0a9e6433fdca16d5
Program: demo/runs/issue-17-reasoning-language/program.think (linted valid, sealed
2026-09-12 19:35:50+03:00, seal.txt written 19:35:52+03:00; program.think untouched
afterwards — deliverable docs written after the seal)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #17 as a docs-only design/research deliverable: one design document
carrying (1) a design thesis, (2) a mechanism table with one row per issue source mapped
to real Tikhon constructs, (3) a falsifiable experiment register, (4) a tokenizer-grounded
notation policy, (5) non-goals — plus one document-map row in docs/README.md. No src/ or
tests/ changes; full suite must stay at 540 passed.
Outputs: G.plan = read the full issue body, verify every current-behavior claim against
src/ before writing, then produce docs/design/01-reasoning-language-foundation.md.
Evidence: /tmp/issue17.md (full body read); python3 -m pytest -q -> 540 passed (baseline).

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the constructs the issue's mechanisms must map onto. Read
docs/spec/01-language-and-state.md (canonical grammar sketch, deterministic expressions,
artifacts, DELTA), docs/spec/05 (envelope regions and control records — specified, not
implemented), docs/adr/0001-0003, docs/research/related-systems.md, and the implemented
subset in src/: parser.py (header/INPUT/DO/DONE/IF/CALL/RETURN/STOP/REVISE/RETIRE;
rejected keywords FIRST SCATTER GATHER LOOP TRY AWAIT APPROVE; 19-ref prefix list; KB.*
restrictions), registry/builtins.py (22 command specs with effect classes, budgets,
routing policies), registry/enums.py (T0-T3), memory.py (KnowledgeBase, kb. key prefix),
runtime/coordinator.py (protocol expansion, registry digest at RUN_STARTED), audit.py
(five invariant groups), learn.py (review-only mining, MIN_SUPPORT=2), protocols/
(framing.think: depth-8 bound, no recursion, seal-composition caveat).
Outputs: E.sources = the construct inventory above with file:line anchors.
Evidence: src/tikhon/syntax/parser.py:19,29-41,43,50-54,58-68,246-330,590-647,878-882,929-931;
src/tikhon/registry/builtins.py; src/tikhon/registry/enums.py:56-64; src/tikhon/memory.py;
src/tikhon/runtime/coordinator.py:57-67; src/tikhon/audit.py:7-17,133; src/tikhon/learn.py:1-11;
protocols/framing.think:1-12; docs/spec/01-language-and-state.md; docs/spec/05-live-authoring-and-routing.md:30-60.

## step.design
Status: succeeded
Inputs: E.sources
Actions: Mapped all 16 issue #17 source bullets (Iverson; Leibniz; Pospelov; Turchin;
Vygotsky; McCarthy; Kowalski; Peirce/Doyle/de Kleer; Russell & Wefald; Newell/Soar;
DreamCoder; Rissanen/MDL; Xu/Chain-of-Draft; Pfau; Yao/ReAct; Geng) onto the verified
inventory. Decisions: (a) mechanism rows name only implemented constructs for "exists"
claims and mark SCATTER/GATHER (#4) and envelopes (#18) as planned; (b) 15 experiments —
one per mechanism, with Russell&Wefald and Pfau sharing E9 (value-of-computation gating
evaluated on Pfau's required difficulty strata) to stay inside the 10-15 target;
(c) notation policy defers all symbol adoption to E1 with an interim keyword rule matching
the implemented grammar; (d) non-goals anchored on auditability (registry digest + audit
invariants) as the reason to reject self-modifying grammar and unverifiable heuristics.
Two initial syntax sketches were corrected against the implemented condition grammar
(no THEN keyword; no < on bare refs, only count() supports ordering operators).
Outputs: E.design = full doc outline: thesis, 16-row mechanism table, 15-experiment
register, notation policy, non-goals table.
Evidence: this design; corrected sketches use forms parser.py:263-330 accepts
(`IF count(E.tests) == 0 DO ...`, `IF V.review.status == "low" DO ...`).

## step.produce
Status: succeeded
Inputs: E.design
Actions: Wrote docs/design/01-reasoning-language-foundation.md (new docs/design/
directory) in the terse-table style of docs/spec/01: design thesis with three
commitments; mechanism table (16 rows, each with citation, borrowed mechanism, mapping
onto existing constructs with syntax sketches, or motivated construct); 15 falsifiable
experiments as compact tables (hypothesis, IV, DV, measurement, baseline, pass
threshold), common measurement ground stated once; notation policy (4-step decision
framework + interim keyword rule); non-goals table (6 rows). Updated docs/README.md with
exactly one new document-map row.
Outputs: ART.doc = docs/design/01-reasoning-language-foundation.md; docs/README.md row.
Evidence: file contents; all "exists" claims carry file:line citations verified in
step.locate; docs/README.md diff is one row after the Related Systems row.

## step.check
Status: succeeded
Inputs: ART.doc, C.done
Actions: Checked against C.done: 16 source bullets -> 16 mechanism rows (Peirce/Doyle/de
Kleer is one row, matching the issue's single bullet); 15 experiments, each with
hypothesis/IV/DV/measurement/baseline/pass threshold; notation policy has per-model
tokenizer protocol and interim rule; non-goals exclude self-modifying grammar and
unverifiable heuristics with the auditability rationale; docs/README.md gained exactly
one row; every sketch is parseable under the implemented grammar (two invalid sketches
caught and fixed in step.design); no src/, tests/, or .opencode/ files touched; no other
docs/ or demo/runs/ files touched.
Outputs: V.checks = all criteria pass (see evaluation.json).
Evidence: grep of mechanism-table rows and experiment headings; git status confined to
docs/design/, docs/README.md, demo/runs/issue-17-reasoning-language/; re-run of
`tikhon seal` reproduces the digest, proving program.think is unchanged since sealing.

## step.verify
Status: succeeded
Inputs: V.checks
Actions: Final verification: python3 -m pytest -q -> 540 passed (baseline preserved, no
production code written); seal digest re-verified against seal.txt; deliverable written
strictly after seal.txt (program.think mtime 19:35:50+03:00, seal.txt 19:35:52+03:00,
docs/design/01-reasoning-language-foundation.md created afterwards).
Outputs: V.result = task succeeded; all acceptance criteria pass.
Evidence: pytest output "540 passed"; `PYTHONPATH=src python3 -m tikhon seal
demo/runs/issue-17-reasoning-language/program.think` -> 4cb5afc1ad0b58ca287b49fee358213edc90defd7f0e3ebf0a9e6433fdca16d5.
