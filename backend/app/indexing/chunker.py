"""Deterministic, syntax-aware chunking of ParsedFile output.

Rule 1/2 (AGENTS.md-style, see the indexing task): chunk boundaries come
from the parser's symbol boundaries first; character-count splitting is
only ever the last-resort fallback for an oversized symbol whose body
can't be further decomposed structurally (see `_split_oversized_function`).
Rule 3: parser output (ParsedFile/ParsedFunction/ParsedClass) is the only
source of truth for where a chunk starts and ends.

Never executes, imports, or evaluates the source it chunks — the only
tree-sitter use here is a **local, throwaway re-parse of an already-
extracted symbol's own source text** (never the original file, never
anything from disk) to find top-level statement boundaries for oversized-
symbol splitting (see SECURITY.md "Parsing safety").
"""

import tree_sitter_python as tspython
from tree_sitter import Language, Node
from tree_sitter import Parser as TreeSitterParser

from app.domain.code_symbols.models import ParsedClass, ParsedFile, ParsedFunction
from app.domain.graph.enums import NodeLabel
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import CodeChunk
from app.indexing.hashing import compute_content_hash, generate_chunk_id
from app.indexing.models import ChunkingLimits, RawFragment
from app.indexing.text_builder import (
    build_api_endpoint_text,
    build_class_overview_text,
    build_function_text,
    build_module_text,
)

_PY_LANGUAGE = Language(tspython.language())


def _line_count(text: str) -> int:
    return text.count("\n") + 1


def _fits(text: str, limits: ChunkingLimits) -> bool:
    return len(text) <= limits.max_characters and _line_count(text) <= limits.max_lines


def _make_chunk(
    *,
    repository_id: str,
    file_id: str,
    symbol_id: str | None,
    parent_symbol_id: str | None,
    chunk_type: ChunkType,
    qualified_name: str | None,
    display_name: str,
    file_path: str,
    start_line: int,
    end_line: int,
    content: str,
    parser_version: str,
    embedding_model: str | None,
    fragment_index: int,
    fragment_count: int,
    metadata: dict[str, object] | None = None,
) -> CodeChunk:
    content_hash = compute_content_hash(content)
    chunk_id = generate_chunk_id(
        repository_id=repository_id,
        file_path=file_path,
        symbol_id=symbol_id,
        chunk_type=chunk_type.value,
        fragment_index=fragment_index,
        content_hash=content_hash,
    )
    return CodeChunk(
        id=chunk_id,
        repository_id=repository_id,
        file_id=file_id,
        symbol_id=symbol_id,
        parent_symbol_id=parent_symbol_id,
        chunk_type=chunk_type,
        language="python",
        qualified_name=qualified_name,
        display_name=display_name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        content=content,
        content_hash=content_hash,
        parser_version=parser_version,
        embedding_model=embedding_model,
        fragment_index=fragment_index,
        fragment_count=fragment_count,
        metadata=metadata or {},
    )


def build_chunks_for_file(
    parsed_file: ParsedFile,
    *,
    repository_id: str,
    limits: ChunkingLimits,
    embedding_model: str | None = None,
) -> list[CodeChunk]:
    """All chunks for one already-parsed file: one MODULE chunk, one
    FUNCTION/METHOD chunk per function/method (or several fragments if
    oversized), one CLASS chunk per class, and one API_ENDPOINT chunk per
    route-decorated handler."""
    chunks: list[CodeChunk] = [
        _build_module_chunk(
            parsed_file, repository_id=repository_id, embedding_model=embedding_model
        )
    ]

    for func in parsed_file.functions:
        chunks.extend(
            _build_function_chunks(
                func,
                parsed_file,
                repository_id=repository_id,
                label=NodeLabel.FUNCTION,
                limits=limits,
                embedding_model=embedding_model,
            )
        )
        chunks.extend(
            _build_endpoint_chunks(
                func, parsed_file, repository_id=repository_id, embedding_model=embedding_model
            )
        )

    for cls in parsed_file.classes:
        chunks.extend(
            _build_class_chunks(
                cls,
                parsed_file,
                repository_id=repository_id,
                limits=limits,
                embedding_model=embedding_model,
            )
        )

    return chunks


def _build_module_chunk(
    parsed_file: ParsedFile, *, repository_id: str, embedding_model: str | None
) -> CodeChunk:
    text = build_module_text(parsed_file)
    end_line = max(1, text.count("\n"))  # module chunks describe the whole file
    return _make_chunk(
        repository_id=repository_id,
        file_id=parsed_file.id,
        symbol_id=parsed_file.id,
        parent_symbol_id=None,
        chunk_type=ChunkType.MODULE,
        qualified_name=parsed_file.module_name,
        display_name=parsed_file.module_name or parsed_file.file_path,
        file_path=parsed_file.file_path,
        start_line=1,
        end_line=end_line,
        content=text,
        parser_version=parsed_file.parser_version,
        embedding_model=embedding_model,
        fragment_index=0,
        fragment_count=1,
    )


