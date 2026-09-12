"""Execution-tree budgets: global concurrency, deadlines, depth (issue #22).

An :class:`ExecutionBudget` is the root-owned scheduler budget shared
across a run's whole execution tree: it caps concurrently active workers
AND simultaneous child-run step executions through one shared semaphore,
sets a global wall-clock deadline for the run, a per-invocation deadline
for each dispatch, and a maximum child-run nesting depth.

The budget object itself is inert configuration; :meth:`SequentialCoordinator.execute`
mints one :class:`BudgetGate` per ``execute`` call — the live runtime
state (semaphore, run start clock) threaded through every drive of that
run tree.  Budgets cap; they never enable: concurrency still requires
``max_workers > 1``, and ``budget=None`` keeps the historical behavior
byte-identical.

Enforcement points (cooperative, at dispatch boundaries):

- global deadline — checked before each dispatch and before a child run
  starts; exceeding it fails the run coherently (``RUN_FINISHED`` failed,
  reason ``"global deadline exceeded"``) and marks in-flight invocations
  FAILED with ``"cancelled: global deadline exceeded"``;
- per-invocation deadline — the threaded frontier waits on futures with
  a timeout, failing an overrunning invocation through the standard
  atomic failure path with error ``"deadline exceeded"``; the
  sequential drive checks after the handler returns (a running handler
  cannot be interrupted — its result is then discarded uncommitted);
- child depth — a CALL whose child run id nests deeper than
  ``max_child_depth`` fails the CALL atomically before dispatch.

Waiting orchestration frames (a parent CALL awaiting its child) hold no
slot: only handler executions and child step executions acquire the
semaphore, so a one-worker budget cannot deadlock a parent waiting on a
child.

Issue #41 extensions:

- ``max_total_tokens`` caps the total tokens spent across all receipt
  metrics in a run; :class:`BudgetGate` accumulates spent tokens and
  reports token exhaustion through the standard ``RUN_FINISHED`` path.
- ``elapsed_offset`` on :class:`BudgetGate` carries pre-crash wall-clock
  time so a resumed run enforces the *remaining* global deadline.
"""

from __future__ import annotations

import dataclasses
import threading
import time

__all__ = [
    "BudgetDeadlineExceeded",
    "BudgetGate",
    "ExecutionBudget",
]


@dataclasses.dataclass(frozen=True)
class ExecutionBudget:
    """Root-owned scheduler budget shared across descendants (issue #22).

    ``max_concurrent_workers`` caps both the parent frontier's worker
    pool and the number of handler/child-step executions active at any
    instant tree-wide (one shared semaphore).  ``global_deadline_seconds``
    bounds the whole run wall-clock; ``per_invocation_deadline_seconds``
    bounds each dispatch; ``max_child_depth`` bounds child-run nesting
    (run-id ``:`` count).  ``None`` deadlines mean unbounded.

    ``max_total_tokens`` (issue #41) caps the total tokens spent across
    all result receipts in a run; ``None`` means unlimited.
    """

    max_concurrent_workers: int = 4
    global_deadline_seconds: float | None = None
    per_invocation_deadline_seconds: float | None = None
    max_child_depth: int = 8
    max_total_tokens: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_concurrent_workers, int)
            or isinstance(self.max_concurrent_workers, bool)
            or self.max_concurrent_workers < 1
        ):
            raise ValueError(
                "max_concurrent_workers must be an integer >= 1, got"
                f" {self.max_concurrent_workers!r}"
            )
        for name in ("global_deadline_seconds", "per_invocation_deadline_seconds"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be a positive number or None, got {value!r}"
                )
        if (
            not isinstance(self.max_child_depth, int)
            or isinstance(self.max_child_depth, bool)
            or self.max_child_depth < 0
        ):
            raise ValueError(
                "max_child_depth must be an integer >= 0, got"
                f" {self.max_child_depth!r}"
            )
        if self.max_total_tokens is not None and (
            not isinstance(self.max_total_tokens, int)
            or isinstance(self.max_total_tokens, bool)
            or self.max_total_tokens < 0
        ):
            raise ValueError(
                "max_total_tokens must be a non-negative integer or None,"
                f" got {self.max_total_tokens!r}"
            )


class BudgetDeadlineExceeded(Exception):
    """A per-invocation deadline was exceeded; message is the recorded error."""


class BudgetGate:
    """Live per-run gate carrying the budget's shared runtime state.

    One gate is minted per root ``execute`` call and threaded through
    every drive (parent frontier, sequential drives, child runs), so
    the semaphore, the global-deadline clock and the depth rule are
    shared across the whole execution tree while separate ``execute``
    calls stay independent.

    ``elapsed_offset`` (issue #41) shifts the wall-clock start backwards
    by the given number of seconds so a resumed run enforces the
    *remaining* global deadline using pre-crash elapsed time.  The
    coordinator derives it from the run's first event timestamp.

    ``spent_tokens`` (issue #41) accumulates token counts from result
    receipts; when it exceeds ``budget.max_total_tokens`` the run fails
    with ``RUN_FINISHED`` reason ``"token budget exceeded"``.
    """

    def __init__(
        self,
        budget: ExecutionBudget,
        *,
        elapsed_offset: float = 0.0,
    ):
        if not isinstance(budget, ExecutionBudget):
            raise TypeError(
                f"budget must be an ExecutionBudget, got {type(budget).__name__}"
            )
        self.budget = budget
        self._slots = threading.BoundedSemaphore(max(1, budget.max_concurrent_workers))
        self._started = time.monotonic() - elapsed_offset
        self._spent_tokens = 0
        self._lock = threading.Lock()

    # -- concurrency slots --------------------------------------------

    def acquire_slot(self) -> None:
        """Hold one execution slot for the duration of a handler call."""
        self._slots.acquire()

    def release_slot(self) -> None:
        self._slots.release()

    # -- deadlines -------------------------------------------------------

    def global_expired(self) -> bool:
        """Whether the run's global wall-clock deadline has passed."""
        deadline = self.budget.global_deadline_seconds
        return deadline is not None and (
            time.monotonic() - self._started
        ) >= deadline

    def global_remaining(self) -> float | None:
        """Seconds left on the global deadline; ``None`` when unbounded."""
        deadline = self.budget.global_deadline_seconds
        if deadline is None:
            return None
        return max(0.0, deadline - (time.monotonic() - self._started))

    # -- token accumulation (issue #41) ----------------------------------

    def add_tokens(self, count: int) -> None:
        """Accumulate spent tokens from a result receipt."""
        with self._lock:
            self._spent_tokens += count

    @property
    def spent_tokens(self) -> int:
        with self._lock:
            return self._spent_tokens

    def token_cap_exceeded(self) -> bool:
        """Whether the accumulated token spend has exceeded the cap."""
        cap = self.budget.max_total_tokens
        if cap is None:
            return False
        with self._lock:
            return self._spent_tokens > cap

    # -- child depth -----------------------------------------------------

    @staticmethod
    def depth_of(child_run_id: str) -> int:
        """Nesting level of a child run: the ``:`` count of its run id."""
        return child_run_id.count(":")

    def depth_exceeded(self, child_run_id: str) -> bool:
        return self.depth_of(child_run_id) > self.budget.max_child_depth
