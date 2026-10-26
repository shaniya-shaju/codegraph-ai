#!/usr/bin/env python3
"""Real Neo4j connectivity smoke test — see Prompt 11.5 "Real Neo4j
smoke test". Uses the actually-configured Neo4jClient (no mocking):
connects, verifies connectivity, ensures the required schema
(constraints/indexes — idempotent, see app/graph/schema.py), and runs one
harmless read query. Never writes/alters repository graph data.

Usage:
    python scripts/check_neo4j.py

Exits 0 on success, 1 on any failure.
"""

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.graph.exceptions import Neo4jConnectionError, Neo4jQueryError  # noqa: E402
from app.graph.neo4j_client import Neo4jClient  # noqa: E402
from app.graph.schema import ensure_schema  # noqa: E402


def main() -> int:
    settings = get_settings()
    print("CodeGraph AI — Neo4j check")
    print(f"URI: {settings.neo4j_uri}")
    print(f"Database: {settings.neo4j_database}")
    print()

    client = Neo4jClient(settings)
    try:
        if not client.verify_connectivity():
            print("[FAIL] connectivity")
            print(
                "Reason: could not verify connectivity — is `docker compose up -d neo4j` "
                "running? See docs/TROUBLESHOOTING.md \"Neo4j unavailable\"."
            )
            return 1
        print("[PASS] connectivity")

        try:
            ensure_schema(client)
            print("[PASS] schema (constraints/indexes ensured — idempotent)")
        except (Neo4jConnectionError, Neo4jQueryError) as exc:
            print("[FAIL] schema")
            print(f"Reason: {exc}")
            return 1

        try:
            rows = client.execute_read("RETURN 1 AS ok", {})
            ok = bool(rows) and rows[0]["ok"] == 1
        except (Neo4jConnectionError, Neo4jQueryError) as exc:
            print("[FAIL] read query")
            print(f"Reason: {exc}")
            return 1
        if not ok:
            print("[FAIL] read query")
            print("Reason: unexpected result from a trivial `RETURN 1` query.")
            return 1
        print("[PASS] read query")
    finally:
        client.close()

    print()
    print("Neo4j is reachable and ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
