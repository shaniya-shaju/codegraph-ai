"""Module-name derivation, stable ID generation, and 1-based line numbers."""

from pathlib import PurePosixPath

from app.parsing.source_utils import derive_module_name, generate_symbol_id


class TestDeriveModuleName:
    def test_nested_module_file(self) -> None:
        assert derive_module_name(PurePosixPath("app/auth/service.py")) == "app.auth.service"

    def test_package_init_file(self) -> None:
        assert derive_module_name(PurePosixPath("app/auth/__init__.py")) == "app.auth"

    def test_top_level_module(self) -> None:
        assert derive_module_name(PurePosixPath("main.py")) == "main"


class TestGenerateSymbolId:
    def test_same_inputs_produce_the_same_id(self) -> None:
        kwargs = dict(
            repository_id="repo-1",
            file_path="app/auth/service.py",
            symbol_type="function",
            qualified_name="app.auth.service.login",
            start_line=10,
        )

        assert generate_symbol_id(**kwargs) == generate_symbol_id(**kwargs)

    def test_different_repository_id_produces_a_different_id(self) -> None:
        common = dict(
            file_path="app/auth/service.py",
            symbol_type="function",
            qualified_name="app.auth.service.login",
            start_line=10,
        )

        id_a = generate_symbol_id(repository_id="repo-a", **common)
        id_b = generate_symbol_id(repository_id="repo-b", **common)

        assert id_a != id_b

    def test_different_start_line_produces_a_different_id(self) -> None:
        common = dict(
            repository_id="repo-1",
            file_path="app/auth/service.py",
            symbol_type="function",
            qualified_name="app.auth.service.login",
        )

        assert generate_symbol_id(start_line=10, **common) != generate_symbol_id(
            start_line=11, **common
        )

    def test_id_is_not_a_bare_random_uuid4_pattern(self) -> None:
        # uuid5 output looks exactly like a UUID string, but must be
        # reproducible — re-generating with identical inputs, twice, must
        # never differ (this would fail for uuid4-based random IDs).
        ids = {
            generate_symbol_id(
                repository_id="repo-1",
                file_path="m.py",
                symbol_type="function",
                qualified_name="m.f",
                start_line=1,
            )
            for _ in range(5)
        }
        assert len(ids) == 1
