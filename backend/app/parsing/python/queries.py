"""Tree-sitter query objects for the Python grammar.

Pinned to tree-sitter 0.22.x's ``Query.captures()`` API, which returns
``list[tuple[Node, str]]`` — this shape changed in 0.23+ (dict-based).
See backend/pyproject.toml's version pin; if it ever moves past 0.23,
every ``.captures(...)`` call site in this package needs re-checking.
"""

import tree_sitter_python as tspython
from tree_sitter import Language, Query

PY_LANGUAGE = Language(tspython.language())

IMPORT_QUERY = Query(
    PY_LANGUAGE,
    """
    (import_statement) @import_statement
    (import_from_statement) @import_from_statement
    """,
)

# Single combined query for call_extractor's whole-tree bucketing pass:
# every node type that needs to be attributed to its nearest enclosing
# function_definition (see call_extractor.collect_function_signals).
FUNCTION_SIGNAL_QUERY = Query(
    PY_LANGUAGE,
    """
    (call) @call
    (if_statement) @branch
    (match_statement) @branch
    (for_statement) @loop
    (while_statement) @loop
    (except_clause) @except_handler
    (except_group_clause) @except_handler
    (return_statement) @return_stmt
    (await) @await_expr
    (function_definition) @nested_function
    """,
)

# HTTP-method-shaped decorator attribute names recognized as API routes,
# independent of any specific framework's import (see the parsing task's
# "Recognize common API decorators without coupling to one framework").
HTTP_METHOD_DECORATOR_NAMES = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)
ROUTE_DECORATOR_NAME = "route"
