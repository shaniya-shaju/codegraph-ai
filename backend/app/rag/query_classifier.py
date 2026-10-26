"""Deterministic heuristic intent classifier.

Always available (no network, no LLM) — this is query_analyzer.py's
mandatory fallback, per "The deterministic analyzer must always be
available as fallback." Classification uses ordered phrase/pattern rules
across several signals (not a single keyword lookup — see "Do not use
simple keyword matching as the only classifier"), each contributing to a
primary intent plus any other intents whose patterns also matched.
"""

import re
from dataclasses import dataclass

from app.domain.rag.enums import QueryIntent

_API_ROUTE_RE = re.compile(r"\b(get|post|put|delete|patch)\s+/\S*", re.IGNORECASE)

# Each rule: (intent, base_confidence, [compiled patterns]). Order matters —
# more specific intents are checked before more general ones so e.g. an
# "impact of changing X" question isn't absorbed by the looser
# CODE_EXPLANATION rule.
_RULES: list[tuple[QueryIntent, float, list[re.Pattern[str]]]] = [
    (
        QueryIntent.API_LOOKUP,
        0.85,
        [
            _API_ROUTE_RE,
            re.compile(r"\bendpoint\b"),
            re.compile(r"\broute\b.*\bhandles?\b"),
            re.compile(r"\bhandles?\b.*\b(get|post|put|delete|patch)\b", re.IGNORECASE),
        ],
    ),
    (
        QueryIntent.IMPACT_ANALYSIS,
        0.85,
        [
            re.compile(r"\bwhat\s+(happens?|changes?)\s+if\b"),
            re.compile(r"\bimpact\s+of\b"),
            re.compile(r"\bif\s+i\s+(change|modify|remove|delete)\b"),
            re.compile(r"\b(if|when)\b.*\b(is|are)\s+(changed|modified|removed|deleted)\b"),
            re.compile(r"\baffected\s+by\b"),
            re.compile(r"\bblast\s+radius\b"),
            re.compile(r"\b(may|might|could)\s+be\s+affected\b"),
            re.compile(r"\b(is|are)\s+(potentially\s+)?impacted\b"),
            re.compile(r"\bhow\s+risky\b"),
        ],
    ),
    (
        QueryIntent.CALLER_LOOKUP,
        0.85,
        [
            re.compile(r"\bwho\s+calls\b"),
            re.compile(r"\bwhich\s+(functions?|methods?)\s+calls?\b"),
            re.compile(r"\bcallers?\s+of\b"),
            re.compile(r"\bwhat\s+calls\b"),
        ],
    ),
    (
        QueryIntent.CALLEE_LOOKUP,
        0.85,
        [
            re.compile(r"\bwhat\s+(functions?|methods?)\s+does\b.*\bcalls?\b"),
            re.compile(r"\bwhat\s+does\b.*\bcalls?\b"),
            re.compile(r"\bcalls?\s+made\s+by\b"),
            re.compile(r"\bwhat\s+is\s+called\s+by\b"),
        ],
    ),
    (
        QueryIntent.INHERITANCE_LOOKUP,
        0.8,
        [
            re.compile(r"\bextends?\b"),
            re.compile(r"\binherits?\s+from\b"),
            re.compile(r"\bsubclass(es)?\s+of\b"),
            re.compile(r"\bbase\s+class(es)?\s+of\b"),
            re.compile(r"\bparent\s+class\b"),
        ],
    ),
    (
        QueryIntent.DEPENDENCY_LOOKUP,
        0.8,
        [
            re.compile(r"\bdepends?\s+on\b"),
            re.compile(r"\bdependenc(y|ies)\s+of\b"),
            re.compile(r"\bwhat\s+does\b.*\bimports?\b"),
            re.compile(r"\bwhat\s+imports\b"),
        ],
    ),
    (
        QueryIntent.ARCHITECTURE,
        0.8,
        [
            re.compile(r"\barchitecture\b"),
            re.compile(r"\bhow\s+is\b.*\b(structured|organized|organised)\b"),
            re.compile(r"\boverview\s+of\b.*\b(repository|repo|project|codebase)\b"),
            re.compile(r"\bhow\s+is\s+(this|the)\s+(repository|repo|project|codebase)\b"),
        ],
    ),
    (
        QueryIntent.CODE_LOCATION,
        0.75,
        [
            re.compile(r"\bwhere\s+is\b"),
            re.compile(r"\bwhere\s+(can|do)\s+i\s+find\b"),
            re.compile(r"\bwhich\s+file\b"),
            re.compile(r"\blocated?\b"),
        ],
    ),
    (
        QueryIntent.CODE_EXPLANATION,
        0.7,
        [
            re.compile(r"\bexplain\b"),
            re.compile(r"\bwhat\s+does\b.*\bdo\b"),
            re.compile(r"\bhow\s+does\b.*\bwork\b"),
            re.compile(r"\bdescribe\b"),
        ],
    ),
]

_GENERAL_CODE_HINTS = re.compile(
    r"\b(function|method|class|module|file|code|symbol|variable|parameter)\b"
)


@dataclass(frozen=True)
class ClassificationResult:
    primary_intent: QueryIntent
    secondary_intents: list[QueryIntent]
    confidence: float


def classify_intent(normalized_question: str) -> ClassificationResult:
    """Ordered, multi-signal, deterministic classification.

    Every rule whose patterns match contributes; the highest-confidence
    match becomes ``primary_intent`` and the rest become
    ``secondary_intents`` (see "secondary_intents: list[QueryIntent]").
    """
    matches: list[tuple[QueryIntent, float]] = []
    for intent, base_confidence, patterns in _RULES:
        if any(pattern.search(normalized_question) for pattern in patterns):
            matches.append((intent, base_confidence))

    if not matches:
        if _GENERAL_CODE_HINTS.search(normalized_question):
            return ClassificationResult(QueryIntent.GENERAL_CODE_QUESTION, [], 0.4)
        return ClassificationResult(QueryIntent.UNKNOWN, [], 0.15)

    matches.sort(key=lambda pair: pair[1], reverse=True)
    primary_intent, confidence = matches[0]
    secondary_intents = [intent for intent, _ in matches[1:]]
    return ClassificationResult(primary_intent, secondary_intents, confidence)
