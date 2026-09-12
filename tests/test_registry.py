"""Tests for the command registry (docs/spec/02-command-catalog.md)."""

import json
from dataclasses import FrozenInstanceError

import pytest

from atlas.registry import (
    Budget,
    CommandSpec,
    ContractError,
    DuplicateCommandError,
    EffectClass,
    ExecutionMode,
    FailureKind,
    FailureSpec,
    IdempotencyMode,
    Registry,
    RegistryError,
    ReservedNameError,
    RoutingPolicy,
    RoutingTier,
    UnknownCommandError,
    builtin_registry,
)

BUILTIN_NAMES = (
    "calculate",
    "challenge",
    "check",
    "choose",
    "compare",
    "decompose",
    "define",
    "delegate",
    "edit",
    "extract",
    "fetch",
    "hypothesize",
    "prove",
    "rank",
    "recall",
    "remember",
    "report",
    "review",
    "search",
    "solve",
    "summarize",
    "test",
    "verify",
)

DECISION_COMMANDS = (
    "decompose",
    "hypothesize",
    "compare",
    "rank",
    "challenge",
    "choose",
)

MEMORY_COMMANDS = (
    "remember",
    "recall",
)

EFFECTFUL_COMMANDS = (
    "edit",
    "test",
    "review",
)

FORMAL_COMMANDS = (
    "prove",
    "solve",
)

# Issue #25: runtime-authored child plans.
DELEGATE_COMMANDS = (
    "delegate",
)

CONTRACT_FIELDS = (
    "name",
    "version",
    "purpose",
    "inputs",
    "parameters",
    "preconditions",
    "outputs",
    "effects",
    "done",
    "failures",
    "effect_class",
    "execution",
    "capabilities",
    "evidence",
    "budget",
    "idempotency",
    "compensation",
    "routing",
)

MANDATORY_STRINGS = ("purpose", "done", "compensation")

MANDATORY_TUPLES = (
    "inputs",
    "parameters",
    "preconditions",
    "outputs",
    "effects",
    "capabilities",
    "evidence",
    "failures",
)


