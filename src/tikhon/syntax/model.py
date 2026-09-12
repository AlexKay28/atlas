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
class Scatter:
    """Bounded fan-out block (issue #4).

    ``SCATTER <item_ref> IN <collection_ref> MAX <max_count>`` followed by
    exactly one indented per-candidate body step.  ``item_ref`` is a fresh
    typed reference bound per candidate inside the body step only (the loop
    variable; it never becomes a committed node and is not visible after
    the block).  ``collection_ref`` must name a committed node whose
    runtime value is a list; ``max_count`` bounds the fan-out — a runtime
    list longer than ``max_count`` fails the run, a shorter one iterates
    its actual length.  ``body`` is the single ``Invocation`` executed once
    per candidate with the item ref bound to that candidate's collection
    element; the body's targets are candidate-scoped names committed under
    the gather alias (never the raw target names).
    """

    item_ref: str
    collection_ref: str
    max_count: int
    body: Invocation
    line: int = 0


@dataclass(frozen=True)
class Gather:
    """Explicit join (issue #4): ``GATHER <step-id> AS <alias> USING <mode>``.

    Must directly follow its ``Scatter`` block and name that block's body
    step id.  ``mode`` is the canonical join rule — ``all`` (every
    candidate must succeed; alias = list of candidate values in candidate
    order), ``any`` (first candidate-order success wins; remaining
    candidates are cancelled and recorded as losers), or ``ranked`` (an
    explicit judge invocation scores each candidate; max score wins, ties
    break to the lowest candidate index).  The issue body's ``first`` and
    ``best`` spellings are accepted aliases for ``any`` and ``ranked``
    respectively and are normalized into ``mode`` at parse time, so both
    spellings parse and seal identically.  ``judge`` is the judge step's
    ``Invocation`` (required exactly when ``mode`` is ``ranked``); it is a
    template executed once per candidate with the item ref and the body's
    target refs bound to that candidate's values, and its result provides
    the score — its targets are never committed as nodes.
    """

    body_step_id: str
    alias_ref: str
    mode: str
    judge: Invocation | None = None
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
