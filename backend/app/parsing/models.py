"""Parser-internal working types.

Not part of the domain output contract (see app.domain.code_symbols) —
these exist only while a single file is being parsed, threaded between
app.parsing.python.parser / symbol_builder / call_extractor. Consumers of
ParsedFile never see these.
"""

from dataclasses import dataclass, field

from tree_sitter import Node, Tree


@dataclass(frozen=True)
class ParseContext:
    """Everything the Python symbol builder needs for one parse call."""

    source_bytes: bytes
    tree: Tree
    file_path: str
    module_name: str
    repository_id: str
    parser_version: str


@dataclass
class FunctionSignals:
    """Mutable accumulator for one function's calls/complexity counts,
    populated by a single whole-tree bucketing pass (see
    app.parsing.python.call_extractor) keyed by each function_definition
    node's (start_byte, end_byte).
    """

    branch_count: int = 0
    loop_count: int = 0
    exception_handler_count: int = 0
    return_count: int = 0
    await_count: int = 0
    nested_function_count: int = 0
    call_nodes: list[Node] = field(default_factory=list)
