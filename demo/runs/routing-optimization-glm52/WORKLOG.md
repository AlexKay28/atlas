# WORKLOG — routing-optimization-glm52

**Seal:** 5215a00d87ba7c2adf03866712ba1da1c7d8b531fb28147b0d39d0dd8fd9ae63
**Task:** demo/tasks/02-routing-optimization.md

---

## step.frame
Status: succeeded
Inputs: G.task = "Choose a static model tier for each of four independent atomic jobs, minimizing total cost while keeping the probability that all jobs succeed at or above 0.90"
Actions: Framed the task as a constrained optimization: minimize total cost over 4 jobs × 3 tiers = 81 assignments, subject to joint success probability ≥ 0.90.
Outputs: G.plan = "Exhaustive enumeration of all 81 tier assignments; find min-cost feasible at thresholds 0.90 and 0.85; sensitivity analysis on the 0.90 optimum."
Evidence: Task file demo/tasks/02-routing-optimization.md lines 1-44 define the goal, data table, deliverables, and acceptance criteria.

---

## step.locate
Status: succeeded
Inputs: G.plan, C.scope = "demo/tasks/02-routing-optimization.md"
Actions: Searched the task file for the data table and constraints. The scope is a single file with all required data inline.
Outputs: E.candidates = "demo/tasks/02-routing-optimization.md"
Evidence: The task file contains the complete data table (lines 14-19) and all constraints.

---

## step.read
Status: succeeded
Inputs: E.candidates
Actions: Read the task file demo/tasks/02-routing-optimization.md in full (44 lines).
Outputs: ART.sources = full text of the task file
Evidence: Read tool returned all 44 lines including the data table with success/cost for each job × tier combination.

---

## step.analyze
Status: succeeded
Inputs: ART.sources, schema = "findings"
Actions: Extracted the data table into structured form:
  Job A: small (p=0.82, c=0.20), focused (p=0.95, c=0.80), heavy (p=0.990, c=2.00)
  Job B: small (p=0.70, c=0.20), focused (p=0.94, c=0.90), heavy (p=0.995, c=2.40)
  Job C: small (p=0.88, c=0.25), focused (p=0.96, c=0.75), heavy (p=0.990, c=1.80)
  Job D: small (p=0.75, c=0.15), focused (p=0.93, c=0.70), heavy (p=0.985, c=1.70)
  Constraints: one attempt per job, independent outcomes, cost charged once, static policy.
Outputs: E.findings = structured data table (4 jobs × 3 tiers, each with success probability and cost)
Evidence: Task file lines 14-19.

---

## step.calc
Status: succeeded
Inputs: E.findings, schema = "exhaustive"
Actions: Wrote and executed `calculate.py` which enumerates all 3^4 = 81 assignments using itertools.product. For each assignment, computed total_cost = sum of costs and joint_prob = product of success probabilities. Sorted by cost ascending.
Outputs: E.enumeration = 81 assignments with cost and joint probability, saved to calculation_output.txt
Evidence: `python3 calculate.py` produced full enumeration table. All 81 assignments listed with cost and joint_prob columns.

---

## step.optimize90
Status: succeeded
Inputs: E.enumeration, schema = "min-cost-threshold-0.90"
Actions: Scanned the sorted enumeration for the first assignment with joint_prob >= 0.90.
Outputs: E.optimum90 = {assignment: A=heavy, B=focused, C=heavy, D=heavy, total_cost: 6.40, joint_prob: 0.907475}
Evidence: Assignment #77 in sorted order. joint_prob = 0.990 × 0.940 × 0.990 × 0.985 = 0.90747459. All 76 cheaper assignments have joint_prob < 0.90 (highest is 0.893828 at cost 5.65).

---

## step.optimize85
Status: succeeded
Inputs: E.enumeration, schema = "min-cost-threshold-0.85"
Actions: Scanned the sorted enumeration for the first assignment with joint_prob >= 0.85.
Outputs: E.optimum85 = {assignment: A=focused, B=focused, C=heavy, D=heavy, total_cost: 5.20, joint_prob: 0.870809}
Evidence: Assignment #65 in sorted order. joint_prob = 0.95 × 0.94 × 0.990 × 0.985 = 0.87080895. All 64 cheaper assignments have joint_prob < 0.85.

---

## step.sensitivity
Status: succeeded
Inputs: E.optimum90, schema = "break-points"
Actions: For each of the 4 probability estimates in the optimum, computed the maximum absolute decrease before joint_prob drops below 0.90 using: delta_max = p_i × (1 - 0.90 / P_joint). Also computed break ratio and break point. Identified Job B (focused, p=0.940) as most sensitive with smallest absolute margin of 0.007742.
Outputs: E.sensitivity = {most_sensitive: Job B (focused, p=0.940), break_margin: 0.007742, break_point: 0.932258, next_feasible: cost=6.70}
Evidence: Margin above threshold = 0.907475 - 0.90 = 0.007475. Job B has the lowest p in the optimum (0.940) and smallest absolute break margin. Second cheapest feasible @ 0.90 costs 6.70 (A=focused, B=heavy, C=heavy, D=heavy, prob=0.921761).

---

## step.write
Status: succeeded
Inputs: E.optimum90, E.enumeration, E.optimum85, E.sensitivity, format = "markdown"
Actions: Wrote solution.md with all 5 required deliverables:
  1. Optimal assignment, total cost, joint probability
  2. Reproducible exhaustive calculation (script reference + verification arithmetic)
  3. Proof of optimality (all 77 cheaper assignments listed with INFEASIBLE status)
  4. Cheapest assignment at threshold 0.85
  5. Sensitivity analysis with numerical break points and margins
Outputs: OUT.solution = solution.md
Evidence: solution.md written with all 5 sections. calculation.py and calculation_output.txt included for reproducibility.

---

## step.verify
Status: succeeded
Inputs: G.task, evidence = OUT.solution
Actions: Verified against all 4 acceptance criteria:
  1. "Every reported assignment is independently reproducible" — calculate.py reproduces all results. Verification: ran `python3 calculate.py` and confirmed output matches solution.md.
  2. "Feasibility uses the product of all four selected success probabilities" — joint_prob = product of 4 probabilities, confirmed in calculate.py and solution.md.
  3. "Optimality is established against all cheaper assignments, not asserted" — All 76 cheaper assignments listed in section 3, each shown INFEASIBLE.
  4. "Sensitivity reasoning includes a numerical break point or margin" — Section 5 includes absolute break margins, break ratios, and break points for all 4 estimates.
Outputs: V.result = {all_acceptance_criteria_passed: true}
Evidence: All 4 acceptance criteria verified. calculation_output.txt contains full reproducible evidence.