def make_spec(**overrides):
    fields = dict(
        name="probe",
        version="1.0.0",
        purpose="Probe the registry",
        inputs=("request:text",),
        parameters=("limit:int<=10",),
        preconditions=("request_nonempty",),
        outputs=("result:artifact",),
        effects=("none",),
        done="result_digest_recorded",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("probe_tool",),
        evidence=("result_digest",),
        budget=Budget(
            max_seconds=5.0,
            max_tokens=0,
            max_cost=0.0,
            max_attempts=1,
            max_output_bytes=4096,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T0,
            permitted_tiers=(RoutingTier.T0, RoutingTier.T1),
            preferred_tier=RoutingTier.T0,
            validator_tier=RoutingTier.T0,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )
    fields.update(overrides)
    return CommandSpec(**fields)


@pytest.fixture
def registry():
    return builtin_registry()


# --- builtin catalog completeness -------------------------------------------


def test_builtin_registry_holds_exactly_the_catalog_commands(registry):
    assert registry.names() == BUILTIN_NAMES


@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_every_builtin_declares_the_full_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    data = spec.to_dict()
    assert tuple(data) == CONTRACT_FIELDS
    for field in MANDATORY_STRINGS:
        assert isinstance(data[field], str) and data[field].strip(), field
    for field in MANDATORY_TUPLES:
        assert isinstance(data[field], list) and data[field], field
    assert data["name"] == name
    assert data["version"] == "1.0.0"
    assert data["effect_class"] in {e.value for e in EffectClass}
    assert data["execution"] in {e.value for e in ExecutionMode}
    assert data["idempotency"] in {e.value for e in IdempotencyMode}
    for failure in spec.failures:
        assert isinstance(failure.kind, FailureKind)
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_builtin_routing_tiers_are_consistent(registry, name):
    routing = registry.resolve(name, "1.0.0").routing
    assert routing.permitted_tiers
    assert routing.minimum_tier in routing.permitted_tiers
    assert routing.preferred_tier in routing.permitted_tiers
    assert routing.validator_tier in routing.permitted_tiers


# --- decision commands (issue #6) ---------------------------------------------


@pytest.mark.parametrize("name", DECISION_COMMANDS)
def test_decision_command_resolves_with_complete_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.name == name
    assert spec.version == "1.0.0"
    for value in (spec.purpose, spec.done, spec.compensation):
        assert isinstance(value, str) and value.strip()
    for field in (spec.inputs, spec.outputs, spec.effects):
        assert field and all(isinstance(entry, str) and entry.strip() for entry in field)
    assert spec.effect_class in EffectClass
    assert spec.execution in ExecutionMode
    assert spec.idempotency in IdempotencyMode
    assert spec.failures
    for failure in spec.failures:
        assert failure.kind in FailureKind
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


@pytest.mark.parametrize("name", DECISION_COMMANDS)
def test_decision_command_is_registered_under_its_name(registry, name):
    assert name in builtin_registry().names()
    assert name in registry.names()


@pytest.mark.parametrize("name", DECISION_COMMANDS)
def test_decision_command_effect_class_matches_contract_intent(registry, name):
    spec = registry.resolve(name, "1.0.0")
    if name in {"decompose", "choose"}:
        assert spec.effect_class is EffectClass.PURE
    else:
        assert spec.effect_class in {EffectClass.PURE, EffectClass.READ_ONLY}


def test_decision_commands_extend_the_nine_originals():
    original = {"calculate", "check", "define", "extract", "fetch", "report", "search", "summarize", "verify"}
    names = set(builtin_registry().names())
    assert original < names
    assert names - original == (
        set(DECISION_COMMANDS)
        | set(MEMORY_COMMANDS)
        | set(EFFECTFUL_COMMANDS)
        | set(FORMAL_COMMANDS)
        | set(DELEGATE_COMMANDS)
    )


# --- formal delegation commands (issue #11) -------------------------------------


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_resolves_with_complete_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.name == name
    assert spec.version == "1.0.0"
    for value in (spec.purpose, spec.done, spec.compensation):
        assert isinstance(value, str) and value.strip()
    for field in (spec.inputs, spec.outputs, spec.effects):
        assert field and all(isinstance(entry, str) and entry.strip() for entry in field)
    assert spec.effect_class in EffectClass
    assert spec.execution in ExecutionMode
    assert spec.idempotency in IdempotencyMode
    assert spec.failures
    for failure in spec.failures:
        assert failure.kind in FailureKind
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_is_registered_under_its_name(registry, name):
    assert name in builtin_registry().names()
    assert name in registry.names()


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_is_read_only(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.effect_class is EffectClass.READ_ONLY


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_declares_formalization_failure(registry, name):
    spec = registry.resolve(name, "1.0.0")
    formalization = [f for f in spec.failures if f.kind is FailureKind.FORMALIZATION]
    assert len(formalization) == 1
    failure = formalization[0]
    assert failure.retryable is True
    assert "new formalization attempt" in failure.recovery
    assert "blind retry" in failure.recovery


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_invalid_input_is_not_retryable(registry, name):
    spec = registry.resolve(name, "1.0.0")
    invalid = [f for f in spec.failures if f.kind is FailureKind.INVALID_INPUT]
    assert len(invalid) == 1
    assert invalid[0].retryable is False


@pytest.mark.parametrize("name", FORMAL_COMMANDS)
def test_formal_command_declares_unavailable_failure(registry, name):
    spec = registry.resolve(name, "1.0.0")
    unavailable = [f for f in spec.failures if f.kind is FailureKind.UNAVAILABLE]
    assert len(unavailable) == 1
    assert unavailable[0].retryable is True


def test_formalization_kind_exists_with_expected_value():
    assert FailureKind.FORMALIZATION.value == "formalization"
    assert FailureKind("formalization") is FailureKind.FORMALIZATION
    existing = {
        "invalid_input",
        "unavailable",
        "timeout",
        "permission",
        "conflict",
        "insufficient_evidence",
        "validation",
        "execution",
        "unknown",
    }
    assert existing <= {kind.value for kind in FailureKind}


def test_solve_contract_matches_issue_11_spec(registry):
    spec = registry.resolve("solve", "1.0.0")
    assert spec.purpose == (
        "Translate a bounded problem to a formal planning/SMT language"
        " and return the deterministic solver result"
    )
    assert ("problem:text", "domain:descriptor") == spec.inputs
    assert ("solution:artifact", "formalization:artifact") == spec.outputs
    assert spec.routing.minimum_tier is RoutingTier.T1
    assert spec.routing.preferred_tier is RoutingTier.T2
    assert spec.routing.validator_tier is RoutingTier.T0
    assert spec.routing.fallback_chain == ()
    assert "formalization_digest" in spec.evidence
    assert "solver_result" in spec.evidence


def test_prove_contract_matches_issue_11_spec(registry):
    spec = registry.resolve("prove", "1.0.0")
    assert spec.purpose == (
        "Emit a proof artifact in a formal proof language"
        " and verify it with a deterministic checker"
    )
    assert ("statement:text", "language:descriptor") == spec.inputs
    assert ("proof:artifact", "checker_result:artifact") == spec.outputs
    assert spec.routing.minimum_tier is RoutingTier.T2
    assert spec.routing.preferred_tier is RoutingTier.T3
    assert spec.routing.validator_tier is RoutingTier.T0
    assert spec.routing.fallback_chain == ()
    assert "proof_digest" in spec.evidence
    assert "checker_result" in spec.evidence


# --- runtime-authored child plans (issue #25) -----------------------------------


def test_delegate_contract_matches_issue_25_spec(registry):
    spec = registry.resolve("delegate", "1.0.0")
    assert spec.purpose == (
        "Author and execute a bounded child plan at runtime from"
        " committed context"
    )
    assert ("goal:text", "constraints:text") == spec.inputs
    assert ("plan_digest:artifact", "result:artifact") == spec.outputs
    assert spec.effect_class is EffectClass.READ_ONLY
    assert spec.routing.minimum_tier is RoutingTier.T2
    assert spec.routing.preferred_tier is RoutingTier.T3
    assert spec.routing.validator_tier is RoutingTier.T0
    assert "plan_digest" in spec.evidence
    assert "child_run_id" in spec.evidence


@pytest.mark.parametrize("name", DELEGATE_COMMANDS)
def test_delegate_command_resolves_with_complete_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.name == name
    assert spec.version == "1.0.0"
    for value in (spec.purpose, spec.done, spec.compensation):
        assert isinstance(value, str) and value.strip()
    for field in (spec.inputs, spec.outputs, spec.effects):
        assert field and all(isinstance(entry, str) and entry.strip() for entry in field)
    assert spec.failures
    for failure in spec.failures:
        assert failure.kind in FailureKind
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


def test_delegate_declares_expected_failures(registry):
    spec = registry.resolve("delegate", "1.0.0")
    kinds = {failure.kind for failure in spec.failures}
    assert {FailureKind.INVALID_INPUT, FailureKind.FORMALIZATION, FailureKind.UNAVAILABLE} <= kinds
    invalid = [f for f in spec.failures if f.kind is FailureKind.INVALID_INPUT]
    assert invalid[0].retryable is False
    formalization = [f for f in spec.failures if f.kind is FailureKind.FORMALIZATION]
    assert formalization[0].retryable is True


# --- memory commands (issue #5) ------------------------------------------------


@pytest.mark.parametrize("name", MEMORY_COMMANDS)
def test_memory_command_resolves_with_complete_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.name == name
    assert spec.version == "1.0.0"
    for value in (spec.purpose, spec.done, spec.compensation):
        assert isinstance(value, str) and value.strip()
    for field in (spec.inputs, spec.outputs, spec.effects):
        assert field and all(isinstance(entry, str) and entry.strip() for entry in field)
    assert spec.effect_class in EffectClass
    assert spec.execution in ExecutionMode
    assert spec.idempotency in IdempotencyMode
    assert spec.failures
    for failure in spec.failures:
        assert failure.kind in FailureKind
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


@pytest.mark.parametrize("name", MEMORY_COMMANDS)
def test_memory_command_is_registered_under_its_name(registry, name):
    assert name in builtin_registry().names()
    assert name in registry.names()


@pytest.mark.parametrize("name", MEMORY_COMMANDS)
def test_memory_command_effect_class_matches_contract_intent(registry, name):
    spec = registry.resolve(name, "1.0.0")
    if name == "remember":
        assert spec.effect_class is EffectClass.REVERSIBLE_WRITE
    else:
        assert spec.effect_class is EffectClass.READ_ONLY


# --- effectful commands (issue #9) ---------------------------------------------


@pytest.mark.parametrize("name", EFFECTFUL_COMMANDS)
def test_effectful_command_resolves_with_complete_contract(registry, name):
    spec = registry.resolve(name, "1.0.0")
    assert spec.name == name
    assert spec.version == "1.0.0"
    for value in (spec.purpose, spec.done, spec.compensation):
        assert isinstance(value, str) and value.strip()
    for field in (spec.inputs, spec.outputs, spec.effects):
        assert field and all(isinstance(entry, str) and entry.strip() for entry in field)
    assert spec.effect_class in EffectClass
    assert spec.execution in ExecutionMode
    assert spec.idempotency in IdempotencyMode
    assert spec.failures
    for failure in spec.failures:
        assert failure.kind in FailureKind
        assert isinstance(failure.retryable, bool)
        assert failure.recovery.strip()


@pytest.mark.parametrize("name", EFFECTFUL_COMMANDS)
def test_effectful_command_is_registered_under_its_name(registry, name):
    assert name in builtin_registry().names()
    assert name in registry.names()


@pytest.mark.parametrize("name", EFFECTFUL_COMMANDS)
def test_effectful_command_effect_class_matches_contract_intent(registry, name):
    spec = registry.resolve(name, "1.0.0")
    if name == "edit":
        assert spec.effect_class is EffectClass.IRREVERSIBLE_WRITE
    else:
        assert spec.effect_class is EffectClass.READ_ONLY


@pytest.mark.parametrize("name", ("edit", "test", "review"))
def test_effectful_command_declares_workspace_inputs(registry, name):
    spec = registry.resolve(name, "1.0.0")
    if name == "review":
        assert any("refs" in entry for entry in spec.inputs)
    else:
        assert any("path" in entry for entry in spec.inputs)


def test_edit_compensation_is_not_a_placeholder():
    spec = builtin_registry().resolve("edit", "1.0.0")
    assert spec.compensation.strip() not in {"", "none"}


# --- resolve and version pinning --------------------------------------------


def test_resolve_returns_pinned_version():
    registry = Registry()
    for version in ("1.0.0", "1.1.0", "2.0.0"):
        registry.register(make_spec(name="probe", version=version))
    assert registry.resolve("probe", "1.0.0").version == "1.0.0"
    assert registry.resolve("probe", "2.0.0").version == "2.0.0"
    assert registry.resolve("probe").version == "2.0.0"


def test_resolve_unknown_name_and_version_raise():
    registry = builtin_registry()
    with pytest.raises(UnknownCommandError):
        registry.resolve("nonexistent")
    with pytest.raises(UnknownCommandError):
        registry.resolve("fetch", "9.9.9")
    with pytest.raises(UnknownCommandError):
        registry.versions("nonexistent")


def test_versions_lists_sorted_semver():
    registry = Registry()
    for version in ("2.0.0", "1.0.0", "1.1.0", "1.0.1-rc.1"):
        registry.register(make_spec(name="probe", version=version))
    assert registry.versions("probe") == ("1.0.0", "1.0.1-rc.1", "1.1.0", "2.0.0")
    assert registry.resolve("probe", "1.0.1-rc.1").version == "1.0.1-rc.1"


# --- duplicates ---------------------------------------------------------------


def test_register_rejects_duplicate_name_version():
    registry = Registry()
    spec = make_spec()
    registry.register(spec)
    with pytest.raises(DuplicateCommandError):
        registry.register(make_spec())
    assert registry.resolve("probe", "1.0.0") is spec


def test_register_accepts_same_name_new_version():
    registry = Registry()
    registry.register(make_spec(version="1.0.0"))
    registry.register(make_spec(version="1.1.0"))
    assert registry.versions("probe") == ("1.0.0", "1.1.0")


# --- reserved control names ---------------------------------------------------


@pytest.mark.parametrize(
    "reserved", ["run", "RUN", "Run", "seal", "SEAL", "approve", "APPROVE", "await", "pause", "resume", "cancel", "fork"]
)
def test_reserved_control_names_rejected_case_insensitively(reserved):
    with pytest.raises(ReservedNameError):
        make_spec(name=reserved)


def test_reserved_words_are_prefix_safe():
    spec = make_spec(name="runaway")
    assert spec.name == "runaway"


# --- malformed specs ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name", ["Define", "define-2", "1define", "has space", "UPPER", "", "dot.name"]
)
def test_malformed_names_rejected(bad_name):
    with pytest.raises(ContractError):
        make_spec(name=bad_name)


@pytest.mark.parametrize(
    "bad_version", ["1.0", "1", "v1.0.0", "1.0.0.0", "abc", "01.2.3", ""]
)
def test_malformed_versions_rejected(bad_version):
    with pytest.raises(ContractError):
        make_spec(version=bad_version)


@pytest.mark.parametrize("field", MANDATORY_STRINGS)
def test_empty_mandatory_strings_rejected(field):
    with pytest.raises(ContractError):
        make_spec(**{field: ""})


@pytest.mark.parametrize("field", MANDATORY_TUPLES)
def test_empty_mandatory_tuples_rejected(field):
    with pytest.raises(ContractError):
        make_spec(**{field: ()})


@pytest.mark.parametrize("field", tuple(f for f in MANDATORY_TUPLES if f != "failures"))
def test_non_string_tuple_entries_rejected(field):
    with pytest.raises(ContractError):
        make_spec(**{field: ("ok", 42)})


def test_missing_field_is_an_error():
    data = make_spec().to_dict()
    for field in CONTRACT_FIELDS:
        partial = dict(data)
        del partial[field]
        with pytest.raises((KeyError, TypeError)):
            CommandSpec.from_dict(partial)


def test_routing_must_permit_minimum_preferred_and_validator_tiers():
    with pytest.raises(ContractError):
        make_spec(
            routing=RoutingPolicy(
                minimum_tier=RoutingTier.T1,
                permitted_tiers=(RoutingTier.T2, RoutingTier.T3),
                preferred_tier=RoutingTier.T1,
                validator_tier=RoutingTier.T1,
                confidence_policy="none",
                escalation_on=(),
                fallback_chain=(),
            )
        )
    with pytest.raises(ContractError):
        make_spec(
            routing=RoutingPolicy(
                minimum_tier=RoutingTier.T1,
                permitted_tiers=(RoutingTier.T1, RoutingTier.T2),
                preferred_tier=RoutingTier.T3,
                validator_tier=RoutingTier.T1,
                confidence_policy="none",
                escalation_on=(),
                fallback_chain=(),
            )
        )
    with pytest.raises(ContractError):
        make_spec(
            routing=RoutingPolicy(
                minimum_tier=RoutingTier.T1,
                permitted_tiers=(RoutingTier.T1, RoutingTier.T2),
                preferred_tier=RoutingTier.T1,
                validator_tier=RoutingTier.T0,
                confidence_policy="none",
                escalation_on=(),
                fallback_chain=(),
            )
        )


def test_budget_rejects_bad_numbers():
    with pytest.raises(ContractError):
        make_spec(
            budget=Budget(
                max_seconds=-1.0, max_tokens=0, max_cost=0.0, max_attempts=1, max_output_bytes=1
            )
        )
    with pytest.raises(ContractError):
        make_spec(
            budget=Budget(
                max_seconds=1.0, max_tokens=0, max_cost=0.0, max_attempts=0, max_output_bytes=1
            )
        )


def test_unknown_enum_string_rejected():
    data = make_spec().to_dict()
    data["effect_class"] = "sideways"
    with pytest.raises(ContractError):
        CommandSpec.from_dict(data)


# --- deterministic serialization ---------------------------------------------


@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_json_roundtrip_all_builtins(registry, name):
    spec = registry.resolve(name, "1.0.0")
    payload = json.dumps(spec.to_dict())
    restored = CommandSpec.from_dict(json.loads(payload))
    assert restored == spec
    assert json.dumps(restored.to_dict()) == payload


def test_to_dict_is_deterministic():
    first = make_spec().to_dict()
    second = make_spec().to_dict()
    assert tuple(first) == CONTRACT_FIELDS
    assert list(first) == list(second)
    assert first == second
    assert json.dumps(first) == json.dumps(second)


def test_nested_specs_roundtrip_through_dict():
    spec = make_spec()
    restored = CommandSpec.from_dict(spec.to_dict())
    assert restored.budget == spec.budget
    assert restored.routing == spec.routing
    assert restored.failures == spec.failures
    assert restored.routing.minimum_tier is RoutingTier.T0


# --- immutability ---------------------------------------------------------------


def test_command_spec_is_frozen():
    spec = make_spec()
    with pytest.raises(FrozenInstanceError):
        spec.name = "other"
    with pytest.raises(FrozenInstanceError):
        spec.inputs = ("x",)


def test_nested_specs_are_frozen():
    spec = make_spec()
    with pytest.raises(FrozenInstanceError):
        spec.budget.max_seconds = 99.0
    with pytest.raises(FrozenInstanceError):
        spec.routing.minimum_tier = RoutingTier.T3
    with pytest.raises(FrozenInstanceError):
        spec.failures[0].recovery = "changed"


def test_to_dict_returns_defensive_copies():
    spec = make_spec()
    data = spec.to_dict()
    data["inputs"].append("mutated")
    data["budget"]["max_seconds"] = 999.0
    assert spec.inputs == ("request:text",)
    assert spec.budget.max_seconds == 5.0
    assert spec.to_dict() == make_spec().to_dict()


def test_registry_errors_share_base_class():
    assert issubclass(DuplicateCommandError, RegistryError)
    assert issubclass(UnknownCommandError, RegistryError)
    assert issubclass(ReservedNameError, RegistryError)
    assert issubclass(ContractError, RegistryError)
