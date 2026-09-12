"""External-driver claim bridge (issue #19).

Adds a ready/claim/submit lifecycle on top of the Wave 8 sequential
external driver (``atlas next`` / ``atlas submit``, issue #18) so an
already-running agent can execute ATLAS invocations with its own tools
while ATLAS maintains state and validates results — the driver process
never holds the event store open beyond one command.

Claim semantics — an additive overlay the coordinator-driven path
ignores (claims live in INVOCATION_CLAIMED events only; the coordinator
and resume treat such invocations as non-terminal and re-executable):

- :meth:`ClaimBridge.ready` renders the next ready invocation's
  :class:`TaskEnvelope` (reusing ``ExternalDriver.next_envelope`` for the
  fresh-start / READY / DISPATCHED bookkeeping) and records an
  INVOCATION_CLAIMED event: fencing claim token (uuid4 hex), claimed_at
  (UTC), envelope digest, optional claimant name and a 1-based claim
  attempt.  A claimed-but-unsubmitted invocation is NOT handed out again
  by a subsequent ready/claim while the claim is fresh.
- :meth:`ClaimBridge.submit` validates the caller's claim token against
  the invocation's open claim (and its freshness) and only then
  delegates to the unchanged ``ExternalDriver.submit_result`` commit path
  (RESULT_RECEIVED -> VALIDATION_PASSED + SUCCEEDED batch, or the atomic
  failure/blocked batch).  Stale or unknown tokens are rejected with
  nothing appended.
- A claim older than ``claim_timeout_seconds`` (default 900) is dead:
  ready/claim re-issues it with a new claim token and attempt+1 — a
  fresh INVOCATION_DISPATCHED is appended (so the envelope's dispatch
  attempt increments and an old envelope's echoed attempt rejects) plus
  the new INVOCATION_CLAIMED — after which the old token rejects.
- A terminal run answers ready/claim with the recorded terminal status
  and appends nothing.

All store invariants are inherited unchanged (gapless seq, atomic
batches, no false completion): the bridge appends through
``EventStore.append``/``append_batch`` and never writes any other event
type.  ``runtime.coordinator`` itself is not modified.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from atlas.envelope import DriverError, ExternalDriver, ResultEnvelope
from atlas.runtime.events import Event, EventType, _Record

__all__ = [
    "DEFAULT_CLAIM_TIMEOUT_SECONDS",
    "ClaimBridge",
    "ClaimInfo",
    "claim_from_event",
]


def _token_fingerprint(token: str) -> str:
    """SHA-256 fingerprint of a claim token (never store the raw token)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

#: Seconds before an unsubmitted claim is considered dead and re-issued.
DEFAULT_CLAIM_TIMEOUT_SECONDS = 900.0


@dataclass(frozen=True)
class ClaimInfo:
    """One recorded claim, parsed from its INVOCATION_CLAIMED event."""

    invocation_id: str
    claim_token: str
    claimed_at: str
    claimant: Optional[str]
    claim_attempt: int
    envelope_digest: str
    seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "claim_token": self.claim_token,
            "claimed_at": self.claimed_at,
            "claimant": self.claimant,
            "claim_attempt": self.claim_attempt,
            "envelope_digest": self.envelope_digest,
            "claim_seq": self.seq,
        }


def claim_from_event(event: Event) -> ClaimInfo:
    """Parse a :class:`ClaimInfo` from an INVOCATION_CLAIMED event."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    return ClaimInfo(
        invocation_id=event.invocation_id,
        claim_token=payload.get("claim_token") or "",
        claimed_at=payload.get("claimed_at") or "",
        claimant=payload.get("claimant"),
        claim_attempt=int(payload.get("claim_attempt") or 0),
        envelope_digest=payload.get("envelope_digest") or "",
        seq=event.seq,
    )


def _check_claim(condition: bool, message: str) -> None:
    if not condition:
        raise DriverError(message)


class ClaimBridge:
    """Ready/claim/submit lifecycle over an :class:`ExternalDriver`.

    ``claim_timeout_seconds`` bounds how long an unsubmitted claim stays
    fresh; ``clock`` is an injectable ``datetime.now(timezone.utc)``
    stand-in for tests (staleness is otherwise evaluated from the
    recorded ``claimed_at`` timestamps alone).
    """

    def __init__(
        self,
        driver: ExternalDriver,
        *,
        claim_timeout_seconds: float = DEFAULT_CLAIM_TIMEOUT_SECONDS,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.driver = driver
        self.claim_timeout_seconds = claim_timeout_seconds
        self._clock = clock or _utcnow

    # -- ready / claim ---------------------------------------------------

    def ready(self, *, claimant: Optional[str] = None) -> dict[str, Any]:
        """Render + claim the next ready invocation.

        Returns one of:

        - ``{"terminal": true, "status": ...}`` when the run is terminal
          (nothing appended);
        - ``{"ready": false, "claim": ...}`` when the next invocation's
          claim is fresh and held by another driver (nothing appended);
        - ``{"ready": true, "claim": ..., "envelope": ...}`` after
          recording the claim (a stale prior claim is re-issued first:
          new dispatch attempt + new token).
        """
        driver = self.driver
        try:
            driver.store.run(driver.run_id)
            events = driver.store.events(driver.run_id)
        except KeyError:
            events = ()
        status = self._terminal_status(events)
        if status is not None:
            return {
                "terminal": True,
                "run_id": driver.run_id,
                "status": status,
            }

        envelope = driver.next_envelope()
        events = driver.store.events(driver.run_id)
        invocation_id = envelope.invocation_id
        claim = self._open_claim(events, invocation_id)
        if claim is not None and self._is_fresh(claim):
            return {
                "ready": False,
                "run_id": driver.run_id,
                "invocation_id": invocation_id,
                "reason": (
                    f"invocation {invocation_id!r} is claimed by another"
                    " driver and the claim is fresh; nothing handed out"
                ),
                "claim": claim.to_dict(),
            }
        max_attempts = self._envelope_max_attempts(envelope)
        if claim is not None and not self._is_fresh(claim):
            if max_attempts is not None and claim.claim_attempt > max_attempts:
                return {
                    "ready": False,
                    "run_id": driver.run_id,
                    "invocation_id": invocation_id,
                    "reason": (
                        f"invocation {invocation_id!r} has reached the"
                        f" contract budget max_attempts ({max_attempts});"
                        " the stale claim will not be re-issued"
                    ),
                    "claim": claim.to_dict(),
                }
        claim, envelope = self._issue_claim(
            envelope, events, claimant=claimant,
            reissue=claim is not None,
            max_attempts=max_attempts,
        )
        return {
            "ready": True,
            "run_id": driver.run_id,
            "invocation_id": envelope.invocation_id,
            "claim": claim.to_dict(),
            "envelope": envelope.to_dict(),
        }

    def _issue_claim(
        self,
        envelope: Any,
        events: tuple,
        *,
        claimant: Optional[str],
        reissue: bool,
        max_attempts: Optional[int] = None,
    ) -> tuple[ClaimInfo, Any]:
        """Record the INVOCATION_CLAIMED event for ``envelope``.

        Returns ``(claim, envelope)``: on a stale re-issue the envelope
        is re-rendered after the fresh INVOCATION_DISPATCHED (the fencing
        contract that makes an old envelope's echoed attempt reject at
        submit) so the handed-out attempt matches the store's dispatch
        count and the recorded envelope digest.
        """
        driver = self.driver
        store = driver.store
        invocation_id = envelope.invocation_id
        if reissue:
            last_dispatch = self._last_dispatch(events, invocation_id)
            store.append(
                driver.run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=last_dispatch.instruction_id,
                invocation_id=invocation_id,
                task_id=last_dispatch.task_id,
                payload=dict(last_dispatch.payload),
            )
            envelope = driver.next_envelope()

        events = store.events(driver.run_id)
        last_dispatch = self._last_dispatch(events, invocation_id)
        claim_token = uuid.uuid4().hex
        claimed_at = self._clock()
        digest = hashlib.sha256(envelope.to_json().encode("utf-8")).hexdigest()
        claim_attempt = len(self._claims(events, invocation_id)) + 1
        record = _Record(
            event_type=EventType.INVOCATION_CLAIMED,
            instruction_id=last_dispatch.instruction_id,
            invocation_id=invocation_id,
            task_id=envelope.task_id,
            attempt=envelope.attempt,
            payload={
                "claim_token": claim_token,
                "claimed_at": claimed_at.isoformat(),
                "claimant": claimant,
                "envelope_digest": digest,
                "claim_attempt": claim_attempt,
            },
            store=store,
        )
        appended = store.append_batch(driver.run_id, [record])
        return claim_from_event(appended[0]), envelope

    # -- submit ------------------------------------------------------------

    def submit(
        self, result: ResultEnvelope, *, claim_token: str
    ) -> dict[str, Any]:
        """Validate the open claim, then commit via ``submit_result``.

        Rejections (unknown run, terminal run, no open claim, token
        mismatch, expired claim) append nothing.
        """
        driver = self.driver
        store = driver.store
        _check_claim(
            isinstance(claim_token, str) and claim_token != "",
            "claim token must be a nonempty string",
        )
        try:
            store.run(driver.run_id)
            events = store.events(driver.run_id)
        except KeyError as exc:
            raise DriverError(f"unknown run: {driver.run_id!r}") from exc
        status = self._terminal_status(events)
        _check_claim(
            status is None,
            f"run {driver.run_id!r} is already terminal"
            f" (status {status!r}); no further results are accepted",
        )
        claim = self._open_claim(events, result.invocation_id)
        _check_claim(
            claim is not None,
            f"no open claim for invocation {result.invocation_id!r} in run"
            f" {driver.run_id!r}; run `atlas claim` first (nothing"
            " appended)",
        )
        assert claim is not None  # narrowed for type checkers
        _check_claim(
            claim.claim_token == claim_token,
            f"claim token mismatch for invocation"
            f" {result.invocation_id!r}: the open claim"
            f" (attempt {claim.claim_attempt}, seq {claim.seq}) was issued"
            " to another token; nothing appended",
        )
        _check_claim(
            self._is_fresh(claim),
            f"claim for invocation {result.invocation_id!r} expired after"
            f" {self.claim_timeout_seconds}s; nothing appended — the"
            " invocation will be re-issued by the next ready",
        )
        return driver.submit_result(result)

    # -- renew -----------------------------------------------------------

    def renew(self, invocation_id: str, claim_token: str) -> dict[str, Any]:
        """Extend the freshness of an open claim by appending a HEARTBEAT.

        Validates the token against the invocation's OPEN claim (wrong or
        expired-foreign token → clean error, NOTHING appended).  On
        success a HEARTBEAT event is appended carrying the invocation id,
        a fingerprint of the claim token (never the raw token), and the
        timestamp — so :meth:`_is_fresh` reads ``max(claimed_at, last
        heartbeat)`` and the claimant's eventual :meth:`submit` succeeds
        even after working longer than ``claim_timeout_seconds``.
        """
        driver = self.driver
        store = driver.store
        _check_claim(
            isinstance(claim_token, str) and claim_token != "",
            "claim token must be a nonempty string",
        )
        try:
            store.run(driver.run_id)
            events = store.events(driver.run_id)
        except KeyError as exc:
            raise DriverError(f"unknown run: {driver.run_id!r}") from exc
        status = self._terminal_status(events)
        _check_claim(
            status is None,
            f"run {driver.run_id!r} is already terminal"
            f" (status {status!r}); no further results are accepted",
        )
        claim = self._open_claim(events, invocation_id)
        _check_claim(
            claim is not None,
            f"no open claim for invocation {invocation_id!r} in run"
            f" {driver.run_id!r}; nothing to renew",
        )
        assert claim is not None  # narrowed for type checkers
        _check_claim(
            claim.claim_token == claim_token,
            f"claim token mismatch for invocation {invocation_id!r}: the"
            f" open claim (attempt {claim.claim_attempt}, seq {claim.seq})"
            " was issued to another token; nothing appended",
        )
        last_dispatch = self._last_dispatch(events, invocation_id)
        ts = self._clock().isoformat()
        record = _Record(
            event_type=EventType.HEARTBEAT,
            instruction_id=last_dispatch.instruction_id,
            invocation_id=invocation_id,
            task_id=last_dispatch.task_id,
            attempt=claim.claim_attempt,
            payload={
                "invocation_id": invocation_id,
                "claim_token_fingerprint": _token_fingerprint(claim_token),
                "ts": ts,
            },
            store=store,
        )
        appended = store.append_batch(driver.run_id, [record])
        heartbeat_event = appended[0]
        return {
            "renewed": True,
            "run_id": driver.run_id,
            "invocation_id": invocation_id,
            "claim_attempt": claim.claim_attempt,
            "heartbeat_seq": heartbeat_event.seq,
            "freshness_ts": ts,
        }

    # -- claim queries -----------------------------------------------------

    def _open_claim(
        self, events: tuple, invocation_id: str
    ) -> Optional[ClaimInfo]:
        """Latest claim for the invocation, unless a submission settled it."""
        claims = self._claims(events, invocation_id)
        if not claims:
            return None
        received = any(
            event.event_type is EventType.RESULT_RECEIVED
            and event.invocation_id == invocation_id
            for event in events
        )
        if received:
            return None
        return claim_from_event(claims[-1])

    def _is_fresh(self, claim: ClaimInfo) -> bool:
        base = self._claim_freshness_base(claim)
        if base is None:
            return False
        return self._clock() < base + timedelta(
            seconds=self.claim_timeout_seconds
        )

    def _claim_freshness_base(
        self, claim: ClaimInfo
    ) -> Optional[datetime]:
        """The effective freshness origin: ``max(claimed_at, last heartbeat)``.

        Reads the last HEARTBEAT for the claim's invocation from the store
        (if any), parses its ``ts`` payload, and returns the later of the
        two timestamps.  Returns ``None`` when ``claimed_at`` is
        unparseable.
        """
        try:
            claimed_at = datetime.fromisoformat(claim.claimed_at)
        except ValueError:
            return None
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        driver = self.driver
        try:
            events = driver.store.events(driver.run_id)
        except Exception:
            return claimed_at
        last_hb = self._last_heartbeat(events, claim.invocation_id)
        if last_hb is not None:
            return last_hb
        return claimed_at

    @staticmethod
    def _last_heartbeat(
        events: tuple, invocation_id: str
    ) -> Optional[datetime]:
        """Most recent HEARTBEAT timestamp for the invocation, or None."""
        latest: Optional[datetime] = None
        for event in events:
            if (
                event.event_type is EventType.HEARTBEAT
                and event.invocation_id == invocation_id
            ):
                payload = event.payload if isinstance(event.payload, dict) else {}
                ts_str = payload.get("ts")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if latest is None or ts > latest:
                    latest = ts
        return latest

    @staticmethod
    def _claims(events: tuple, invocation_id: str) -> list:
        return [
            event
            for event in events
            if event.event_type is EventType.INVOCATION_CLAIMED
            and event.invocation_id == invocation_id
        ]

    @staticmethod
    def _dispatches(events: tuple, invocation_id: str) -> list:
        return [
            event
            for event in events
            if event.event_type is EventType.INVOCATION_DISPATCHED
            and event.invocation_id == invocation_id
        ]

    @classmethod
    def _last_dispatch(cls, events: tuple, invocation_id: str) -> Event:
        dispatches = cls._dispatches(events, invocation_id)
        if not dispatches:
            raise DriverError(
                f"invocation {invocation_id!r} has no DISPATCHED event to"
                " claim against; run `atlas next` first"
            )
        return dispatches[-1]

    @staticmethod
    def _terminal_status(events: tuple) -> Optional[str]:
        status = None
        for event in events:
            if event.event_type is EventType.RUN_FINISHED:
                payload = event.payload if isinstance(event.payload, dict) else {}
                status = payload.get("status", "unknown")
        return status

    @staticmethod
    def _envelope_max_attempts(envelope: Any) -> Optional[int]:
        """Read ``contract.budget.max_attempts`` off a TaskEnvelope.

        Returns ``None`` when the field is absent or unparseable,
        preserving the historical unlimited-reissue behaviour.
        """
        contract = getattr(envelope, "contract", None)
        if not isinstance(contract, dict):
            return None
        budget = contract.get("budget")
        if not isinstance(budget, dict):
            return None
        value = budget.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
