#!/usr/bin/env python3
"""Exhaustive enumeration of all 3^4 = 81 tier assignments for 4 jobs x 3 tiers.

Each job gets exactly one attempt. Outcomes are independent.
Cost is charged once regardless of success. A static policy chooses all tiers
before execution. The joint success probability is the product of the four
selected success probabilities.

We enumerate all 81 assignments, compute total cost and joint probability,
then find:
  1. The minimum-cost assignment with joint probability >= 0.90
  2. The minimum-cost assignment with joint probability >= 0.85
  3. For the 0.90 optimum, sensitivity: for each probability estimate, find
     the break point (decrease amount) at which the optimum changes.
"""

from itertools import product
import json

# Data from the task table
# Job: (small_success, small_cost, focused_success, focused_cost, heavy_success, heavy_cost)
jobs = {
    "A": {"small": (0.82, 0.20), "focused": (0.95, 0.80), "heavy": (0.990, 2.00)},
    "B": {"small": (0.70, 0.20), "focused": (0.94, 0.90), "heavy": (0.995, 2.40)},
    "C": {"small": (0.88, 0.25), "focused": (0.96, 0.75), "heavy": (0.990, 1.80)},
    "D": {"small": (0.75, 0.15), "focused": (0.93, 0.70), "heavy": (0.985, 1.70)},
}

job_names = ["A", "B", "C", "D"]
tiers = ["small", "focused", "heavy"]

# Enumerate all 81 assignments
all_assignments = []
for combo in product(tiers, repeat=4):
    total_cost = 0.0
    joint_prob = 1.0
    for i, job in enumerate(job_names):
        tier = combo[i]
        p, c = jobs[job][tier]
        total_cost += c
        joint_prob *= p
    all_assignments.append({
        "assignment": dict(zip(job_names, combo)),
        "total_cost": total_cost,
        "joint_prob": joint_prob,
    })

# Sort by cost ascending
all_assignments.sort(key=lambda x: x["total_cost"])

# Find minimum cost with joint_prob >= 0.90
optimum90 = None
for a in all_assignments:
    if a["joint_prob"] >= 0.90:
        optimum90 = a
        break

# Find minimum cost with joint_prob >= 0.85
optimum85 = None
for a in all_assignments:
    if a["joint_prob"] >= 0.85:
        optimum85 = a
        break

# Print full enumeration (for reproducibility)
print("=== FULL ENUMERATION (81 assignments, sorted by cost) ===")
print(f"{'#':>3} {'A':>8} {'B':>8} {'C':>8} {'D':>8} {'cost':>8} {'joint_p':>12} {'feasible@0.90':>14} {'feasible@0.85':>14}")
for i, a in enumerate(all_assignments):
    print(f"{i+1:3d} "
          f"{a['assignment']['A']:>8} {a['assignment']['B']:>8} "
          f"{a['assignment']['C']:>8} {a['assignment']['D']:>8} "
          f"{a['total_cost']:8.2f} {a['joint_prob']:12.6f} "
          f"{'YES' if a['joint_prob'] >= 0.90 else 'no':>14} "
          f"{'YES' if a['joint_prob'] >= 0.85 else 'no':>14}")

print()
print("=== OPTIMUM @ 0.90 ===")
print(json.dumps(optimum90, indent=2))

print()
print("=== OPTIMUM @ 0.85 ===")
print(json.dumps(optimum85, indent=2))

# Optimality proof: show all cheaper assignments than optimum90 and their joint probs
print()
print("=== OPTIMALITY PROOF @ 0.90: all cheaper assignments ===")
opt_cost = optimum90["total_cost"]
for a in all_assignments:
    if a["total_cost"] < opt_cost:
        print(f"  cost={a['total_cost']:.2f} prob={a['joint_prob']:.6f} "
              f"{'FEASIBLE' if a['joint_prob'] >= 0.90 else 'INFEASIBLE'} "
              f"assignment={a['assignment']}")

