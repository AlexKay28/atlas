"""Replay-based run verification for the TAHOE runtime (issue #14).

``audit_run`` re-derives every invariant a trusted run must satisfy from
the event store alone and reports each violation together with the
offending event sequence numbers, per docs/spec/03-runtime-and-events.md:

1. gapless per-run sequence numbers (``seq`` is exactly ``0..n-1``);
2. event truthfulness: no VALIDATION_PASSED for an invocation that
   receives FAILED (in either order), no SUCCEEDED after FAILED for the
   same invocation, at most one RUN_FINISHED, and RUN_FINISHED status
   consistent with the preceding terminal events (succeeded requires no
   preceding FAILED; a 'failed' status requires one);
3. ledger invariants on a terminal run (RUN_FINISHED exists): no task
   left PENDING or IN_PROGRESS, every COMPLETED task carries nonempty
   evidence, and every invocation-bound event carries nonempty task_id
   and instruction_id;
4. state projection determinism: projecting the run's events twice
   yields identical state;
5. payload integrity (issue #39): every event's ``payload_ref`` (sha256
   of canonical JSON) must match the stored payload — a mutated row
   under a fixed ref is flagged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from tahoe.runtime.events import Event, EventStore, EventType, canonical_json

__all__ = ["AuditFinding", "AuditReport", "audit_run"]


_INVOCATION_BOUND_TYPES = frozenset({
    EventType.INVOCATION_READY,
    EventType.INVOCATION_DISPATCHED,
    EventType.HEARTBEAT,
    EventType.RESULT_RECEIVED,
    EventType.VALIDATION_PASSED,
    EventType.VALIDATION_FAILED,
    EventType.SUCCEEDED,
    EventType.FAILED,
    EventType.TIMED_OUT,
    EventType.RETRYING,
    EventType.LATE_RESULT,
    EventType.CANCELLED,
    EventType.BLOCKED,
    EventType.UNBLOCKED,
})

_TASK_STATUS_KINDS = {
    "task_created": "pending",
    "task_started": "in_progress",
    "task_completed": "completed",
    "task_cancelled": "cancelled",
}

_UNSETTLED_STATUSES = frozenset({"pending", "in_progress"})


@dataclass(frozen=True)
class AuditFinding:
    """One invariant violation, with the offending event sequence numbers."""

    code: str
    message: str
    seqs: tuple[int, ...] = ()


@dataclass(frozen=True)
class AuditReport:
    """Result of auditing one persisted run."""

    run_id: str
    ok: bool
    findings: tuple[AuditFinding, ...] = ()
    event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict form of the report."""
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "event_count": self.event_count,
            "findings": [
                {"code": finding.code, "message": finding.message,
                 "seqs": list(finding.seqs)}
                for finding in self.findings
            ],
        }


def audit_run(store: EventStore, run_id: str) -> AuditReport:
    """Audit one persisted run from its event history alone.

    Raises :class:`KeyError` when ``run_id`` does not exist in the store.
    """
    store.run(run_id)
    events = store.events(run_id)
    run_finished = next(
        (ev for ev in events if ev.event_type is EventType.RUN_FINISHED),
        None,
    )

    findings = [
        *_check_gapless(events),
        *_check_truthfulness(events),
        *_check_invocation_ids(events),
        *_check_ledger(events, run_finished),
        *_check_payload_integrity(events),
        *_check_projection_determinism(store, run_id, events),
        *_check_reformulation_invariants(events),
    ]
    return AuditReport(
        run_id=run_id,
        ok=not findings,
        findings=tuple(findings),
        event_count=len(events),
    )


def _check_gapless(events: tuple[Event, ...]) -> list[AuditFinding]:
    misplaced = [
        ev.seq for index, ev in enumerate(events) if ev.seq != index
    ]
    if not misplaced:
        return []
    return [AuditFinding(
        code="gapless_sequence",
        message=(
            "sequence numbers are not gapless from 0: events at seq"
            f" {sorted(misplaced)} break the 0..n-1 order"
        ),
        seqs=tuple(sorted(misplaced)),
    )]


