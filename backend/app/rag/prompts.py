"""Prompt text for the optional LLM query analyzer.

Plain string templates — no LangChain/provider imports here (rule:
"LangChain should be behind the provider implementation rather than
imported throughout the business logic"). Deliberately does not embed
any repository source code (see "LLM query analysis must never receive
more repository content than necessary" / "Query analysis should usually
require only the user's question, not the repository source").
"""

QUERY_ANALYSIS_SYSTEM_PROMPT = """\
You classify natural-language questions about a Python source-code \
repository for a retrieval system. You do not answer the question and \
you do not have access to the repository's source code.

Given a question, decide:
1. Its primary intent, from a fixed set of categories.
2. Any secondary intents that also plausibly apply.
3. Any identifiers the question literally mentions: function names, \
class names, module names, file paths, or "METHOD /path" API routes.

Rules:
- Only extract identifiers that are literally present (or a very close \
paraphrase) in the question text. Never invent an identifier.
- Do not claim an extracted identifier exists in the repository — you \
have no way to verify that; extraction only records what the question \
mentions.
- confidence is a heuristic self-assessment of classification certainty \
in [0, 1], not a calibrated probability.
"""


def build_query_analysis_user_prompt(question: str) -> str:
    return f"Classify this question about a code repository:\n\n{question}"
