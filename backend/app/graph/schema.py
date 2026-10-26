"""Constraints and indexes for the MVP graph schema.

Every uniqueness constraint includes ``repository_id`` (see DATA_MODEL.md
"Isolation rule" and this task's "Repository isolation" — there is no
Neo4j instance in this system holding a single tenant's data without that
prefix). Composite keys follow the task's worked examples exactly, so
graph_builder.py's MERGE statements key on the same natural keys these
constraints enforce.

A separate single-property index on ``id`` per label supports looking up
"whatever node has this id" without knowing its label ahead of time (used
by the symbol-detail/callers/callees/dependencies endpoints).
"""

from app.graph.neo4j_client import Neo4jClient

_CONSTRAINTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Repository", "repository_repository_id_key", ("repository_id",)),
    ("Directory", "directory_repo_path_key", ("repository_id", "path")),
    ("File", "file_repo_path_key", ("repository_id", "file_path")),
    ("Module", "module_repo_qualified_name_key", ("repository_id", "qualified_name")),
    ("Class", "class_repo_qualified_name_key", ("repository_id", "qualified_name")),
    (
        "Function",
        "function_repo_qualified_name_start_line_key",
        ("repository_id", "qualified_name", "start_line"),
    ),
    (
        "Method",
        "method_repo_qualified_name_start_line_key",
        ("repository_id", "qualified_name", "start_line"),
    ),
    ("Parameter", "parameter_repo_id_key", ("repository_id", "id")),
    ("ExternalDependency", "external_dependency_repo_name_key", ("repository_id", "name")),
    ("APIEndpoint", "api_endpoint_repo_id_key", ("repository_id", "id")),
]

_ID_INDEX_LABELS = [
    "Directory",
    "File",
    "Module",
    "Class",
    "Function",
    "Method",
    "Parameter",
    "ExternalDependency",
    "APIEndpoint",
]


def ensure_schema(client: Neo4jClient) -> None:
    """Create every constraint/index if it doesn't already exist.

    Idempotent and safe to call on every application startup — Cypher's
    ``IF NOT EXISTS`` makes repeated calls a no-op after the first.
    """
    for label, constraint_name, properties in _CONSTRAINTS:
        prop_list = ", ".join(f"n.{prop}" for prop in properties)
        query = (
            f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE ({prop_list}) IS UNIQUE"
        )
        client.execute_write(query)

    for label in _ID_INDEX_LABELS:
        index_name = f"{label.lower()}_id_index"
        query = f"CREATE INDEX {index_name} IF NOT EXISTS FOR (n:{label}) ON (n.id)"
        client.execute_write(query)
