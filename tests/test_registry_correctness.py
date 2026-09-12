"""Tests for issues #33, #34, #35 — registry correctness bundle."""

import dataclasses

import pytest

from tahoe.registry import (
    Budget,
    CommandSpec,
    ContractError,
    EffectClass,
    ExecutionMode,
    FailureKind,
    FailureSpec,
    IdempotencyMode,
    Registry,
    RoutingPolicy,
    RoutingTier,
    SchemaError,
    builtin_registry,
)
from tahoe.registry.registry import _version_sort_key, registry_digest


def _make_spec(**overrides):
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


# --- Issue #33: registry_digest hashes full specs ----------------------------


def test_digest_changes_on_capability_change():
    """Acceptance (1): capability change -> different digest."""
    r1 = Registry()
    r2 = Registry()
    r1.register(_make_spec(capabilities=("cap_a",)))
    r2.register(_make_spec(capabilities=("cap_b",)))
    assert registry_digest(r1) != registry_digest(r2)


def test_digest_changes_on_budget_change():
    """Acceptance (2): budget change -> different digest."""
    r1 = Registry()
    r2 = Registry()
    r1.register(_make_spec(budget=Budget(
        max_seconds=9999.0, max_tokens=0, max_cost=0.0,
        max_attempts=1, max_output_bytes=4096,
    )))
    r2.register(_make_spec(budget=Budget(
        max_seconds=30.0, max_tokens=0, max_cost=0.0,
        max_attempts=1, max_output_bytes=4096,
    )))
    assert registry_digest(r1) != registry_digest(r2)


def test_digest_invariant_to_registration_order():
    """Acceptance (3): digest stays invariant to registration order."""
    specs = [
        _make_spec(name="alpha", version="1.0.0"),
        _make_spec(name="beta", version="1.0.0"),
        _make_spec(name="gamma", version="1.0.0"),
    ]
    r1 = Registry()
    for s in specs:
        r1.register(s)
    r2 = Registry()
    for s in reversed(specs):
        r2.register(s)
    assert registry_digest(r1) == registry_digest(r2)


def test_digest_changes_on_failure_change():
    """Bonus: failure spec change -> different digest."""
    r1 = Registry()
    r2 = Registry()
    r1.register(_make_spec(failures=(
        FailureSpec(kind=FailureKind.INVALID_INPUT, retryable=False, recovery="reject"),
    )))
    r2.register(_make_spec(failures=(
        FailureSpec(kind=FailureKind.TIMEOUT, retryable=True, recovery="retry"),
    )))
    assert registry_digest(r1) != registry_digest(r2)


def test_digest_changes_on_idempotency_change():
    """Bonus: idempotency mode change -> different digest."""
    r1 = Registry()
    r2 = Registry()
    r1.register(_make_spec(idempotency=IdempotencyMode.INPUT_DIGEST))
    r2.register(_make_spec(idempotency=IdempotencyMode.NONE))
    assert registry_digest(r1) != registry_digest(r2)


def test_builtin_digest_is_stable_across_calls():
    """The builtin registry digest is stable across repeated calls."""
    d1 = registry_digest(builtin_registry())
    d2 = registry_digest(builtin_registry())
    assert d1 == d2
    assert len(d1) == 64


def test_builtin_registry_has_23_commands():
    """Acceptance (4): doc count matches len(builtin_registry().names())."""
    assert len(builtin_registry().names()) == 23


# --- Issue #34: prerelease ordering and minimum_tier enforcement --------------


def test_prerelease_alpha10_sorts_after_alpha2():
    """Acceptance (1): alpha.10 resolves over alpha.2."""
    assert _version_sort_key("1.0.0-alpha.2") < _version_sort_key("1.0.0-alpha.10")


def test_release_beats_prerelease():
    """Acceptance (1): release beats prerelease."""
    assert _version_sort_key("1.0.0-rc.1") < _version_sort_key("1.0.0")


def test_resolve_picks_alpha10_over_alpha2():
    """End-to-end: resolve() picks alpha.10 as latest."""
    r = Registry()
    r.register(_make_spec(version="1.0.0-alpha.2"))
    r.register(_make_spec(version="1.0.0-alpha.10"))
    assert r.resolve("probe").version == "1.0.0-alpha.10"


def test_resolve_release_beats_prerelease():
    """End-to-end: resolve() picks release over prerelease."""
    r = Registry()
    r.register(_make_spec(version="1.0.0-rc.1"))
    r.register(_make_spec(version="1.0.0"))
    assert r.resolve("probe").version == "1.0.0"


