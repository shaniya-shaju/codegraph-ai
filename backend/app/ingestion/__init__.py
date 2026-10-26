"""Repository acquisition (ZIP upload / git clone) and file scanning.

See ARCHITECTURE.md "Repository ingestion flow". Tree-sitter parsing and
graph/vector writes are not implemented yet — this package currently only
gets a repository's files safely onto disk and produces file-level
statistics (see app.ingestion.scanner).
"""
