"""Neo4j-backed source-code knowledge graph: writes and bounded reads.

See ARCHITECTURE.md "Tree-sitter parsing flow" / DATA_MODEL.md "Neo4j:
knowledge graph schema". Layering, strictly one-directional:

- ``neo4j_client.py`` — the only module that imports the ``neo4j`` driver
  package. Connectivity, sessions, transactions, shutdown.
- ``schema.py`` — constraints/indexes, all repository_id-scoped.
- ``queries.py`` — every Cypher string used anywhere in this package,
  always parameterized (never string-interpolated user input — see
  SECURITY.md).
- ``mappers.py`` — Record <-> domain model translation, both directions
  (read: neo4j Record -> app.domain.graph.models; write: parsed-symbol
  dataclasses -> Cypher-ready parameter dicts + deterministic IDs).
- ``relationship_resolver.py`` — the conservative CALLS/EXTENDS resolution
  rules, pure logic over already-parsed data.
- ``graph_builder.py`` — write-side orchestration: idempotent upserts +
  stale-node cleanup, one file per transaction.
- ``repository_graph_service.py`` — read-side orchestration: bounded,
  repository_id-scoped queries for the API layer.

Nothing here calls an LLM, and nothing here is the source of a graph fact
that didn't come from app.parsing's deterministic output (AGENTS.md rules
1-2).
"""
