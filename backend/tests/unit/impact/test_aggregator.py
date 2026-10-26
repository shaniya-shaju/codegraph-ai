"""Unit tests for app.impact.aggregator — file/module aggregation and
conservative test-reference detection."""

from app.domain.impact.enums import ImpactType, TestRelationshipStatus
from app.domain.impact.models import ImpactedSymbol
from app.impact import aggregator


def _symbol(
    *,
    symbol_id: str,
    qualified_name: str,
    file_path: str | None,
    distance: int,
    impact_type: ImpactType = ImpactType.DIRECT_CALLER,
) -> ImpactedSymbol:
    return ImpactedSymbol(
        symbol_id=symbol_id,
        qualified_name=qualified_name,
        symbol_type="Function",
        file_path=file_path,
        start_line=1,
        end_line=2,
        impact_type=impact_type,
        distance=distance,
        reason="test",
    )


class TestIsTestFilePath:
    def test_tests_directory_matches(self) -> None:
        assert aggregator.is_test_file_path("tests/test_auth.py")

    def test_test_prefix_matches(self) -> None:
        assert aggregator.is_test_file_path("app/test_auth.py")

    def test_test_suffix_matches(self) -> None:
        assert aggregator.is_test_file_path("app/auth_test.py")

    def test_ordinary_file_does_not_match(self) -> None:
        assert not aggregator.is_test_file_path("app/auth.py")

    def test_none_does_not_match(self) -> None:
        assert not aggregator.is_test_file_path(None)


class TestAggregateFiles:
    def test_multiple_symbols_same_file_counted_once(self) -> None:
        symbols = [
            _symbol(symbol_id="a", qualified_name="pkg.a", file_path="pkg/mod.py", distance=1),
            _symbol(symbol_id="b", qualified_name="pkg.b", file_path="pkg/mod.py", distance=2),
        ]
        files = aggregator.aggregate_files(symbols)
        assert len(files) == 1
        assert files[0].file_path == "pkg/mod.py"
        assert files[0].affected_symbol_count == 2
        assert files[0].minimum_distance == 1
        assert set(files[0].impacted_symbol_ids) == {"a", "b"}

    def test_symbols_across_files_produce_separate_rows(self) -> None:
        symbols = [
            _symbol(symbol_id="a", qualified_name="pkg.a", file_path="pkg/a.py", distance=1),
            _symbol(symbol_id="b", qualified_name="pkg.b", file_path="pkg/b.py", distance=1),
        ]
        files = aggregator.aggregate_files(symbols)
        assert {f.file_path for f in files} == {"pkg/a.py", "pkg/b.py"}

    def test_symbol_without_file_path_is_skipped(self) -> None:
        symbols = [_symbol(symbol_id="a", qualified_name="pkg.a", file_path=None, distance=1)]
        assert aggregator.aggregate_files(symbols) == []

    def test_impact_types_are_deduplicated_per_file(self) -> None:
        symbols = [
            _symbol(
                symbol_id="a",
                qualified_name="pkg.a",
                file_path="pkg/mod.py",
                distance=1,
                impact_type=ImpactType.DIRECT_CALLER,
            ),
            _symbol(
                symbol_id="b",
                qualified_name="pkg.b",
                file_path="pkg/mod.py",
                distance=1,
                impact_type=ImpactType.DIRECT_CALLER,
            ),
        ]
        files = aggregator.aggregate_files(symbols)
        assert files[0].impact_types == [ImpactType.DIRECT_CALLER]


class TestAggregateModules:
    def test_module_derived_from_qualified_name(self) -> None:
        symbols = [
            _symbol(
                symbol_id="a", qualified_name="pkg.mod.func_a", file_path="pkg/mod.py", distance=1
            ),
            _symbol(
                symbol_id="b", qualified_name="pkg.mod.func_b", file_path="pkg/mod.py", distance=2
            ),
        ]
        modules = aggregator.aggregate_modules(symbols)
        assert len(modules) == 1
        assert modules[0].module_name == "pkg.mod"
        assert modules[0].affected_symbol_count == 2
        assert modules[0].minimum_distance == 1

    def test_symbols_across_modules_produce_separate_rows(self) -> None:
        symbols = [
            _symbol(symbol_id="a", qualified_name="pkg.a.func", file_path="pkg/a.py", distance=1),
            _symbol(symbol_id="b", qualified_name="pkg.b.func", file_path="pkg/b.py", distance=1),
        ]
        modules = aggregator.aggregate_modules(symbols)
        assert {m.module_name for m in modules} == {"pkg.a", "pkg.b"}


class TestClassifyTestReferences:
    def test_known_test_caller_is_labeled_related(self) -> None:
        dependents = [
            _symbol(
                symbol_id="t1",
                qualified_name="tests.test_auth.test_login",
                file_path="tests/test_auth.py",
                distance=1,
            )
        ]
        related, status = aggregator.classify_test_references(dependents, truncated=False)
        assert status is TestRelationshipStatus.KNOWN_RELATED_TESTS
        assert len(related) == 1
        assert related[0].impact_type is ImpactType.TEST_REFERENCE

    def test_non_test_dependents_yield_no_known_references(self) -> None:
        dependents = [
            _symbol(symbol_id="a", qualified_name="pkg.a", file_path="pkg/a.py", distance=1)
        ]
        related, status = aggregator.classify_test_references(dependents, truncated=False)
        assert related == []
        assert status is TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES

    def test_truncated_search_with_no_hits_is_unknown_not_no_tests(self) -> None:
        dependents = [
            _symbol(symbol_id="a", qualified_name="pkg.a", file_path="pkg/a.py", distance=1)
        ]
        related, status = aggregator.classify_test_references(dependents, truncated=True)
        assert related == []
        assert status is TestRelationshipStatus.UNKNOWN

    def test_filename_match_without_dependents_list_membership_is_not_related(self) -> None:
        """A test-looking file that never appears in the dependents list
        (i.e. no real graph CALLS relationship reached it) must never be
        reported as a related test — only filenames already reached
        through a real relationship are considered."""
        dependents: list[ImpactedSymbol] = []
        related, status = aggregator.classify_test_references(dependents, truncated=False)
        assert related == []
        assert status is TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES
