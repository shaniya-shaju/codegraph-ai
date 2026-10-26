"""Deterministic content hashing and stable chunk-ID generation."""

from app.indexing.hashing import compute_content_hash, generate_chunk_id


class TestComputeContentHash:
    def test_same_content_same_hash(self) -> None:
        assert compute_content_hash("def f():\n    pass\n") == compute_content_hash(
            "def f():\n    pass\n"
        )

    def test_different_content_different_hash(self) -> None:
        assert compute_content_hash("a") != compute_content_hash("b")


class TestGenerateChunkId:
    def _kwargs(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = dict(
            repository_id="repo-1",
            file_path="m.py",
            symbol_id="sym-1",
            chunk_type="function",
            fragment_index=0,
            content_hash="abc123",
        )
        base.update(overrides)
        return base

    def test_same_inputs_produce_the_same_id(self) -> None:
        assert generate_chunk_id(**self._kwargs()) == generate_chunk_id(**self._kwargs())  # type: ignore[arg-type]

    def test_different_content_hash_produces_a_different_id(self) -> None:
        id_a = generate_chunk_id(**self._kwargs(content_hash="aaa"))  # type: ignore[arg-type]
        id_b = generate_chunk_id(**self._kwargs(content_hash="bbb"))  # type: ignore[arg-type]
        assert id_a != id_b

    def test_different_fragment_index_produces_a_different_id(self) -> None:
        id_a = generate_chunk_id(**self._kwargs(fragment_index=0))  # type: ignore[arg-type]
        id_b = generate_chunk_id(**self._kwargs(fragment_index=1))  # type: ignore[arg-type]
        assert id_a != id_b

    def test_different_repository_id_produces_a_different_id(self) -> None:
        id_a = generate_chunk_id(**self._kwargs(repository_id="repo-a"))  # type: ignore[arg-type]
        id_b = generate_chunk_id(**self._kwargs(repository_id="repo-b"))  # type: ignore[arg-type]
        assert id_a != id_b

    def test_none_symbol_id_is_handled(self) -> None:
        # module chunks may have symbol_id set to a file id, but the
        # function must not crash on None either (defensive).
        generate_chunk_id(**self._kwargs(symbol_id=None))  # type: ignore[arg-type]
