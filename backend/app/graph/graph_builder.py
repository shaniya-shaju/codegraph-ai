"""Write-side orchestration: idempotent upserts + stale-node cleanup.

See the task's "Graph-building behavior" and "Idempotency and reanalysis"
sections. One Neo4j write transaction per FILE for that file's own nodes
— never one transaction per property/relationship: each file's
previous-analysis descendants are deleted and its current parse
re-inserted atomically inside a single transaction, so a partial failure
on one file can't leave that file's subgraph half-written, and
reanalyzing an unchanged file never accumulates duplicates (MERGE on each
label's natural key, matching the constraints in schema.py, plus the
delete-then-insert step for exactly the descendants that don't have a
natural-key MERGE target of their own, i.e. nothing here truly needs a
diff — it needs "this file's graph is authoritative for this file's
descendants").

Two-pass write, across *all* files: a relationship whose target may live
in a different file (CALLS, an internally-resolved EXTENDS, an
internally-resolved IMPORTS) is never written in the same per-file
transaction as that file's own nodes — see _PendingEdge. Files are parsed
and queued independently, so nothing guarantees a callee's/base
class's/imported module's file has already been written by the time a
caller's file is processed; writing such an edge with a plain
MATCH-MATCH-MERGE (as this module's edge queries do, deliberately, so
they never silently create a placeholder node from the wrong side) would
silently find no match and drop the edge if the target's file happens to
sort later. Every file's nodes are written first (pass 1); only once
every file's nodes exist are the deferred cross-file edges written (pass
2, also one transaction per file). A relationship that's always safe
within a single file's own transaction (DEFINES, HAS_PARAMETER,
HANDLED_BY, an externally-resolved EXTENDS/IMPORTS onto a freshly-merged
ExternalDependency node) is unaffected and still written in pass 1.

Relationship directions follow DATA_MODEL.md's worked example exactly:
File-DEFINES->{Module,Class,Function} directly (not chained through
Module) for top-level symbols; nested symbols chain off their actual
lexical parent, inferred from qualified_name for the flattened function
list (see _infer_local_parent) and taken directly from ParsedClass's own
structure for methods/nested classes.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from app.domain.code_symbols.models import ParsedClass, ParsedFile, ParsedFunction, ParsedImport
from app.domain.graph.enums import CallResolutionConfidence, NodeLabel
from app.graph import queries
from app.graph.mappers import (
    class_properties,
    function_properties,
    parameter_properties,
    utc_now_iso,
)
from app.graph.neo4j_client import Neo4jClient
from app.graph.relationship_resolver import (
    RepositoryIndex,
    build_repository_index,
    resolve_base_class,
    resolve_call,
    resolve_import_target,
)
from app.parsing.source_utils import generate_symbol_id

if TYPE_CHECKING:
    from neo4j import ManagedTransaction


@dataclass(frozen=True)
class RepositoryMetadata:
    repository_id: str
    name: str
    source_type: str
    source_url: str | None
    default_branch: str | None
    commit_hash: str | None
    parser_version: str


@dataclass
class GraphBuildSummary:
    files_processed: int = 0
    unresolved_call_count: int = 0


@dataclass(frozen=True)
class _PendingEdge:
    """A cross-file-referencing edge write, deferred to pass 2 — see the
    module docstring's "Two-pass write"."""

    query: str
    params: dict[str, object]