# Also check assignments with equal cost
print()
print("=== Equal-cost assignments to optimum90 ===")
for a in all_assignments:
    if abs(a["total_cost"] - opt_cost) < 1e-12:
        print(f"  cost={a['total_cost']:.2f} prob={a['joint_prob']:.6f} "
              f"assignment={a['assignment']}")

# Sensitivity analysis
# For the 0.90 optimum, for each of the 4 selected probability estimates,
# find the maximum decrease delta such that the optimum remains feasible
# (joint prob >= 0.90), and find the break point where a cheaper assignment
# becomes the new optimum.
print()
print("=== SENSITIVITY ANALYSIS ===")
opt_assignment = optimum90["assignment"]
opt_cost = optimum90["total_cost"]
opt_prob = optimum90["joint_prob"]

# Current margin above threshold
margin = opt_prob - 0.90
print(f"Current optimum joint prob = {opt_prob:.6f}, margin above 0.90 = {margin:.6f}")

# For each job in the optimum, find which probability estimate we have
for job in job_names:
    tier = opt_assignment[job]
    p_current = jobs[job][tier][0]
    
    # The joint prob is product of 4 probs. If we decrease p_current by delta,
    # new joint = opt_prob * (1 - delta / p_current)
    # We need new joint >= 0.90
    # opt_prob * (1 - delta / p_current) >= 0.90
    # 1 - delta / p_current >= 0.90 / opt_prob
    # delta / p_current <= 1 - 0.90 / opt_prob
    # delta <= p_current * (1 - 0.90 / opt_prob)
    
    delta_max = p_current * (1 - 0.90 / opt_prob)
    break_ratio = delta_max / p_current
    
    print(f"  Job {job} (tier={tier}, p={p_current:.3f}): "
          f"max decrease = {delta_max:.6f} (absolute), "
          f"break ratio = {break_ratio:.6f} ({break_ratio*100:.2f}%), "
          f"break point p = {p_current - delta_max:.6f}")

# Also: for each probability in the optimum, what decrease would make the
# optimum's joint prob drop below 0.90 AND a different (cheaper) assignment
# becomes the new optimum? This is the key question.
print()
print("=== SENSITIVITY: which single estimate decrease most likely changes optimum? ===")

# For each probability estimate in the optimum assignment, compute:
# 1. The margin (how much it can decrease before joint < 0.90)
# 2. The nearest competitor: cheapest assignment that would become optimal
#    if this prob decreases

# The probability with the smallest margin is the most sensitive
margins = {}
for job in job_names:
    tier = opt_assignment[job]
    p_current = jobs[job][tier][0]
    delta_max = p_current * (1 - 0.90 / opt_prob)
    margins[job] = (tier, p_current, delta_max, delta_max / p_current)

# Sort by margin (smallest absolute decrease first = most sensitive)
sorted_margins = sorted(margins.items(), key=lambda x: x[1][2])
print("Sorted by absolute break margin (smallest = most sensitive):")
for job, (tier, p, delta, ratio) in sorted_margins:
    print(f"  Job {job} (tier={tier}, p={p:.3f}): "
          f"break at delta={delta:.6f} ({ratio*100:.2f}%), "
          f"break point p={p - delta:.6f}")

most_sensitive = sorted_margins[0]
print(f"\nMost sensitive: Job {most_sensitive[0]} (tier={most_sensitive[1][0]}, "
      f"p={most_sensitive[1][1]:.3f}), break margin = {most_sensitive[1][2]:.6f}")

# Now also check: what happens to the second-best feasible assignment?
# Find the second cheapest feasible assignment
feasible_90 = [a for a in all_assignments if a["joint_prob"] >= 0.90]
feasible_90.sort(key=lambda x: x["total_cost"])
if len(feasible_90) >= 2:
    second = feasible_90[1]
    print(f"\nSecond cheapest feasible @ 0.90: cost={second['total_cost']:.2f}, "
          f"prob={second['joint_prob']:.6f}, assignment={second['assignment']}")
    print(f"Cost difference from optimum: {second['total_cost'] - opt_cost:.2f}")
