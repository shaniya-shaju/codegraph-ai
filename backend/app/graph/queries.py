"""Every Cypher string used by this package.

Values are always passed as ``$parameters`` — never string-interpolated
(see SECURITY.md "Use parameterized Cypher" / "Never build Cypher by
directly interpolating user input"). Labels and relationship types have
no parameter syntax in Cypher at all, so where they must appear in the
query text they are filled in only from ``app.domain.graph.enums``
members (a closed, code-defined allow-list — never a raw string that
originated from a request). The one deliberate exception is the
variable-length traversal depth in ``neighbor_subgraph_query`` /
``path_between_query``: Cypher does not support a parameter for a
pattern's hop-count bound either, so the (already range-validated,
plain-``int``) depth is interpolated as a numeric literal, never a string
— see repository_graph_service.py, which validates it before this module
ever sees it.
"""

from app.domain.graph.enums import NodeLabel, RelationshipType

SEARCHABLE_LABELS = [
    NodeLabel.MODULE.value,
    NodeLabel.CLASS.value,
    NodeLabel.FUNCTION.value,
    NodeLabel.METHOD.value,
    NodeLabel.API_ENDPOINT.value,
]

ALLOWED_RELATIONSHIP_TYPES = frozenset(r.value for r in RelationshipType)

# --- writes: upserts (see graph_builder.py) --------------------------------

UPSERT_REPOSITORY = """
MERGE (r:Repository {repository_id: $repository_id})
SET r.name = $name,
    r.source_type = $source_type,
    r.source_url = $source_url,
    r.default_branch = $default_branch,
    r.commit_hash = $commit_hash,
    r.analyzed_at = $analyzed_at,
    r.parser_version = $parser_version
"""

UPSERT_DIRECTORY = """
MERGE (d:Directory {repository_id: $repository_id, path: $path})
SET d.name = $name
"""

CONTAINS_REPOSITORY_DIRECTORY = """
MATCH (r:Repository {repository_id: $repository_id})
MATCH (d:Directory {repository_id: $repository_id, path: $path})
MERGE (r)-[:CONTAINS]->(d)
"""

CONTAINS_DIRECTORY_DIRECTORY = """
MATCH (parent:Directory {repository_id: $repository_id, path: $parent_path})
MATCH (child:Directory {repository_id: $repository_id, path: $child_path})
MERGE (parent)-[:CONTAINS]->(child)
"""

UPSERT_FILE = """
MERGE (f:File {repository_id: $repository_id, file_path: $file_path})
SET f.id = $id,
    f.language = $language,
    f.content_hash = $content_hash,
    f.module_name = $module_name,
    f.line_count = $line_count,
    f.parse_error_count = $parse_error_count
"""

CONTAINS_DIRECTORY_FILE = """
MATCH (d:Directory {repository_id: $repository_id, path: $directory_path})
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
MERGE (d)-[:CONTAINS]->(f)
"""

CONTAINS_REPOSITORY_FILE = """
MATCH (r:Repository {repository_id: $repository_id})
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
MERGE (r)-[:CONTAINS]->(f)
"""

# Reanalysis strategy (see graph_builder.py): delete this file's own
# descendant symbols/relationships before re-inserting the current parse,
# all inside one write transaction with the fresh upserts that follow.
DELETE_STALE_FILE_SYMBOLS = """
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
OPTIONAL MATCH (f)-[:DEFINES*1..10]->(sym)
WHERE sym:Class OR sym:Function OR sym:Method
OPTIONAL MATCH (sym)-[:HAS_PARAMETER]->(param:Parameter)
DETACH DELETE sym, param
"""

DELETE_STALE_FILE_ENDPOINTS = """
MATCH (e:APIEndpoint {repository_id: $repository_id, file_path: $file_path})
DETACH DELETE e
"""

DELETE_STALE_FILE_OUTGOING_EDGES = """
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})-[r:IMPORTS|DEPENDS_ON]->()
DELETE r
"""

UPSERT_MODULE = """
MERGE (m:Module {repository_id: $repository_id, qualified_name: $qualified_name})
SET m.id = $id, m.name = $name, m.file_path = $file_path
"""

DEFINES_FILE_MODULE = """
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
MATCH (m:Module {repository_id: $repository_id, qualified_name: $qualified_name})
MERGE (f)-[:DEFINES]->(m)
"""

UPSERT_CLASS = """
MERGE (c:Class {repository_id: $repository_id, qualified_name: $qualified_name})
SET c.id = $id, c.name = $name, c.file_path = $file_path,
    c.start_line = $start_line, c.end_line = $end_line,
    c.docstring_summary = $docstring_summary,
    c.decorators = $decorators, c.base_class_names = $base_class_names
"""


