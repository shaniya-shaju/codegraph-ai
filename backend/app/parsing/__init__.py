"""Deterministic, language-pluggable source-code parsing.

See ARCHITECTURE.md "Tree-sitter parsing flow" and AGENTS.md rule 10. The
public surface is:

- ``app.parsing.base.LanguageParser`` — the protocol every language
  parser implements.
- ``app.parsing.registry.ParserRegistry`` / ``build_default_registry`` /
  ``parse_source_bytes`` — register parsers and dispatch to the right one.
- ``app.parsing.python.parser.PythonParser`` — the only language shipped
  so far.

This package never executes, imports, or evaluates the source it parses
(see SECURITY.md "Parsing safety"), and never calls Neo4j, ChromaDB,
LangChain, or an LLM (see AGENTS.md rules 1-3) — its only output is the
domain models in app.domain.code_symbols.
"""
