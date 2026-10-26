"""Symbol resolution ranking rules — see the hybrid-retrieval task's
"Symbol resolution": exact qualified-name match, exact short-name match,
suffix match, same-file evidence, and ambiguity handling."""

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.domain.graph.models import SymbolSearchResult
from app.domain.rag.enums import SymbolResolutionStatus
from app.rag.symbol_retriever import SymbolRetriever


class _FakeGraphService:
    def __init__(self, results: list[SymbolSearchResult]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    def search_symbols(
        self,
        client,
        settings,
        *,
        repository_id,
        query,
        symbol_type=None,
        file_path=None,
        limit=None,
    ):
        self.calls.append(
            {
                "repository_id": repository_id,
                "query": query,
                "symbol_type": symbol_type,
                "limit": limit,
            }
        )
        return self._results


def _result(
    symbol_id: str,
    name: str,
    qualified_name: str,
    match_type: SymbolMatchType,
    *,
    symbol_type: NodeLabel = NodeLabel.FUNCTION,
    file_path: str = "app/auth.py",
) -> SymbolSearchResult:
    return SymbolSearchResult(
        symbol_id=symbol_id,
        symbol_type=symbol_type,
        name=name,
        qualified_name=qualified_name,
        file_path=file_path,
        start_line=1,
        end_line=5,
        match_type=match_type,
    )


def _retriever(results: list[SymbolSearchResult]) -> tuple[SymbolRetriever, _FakeGraphService]:
    fake = _FakeGraphService(results)
    return SymbolRetriever(client=None, settings=Settings(), graph_service=fake), fake  # type: ignore[arg-type]


class TestExactQualifiedName:
    def test_status_is_exact(self) -> None:
        retriever, _ = _retriever(
            [_result("s1", "login", "app.auth.login", SymbolMatchType.EXACT_QUALIFIED_NAME)]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="app.auth.login")
        assert resolution.status is SymbolResolutionStatus.EXACT
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_id == "s1"


class TestUniqueShortName:
    def test_single_candidate_is_unique_or_exact(self) -> None:
        retriever, _ = _retriever(
            [_result("s1", "login", "app.auth.login", SymbolMatchType.EXACT_NAME)]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="login")
        assert resolution.status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE)
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_id == "s1"


class TestAmbiguousShortName:
    def test_two_equally_strong_candidates_are_ambiguous(self) -> None:
        retriever, _ = _retriever(
            [
                _result(
                    "s1",
                    "login",
                    "app.auth.login",
                    SymbolMatchType.CONTAINS,
                    file_path="app/auth.py",
                ),
                _result(
                    "s2",
                    "login",
                    "app.admin.login",
                    SymbolMatchType.CONTAINS,
                    file_path="app/admin.py",
                ),
            ]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="login")
        assert resolution.status is SymbolResolutionStatus.AMBIGUOUS
        assert resolution.resolved_symbol is None
        assert len(resolution.candidates) == 2


class TestMissingSymbol:
    def test_no_candidates_is_not_found(self) -> None:
        retriever, _ = _retriever([])
        resolution = retriever.resolve(repository_id="repo-1", query="does_not_exist")
        assert resolution.status is SymbolResolutionStatus.NOT_FOUND
        assert resolution.resolved_symbol is None
        assert resolution.candidates == []


class TestMethodAndClassAndApiHandler:
    def test_method_symbol_type_is_preserved(self) -> None:
        retriever, _ = _retriever(
            [
                _result(
                    "s1",
                    "login",
                    "app.auth.AuthService.login",
                    SymbolMatchType.EXACT_QUALIFIED_NAME,
                    symbol_type=NodeLabel.METHOD,
                )
            ]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="app.auth.AuthService.login")
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_type is NodeLabel.METHOD

    def test_class_symbol_type_is_preserved(self) -> None:
        retriever, _ = _retriever(
            [
                _result(
                    "s1",
                    "AuthService",
                    "app.auth.AuthService",
                    SymbolMatchType.EXACT_QUALIFIED_NAME,
                    symbol_type=NodeLabel.CLASS,
                )
            ]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="app.auth.AuthService")
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_type is NodeLabel.CLASS

    def test_api_handler_symbol_type_is_passed_through_as_filter(self) -> None:
        retriever, fake = _retriever(
            [
                _result(
                    "s1",
                    "login_endpoint",
                    "/login",
                    SymbolMatchType.CONTAINS,
                    symbol_type=NodeLabel.API_ENDPOINT,
                )
            ]
        )
        retriever.resolve(
            repository_id="repo-1", query="/login", symbol_type=NodeLabel.API_ENDPOINT.value
        )
        assert fake.calls[0]["symbol_type"] == NodeLabel.API_ENDPOINT.value


class TestSuffixMatchRanking:
    def test_suffix_match_outranks_plain_contains_match(self) -> None:
        retriever, _ = _retriever(
            [
                _result(
                    "s1",
                    "login",
                    "app.auth.AuthService.login",
                    SymbolMatchType.CONTAINS,
                    file_path="app/auth.py",
                ),
                _result(
                    "s2",
                    "logingate",
                    "app.other.logingate",
                    SymbolMatchType.CONTAINS,
                    file_path="app/other.py",
                ),
            ]
        )
        resolution = retriever.resolve(repository_id="repo-1", query="AuthService.login")
        assert resolution.status is not SymbolResolutionStatus.AMBIGUOUS
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_id == "s1"


class TestSameFileEvidenceBoost:
    def test_hint_file_path_breaks_a_tie(self) -> None:
        retriever, _ = _retriever(
            [
                _result(
                    "s1",
                    "login",
                    "app.auth.login",
                    SymbolMatchType.CONTAINS,
                    file_path="app/auth.py",
                ),
                _result(
                    "s2",
                    "login",
                    "app.admin.login",
                    SymbolMatchType.CONTAINS,
                    file_path="app/admin.py",
                ),
            ]
        )
        resolution = retriever.resolve(
            repository_id="repo-1", query="login", hint_file_paths=frozenset({"app/auth.py"})
        )
        assert resolution.status is not SymbolResolutionStatus.AMBIGUOUS
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.symbol_id == "s1"


class TestSymbolLimitIsForwarded:
    def test_default_limit_comes_from_settings(self) -> None:
        retriever, fake = _retriever([])
        retriever.resolve(repository_id="repo-1", query="login")
        assert fake.calls[0]["limit"] == Settings().rag_symbol_candidate_limit
