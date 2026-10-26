"""Translation between Neo4j driver graph objects and this app's domain
models (read side), and between parsed-symbol dataclasses and Cypher-ready
parameter dicts (write side).

Read side never leaks a raw ``neo4j.graph.Node``/``Relationship`` past
this module (rule 10). Write side never stores a complete source file in
Neo4j (rule 9) — only the already-small, already-computed fields the
parser produced.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from neo4j.graph import Node as DriverNode
from neo4j.graph import Relationship as DriverRelationship

from app.domain.code_symbols.enums import ParameterKind
from app.domain.code_symbols.models import ParsedClass, ParsedFunction, ParsedParameter
from app.domain.graph.enums import NodeLabel, RelationshipType, SymbolMatchType
from app.domain.graph.models import GraphEdge, GraphNode, GraphStatistics, SymbolSearchResult
from app.parsing.source_utils import generate_symbol_id

_KNOWN_TOP_LEVEL_FIELDS = {
    "id",
    "repository_id",
    "name",
    "qualified_name",
    "file_path",
    "start_line",
    "end_line",
}

_LABEL_BY_VALUE = {label.value: label for label in NodeLabel}


def _node_label(node: DriverNode) -> NodeLabel:
    for label_value in node.labels:
        if label_value in _LABEL_BY_VALUE:
            return _LABEL_BY_VALUE[label_value]
    raise ValueError(f"Node has no recognized label: {list(node.labels)!r}")


def map_node(node: DriverNode) -> GraphNode:
    label = _node_label(node)
    properties = {key: value for key, value in node.items() if key not in _KNOWN_TOP_LEVEL_FIELDS}
    return GraphNode(
        id=str(node.get("id")),
        repository_id=str(node.get("repository_id")),
        label=label,
        name=str(node.get("name", "")),
        qualified_name=node.get("qualified_name"),
        file_path=node.get("file_path"),
        start_line=node.get("start_line"),
        end_line=node.get("end_line"),
        properties=properties,
    )


def map_relationship(rel: DriverRelationship, *, repository_id: str) -> GraphEdge:
    relationship_type = RelationshipType(rel.type)
    source_id = str(rel.start_node.get("id")) if rel.start_node is not None else ""
    target_id = str(rel.end_node.get("id")) if rel.end_node is not None else ""
    edge_id = generate_symbol_id(
        repository_id=repository_id,
        file_path="",
        symbol_type=f"edge:{relationship_type.value}",
        qualified_name=f"{source_id}->{target_id}:{rel.get('call_site_line', '')}",
        start_line=0,
    )
    properties = dict(rel.items())
    return GraphEdge(
        id=edge_id,
        repository_id=repository_id,
        source_id=source_id,
        target_id=target_id,
        relationship_type=relationship_type,
        properties=properties,
    )


def map_symbol_search_result(node: DriverNode, query: str) -> SymbolSearchResult:
    graph_node = map_node(node)
    lowered_query = query.lower()
    name = graph_node.name.lower()
    qualified = (graph_node.qualified_name or "").lower()

    if name == lowered_query:
        match_type = SymbolMatchType.EXACT_NAME
    elif qualified == lowered_query:
        match_type = SymbolMatchType.EXACT_QUALIFIED_NAME
    elif name.startswith(lowered_query):
        match_type = SymbolMatchType.PREFIX
    else:
        match_type = SymbolMatchType.CONTAINS

    return SymbolSearchResult(
        symbol_id=graph_node.id,
        symbol_type=graph_node.label,
        name=graph_node.name,
        qualified_name=graph_node.qualified_name,
        file_path=graph_node.file_path,
        start_line=graph_node.start_line,
        end_line=graph_node.end_line,
        match_type=match_type,
    )


def map_graph_statistics(
    *,
    repository_id: str,
    node_count_rows: Sequence[Mapping[str, object]],
    relationship_count_rows: Sequence[Mapping[str, object]],
    unresolved_call_count: int,
    parse_error_count: int,
) -> GraphStatistics:
    node_counts = {str(row["label"]): cast(int, row["count"]) for row in node_count_rows}
    relationship_counts = {
        str(row["relationship_type"]): cast(int, row["count"]) for row in relationship_count_rows
    }
    return GraphStatistics(
        repository_id=repository_id,
        node_counts=node_counts,
        relationship_counts=relationship_counts,
        unresolved_call_count=unresolved_call_count,
        parse_error_count=parse_error_count,
    )


# --- write side: parsed-symbol dataclasses -> Cypher parameter dicts ------


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def class_properties(cls: ParsedClass, *, repository_id: str, file_path: str) -> dict[str, object]:
    """Never includes ``source_code`` — Neo4j stores summaries/metadata,
    not complete source (rule 9: "Do not store complete source files
    unnecessarily in Neo4j")."""
    return {
        "repository_id": repository_id,
        "id": cls.id,
        "qualified_name": cls.qualified_name,
        "name": cls.name,
        "file_path": file_path,
        "start_line": cls.location.start_line,
        "end_line": cls.location.end_line,
        "docstring_summary": _summarize(cls.docstring),
        "decorators": [d.raw_expression for d in cls.decorators],
        "base_class_names": list(cls.base_classes),
    }


def function_properties(
    func: ParsedFunction, *, repository_id: str, file_path: str
) -> dict[str, object]:
    signals = func.complexity_signals
    return {
        "repository_id": repository_id,
        "id": func.id,
        "qualified_name": func.qualified_name,
        "name": func.name,
        "file_path": file_path,
        "start_line": func.location.start_line,
        "signature": func.signature,
        "end_line": func.location.end_line,
        "async_function": func.async_function,
        "decorators": [d.raw_expression for d in func.decorators],
        "return_annotation": func.return_annotation,
        "branch_count": signals.branch_count,
        "loop_count": signals.loop_count,
        "exception_handler_count": signals.exception_handler_count,
        "return_count": signals.return_count,
        "await_count": signals.await_count,
        "nested_function_count": signals.nested_function_count,
    }


def parameter_properties(param: ParsedParameter, *, repository_id: str) -> dict[str, object]:
    return {
        "repository_id": repository_id,
        "id": param.id,
        "name": param.name,
        "annotation": param.annotation,
        "default_value": param.default_value,
        "kind": param.kind.value if isinstance(param.kind, ParameterKind) else str(param.kind),
        "position": param.position,
    }


def _summarize(docstring: str | None, *, max_length: int = 240) -> str | None:
    """A short, deterministic summary — the first line, truncated.

    Never an LLM summary (AGENTS.md rule 2/8) — just the docstring's own
    first line, since that's already what most Python docstrings use as
    a one-line summary (PEP 257).
    """
    if not docstring:
        return None
    first_line = docstring.strip().splitlines()[0].strip()
    if len(first_line) > max_length:
        return first_line[: max_length - 1] + "…"
    return first_line
