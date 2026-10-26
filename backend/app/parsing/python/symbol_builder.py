"""Builds ParsedFile/ParsedFunction/ParsedClass/... from a parsed Tree-sitter
tree. Pure tree-walking — never executes, imports, or evaluates anything
from the source it reads (see SECURITY.md "Parsing safety").

See models.py's module docstring for the documented, deliberate rules on
import grouping, nested-function flattening, and decorator/route metadata
that resolve ambiguities in the parsing task's field list.
"""

from tree_sitter import Node

from app.domain.code_symbols.enums import ParameterKind, ParseErrorType, SymbolType
from app.domain.code_symbols.models import (
    ComplexitySignals,
    ParsedAssignment,
    ParsedClass,
    ParsedDecorator,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedParameter,
    ParsedRouteInfo,
    ParseError,
)
from app.parsing.models import FunctionSignals, ParseContext
from app.parsing.python.call_extractor import build_parsed_call, collect_function_signals
from app.parsing.python.queries import (
    HTTP_METHOD_DECORATOR_NAMES,
    IMPORT_QUERY,
    ROUTE_DECORATOR_NAME,
)
from app.parsing.source_utils import (
    compute_content_hash,
    generate_symbol_id,
    node_text,
    node_to_location,
)

_PUNCTUATION = {"(", ")", ","}
_KEYWORD_ARGUMENT_TYPE = "keyword_argument"


def build_parsed_file(ctx: ParseContext, root: Node) -> ParsedFile:
    """Entry point: walk the whole tree and assemble a ParsedFile."""
    signal_buckets = collect_function_signals(root)

    imports = _build_imports(ctx, root)
    module_docstring = _extract_docstring(root)
    parse_errors = _collect_parse_errors(root, ctx.file_path)

    functions: list[ParsedFunction] = []
    classes: list[ParsedClass] = []
    module_attributes: list[ParsedAssignment] = []

    for child in root.children:
        target, decorated_node = _unwrap_decorated(child)

        if target.type == "function_definition":
            func, bubbled_functions, bubbled_classes = _build_function(
                ctx,
                signal_buckets,
                target,
                decorated_node,
                scope_stack=(),
                parent_class=None,
            )
            functions.append(func)
            functions.extend(bubbled_functions)
            classes.extend(bubbled_classes)
        elif target.type == "class_definition":
            cls, bubbled_functions, bubbled_classes = _build_class(
                ctx, signal_buckets, target, decorated_node, scope_stack=()
            )
            classes.append(cls)
            functions.extend(bubbled_functions)
            classes.extend(bubbled_classes)
        elif child.type == "expression_statement" and child.children:
            assignment = _build_assignment(ctx, child.children[0])
            if assignment is not None:
                module_attributes.append(assignment)

    file_id = generate_symbol_id(
        repository_id=ctx.repository_id,
        file_path=ctx.file_path,
        symbol_type=SymbolType.MODULE.value,
        qualified_name=ctx.module_name,
        start_line=1,
    )

    return ParsedFile(
        id=file_id,
        repository_id=ctx.repository_id,
        file_path=ctx.file_path,
        module_name=ctx.module_name,
        language="python",
        content_hash=compute_content_hash(ctx.source_bytes),
        imports=imports,
        functions=functions,
        classes=classes,
        module_docstring=module_docstring,
        module_attributes=module_attributes,
        parse_errors=parse_errors,
        parser_version=ctx.parser_version,
    )


def _unwrap_decorated(node: Node) -> tuple[Node, Node | None]:
    if node.type == "decorated_definition":
        return node.children[-1], node
    return node, None


def _qualified_name(module_name: str, scope_stack: tuple[str, ...], symbol_name: str) -> str:
    parts = [part for part in (module_name, *scope_stack, symbol_name) if part]
    return ".".join(parts)


# --- functions ---------------------------------------------------------


