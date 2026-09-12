"""Standard catalog commands (docs/spec/02-command-catalog.md, complete contracts)."""

from __future__ import annotations

from .enums import EffectClass, ExecutionMode, FailureKind, IdempotencyMode, RoutingTier
from .registry import Registry
from .spec import Budget, CommandSpec, FailureSpec, RoutingPolicy

_VERSION = "1.0.0"


def _define() -> CommandSpec:
    return CommandSpec(
        name="define",
        version=_VERSION,
        purpose="Frame a request into typed goal, context, plan, knowledge, and output nodes",
        inputs=("request:text",),
        parameters=("node_schema:G/C/P/K/OUT", "ambiguity_policy:Q/U"),
        preconditions=("request_nonempty", "authoring_revision_sealed", "budget_within_parent"),
        outputs=("typed_nodes:G/C/P/K/OUT", "ambiguities:Q/U"),
        effects=("none",),
        done="all_ambiguities_recorded_as_Q_or_U_and_no_hidden_assumptions_remain",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the malformed request",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after the request is revised or a Q node is answered",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("typed_node_authoring",),
        evidence=("authored_node_digest", "ambiguity_manifest"),
        budget=Budget(
            max_seconds=15.0,
            max_tokens=2000,
            max_cost=0.0,
            max_attempts=1,
            max_output_bytes=65536,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="none",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=(),
        ),
    )


def _search() -> CommandSpec:
    return CommandSpec(
        name="search",
        version=_VERSION,
        purpose="Find ranked candidates matching a query within a bounded scope",
        inputs=("query:text", "scope:descriptor"),
        parameters=("limit:int<=100", "filters:map", "timeout_seconds:int>0"),
        preconditions=("query_nonempty", "scope_addressable", "budget_available"),
        outputs=("candidates:ranked_refs", "ranking_evidence:artifact"),
        effects=("external_read_only",),
        done="query_scope_source_and_ranking_evidence_recorded",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the malformed query or scope",
            ),
            FailureSpec(
                kind=FailureKind.UNAVAILABLE,
                retryable=True,
                recovery="retry within budget attempts, then fall back",
            ),
            FailureSpec(
                kind=FailureKind.TIMEOUT,
                retryable=True,
                recovery="retry with a smaller scope or shorter deadline",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only with a new query, source, or budget",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("network.search",),
        evidence=("query_scope_digest", "source_list", "ranking_scores"),
        budget=Budget(
            max_seconds=30.0,
            max_tokens=4000,
            max_cost=0.05,
            max_attempts=3,
            max_output_bytes=262144,
        ),
        idempotency=IdempotencyMode.NONE,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T1,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_search",
            escalation_on=(FailureKind.TIMEOUT, FailureKind.UNAVAILABLE),
            fallback_chain=("fetch@1.0.0",),
        ),
    )


def _fetch() -> CommandSpec:
    return CommandSpec(
        name="fetch",
        version=_VERSION,
        purpose="Retrieve referenced resources as immutable artifacts",
        inputs=("resource_refs:refs",),
        parameters=("accept:media_types", "timeout_seconds:int>0"),
        preconditions=("refs_addressable", "budget_available", "capability_network_granted"),
        outputs=("artifacts:immutable", "retrieval_metadata:artifact"),
        effects=("external_read_only",),
        done="content_digest_and_retrieval_metadata_recorded_for_every_ref",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the unaddressable refs",
            ),
            FailureSpec(
                kind=FailureKind.UNAVAILABLE,
                retryable=True,
                recovery="retry within budget attempts, then fall back",
            ),
            FailureSpec(
                kind=FailureKind.TIMEOUT,
                retryable=True,
                recovery="retry with a longer deadline or fewer refs",
            ),
            FailureSpec(
                kind=FailureKind.PERMISSION,
                retryable=False,
                recovery="report denied capability; no retry without new authorization",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("network.fetch",),
        evidence=("content_digest", "retrieval_metadata"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=1000,
            max_cost=0.02,
            max_attempts=3,
            max_output_bytes=1048576,
        ),
        idempotency=IdempotencyMode.EXTERNAL_KEY,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T0, RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T1,
            validator_tier=RoutingTier.T0,
            confidence_policy="none",
            escalation_on=(FailureKind.TIMEOUT, FailureKind.UNAVAILABLE),
            fallback_chain=("search@1.0.0",),
        ),
    )


