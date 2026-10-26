"""Unit tests for app.impact.service — symbol_id/qualified_name target
resolution and ambiguity handling. Uses graph_symbol_service_patch (see
conftest.py) to fake app.graph.repository_graph_service without a real
Neo4j."""

import pytest

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.domain.graph.models import SymbolSearchResult
from app.impact import service as impact_service
from app.impact.exceptions import (
    AmbiguousTargetError,
    InvalidImpactParameterError,
    TargetSymbolNotFoundError,
    UnsupportedTargetTypeError,
)


@pytest.fixture
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def _search_result(
    *,
    symbol_id: str,
    name: str,
    qualified_name: str,
    symbol_type: NodeLabel = NodeLabel.FUNCTION,
    match_type: SymbolMatchType = SymbolMatchType.EXACT_QUALIFIED_NAME,
) -> SymbolSearchResult:
    return SymbolSearchResult(
        symbol_id=symbol_id,
        symbol_type=symbol_type,
        name=name,
        qualified_name=qualified_name,
        file_path="pkg/mod.py",
        start_line=1,
        end_line=2,
        match_type=match_type,
    )


class TestResolveTargetBySymbolId:
    def test_found_symbol_is_returned(
        self, settings: Settings, graph_symbol_service_patch, fake_node_factory
    ) -> None:
        from app.graph.mappers import map_node

        graph_symbol_service_patch["get_symbol"] = map_node(
            fake_node_factory(id="s1", qualified_name="pkg.func")
        )
        node = impact_service.resolve_target(
            None, settings, repository_id="repo-1", symbol_id="s1", qualified_name=None
        )
        assert node.id == "s1"

    def test_missing_symbol_raises_not_found(
        self, settings: Settings, graph_symbol_service_patch
    ) -> None:
        with pytest.raises(TargetSymbolNotFoundError):
            impact_service.resolve_target(
                None, settings, repository_id="repo-1", symbol_id="missing", qualified_name=None
            )


class TestResolveTargetByQualifiedName:
    def test_unique_match_is_resolved(self, settings: Settings, graph_symbol_service_patch) -> None:
        graph_symbol_service_patch["search_symbols"] = [
            _search_result(symbol_id="s1", name="login", qualified_name="pkg.auth.login")
        ]
        node = impact_service.resolve_target(
            None,
            settings,
            repository_id="repo-1",
            symbol_id=None,
            qualified_name="pkg.auth.login",
        )
        assert node.id == "s1"
        assert node.qualified_name == "pkg.auth.login"

    def test_no_match_raises_not_found(
        self, settings: Settings, graph_symbol_service_patch
    ) -> None:
        graph_symbol_service_patch["search_symbols"] = []
        with pytest.raises(TargetSymbolNotFoundError):
            impact_service.resolve_target(
                None, settings, repository_id="repo-1", symbol_id=None, qualified_name="pkg.nope"
            )

    def test_ambiguous_match_raises_with_candidate_list(
        self, settings: Settings, graph_symbol_service_patch
    ) -> None:
        graph_symbol_service_patch["search_symbols"] = [
            _search_result(
                symbol_id="s1",
                name="login",
                qualified_name="app.auth.service.login",
                match_type=SymbolMatchType.EXACT_NAME,
            ),
            _search_result(
                symbol_id="s2",
                name="login",
                qualified_name="tests.helpers.login",
                match_type=SymbolMatchType.EXACT_NAME,
            ),
        ]
        with pytest.raises(AmbiguousTargetError) as exc_info:
            impact_service.resolve_target(
                None, settings, repository_id="repo-1", symbol_id=None, qualified_name="login"
            )
        assert set(exc_info.value.candidates) == {
            "app.auth.service.login",
            "tests.helpers.login",
        }

    def test_never_picks_randomly_between_tied_candidates(
        self, settings: Settings, graph_symbol_service_patch
    ) -> None:
        """Calling resolution repeatedly on the same tied candidates must
        always raise ambiguity — never silently settle on one."""
        graph_symbol_service_patch["search_symbols"] = [
            _search_result(
                symbol_id="s1",
                name="login",
                qualified_name="a.login",
                match_type=SymbolMatchType.EXACT_NAME,
            ),
            _search_result(
                symbol_id="s2",
                name="login",
                qualified_name="b.login",
                match_type=SymbolMatchType.EXACT_NAME,
            ),
        ]
        for _ in range(3):
            with pytest.raises(AmbiguousTargetError):
                impact_service.resolve_target(
                    None, settings, repository_id="repo-1", symbol_id=None, qualified_name="login"
                )


class TestResolveTargetRequiresAKey:
    def test_neither_symbol_id_nor_qualified_name_raises(self, settings: Settings) -> None:
        with pytest.raises(InvalidImpactParameterError):
            impact_service.resolve_target(
                None, settings, repository_id="repo-1", symbol_id=None, qualified_name=None
            )


class TestGetImpactAnalysis:
    def test_unsupported_target_type_is_rejected(
        self, settings: Settings, graph_symbol_service_patch, fake_node_factory, monkeypatch
    ) -> None:
        from app.graph.mappers import map_node

        graph_symbol_service_patch["get_symbol"] = map_node(
            fake_node_factory(id="mod1", label="Module", qualified_name="pkg.mod")
        )
        with pytest.raises(UnsupportedTargetTypeError):
            impact_service.get_impact_analysis(
                None, settings, repository_id="repo-1", symbol_id="mod1"
            )

    def test_supported_target_delegates_to_analyzer(
        self, settings: Settings, graph_symbol_service_patch, fake_node_factory, monkeypatch
    ) -> None:
        from app.graph.mappers import map_node

        graph_symbol_service_patch["get_symbol"] = map_node(
            fake_node_factory(id="f1", label="Function", qualified_name="pkg.func")
        )

        captured = {}

        def _fake_analyze_impact(client, settings, **kwargs):
            captured.update(kwargs)
            return "sentinel-result"

        monkeypatch.setattr(impact_service, "analyze_impact", _fake_analyze_impact)

        result = impact_service.get_impact_analysis(
            None, settings, repository_id="repo-1", symbol_id="f1", max_depth=3
        )
        assert result == "sentinel-result"
        assert captured["target_node"].id == "f1"
        assert captured["max_depth"] == 3