def _build_function(
    ctx: ParseContext,
    signal_buckets: dict[tuple[int, int], FunctionSignals],
    node: Node,
    decorated_node: Node | None,
    *,
    scope_stack: tuple[str, ...],
    parent_class: str | None,
) -> tuple[ParsedFunction, list[ParsedFunction], list[ParsedClass]]:
    name_node = node.child_by_field_name("name")
    name = node_text(name_node) if name_node is not None else "<anonymous>"
    qualified_name = _qualified_name(ctx.module_name, scope_stack, name)

    is_async = any(child.type == "async" for child in node.children)

    params_node = node.child_by_field_name("parameters")
    parameters = (
        _build_parameters(ctx, params_node, qualified_name) if params_node is not None else []
    )

    return_type_node = node.child_by_field_name("return_type")
    return_annotation = node_text(return_type_node) if return_type_node is not None else None

    body_node = node.child_by_field_name("body")
    docstring = _extract_docstring(body_node) if body_node is not None else None

    decorators = _build_decorators(decorated_node) if decorated_node is not None else []

    location = node_to_location(node, ctx.file_path)
    signature = _build_signature(ctx, node, body_node)
    source_code = node_text(decorated_node) if decorated_node is not None else node_text(node)

    signals = signal_buckets.get((node.start_byte, node.end_byte), FunctionSignals())
    calls = [
        build_parsed_call(
            call_node,
            caller_qualified_name=qualified_name,
            file_path=ctx.file_path,
            repository_id=ctx.repository_id,
        )
        for call_node in signals.call_nodes
    ]
    complexity_signals = ComplexitySignals(
        branch_count=signals.branch_count,
        loop_count=signals.loop_count,
        exception_handler_count=signals.exception_handler_count,
        return_count=signals.return_count,
        await_count=signals.await_count,
        nested_function_count=signals.nested_function_count,
    )

    symbol_id = generate_symbol_id(
        repository_id=ctx.repository_id,
        file_path=ctx.file_path,
        symbol_type=SymbolType.FUNCTION.value,
        qualified_name=qualified_name,
        start_line=location.start_line,
    )

    parsed_function = ParsedFunction(
        id=symbol_id,
        name=name,
        qualified_name=qualified_name,
        signature=signature,
        async_function=is_async,
        decorators=decorators,
        parameters=parameters,
        return_annotation=return_annotation,
        docstring=docstring,
        source_code=source_code,
        location=location,
        calls=calls,
        parent_class=parent_class,
        complexity_signals=complexity_signals,
    )

    bubbled_functions: list[ParsedFunction] = []
    bubbled_classes: list[ParsedClass] = []

    if body_node is not None:
        new_scope = (*scope_stack, name)
        for child in body_node.children:
            target, child_decorated = _unwrap_decorated(child)

            if target.type == "function_definition":
                nested_func, nested_bubbled_funcs, nested_bubbled_classes = _build_function(
                    ctx,
                    signal_buckets,
                    target,
                    child_decorated,
                    scope_stack=new_scope,
                    parent_class=None,
                )
                # A function nested in a function body has no container at
                # this level (ParsedFunction has no nested_functions field)
                # — it flattens into ParsedFile.functions (see models.py).
                bubbled_functions.append(nested_func)
                bubbled_functions.extend(nested_bubbled_funcs)
                bubbled_classes.extend(nested_bubbled_classes)
            elif target.type == "class_definition":
                nested_cls, nested_bubbled_funcs, nested_bubbled_classes = _build_class(
                    ctx, signal_buckets, target, child_decorated, scope_stack=new_scope
                )
                # Rare: a class defined inside a function body. No container
                # here either, so it flattens into ParsedFile.classes.
                bubbled_classes.append(nested_cls)
                bubbled_functions.extend(nested_bubbled_funcs)
                bubbled_classes.extend(nested_bubbled_classes)

    return parsed_function, bubbled_functions, bubbled_classes


def _build_signature(ctx: ParseContext, func_node: Node, body_node: Node | None) -> str:
    end_byte = body_node.start_byte if body_node is not None else func_node.end_byte
    return ctx.source_bytes[func_node.start_byte : end_byte].decode("utf-8").rstrip()


# --- classes -------------------------------------------------------------


