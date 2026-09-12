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
    step_id: str
    command: str
    args: tuple[Argument, ...]
    targets: tuple[str, ...]
    done: DonePredicate | None = None


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
