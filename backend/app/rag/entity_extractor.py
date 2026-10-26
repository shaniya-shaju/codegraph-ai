"""Heuristic entity extraction from a natural-language question.

Extracts *mentioned* strings only — this module never checks them
against the repository (see "Distinguish: mentioned entity / resolved
repository symbol"; resolution happens in symbol_retriever.py). Original
casing/spelling is preserved verbatim in every extracted string (see
"Entity extraction should preserve original strings").
"""

import re
from dataclasses import dataclass, field

_API_ROUTE_RE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/[A-Za-z0-9_\-/{}]*)", re.IGNORECASE)
_FILE_PATH_RE = re.compile(r"\b[\w][\w\-./]*\.py\b")
# "app.auth.service.login" / "AuthService.login" — a dotted chain of
# identifiers, most specific entity form, extracted before its
# individual segments are considered separately.
_DOTTED_NAME_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
# "login()" / "find_by_email()" — parens are a strong function-call signal.
_CALL_LIKE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)")
# "AuthService" / "UserRepository" — CamelCase, at least two humps.
_CAMEL_CASE_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b")


@dataclass(frozen=True)
class ExtractedEntities:
    symbols: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    module_names: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    function_names: list[str] = field(default_factory=list)
    api_routes: list[str] = field(default_factory=list)


def _dedup_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def extract_entities(raw_question: str) -> ExtractedEntities:
    symbols: list[str] = []
    file_paths: list[str] = []
    module_names: list[str] = []
    class_names: list[str] = []
    function_names: list[str] = []
    api_routes: list[str] = []

    for method, path in _API_ROUTE_RE.findall(raw_question):
        api_routes.append(f"{method.upper()} {path}")

    for match in _FILE_PATH_RE.findall(raw_question):
        file_paths.append(match)
        module_names.append(match)
        symbols.append(match)

    consumed_spans: list[tuple[int, int]] = []
    for match in _DOTTED_NAME_RE.finditer(raw_question):
        dotted = match.group(0)
        if dotted in file_paths:
            continue  # already handled as a file path
        consumed_spans.append(match.span())
        symbols.append(dotted)
        segments = dotted.split(".")
        first, last = segments[0], segments[-1]
        if first[0].isupper():
            class_names.append(first)
        if last[0].islower() or "_" in last:
            function_names.append(last)
        elif last[0].isupper():
            class_names.append(last)
        if len(segments) > 2:
            module_names.append(".".join(segments[:-1]))

    def _inside_consumed(pos: int) -> bool:
        return any(start <= pos < end for start, end in consumed_spans)

    for match in _CALL_LIKE_RE.finditer(raw_question):
        if _inside_consumed(match.start()):
            continue
        name = match.group(1)
        function_names.append(name)
        symbols.append(name)

    for match in _CAMEL_CASE_RE.finditer(raw_question):
        if _inside_consumed(match.start()):
            continue
        name = match.group(1)
        class_names.append(name)
        symbols.append(name)

    return ExtractedEntities(
        symbols=_dedup_preserve_order(symbols),
        file_paths=_dedup_preserve_order(file_paths),
        module_names=_dedup_preserve_order(module_names),
        class_names=_dedup_preserve_order(class_names),
        function_names=_dedup_preserve_order(function_names),
        api_routes=_dedup_preserve_order(api_routes),
    )
