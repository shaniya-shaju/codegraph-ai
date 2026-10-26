"""Deterministic content hashing and stable chunk-ID generation.

Mirrors app.parsing.source_utils.generate_symbol_id's approach (uuid5,
never uuid4) — see the indexing task's "Stable chunk IDs": the same
unchanged symbol content must receive the same chunk ID on repeated
indexing, and a changed symbol must receive a new one.
"""

import hashlib
import uuid

# Fixed, arbitrary namespace — distinct from parsing's symbol-id namespace
# so a symbol_id and a chunk_id can never collide even for identical
# inputs. What matters is that it never changes.
_CHUNK_ID_NAMESPACE = uuid.UUID("2f8b6a3e-6b8a-4e60-9a8a-3b6f7c9d2e10")


def compute_content_hash(content: str) -> str:
    """SHA-256 of the exact chunk text, hex-encoded."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_chunk_id(
    *,
    repository_id: str,
    file_path: str,
    symbol_id: str | None,
    chunk_type: str,
    fragment_index: int,
    content_hash: str,
) -> str:
    """Deterministic chunk id.

    ``content_hash`` is part of the hash input deliberately: a changed
    symbol's content_hash changes, which changes its chunk_id, which is
    exactly what lets the indexing service treat it as "new" (embed +
    upsert) while the old id's document becomes stale and gets deleted.
    """
    key = (
        f"{repository_id}:{file_path}:{symbol_id or ''}:{chunk_type}:"
        f"{fragment_index}:{content_hash}"
    )
    return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, key))
