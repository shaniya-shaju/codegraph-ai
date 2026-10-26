"""Builds the human/embedding-ready text representation for each chunk type.

Deterministic, template-based formatting only — never an LLM-generated
summary (AGENTS.md rule 2/8, and the indexing task's "Do not add an
LLM-generated summary"). Every field here comes directly from
app.domain.code_symbols (the parser's output), never inferred.
"""

import re

from app.domain.code_symbols.models import ParsedClass, ParsedDecorator, ParsedFile, ParsedFunction
from app.domain.graph.enums import NodeLabel

_MAX_RELEVANT_IMPORTS = 20
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _display_signature(signature: str) -> str:
    """`"async def login(...) -> Token:"` -> `"login(...) -> Token"` — the
    parser's own `signature` field keeps `def`/`:` for source fidelity;
    the embedding text drops them per the suggested text format."""
    text = signature.strip()
    text = re.sub(r"^(async\s+)?def\s+", "", text)
    return text.removesuffix(":").strip()


def _bound_import_display_names(parsed_file: ParsedFile) -> list[tuple[str, str]]:
    """(bound_local_name, dotted_display_path) pairs for every import in
    this file — used both to render "Relevant imports" and to decide
    relevance by scanning a function's source text for the bound name."""
    pairs: list[tuple[str, str]] = []
    for imp in parsed_file.imports:
        if not imp.is_from_import:
            if imp.module is None:
                continue
            bound = imp.alias or imp.module.split(".", 1)[0]
            pairs.append((bound, imp.module))
            continue
        prefix = imp.module or ""
        for name in imp.imported_names:
            if name == "*":
                continue
            display = f"{prefix}.{name}" if prefix else name
            pairs.append((name, display))
    return pairs


def _relevant_imports_for(source_code: str, parsed_file: ParsedFile) -> list[str]:
    tokens = set(_IDENTIFIER_PATTERN.findall(source_code))
    relevant = [
        display for bound, display in _bound_import_display_names(parsed_file) if bound in tokens
    ]
    # stable order, de-duplicated, capped
    seen: set[str] = set()
    ordered: list[str] = []
    for name in relevant:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered[:_MAX_RELEVANT_IMPORTS]


def _decorator_names(decorators: list[ParsedDecorator]) -> str:
    if not decorators:
        return "none"
    return ", ".join(d.raw_expression for d in decorators)


def _complexity_lines(func: ParsedFunction) -> str:
    signals = func.complexity_signals
    return (
        "Complexity:\n"
        f"- branches: {signals.branch_count}\n"
        f"- loops: {signals.loop_count}\n"
        f"- exception handlers: {signals.exception_handler_count}\n"
        f"- returns: {signals.return_count}\n"
        f"- awaits: {signals.await_count}"
    )


def build_function_text(
    func: ParsedFunction,
    *,
    file_path: str,
    label: NodeLabel,
    parsed_file: ParsedFile,
) -> str:
    """Text for a FUNCTION or METHOD chunk — see the indexing task's
    suggested format."""
    relevant_imports = _relevant_imports_for(func.source_code, parsed_file)
    imports_block = (
        "\n".join(f"- {name}" for name in relevant_imports) if relevant_imports else "none"
    )
    docstring = func.docstring.strip() if func.docstring else "none"

    lines = [
        f"Symbol: {func.qualified_name}",
        f"Type: {label.value.lower()}",
        f"File: {file_path}",
        f"Lines: {func.location.start_line}-{func.location.end_line}",
        f"Signature: {_display_signature(func.signature)}",
        f"Parent class: {func.parent_class or 'none'}",
        f"Decorators: {_decorator_names(func.decorators)}",
        f"Returns: {func.return_annotation or 'none'}",
        f"Docstring: {docstring}",
        _complexity_lines(func),
        "Relevant imports:",
        imports_block,
        "",
        "Source:",
        func.source_code,
    ]
    return "\n".join(lines)


