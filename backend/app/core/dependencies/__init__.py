"""Centralized dependency-status tracking: circuit breaking for Neo4j and
a single place that reports READY/DEGRADED/UNAVAILABLE/NOT_LOADED/UNKNOWN
for every external dependency (database, Neo4j, ChromaDB, embedding
provider) — see the integration-reliability task's "Dependency-state
service": "Avoid each endpoint performing independent health logic."
"""
