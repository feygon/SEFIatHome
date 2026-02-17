"""Database adapter subpackage for SEFI@Home.

Provides read-only access to rhowardstone SQLite databases and ingestion
of pre-extracted JSON exports into working tables.
"""

from sefi.db.ingest import IngestManager, IngestResult

__all__: list[str] = ["IngestManager", "IngestResult"]
