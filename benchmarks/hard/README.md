# Hard Reasoning Benchmarks

> Tasks designed to test TAHOE's value: multi-constraint, deep-chain
> reasoning where structured thinking prevents the model from losing track.

## Design principles

1. **Multi-constraint**: 5+ interacting constraints that must all be satisfied
2. **Deep chain**: 5+ dependent reasoning steps where early errors propagate
3. **Context explosion**: enough data that the model can't hold it all in one thought
4. **Verifiable**: binary pass/fail, no subjective grading
5. **Token-heavy**: classic inference should produce 1000+ tokens of meandering

## Tasks

### hard-scheduling: Resource-constrained scheduling
7 tasks, 3 resources, 5 time slots, precedence constraints.
Model must assign tasks to slots without conflicts. Answer: slot assignment.

### hard-routing: Multi-stop route optimization
10 deliveries, 5 vehicles, capacity constraints, time windows.
Model must assign deliveries to vehicles minimizing total distance.

### hard-deduction: Deep logical chain
7 objects, 10+ constraints (some conditional), transitive implications.
Model must determine the full ordering. Answer: position of specific object.

### hard-math: Multi-step word problem
5-step calculation with unit conversions, conditional branches, and
verification. Each step depends on prior results. Answer: final number.

### hard-constraint: Constraint satisfaction
5 variables, 8 constraints (inequality, equality, ordering, conditional).
Model must find the unique assignment. Answer: value of specific variable.