def _build_class(
    ctx: ParseContext,
    signal_buckets: dict[tuple[int, int], FunctionSignals],
    node: Node,
    decorated_node: Node | None,
    *,
    scope_stack: tuple[str, ...],
) -> tuple[ParsedClass, list[ParsedFunction], list[ParsedClass]]:
    name_node = node.child_by_field_name("name")
    name = node_text(name_node) if name_node is not None else "<anonymous>"
    qualified_name = _qualified_name(ctx.module_name, scope_stack, name)

    base_classes = _build_base_classes(node)
    decorators = _build_decorators(decorated_node) if decorated_node is not None else []

    body_node = node.child_by_field_name("body")
    docstring = _extract_docstring(body_node) if body_node is not None else None

    location = node_to_location(node, ctx.file_path)
    source_code = node_text(decorated_node) if decorated_node is not None else node_text(node)

    symbol_id = generate_symbol_id(
        repository_id=ctx.repository_id,
        file_path=ctx.file_path,
        symbol_type=SymbolType.CLASS.value,
        qualified_name=qualified_name,
        start_line=location.start_line,
    )

    methods: list[ParsedFunction] = []
    nested_classes: list[ParsedClass] = []
    class_attributes: list[ParsedAssignment] = []
    bubbled_functions: list[ParsedFunction] = []
    bubbled_classes: list[ParsedClass] = []

    if body_node is not None:
        new_scope = (*scope_stack, name)
        for child in body_node.children:
            target, child_decorated = _unwrap_decorated(child)

            if target.type == "function_definition":
                method, nested_bubbled_funcs, nested_bubbled_classes = _build_function(
                    ctx,
                    signal_buckets,
                    target,
                    child_decorated,
                    scope_stack=new_scope,
                    parent_class=qualified_name,
                )
                methods.append(method)
                bubbled_functions.extend(nested_bubbled_funcs)
                bubbled_classes.extend(nested_bubbled_classes)
            elif target.type == "class_definition":
                nested_cls, nested_bubbled_funcs, nested_bubbled_classes = _build_class(
                    ctx, signal_buckets, target, child_decorated, scope_stack=new_scope
                )
                nested_classes.append(nested_cls)
                bubbled_functions.extend(nested_bubbled_funcs)
                bubbled_classes.extend(nested_bubbled_classes)
            elif child.type == "expression_statement" and child.children:
                assignment = _build_assignment(ctx, child.children[0])
                if assignment is not None:
                    class_attributes.append(assignment)

    parsed_class = ParsedClass(
        id=symbol_id,
        name=name,
        qualified_name=qualified_name,
        base_classes=base_classes,
        decorators=decorators,
        docstring=docstring,
        source_code=source_code,
        location=location,
        methods=methods,
        nested_classes=nested_classes,
        class_attributes=class_attributes,
    )
    return parsed_class, bubbled_functions, bubbled_classes


def _build_base_classes(class_node: Node) -> list[str]:
    superclasses = class_node.child_by_field_name("superclasses")
    if superclasses is None:
        return []
    return [
        node_text(child)
        for child in superclasses.children
        if child.type not in _PUNCTUATION and child.type != _KEYWORD_ARGUMENT_TYPE
    ]


# --- decorators / API-route metadata --------------------------------------


def _build_decorators(decorated_node: Node) -> list[ParsedDecorator]:
    decorators: list[ParsedDecorator] = []
    for child in decorated_node.children:
        if child.type != "decorator":
            continue
        expr = next((c for c in child.children if c.type != "@"), None)
        route_info = _extract_route_info(expr) if expr is not None else None
        decorators.append(ParsedDecorator(raw_expression=node_text(child), route_info=route_info))
    return decorators


def _extract_route_info(expr: Node) -> ParsedRouteInfo | None:
    if expr.type != "call":
        return None
    function_expr = expr.child_by_field_name("function")
    if function_expr is None or function_expr.type != "attribute":
        return None
    attribute_field = function_expr.child_by_field_name("attribute")
    if attribute_field is None:
        return None
    method_name = node_text(attribute_field)

    arguments = expr.child_by_field_name("arguments")
    path = _first_string_literal_argument(arguments) if arguments is not None else None

    if method_name in HTTP_METHOD_DECORATOR_NAMES:
        return ParsedRouteInfo(http_method=method_name.upper(), path=path)

    if method_name == ROUTE_DECORATOR_NAME:
        http_method = _extract_methods_keyword(arguments) if arguments is not None else None
        return ParsedRouteInfo(http_method=http_method or "GET", path=path)

    return None


def _first_string_literal_argument(arguments: Node) -> str | None:
    for child in arguments.children:
        if child.type == "string":
            return _string_literal_value(child)
    return None


def _string_literal_value(string_node: Node) -> str:
    return "".join(
        node_text(child)
        for child in string_node.children
        if child.type not in ("string_start", "string_end")
    )


