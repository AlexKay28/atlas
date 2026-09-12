"""Delegate engine — runtime-authored child plans (issue #25).

Extracted from ``coordinator.py`` as a mixin so the coordinator class can
compose delegate execution without bloating the main driver.  All
module-level helpers and the ``DelegateEngine`` mixin methods preserve the
exact behavior and signatures from the original coordinator code.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tahoe.runtime.events import EventType, _Record, canonical_json as _canonical_event_json
from tahoe.runtime.tasks import TaskStatus
from tahoe.syntax import ParseError, load_protocol, parse_program, validate_program
from tahoe.syntax.model import (
    Argument, Call, Conditional, Declaration, Invocation, Par, ParBranch,
    Program, Return, Scatter, Gather,
)
from tahoe.state import StateDelta

if TYPE_CHECKING:
    from tahoe.budgets import BudgetGate
    from tahoe.claims import ResourceLedger
    from tahoe.runtime.coordinator import _PlanEntry


# Issue #25: runtime-authored child plans (delegate).
#
# ``delegate`` is a plain registered command executed through the standard
# DO machinery: the worker reply is the AUTHORED child program text, which
# the coordinator validates against the registry, records as a
# CHILD_PLAN_AUTHORED event, and executes as an isolated child run using
# the same child machinery as CALL.  The authored plan's step count is
# bounded (default 6, hard cap 12) and recursion is rejected: the authored
# plan may not contain a delegate command, directly or through any
# transitively called protocol file.
DELEGATE_COMMAND = "delegate"
DELEGATE_DEFAULT_MAX_STEPS = 6
DELEGATE_HARD_MAX_STEPS = 12
# Protocol-call chains are already validated to be acyclic and bounded at
# depth 8 (issue #12); the transitive no-recursion walk uses the same cap
# defensively.
DELEGATE_PROTOCOL_DEPTH_LIMIT = 8


def delegate_plan_name(step_id: str) -> str:
    """The bound program name of a delegate-authored child plan (issue #25).

    ``delegated_<parent_step_id>`` with the step id's dot normalized to an
    underscore (``step.author`` -> ``delegated_step_author``) so the name
    satisfies the canonical ``PROGRAM`` header charset.  The coordinator
    binds this name onto the accepted plan before executing it, making the
    lineage label part of the executed artifact (and of its digest).
    """
    return "delegated_" + step_id.replace(".", "_")


def delegate_plan_digest(step_id: str, plan_text: str) -> str:
    """Digest pinning one authored child plan (issue #25).

    sha256 over the canonical JSON of ``{"name": <bound plan name>,
    "plan_text": <raw authored text>}`` — computed from the step id and
    the raw text alone, so it exists even for plans that later fail to
    parse (the CHILD_PLAN_AUTHORED event records it either way).
    """
    payload = {
        "name": delegate_plan_name(step_id),
        "plan_text": plan_text,
    }
    return hashlib.sha256(
        _canonical_event_json(payload).encode("utf-8")
    ).hexdigest()


def count_plan_steps(program: Program) -> int:
    """The number of executable plan entries an authored plan would create.

    Mirrors :meth:`SequentialCoordinator._build_plan`'s counting: every
    bare or conditional DO invocation, CALL, SCATTER, GATHER and PAR block
    occupies one plan entry.  The delegate step bound (``max_steps``,
    default 6, hard cap 12) applies to this count.
    """
    count = 0
    for statement in program.statements:
        if isinstance(statement, Invocation):
            count += 1
        elif isinstance(statement, Conditional):
            if isinstance(statement.statement, Invocation):
                count += 1
        elif isinstance(statement, (Call, Scatter, Par, Gather)):
            count += 1
    return count


def _iter_invocations_and_calls(program: Program):
    """Yield every ``(invocation, call)`` pair an authored plan can dispatch.

    Walks plain statements plus every nested holder: conditional embedded
    statements, SCATTER bodies, PAR branches (DO or CALL) and GATHER judge
    templates.
    """
    for statement in program.statements:
        yield from _walk_invocation_holder(statement)


def _walk_invocation_holder(statement: object):
    if isinstance(statement, Invocation):
        yield statement, None
    elif isinstance(statement, Conditional):
        if isinstance(statement.statement, Invocation):
            yield statement.statement, None
    elif isinstance(statement, Scatter):
        yield statement.body, None
    elif isinstance(statement, Gather):
        if statement.judge is not None:
            yield statement.judge, None
    elif isinstance(statement, Par):
        for branch in statement.branches:
            if branch.invocation is not None:
                yield branch.invocation, None
            else:
                yield None, branch.call
    elif isinstance(statement, Call):
        yield None, statement


def _extract_plan_text(result: Any) -> str:
    """Normalize a delegate worker reply into the authored plan text.

    The handler contract: the reply IS the plan text (a string) — that is
    what deterministic handlers return.  A model worker parses its strict
    JSON reply into a mapping, so the issue-specified shape
    ``{"plan_text": "..."}`` is accepted too.  Anything else is an
    INVALID_INPUT-class defect.
    """
    if isinstance(result, str) and result.strip():
        return result
    if isinstance(result, Mapping):
        plan_text = result.get("plan_text")
        if isinstance(plan_text, str) and plan_text.strip():
            return plan_text
    raise ValueError(
        "delegate worker reply must be the authored plan text (a"
        ' nonempty string) or a mapping with a nonempty "plan_text"'
        f" string field; got {type(result).__name__}"
    )


class DelegateEngine:
    """Mixin providing delegate (runtime-authored child plan) execution.

    Mixed into :class:`SequentialCoordinator` to keep the delegate
    protocol's three methods — replay, no-recursion validation, and the
    full entry executor — in one self-contained module.
    """

    def _recorded_delegate_plan(self, run_id: str, invocation_id: str):
        """The CHILD_PLAN_AUTHORED event recorded for one delegate step.

        Replay identity (issue #25): the ACCEPTED artifact is the recorded
        one.  A resumed in-flight delegate step reuses the recorded plan
        text instead of re-asking the worker, so a crash can never trigger
        unrecorded replanning; a plan whose authoring crashed BEFORE the
        event committed was never accepted and re-authors (at-least-once).
        """
        for event in self.store.events(run_id):
            if (
                event.event_type is EventType.CHILD_PLAN_AUTHORED
                and event.invocation_id == invocation_id
            ):
                return event
        return None

    def _plan_contains_delegate(self, program: Program, seen: tuple[str, ...] = ()) -> bool:
        """Whether an authored plan reaches a delegate command at any depth.

        Rejects the delegate command in every dispatchable position of the
        authored program (plain steps, conditional DO lines, SCATTER
        bodies, GATHER judges, PAR branches) and transitively through every
        CALLed protocol file.  ``validate_program`` has already guaranteed
        the protocol call graph is acyclic and bounded at depth 8, so the
        walk terminates; ``seen`` only prunes diamond re-visits.
        """
        for invocation, call in _iter_invocations_and_calls(program):
            if invocation is not None and invocation.command == DELEGATE_COMMAND:
                return True
            if call is not None:
                if call.protocol in seen:
                    continue
                protocol = load_protocol(call.protocol, self.protocols_dir)
                if self._plan_contains_delegate(protocol, seen + (call.protocol,)):
                    return True
        return False

    def _execute_delegate_entry(
        self,
        run_id: str,
        idx: int,
        invocation_id: str,
        task_id: str,
        statement: Invocation,
        resolved_kwargs: dict[str, Any],
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        prior_types: set[EventType],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
        branch_claim: str | None,
        fail_invocation: Callable[..., None],
    ) -> dict[str, Any] | None:
        """Execute one delegate plan entry (issue #25).

        The step's worker call returns the AUTHORED child plan text (the
        deterministic handler replies with a fixed sample plan; the model
        worker is prompted for a canonical-grammar child program).  The
        coordinator then:

        1. records the authored artifact as a CHILD_PLAN_AUTHORED event
           (payload ``{step_id, plan_digest, plan_text}``) BEFORE any
           validation or execution — the authored plan is part of history,
           never ephemeral, and stays recorded even when rejected;
        2. validates the plan with ``parse_program`` +
           ``validate_program`` against the worker's registry, and
           enforces the delegation bounds: step count <= ``max_steps``
           (default 6, hard cap 12) and no delegate command anywhere in
           the plan, directly or through called protocols (no recursion).
           Namespaces are already enforced by the parser's typed-reference
           grammar; the executed program's name is bound to
           ``delegated_<parent_step_id>``;
        3. executes the accepted plan as an isolated child run under the
           deterministic id ``<parent_run_id>:<invocation_id>`` — the same
           machinery as a CALL child (own ledger, own namespace seeded
           from the resolved delegate arguments, budget depth gate) — and
           adopts the plan's RETURN refs ONTO the delegate step's targets
           positionally (ref k -> target k); a count mismatch is a
           validation failure.

        Any rejection or non-succeeded child terminal fails the parent
        through the standard atomic path (``fail_invocation``).  Returns
        the terminal failure result dict, or ``None`` when the entry
        committed successfully and the plan loop should continue.
        """

        def fail_delegate(
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            fail_invocation(
                idx, statement.step_id, invocation_id, task_id, error,
                validation=validation,
            )
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        def plan_defect(
            kind: str, detail: str
        ) -> dict[str, Any]:
            return fail_delegate(
                f"authored child plan rejected ({kind}): {detail}",
                validation={
                    "step_id": statement.step_id,
                    "plan_digest": plan_digest,
                    "failure_kind": kind,
                    "detail": detail,
                },
            )

        # -- the max_steps bound --------------------------------------
        raw_max = resolved_kwargs.get("max_steps", DELEGATE_DEFAULT_MAX_STEPS)
        if (
            isinstance(raw_max, bool)
            or not isinstance(raw_max, int)
            or raw_max < 1
        ):
            return fail_delegate(
                f"delegate requires an integer max_steps >= 1, got {raw_max!r}",
                validation={
                    "step_id": statement.step_id,
                    "failure_kind": "invalid_input",
                    "detail": f"max_steps={raw_max!r}",
                },
            )
        max_steps = min(int(raw_max), DELEGATE_HARD_MAX_STEPS)

        # -- the authored plan text (reused verbatim on resume) --------
        recorded = self._recorded_delegate_plan(run_id, invocation_id)
        if recorded is not None:
            payload = recorded.payload if isinstance(recorded.payload, dict) else {}
            plan_text = payload.get("plan_text")
            plan_digest = payload.get("plan_digest")
            if not isinstance(plan_text, str) or not isinstance(plan_digest, str):
                return fail_delegate(
                    "recorded CHILD_PLAN_AUTHORED event for this delegate"
                    " step carries no usable plan text/digest; cannot"
                    " replay the accepted artifact"
                )
        else:
            try:
                reply = self._execute_worker_call(
                    DELEGATE_COMMAND, resolved_kwargs, gate
                )
            except Exception as exc:
                return fail_delegate(str(exc))
            try:
                plan_text = _extract_plan_text(reply)
            except ValueError as exc:
                return fail_delegate(
                    str(exc),
                    validation={
                        "step_id": statement.step_id,
                        "failure_kind": "invalid_input",
                        "detail": str(exc),
                    },
                )
            plan_digest = delegate_plan_digest(statement.step_id, plan_text)
            if EventType.CHILD_PLAN_AUTHORED not in prior_types:
                self.store.append(
                    run_id,
                    EventType.CHILD_PLAN_AUTHORED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "step_id": statement.step_id,
                        "plan_digest": plan_digest,
                        "plan_text": plan_text,
                    },
                )

        # -- validation: parse, registry, bounds -----------------------
        try:
            authored = parse_program(plan_text)
        except ParseError as exc:
            return plan_defect("formalization", f"plan failed to parse: {exc}")
        try:
            validate_program(
                authored,
                known_commands=self.worker.commands,
                protocols_dir=self.protocols_dir,
            )
        except ParseError as exc:
            return plan_defect("formalization", f"plan is invalid: {exc}")
        try:
            contains_delegate = self._plan_contains_delegate(authored)
        except Exception as exc:
            return plan_defect("formalization", str(exc))
        if contains_delegate:
            return plan_defect(
                "invalid_input",
                "the plan contains a delegate command (directly or through"
                " a called protocol): nested dynamic delegation is"
                " rejected, plans stay bounded",
            )
        plan_steps = count_plan_steps(authored)
        if plan_steps > max_steps:
            return plan_defect(
                "formalization",
                f"the plan has {plan_steps} steps, exceeding the delegate"
                f" bound of {max_steps} (default"
                f" {DELEGATE_DEFAULT_MAX_STEPS}, hard cap"
                f" {DELEGATE_HARD_MAX_STEPS})",
            )

        # -- sealed-like binding and isolated child execution ----------
        bound = dataclasses.replace(
            authored, name=delegate_plan_name(statement.step_id)
        )
        child_run_id = f"{run_id}:{invocation_id}"
        if gate is not None and gate.depth_exceeded(child_run_id):
            return fail_delegate(
                f"child run {child_run_id} depth"
                f" {gate.depth_of(child_run_id)} exceeds budget"
                f" max_child_depth {gate.budget.max_child_depth}"
            )
        child_values = self._bind_child_inputs(bound, resolved_kwargs)
        try:
            child_result = self._execute_program_child(
                bound,
                child_run_id,
                run_id,
                f"delegate:{statement.step_id}",
                child_values,
                gate,
                claims=claims,
                branch_workspace=branch_root,
                branch_claim=branch_claim,
            )
        except Exception as exc:
            return fail_delegate(str(exc))
        child_status = child_result.get("status", "unknown")
        if child_status != "succeeded":
            child_error = child_result.get("error")
            error = (
                f"child run {child_run_id} for delegate"
                f" {statement.step_id} finished with status"
                f" {child_status!r}; the delegate step cannot adopt its"
                " outputs"
            )
            if child_error:
                error = f"{error}: {child_error}"
            return fail_delegate(error)

        if EventType.RESULT_RECEIVED not in prior_types:
            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "child_run_id": child_run_id,
                    "plan_digest": plan_digest,
                    "plan_steps": plan_steps,
                    "status": child_status,
                },
            )

        # -- positional adoption: authored RETURN ref k -> target k ----
        return_statement = next(
            (
                item
                for item in bound.statements
                if isinstance(item, Return)
            ),
            None,
        )
        if return_statement is None:
            return plan_defect(
                "formalization",
                "the plan has no RETURN statement; the delegate step"
                " cannot adopt its outputs",
            )
        return_refs = return_statement.refs
        if len(return_refs) != len(statement.targets):
            return plan_defect(
                "formalization",
                "the plan's RETURN refs ("
                f"{', '.join(return_refs)}) do not map one-to-one onto the"
                f" delegate step's targets ({', '.join(statement.targets)})",
            )
        child_committed: dict[str, Any] = dict(
            child_result.get("child_values") or {}
        )
        self._apply_committed_deltas(
            child_committed, self.store.events(child_run_id)
        )
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target, ref in zip(statement.targets, return_refs):
            if ref not in child_committed:
                return fail_delegate(
                    f"child run {child_run_id} did not commit authored"
                    f" RETURN reference {ref}"
                )
            adopted_nodes.append({"id": target, "value": child_committed[ref]})
            adopted_map[target] = ref
        target_values: dict[str, Any] = {
            node["id"]: node["value"] for node in adopted_nodes
        }

        if statement.done is not None:
            from tahoe.runtime.coordinator import evaluate_done_predicate

            passed, detail = evaluate_done_predicate(
                statement.done, target_values
            )
            if not passed:
                return fail_delegate(
                    f"DONE predicate failed for {statement.step_id}: {detail}",
                    validation={
                        "step_id": statement.step_id,
                        "plan_digest": plan_digest,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    },
                )

        if crash_hook is not None:
            # Issue #25: crash window after the child is terminal but
            # before the parent adopts — resume reuses the recorded plan,
            # finds the terminal child, and adopts without re-executing.
            crash_hook(idx)

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=statement.step_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        for node in adopted_nodes:
            values[node["id"]] = node["value"]

        delta = StateDelta(add_nodes=tuple(adopted_nodes))
        expected_sv = self.store._current_state_version(run_id)

        # batch: CHILD_ADOPTED + SUCCEEDED + invocation_recorded
        # + task_completed — one atomic append, exactly like a CALL
        # adoption (the store's duplicate-SUCCEEDED guard makes a
        # re-adoption of the same delegate invocation impossible).
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.CHILD_ADOPTED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "child_run_id": child_run_id,
                    "adopted": adopted_map,
                    "child_status": child_status,
                    "plan_digest": plan_digest,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={"delta": delta},
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_completed", "id": task_id,
                    "evidence": (
                        f"delegate {statement.step_id} ({child_run_id})"
                        f" -> {list(statement.targets)}"
                    ),
                },
                store=self.store,
            ),
        ])
        return None
