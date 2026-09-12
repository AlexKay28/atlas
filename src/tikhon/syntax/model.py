"""Syntax model for tikhon programs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Declaration:
    ref: str
    value: object


@dataclass(frozen=True)
class Argument:
    name: str
    value: object
    line: int = 0


@dataclass(frozen=True)
class DonePredicate:
    """Deterministic DONE predicate attached to an invocation.

    ``op`` is one of ``equals`` (``<ref> == <json-literal>``), ``in``
    (``<ref> IN [<json-literal>, ...]``), or ``matched``
    (``matched(<ref>, "<regex>")``); ``ref`` must be one of the owning
    invocation's targets; ``value`` is the JSON literal (or the list of
    JSON literals for ``in``, or the pattern string for ``matched``).
    """

    op: str
    ref: str
    value: object
    line: int = 0


@dataclass(frozen=True)
class Invocation:
    """One sequential step: ``step.<id>: DO <command>(args) -> targets``.

    ``revisions`` and ``retirements`` carry the optional trailing
    correction clause (issue #7): ``REVISE r1, r2 | RETIRE r3`` (either or
    both groups).  Semantics, applied by the coordinator inside the
    step's own SUCCEEDED delta: a REVISE ref — an existing earlier node,
    never the step's own target — is set to the step's single target
    value (REVISE is therefore only valid on single-target steps); a
    RETIRE ref is removed from the projection (history retains it).
    """

    step_id: str
    command: str
    args: tuple[Argument, ...]
    targets: tuple[str, ...]
    done: DonePredicate | None = None
    revisions: tuple[str, ...] = ()
    retirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class Call:
    """Protocol call statement (issue #12): ``CALL protocol.name(...) -> targets``.

    ``protocol`` is the full protocol reference — the required ``protocol.``
    prefix followed by dot-separated ``[a-z][a-z0-9_]*`` segments; the
    segments after the prefix select the protocol file (``protocol.framing``
    loads ``protocols/framing.think``).  ``args`` are named like invocation
    arguments and bind the protocol's INPUT declarations; ``targets`` must
    be a subset of the protocol's RETURN refs.
    """

    protocol: str
    args: tuple[Argument, ...]
    targets: tuple[str, ...]
    line: int = 0


@dataclass(frozen=True)
class Conditional:
    """Single-line deterministic conditional (issue #3): ``IF <expr> <statement>``.

    ``condition`` is the raw condition text between ``IF`` and the embedded
    statement — deterministic comparisons over committed node refs and JSON
    literals (``<ref> == <json>``, ``<ref> != <json>``, ``count(<ref>) <op>
    <int>`` for list-valued refs) combined with left-associative ``AND`` /
    ``OR`` and prefix ``NOT``; no parentheses, no worker calls.  ``statement``
    is the embedded statement object — a :class:`Stop`, a :class:`Return`, or
    a full :class:`Invocation` (``step.<id>: DO ...``).  Block forms (ELSE,
    ELSE IF) are not part of the grammar and are rejected at parse time.
    The coordinator evaluates the condition purely over committed run state
    and executes the embedded statement only when it holds.
    """

    condition: str
    statement: object
    line: int = 0


@dataclass(frozen=True)
class Return:
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Stop:
    kind: str
    ref: str | None = None


@dataclass(frozen=True)
class Program:
    name: str
    version: str
    declarations: tuple[Declaration, ...]
    statements: tuple[object, ...]