def _extract_methods_keyword(arguments: Node) -> str | None:
    for child in arguments.children:
        if child.type != _KEYWORD_ARGUMENT_TYPE:
            continue
        name_field = child.child_by_field_name("name")
        if name_field is None or node_text(name_field) != "methods":
            continue
        value_field = child.child_by_field_name("value")
        if value_field is None:
            continue
        for element in value_field.children:
            if element.type == "string":
                return _string_literal_value(element).upper()
    return None


# --- parameters ------------------------------------------------------------


def _param_name(node: Node) -> str:
    if node.type == "identifier":
        return node_text(node)
    name_field = node.child_by_field_name("name")
    if name_field is not None:
        return node_text(name_field)
    identifier_child = next((c for c in node.children if c.type == "identifier"), None)
    return node_text(identifier_child) if identifier_child is not None else node_text(node)


def _param_annotation(node: Node) -> str | None:
    type_field = node.child_by_field_name("type")
    return node_text(type_field) if type_field is not None else None


def _param_default(node: Node) -> str | None:
    value_field = node.child_by_field_name("value")
    return node_text(value_field) if value_field is not None else None


def _build_parameters(
    ctx: ParseContext, params_node: Node, owner_qualified_name: str
) -> list[ParsedParameter]:
    meaningful = [child for child in params_node.children if child.type not in _PUNCTUATION]

    entries: list[tuple[Node, ParameterKind]] = []
    slash_index: int | None = None
    after_star = False

    for node in meaningful:
        if node.type == "positional_separator":
            slash_index = len(entries)
            continue
        if node.type == "keyword_separator":
            after_star = True
            continue
        if node.type == "list_splat_pattern":
            entries.append((node, ParameterKind.VAR_POSITIONAL))
            after_star = True
            continue
        if node.type == "dictionary_splat_pattern":
            entries.append((node, ParameterKind.VAR_KEYWORD))
            continue
        entries.append(
            (node, ParameterKind.KEYWORD_ONLY if after_star else ParameterKind.POSITIONAL)
        )

    parameters: list[ParsedParameter] = []
    for position, (node, kind) in enumerate(entries):
        if slash_index is not None and position < slash_index:
            kind = ParameterKind.POSITIONAL_ONLY

        name = _param_name(node)
        location = node_to_location(node, ctx.file_path)
        param_id = generate_symbol_id(
            repository_id=ctx.repository_id,
            file_path=ctx.file_path,
            symbol_type=SymbolType.PARAMETER.value,
            qualified_name=f"{owner_qualified_name}.{name}",
            start_line=location.start_line,
        )
        parameters.append(
            ParsedParameter(
                id=param_id,
                name=name,
                annotation=_param_annotation(node),
                default_value=_param_default(node),
                kind=kind,
                position=position,
                location=location,
            )
        )
    return parameters


# --- docstrings / assignments ----------------------------------------------


def _extract_docstring(body_node: Node) -> str | None:
    if not body_node.children:
        return None
    first = body_node.children[0]
    if first.type != "expression_statement" or not first.children:
        return None
    inner = first.children[0]
    if inner.type != "string":
        return None
    return _string_literal_value(inner)


_SIMPLE_ASSIGNMENT_TARGET_TYPES = {"identifier"}


def _build_assignment(ctx: ParseContext, node: Node) -> ParsedAssignment | None:
    if node.type != "assignment":
        return None
    left = node.child_by_field_name("left")
    if left is None or left.type not in _SIMPLE_ASSIGNMENT_TARGET_TYPES:
        return None  # tuple/list unpacking, attribute/subscript targets: not "simple"

    type_field = node.child_by_field_name("type")
    right = node.child_by_field_name("right")
    location = node_to_location(node, ctx.file_path)

    return ParsedAssignment(
        name=node_text(left),
        annotation=node_text(type_field) if type_field is not None else None,
        value=node_text(right) if right is not None else None,
        location=location,
    )


# --- imports -----------------------------------------------------------


def _build_imports(ctx: ParseContext, root: Node) -> list[ParsedImport]:
    imports: list[ParsedImport] = []
    for node, capture_name in IMPORT_QUERY.captures(root):
        if capture_name == "import_statement":
            imports.extend(_build_plain_imports(ctx, node))
        elif capture_name == "import_from_statement":
            parsed = _build_from_import(ctx, node)
            if parsed is not None:
                imports.append(parsed)
    return imports


