"""UTF-8-safe source helpers and stable ID generation shared by all
language parsers (see AGENTS.md rule 10 — kept language-agnostic)."""

import hashlib
import uuid
from pathlib import PurePosixPath

from tree_sitter import Node

from app.domain.code_symbols.models import SourceLocation
from app.parsing.exceptions import SourceDecodingError

# Fixed, arbitrary namespace for uuid5-based symbol IDs. Any constant UUID
# works here — what matters is that it never changes, so the same inputs
# always hash to the same ID (see "Stable IDs" in the parsing task).
_SYMBOL_ID_NAMESPACE = uuid.UUID("c9c6e772-2b7b-4a6a-9a3d-7a6b1f7e2c1a")


def decode_source(raw_bytes: bytes) -> str:
    """Decode raw file bytes as UTF-8, raising a controlled error otherwise."""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceDecodingError("Source is not valid UTF-8 text and cannot be parsed.") from exc


def compute_content_hash(source_bytes: bytes) -> str:
    return hashlib.sha256(source_bytes).hexdigest()


def derive_module_name(repository_relative_path: PurePosixPath) -> str:
    """``app/auth/service.py`` -> ``app.auth.service``;
    ``app/auth/__init__.py`` -> ``app.auth``; ``main.py`` -> ``main``.
    """
    parts = list(repository_relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def generate_symbol_id(
    *,
    repository_id: str,
    file_path: str,
    symbol_type: str,
    qualified_name: str,
    start_line: int,
) -> str:
    """Deterministic uuid5 ID: same inputs always produce the same ID.

    Never uses uuid4 (random) — see "Stable IDs" in the parsing task.
    """
    key = f"{repository_id}:{file_path}:{symbol_type}:{qualified_name}:{start_line}"
    return str(uuid.uuid5(_SYMBOL_ID_NAMESPACE, key))


def node_text(node: Node) -> str:
    """Exact, UTF-8-safe source text for a Tree-sitter node.

    Uses Node.text (a raw byte slice from the original buffer), never
    character-offset slicing of the decoded str — the two diverge as soon
    as the source contains any multi-byte UTF-8 character before the node.
    ``Node.text`` is only ``None`` for a node with no byte range of its own
    (not expected for any node this parser inspects); treated as empty.
    """
    return node.text.decode("utf-8") if node.text is not None else ""


def node_to_location(node: Node, file_path: str) -> SourceLocation:
    """Tree-sitter points are 0-based; exposed line numbers must be
    1-based (columns stay 0-based byte offsets — see models.py)."""
    return SourceLocation(
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        start_column=node.start_point[1],
        end_line=node.end_point[0] + 1,
        end_column=node.end_point[1],
    )
