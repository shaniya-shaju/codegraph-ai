"""Unit tests for app.impact.traversal — bounded, repository-scoped
Cypher construction and Record -> domain-model mapping. Uses FakeNeo4jClient
(see conftest.py) so these run without a real Neo4j instance; genuine
graph-cycle/repository-isolation behavior against a real database is
covered separately in tests/integration/impact.
"""

import pytest

from app.core.config import Settings
from app.impact import traversal
from app.impact.exceptions import InvalidImpactParameterError
from tests.unit.impact.conftest import FakeNeo4jClient


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        impact_default_depth=2,
        impact_max_depth=5,
        impact_default_max_nodes=200,
        impact_max_nodes=1000,
        impact_max_paths=100,
    )


class TestValidation:
    def test_depth_within_bounds_is_returned_unchanged(self, settings: Settings) -> None:
        assert traversal.validate_depth(3, settings) == 3

    def test_depth_below_one_raises(self, settings: Settings) -> None:
        with pytest.raises(InvalidImpactParameterError):
            traversal.validate_depth(0, settings)

    def test_depth_above_max_raises(self, settings: Settings) -> None:
        with pytest.raises(InvalidImpactParameterError):
            traversal.validate_depth(6, settings)

    def test_max_nodes_within_bounds_is_returned_unchanged(self, settings: Settings) -> None:
        assert traversal.validate_max_nodes(50, settings) == 50

    def test_max_nodes_below_one_raises(self, settings: Settings) -> None:
        with pytest.raises(InvalidImpactParameterError):
            traversal.validate_max_nodes(0, settings)

    def test_max_nodes_above_max_raises(self, settings: Settings) -> None:
        with pytest.raises(InvalidImpactParameterError):
            traversal.validate_max_nodes(1001, settings)


class TestUpstreamCallers:
    def test_maps_rows_to_path_rows(self, settings: Settings, fake_node_factory) -> None:
        caller = fake_node_factory(id="c1", qualified_name="pkg.caller", label="Function")
        client = FakeNeo4jClient(
            [
                [
                    {
                        "caller": caller,
                        "distance": 1,
                        "path_names": ["pkg.caller", "pkg.target"],
                        "path_ids": ["c1", "t1"],
                    }
                ]
            ]
        )
        rows = traversal.get_upstream_callers(
            client, settings, repository_id="repo-1", symbol_id="t1", max_depth=2, max_paths=100
        )
        assert len(rows) == 1
        assert rows[0].node.qualified_name == "pkg.caller"
        assert rows[0].distance == 1
        assert rows[0].path_ids == ["c1", "t1"]

    def test_query_bounds_depth_and_excludes_target_self(self, settings: Settings) -> None:
        client = FakeNeo4jClient([[]])
        traversal.get_upstream_callers(
            client, settings, repository_id="repo-1", symbol_id="t1", max_depth=3, max_paths=100
        )
        query = client.queries[0]
        assert "*1..3" in query
        assert "caller.id <> $symbol_id" in query
        assert client.params[0]["symbol_id"] == "t1"
        assert client.params[0]["repository_id"] == "repo-1"

    def test_rejects_depth_above_configured_max(self, settings: Settings) -> None:
        client = FakeNeo4jClient([[]])
        with pytest.raises(InvalidImpactParameterError):
            traversal.get_upstream_callers(
                client,
                settings,
                repository_id="repo-1",
                symbol_id="t1",
                max_depth=99,
                max_paths=100,
            )


class TestDownstreamCallees:
    def test_maps_rows_and_bounds_depth(self, settings: Settings, fake_node_factory) -> None:
        callee = fake_node_factory(id="d1", qualified_name="pkg.dep", label="Function")
        client = FakeNeo4jClient(
            [[{"callee": callee, "distance": 1, "path_names": ["x"], "path_ids": ["d1"]}]]
        )
        rows = traversal.get_downstream_callees(
            client, settings, repository_id="repo-1", symbol_id="t1", max_depth=2, max_paths=100
        )
        assert rows[0].node.qualified_name == "pkg.dep"
        assert "*1..2" in client.queries[0]
        assert "callee.id <> $symbol_id" in client.queries[0]


