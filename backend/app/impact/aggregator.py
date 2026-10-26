"""File/module aggregation and conservative test-reference detection —
kept deliberately separate from graph traversal and risk scoring (see the
impact-analysis task's package layout: "Keep graph traversal, signal
calculation and risk scoring separate. Do not build one large impact
service.")."""

import re

from app.domain.impact.enums import ImpactType, TestRelationshipStatus
from app.domain.impact.models import ImpactedFile, ImpactedModule, ImpactedSymbol
from app.impact.mappers import module_of

# Conservative test-file recognition, per "Recognize test files
# conservatively using patterns such as: tests/, test_*.py, *_test.py" —
# used ONLY to filter a set of symbols already reached by a real graph
# relationship (a CALLS edge). A filename match alone never manufactures
# a test relationship (see "Do NOT equate filename matching with
# dependency evidence.").
_TEST_PATH_RE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")


def is_test_file_path(file_path: str | None) -> bool:
    if not file_path:
        return False
    return bool(_TEST_PATH_RE.search(file_path))


def aggregate_files(symbols: list[ImpactedSymbol]) -> list[ImpactedFile]:
    """One row per distinct file_path — never duplicated (see "Do not
    count the same file multiple times.")."""
    by_file: dict[str, list[ImpactedSymbol]] = {}
    for symbol in symbols:
        if symbol.file_path is None:
            continue
        by_file.setdefault(symbol.file_path, []).append(symbol)

    files = []
    for file_path, group in by_file.items():
        impact_types: list[ImpactType] = []
        for s in group:
            if s.impact_type not in impact_types:
                impact_types.append(s.impact_type)
        files.append(
            ImpactedFile(
                file_path=file_path,
                affected_symbol_count=len(group),
                minimum_distance=min(s.distance for s in group),
                impact_types=impact_types,
                impacted_symbol_ids=[s.symbol_id for s in group],
            )
        )
    files.sort(key=lambda f: (f.minimum_distance, f.file_path))
    return files


def aggregate_modules(symbols: list[ImpactedSymbol]) -> list[ImpactedModule]:
    by_module: dict[str, list[ImpactedSymbol]] = {}
    for symbol in symbols:
        module_name = module_of(symbol.qualified_name, fallback_file_path=symbol.file_path)
        by_module.setdefault(module_name, []).append(symbol)

    modules = []
    for module_name, group in by_module.items():
        modules.append(
            ImpactedModule(
                module_name=module_name,
                affected_symbol_count=len(group),
                minimum_distance=min(s.distance for s in group),
                impacted_symbol_ids=[s.symbol_id for s in group],
            )
        )
    modules.sort(key=lambda m: (m.minimum_distance, m.module_name))
    return modules


def classify_test_references(
    dependents: list[ImpactedSymbol], *, truncated: bool
) -> tuple[list[ImpactedSymbol], TestRelationshipStatus]:
    """Related tests are exactly the subset of already-graph-connected
    dependents (direct/transitive callers) whose file path looks like a
    test file — never a separate, weaker "filename only" search (see
    "only label them as related if an actual graph relationship connects
    them.").

    ``NO_KNOWN_TEST_REFERENCES`` is returned when none were found and the
    traversal was not truncated (so the search was exhaustive within the
    configured bound); ``UNKNOWN`` when truncation means dependents beyond
    the bound were never examined, so an honest "no tests" claim can't be
    made (see "NO_KNOWN_TEST_REFERENCES must NOT be presented as 'there
    are no tests.'")."""
    related = [s for s in dependents if is_test_file_path(s.file_path)]
    related = [
        ImpactedSymbol(
            symbol_id=s.symbol_id,
            qualified_name=s.qualified_name,
            symbol_type=s.symbol_type,
            file_path=s.file_path,
            start_line=s.start_line,
            end_line=s.end_line,
            impact_type=ImpactType.TEST_REFERENCE,
            distance=s.distance,
            reason=f"{s.file_path} matches a conservative test-file pattern and has a real "
            "graph CALLS relationship to the target.",
            path=s.path,
            relationship_path=s.relationship_path,
        )
        for s in related
    ]
    if related:
        return related, TestRelationshipStatus.KNOWN_RELATED_TESTS
    if truncated:
        return related, TestRelationshipStatus.UNKNOWN
    return related, TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES
