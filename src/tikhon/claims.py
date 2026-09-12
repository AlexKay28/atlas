"""In-process exclusive resource claims (issue #23).

A :class:`ResourceLedger` records which owner currently holds each named
resource and hands out exclusive holds: ``claim`` succeeds only when the
resource is free, ``release`` frees a hold the same owner placed.  The
ledger is purely in-memory and thread-safe (one lock over a dict) and is
run-scoped by construction: the coordinator mints one ledger per root
``execute`` call and threads it through the run's whole execution tree,
so separate runs never see each other's holds while every branch, merge
step and child run inside one tree coordinates through the same ledger.

Grammar-adjacent wiring (no new syntax this wave) lives in the
coordinator:

- an effectful dispatch inside a branch (PAR branch or scatter
  candidate) claims ``workspace:<branch identity>`` for the handler's
  duration, documenting that the branch workspace subdirectory belongs
  to that branch alone;
- the explicit artifact merge claims ``merge:<run_id>`` while it
  integrates branch-produced artifacts, so merges serialize by contract
  even when two joins could otherwise race;
- the dispatch's ``INVOCATION_DISPATCHED`` payload is annotated with the
  held claim names (``"resource_claims": [...]``) — no new event types.

Claims coordinate; they do not roll back.  An unreleased hold (a crash
between claim and release) dies with the process, which is the correct
scope for in-process exclusivity.

(Note recorded during this session: an early dogfood execution of the
sealed program ran its ``edit`` step with no declared workspace root, so
the handler wrote relative to the repository root and clobbered this very
file — restored by hand.  Exactly the failure mode branch workspaces
exist to prevent.)
"""

from __future__ import annotations

import threading

__all__ = ["ResourceLedger"]


class ResourceLedger:
    """Exclusive, in-process, thread-safe resource-claim ledger (issue #23).

    ``claim(resource, owner)`` returns ``True`` and records the hold when
    the resource is currently free, and ``False`` otherwise — including
    when the same owner already holds it (a hold is exclusive; the holder
    must release before claiming again).  ``release(resource, owner)``
    removes a hold only when ``owner`` matches the current holder and
    reports whether it did.  ``holder(resource)`` exposes the current
    holder for diagnostics and failure messages.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._holds: dict[str, str] = {}

    def claim(self, resource: str, owner: str) -> bool:
        """Acquire an exclusive hold on ``resource`` for ``owner``."""
        if not isinstance(resource, str) or not resource:
            raise ValueError("resource must be a nonempty string")
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a nonempty string")
        with self._lock:
            if resource in self._holds:
                return False
            self._holds[resource] = owner
            return True

    def release(self, resource: str, owner: str) -> bool:
        """Free ``resource`` when ``owner`` is its current holder."""
        if not isinstance(resource, str) or not resource:
            raise ValueError("resource must be a nonempty string")
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a nonempty string")
        with self._lock:
            if self._holds.get(resource) == owner:
                del self._holds[resource]
                return True
            return False

    def holder(self, resource: str) -> str | None:
        """The current holder of ``resource``, or ``None`` when free."""
        if not isinstance(resource, str) or not resource:
            raise ValueError("resource must be a nonempty string")
        with self._lock:
            return self._holds.get(resource)