def build_class_overview_text(cls: ParsedClass, *, file_path: str, include_source: bool) -> str:
    """Text for a CLASS chunk. When `include_source` is False (an
    oversized class), the class's own full source is omitted — its
    methods are indexed as separate FUNCTION/METHOD chunks instead (see
    chunker.py's "Class chunks" strategy)."""
    method_signatures = (
        "\n".join(f"- {_display_signature(m.signature)}" for m in cls.methods)
        if cls.methods
        else "none"
    )
    nested_class_names = (
        ", ".join(nested.name for nested in cls.nested_classes) if cls.nested_classes else "none"
    )
    class_attributes = (
        "\n".join(
            f"- {attr.name}" + (f": {attr.annotation}" if attr.annotation else "")
            for attr in cls.class_attributes
        )
        if cls.class_attributes
        else "none"
    )
    docstring = cls.docstring.strip() if cls.docstring else "none"

    lines = [
        f"Symbol: {cls.qualified_name}",
        "Type: class",
        f"File: {file_path}",
        f"Lines: {cls.location.start_line}-{cls.location.end_line}",
        f"Base classes: {', '.join(cls.base_classes) if cls.base_classes else 'none'}",
        f"Decorators: {_decorator_names(cls.decorators)}",
        f"Docstring: {docstring}",
        "Class attributes:",
        class_attributes,
        "Methods:",
        method_signatures,
        f"Nested classes: {nested_class_names}",
    ]
    if include_source:
        lines += ["", "Source:", cls.source_code]
    return "\n".join(lines)


def build_module_text(parsed_file: ParsedFile) -> str:
    """Text for a MODULE chunk — never the complete source of a large
    module (see the indexing task's "Module chunks")."""
    imports = (
        "\n".join(f"- {display}" for _bound, display in _bound_import_display_names(parsed_file))
        if parsed_file.imports
        else "none"
    )
    module_attributes = (
        "\n".join(
            f"- {attr.name}" + (f": {attr.annotation}" if attr.annotation else "")
            for attr in parsed_file.module_attributes
        )
        if parsed_file.module_attributes
        else "none"
    )
    class_names = (
        "\n".join(f"- {cls.name}({', '.join(cls.base_classes)})" for cls in parsed_file.classes)
        if parsed_file.classes
        else "none"
    )
    function_signatures = (
        "\n".join(f"- {_display_signature(f.signature)}" for f in parsed_file.functions)
        if parsed_file.functions
        else "none"
    )
    docstring = parsed_file.module_docstring.strip() if parsed_file.module_docstring else "none"

    lines = [
        f"Module: {parsed_file.module_name}",
        f"File: {parsed_file.file_path}",
        f"Docstring: {docstring}",
        "Imports:",
        imports,
        "Module attributes:",
        module_attributes,
        "Top-level classes:",
        class_names,
        "Top-level functions:",
        function_signatures,
    ]
    return "\n".join(lines)


def build_api_endpoint_text(
    func: ParsedFunction,
    decorator: ParsedDecorator,
    *,
    file_path: str,
    framework_hint: str,
) -> str:
    """Text for an API_ENDPOINT chunk — a distinct chunk from the handler's
    own FUNCTION/METHOD chunk (different id, different chunk_type)."""
    route_info = decorator.route_info
    assert route_info is not None  # callers only invoke this for route decorators

    lines = [
        f"Endpoint: {route_info.http_method or 'UNKNOWN'} {route_info.path or 'unknown'}",
        f"Framework hint: {framework_hint}",
        f"Handler: {func.qualified_name}",
        f"Handler signature: {_display_signature(func.signature)}",
        f"File: {file_path}",
        f"Lines: {func.location.start_line}-{func.location.end_line}",
        f"Decorator: {decorator.raw_expression}",
        "",
        "Source:",
        func.source_code,
    ]
    return "\n".join(lines)