def upsert_function_or_method_query(label: NodeLabel) -> str:
    """Shared shape for Function/Method — only the label differs, and
    `label` only ever comes from NodeLabel (never a request value)."""
    return f"""
MERGE (fn:{label.value} {{
    repository_id: $repository_id, qualified_name: $qualified_name, start_line: $start_line
}})
SET fn.id = $id, fn.name = $name, fn.signature = $signature, fn.file_path = $file_path,
    fn.end_line = $end_line, fn.async_function = $async_function, fn.decorators = $decorators,
    fn.return_annotation = $return_annotation, fn.branch_count = $branch_count,
    fn.loop_count = $loop_count, fn.exception_handler_count = $exception_handler_count,
    fn.return_count = $return_count, fn.await_count = $await_count,
    fn.nested_function_count = $nested_function_count
"""


def defines_query(parent_label: NodeLabel, child_label: NodeLabel) -> str:
    """A DEFINES edge between two already-upserted nodes, matched by id."""
    return f"""
MATCH (parent:{parent_label.value} {{repository_id: $repository_id, id: $parent_id}})
MATCH (child:{child_label.value} {{repository_id: $repository_id, id: $child_id}})
MERGE (parent)-[:DEFINES]->(child)
"""


UPSERT_PARAMETER = """
MERGE (p:Parameter {repository_id: $repository_id, id: $id})
SET p.name = $name, p.annotation = $annotation, p.default_value = $default_value,
    p.kind = $kind, p.position = $position
"""


def has_parameter_query(owner_label: NodeLabel) -> str:
    return f"""
MATCH (owner:{owner_label.value} {{repository_id: $repository_id, id: $owner_id}})
MATCH (p:Parameter {{repository_id: $repository_id, id: $parameter_id}})
MERGE (owner)-[:HAS_PARAMETER]->(p)
"""


UPSERT_EXTERNAL_DEPENDENCY = """
MERGE (e:ExternalDependency {repository_id: $repository_id, name: $name})
SET e.id = $id, e.import_alias = $import_alias, e.dependency_type = $dependency_type,
    e.is_standard_library = $is_standard_library
"""

IMPORTS_FILE_MODULE = """
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
MATCH (m:Module {repository_id: $repository_id, qualified_name: $target_qualified_name})
MERGE (f)-[r:IMPORTS]->(m)
SET r.alias = $alias, r.imported_names = $imported_names, r.relative_level = $relative_level,
    r.raw_import = $raw_import
"""

IMPORTS_FILE_EXTERNAL_DEPENDENCY = """
MATCH (f:File {repository_id: $repository_id, file_path: $file_path})
MATCH (e:ExternalDependency {repository_id: $repository_id, name: $dependency_name})
MERGE (f)-[r:IMPORTS]->(e)
SET r.alias = $alias, r.imported_names = $imported_names, r.relative_level = $relative_level,
    r.raw_import = $raw_import
"""


def depends_on_query(source_label: NodeLabel) -> str:
    return f"""
MATCH (source:{source_label.value} {{repository_id: $repository_id, id: $source_id}})
MATCH (e:ExternalDependency {{repository_id: $repository_id, name: $dependency_name}})
MERGE (source)-[:DEPENDS_ON]->(e)
"""


def extends_query(child_label: NodeLabel) -> str:
    return f"""
MATCH (child:{child_label.value} {{repository_id: $repository_id, id: $child_id}})
MATCH (parent:Class {{repository_id: $repository_id, id: $parent_id}})
MERGE (child)-[:EXTENDS]->(parent)
"""


def calls_query(caller_label: NodeLabel, callee_label: NodeLabel) -> str:
    return f"""
MATCH (caller:{caller_label.value} {{repository_id: $repository_id, id: $caller_id}})
MATCH (callee:{callee_label.value} {{repository_id: $repository_id, id: $callee_id}})
MERGE (caller)-[r:CALLS {{
    call_site_line: $call_site_line, called_expression: $called_expression
}}]->(callee)
SET r.call_site_file = $call_site_file, r.resolution_confidence = $resolution_confidence,
    r.resolution_strategy = $resolution_strategy
"""


def handled_by_query(handler_label: NodeLabel) -> str:
    return f"""
MATCH (endpoint:APIEndpoint {{repository_id: $repository_id, id: $endpoint_id}})
MATCH (handler:{handler_label.value} {{repository_id: $repository_id, id: $handler_id}})
MERGE (endpoint)-[:HANDLED_BY]->(handler)
"""


