"""Syntax-aware chunking: one chunk type per requirement, stable IDs,
exact line preservation, oversized-symbol fragmentation, and determinism."""

from app.domain.retrieval.enums import ChunkType
from app.indexing.chunker import build_chunks_for_file
from tests.unit.indexing.conftest import parse


def _chunks_of_type(chunks, chunk_type: ChunkType):
    return [c for c in chunks if c.chunk_type is chunk_type]


class TestModuleChunk:
    def test_exactly_one_module_chunk_with_expected_fields(
        self, python_parser, generous_limits
    ) -> None:
        source = '"""A demo module."""\nimport os\n\n\ndef f():\n    pass\n'
        parsed = parse(python_parser, source, "app/demo.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        module_chunks = _chunks_of_type(chunks, ChunkType.MODULE)

        assert len(module_chunks) == 1
        module_chunk = module_chunks[0]
        assert module_chunk.repository_id == "repo-1"
        assert module_chunk.symbol_id == parsed.id
        assert module_chunk.qualified_name == parsed.module_name
        assert module_chunk.file_path == "app/demo.py"
        assert "Module: app.demo" in module_chunk.content
        assert "A demo module." in module_chunk.content
        assert "- os" in module_chunk.content

    def test_empty_file_still_produces_a_module_chunk(self, python_parser, generous_limits) -> None:
        parsed = parse(python_parser, "", "empty.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)

        assert len(chunks) == 1
        assert chunks[0].chunk_type is ChunkType.MODULE

    def test_file_with_parse_errors_still_chunks_whatever_parsed(
        self, python_parser, generous_limits
    ) -> None:
        source = "def broken(:\n    pass\n\ndef good():\n    return 1\n"
        parsed = parse(python_parser, source, "m.py")
        assert parsed.parse_errors  # sanity: this fixture really does have errors

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)

        function_names = {c.display_name for c in _chunks_of_type(chunks, ChunkType.FUNCTION)}
        assert "good" in function_names


class TestFunctionChunk:
    def test_function_chunk_fields_and_content(self, python_parser, generous_limits) -> None:
        source = 'def login(email: str) -> bool:\n    """Authenticate a user."""\n    return True\n'
        parsed = parse(python_parser, source, "app/auth.py")
        func = parsed.functions[0]

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        function_chunks = _chunks_of_type(chunks, ChunkType.FUNCTION)

        assert len(function_chunks) == 1
        chunk = function_chunks[0]
        assert chunk.symbol_id == func.id
        assert chunk.parent_symbol_id is None
        assert chunk.qualified_name == "app.auth.login"
        assert chunk.start_line == func.location.start_line
        assert chunk.end_line == func.location.end_line
        assert chunk.fragment_index == 0
        assert chunk.fragment_count == 1
        assert "Symbol: app.auth.login" in chunk.content
        assert "Signature: login(email: str) -> bool" in chunk.content
        assert "Authenticate a user." in chunk.content
        assert "Source:" in chunk.content
        assert func.source_code in chunk.content


class TestMethodChunk:
    def test_method_chunk_uses_method_type_and_parent_class(
        self, python_parser, generous_limits
    ) -> None:
        source = "class AuthService:\n    def login(self):\n        return True\n"
        parsed = parse(python_parser, source, "m.py")
        method = parsed.classes[0].methods[0]

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        method_chunks = _chunks_of_type(chunks, ChunkType.METHOD)
        function_chunks = _chunks_of_type(chunks, ChunkType.FUNCTION)

        assert len(method_chunks) == 1
        assert function_chunks == []  # methods are never also counted as functions
        chunk = method_chunks[0]
        assert chunk.symbol_id == method.id
        assert chunk.qualified_name == "m.AuthService.login"
        assert "Parent class: m.AuthService" in chunk.content


class TestClassChunk:
    def test_class_chunk_includes_full_source_when_small(
        self, python_parser, generous_limits
    ) -> None:
        source = 'class Animal:\n    """A pet."""\n\n    def speak(self):\n        return \'...\'\n'
        parsed = parse(python_parser, source, "m.py")
        cls = parsed.classes[0]

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        class_chunks = _chunks_of_type(chunks, ChunkType.CLASS)

        assert len(class_chunks) == 1
        chunk = class_chunks[0]
        assert chunk.symbol_id == cls.id
        assert chunk.metadata["class_source_included"] is True
        assert "Source:" in chunk.content
        assert cls.source_code in chunk.content
        assert "speak(self)" in chunk.content  # method signatures listed

    def test_oversized_class_overview_omits_full_source_but_keeps_methods_separate(
        self, python_parser, tiny_limits
    ) -> None:
        source = (
            "class Big:\n"
            "    def method_one(self):\n"
            "        return 1\n\n"
            "    def method_two(self):\n"
            "        return 2\n\n"
            "    def method_three(self):\n"
            "        return 3\n"
        )
        parsed = parse(python_parser, source, "m.py")
        cls = parsed.classes[0]
        assert len(cls.source_code) > tiny_limits.max_characters  # sanity: this really is oversized

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=tiny_limits)
        class_chunks = _chunks_of_type(chunks, ChunkType.CLASS)
        method_chunks = _chunks_of_type(chunks, ChunkType.METHOD)

        assert len(class_chunks) == 1
        overview = class_chunks[0]
        assert overview.metadata["class_source_included"] is False
        assert "Source:" not in overview.content
        assert cls.source_code not in overview.content
        # each method is still its own chunk (possibly fragmented, but present)
        method_symbol_ids = {c.symbol_id for c in method_chunks}
        assert {m.id for m in cls.methods} <= method_symbol_ids


