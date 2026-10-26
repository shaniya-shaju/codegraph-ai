"""End-to-end graph-layer integration tests against a real Neo4j.

See conftest.py for how to run these (they auto-skip, visibly, if no
Neo4j is reachable). Covers the graph task's required integration
scenarios: building a graph, querying symbols, callers/callees,
inheritance, endpoint handlers, idempotent reanalysis, stale-symbol
removal, repository isolation, bounded subgraphs, and repository deletion.
"""

import uuid
from pathlib import Path

from app.core.config import get_settings
from app.graph import repository_graph_service as service
from app.graph.exceptions import TraversalLimitExceededError
from app.graph.graph_builder import (
    RepositoryMetadata,
    build_repository_graph,
    delete_repository_graph,
)
from app.graph.neo4j_client import Neo4jClient
from app.parsing.python.parser import PythonParser

_PARSER = PythonParser()

_SAMPLE_SOURCE = '''"""A tiny sample repository for the graph integration tests."""


class Animal:
    """Base animal."""

    def speak(self):
        return "..."


class Dog(Animal):
    def speak(self):
        self.bark()
        return "Woof"

    def bark(self):
        return "Woof!"


@app.get("/animals")
def list_animals():
    return build_default_animal()


def build_default_animal():
    return Dog()
'''


def _metadata(repository_id: str) -> RepositoryMetadata:
    return RepositoryMetadata(
        repository_id=repository_id,
        name="sample",
        source_type="git_url",
        source_url="https://example.com/sample.git",
        default_branch="main",
        commit_hash="deadbeef",
        parser_version="1",
    )


def _build_sample_graph(client: Neo4jClient, repository_id: str) -> None:
    parsed = _PARSER.parse(_SAMPLE_SOURCE, Path("animals.py"), repository_id)
    build_repository_graph(client, _metadata(repository_id), [parsed])


class TestBuildingAndQueryingAGraph:
    def test_build_then_search_symbols(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)

        results = service.search_symbols(
            neo4j_client, get_settings(), repository_id=test_repository_id, query="Dog"
        )

        assert any(r.name == "Dog" for r in results)

    def test_get_symbol_returns_full_details(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        [dog] = [
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="Dog"
            )
            if r.name == "Dog"
        ]

        node = service.get_symbol(
            neo4j_client, repository_id=test_repository_id, symbol_id=dog.symbol_id
        )

        assert node is not None
        assert node.qualified_name == "animals.Dog"


class TestCallersAndCallees:
    def test_bark_has_a_caller_and_speak_has_a_callee(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        bark = next(
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="bark"
            )
            if r.name == "bark"
        )
        speak = next(
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="speak"
            )
            if r.qualified_name == "animals.Dog.speak"
        )

        callers = service.get_callers(
            neo4j_client, get_settings(), repository_id=test_repository_id, symbol_id=bark.symbol_id
        )
        callees = service.get_callees(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=speak.symbol_id,
        )

        assert any(n.qualified_name == "animals.Dog.speak" for n in callers.nodes)
        assert any(n.qualified_name == "animals.Dog.bark" for n in callees.nodes)


_CROSS_FILE_CALLER_SOURCE = '''"""Caller module — deliberately passed to
build_repository_graph before its callee's module, to pin the
write-ordering regression (see graph_builder.py's "Two-pass write")."""

from callee import helper


def use_helper():
    return helper()
'''

_CROSS_FILE_CALLEE_SOURCE = '''"""Callee module, processed after the caller above."""


def helper():
    return "hi"
'''

_CROSS_FILE_CHILD_SOURCE = '''"""Subclass module — deliberately processed before its base class's
module (see graph_builder.py's "Two-pass write")."""


class Child(Base):
    pass
'''

_CROSS_FILE_BASE_SOURCE = '''"""Base class module, processed after the subclass above."""


class Base:
    pass
'''