def _build_class_chunks(
    cls: ParsedClass,
    parsed_file: ParsedFile,
    *,
    repository_id: str,
    limits: ChunkingLimits,
    embedding_model: str | None,
) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    include_source = _fits(cls.source_code, limits)
    text = build_class_overview_text(
        cls, file_path=parsed_file.file_path, include_source=include_source
    )
    chunks.append(
        _make_chunk(
            repository_id=repository_id,
            file_id=parsed_file.id,
            symbol_id=cls.id,
            parent_symbol_id=None,
            chunk_type=ChunkType.CLASS,
            qualified_name=cls.qualified_name,
            display_name=cls.name,
            file_path=parsed_file.file_path,
            start_line=cls.location.start_line,
            end_line=cls.location.end_line,
            content=text,
            parser_version=parsed_file.parser_version,
            embedding_model=embedding_model,
            fragment_index=0,
            fragment_count=1,
            metadata={"class_source_included": include_source},
        )
    )

    for method in cls.methods:
        chunks.extend(
            _build_function_chunks(
                method,
                parsed_file,
                repository_id=repository_id,
                label=NodeLabel.METHOD,
                limits=limits,
                embedding_model=embedding_model,
            )
        )
        chunks.extend(
            _build_endpoint_chunks(
                method, parsed_file, repository_id=repository_id, embedding_model=embedding_model
            )
        )

    for nested in cls.nested_classes:
        chunks.extend(
            _build_class_chunks(
                nested,
                parsed_file,
                repository_id=repository_id,
                limits=limits,
                embedding_model=embedding_model,
            )
        )

    return chunks


def _build_function_chunks(
    func: ParsedFunction,
    parsed_file: ParsedFile,
    *,
    repository_id: str,
    label: NodeLabel,
    limits: ChunkingLimits,
    embedding_model: str | None,
) -> list[CodeChunk]:
    chunk_type = ChunkType.METHOD if label is NodeLabel.METHOD else ChunkType.FUNCTION
    text = build_function_text(
        func, file_path=parsed_file.file_path, label=label, parsed_file=parsed_file
    )

    if _fits(text, limits):
        return [
            _make_chunk(
                repository_id=repository_id,
                file_id=parsed_file.id,
                symbol_id=func.id,
                parent_symbol_id=None,
                chunk_type=chunk_type,
                qualified_name=func.qualified_name,
                display_name=func.name,
                file_path=parsed_file.file_path,
                start_line=func.location.start_line,
                end_line=func.location.end_line,
                content=text,
                parser_version=parsed_file.parser_version,
                embedding_model=embedding_model,
                fragment_index=0,
                fragment_count=1,
            )
        ]

    fragments = _split_oversized_symbol(func, limits)
    result = []
    for index, fragment in enumerate(fragments):
        fragment_text = _build_fragment_text(
            func,
            fragment,
            file_path=parsed_file.file_path,
            label=label,
            fragment_index=index,
            fragment_count=len(fragments),
        )
        result.append(
            _make_chunk(
                repository_id=repository_id,
                file_id=parsed_file.id,
                symbol_id=func.id,
                parent_symbol_id=func.id,
                chunk_type=chunk_type,
                qualified_name=func.qualified_name,
                display_name=func.name,
                file_path=parsed_file.file_path,
                start_line=fragment.start_line,
                end_line=fragment.end_line,
                content=fragment_text,
                parser_version=parsed_file.parser_version,
                embedding_model=embedding_model,
                fragment_index=index,
                fragment_count=len(fragments),
            )
        )
    return result


def _build_endpoint_chunks(
    func: ParsedFunction,
    parsed_file: ParsedFile,
    *,
    repository_id: str,
    embedding_model: str | None,
) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    for decorator in func.decorators:
        if decorator.route_info is None:
            continue
        text = build_api_endpoint_text(
            func, decorator, file_path=parsed_file.file_path, framework_hint="unknown"
        )
        # A different deterministic id than the handler's own FUNCTION/
        # METHOD chunk: symbol_id references the handler, but chunk_type
        # differs, and the content (hence content_hash) differs too.
        chunks.append(
            _make_chunk(
                repository_id=repository_id,
                file_id=parsed_file.id,
                symbol_id=func.id,
                parent_symbol_id=None,
                chunk_type=ChunkType.API_ENDPOINT,
                qualified_name=func.qualified_name,
                display_name=f"{decorator.route_info.http_method} {decorator.route_info.path}",
                file_path=parsed_file.file_path,
                start_line=func.location.start_line,
                end_line=func.location.end_line,
                content=text,
                parser_version=parsed_file.parser_version,
                embedding_model=embedding_model,
                fragment_index=0,
                fragment_count=1,
                metadata={
                    "http_method": decorator.route_info.http_method,
                    "route_path": decorator.route_info.path,
                },
            )
        )
    return chunks


