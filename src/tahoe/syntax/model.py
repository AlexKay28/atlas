"""Syntax model for TAHOE programs."""

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
    """Deterministic conditional (issue #3, issue #83): ``IF <expr> ...``.

    Two forms:

    * Single-line: ``IF <expr> <statement>`` — the embedded ``statement`` is
      a :class:`Stop`, a :class:`Return`, or a full :class:`Invocation`.
    * Block form with optional ELSE (issue #83):

      .. code-block:: text

         IF <cond>
           <statement>
           ...
         ELSE
           <statement>
           ...

    In the block form ``statement`` holds the first branch's embedded
    statement and ``else_branch`` holds the ELSE body as a tuple of
    statements (or ``None`` when there is no ELSE).  The single-line form
    always has ``else_branch = None``.

    ``condition`` is the raw condition text — deterministic comparisons
    over committed node refs and JSON literals combined with
    left-associative ``AND`` / ``OR`` and prefix ``NOT``.  The coordinator
    evaluates the condition purely over committed run state and executes
    the embedded statement(s) only when it holds.
    """

    condition: str
    statement: object
    line: int = 0
    else_branch: tuple[object, ...] | None = None
    if_branch_extra: tuple[object, ...] = ()


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
class ParBranch:
    """One heterogeneous branch line of a PAR block (issue #24).

    A branch is exactly one of a full ``step.<id>: DO ...`` invocation
    line (``invocation``) or a ``CALL protocol.name(...) -> targets``
    line (``call``).  Branches carry no nested control of their own —
    nested parallelism is expressed by a branch CALLing a protocol whose
    program contains its own PAR block.  The branch's deterministic id
    (``par<k>``, 1-based source order) is positional and therefore not
    stored on the model.
    """

    invocation: Invocation | None = None
    call: "Call | None" = None
    line: int = 0


@dataclass(frozen=True)
class Par:
    """Bounded heterogeneous parallel block (issue #24).

    ``PAR MAX <n>`` followed by two or more indented branch lines and
    terminated by a matching-dedent ``BARRIER`` line that optionally
    declares the published targets (``BARRIER -> t1, t2``).  ``max_count``
    is the local concurrency ceiling (more branches than ``MAX`` queue;
    the ceiling is further bounded by the run's execution budget).
    Branches execute concurrently as isolated child-scoped runs; the
    barrier blocks until every branch is terminal.  When
    ``barrier_targets`` is empty the published targets are the union of
    the branches' own targets; when declared, the declaration must equal
    that union exactly (validated), pinning the explicit adoption mapping.
    """

    max_count: int
    branches: tuple[ParBranch, ...]
    barrier_targets: tuple[str, ...] = ()
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
class Loop:
    """Bounded iterative refinement block (issue #68).

    ``LOOP <name> ENTRY <expr> WHILE <expr> PROGRESS <expr> MAX <int>
    EXIT <expr> EXHAUSTED <terminal>`` followed by an indented body of
    statements.  The loop executes its body up to ``max_iterations`` times,
    checking the WHILE condition before each iteration, the PROGRESS
    metric after each body execution, and the EXIT condition after each
    iteration.  If MAX is reached without EXIT, the EXHAUSTED terminal
    fires (typically ``STOP unresolved(...)``).

    ``entry_condition`` gates the entire loop: a false entry skips the
    loop like a false IF condition.  ``while_condition`` gates each
    iteration: a false while breaks the loop normally (not exhausted).
    ``progress_expression`` is a raw expression text like
    ``U.high_impact.count decreases`` — the coordinator evaluates the
    metric before and after each iteration and blocks the run if no
    progress is made.  ``exit_condition`` breaks the loop on success.
    ``exhausted`` is a :class:`Stop` terminal or a raw expression string.

    ``body`` is a tuple of statements (invocations, conditionals,
    scatter/gather, par, calls, returns, stops) executed sequentially
    each iteration.
    """

    name: str
    entry_condition: str
    while_condition: str
    progress_expression: str
    max_iterations: int
    exit_condition: str
    exhausted: "Stop | str"
    body: tuple
    line: int = 0


@dataclass(frozen=True)
class Reformulate:
    """Plan reformulation at runtime (issue #80).

    Triggered inside an IF block (or standalone after a failed step) when
    a plan fails mid-execution.  The model can detect the failure,
    diagnose what went wrong, revise invalidated refs, author a new
    sub-plan from the current execution point, and continue — all within
    the same run.

    Four labeled sections:

    - ``DIAGNOSE`` (mandatory): a regular DO step (challenge or review)
      that identifies what went wrong.  ``diagnose`` is an ``Invocation``.
    - ``REVISE`` (optional): retires invalidated refs and creates new ones.
      ``revise`` is a list of ``(old_ref, new_ref)`` tuples.  The old ref
      is retired (history preserved), the new ref is created with the old
      ref's value as a starting point.
    - ``REPLAN`` (mandatory): produces a new sub-plan from the current
      committed state.  ``replan`` is an ``Invocation`` (typically
      ``DO decompose(...)``).  Uses delegate machinery but with a critical
      difference: the child plan inherits ALL committed state from the
      parent (not isolated namespace).
    - ``CONTINUE`` (mandatory): resumes execution at the first step of the
      new plan.  ``continue_ref`` is the ref name produced by REPLAN
      (e.g. ``G.plan2``).
    """

    diagnose: Invocation
    revise: tuple[tuple[str, str], ...]
    replan: Invocation
    continue_ref: str
    line: int = 0


@dataclass(frozen=True)
class Program:
    name: str
    version: str
    declarations: tuple[Declaration, ...]
    statements: tuple[object, ...]
