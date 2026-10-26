"""Unit tests for app.impact.analyzer — the deterministic core that ties
traversal + aggregation + signals + risk scoring together. Uses
FakeNeo4jClient (see conftest.py); each test queues execute_read results
in the exact order analyze_impact calls them for the given target type:

FUNCTION/API_ENDPOINT target: callers, callees, endpoints,
    external(direct), external(via_file), centrality
CLASS target: callers, callees, endpoints, inheriting_classes,
    base_classes, external(direct), external(via_file), centrality
METHOD target: callers, callees, endpoints, owning_class,
    [inheriting_classes, base_classes if an owner was found],
    external(direct), external(via_file), centrality
"""

import dataclasses

import pytest

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel
from app.domain.graph.models import GraphNode
from app.domain.impact.enums import ImpactTargetType, ImpactType, RiskLevel, TestRelationshipStatus
from app.impact.analyzer import analyze_impact
from tests.unit.impact.conftest import FakeNeo4jClient


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        impact_default_depth=2,
        impact_max_depth=5,
        impact_default_max_nodes=200,
        impact_max_nodes=1000,
        impact_max_paths=100,
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
        impact_risk_medium_threshold=25.0,
        impact_risk_high_threshold=50.0,
        impact_risk_critical_threshold=75.0,
    )


def _target(
    *,
    symbol_id: str = "t1",
    label: NodeLabel = NodeLabel.FUNCTION,
    qualified_name: str = "pkg.target",
) -> GraphNode:
    return GraphNode(
        id=symbol_id,
        repository_id="repo-1",
        label=label,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        file_path="pkg/target_module.py",
        start_line=10,
        end_line=20,
    )


def _no_op_client(*, function_target: bool = True) -> FakeNeo4jClient:
    """No callers/callees/endpoints/external deps, zero centrality."""
    queue = [[], []]  # callers, callees
    queue.append([])  # endpoints
    queue += [[], []]  # external direct, via_file
    queue.append([{"in_degree": 0, "out_degree": 0}])  # centrality
    return FakeNeo4jClient(queue)


def _run_function(client: FakeNeo4jClient, settings: Settings, **kwargs):
    return analyze_impact(
        client,
        settings,
        repository_id="repo-1",
        target_node=_target(),
        target_type=ImpactTargetType.FUNCTION,
        **kwargs,
    )


class TestNoCallers:
    def test_zero_impact_is_low_risk(self, settings: Settings) -> None:
        client = _no_op_client()
        result = _run_function(client, settings)
        assert result.direct_callers == []
        assert result.transitive_dependents == []
        assert result.risk_level is RiskLevel.LOW
        assert result.total_impacted_symbols == 0
        assert result.test_relationship_status is TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES


