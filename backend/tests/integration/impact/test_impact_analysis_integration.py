"""Integration tests for the deterministic change-impact-analysis engine
against a real Neo4j — see the impact-analysis task's "Integration
tests". Requires a reachable Neo4j (see conftest.py); every test in this
module is skipped with a visible reason otherwise — never faked.
"""

from tests.integration.impact.conftest import SampleRepository

from app.core.config import get_settings
from app.domain.impact.enums import ImpactTargetType, TestRelationshipStatus
from app.impact.analyzer import analyze_impact


def _login_target(sample: SampleRepository, neo4j_client):
    from app.impact import service as impact_service

    return impact_service.resolve_target(
        neo4j_client,
        get_settings(),
        repository_id=sample.repository_id,
        symbol_id=sample.symbol_ids["app.api.login"],
        qualified_name=None,
    )


class TestDirectAndTransitiveCallers:
    def test_login_has_expected_direct_callers(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
        )
        direct_names = {s.qualified_name for s in result.direct_callers}
        # Three real callers, not two: tests/test_api.py's test_login_succeeds
        # (see conftest.py's _TEST_SOURCE) also calls login(...) directly, so
        # it's a genuine direct caller — direct_callers intentionally includes
        # test-file callers (see app.impact.aggregator.classify_test_references,
        # whose own docstring says related_tests is drawn *from* direct/
        # transitive callers, not a separate detection path; TestTestReferenceDetection
        # below asserts exactly that subset relationship).
        assert direct_names == {
            "app.api.authentication_service",
            "app.api.admin_login",
            "tests.test_api.test_login_succeeds",
        }

    def test_transitive_caller_includes_api_handler(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        transitive_names = {s.qualified_name for s in result.transitive_dependents}
        assert "app.api.login_endpoint" in transitive_names


class TestApiEndpointImpact:
    def test_post_login_appears_as_affected_endpoint(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        assert len(result.affected_endpoints) == 1
        endpoint = result.affected_endpoints[0]
        assert endpoint.http_method == "POST"
        assert endpoint.route_path == "/login"
        assert endpoint.handler_qualified_name == "app.api.login_endpoint"


class TestAffectedFilesDeduplication:
    def test_affected_files_are_deduplicated(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        file_paths = [f.file_path for f in result.affected_files]
        assert len(file_paths) == len(set(file_paths))
        assert "app/api.py" in file_paths


class TestDownstreamDependenciesSeparate:
    def test_downstream_dependencies_are_not_mixed_with_dependents(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
        )
        downstream_names = {s.qualified_name for s in result.downstream_dependencies}
        dependent_names = {s.qualified_name for s in result.direct_callers}
        assert "app.api.find_by_email" in downstream_names
        assert downstream_names.isdisjoint(dependent_names)


class TestDeterminism:
    def test_repeated_analysis_returns_identical_result(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        kwargs = dict(
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        first = analyze_impact(neo4j_client, get_settings(), **kwargs)
        second = analyze_impact(neo4j_client, get_settings(), **kwargs)

        assert first.risk_score == second.risk_score
        assert first.risk_level == second.risk_level
        assert {s.qualified_name for s in first.direct_callers} == {
            s.qualified_name for s in second.direct_callers
        }
        assert {s.qualified_name for s in first.transitive_dependents} == {
            s.qualified_name for s in second.transitive_dependents
        }
        assert len(first.affected_endpoints) == len(second.affected_endpoints)


class TestRepositoryIsolation:
    def test_second_repository_remains_isolated(
        self,
        neo4j_client,
        sample_repository: SampleRepository,
        second_sample_repository: SampleRepository,
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        # Every impacted symbol/file must belong to THIS repository's own
        # symbol_id set — never leak the second repository's identical
        # qualified_name/file_path graph.
        all_ids = {s.symbol_id for s in result.direct_callers + result.transitive_dependents}
        assert all_ids.issubset(set(sample_repository.symbol_ids.values()))
        assert all_ids.isdisjoint(set(second_sample_repository.symbol_ids.values()))


class TestGraphCycleSafety:
    def test_cycle_does_not_break_traversal(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        from app.impact import service as impact_service

        target = impact_service.resolve_target(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            symbol_id=sample_repository.symbol_ids["app.api.cyclic_a"],
            qualified_name=None,
        )
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=5,
        )
        # Must terminate and return a small, bounded result — never hang
        # or raise on the 3-node cyclic_a -> cyclic_b -> cyclic_c -> cyclic_a chain.
        assert result.diagnostics.analysis_duration_ms < 30_000
        direct_names = {s.qualified_name for s in result.direct_callers}
        assert direct_names == {"app.api.cyclic_c"}


class TestMaxDepthChangesResult:
    def test_shallow_depth_misses_transitive_endpoint(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        shallow = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=1,
        )
        deep = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
            max_depth=3,
        )
        assert shallow.affected_endpoints == []
        assert len(deep.affected_endpoints) == 1
        assert shallow.transitive_dependents == []
        assert any(s.qualified_name == "app.api.login_endpoint" for s in deep.transitive_dependents)


class TestInheritanceImpact:
    def test_child_class_is_reported_as_inheriting(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        from app.impact import service as impact_service

        target = impact_service.resolve_target(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            symbol_id=sample_repository.symbol_ids["app.api.BaseHandler"],
            qualified_name=None,
        )
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.CLASS,
        )
        assert {s.qualified_name for s in result.inheriting_classes} == {"app.api.LoginHandler"}


class TestExternalDependencySignal:
    def test_login_reports_bcrypt_via_containing_file(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        from app.impact import traversal

        rows = traversal.get_external_dependencies(
            neo4j_client,
            repository_id=sample_repository.repository_id,
            symbol_id=sample_repository.symbol_ids["app.api.login"],
            limit=100,
        )
        assert any(row.node.name == "bcrypt" for row in rows)


class TestTestReferenceDetection:
    def test_status_is_a_known_enum_value_and_conservative(
        self, neo4j_client, sample_repository: SampleRepository
    ) -> None:
        target = _login_target(sample_repository, neo4j_client)
        result = analyze_impact(
            neo4j_client,
            get_settings(),
            repository_id=sample_repository.repository_id,
            target_node=target,
            target_type=ImpactTargetType.FUNCTION,
        )
        assert result.test_relationship_status in (
            TestRelationshipStatus.KNOWN_RELATED_TESTS,
            TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES,
        )
        # Whatever the status, every entry in related_tests (if any) must
        # be backed by a real graph relationship the analyzer already
        # found among direct/transitive callers — never a bare filename
        # match (see app.impact.aggregator.classify_test_references).
        dependent_ids = {s.symbol_id for s in result.direct_callers + result.transitive_dependents}
        assert {s.symbol_id for s in result.related_tests}.issubset(dependent_ids)