def _extract() -> CommandSpec:
    return CommandSpec(
        name="extract",
        version=_VERSION,
        purpose="Turn an artifact into typed records bound to source locations",
        inputs=("artifact:immutable", "schema:bounded_types"),
        parameters=("record_limit:int>0", "strictness:enum"),
        preconditions=("artifact_digest_known", "schema_bounded"),
        outputs=("records:typed", "source_links:refs"),
        effects=("none",),
        done="every_record_links_to_a_source_location",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report schema or artifact mismatch",
            ),
            FailureSpec(
                kind=FailureKind.VALIDATION,
                retryable=False,
                recovery="return typed validation defects without retry",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("structured_extraction",),
        evidence=("record_source_links", "input_digest"),
        budget=Budget(
            max_seconds=30.0,
            max_tokens=8000,
            max_cost=0.0,
            max_attempts=2,
            max_output_bytes=1048576,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T0,
            permitted_tiers=(RoutingTier.T0, RoutingTier.T1, RoutingTier.T2),
            preferred_tier=RoutingTier.T1,
            validator_tier=RoutingTier.T0,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )


def _summarize() -> CommandSpec:
    return CommandSpec(
        name="summarize",
        version=_VERSION,
        purpose="Produce a bounded summary whose claims trace to sources",
        inputs=("source_refs:refs", "budget:token_cap"),
        parameters=("target_tokens:int>0", "depth:enum"),
        preconditions=("sources_fetched", "budget_within_parent"),
        outputs=("summary:artifact", "claim_source_map:refs"),
        effects=("none",),
        done="claims_retain_source_refs_and_no_new_claims_are_introduced",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report missing or unfetched sources",
            ),
            FailureSpec(
                kind=FailureKind.TIMEOUT,
                retryable=True,
                recovery="retry with a smaller target or fewer sources",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only with new sources or a larger budget",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("claim_source_map", "summary_digest"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=6000,
            max_cost=0.10,
            max_attempts=2,
            max_output_bytes=131072,
        ),
        idempotency=IdempotencyMode.NONE,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_summary",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=(),
        ),
    )