UPSERT_API_ENDPOINT = """
MERGE (e:APIEndpoint {repository_id: $repository_id, id: $id})
SET e.framework_hint = $framework_hint, e.http_method = $http_method, e.route_path = $route_path,
    e.decorator_expression = $decorator_expression, e.file_path = $file_path,
    e.start_line = $start_line
"""

SET_REPOSITORY_UNRESOLVED_CALL_COUNT = """
MATCH (r:Repository {repository_id: $repository_id})
SET r.unresolved_call_count = $unresolved_call_count
"""

DELETE_REPOSITORY_GRAPH = """
MATCH (n {repository_id: $repository_id})
DETACH DELETE n
"""

# --- reads: bounded, repository-scoped (see repository_graph_service.py) --

SEARCH_SYMBOLS = """
MATCH (n {repository_id: $repository_id})
WHERE any(l IN labels(n) WHERE l IN $searchable_labels)
  AND ($symbol_type IS NULL OR $symbol_type IN labels(n))
  AND ($file_path IS NULL OR n.file_path = $file_path)
  AND (
    toLower(n.name) CONTAINS toLower($query)
    OR (n.qualified_name IS NOT NULL AND toLower(n.qualified_name) CONTAINS toLower($query))
    OR (n.route_path IS NOT NULL AND toLower(n.route_path) CONTAINS toLower($query))
  )
RETURN n
LIMIT $limit
"""

GET_SYMBOL_BY_ID = """
MATCH (n {repository_id: $repository_id, id: $symbol_id})
RETURN n
LIMIT 1
"""

GET_DIRECT_CALLERS = """
MATCH (caller)-[r:CALLS]->(target {repository_id: $repository_id, id: $symbol_id})
WHERE caller.repository_id = $repository_id
RETURN caller, r
LIMIT $limit
"""

GET_DIRECT_CALLEES = """
MATCH (source {repository_id: $repository_id, id: $symbol_id})-[r:CALLS]->(callee)
WHERE callee.repository_id = $repository_id
RETURN callee, r
LIMIT $limit
"""

GET_DEPENDENCIES = """
MATCH (source {repository_id: $repository_id, id: $symbol_id})
      -[r:IMPORTS|DEPENDS_ON|EXTENDS]->(target)
RETURN target, r
LIMIT $limit
"""


def neighbor_subgraph_query(depth: int) -> str:
    """`depth` is a plain int, already validated against
    graph_max_traversal_depth before this is called — see the module
    docstring on why this is the one literal (not `$param`) interpolation."""
    return f"""
MATCH (root {{repository_id: $repository_id, id: $symbol_id}})
MATCH path = (root)-[*1..{depth}]-(other {{repository_id: $repository_id}})
WITH root, other, relationships(path) AS rels
UNWIND rels AS r
RETURN DISTINCT root, other, r
LIMIT $limit
"""


def repository_overview_query(depth: int) -> str:
    return f"""
MATCH (root:Repository {{repository_id: $repository_id}})
MATCH path = (root)-[*1..{depth}]-(other {{repository_id: $repository_id}})
WITH root, other, relationships(path) AS rels
UNWIND rels AS r
RETURN DISTINCT root, other, r
LIMIT $limit
"""


def path_between_query(max_depth: int) -> str:
    return f"""
MATCH (source {{repository_id: $repository_id, id: $source_symbol_id}})
MATCH (target {{repository_id: $repository_id, id: $target_symbol_id}})
MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
RETURN path
LIMIT 1
"""


GET_GRAPH_STATISTICS_NODE_COUNTS = """
MATCH (n {repository_id: $repository_id})
UNWIND labels(n) AS label
RETURN label, count(*) AS count
"""

GET_GRAPH_STATISTICS_RELATIONSHIP_COUNTS = """
MATCH (a {repository_id: $repository_id})-[r]->(b {repository_id: $repository_id})
RETURN type(r) AS relationship_type, count(*) AS count
"""

# Unresolved calls never get a CALLS edge at all (there is no internal
# target to connect to — see relationship_resolver.py), so this can't be
# counted from edges. graph_builder.py tallies it in Python while writing
# and stores the total on the Repository node instead.
GET_UNRESOLVED_CALL_COUNT = """
MATCH (r:Repository {repository_id: $repository_id})
RETURN coalesce(r.unresolved_call_count, 0) AS count
"""

GET_PARSE_ERROR_COUNT = """
MATCH (f:File {repository_id: $repository_id})
RETURN coalesce(sum(f.parse_error_count), 0) AS count
"""
