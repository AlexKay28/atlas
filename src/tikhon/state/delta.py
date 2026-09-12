"""Immutable state deltas applied by deterministic projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional


def _freeze_nodes(nodes: Optional[Iterable[Mapping[str, Any]]]) -> tuple[dict, ...]:
    return tuple(dict(node) for node in (nodes or ()))


@dataclass(frozen=True)
class StateDelta:
    """A pure, immutable change to a run's projected state.

    Projection semantics (applied in this order, deterministically):

    - ``add_nodes``: insert each node (a mapping with an ``"id"``) into
      ``state["nodes"]`` keyed by id, replacing any prior value;
    - ``revise_nodes``: merge each mapping into the node with the same id
      (creating it if absent); keys in the revision win;
    - ``retire_nodes``: remove each node id from ``state["nodes"]``;
    - ``add_artifacts``: insert each artifact (a mapping with an ``"id"``)
      into ``state["artifacts"]`` keyed by id, replacing any prior value.
    """

    add_nodes: tuple[dict, ...] = ()
    revise_nodes: tuple[dict, ...] = ()
    retire_nodes: tuple[str, ...] = ()
    add_artifacts: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "add_nodes", _freeze_nodes(self.add_nodes))
        object.__setattr__(self, "revise_nodes", _freeze_nodes(self.revise_nodes))
        object.__setattr__(self, "retire_nodes", tuple(self.retire_nodes or ()))
        object.__setattr__(self, "add_artifacts", _freeze_nodes(self.add_artifacts))

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict form."""
        return {
            "add_nodes": [dict(node) for node in self.add_nodes],
            "revise_nodes": [dict(node) for node in self.revise_nodes],
            "retire_nodes": list(self.retire_nodes),
            "add_artifacts": [dict(artifact) for artifact in self.add_artifacts],
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "StateDelta":
        """Rebuild a delta from :meth:`to_dict` output (or a partial subset)."""
        data = data or {}
        return cls(
            add_nodes=data.get("add_nodes", ()),
            revise_nodes=data.get("revise_nodes", ()),
            retire_nodes=data.get("retire_nodes", ()),
            add_artifacts=data.get("add_artifacts", ()),
        )

    def is_empty(self) -> bool:
        return not (
            self.add_nodes or self.revise_nodes or self.retire_nodes or self.add_artifacts
        )

    def apply_to(self, state: dict) -> None:
        """Apply this delta to ``state`` in place, deterministically."""
        nodes = state.setdefault("nodes", {})
        for node in self.add_nodes:
            nodes[node["id"]] = dict(node)
        for node in self.revise_nodes:
            node_id = node["id"]
            nodes[node_id] = {**nodes.get(node_id, {}), **node}
        for node_id in self.retire_nodes:
            nodes.pop(node_id, None)
        artifacts = state.setdefault("artifacts", {})
        for artifact in self.add_artifacts:
            artifacts[artifact["id"]] = dict(artifact)
