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
