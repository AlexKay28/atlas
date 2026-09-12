"""Name/version keyed store of command contracts (docs/spec/02-command-catalog.md)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from .errors import DuplicateCommandError, ReservedNameError, UnknownCommandError
from .spec import RESERVED_CONTROL_NAMES, CommandSpec, NAME_PATTERN

_VERSION_HEAD = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _version_sort_key(version: str) -> tuple:
    """Order versions semver-style: 1.2.3 < 1.2.4, prerelease < release."""
    match = _VERSION_HEAD.match(version)
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    is_release = 0 if version[match.end() :].startswith("-") else 1
    return (major, minor, patch, is_release, version)


def registry_digest(registry: "Registry") -> str:
    """Deterministic digest of the registry's command-contract set.

    Canonical JSON of the sorted ``(name, version, effect_class, execution,
    minimum_tier)`` summary tuples, sha256-hex-encoded.  Only the stable
    summary fields are hashed, so the digest is cheap to compute and stays
    deterministic across registration order, interpreter runs, and hosts;
    any change to the registered spec set (names, versions, or one of the
    summary fields) changes the digest.
    """
    summaries = sorted(
        (
            spec.name,
            spec.version,
            spec.effect_class.value,
            spec.execution.value,
            spec.routing.minimum_tier.value,
        )
        for name in registry.names()
        for version in registry.versions(name)
        for spec in (registry.resolve(name, version),)
    )
    payload = json.dumps(summaries, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Registry:
    """Stores immutable command specs keyed by (name, version)."""

    def __init__(self) -> None:
        self._commands: dict[str, dict[str, CommandSpec]] = {}

    def register(self, spec: CommandSpec) -> CommandSpec:
        if spec.name.casefold() in RESERVED_CONTROL_NAMES:
            raise ReservedNameError(
                f"command name {spec.name!r} collides with a reserved control word"
            )
        if not NAME_PATTERN.fullmatch(spec.name):
            raise ReservedNameError(f"invalid command name {spec.name!r}")
        bucket = self._commands.setdefault(spec.name, {})
        if spec.version in bucket:
            raise DuplicateCommandError(
                f"command {spec.name}@{spec.version} is already registered"
            )
        bucket[spec.version] = spec
        return spec

    def resolve(self, name: str, version: Optional[str] = None) -> CommandSpec:
        bucket = self._commands.get(name)
        if bucket is None:
            raise UnknownCommandError(f"no command named {name!r} is registered")
        if version is None:
            version = max(bucket, key=_version_sort_key)
        spec = bucket.get(version)
        if spec is None:
            known = ", ".join(sorted(bucket))
            raise UnknownCommandError(
                f"command {name}@{version} is not registered; known versions: {known}"
            )
        return spec

    def versions(self, name: str) -> tuple[str, ...]:
        bucket = self._commands.get(name)
        if bucket is None:
            raise UnknownCommandError(f"no command named {name!r} is registered")
        return tuple(sorted(bucket, key=_version_sort_key))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._commands))


def builtin_registry() -> Registry:
    """Registry preloaded with the standard catalog commands."""
    from .builtins import load_builtin_registry

    return load_builtin_registry()