class TestAffectedEndpoints:
    def test_zero_length_path_supports_target_is_handler(
        self, settings: Settings, fake_node_factory
    ) -> None:
        endpoint = fake_node_factory(
            id="e1", label="APIEndpoint", name="", http_method="POST", route_path="/login"
        )
        handler = fake_node_factory(id="t1", qualified_name="pkg.login", label="Function")
        client = FakeNeo4jClient([[{"endpoint": endpoint, "handler": handler, "distance": 0}]])
        rows = traversal.get_affected_endpoints(
            client, settings, repository_id="repo-1", symbol_id="t1", max_depth=2, max_paths=100
        )
        assert rows[0].distance == 0
        assert "*0..2" in client.queries[0]
        assert rows[0].endpoint.properties["route_path"] == "/login"


class TestInheritance:
    def test_inheriting_classes_query_shape(self, settings: Settings, fake_node_factory) -> None:
        child = fake_node_factory(id="c1", label="Class", qualified_name="pkg.Child")
        client = FakeNeo4jClient([[{"child": child, "distance": 1}]])
        rows = traversal.get_inheriting_classes(
            client, settings, repository_id="repo-1", class_id="base1", max_depth=2, max_paths=100
        )
        assert rows[0].node.qualified_name == "pkg.Child"
        assert "EXTENDS*1..2" in client.queries[0]

    def test_base_classes_query_shape(self, settings: Settings, fake_node_factory) -> None:
        base = fake_node_factory(id="b1", label="Class", qualified_name="pkg.Base")
        client = FakeNeo4jClient([[{"base": base, "distance": 1}]])
        rows = traversal.get_base_classes(
            client, settings, repository_id="repo-1", class_id="c1", max_depth=2, max_paths=100
        )
        assert rows[0].node.qualified_name == "pkg.Base"
        assert "EXTENDS*1..2" in client.queries[0]


class TestOwningClass:
    def test_returns_none_when_no_owner_found(self, settings: Settings) -> None:
        client = FakeNeo4jClient([[]])
        assert traversal.get_owning_class(client, repository_id="repo-1", method_id="m1") is None

    def test_returns_mapped_owner(self, fake_node_factory) -> None:
        owner = fake_node_factory(id="cls1", label="Class", qualified_name="pkg.Owner")
        client = FakeNeo4jClient([[{"owner": owner}]])
        node = traversal.get_owning_class(client, repository_id="repo-1", method_id="m1")
        assert node is not None
        assert node.qualified_name == "pkg.Owner"


class TestExternalDependencies:
    def test_dedupes_direct_and_containing_file_results(self, fake_node_factory) -> None:
        dep_direct = fake_node_factory(id="dep1", label="ExternalDependency", name="bcrypt")
        dep_via_file_same = fake_node_factory(id="dep1", label="ExternalDependency", name="bcrypt")
        dep_via_file_new = fake_node_factory(id="dep2", label="ExternalDependency", name="jwt")
        client = FakeNeo4jClient(
            [
                [{"dep": dep_direct}],
                [{"dep": dep_via_file_same}, {"dep": dep_via_file_new}],
            ]
        )
        rows = traversal.get_external_dependencies(
            client, repository_id="repo-1", symbol_id="t1", limit=100
        )
        assert len(rows) == 2
        by_id = {row.node.id: row for row in rows}
        assert by_id["dep1"].via == "direct"
        assert by_id["dep2"].via == "containing_file"


class TestLocalCentrality:
    def test_returns_in_and_out_degree(self, settings: Settings) -> None:
        client = FakeNeo4jClient([[{"in_degree": 3, "out_degree": 5}]])
        in_degree, out_degree = traversal.get_local_centrality(
            client, repository_id="repo-1", symbol_id="t1"
        )
        assert (in_degree, out_degree) == (3, 5)

    def test_returns_zero_zero_when_no_records(self, settings: Settings) -> None:
        client = FakeNeo4jClient([[]])
        assert traversal.get_local_centrality(client, repository_id="repo-1", symbol_id="t1") == (
            0,
            0,
        )