def _build_plain_imports(ctx: ParseContext, node: Node) -> list[ParsedImport]:
    results: list[ParsedImport] = []
    for name_node in node.children_by_field_name("name"):
        location = node_to_location(name_node, ctx.file_path)

        if name_node.type == "aliased_import":
            dotted = name_node.child_by_field_name("name")
            alias_node = name_node.child_by_field_name("alias")
            module = node_text(dotted) if dotted is not None else node_text(name_node)
            alias = node_text(alias_node) if alias_node is not None else None
        else:
            module = node_text(name_node)
            alias = None

        import_id = generate_symbol_id(
            repository_id=ctx.repository_id,
            file_path=ctx.file_path,
            symbol_type=SymbolType.IMPORT.value,
            qualified_name=f"import:{module}",
            start_line=location.start_line,
        )
        results.append(
            ParsedImport(
                id=import_id,
                module=module,
                imported_names=[],
                alias=alias,
                is_from_import=False,
                relative_level=0,
                location=location,
            )
        )
    return results


def _build_from_import(ctx: ParseContext, node: Node) -> ParsedImport | None:
    module_name_field = node.child_by_field_name("module_name")
    relative_level = 0
    module: str | None = None

    if module_name_field is not None:
        if module_name_field.type == "relative_import":
            prefix = next(
                (c for c in module_name_field.children if c.type == "import_prefix"), None
            )
            if prefix is not None:
                relative_level = sum(1 for c in prefix.children if c.type == ".")
            dotted = next((c for c in module_name_field.children if c.type == "dotted_name"), None)
            module = node_text(dotted) if dotted is not None else None
        else:
            module = node_text(module_name_field)

    name_nodes = list(node.children_by_field_name("name"))
    wildcard_node = next((c for c in node.children if c.type == "wildcard_import"), None)

    imported_names: list[str] = []
    single_alias: str | None = None

    if wildcard_node is not None:
        imported_names = ["*"]
    elif name_nodes:
        for name_node in name_nodes:
            if name_node.type == "aliased_import":
                dotted = name_node.child_by_field_name("name")
                alias_node = name_node.child_by_field_name("alias")
                bound_name = (
                    node_text(alias_node)
                    if alias_node is not None
                    else (node_text(dotted) if dotted is not None else node_text(name_node))
                )
                imported_names.append(bound_name)
                if len(name_nodes) == 1 and alias_node is not None:
                    single_alias = node_text(alias_node)
            else:
                imported_names.append(node_text(name_node))
    else:
        return None

    location = node_to_location(node, ctx.file_path)
    qualified_name_for_id = f"from:{'.' * relative_level}{module or ''}:{','.join(imported_names)}"
    import_id = generate_symbol_id(
        repository_id=ctx.repository_id,
        file_path=ctx.file_path,
        symbol_type=SymbolType.IMPORT.value,
        qualified_name=qualified_name_for_id,
        start_line=location.start_line,
    )

    return ParsedImport(
        id=import_id,
        module=module,
        imported_names=imported_names,
        alias=single_alias,
        is_from_import=True,
        relative_level=relative_level,
        location=location,
    )


# --- parse-error / recovery reporting ---------------------------------------


def _collect_parse_errors(root: Node, file_path: str) -> list[ParseError]:
    """Report Tree-sitter's own recovered-error markers.

    Only the outermost ERROR node in a given subtree is reported (its
    children aren't walked further) to avoid one syntax mistake producing
    a flood of nested duplicate entries; `is_missing` tokens elsewhere in
    an otherwise-clean tree are reported individually since they're cheap
    and precise.
    """
    errors: list[ParseError] = []

    def visit(node: Node) -> None:
        if node.type == "ERROR":
            snippet = node_text(node)[:80]
            errors.append(
                ParseError(
                    error_type=ParseErrorType.SYNTAX_ERROR,
                    message=f"Unparseable syntax near {snippet!r}.",
                    file_path=file_path,
                    location=node_to_location(node, file_path),
                    recoverable=True,
                )
            )
            return
        if node.is_missing:
            errors.append(
                ParseError(
                    error_type=ParseErrorType.SYNTAX_ERROR,
                    message=f"Expected a {node.type!r} token but it was missing.",
                    file_path=file_path,
                    location=node_to_location(node, file_path),
                    recoverable=True,
                )
            )
            return
        for child in node.children:
            visit(child)

    visit(root)
    return errors
