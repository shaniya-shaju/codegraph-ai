"""API-independent graph domain models — see DATA_MODEL.md "Neo4j: knowledge
graph schema" for the node/relationship vocabulary these mirror.

Nothing here imports the ``neo4j`` driver package (rule 10: "Keep
graph-query responses independent from raw Neo4j driver objects") — see
app.graph.mappers for the translation from driver Records to these models.
"""
