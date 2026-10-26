"""Call-expression extraction: syntax-only classification, never resolution.

See ARCHITECTURE.md "Tree-sitter parsing flow" and the parsing task's
explicit non-goal: this module extracts call *expressions* deterministically
from syntax shape alone. It never claims a call has been resolved to a
concrete symbol — that is a later stage's job (see AGENTS.md rule 2 and
the parsing task's non-goals: "Cross-file call resolution").

Design: a single whole-tree query pass buckets every call/branch/loop/
except/return/await/nested-function node by its *nearest enclosing*
function_definition (keyed by that function's (start_byte, end_byte)).
symbol_builder then looks up each function's bucket by that same key when
it builds the corresponding ParsedFunction. This avoids double-counting a
nested function's internals in its parent's complexity signals: a node's
nearest enclosing function is always the innermost one.
"""

from tree_sitter import Node

from app.domain.code_symbols.enums import CallType, SymbolType
from app.domain.code_symbols.models import ParsedCall
from app.parsing.models import FunctionSignals
from app.parsing.python.queries import FUNCTION_SIGNAL_QUERY
from app.parsing.source_utils import generate_symbol_id, node_text, node_to_location


def _nearest_enclosing_function(node: Node) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            return current
        current = current.parent
    return None


def collect_function_signals(root: Node) -> dict[tuple[int, int], FunctionSignals]:
    """Bucket calls/complexity-signal nodes by nearest enclosing function.

    Nodes with no enclosing function (module- or class-body-level, outside
    any method) are intentionally dropped — see models.py's module
    docstring on why ParsedFile has no top-level `calls`.
    """
    buckets: dict[tuple[int, int], FunctionSignals] = {}

    for node, capture_name in FUNCTION_SIGNAL_QUERY.captures(root):
        enclosing = _nearest_enclosing_function(node)
        if enclosing is None:
            continue

        key = (enclosing.start_byte, enclosing.end_byte)
        signals = buckets.setdefault(key, FunctionSignals())

        if capture_name == "call":
            signals.call_nodes.append(node)
        elif capture_name == "branch":
            signals.branch_count += 1
        elif capture_name == "loop":
            signals.loop_count += 1
        elif capture_name == "except_handler":
            signals.exception_handler_count += 1
        elif capture_name == "return_stmt":
            signals.return_count += 1
        elif capture_name == "await_expr":
            signals.await_count += 1
        elif capture_name == "nested_function":
            signals.nested_function_count += 1

    return buckets


def _classify_call(call_node: Node) -> tuple[CallType, str | None]:
    function_expr = call_node.child_by_field_name("function")
    if function_expr is None:
        return CallType.DYNAMIC_OR_UNKNOWN, None

    if function_expr.type == "identifier":
        name = node_text(function_expr)
        if name[:1].isupper():
            return CallType.CONSTRUCTOR_CANDIDATE, name
        return CallType.DIRECT, name

    if function_expr.type == "attribute":
        attribute_field = function_expr.child_by_field_name("attribute")
        object_field = function_expr.child_by_field_name("object")
        if attribute_field is None or object_field is None:
            return CallType.DYNAMIC_OR_UNKNOWN, None

        # Only a plain attribute chain rooted in an identifier is
        # statically attributable (self.repo.users.find(), auth.login()).
        # A call or subscript as the root (get_service().login()) is not.
        root: Node | None = object_field
        while root is not None and root.type == "attribute":
            root = root.child_by_field_name("object")
        if root is None or root.type != "identifier":
            return CallType.DYNAMIC_OR_UNKNOWN, None

        return CallType.ATTRIBUTE, node_text(attribute_field)

    return CallType.DYNAMIC_OR_UNKNOWN, None


def _count_arguments(call_node: Node) -> int:
    arguments = call_node.child_by_field_name("arguments")
    if arguments is None:
        return 0
    return sum(1 for child in arguments.children if child.type not in ("(", ")", ","))


def build_parsed_call(
    call_node: Node,
    *,
    caller_qualified_name: str,
    file_path: str,
    repository_id: str,
) -> ParsedCall:
    call_type, probable_target_name = _classify_call(call_node)
    location = node_to_location(call_node, file_path)

    function_expr = call_node.child_by_field_name("function")
    called_expression = (
        node_text(function_expr) if function_expr is not None else node_text(call_node)
    )

    symbol_id = generate_symbol_id(
        repository_id=repository_id,
        file_path=file_path,
        symbol_type=SymbolType.CALL.value,
        qualified_name=f"{caller_qualified_name}::{called_expression}",
        start_line=location.start_line,
    )

    return ParsedCall(
        id=symbol_id,
        caller_qualified_name=caller_qualified_name,
        called_expression=called_expression,
        probable_target_name=probable_target_name,
        call_type=call_type,
        argument_count=_count_arguments(call_node),
        location=location,
    )
