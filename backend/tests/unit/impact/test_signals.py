"""Unit tests for app.impact.signals — each signal computed independently,
with normalization and weighting verified explicitly."""

import pytest

from app.core.config import Settings
from app.domain.impact.enums import ImpactSignalType, TestRelationshipStatus
from app.impact.signals import SignalInputs, compute_signals


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        impact_weight_direct_callers=15.0,
        impact_weight_transitive_dependents=15.0,
        impact_weight_affected_files=10.0,
        impact_weight_api_exposure=20.0,
        impact_weight_cross_module=10.0,
        impact_weight_external_dependency=5.0,
        impact_weight_inheritance=10.0,
        impact_weight_centrality=10.0,
        impact_weight_test_signal=5.0,
        impact_reference_direct_callers=5.0,
        impact_reference_transitive_dependents=15.0,
        impact_reference_affected_files=8.0,
        impact_reference_api_endpoints=2.0,
        impact_reference_cross_module=5.0,
        impact_reference_external_dependencies=3.0,
        impact_reference_inheritance=3.0,
        impact_reference_centrality=10.0,
    )


def _zero_inputs(**overrides: object) -> SignalInputs:
    base = dict(
        direct_caller_count=0,
        transitive_dependent_count=0,
        affected_file_count=0,
        affected_module_count=0,
        api_endpoint_count=0,
        cross_module_dependent_count=0,
        external_dependency_count=0,
        inheritance_impact_count=0,
        centrality_in_degree=0,
        centrality_out_degree=0,
        test_relationship_status=TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES,
    )
    base.update(overrides)
    return SignalInputs(**base)  # type: ignore[arg-type]


def _signal(signals, signal_type: ImpactSignalType):
    return next(s for s in signals if s.signal_type is signal_type)


class TestZeroImpact:
    def test_all_signals_are_zero_or_documented_baseline(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(), settings)
        for signal in signals:
            if signal.signal_type is ImpactSignalType.RELATED_TEST_SIGNAL:
                # No known tests -> higher-risk baseline (documented design decision).
                assert signal.raw_value == 1.0
            else:
                assert signal.raw_value == 0.0
                assert signal.contribution == 0.0


class TestDirectCallerCount:
    def test_raw_normalized_and_contribution(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(direct_caller_count=5), settings)
        signal = _signal(signals, ImpactSignalType.DIRECT_CALLER_COUNT)
        assert signal.raw_value == 5.0
        assert signal.normalized_value == 1.0  # 5 / reference(5) == 1.0
        assert signal.contribution == 15.0

    def test_normalization_caps_at_one(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(direct_caller_count=500), settings)
        signal = _signal(signals, ImpactSignalType.DIRECT_CALLER_COUNT)
        assert signal.normalized_value == 1.0
        assert signal.contribution == 15.0


class TestTransitiveDependentCount:
    def test_partial_normalization(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(transitive_dependent_count=15), settings)
        signal = _signal(signals, ImpactSignalType.TRANSITIVE_DEPENDENT_COUNT)
        assert signal.normalized_value == 1.0
        assert signal.contribution == 15.0


class TestAffectedFileCount:
    def test_half_reference(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(affected_file_count=4), settings)
        signal = _signal(signals, ImpactSignalType.AFFECTED_FILE_COUNT)
        assert signal.normalized_value == pytest.approx(0.5)
        assert signal.contribution == pytest.approx(5.0)


class TestAffectedModuleCount:
    def test_is_informational_only_zero_weight(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(affected_module_count=10), settings)
        signal = _signal(signals, ImpactSignalType.AFFECTED_MODULE_COUNT)
        assert signal.contribution == 0.0


class TestPublicApiExposure:
    def test_two_endpoints_saturates_reference(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(api_endpoint_count=2), settings)
        signal = _signal(signals, ImpactSignalType.PUBLIC_API_EXPOSURE)
        assert signal.normalized_value == 1.0
        assert signal.contribution == 20.0


class TestCrossModuleDependency:
    def test_contribution(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(cross_module_dependent_count=5), settings)
        signal = _signal(signals, ImpactSignalType.CROSS_MODULE_DEPENDENCY)
        assert signal.contribution == 10.0


class TestExternalDependencyInteraction:
    def test_contribution(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(external_dependency_count=3), settings)
        signal = _signal(signals, ImpactSignalType.EXTERNAL_DEPENDENCY_INTERACTION)
        assert signal.contribution == 5.0


class TestInheritanceImpact:
    def test_contribution(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(inheritance_impact_count=3), settings)
        signal = _signal(signals, ImpactSignalType.INHERITANCE_IMPACT)
        assert signal.contribution == 10.0


class TestGraphCentrality:
    def test_in_and_out_degree_sum(self, settings: Settings) -> None:
        signals = compute_signals(
            _zero_inputs(centrality_in_degree=4, centrality_out_degree=6), settings
        )
        signal = _signal(signals, ImpactSignalType.GRAPH_CENTRALITY)
        assert signal.raw_value == 10.0
        assert signal.normalized_value == 1.0
        assert signal.contribution == 10.0


class TestRelatedTestSignal:
    def test_known_tests_reduce_the_signal(self, settings: Settings) -> None:
        signals = compute_signals(
            _zero_inputs(test_relationship_status=TestRelationshipStatus.KNOWN_RELATED_TESTS),
            settings,
        )
        signal = _signal(signals, ImpactSignalType.RELATED_TEST_SIGNAL)
        assert signal.raw_value == 0.0
        assert signal.contribution == 0.0

    def test_unknown_status_is_treated_like_no_known_tests(self, settings: Settings) -> None:
        signals = compute_signals(
            _zero_inputs(test_relationship_status=TestRelationshipStatus.UNKNOWN), settings
        )
        signal = _signal(signals, ImpactSignalType.RELATED_TEST_SIGNAL)
        assert signal.raw_value == 1.0
        assert signal.contribution == 5.0


class TestExplanationsArePresent:
    def test_every_signal_has_a_nonempty_explanation(self, settings: Settings) -> None:
        signals = compute_signals(_zero_inputs(direct_caller_count=2), settings)
        for signal in signals:
            assert signal.explanation