def test_routing_policy_rejects_permitted_tier_below_minimum():
    """Acceptance (2): RoutingPolicy rejects sub-minimum permitted_tiers."""
    with pytest.raises(ContractError, match="below.*minimum_tier"):
        _make_spec(routing=RoutingPolicy(
            minimum_tier=RoutingTier.T2,
            permitted_tiers=(RoutingTier.T0, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T2,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ))


def test_builtin_fetch_permitted_tiers_all_above_minimum():
    """The fetch builtin no longer permits T0 below its minimum_tier T1."""
    spec = builtin_registry().resolve("fetch")
    min_rank = int(spec.routing.minimum_tier.value[1])
    for tier in spec.routing.permitted_tiers:
        assert int(tier.value[1]) >= min_rank


def test_builtin_prove_permitted_tiers_all_above_minimum():
    """The prove builtin no longer permits T0 below its minimum_tier T2."""
    spec = builtin_registry().resolve("prove")
    min_rank = int(spec.routing.minimum_tier.value[1])
    for tier in spec.routing.permitted_tiers:
        assert int(tier.value[1]) >= min_rank


def test_builtin_delegate_permitted_tiers_all_above_minimum():
    """The delegate builtin no longer permits T0 below its minimum_tier T2."""
    spec = builtin_registry().resolve("delegate")
    min_rank = int(spec.routing.minimum_tier.value[1])
    for tier in spec.routing.permitted_tiers:
        assert int(tier.value[1]) >= min_rank


def test_builtin_solve_permitted_tiers_all_above_minimum():
    """The solve builtin also no longer permits T0 below its minimum_tier T1."""
    spec = builtin_registry().resolve("solve")
    min_rank = int(spec.routing.minimum_tier.value[1])
    for tier in spec.routing.permitted_tiers:
        assert int(tier.value[1]) >= min_rank


def test_all_builtins_permitted_tiers_above_minimum():
    """Every builtin command's permitted_tiers are all >= minimum_tier."""
    r = builtin_registry()
    for name in r.names():
        spec = r.resolve(name)
        min_rank = int(spec.routing.minimum_tier.value[1])
        for tier in spec.routing.permitted_tiers:
            assert int(tier.value[1]) >= min_rank, (
                f"{name}: {tier.value} < {spec.routing.minimum_tier.value}"
            )


# --- Issue #35: type grammar validation and SchemaError -----------------------


def test_unknown_type_suffix_raises_schema_error():
    """Acceptance (1): unknown type suffix -> SchemaError."""
    with pytest.raises(SchemaError, match="unknown type"):
        _make_spec(inputs=("request:$$$weird",))


def test_unbounded_int_parameter_raises_schema_error():
    """Acceptance (2): unbounded int parameter -> SchemaError."""
    with pytest.raises(SchemaError, match="int parameter requires a bound"):
        _make_spec(parameters=("limit:int",))


def test_all_23_builtins_register_with_type_validation():
    """Acceptance (3): all 23 builtins still register."""
    r = builtin_registry()
    assert len(r.names()) == 23


def test_missing_colon_raises_schema_error():
    """An entry without name:type separator raises SchemaError."""
    with pytest.raises(SchemaError, match="must be 'name:type'"):
        _make_spec(inputs=("notype",))


def test_empty_type_raises_schema_error():
    """An entry with empty type raises SchemaError."""
    with pytest.raises(SchemaError, match="empty type"):
        _make_spec(inputs=("request:",))


def test_bad_name_in_entry_raises_schema_error():
    """An entry with invalid name raises SchemaError."""
    with pytest.raises(SchemaError, match="invalid name"):
        _make_spec(inputs=("Request:text",))


def test_valid_compound_type_accepted():
    """Compound slash types with valid segments are accepted."""
    _make_spec(inputs=("target:pddl/smt",))
    _make_spec(inputs=("schema:G/C/P/K/OUT",))
    _make_spec(inputs=("ambiguity:Q/U",))


def test_invalid_compound_segment_raises_schema_error():
    """Compound types with an invalid segment raise SchemaError."""
    with pytest.raises(SchemaError, match="unknown type segment"):
        _make_spec(inputs=("target:pddl/unknown_solver",))


def test_bounded_int_variants_accepted():
    """All bound syntaxes (<=, >=, >, <) are accepted."""
    _make_spec(parameters=("limit:int<=100",))
    _make_spec(parameters=("limit:int>0",))
    _make_spec(parameters=("limit:int>=1",))
    _make_spec(parameters=("limit:int<1000",))


def test_schema_error_is_registry_error():
    """SchemaError is a subclass of RegistryError (was dead code, now raised)."""
    from tahoe.registry import RegistryError
    assert issubclass(SchemaError, RegistryError)


def test_schema_error_is_not_contract_error():
    """SchemaError is distinct from ContractError."""
    from tahoe.registry import ContractError
    assert not issubclass(SchemaError, ContractError)
    assert not issubclass(ContractError, SchemaError)
