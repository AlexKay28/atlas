"""Sentinel marking a contract field whose value was never supplied.

The command contract (docs/spec/02-command-catalog.md) requires every field to
be mandatory, including explicit ``none``. Dataclass fields that may legitimately
hold ``None`` therefore default to ``UNSET`` instead: a caller that omits the
field produces an incomplete contract, while a caller that passes ``None``
produces the explicit-none form the spec requires.
"""

UNSET = object()