class TestDirectCallers:
    def test_one_direct_caller(self, settings: Settings, fake_node_factory) -> None:
        caller = fake_node_factory(id="c1", qualified_name="pkg.caller", label="Function")
        queue = [
            [
                {
                    "caller": caller,
                    "distance": 1,
                    "path_names": ["pkg.caller", "pkg.target"],
                    "path_ids": ["c1", "t1"],
                }
            ],
            [],  # callees
            [],  # endpoints
            [],
            [],  # external
            [{"in_degree": 1, "out_degree": 0}],  # centrality
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert len(result.direct_callers) == 1
        assert result.direct_callers[0].qualified_name == "pkg.caller"
        assert result.direct_callers[0].impact_type is ImpactType.DIRECT_CALLER
        assert result.direct_callers[0].reason

    def test_multiple_direct_callers(self, settings: Settings, fake_node_factory) -> None:
        c1 = fake_node_factory(id="c1", qualified_name="pkg.c1", label="Function")
        c2 = fake_node_factory(id="c2", qualified_name="pkg.c2", label="Function")
        queue = [
            [
                {
                    "caller": c1,
                    "distance": 1,
                    "path_names": ["pkg.c1", "pkg.target"],
                    "path_ids": ["c1", "t1"],
                },
                {
                    "caller": c2,
                    "distance": 1,
                    "path_names": ["pkg.c2", "pkg.target"],
                    "path_ids": ["c2", "t1"],
                },
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 2, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert len(result.direct_callers) == 2
        assert {s.qualified_name for s in result.direct_callers} == {"pkg.c1", "pkg.c2"}


class TestTransitiveChainAndDiamond:
    def test_transitive_caller_chain(self, settings: Settings, fake_node_factory) -> None:
        direct = fake_node_factory(id="c1", qualified_name="pkg.c1", label="Function")
        transitive = fake_node_factory(id="c2", qualified_name="pkg.c2", label="Function")
        queue = [
            [
                {
                    "caller": direct,
                    "distance": 1,
                    "path_names": ["pkg.c1", "pkg.target"],
                    "path_ids": ["c1", "t1"],
                },
                {
                    "caller": transitive,
                    "distance": 2,
                    "path_names": ["pkg.c2", "pkg.c1", "pkg.target"],
                    "path_ids": ["c2", "c1", "t1"],
                },
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 1, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert [s.qualified_name for s in result.direct_callers] == ["pkg.c1"]
        assert [s.qualified_name for s in result.transitive_dependents] == ["pkg.c2"]
        assert result.transitive_dependents[0].impact_type is ImpactType.TRANSITIVE_CALLER
        assert result.transitive_dependents[0].path == ["pkg.c2", "pkg.c1", "pkg.target"]

    def test_diamond_shaped_graph_dedupes_to_one_entry_at_min_distance(
        self, settings: Settings, fake_node_factory
    ) -> None:
        """A -> B -> target and A -> target directly: A should appear once,
        at its minimum (direct) distance."""
        a = fake_node_factory(id="a", qualified_name="pkg.a", label="Function")
        queue = [
            [
                {
                    "caller": a,
                    "distance": 1,
                    "path_names": ["pkg.a", "pkg.target"],
                    "path_ids": ["a", "t1"],
                },
                {
                    "caller": a,
                    "distance": 2,
                    "path_names": ["pkg.a", "pkg.b", "pkg.target"],
                    "path_ids": ["a", "b", "t1"],
                },
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 1, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        all_dependents = result.direct_callers + result.transitive_dependents
        assert len(all_dependents) == 1
        assert all_dependents[0].distance == 1


class TestCycleSafety:
    def test_cycle_within_a_path_is_detected_and_does_not_crash(
        self, settings: Settings, fake_node_factory
    ) -> None:
        """A -> B -> A -> target: path_ids repeats node 'a', simulating what
        a real cyclic graph (A calls B, B calls A, A calls target) would
        produce for one bounded path — must terminate normally and record
        the cycle in diagnostics, never loop."""
        a = fake_node_factory(id="a", qualified_name="pkg.a", label="Function")
        queue = [
            [
                {
                    "caller": a,
                    "distance": 3,
                    "path_names": ["pkg.a", "pkg.b", "pkg.a", "pkg.target"],
                    "path_ids": ["a", "b", "a", "t1"],
                }
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 1, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert result.diagnostics.cycles_detected == 1
        assert len(result.transitive_dependents) == 1


class TestDepthParameter:
    def test_depth_1_is_honored_in_result_and_query(self, settings: Settings) -> None:
        client = _no_op_client()
        result = _run_function(client, settings, max_depth=1)
        assert result.traversal_depth == 1
        assert "*1..1" in client.queries[0]

    def test_depth_2_is_honored(self, settings: Settings) -> None:
        client = _no_op_client()
        result = _run_function(client, settings, max_depth=2)
        assert result.traversal_depth == 2

    def test_maximum_allowed_depth(self, settings: Settings) -> None:
        client = _no_op_client()
        result = _run_function(client, settings, max_depth=5)
        assert result.traversal_depth == 5

    def test_depth_above_configured_max_raises(self, settings: Settings) -> None:
        from app.impact.exceptions import InvalidImpactParameterError

        client = _no_op_client()
        with pytest.raises(InvalidImpactParameterError):
            _run_function(client, settings, max_depth=6)


class TestNodeTruncation:
    def test_more_callers_than_max_nodes_are_truncated(
        self, settings: Settings, fake_node_factory
    ) -> None:
        callers = [
            {
                "caller": fake_node_factory(
                    id=f"c{i}", qualified_name=f"pkg.c{i}", label="Function"
                ),
                "distance": 1,
                "path_names": [f"pkg.c{i}", "pkg.target"],
                "path_ids": [f"c{i}", "t1"],
            }
            for i in range(5)
        ]
        queue = [callers, [], [], [], [], [{"in_degree": 5, "out_degree": 0}]]
        result = _run_function(FakeNeo4jClient(queue), settings, max_nodes=3)
        assert len(result.direct_callers) == 3
        assert result.truncated is True
        assert "max_nodes" in (result.diagnostics.truncated_reason or "")


class TestRepositoryIsolation:
    def test_repository_id_is_threaded_through_every_traversal_call(
        self, settings: Settings
    ) -> None:
        client = _no_op_client()
        _run_function(client, settings)
        assert client.params
        for params in client.params:
            assert params.get("repository_id") == "repo-1"


class TestApiExposure:
    def test_target_directly_handles_endpoint(self, settings: Settings, fake_node_factory) -> None:
        endpoint = fake_node_factory(
            id="e1", label="APIEndpoint", name="", http_method="POST", route_path="/login"
        )
        handler = fake_node_factory(id="t1", qualified_name="pkg.target", label="Function")
        queue = [
            [],
            [],
            [{"endpoint": endpoint, "handler": handler, "distance": 0}],
            [],
            [],
            [{"in_degree": 0, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert len(result.affected_endpoints) == 1
        assert result.affected_endpoints[0].distance_from_target == 0
        assert result.affected_endpoints[0].route_path == "/login"

    def test_direct_and_transitive_caller_handling_multiple_endpoints(
        self, settings: Settings, fake_node_factory
    ) -> None:
        e1 = fake_node_factory(
            id="e1", label="APIEndpoint", name="", http_method="GET", route_path="/a"
        )
        e2 = fake_node_factory(
            id="e2", label="APIEndpoint", name="", http_method="POST", route_path="/b"
        )
        h1 = fake_node_factory(id="h1", qualified_name="pkg.h1", label="Function")
        h2 = fake_node_factory(id="h2", qualified_name="pkg.h2", label="Function")
        queue = [
            [],
            [],
            [
                {"endpoint": e1, "handler": h1, "distance": 1},
                {"endpoint": e2, "handler": h2, "distance": 2},
            ],
            [],
            [],
            [{"in_degree": 0, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert {e.route_path for e in result.affected_endpoints} == {"/a", "/b"}

    def test_duplicate_paths_to_same_endpoint_are_not_duplicated(
        self, settings: Settings, fake_node_factory
    ) -> None:
        endpoint = fake_node_factory(
            id="e1", label="APIEndpoint", name="", http_method="GET", route_path="/a"
        )
        h1 = fake_node_factory(id="h1", qualified_name="pkg.h1", label="Function")
        queue = [
            [],
            [],
            [
                {"endpoint": endpoint, "handler": h1, "distance": 2},
                {"endpoint": endpoint, "handler": h1, "distance": 1},
            ],
            [],
            [],
            [{"in_degree": 0, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert len(result.affected_endpoints) == 1
        assert result.affected_endpoints[0].distance_from_target == 1


class TestFileAndModuleAggregation:
    def test_multiple_symbols_in_same_file_and_across_files(
        self, settings: Settings, fake_node_factory
    ) -> None:
        c1 = fake_node_factory(
            id="c1", qualified_name="pkg.mod.c1", label="Function", file_path="pkg/mod.py"
        )
        c2 = fake_node_factory(
            id="c2", qualified_name="pkg.mod.c2", label="Function", file_path="pkg/mod.py"
        )
        c3 = fake_node_factory(
            id="c3", qualified_name="pkg.other.c3", label="Function", file_path="pkg/other.py"
        )
        queue = [
            [
                {
                    "caller": c1,
                    "distance": 1,
                    "path_names": ["pkg.mod.c1", "pkg.target"],
                    "path_ids": ["c1", "t1"],
                },
                {
                    "caller": c2,
                    "distance": 1,
                    "path_names": ["pkg.mod.c2", "pkg.target"],
                    "path_ids": ["c2", "t1"],
                },
                {
                    "caller": c3,
                    "distance": 2,
                    "path_names": ["pkg.other.c3", "pkg.mod.c1", "pkg.target"],
                    "path_ids": ["c3", "c1", "t1"],
                },
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 2, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        files_by_path = {f.file_path: f for f in result.affected_files}
        assert files_by_path["pkg/mod.py"].affected_symbol_count == 2
        assert files_by_path["pkg/mod.py"].minimum_distance == 1
        assert files_by_path["pkg/other.py"].affected_symbol_count == 1
        modules_by_name = {m.module_name: m for m in result.affected_modules}
        assert modules_by_name["pkg.mod"].affected_symbol_count == 2
        assert modules_by_name["pkg.other"].affected_symbol_count == 1
        # cross-module signal: pkg.other differs from target's own module pkg
        assert any(
            s.signal_type.name == "CROSS_MODULE_DEPENDENCY" and s.raw_value >= 1
            for s in result.risk_signals
        )


class TestInheritance:
    def test_class_target_with_child_and_base(self, settings: Settings, fake_node_factory) -> None:
        child = fake_node_factory(id="child1", qualified_name="pkg.Child", label="Class")
        base = fake_node_factory(id="base1", qualified_name="pkg.Base", label="Class")
        queue = [
            [],  # callers
            [],  # callees
            [],  # endpoints
            [{"child": child, "distance": 1}],  # inheriting classes
            [{"base": base, "distance": 1}],  # base classes
            [],
            [],  # external
            [{"in_degree": 0, "out_degree": 0}],
        ]
        result = analyze_impact(
            FakeNeo4jClient(queue),
            settings,
            repository_id="repo-1",
            target_node=_target(
                symbol_id="cls1", label=NodeLabel.CLASS, qualified_name="pkg.Target"
            ),
            target_type=ImpactTargetType.CLASS,
        )
        assert [s.qualified_name for s in result.inheriting_classes] == ["pkg.Child"]
        assert [s.qualified_name for s in result.base_classes] == ["pkg.Base"]
        assert len(result.inheritance_impacts) == 2

    def test_class_target_with_no_inheritance(self, settings: Settings) -> None:
        queue = [[], [], [], [], [], [], [], [{"in_degree": 0, "out_degree": 0}]]
        result = analyze_impact(
            FakeNeo4jClient(queue),
            settings,
            repository_id="repo-1",
            target_node=_target(
                symbol_id="cls1", label=NodeLabel.CLASS, qualified_name="pkg.Target"
            ),
            target_type=ImpactTargetType.CLASS,
        )
        assert result.inheriting_classes == []
        assert result.base_classes == []

    def test_method_target_surfaces_impact_via_owning_class(
        self, settings: Settings, fake_node_factory
    ) -> None:
        owner = fake_node_factory(id="cls1", qualified_name="pkg.Owner", label="Class")
        child = fake_node_factory(id="child1", qualified_name="pkg.Child", label="Class")
        queue = [
            [],  # callers
            [],  # callees
            [],  # endpoints
            [{"owner": owner}],  # get_owning_class
            [{"child": child, "distance": 1}],  # inheriting_classes
            [],  # base_classes
            [],
            [],  # external
            [{"in_degree": 0, "out_degree": 0}],
        ]
        result = analyze_impact(
            FakeNeo4jClient(queue),
            settings,
            repository_id="repo-1",
            target_node=_target(
                symbol_id="m1", label=NodeLabel.METHOD, qualified_name="pkg.Owner.method"
            ),
            target_type=ImpactTargetType.METHOD,
        )
        assert [s.qualified_name for s in result.inheriting_classes] == ["pkg.Child"]
        assert "Polymorphic dispatch" in " ".join(result.limitations)

    def test_method_target_with_no_owning_class_skips_inheritance_queries(
        self, settings: Settings
    ) -> None:
        # callers, callees, endpoints, owning_class(empty->None), ext_direct,
        # ext_via_file, centrality — inheriting_classes/base_classes queries
        # are never issued since no owning class was found.
        queue = [[], [], [], [], [], [], [{"in_degree": 0, "out_degree": 0}]]
        result = analyze_impact(
            FakeNeo4jClient(queue),
            settings,
            repository_id="repo-1",
            target_node=_target(
                symbol_id="m1", label=NodeLabel.METHOD, qualified_name="pkg.orphan_method"
            ),
            target_type=ImpactTargetType.METHOD,
        )
        assert result.inheriting_classes == []
        assert result.base_classes == []


class TestTestReferences:
    def test_known_test_caller_is_reported(self, settings: Settings, fake_node_factory) -> None:
        test_caller = fake_node_factory(
            id="tc1",
            qualified_name="tests.test_target.test_it",
            label="Function",
            file_path="tests/test_target.py",
        )
        queue = [
            [
                {
                    "caller": test_caller,
                    "distance": 1,
                    "path_names": ["tests.test_target.test_it", "pkg.target"],
                    "path_ids": ["tc1", "t1"],
                }
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 1, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert result.test_relationship_status is TestRelationshipStatus.KNOWN_RELATED_TESTS
        assert len(result.related_tests) == 1

    def test_non_test_caller_yields_no_known_references(
        self, settings: Settings, fake_node_factory
    ) -> None:
        caller = fake_node_factory(id="c1", qualified_name="pkg.c1", label="Function")
        queue = [
            [
                {
                    "caller": caller,
                    "distance": 1,
                    "path_names": ["pkg.c1", "pkg.target"],
                    "path_ids": ["c1", "t1"],
                }
            ],
            [],
            [],
            [],
            [],
            [{"in_degree": 1, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert result.test_relationship_status is TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES

    def test_include_tests_false_yields_unknown(self, settings: Settings) -> None:
        client = _no_op_client()
        result = _run_function(client, settings, include_tests=False)
        assert result.test_relationship_status is TestRelationshipStatus.UNKNOWN
        assert "Test-reference detection was skipped" in " ".join(result.limitations)


class TestDeterminism:
    def test_repeated_analysis_with_identical_data_is_identical(
        self, settings: Settings, fake_node_factory
    ) -> None:
        def build_queue() -> list:
            caller = fake_node_factory(id="c1", qualified_name="pkg.c1", label="Function")
            return [
                [
                    {
                        "caller": caller,
                        "distance": 1,
                        "path_names": ["pkg.c1", "pkg.target"],
                        "path_ids": ["c1", "t1"],
                    }
                ],
                [],
                [],
                [],
                [],
                [{"in_degree": 1, "out_degree": 0}],
            ]

        first = _run_function(FakeNeo4jClient(build_queue()), settings)
        second = _run_function(FakeNeo4jClient(build_queue()), settings)

        strip = lambda r: dataclasses.replace(  # noqa: E731
            r, diagnostics=dataclasses.replace(r.diagnostics, analysis_duration_ms=0)
        )
        assert strip(first) == strip(second)


class TestDownstreamDependencies:
    def test_downstream_dependencies_are_kept_separate_from_upstream(
        self, settings: Settings, fake_node_factory
    ) -> None:
        callee = fake_node_factory(id="d1", qualified_name="pkg.dep", label="Function")
        queue = [
            [],  # callers
            [
                {
                    "callee": callee,
                    "distance": 1,
                    "path_names": ["pkg.target", "pkg.dep"],
                    "path_ids": ["t1", "d1"],
                }
            ],
            [],
            [],
            [],
            [{"in_degree": 0, "out_degree": 1}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert result.direct_callers == []
        assert len(result.downstream_dependencies) == 1
        assert result.downstream_dependencies[0].qualified_name == "pkg.dep"
        assert result.downstream_dependencies[0].impact_type is ImpactType.CALLEE

    def test_include_downstream_false_skips_callee_query(self, settings: Settings) -> None:
        queue = [[], [], [], []]  # callers, endpoints, external x2 (no callees query!)
        queue.append([{"in_degree": 0, "out_degree": 0}])
        client = FakeNeo4jClient(queue)
        result = _run_function(client, settings, include_downstream=False)
        assert result.downstream_dependencies == []
        assert "Downstream dependency analysis was skipped" in " ".join(result.limitations)


class TestRiskLevels:
    def test_high_direct_caller_and_api_exposure_pushes_risk_up(
        self, settings: Settings, fake_node_factory
    ) -> None:
        callers = [
            {
                "caller": fake_node_factory(
                    id=f"c{i}", qualified_name=f"pkg.c{i}", label="Function"
                ),
                "distance": 1,
                "path_names": [f"pkg.c{i}", "pkg.target"],
                "path_ids": [f"c{i}", "t1"],
            }
            for i in range(5)
        ]
        endpoint = fake_node_factory(
            id="e1", label="APIEndpoint", name="", http_method="POST", route_path="/x"
        )
        handler = fake_node_factory(id="c0", qualified_name="pkg.c0", label="Function")
        queue = [
            callers,
            [],
            [{"endpoint": endpoint, "handler": handler, "distance": 1}],
            [],
            [],
            [{"in_degree": 5, "out_degree": 0}],
        ]
        result = _run_function(FakeNeo4jClient(queue), settings)
        assert result.risk_score > 0
        assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
        total_contribution = sum(s.contribution for s in result.risk_signals)
        assert result.risk_score == pytest.approx(min(total_contribution, 100.0))