class TestCrossFileWriteOrdering:
    """Regression coverage for graph_builder.py's two-pass write: a CALLS,
    IMPORTS, or EXTENDS edge must still be written even when its target is
    defined in a file processed *after* the referencing file. Before that
    fix, the plain MATCH-MATCH-MERGE edge queries silently dropped exactly
    this case. parsed_files is passed in caller-before-callee order
    explicitly, independent of any alphabetical-sort coincidence."""

    def test_calls_and_imports_edges_survive_cross_file_forward_reference(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        caller_file = _PARSER.parse(
            _CROSS_FILE_CALLER_SOURCE, Path("caller.py"), test_repository_id
        )
        callee_file = _PARSER.parse(
            _CROSS_FILE_CALLEE_SOURCE, Path("callee.py"), test_repository_id
        )

        build_repository_graph(
            neo4j_client, _metadata(test_repository_id), [caller_file, callee_file]
        )

        use_helper = next(
            r
            for r in service.search_symbols(
                neo4j_client,
                get_settings(),
                repository_id=test_repository_id,
                query="use_helper",
            )
            if r.name == "use_helper"
        )
        callees = service.get_callees(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=use_helper.symbol_id,
        )
        assert any(n.qualified_name == "callee.helper" for n in callees.nodes)

        # IMPORTS edges originate from the File node (parsed_file.id) —
        # File isn't a searchable label, so look it up directly rather
        # than via search_symbols.
        dependencies = service.get_dependencies(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=caller_file.id,
        )
        assert any(
            n.qualified_name == "callee" and e.relationship_type.value == "IMPORTS"
            for n in dependencies.nodes
            for e in dependencies.edges
            if e.target_id == n.id
        )

    def test_extends_edge_survives_cross_file_forward_reference(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        child_file = _PARSER.parse(_CROSS_FILE_CHILD_SOURCE, Path("child.py"), test_repository_id)
        base_file = _PARSER.parse(_CROSS_FILE_BASE_SOURCE, Path("base.py"), test_repository_id)

        build_repository_graph(
            neo4j_client, _metadata(test_repository_id), [child_file, base_file]
        )

        child = next(
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="Child"
            )
            if r.name == "Child"
        )
        dependencies = service.get_dependencies(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=child.symbol_id,
        )
        assert any(
            n.qualified_name == "base.Base" and e.relationship_type.value == "EXTENDS"
            for n in dependencies.nodes
            for e in dependencies.edges
            if e.target_id == n.id
        )


class TestInheritance:
    def test_dependencies_surface_the_extends_edge(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        dog = next(
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="Dog"
            )
            if r.name == "Dog"
        )

        dependencies = service.get_dependencies(
            neo4j_client, get_settings(), repository_id=test_repository_id, symbol_id=dog.symbol_id
        )

        assert any(
            n.qualified_name == "animals.Animal" and e.relationship_type.value == "EXTENDS"
            for n in dependencies.nodes
            for e in dependencies.edges
            if e.target_id == n.id
        )


class TestApiEndpointHandler:
    def test_endpoint_is_handled_by_list_animals(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)

        results = service.search_symbols(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            query="animals",
            symbol_type="APIEndpoint",
        )

        assert len(results) == 1
        endpoint = results[0]
        dependencies = service.get_symbol_neighbors(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=endpoint.symbol_id,
        )
        assert any(n.qualified_name == "animals.list_animals" for n in dependencies.nodes)

    def test_endpoint_is_findable_by_route_path_alone(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        """Regression test for SEARCH_SYMBOLS: an APIEndpoint node has no
        name/qualified_name property (see queries.py's UPSERT_API_ENDPOINT),
        so it must be matched via the route_path branch added to
        queries.SEARCH_SYMBOLS. The route and handler name here
        deliberately share no substring, so this can't pass by
        accidentally matching on the handler's name instead."""
        source = '''"""Endpoint whose route path shares no text with its
handler's name — isolates route_path-based matching from name-based
matching."""


@app.get("/zoo")
def list_creatures():
    return []
'''
        parsed = _PARSER.parse(source, Path("zoo.py"), test_repository_id)
        build_repository_graph(neo4j_client, _metadata(test_repository_id), [parsed])

        results = service.search_symbols(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            query="zoo",
            symbol_type="APIEndpoint",
        )

        assert len(results) == 1
        endpoint = results[0]
        dependencies = service.get_symbol_neighbors(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=endpoint.symbol_id,
        )
        assert any(n.qualified_name == "zoo.list_creatures" for n in dependencies.nodes)


class TestIdempotentReanalysis:
    def test_reanalyzing_the_same_source_does_not_duplicate_nodes(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        stats_before = service.get_statistics(neo4j_client, repository_id=test_repository_id)

        _build_sample_graph(neo4j_client, test_repository_id)
        stats_after = service.get_statistics(neo4j_client, repository_id=test_repository_id)

        assert stats_before.node_counts == stats_after.node_counts
        assert stats_before.relationship_counts == stats_after.relationship_counts


class TestStaleSymbolRemoval:
    def test_removing_a_method_from_source_removes_its_node(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        before = service.search_symbols(
            neo4j_client, get_settings(), repository_id=test_repository_id, query="bark"
        )
        assert any(r.name == "bark" for r in before)

        reduced_source = _SAMPLE_SOURCE.replace(
            '    def bark(self):\n        return "Woof!"\n', ""
        ).replace("        self.bark()\n", "")
        parsed = _PARSER.parse(reduced_source, Path("animals.py"), test_repository_id)
        build_repository_graph(neo4j_client, _metadata(test_repository_id), [parsed])

        after = service.search_symbols(
            neo4j_client, get_settings(), repository_id=test_repository_id, query="bark"
        )
        assert not any(r.name == "bark" for r in after)


class TestRepositoryIsolation:
    def test_two_repositories_never_share_symbols(self, neo4j_client: Neo4jClient) -> None:
        repo_a = f"itest-{uuid.uuid4()}"
        repo_b = f"itest-{uuid.uuid4()}"
        try:
            _build_sample_graph(neo4j_client, repo_a)
            _build_sample_graph(neo4j_client, repo_b)

            results_a = service.search_symbols(
                neo4j_client, get_settings(), repository_id=repo_a, query="Dog"
            )
            results_b = service.search_symbols(
                neo4j_client, get_settings(), repository_id=repo_b, query="Dog"
            )

            assert results_a and results_b
            ids_a = {r.symbol_id for r in results_a}
            ids_b = {r.symbol_id for r in results_b}
            assert ids_a.isdisjoint(ids_b)
        finally:
            delete_repository_graph(neo4j_client, repo_a)
            delete_repository_graph(neo4j_client, repo_b)


class TestBoundedSubgraph:
    def test_neighbors_are_bounded_by_configured_depth(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        _build_sample_graph(neo4j_client, test_repository_id)
        dog = next(
            r
            for r in service.search_symbols(
                neo4j_client, get_settings(), repository_id=test_repository_id, query="Dog"
            )
            if r.name == "Dog"
        )

        subgraph = service.get_symbol_neighbors(
            neo4j_client,
            get_settings(),
            repository_id=test_repository_id,
            symbol_id=dog.symbol_id,
            depth=1,
        )

        assert subgraph.traversal_depth == 1
        assert len(subgraph.nodes) > 0

    def test_depth_beyond_configured_maximum_is_rejected(
        self, neo4j_client: Neo4jClient, test_repository_id: str
    ) -> None:
        settings = get_settings()
        try:
            service.get_symbol_neighbors(
                neo4j_client,
                settings,
                repository_id=test_repository_id,
                symbol_id="whatever",
                depth=settings.graph_max_traversal_depth + 1,
            )
            raise AssertionError("expected TraversalLimitExceededError")
        except TraversalLimitExceededError:
            pass


class TestRepositoryDeletion:
    def test_deleting_one_repository_leaves_another_untouched(
        self, neo4j_client: Neo4jClient
    ) -> None:
        repo_a = f"itest-{uuid.uuid4()}"
        repo_b = f"itest-{uuid.uuid4()}"
        try:
            _build_sample_graph(neo4j_client, repo_a)
            _build_sample_graph(neo4j_client, repo_b)

            delete_repository_graph(neo4j_client, repo_a)

            results_a = service.search_symbols(
                neo4j_client, get_settings(), repository_id=repo_a, query="Dog"
            )
            results_b = service.search_symbols(
                neo4j_client, get_settings(), repository_id=repo_b, query="Dog"
            )

            assert results_a == []
            assert results_b != []
        finally:
            delete_repository_graph(neo4j_client, repo_a)
            delete_repository_graph(neo4j_client, repo_b)
