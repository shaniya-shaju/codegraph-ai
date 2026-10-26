"""Graph retriever adapter — mocks app.graph.repository_graph_service
entirely (no real Neo4j) and verifies callers/callees/neighbors/
dependencies/inheritance/bounded-depth behavior."""

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, RelationshipType, SymbolMatchType
from app.domain.graph.models import (
    GraphEdge,
    GraphNode,
    GraphStatistics,
    GraphSubgraph,
    SymbolSearchResult,
)
from app.domain.rag.enums import EvidenceType, GraphRetrievalOperation
from app.rag.graph_retriever import GraphRetriever


def _node(
    node_id: str,
    label: NodeLabel = NodeLabel.FUNCTION,
    name: str = "login",
    qualified_name: str = "app.auth.login",
) -> GraphNode:
    return GraphNode(
        id=node_id,
        repository_id="repo-1",
        label=label,
        name=name,
        qualified_name=qualified_name,
        file_path="app/auth.py",
        start_line=1,
        end_line=5,
    )


def _edge(edge_id: str, source_id: str, target_id: str, rel_type: RelationshipType) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        repository_id="repo-1",
        source_id=source_id,
        target_id=target_id,
        relationship_type=rel_type,
    )


class _FakeGraphService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.symbol_result: GraphNode | None = None
        self.callers_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        )
        self.callees_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        )
        self.dependencies_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        )
        self.neighbors_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        )
        self.overview_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        )
        self.search_results: list[SymbolSearchResult] = []
        self.statistics_result = GraphStatistics(
            repository_id="repo-1",
            node_counts={},
            relationship_counts={},
            unresolved_call_count=0,
            parse_error_count=0,
        )
        self.path_result = GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=1
        )

    def _record(self, name: str, **kwargs: object) -> None:
        self.calls.append((name, kwargs))

    def search_symbols(
        self,
        client,
        settings,
        *,
        repository_id,
        query,
        symbol_type=None,
        file_path=None,
        limit=None,
    ):
        self._record("search_symbols", query=query, symbol_type=symbol_type, limit=limit)
        return self.search_results

    def get_symbol(self, client, *, repository_id, symbol_id):
        self._record("get_symbol", symbol_id=symbol_id)
        return self.symbol_result

    def get_callers(self, client, settings, *, repository_id, symbol_id, limit=None):
        self._record("get_callers", symbol_id=symbol_id, limit=limit)
        return self.callers_result

    def get_callees(self, client, settings, *, repository_id, symbol_id, limit=None):
        self._record("get_callees", symbol_id=symbol_id, limit=limit)
        return self.callees_result

    def get_dependencies(self, client, settings, *, repository_id, symbol_id, limit=None):
        self._record("get_dependencies", symbol_id=symbol_id, limit=limit)
        return self.dependencies_result

    def get_symbol_neighbors(
        self, client, settings, *, repository_id, symbol_id, depth=None, limit=None
    ):
        self._record("get_symbol_neighbors", symbol_id=symbol_id, depth=depth, limit=limit)
        return self.neighbors_result

    def get_repository_overview(self, client, settings, *, repository_id, depth=None, limit=None):
        self._record("get_repository_overview", depth=depth, limit=limit)
        return self.overview_result

    def find_path(
        self, client, settings, *, repository_id, source_symbol_id, target_symbol_id, max_depth=None
    ):
        self._record(
            "find_path",
            source_symbol_id=source_symbol_id,
            target_symbol_id=target_symbol_id,
            max_depth=max_depth,
        )
        return self.path_result

    def get_statistics(self, client, *, repository_id):
        self._record("get_statistics")
        return self.statistics_result


def _retriever(fake: _FakeGraphService) -> GraphRetriever:
    return GraphRetriever(client=None, settings=Settings(), graph_service=fake)  # type: ignore[arg-type]


class TestSymbolDetails:
    def test_returns_one_evidence_item_for_the_node(self) -> None:
        fake = _FakeGraphService()
        fake.symbol_result = _node("s1")
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.SYMBOL_DETAILS, repository_id="repo-1", symbol_id="s1"
        )
        assert len(evidence) == 1
        assert evidence[0].symbol_id == "s1"
        assert evidence[0].graph_distance == 0

    def test_no_node_found_returns_empty(self) -> None:
        fake = _FakeGraphService()
        fake.symbol_result = None
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.SYMBOL_DETAILS, repository_id="repo-1", symbol_id="missing"
        )
        assert evidence == []