def build_repository_graph(
    client: Neo4jClient,
    metadata: RepositoryMetadata,
    parsed_files: list[ParsedFile],
    line_counts: dict[str, int] | None = None,
) -> GraphBuildSummary:
    """Write (or idempotently re-write) a whole repository's graph.

    `line_counts` (file_path -> line count) is supplied by the caller
    (which already has the raw source bytes for parsing) rather than
    computed here — Neo4j never stores complete file source (rule 9), and
    ParsedFile itself intentionally doesn't retain it either.
    """
    line_counts = line_counts or {}
    _upsert_repository(client, metadata)
    _upsert_directory_hierarchy(
        client, metadata.repository_id, [pf.file_path for pf in parsed_files]
    )

    index = build_repository_index(parsed_files)
    summary = GraphBuildSummary()

    # Pass 1: every file's own nodes (+ locally-safe edges) — see the
    # module docstring. pending_by_file keeps each file's deferred
    # cross-file edges separate so pass 2 can still write them one
    # file-scoped transaction at a time.
    pending_by_file: list[list[_PendingEdge]] = []
    for parsed_file in parsed_files:
        line_count = line_counts.get(parsed_file.file_path)
        unresolved, pending = _write_file_graph(
            client, metadata.repository_id, parsed_file, index, line_count
        )
        summary.unresolved_call_count += unresolved
        summary.files_processed += 1
        pending_by_file.append(pending)

    # Pass 2: cross-file edges, now that every file's nodes exist.
    for pending in pending_by_file:
        if not pending:
            continue

        def _write_pending(tx: "ManagedTransaction", pending: list[_PendingEdge] = pending) -> None:
            for edge in pending:
                tx.run(edge.query, edge.params)

        client.run_write_transaction(_write_pending)

    client.execute_write(
        queries.SET_REPOSITORY_UNRESOLVED_CALL_COUNT,
        {
            "repository_id": metadata.repository_id,
            "unresolved_call_count": summary.unresolved_call_count,
        },
    )
    return summary


def delete_repository_graph(client: Neo4jClient, repository_id: str) -> None:
    """Remove every node (and its relationships) for one repository_id.

    Never touches another repository's data — the MATCH is always scoped
    by repository_id (see DATA_MODEL.md "Isolation rule").
    """
    client.execute_write(queries.DELETE_REPOSITORY_GRAPH, {"repository_id": repository_id})


def _upsert_repository(client: Neo4jClient, metadata: RepositoryMetadata) -> None:
    client.execute_write(
        queries.UPSERT_REPOSITORY,
        {
            "repository_id": metadata.repository_id,
            "name": metadata.name,
            "source_type": metadata.source_type,
            "source_url": metadata.source_url,
            "default_branch": metadata.default_branch,
            "commit_hash": metadata.commit_hash,
            "analyzed_at": utc_now_iso(),
            "parser_version": metadata.parser_version,
        },
    )


def _directory_path(file_path: str) -> str | None:
    parent = PurePosixPath(file_path).parent
    return None if str(parent) == "." else str(parent)


def _upsert_directory_hierarchy(
    client: Neo4jClient, repository_id: str, file_paths: list[str]
) -> None:
    directory_paths: set[str] = set()
    for file_path in file_paths:
        directory_path = _directory_path(file_path)
        if directory_path is None:
            continue
        parts = PurePosixPath(directory_path).parts
        for i in range(1, len(parts) + 1):
            directory_paths.add("/".join(parts[:i]))

    for path in sorted(directory_paths):
        name = path.rsplit("/", 1)[-1]
        client.execute_write(
            queries.UPSERT_DIRECTORY, {"repository_id": repository_id, "path": path, "name": name}
        )

    for path in sorted(directory_paths):
        if "/" in path:
            parent_path = path.rsplit("/", 1)[0]
            client.execute_write(
                queries.CONTAINS_DIRECTORY_DIRECTORY,
                {"repository_id": repository_id, "parent_path": parent_path, "child_path": path},
            )
        else:
            client.execute_write(
                queries.CONTAINS_REPOSITORY_DIRECTORY,
                {"repository_id": repository_id, "path": path},
            )


def _local_symbol_index(parsed_file: ParsedFile) -> dict[str, tuple[NodeLabel, str]]:
    """qualified_name -> (label, node_id) for every symbol *in this file
    only* — used to infer a flattened function's true DEFINES parent."""
    local: dict[str, tuple[NodeLabel, str]] = {}

    def visit_class(cls: ParsedClass) -> None:
        local[cls.qualified_name] = (NodeLabel.CLASS, cls.id)
        for method in cls.methods:
            local[method.qualified_name] = (NodeLabel.METHOD, method.id)
        for nested in cls.nested_classes:
            visit_class(nested)

    for cls in parsed_file.classes:
        visit_class(cls)
    for func in parsed_file.functions:
        local[func.qualified_name] = (NodeLabel.FUNCTION, func.id)

    return local