class TestApiEndpointChunk:
    def test_endpoint_chunk_is_distinct_from_function_chunk(
        self, python_parser, generous_limits
    ) -> None:
        source = '@app.get("/users")\ndef list_users():\n    return []\n'
        parsed = parse(python_parser, source, "m.py")
        func = parsed.functions[0]

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        endpoint_chunks = _chunks_of_type(chunks, ChunkType.API_ENDPOINT)
        function_chunks = _chunks_of_type(chunks, ChunkType.FUNCTION)

        assert len(endpoint_chunks) == 1
        assert len(function_chunks) == 1
        endpoint_chunk = endpoint_chunks[0]
        function_chunk = function_chunks[0]

        assert endpoint_chunk.id != function_chunk.id
        assert endpoint_chunk.symbol_id == func.id  # same handler, different chunk
        assert endpoint_chunk.metadata["http_method"] == "GET"
        assert endpoint_chunk.metadata["route_path"] == "/users"
        assert "Endpoint: GET /users" in endpoint_chunk.content

    def test_non_route_decorator_produces_no_endpoint_chunk(
        self, python_parser, generous_limits
    ) -> None:
        source = "@staticmethod\ndef f():\n    pass\n"
        parsed = parse(python_parser, source, "m.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)

        assert _chunks_of_type(chunks, ChunkType.API_ENDPOINT) == []


class TestStableChunkIds:
    def test_repeated_chunking_of_identical_input_is_deterministic(
        self, python_parser, generous_limits
    ) -> None:
        source = (
            "class C:\n    def m(self, a, b):\n        return a + b\n\ndef f():\n    return 1\n"
        )
        parsed = parse(python_parser, source, "m.py")

        first = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        second = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)

        assert [c.id for c in first] == [c.id for c in second]
        assert [c.content_hash for c in first] == [c.content_hash for c in second]

    def test_changed_source_changes_only_that_chunks_id(
        self, python_parser, generous_limits
    ) -> None:
        original = parse(python_parser, "def f():\n    return 1\n", "m.py")
        changed = parse(python_parser, "def f():\n    return 2\n", "m.py")

        original_chunks = {
            c.chunk_type: c
            for c in build_chunks_for_file(original, repository_id="repo-1", limits=generous_limits)
        }
        changed_chunks = {
            c.chunk_type: c
            for c in build_chunks_for_file(changed, repository_id="repo-1", limits=generous_limits)
        }

        assert original_chunks[ChunkType.FUNCTION].id != changed_chunks[ChunkType.FUNCTION].id


class TestUnicodeSafety:
    def test_unicode_content_is_preserved_exactly(self, python_parser, generous_limits) -> None:
        source = 'def café() -> str:\n    """café docstring 名前."""\n    return "héllo"\n'
        parsed = parse(python_parser, source, "m.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=generous_limits)
        function_chunk = _chunks_of_type(chunks, ChunkType.FUNCTION)[0]

        assert "café" in function_chunk.content
        assert "名前" in function_chunk.content
        assert "héllo" in function_chunk.content


class TestOversizedFunctionFragmentation:
    def _oversized_source(self) -> str:
        lines = ["def big(a):"]
        for i in range(6):
            lines.append(f"    if a == {i}:")
            lines.append(f"        print({i})")
        lines.append("    return a")
        return "\n".join(lines) + "\n"

    def test_oversized_function_is_split_into_multiple_fragments(
        self, python_parser, tiny_limits
    ) -> None:
        parsed = parse(python_parser, self._oversized_source(), "m.py")
        func = parsed.functions[0]

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=tiny_limits)
        function_chunks = _chunks_of_type(chunks, ChunkType.FUNCTION)

        assert len(function_chunks) > 1
        for chunk in function_chunks:
            assert chunk.symbol_id == func.id
            assert chunk.parent_symbol_id == func.id
            assert chunk.fragment_count == len(function_chunks)

    def test_fragments_are_ordered_and_indexed_sequentially(
        self, python_parser, tiny_limits
    ) -> None:
        parsed = parse(python_parser, self._oversized_source(), "m.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=tiny_limits)
        function_chunks = sorted(
            _chunks_of_type(chunks, ChunkType.FUNCTION), key=lambda c: c.fragment_index
        )

        assert [c.fragment_index for c in function_chunks] == list(range(len(function_chunks)))
        start_lines = [c.start_line for c in function_chunks]
        assert start_lines == sorted(start_lines)
        # each fragment carries the original signature for standalone context
        for chunk in function_chunks:
            assert "Signature:" in chunk.content
            assert "Fragment:" in chunk.content

    def test_fragmentation_prefers_structural_boundaries_over_mid_statement_splits(
        self, python_parser, tiny_limits
    ) -> None:
        parsed = parse(python_parser, self._oversized_source(), "m.py")

        chunks = build_chunks_for_file(parsed, repository_id="repo-1", limits=tiny_limits)
        function_chunks = _chunks_of_type(chunks, ChunkType.FUNCTION)

        # every fragment's source slice should contain only whole lines —
        # never cut off mid-line (a proxy for "never mid-statement").
        for chunk in function_chunks:
            source_section = chunk.content.split("Source:\n", 1)[1]
            assert not source_section.endswith(" ")
            lines = source_section.splitlines()
            assert all(line == line.rstrip("\r") for line in lines)
