"""Write-side graph_builder.py behavior: repository isolation, file
hierarchy, symbol/parameter/endpoint upserts, stale-symbol cleanup, and
Cypher parameterization — all verified against a FakeNeo4jClient that
records calls instead of needing a real Neo4j."""

from pathlib import Path

from app.graph import queries
from app.graph.graph_builder import RepositoryMetadata, build_repository_graph
from app.parsing.python.parser import PythonParser
from tests.unit.graph.conftest import FakeNeo4jClient


def _parse(source: str, file_path: str, repository_id: str = "repo-1"):
    return PythonParser().parse(source, Path(file_path), repository_id)


def _metadata(repository_id: str = "repo-1") -> RepositoryMetadata:
    return RepositoryMetadata(
        repository_id=repository_id,
        name="demo",
        source_type="git_url",
        source_url="https://example.com/demo.git",
        default_branch="main",
        commit_hash="abc123",
        parser_version="1",
    )


class TestRepositoryIsolation:
    def test_every_write_carries_the_repository_id(self, fake_client: FakeNeo4jClient) -> None:
        parsed = _parse("def f():\n    pass\n", "m.py", repository_id="repo-xyz")

        build_repository_graph(fake_client, _metadata("repo-xyz"), [parsed])

        for _query, params in fake_client.write_calls:
            assert params.get("repository_id") == "repo-xyz"


class TestFileHierarchy:
    def test_creates_directory_chain_for_nested_file(self, fake_client: FakeNeo4jClient) -> None:
        parsed = _parse("x = 1\n", "app/auth/service.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        directory_writes = [p for q, p in fake_client.write_calls if q is queries.UPSERT_DIRECTORY]
        paths = {p["path"] for p in directory_writes}
        assert paths == {"app", "app/auth"}

    def test_top_level_file_creates_no_directory(self, fake_client: FakeNeo4jClient) -> None:
        parsed = _parse("x = 1\n", "main.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        directory_writes = [p for q, p in fake_client.write_calls if q is queries.UPSERT_DIRECTORY]
        assert directory_writes == []


class TestSymbolAndParameterUpserts:
    def test_function_upsert_includes_signature_and_signals(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse("def f(a, b):\n    if a:\n        pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        function_writes = [p for q, p in fake_client.write_calls if "MERGE (fn:Function" in q]
        assert len(function_writes) == 1
        assert function_writes[0]["name"] == "f"
        assert function_writes[0]["branch_count"] == 1

    def test_parameter_and_has_parameter_relationship_written(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse("def f(a, b):\n    pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        parameter_writes = [p for q, p in fake_client.write_calls if q is queries.UPSERT_PARAMETER]
        has_param_writes = [
            p for q, p in fake_client.write_calls if "MERGE (owner)-[:HAS_PARAMETER]" in q
        ]
        assert {p["name"] for p in parameter_writes} == {"a", "b"}
        assert len(has_param_writes) == 2

    def test_method_uses_method_label_not_function(self, fake_client: FakeNeo4jClient) -> None:
        parsed = _parse("class C:\n    def m(self):\n        pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        assert any("MERGE (fn:Method" in q for q, _ in fake_client.write_calls)
        assert not any("MERGE (fn:Function" in q for q, _ in fake_client.write_calls)


class TestApiEndpointExtraction:
    def test_route_decorated_function_creates_endpoint_and_handled_by(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse('@app.get("/users")\ndef list_users():\n    return []\n', "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        endpoint_writes = [
            p for q, p in fake_client.write_calls if q is queries.UPSERT_API_ENDPOINT
        ]
        handled_by_writes = [p for q, p in fake_client.write_calls if "HANDLED_BY" in q]
        assert len(endpoint_writes) == 1
        assert endpoint_writes[0]["http_method"] == "GET"
        assert endpoint_writes[0]["route_path"] == "/users"
        assert len(handled_by_writes) == 1

    def test_non_route_decorator_creates_no_endpoint(self, fake_client: FakeNeo4jClient) -> None:
        parsed = _parse("@staticmethod\ndef f():\n    pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        endpoint_writes = [
            p for q, p in fake_client.write_calls if q is queries.UPSERT_API_ENDPOINT
        ]
        assert endpoint_writes == []


class TestStaleCleanupAndIdempotency:
    def test_stale_cleanup_queries_run_before_every_fresh_insert(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse("def f():\n    pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        queries_run = [q for q, _ in fake_client.write_calls]
        assert queries.DELETE_STALE_FILE_SYMBOLS in queries_run
        assert queries.DELETE_STALE_FILE_ENDPOINTS in queries_run
        assert queries.DELETE_STALE_FILE_OUTGOING_EDGES in queries_run
        # cleanup happens before the file's own fresh upsert.
        cleanup_index = queries_run.index(queries.DELETE_STALE_FILE_SYMBOLS)
        upsert_index = queries_run.index(queries.UPSERT_FILE)
        assert cleanup_index < upsert_index

    def test_reanalyzing_the_same_file_runs_cleanup_again(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse("def f():\n    pass\n", "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])
        first_cleanup_count = sum(
            1 for q, _ in fake_client.write_calls if q is queries.DELETE_STALE_FILE_SYMBOLS
        )

        build_repository_graph(fake_client, _metadata(), [parsed])
        second_cleanup_count = sum(
            1 for q, _ in fake_client.write_calls if q is queries.DELETE_STALE_FILE_SYMBOLS
        )

        assert first_cleanup_count == 1
        assert (
            second_cleanup_count == 2
        )  # ran again on reanalysis — this is what prevents duplicates


class TestCypherParameterization:
    def test_every_upsert_query_uses_dollar_placeholders_not_fstring_values(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        parsed = _parse('@app.get("/weird\'; DROP")\ndef f():\n    pass\n', "m.py")

        build_repository_graph(fake_client, _metadata(), [parsed])

        for query, params in fake_client.write_calls:
            for value in params.values():
                if isinstance(value, str) and value and "DROP" in value:
                    # the dangerous value must appear only as a parameter,
                    # never spliced into the query text itself.
                    assert value not in query