# --- oversized-symbol fallback splitting -----------------------------------


def _split_oversized_symbol(func: ParsedFunction, limits: ChunkingLimits) -> list[RawFragment]:
    """Preferred order (see the indexing task's "Oversized-symbol
    strategy"): split by the function body's own top-level statement
    boundaries; only fall back to fixed-line grouping if the body can't be
    parsed into statements at all (e.g. a single huge statement)."""
    body_node = _reparse_function_body(func.source_code)
    if body_node is None or len(body_node.children) < 2:
        return _split_by_line_groups(func.source_code, func.location.start_line, limits)

    return _group_statements_into_fragments(func, body_node, limits)


def _reparse_function_body(source_code: str) -> Node | None:
    parser = TreeSitterParser(_PY_LANGUAGE)
    tree = parser.parse(source_code.encode("utf-8"))
    for child in tree.root_node.children:
        target = child.children[-1] if child.type == "decorated_definition" else child
        if target.type == "function_definition":
            return target.child_by_field_name("body")
    return None


def _group_statements_into_fragments(
    func: ParsedFunction, body_node: Node, limits: ChunkingLimits
) -> list[RawFragment]:
    source_bytes = func.source_code.encode("utf-8")
    base_line = func.location.start_line  # source_code was reparsed starting at row 0

    groups: list[list[Node]] = []
    current: list[Node] = []
    current_chars = 0

    for statement in body_node.children:
        statement_text = source_bytes[statement.start_byte : statement.end_byte].decode("utf-8")
        projected_chars = current_chars + len(statement_text)
        projected_lines = (
            statement.end_point[0]
            - (current[0].start_point[0] if current else statement.start_point[0])
        ) + 1
        if current and (
            projected_chars > limits.max_characters or projected_lines > limits.max_lines
        ):
            groups.append(current)
            current = []
            current_chars = 0
        current.append(statement)
        current_chars += len(statement_text)

    if current:
        groups.append(current)

    fragments: list[RawFragment] = []
    for group in groups:
        start_byte = group[0].start_byte
        end_byte = group[-1].end_byte
        content = source_bytes[start_byte:end_byte].decode("utf-8")
        fragments.append(
            RawFragment(
                content=content,
                start_line=base_line + group[0].start_point[0],
                end_line=base_line + group[-1].end_point[0],
            )
        )
    return fragments


def _split_by_line_groups(
    source_code: str, base_line: int, limits: ChunkingLimits
) -> list[RawFragment]:
    """Last-resort fallback when no structural boundary is available (see
    rule 6) — splits by whole lines (never mid-line, so never mid-UTF-8-
    byte-sequence either), not by a fixed character count."""
    lines = source_code.splitlines()
    fragments: list[RawFragment] = []
    start_index = 0
    while start_index < len(lines):
        end_index = min(start_index + limits.max_lines, len(lines))
        group = lines[start_index:end_index]
        # keep growing the group by one line at a time only while doing so
        # still fits the character budget, to respect both limits.
        while (
            end_index < len(lines)
            and sum(len(line) + 1 for line in lines[start_index:end_index]) < limits.max_characters
        ):
            end_index += 1
            group = lines[start_index:end_index]
        content = "\n".join(group)
        fragments.append(
            RawFragment(
                content=content,
                start_line=base_line + start_index,
                end_line=base_line + end_index - 1,
            )
        )
        start_index = end_index
    return fragments or [
        RawFragment(
            content=source_code,
            start_line=base_line,
            end_line=base_line + _line_count(source_code) - 1,
        )
    ]


def _build_fragment_text(
    func: ParsedFunction,
    fragment: RawFragment,
    *,
    file_path: str,
    label: NodeLabel,
    fragment_index: int,
    fragment_count: int,
) -> str:
    header = (
        f"Symbol: {func.qualified_name}\n"
        f"Type: {label.value.lower()}\n"
        f"File: {file_path}\n"
        f"Lines: {func.location.start_line}-{func.location.end_line}\n"
        f"Signature: {func.signature.rstrip(':')}\n"
        f"Fragment: {fragment_index + 1}/{fragment_count}\n"
        f"Fragment lines: {fragment.start_line}-{fragment.end_line}\n"
    )
    return f"{header}\nSource:\n{fragment.content}"
