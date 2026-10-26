"""Cross-cutting operational-state persistence — currently just
``RepositoryAnalysisState`` (see models.py), the explicit per-subsystem
analysis-readiness record introduced by the integration-reliability task.

Repository *identity* (name, source, commit) still lives in
``app.domain.repositories`` — this package is for state that's about the
*process* of analyzing a repository, not the repository itself. No
Alembic migrations exist yet in this project (see
app.core.database.init_db) — table creation is still via
``Base.metadata.create_all()``.
"""