def _infer_local_parent(
    qualified_name: str, local_index: dict[str, tuple[NodeLabel, str]]
) -> tuple[NodeLabel, str] | None:
    if "." not in qualified_name:
        return None
    parent_name = qualified_name.rsplit(".", 1)[0]
    return local_index.get(parent_name)


def _write_file_graph(
    client: Neo4jClient,
    repository_id: str,
    parsed_file: ParsedFile,
    index: RepositoryIndex,
    line_count: int | None,
) -> tuple[int, list[_PendingEdge]]:
    local_index = _local_symbol_index(parsed_file)
    pending: list[_PendingEdge] = []

    def work(tx: "ManagedTransaction") -> int:
        unresolved = 0
        base = {"repository_id": repository_id, "file_path": parsed_file.file_path}

        # 1. Idempotent reanalysis: this file's own previous descendants
        # are removed before its current parse is (re-)inserted, all in
        # this one transaction.
        tx.run(queries.DELETE_STALE_FILE_SYMBOLS, base)
        tx.run(queries.DELETE_STALE_FILE_ENDPOINTS, base)
        tx.run(queries.DELETE_STALE_FILE_OUTGOING_EDGES, base)

        # 2. File + containment + Module identity.
        tx.run(
            queries.UPSERT_FILE,
            {
                **base,
                "id": parsed_file.id,
                "language": parsed_file.language,
                "content_hash": parsed_file.content_hash,
                "module_name": parsed_file.module_name,
                "line_count": line_count,
                "parse_error_count": len(parsed_file.parse_errors),
            },
        )
        tx.run(queries.CONTAINS_REPOSITORY_FILE, base)
        directory_path = _directory_path(parsed_file.file_path)
        if directory_path is not None:
            tx.run(queries.CONTAINS_DIRECTORY_FILE, {**base, "directory_path": directory_path})

        tx.run(
            queries.UPSERT_MODULE,
            {
                "repository_id": repository_id,
                "id": parsed_file.id,
                "qualified_name": parsed_file.module_name,
                "name": parsed_file.module_name.rsplit(".", 1)[-1]
                if parsed_file.module_name
                else "",
                "file_path": parsed_file.file_path,
            },
        )
        tx.run(queries.DEFINES_FILE_MODULE, {**base, "qualified_name": parsed_file.module_name})

        # 3. Classes (recursive) — methods, nested classes, parameters, inheritance.
        for cls in parsed_file.classes:
            unresolved += _write_class(
                tx,
                repository_id,
                parsed_file,
                cls,
                parent_label=NodeLabel.FILE,
                parent_id=parsed_file.id,
                index=index,
                pending=pending,
            )

        # 4. Flattened functions (top-level + nested), DEFINES parent inferred locally.
        for func in parsed_file.functions:
            unresolved += _write_function(
                tx, repository_id, parsed_file, func, index=index, pending=pending
            )
            parent = _infer_local_parent(func.qualified_name, local_index)
            if parent is not None:
                parent_label, parent_id = parent
                tx.run(
                    queries.defines_query(parent_label, NodeLabel.FUNCTION),
                    {"repository_id": repository_id, "parent_id": parent_id, "child_id": func.id},
                )
            else:
                tx.run(
                    queries.defines_query(NodeLabel.FILE, NodeLabel.FUNCTION),
                    {
                        "repository_id": repository_id,
                        "parent_id": parsed_file.id,
                        "child_id": func.id,
                    },
                )
            _write_endpoint_if_route(tx, repository_id, func, NodeLabel.FUNCTION)

        # 5. Imports.
        for imp in parsed_file.imports:
            _write_import(tx, repository_id, parsed_file, imp, index, pending=pending)

        return unresolved

    unresolved = client.run_write_transaction(work)
    return unresolved, pending