class TestCallers:
    def test_returns_one_evidence_item_per_caller(self) -> None:
        fake = _FakeGraphService()
        caller = _node("c1", name="handler")
        fake.callers_result = GraphSubgraph(
            nodes=[caller],
            edges=[_edge("e1", "c1", "s1", RelationshipType.CALLS)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.CALLERS, repository_id="repo-1", symbol_id="s1"
        )
        assert len(evidence) == 1
        assert evidence[0].evidence_type is EvidenceType.CALL_RELATIONSHIP
        assert evidence[0].relationship_type == "CALLS"
        assert evidence[0].graph_distance == 1

    def test_no_symbol_id_returns_empty(self) -> None:
        fake = _FakeGraphService()
        assert (
            _retriever(fake).run(
                GraphRetrievalOperation.CALLERS, repository_id="repo-1", symbol_id=None
            )
            == []
        )


class TestCallees:
    def test_returns_one_evidence_item_per_callee(self) -> None:
        fake = _FakeGraphService()
        callee = _node("c2", name="validate")
        fake.callees_result = GraphSubgraph(
            nodes=[callee],
            edges=[_edge("e2", "s1", "c2", RelationshipType.CALLS)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.CALLEES, repository_id="repo-1", symbol_id="s1"
        )
        assert len(evidence) == 1
        assert evidence[0].symbol_id == "c2"


class TestDependencies:
    def test_extends_edge_maps_to_inheritance_relationship_type(self) -> None:
        fake = _FakeGraphService()
        parent = _node("p1", label=NodeLabel.CLASS, name="Base")
        fake.dependencies_result = GraphSubgraph(
            nodes=[parent],
            edges=[_edge("e3", "s1", "p1", RelationshipType.EXTENDS)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.DEPENDENCIES, repository_id="repo-1", symbol_id="s1"
        )
        assert evidence[0].evidence_type is EvidenceType.INHERITANCE_RELATIONSHIP

    def test_depends_on_edge_maps_to_dependency_relationship_type(self) -> None:
        fake = _FakeGraphService()
        dep = _node("d1", label=NodeLabel.EXTERNAL_DEPENDENCY, name="requests")
        fake.dependencies_result = GraphSubgraph(
            nodes=[dep],
            edges=[_edge("e4", "s1", "d1", RelationshipType.DEPENDS_ON)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.DEPENDENCIES, repository_id="repo-1", symbol_id="s1"
        )
        assert evidence[0].evidence_type is EvidenceType.DEPENDENCY_RELATIONSHIP


class TestInheritance:
    def test_filters_out_non_extends_edges(self) -> None:
        fake = _FakeGraphService()
        parent = _node("p1", label=NodeLabel.CLASS, name="Base")
        dep = _node("d1", label=NodeLabel.EXTERNAL_DEPENDENCY, name="requests")
        fake.dependencies_result = GraphSubgraph(
            nodes=[parent, dep],
            edges=[
                _edge("e3", "s1", "p1", RelationshipType.EXTENDS),
                _edge("e4", "s1", "d1", RelationshipType.DEPENDS_ON),
            ],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.INHERITANCE, repository_id="repo-1", symbol_id="s1"
        )
        assert len(evidence) == 1
        assert evidence[0].symbol_id == "p1"


class TestNeighborsAndBoundedDepth:
    def test_depth_is_forwarded_to_the_graph_service(self) -> None:
        fake = _FakeGraphService()
        _retriever(fake).run(
            GraphRetrievalOperation.NEIGHBORS, repository_id="repo-1", symbol_id="s1", depth=2
        )
        call_name, kwargs = fake.calls[0]
        assert call_name == "get_symbol_neighbors"
        assert kwargs["depth"] == 2

    def test_edges_become_evidence_with_unknown_distance(self) -> None:
        fake = _FakeGraphService()
        other = _node("o1", name="helper")
        fake.neighbors_result = GraphSubgraph(
            nodes=[_node("s1"), other],
            edges=[_edge("e5", "s1", "o1", RelationshipType.CALLS)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.NEIGHBORS, repository_id="repo-1", symbol_id="s1"
        )
        assert len(evidence) == 1
        assert evidence[0].graph_distance is None


class TestRepositoryOverview:
    def test_includes_a_statistics_evidence_item(self) -> None:
        fake = _FakeGraphService()
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.REPOSITORY_OVERVIEW, repository_id="repo-1"
        )
        assert any(e.evidence_type is EvidenceType.GRAPH_STATISTIC for e in evidence)


class TestApiHandler:
    def test_returns_endpoint_and_handler_evidence(self) -> None:
        fake = _FakeGraphService()
        endpoint = SymbolSearchResult(
            symbol_id="ep1",
            symbol_type=NodeLabel.API_ENDPOINT,
            name="login_endpoint",
            qualified_name=None,
            file_path="app/auth.py",
            start_line=1,
            end_line=1,
            match_type=SymbolMatchType.CONTAINS,
        )
        fake.search_results = [endpoint]
        fake.symbol_result = _node("ep1", label=NodeLabel.API_ENDPOINT, name="login_endpoint")
        handler = _node("h1", name="login")
        fake.neighbors_result = GraphSubgraph(
            nodes=[handler],
            edges=[_edge("e6", "ep1", "h1", RelationshipType.HANDLED_BY)],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.API_HANDLER, repository_id="repo-1", query="POST /login"
        )
        assert any(e.evidence_type is EvidenceType.API_ENDPOINT for e in evidence)
        assert any(e.relationship_type == "HANDLED_BY" for e in evidence)

    def test_no_query_returns_empty(self) -> None:
        fake = _FakeGraphService()
        assert (
            _retriever(fake).run(
                GraphRetrievalOperation.API_HANDLER, repository_id="repo-1", query=None
            )
            == []
        )


class TestPaths:
    def test_builds_one_summary_evidence_item(self) -> None:
        fake = _FakeGraphService()
        fake.path_result = GraphSubgraph(
            nodes=[_node("s1", name="a"), _node("s2", name="b")],
            edges=[_edge("e7", "s1", "s2", RelationshipType.CALLS)],
            truncated=False,
            traversal_depth=1,
            result_limit=1,
        )
        evidence = _retriever(fake).run(
            GraphRetrievalOperation.PATHS,
            repository_id="repo-1",
            symbol_id="s1",
            target_symbol_id="s2",
        )
        assert len(evidence) == 1
        assert "Path:" in evidence[0].content
        assert evidence[0].evidence_type is EvidenceType.CALL_RELATIONSHIP

    def test_missing_symbol_ids_returns_empty(self) -> None:
        fake = _FakeGraphService()
        assert (
            _retriever(fake).run(
                GraphRetrievalOperation.PATHS,
                repository_id="repo-1",
                symbol_id="s1",
                target_symbol_id=None,
            )
            == []
        )
