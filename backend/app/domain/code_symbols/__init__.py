"""Parsed source-code symbol models — the parser's output contract.

These are plain data models (no ORM, no Pydantic-over-the-wire concerns):
the deterministic parsing layer (app.parsing) produces them; a future
graph-construction stage (not implemented yet) will consume them. See
ARCHITECTURE.md "Tree-sitter parsing flow" and AGENTS.md rule 9 ("keep
parser output independent from Neo4j and database-specific models").
"""