def _write_class(
    tx: "ManagedTransaction",
    repository_id: str,
    parsed_file: ParsedFile,
    cls: ParsedClass,
    *,
    parent_label: NodeLabel,
    parent_id: str,
    index: RepositoryIndex,
    pending: list[_PendingEdge],
) -> int:
    unresolved = 0
    tx.run(
        queries.UPSERT_CLASS,
        class_properties(cls, repository_id=repository_id, file_path=parsed_file.file_path),
    )
    tx.run(
        queries.defines_query(parent_label, NodeLabel.CLASS),
        {"repository_id": repository_id, "parent_id": parent_id, "child_id": cls.id},
    )

    for base_expression in cls.base_classes:
        resolved = resolve_base_class(
            base_expression,
            caller_module=parsed_file.module_name,
            imports=parsed_file.imports,
            index=index,
        )
        if resolved is not None:
            # Deferred: the base class may be defined in a file not yet
            # written — see module docstring "Two-pass write".
            pending.append(
                _PendingEdge(
                    queries.extends_query(NodeLabel.CLASS),
                    {
                        "repository_id": repository_id,
                        "child_id": cls.id,
                        "parent_id": resolved.node_id,
                    },
                )
            )
        else:
            dependency_id = _external_dependency_id(repository_id, base_expression)
            tx.run(
                queries.UPSERT_EXTERNAL_DEPENDENCY,
                {
                    "repository_id": repository_id,
                    "id": dependency_id,
                    "name": base_expression,
                    "import_alias": None,
                    "dependency_type": "base_class",
                    "is_standard_library": False,
                },
            )
            tx.run(
                queries.depends_on_query(NodeLabel.CLASS),
                {
                    "repository_id": repository_id,
                    "source_id": cls.id,
                    "dependency_name": base_expression,
                },
            )

    for method in cls.methods:
        unresolved += _write_function(
            tx,
            repository_id,
            parsed_file,
            method,
            index=index,
            pending=pending,
            label=NodeLabel.METHOD,
        )
        tx.run(
            queries.defines_query(NodeLabel.CLASS, NodeLabel.METHOD),
            {"repository_id": repository_id, "parent_id": cls.id, "child_id": method.id},
        )
        _write_endpoint_if_route(tx, repository_id, method, NodeLabel.METHOD)

    for nested in cls.nested_classes:
        unresolved += _write_class(
            tx,
            repository_id,
            parsed_file,
            nested,
            parent_label=NodeLabel.CLASS,
            parent_id=cls.id,
            index=index,
            pending=pending,
        )

    return unresolved


def _write_function(
    tx: "ManagedTransaction",
    repository_id: str,
    parsed_file: ParsedFile,
    func: ParsedFunction,
    *,
    index: RepositoryIndex,
    pending: list[_PendingEdge],
    label: NodeLabel = NodeLabel.FUNCTION,
) -> int:
    tx.run(
        queries.upsert_function_or_method_query(label),
        function_properties(func, repository_id=repository_id, file_path=parsed_file.file_path),
    )

    for param in func.parameters:
        tx.run(queries.UPSERT_PARAMETER, parameter_properties(param, repository_id=repository_id))
        tx.run(
            queries.has_parameter_query(label),
            {"repository_id": repository_id, "owner_id": func.id, "parameter_id": param.id},
        )

    unresolved = 0
    for call in func.calls:
        resolution = resolve_call(
            call,
            caller_module=parsed_file.module_name,
            caller_class_qualified_name=func.parent_class,
            imports=parsed_file.imports,
            index=index,
        )
        if (
            resolution.confidence is CallResolutionConfidence.UNRESOLVED
            or resolution.target is None
        ):
            unresolved += 1
            continue
        # Deferred: the callee may be defined in a file not yet written —
        # see module docstring "Two-pass write".
        pending.append(
            _PendingEdge(
                queries.calls_query(label, resolution.target.label),
                {
                    "repository_id": repository_id,
                    "caller_id": func.id,
                    "callee_id": resolution.target.node_id,
                    "call_site_line": call.location.start_line,
                    "called_expression": call.called_expression,
                    "call_site_file": parsed_file.file_path,
                    "resolution_confidence": resolution.confidence.value,
                    "resolution_strategy": resolution.strategy.value,
                },
            )
        )

    return unresolved