def _report() -> CommandSpec:
    return CommandSpec(
        name="report",
        version=_VERSION,
        purpose="Render committed state references into a required report format",
        inputs=("committed_refs:refs", "format:descriptor"),
        parameters=("sections:tuple", "audience:enum"),
        preconditions=("refs_committed", "format_supported"),
        outputs=("report:artifact",),
        effects=("none",),
        done="required_sections_present_and_claims_trace_to_committed_state",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report unsupported format or uncommitted refs",
            ),
            FailureSpec(
                kind=FailureKind.VALIDATION,
                retryable=False,
                recovery="return missing-section defects without retry",
            ),
            FailureSpec(
                kind=FailureKind.UNAVAILABLE,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("document_rendering",),
        evidence=("report_digest", "section_manifest"),
        budget=Budget(
            max_seconds=45.0,
            max_tokens=8000,
            max_cost=0.05,
            max_attempts=2,
            max_output_bytes=524288,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T1,
            validator_tier=RoutingTier.T1,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )


def _verify() -> CommandSpec:
    return CommandSpec(
        name="verify",
        version=_VERSION,
        purpose="Evaluate original acceptance conditions against collected evidence",
        inputs=("goal:G", "evidence:artifacts"),
        parameters=("acceptance:predicates", "strictness:enum"),
        preconditions=("goal_pinned", "evidence_digests_known"),
        outputs=("verdict:V", "verdict_evidence:refs"),
        effects=("none",),
        done="original_acceptance_condition_evaluated_with_recorded_result",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report unpinned goal or unknown evidence",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after new evidence is collected",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("predicate_evaluation", "language_model"),
        evidence=("verdict_with_reasoning", "inspected_versions"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=6000,
            max_cost=0.10,
            max_attempts=2,
            max_output_bytes=65536,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_verdict",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=("check@1.0.0",),
        ),
    )


def _calculate() -> CommandSpec:
    return CommandSpec(
        name="calculate",
        version=_VERSION,
        purpose="Evaluate a numeric expression exactly with units and precision",
        inputs=("expression:numeric", "values:map"),
        parameters=("units:descriptor", "precision:enum"),
        preconditions=("expression_parseable", "values_numeric"),
        outputs=("value:numeric", "errors:artifact"),
        effects=("none",),
        done="exact_expression_units_precision_and_errors_returned",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the parse or value defect",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("arithmetic_library",),
        evidence=("expression_echo", "value_with_units"),
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
            permitted_tiers=(RoutingTier.T0,),
            preferred_tier=RoutingTier.T0,
            validator_tier=RoutingTier.T0,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )


def _check() -> CommandSpec:
    return CommandSpec(
        name="check",
        version=_VERSION,
        purpose="Run a deterministic predicate over an artifact and record the verdict",
        inputs=("artifact:immutable", "predicate:deterministic"),
        parameters=("version:pinned_ref", "on_error:enum"),
        preconditions=("artifact_digest_known", "predicate_machine_evaluable"),
        outputs=("verdict:V", "inspected_version:ref"),
        effects=("none",),
        done="predicate_result_and_inspected_version_recorded",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report non-evaluable predicate or unknown artifact",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("predicate_evaluation",),
        evidence=("verdict", "inspected_version_digest"),
        budget=Budget(
            max_seconds=10.0,
            max_tokens=0,
            max_cost=0.0,
            max_attempts=1,
            max_output_bytes=8192,
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


def _decompose() -> CommandSpec:
    return CommandSpec(
        name="decompose",
        version=_VERSION,
        purpose="Split a pinned goal into bounded subgoals whose children cover the parent",
        inputs=("goal:G", "protocol:descriptor"),
        parameters=("max_children:int>0", "stop_check_policy:enum"),
        preconditions=("goal_pinned", "protocol_bounded", "budget_within_parent"),
        outputs=("subgoals:bounded_children", "stop_checks:predicates"),
        effects=("none",),
        done="children_cover_parent_and_each_child_declares_a_stop_check",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the unpinned goal or unbounded protocol",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after the goal is revised or clarified",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("goal_decomposition",),
        evidence=("child_coverage_map", "stop_check_manifest"),
        budget=Budget(
            max_seconds=30.0,
            max_tokens=4000,
            max_cost=0.0,
            max_attempts=2,
            max_output_bytes=131072,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_decomposition",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=(),
        ),
    )


def _hypothesize() -> CommandSpec:
    return CommandSpec(
        name="hypothesize",
        version=_VERSION,
        purpose="Generate distinct falsifiable alternatives that answer a question against evidence",
        inputs=("question:text", "evidence:artifacts"),
        parameters=("hypothesis_limit:int>0", "distinctness:enum"),
        preconditions=("question_nonempty", "evidence_digests_known"),
        outputs=("hypotheses:H", "falsifiers:predicates"),
        effects=("none",),
        done="alternatives_are_distinct_and_each_carries_a_falsifiable_prediction",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the empty question or unknown evidence",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after new evidence is collected",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("hypothesis_manifest", "falsifier_set"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=6000,
            max_cost=0.10,
            max_attempts=2,
            max_output_bytes=131072,
        ),
        idempotency=IdempotencyMode.NONE,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_hypotheses",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=(),
        ),
    )


def _compare() -> CommandSpec:
    return CommandSpec(
        name="compare",
        version=_VERSION,
        purpose="Score options against declared criteria with constraints applied before preferences",
        inputs=("options:refs", "criteria:predicates"),
        parameters=("weights:map", "unknown_cell_policy:enum"),
        preconditions=("options_addressable", "criteria_bounded"),
        outputs=("comparison:artifact", "unknown_cells:manifest"),
        effects=("none",),
        done="constraints_applied_before_preferences_and_unknown_cells_recorded_explicitly",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report unaddressable options or unbounded criteria",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only with new evidence or a narrower option set",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("comparison_matrix", "unknown_cell_manifest"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=6000,
            max_cost=0.05,
            max_attempts=2,
            max_output_bytes=131072,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )


def _rank() -> CommandSpec:
    return CommandSpec(
        name="rank",
        version=_VERSION,
        purpose="Order options by declared criteria under explicit tie and missing-evidence policies",
        inputs=("options:refs", "criteria:predicates"),
        parameters=("tie_policy:enum", "missing_evidence_policy:enum"),
        preconditions=("options_addressable", "criteria_bounded"),
        outputs=("ordering:ranked_refs", "tie_report:artifact"),
        effects=("none",),
        done="tie_and_missing_evidence_policies_applied_to_every_option",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report unaddressable options or unbounded criteria",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only with new evidence or a narrower option set",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("ordering_with_scores", "tie_report"),
        budget=Budget(
            max_seconds=30.0,
            max_tokens=4000,
            max_cost=0.0,
            max_attempts=2,
            max_output_bytes=65536,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T1,
            validator_tier=RoutingTier.T1,
            confidence_policy="none",
            escalation_on=(),
            fallback_chain=(),
        ),
    )


def _challenge() -> CommandSpec:
    return CommandSpec(
        name="challenge",
        version=_VERSION,
        purpose="Stress a claim or decision by checking the strongest plausible failure cases",
        inputs=("claim:artifact", "evidence:artifacts"),
        parameters=("adversary_strength:enum", "risk_limit:int>0"),
        preconditions=("claim_digest_known", "evidence_digests_known"),
        outputs=("counterevidence:artifacts", "risks:ranked_manifest"),
        effects=("none",),
        done="strongest_plausible_failure_cases_checked_with_recorded_outcomes",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report the unknown claim or evidence",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after new counterevidence is collected",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.READ_ONLY,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("counterevidence_manifest", "risk_ranking"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=6000,
            max_cost=0.10,
            max_attempts=2,
            max_output_bytes=131072,
        ),
        idempotency=IdempotencyMode.NONE,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_challenge",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=(),
        ),
    )


def _choose() -> CommandSpec:
    return CommandSpec(
        name="choose",
        version=_VERSION,
        purpose="Commit a decision that accepts one valid option or blocks with a typed reason",
        inputs=("valid_options:ranked_refs", "evidence:artifacts"),
        parameters=("decision_policy:enum", "tie_breaker:descriptor"),
        preconditions=("options_validated", "evidence_digests_known", "budget_within_parent"),
        outputs=("decision:D", "blocked_reason:artifact"),
        effects=("none",),
        done="decision_accepts_one_option_or_blocks_with_a_typed_reason",
        failures=(
            FailureSpec(
                kind=FailureKind.INVALID_INPUT,
                retryable=False,
                recovery="reject and report unvalidated options or unknown evidence",
            ),
            FailureSpec(
                kind=FailureKind.INSUFFICIENT_EVIDENCE,
                retryable=True,
                recovery="retry only after new evidence or ranked options arrive",
            ),
            FailureSpec(
                kind=FailureKind.EXECUTION,
                retryable=True,
                recovery="retry within budget attempts",
            ),
        ),
        effect_class=EffectClass.PURE,
        execution=ExecutionMode.IMMEDIATE,
        capabilities=("language_model",),
        evidence=("decision_with_reasoning", "blocked_reason_when_blocked"),
        budget=Budget(
            max_seconds=60.0,
            max_tokens=4000,
            max_cost=0.05,
            max_attempts=2,
            max_output_bytes=8192,
        ),
        idempotency=IdempotencyMode.INPUT_DIGEST,
        compensation="none",
        routing=RoutingPolicy(
            minimum_tier=RoutingTier.T1,
            permitted_tiers=(RoutingTier.T1, RoutingTier.T2, RoutingTier.T3),
            preferred_tier=RoutingTier.T2,
            validator_tier=RoutingTier.T1,
            confidence_policy="calibrated_decision",
            escalation_on=(FailureKind.INSUFFICIENT_EVIDENCE,),
            fallback_chain=("rank@1.0.0",),
        ),
    )


BUILTIN_FACTORIES = (
    _define,
    _search,
    _fetch,
    _extract,
    _summarize,
    _report,
    _verify,
    _calculate,
    _check,
    _decompose,
    _hypothesize,
    _compare,
    _rank,
    _challenge,
    _choose,
)


def load_builtin_registry() -> Registry:
    registry = Registry()
    for factory in BUILTIN_FACTORIES:
        registry.register(factory())
    return registry
