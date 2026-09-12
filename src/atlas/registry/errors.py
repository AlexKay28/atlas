"""Exception hierarchy for the command registry."""


class RegistryError(ValueError):
    """Base class for all command-registry errors."""


class SchemaError(RegistryError):
    """A type reference, port, or parameter violates the bounded type grammar."""


class ContractError(RegistryError):
    """A command definition is incomplete or violates the command contract."""


class DuplicateCommandError(RegistryError):
    """A command with the same name and version is already registered."""


class UnknownCommandError(RegistryError):
    """No registered command matches the requested name and version."""


class ReservedNameError(RegistryError):
    """A command name collides with a reserved control word."""
