"""Command registry and standard catalog (docs/spec/02-command-catalog.md)."""

from .enums import EffectClass, ExecutionMode, FailureKind, IdempotencyMode, RoutingTier
from .errors import (
    ContractError,
    DuplicateCommandError,
    RegistryError,
    ReservedNameError,
    SchemaError,
    UnknownCommandError,
)
from .registry import Registry, builtin_registry
from .spec import Budget, CommandSpec, FailureSpec, RoutingPolicy

__all__ = [
    "Budget",
    "CommandSpec",
    "ContractError",
    "DuplicateCommandError",
    "EffectClass",
    "ExecutionMode",
    "FailureKind",
    "FailureSpec",
    "IdempotencyMode",
    "Registry",
    "RegistryError",
    "ReservedNameError",
    "RoutingPolicy",
    "RoutingTier",
    "SchemaError",
    "UnknownCommandError",
    "builtin_registry",
]
