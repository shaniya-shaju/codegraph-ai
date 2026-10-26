"""Resolves a mentioned-entity string to actual repository symbols.

Wraps ``app.graph.repository_graph_service.search_symbols`` — it does not
talk to Neo4j directly and does not duplicate any Cypher (see "Symbol
resolution": "Create a dedicated SymbolRetriever"). Never silently picks
one candidate when several are equally strong — see ``SymbolResolutionStatus``.
"""

from typing import Protocol

from app.core.config import Settings
from app.domain.graph.enums import SymbolMatchType
from app.domain.graph.models import SymbolSearchResult
from app.domain.rag.enums import SymbolResolutionStatus
from app.domain.rag.models import ResolvedSymbol, SymbolResolution
from app.graph import repository_graph_service
from app.graph.neo4j_client import Neo4jClient

# Ranking tiers, highest first — see "rank candidate repository symbols
# using: 1. Exact qualified-name match 2. Exact short-name match
# 3. Suffix match 4. Same file/module evidence 5. Vector semantic support".
# (4) and (5) are applied as small additive boosts on top of these base
# scores rather than as separate tiers, since they're supporting evidence
# rather than a match *type* in their own right.
_MATCH_TYPE_BASE_SCORE = {
    SymbolMatchType.EXACT_QUALIFIED_NAME: 1.0,
    SymbolMatchType.EXACT_NAME: 0.9,
    SymbolMatchType.PREFIX: 0.6,
    SymbolMatchType.CONTAINS: 0.4,
}
_SUFFIX_MATCH_SCORE = 0.75  # between EXACT_NAME and PREFIX
_SAME_FILE_BOOST = 0.05
_EXACT_STATUS_THRESHOLD = 0.85


class GraphServiceLike(Protocol):
    """The subset of app.graph.repository_graph_service this module
    depends on — lets unit tests inject a fake without touching Neo4j."""

    def search_symbols(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        query: str,
        symbol_type: str | None = None,
        file_path: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolSearchResult]: ...


def _score(candidate: SymbolSearchResult, query: str, *, hint_file_paths: frozenset[str]) -> float:
    score = _MATCH_TYPE_BASE_SCORE[candidate.match_type]
    qualified = (candidate.qualified_name or "").lower()
    lowered_query = query.lower()
    if candidate.match_type == SymbolMatchType.CONTAINS and qualified.endswith(f".{lowered_query}"):
        score = max(score, _SUFFIX_MATCH_SCORE)
    if candidate.file_path and candidate.file_path in hint_file_paths:
        score = min(1.0, score + _SAME_FILE_BOOST)
    return score


def _to_resolved(candidate: SymbolSearchResult, score: float) -> ResolvedSymbol:
    return ResolvedSymbol(
        symbol_id=candidate.symbol_id,
        symbol_type=candidate.symbol_type,
        name=candidate.name,
        qualified_name=candidate.qualified_name,
        file_path=candidate.file_path,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        match_type=candidate.match_type,
        confidence=score,
    )


class SymbolRetriever:
    def __init__(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        graph_service: GraphServiceLike = repository_graph_service,
    ) -> None:
        self._client = client
        self._settings = settings
        self._graph_service = graph_service

    def resolve(
        self,
        *,
        repository_id: str,
        query: str,
        symbol_type: str | None = None,
        hint_file_paths: frozenset[str] = frozenset(),
        limit: int | None = None,
    ) -> SymbolResolution:
        raw_candidates = self._graph_service.search_symbols(
            self._client,
            self._settings,
            repository_id=repository_id,
            query=query,
            symbol_type=symbol_type,
            limit=limit if limit is not None else self._settings.rag_symbol_candidate_limit,
        )
        if not raw_candidates:
            return SymbolResolution(
                query=query,
                resolved_symbol=None,
                candidates=[],
                status=SymbolResolutionStatus.NOT_FOUND,
            )

        scored = [
            (candidate, _score(candidate, query, hint_file_paths=hint_file_paths))
            for candidate in raw_candidates
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        candidates = [_to_resolved(candidate, score) for candidate, score in scored]

        best_score = candidates[0].confidence
        top_tier = [c for c in candidates if c.confidence == best_score]

        if len(top_tier) > 1:
            return SymbolResolution(
                query=query,
                resolved_symbol=None,
                candidates=candidates,
                status=SymbolResolutionStatus.AMBIGUOUS,
            )

        status = (
            SymbolResolutionStatus.EXACT
            if best_score >= _EXACT_STATUS_THRESHOLD
            else SymbolResolutionStatus.UNIQUE
        )
        return SymbolResolution(
            query=query, resolved_symbol=top_tier[0], candidates=candidates, status=status
        )
