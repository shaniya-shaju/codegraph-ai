"""Stable node/edge mapping, symbol-node mapping, and write-side property
builders — see rule 10 ("Keep graph-query responses independent from raw
Neo4j driver objects")."""

from app.domain.code_symbols.enums import ParameterKind
from app.domain.code_symbols.models import (
    ComplexitySignals,
    ParsedClass,
    ParsedDecorator,
    ParsedFunction,
    ParsedParameter,
    SourceLocation,
)
from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.graph.mappers import (
    class_properties,
    function_properties,
    map_graph_statistics,
    map_node,
    map_relationship,
    map_symbol_search_result,
    parameter_properties,
)
from tests.unit.graph.conftest import FakeDriverNode, FakeDriverRelationship


def _location(line: int = 10) -> SourceLocation:
    return SourceLocation(
        file_path="m.py", start_line=line, start_column=0, end_line=line, end_column=5
    )


class TestMapNode:
    def test_maps_known_fields_and_leftover_properties(self) -> None:
        node = FakeDriverNode(
            labels={"Function"},
            properties={
                "id": "abc",
                "repository_id": "repo-1",
                "name": "login",
                "qualified_name": "app.auth.login",
                "file_path": "app/auth.py",
                "start_line": 10,
                "end_line": 20,
                "async_function": True,
                "branch_count": 2,
            },
        )

        result = map_node(node)  # type: ignore[arg-type]

        assert result.id == "abc"
        assert result.repository_id == "repo-1"
        assert result.label is NodeLabel.FUNCTION
        assert result.name == "login"
        assert result.qualified_name == "app.auth.login"
        assert result.file_path == "app/auth.py"
        assert result.start_line == 10
        assert result.end_line == 20
        # Non-"known" fields fall into `properties`, not lost.
        assert result.properties == {"async_function": True, "branch_count": 2}

    def test_two_calls_with_identical_input_produce_equal_output(self) -> None:
        properties = {"id": "abc", "repository_id": "repo-1", "name": "login"}
        node_a = FakeDriverNode(labels={"Function"}, properties=dict(properties))
        node_b = FakeDriverNode(labels={"Function"}, properties=dict(properties))

        assert map_node(node_a) == map_node(node_b)  # type: ignore[arg-type]


class TestMapRelationship:
    def test_maps_type_and_endpoints_and_generates_a_stable_id(self) -> None:
        source = FakeDriverNode(labels={"Function"}, properties={"id": "caller-id"})
        target = FakeDriverNode(labels={"Function"}, properties={"id": "callee-id"})
        rel = FakeDriverRelationship(
            rel_type="CALLS",
            properties={"call_site_line": 5, "resolution_confidence": "exact"},
            start_node=source,
            end_node=target,
        )

        edge = map_relationship(rel, repository_id="repo-1")  # type: ignore[arg-type]

        assert edge.source_id == "caller-id"
        assert edge.target_id == "callee-id"
        assert edge.relationship_type.value == "CALLS"
        assert edge.properties["resolution_confidence"] == "exact"
        assert edge.id  # non-empty

    def test_same_relationship_maps_to_the_same_id_every_time(self) -> None:
        source = FakeDriverNode(labels={"Function"}, properties={"id": "caller-id"})
        target = FakeDriverNode(labels={"Function"}, properties={"id": "callee-id"})
        rel = FakeDriverRelationship(
            rel_type="CALLS", properties={"call_site_line": 5}, start_node=source, end_node=target
        )

        first = map_relationship(rel, repository_id="repo-1")  # type: ignore[arg-type]
        second = map_relationship(rel, repository_id="repo-1")  # type: ignore[arg-type]

        assert first.id == second.id

    def test_different_repository_id_produces_a_different_edge_id(self) -> None:
        source = FakeDriverNode(labels={"Function"}, properties={"id": "caller-id"})
        target = FakeDriverNode(labels={"Function"}, properties={"id": "callee-id"})
        rel = FakeDriverRelationship(
            rel_type="CALLS", properties={"call_site_line": 5}, start_node=source, end_node=target
        )

        edge_a = map_relationship(rel, repository_id="repo-a")  # type: ignore[arg-type]
        edge_b = map_relationship(rel, repository_id="repo-b")  # type: ignore[arg-type]

        assert edge_a.id != edge_b.id


class TestMapSymbolSearchResult:
    def test_exact_name_match(self) -> None:
        node = FakeDriverNode(labels={"Function"}, properties={"id": "1", "name": "login"})
        result = map_symbol_search_result(node, "login")  # type: ignore[arg-type]
        assert result.match_type is SymbolMatchType.EXACT_NAME

    def test_prefix_match(self) -> None:
        node = FakeDriverNode(labels={"Function"}, properties={"id": "1", "name": "login_user"})
        result = map_symbol_search_result(node, "login")  # type: ignore[arg-type]
        assert result.match_type is SymbolMatchType.PREFIX

    def test_contains_match(self) -> None:
        node = FakeDriverNode(
            labels={"Function"}, properties={"id": "1", "name": "user_login_flow"}
        )
        result = map_symbol_search_result(node, "login")  # type: ignore[arg-type]
        assert result.match_type is SymbolMatchType.CONTAINS


class TestMapGraphStatistics:
    def test_aggregates_rows_into_dicts(self) -> None:
        stats = map_graph_statistics(
            repository_id="repo-1",
            node_count_rows=[{"label": "Function", "count": 3}, {"label": "Class", "count": 1}],
            relationship_count_rows=[{"relationship_type": "CALLS", "count": 5}],
            unresolved_call_count=2,
            parse_error_count=0,
        )

        assert stats.node_counts == {"Function": 3, "Class": 1}
        assert stats.relationship_counts == {"CALLS": 5}
        assert stats.unresolved_call_count == 2


class TestWriteSideProperties:
    def test_class_properties_never_include_source_code(self) -> None:
        cls = ParsedClass(
            id="c1",
            name="Foo",
            qualified_name="m.Foo",
            base_classes=["Base"],
            decorators=[],
            docstring="First line.\nMore detail.",
            source_code="class Foo(Base):\n    pass",
            location=_location(),
        )

        props = class_properties(cls, repository_id="repo-1", file_path="m.py")

        assert "source_code" not in props
        assert props["docstring_summary"] == "First line."
        assert props["base_class_names"] == ["Base"]

    def test_function_properties_include_complexity_signals(self) -> None:
        func = ParsedFunction(
            id="f1",
            name="login",
            qualified_name="m.login",
            signature="def login():",
            async_function=False,
            decorators=[ParsedDecorator(raw_expression="@app.get('/x')", route_info=None)],
            parameters=[],
            return_annotation=None,
            docstring=None,
            source_code="def login():\n    pass",
            location=_location(),
            calls=[],
            parent_class=None,
            complexity_signals=ComplexitySignals(branch_count=2, loop_count=1),
        )

        props = function_properties(func, repository_id="repo-1", file_path="m.py")

        assert props["branch_count"] == 2
        assert props["loop_count"] == 1
        assert props["decorators"] == ["@app.get('/x')"]
        assert "source_code" not in props

    def test_parameter_properties_serializes_kind_as_plain_string(self) -> None:
        param = ParsedParameter(
            id="p1",
            name="x",
            annotation="int",
            default_value=None,
            kind=ParameterKind.POSITIONAL,
            position=0,
            location=_location(),
        )

        props = parameter_properties(param, repository_id="repo-1")

        assert props["kind"] == "positional"
        assert props["repository_id"] == "repo-1"