def _write_endpoint_if_route(
    tx: "ManagedTransaction", repository_id: str, func: ParsedFunction, handler_label: NodeLabel
) -> None:
    for decorator in func.decorators:
        if decorator.route_info is None:
            continue
        endpoint_id = generate_symbol_id(
            repository_id=repository_id,
            file_path=func.location.file_path,
            symbol_type="api_endpoint",
            qualified_name=f"{decorator.route_info.http_method}:{decorator.route_info.path}:{func.qualified_name}",
            start_line=func.location.start_line,
        )
        tx.run(
            queries.UPSERT_API_ENDPOINT,
            {
                "repository_id": repository_id,
                "id": endpoint_id,
                "framework_hint": "unknown",
                "http_method": decorator.route_info.http_method,
                "route_path": decorator.route_info.path,
                "decorator_expression": decorator.raw_expression,
                "file_path": func.location.file_path,
                "start_line": func.location.start_line,
            },
        )
        tx.run(
            queries.handled_by_query(handler_label),
            {"repository_id": repository_id, "endpoint_id": endpoint_id, "handler_id": func.id},
        )


def _external_dependency_id(repository_id: str, name: str) -> str:
    return generate_symbol_id(
        repository_id=repository_id,
        file_path="",
        symbol_type="external_dependency",
        qualified_name=name,
        start_line=0,
    )


def _write_import(
    tx: "ManagedTransaction",
    repository_id: str,
    parsed_file: ParsedFile,
    imp: ParsedImport,
    index: RepositoryIndex,
    *,
    pending: list[_PendingEdge],
) -> None:
    resolved_module = resolve_import_target(
        imp,
        file_path=parsed_file.file_path,
        module_name=parsed_file.module_name,
        known_modules=index.known_modules,
    )
    relationship_params = {
        "repository_id": repository_id,
        "file_path": parsed_file.file_path,
        "alias": imp.alias,
        "imported_names": list(imp.imported_names),
        "relative_level": imp.relative_level,
        "raw_import": imp.module or "",
    }

    if resolved_module is not None:
        # Deferred: the imported module may not be written yet — see
        # module docstring "Two-pass write".
        pending.append(
            _PendingEdge(
                queries.IMPORTS_FILE_MODULE,
                {**relationship_params, "target_qualified_name": resolved_module},
            )
        )
        return

    dependency_name = imp.module or (imp.imported_names[0] if imp.imported_names else "unknown")
    dependency_id = _external_dependency_id(repository_id, dependency_name)
    tx.run(
        queries.UPSERT_EXTERNAL_DEPENDENCY,
        {
            "repository_id": repository_id,
            "id": dependency_id,
            "name": dependency_name,
            "import_alias": imp.alias,
            "dependency_type": "import",
            "is_standard_library": _looks_like_stdlib(dependency_name),
        },
    )
    tx.run(
        queries.IMPORTS_FILE_EXTERNAL_DEPENDENCY,
        {**relationship_params, "dependency_name": dependency_name},
    )


_STDLIB_TOP_LEVEL_MODULES = frozenset(
    {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "pathlib",
        "typing",
        "collections",
        "itertools",
        "functools",
        "logging",
        "subprocess",
        "hashlib",
        "uuid",
        "enum",
        "dataclasses",
        "abc",
        "io",
        "asyncio",
        "unittest",
        "http",
        "urllib",
        "socket",
        "threading",
        "multiprocessing",
        "sqlite3",
        "csv",
        "shutil",
        "tempfile",
        "copy",
        "string",
        "random",
        "argparse",
        "contextlib",
    }
)


def _looks_like_stdlib(dependency_name: str) -> bool:
    """A plain, deterministic top-level-name check — not a real package
    index lookup (no network access here by design)."""
    return dependency_name.split(".", 1)[0] in _STDLIB_TOP_LEVEL_MODULES