def _check_truthfulness(events: tuple[Event, ...]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    by_invocation: dict[str, list[Event]] = {}
    run_finished: list[Event] = []
    for ev in events:
        if ev.invocation_id:
            by_invocation.setdefault(ev.invocation_id, []).append(ev)
        if ev.event_type is EventType.RUN_FINISHED:
            run_finished.append(ev)

    for invocation_id in sorted(by_invocation):
        evs = by_invocation[invocation_id]
        failed = [ev.seq for ev in evs if ev.event_type is EventType.FAILED]
        passed = [
            ev.seq for ev in evs
            if ev.event_type is EventType.VALIDATION_PASSED
        ]
        succeeded = [ev.seq for ev in evs if ev.event_type is EventType.SUCCEEDED]

        for passed_seq in passed:
            later_failed = sorted(
                failed_seq for failed_seq in failed if failed_seq > passed_seq
            )
            if later_failed:
                findings.append(AuditFinding(
                    code="validation_passed_before_failed",
                    message=(
                        f"invocation {invocation_id!r} has VALIDATION_PASSED"
                        f" at seq {passed_seq} but FAILED at seq {later_failed}"
                    ),
                    seqs=tuple([passed_seq, *later_failed]),
                ))
            earlier_failed = sorted(
                failed_seq for failed_seq in failed if failed_seq < passed_seq
            )
            if earlier_failed:
                findings.append(AuditFinding(
                    code="validation_passed_after_failed",
                    message=(
                        f"invocation {invocation_id!r} already FAILED at seq"
                        f" {earlier_failed} but received VALIDATION_PASSED"
                        f" at seq {passed_seq}"
                    ),
                    seqs=tuple([*earlier_failed, passed_seq]),
                ))
        for succeeded_seq in succeeded:
            earlier_failed = sorted(
                failed_seq for failed_seq in failed if failed_seq < succeeded_seq
            )
            if earlier_failed:
                findings.append(AuditFinding(
                    code="succeeded_after_failed",
                    message=(
                        f"invocation {invocation_id!r} has SUCCEEDED at seq"
                        f" {succeeded_seq} after FAILED at seq {earlier_failed}"
                    ),
                    seqs=tuple([*earlier_failed, succeeded_seq]),
                ))

    if len(run_finished) > 1:
        findings.append(AuditFinding(
            code="multiple_run_finished",
            message=f"run has {len(run_finished)} RUN_FINISHED events",
            seqs=tuple(ev.seq for ev in run_finished),
        ))

    for ev in run_finished:
        status = ev.payload.get("status") if isinstance(ev.payload, dict) else None
        failed_before = sorted(
            other.seq for other in events
            if other.event_type is EventType.FAILED and other.seq < ev.seq
        )
        if status == "succeeded" and failed_before:
            findings.append(AuditFinding(
                code="run_finished_status_mismatch",
                message=(
                    f"RUN_FINISHED at seq {ev.seq} claims status 'succeeded'"
                    f" but FAILED events precede it at seq {failed_before}"
                ),
                seqs=tuple([*failed_before, ev.seq]),
            ))
        elif status == "failed" and not failed_before:
            findings.append(AuditFinding(
                code="run_finished_status_mismatch",
                message=(
                    f"RUN_FINISHED at seq {ev.seq} claims status 'failed'"
                    " but no FAILED event precedes it"
                ),
                seqs=(ev.seq,),
            ))
    return findings


def _check_invocation_ids(events: tuple[Event, ...]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for ev in events:
        if ev.event_type not in _INVOCATION_BOUND_TYPES:
            continue
        # Issue #24 false-positive fix: a PAR barrier's entry-terminal
        # SUCCEEDED commits the branches' adopted targets, and a
        # join-level PAR failure (the artifact merge) carries the entry's
        # positional invocation id — both under the "par" payload marker.
        # A PAR block owns no ledger task of its own (the ledger carries
        # one task per branch instead), so these events carry no task_id
        # by design; the instruction_id requirement still applies.
        if (
            ev.event_type in (EventType.SUCCEEDED, EventType.FAILED)
            and not ev.task_id
            and isinstance(ev.payload, dict)
            and "par" in ev.payload
        ):
            if not ev.instruction_id:
                findings.append(AuditFinding(
                    code="invocation_event_missing_ids",
                    message=(
                        f"{ev.event_type.value} at seq {ev.seq} is missing"
                        " nonempty instruction_id"
                    ),
                    seqs=(ev.seq,),
                ))
            continue
        missing = [
            name for name, value in (("task_id", ev.task_id),
                                     ("instruction_id", ev.instruction_id))
            if not value
        ]
        if missing:
            findings.append(AuditFinding(
                code="invocation_event_missing_ids",
                message=(
                    f"{ev.event_type.value} at seq {ev.seq} is missing"
                    f" nonempty {', '.join(missing)}"
                ),
                seqs=(ev.seq,),
            ))
    return findings


def _project_tasks(events: tuple[Event, ...]) -> dict[str, dict[str, Any]]:
    """Project the task ledger from TASK_UPDATED events, keeping the seq
    of the last status-setting event per task."""
    tasks: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.event_type is not EventType.TASK_UPDATED:
            continue
        payload = ev.payload
        if not isinstance(payload, dict):
            continue
        status = _TASK_STATUS_KINDS.get(payload.get("kind"))
        if status is None:
            continue
        task_id = payload.get("id") or ev.task_id
        record = tasks.setdefault(
            task_id, {"status": "pending", "seq": ev.seq, "evidence": []},
        )
        record["status"] = status
        record["seq"] = ev.seq
        if payload.get("kind") == "task_completed":
            evidence = payload.get("evidence")
            if isinstance(evidence, str) and evidence.strip():
                record["evidence"].append(evidence)
    return tasks


def _check_ledger(
    events: tuple[Event, ...],
    run_finished: Event | None,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    tasks = _project_tasks(events)
    if run_finished is None:
        return findings

    for task_id in sorted(tasks):
        record = tasks[task_id]
        if record["status"] in _UNSETTLED_STATUSES:
            findings.append(AuditFinding(
                code="unsettled_task_on_terminal_run",
                message=(
                    f"terminal run leaves task {task_id!r} in status"
                    f" {record['status']!r} (last ledger event at seq"
                    f" {record['seq']})"
                ),
                seqs=(record["seq"], run_finished.seq),
            ))
        elif record["status"] == "completed" and not record["evidence"]:
            findings.append(AuditFinding(
                code="completed_task_missing_evidence",
                message=(
                    f"task {task_id!r} is COMPLETED (task_completed at seq"
                    f" {record['seq']}) but its completion carries no"
                    " nonempty evidence"
                ),
                seqs=(record["seq"],),
            ))
    return findings


def _check_reformulation_invariants(
    events: tuple[Event, ...],
) -> list[AuditFinding]:
    """Verify reformulation invariants (issue #80).

    - Max 3 reformulations per run.
    - Each PLAN_REFORMULATED event carries the required payload fields:
      trigger_step, diagnosis_ref, revised_refs, new_plan_digest,
      preserved_refs.
    - The reformulation count is sequential (1, 2, 3, ...).
    - Preserved refs include goal-level (G.*) refs from pre-reformulation.
    """
    findings: list[AuditFinding] = []
    reformulation_events = [
        ev for ev in events
        if ev.event_type is EventType.PLAN_REFORMULATED
    ]
    max_reformulations = 3
    if len(reformulation_events) > max_reformulations:
        findings.append(AuditFinding(
            code="max_reformulations_exceeded",
            message=(
                f"run has {len(reformulation_events)} PLAN_REFORMULATED"
                f" events, exceeding the maximum of {max_reformulations}"
            ),
            seqs=tuple(ev.seq for ev in reformulation_events),
        ))
    expected_count = 0
    for ev in reformulation_events:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        required_fields = (
            "trigger_step", "diagnosis_ref", "revised_refs",
            "new_plan_digest", "preserved_refs",
        )
        missing = [
            field for field in required_fields
            if field not in payload
        ]
        if missing:
            findings.append(AuditFinding(
                code="reformulation_missing_payload",
                message=(
                    f"PLAN_REFORMULATED at seq {ev.seq} is missing"
                    f" required payload fields: {', '.join(missing)}"
                ),
                seqs=(ev.seq,),
            ))
        expected_count += 1
        actual_count = payload.get("reformulation_count")
        if actual_count != expected_count:
            findings.append(AuditFinding(
                code="reformulation_count_not_sequential",
                message=(
                    f"PLAN_REFORMULATED at seq {ev.seq} has"
                    f" reformulation_count={actual_count!r}, expected"
                    f" {expected_count}"
                ),
                seqs=(ev.seq,),
            ))
        preserved = payload.get("preserved_refs")
        if isinstance(preserved, list):
            has_goal_ref = any(
                isinstance(r, str) and r.startswith("G.")
                for r in preserved
            )
            if not has_goal_ref:
                findings.append(AuditFinding(
                    code="reformulation_no_goal_ref_preserved",
                    message=(
                        f"PLAN_REFORMULATED at seq {ev.seq} preserved_refs"
                        f" contains no G.* goal-level ref — goal-level"
                        f" DONE predicates may be lost"
                    ),
                    seqs=(ev.seq,),
                ))
    return findings


def _check_projection_determinism(
    store: EventStore,
    run_id: str,
    events: tuple[Event, ...],
) -> list[AuditFinding]:
    first = store.project_state(run_id)
    second = store.project_state(run_id)
    if canonical_json(first) == canonical_json(second):
        return []
    return [AuditFinding(
        code="state_projection_nondeterministic",
        message=(
            "projecting the run's events twice produced different state;"
            " replay is not deterministic (all events suspect)"
        ),
        seqs=tuple(ev.seq for ev in events),
    )]


def _check_payload_integrity(events: tuple[Event, ...]) -> list[AuditFinding]:
    """Verify every event's payload_ref matches the stored payload (issue #39).

    payload_ref is the sha256 of the canonical JSON of the payload.  If a
    row's payload was mutated after insertion, the ref will not match.
    """
    findings: list[AuditFinding] = []
    for ev in events:
        if ev.payload_ref is None:
            continue
        payload_json = canonical_json(ev.payload) if ev.payload is not None else None
        expected_ref = (
            hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            if payload_json is not None
            else None
        )
        if expected_ref != ev.payload_ref:
            findings.append(AuditFinding(
                code="payload_digest_mismatch",
                message=(
                    f"event at seq {ev.seq} has payload_ref {ev.payload_ref!r}"
                    f" but the stored payload hashes to {expected_ref!r}"
                    " — payload was mutated after insertion"
                ),
                seqs=(ev.seq,),
            ))
    return findings
