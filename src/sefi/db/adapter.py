"""Database adapter for SEFI@Home.

Provides the high-level read interface over the ingested JSON working tables.
``DatabaseAdapter`` is the public API; ``IngestManager`` is the implementation
detail used internally to load JSON exports.

Typical usage::

    import sqlite3
    from pathlib import Path
    from sefi.db.adapter import DatabaseAdapter

    conn = sqlite3.connect(":memory:")
    adapter = DatabaseAdapter(conn)
    adapter.load_json_export(Path("data/persons_registry.json"), "persons")
    persons = adapter.get_persons_registry()
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from sefi.db.ingest import IngestManager

logger = logging.getLogger(__name__)


class DatabaseAdapter:
    """High-level read interface over SEFI@Home ingested working tables.

    Wraps :class:`~sefi.db.ingest.IngestManager` for data loading and exposes
    three named query methods — :meth:`get_known_entities`,
    :meth:`get_known_relationships`, and :meth:`get_persons_registry` — plus
    the generic :meth:`load_json_export` ingestion entry point.

    All SQL queries use ``?`` parameterised placeholders.  No ORM is used.

    Args:
        conn: An open :class:`sqlite3.Connection`, **or** a
            :class:`pathlib.Path` / ``str`` pointing to a SQLite file.
            Pass ``sqlite3.connect(":memory:")`` to run entirely in-memory
            (useful in tests).
    """

    def __init__(self, conn: sqlite3.Connection | Path | str) -> None:
        """Initialise the adapter.

        Args:
            conn: An open :class:`sqlite3.Connection`, or a path string /
                :class:`~pathlib.Path` to a SQLite file that will be opened
                automatically.  When a path is supplied the adapter owns the
                connection and will configure ``row_factory`` automatically.
        """
        if isinstance(conn, sqlite3.Connection):
            self._conn = conn
            # Ensure rows are returned as sqlite3.Row so we can call dict().
            self._conn.row_factory = sqlite3.Row
        else:
            path = Path(conn)
            self._conn = sqlite3.connect(str(path))
            self._conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # Ingestion entry point
    # ------------------------------------------------------------------

    def load_json_export(self, file_path: Path | str, table_name: str) -> int:
        """Load a rhowardstone JSON export file into a working table.

        Delegates to :class:`~sefi.db.ingest.IngestManager` to perform the
        actual ingest.  The appropriate ingest method is selected based on
        *table_name*.

        Supported *table_name* values and the files they expect:

        +---------------------+-----------------------------------+
        | ``table_name``      | Expected file                     |
        +=====================+===================================+
        | ``persons``         | ``persons_registry.json``         |
        +---------------------+-----------------------------------+
        | ``entities``        | ``knowledge_graph_entities.json`` |
        +---------------------+-----------------------------------+
        | ``relationships``   | ``knowledge_graph_relationships.json`` |
        +---------------------+-----------------------------------+
        | ``efta_mapping``    | ``efta_dataset_mapping.json``     |
        +---------------------+-----------------------------------+

        Args:
            file_path: Path to the JSON export file.  May be a
                :class:`~pathlib.Path` or a ``str``.
            table_name: Name of the SQLite working table to populate.  Must
                be one of the four values listed above.

        Returns:
            The integer count of records loaded from *file_path*.

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            ValueError: If *table_name* is not one of the four supported
                values.
        """
        file_path = Path(file_path)
        data_dir = file_path.parent

        manager = IngestManager(conn=self._conn, data_dir=data_dir)

        dispatch: dict[str, Any] = {
            "persons": manager.ingest_persons,
            "entities": manager.ingest_entities,
            "relationships": manager.ingest_relationships,
            "efta_mapping": manager.ingest_efta_mapping,
        }

        if table_name not in dispatch:
            supported = ", ".join(f"'{k}'" for k in sorted(dispatch))
            raise ValueError(
                f"Unknown table_name '{table_name}'. "
                f"Supported values are: {supported}."
            )

        # IngestManager derives the filename from the table; we verify the
        # caller-supplied file exists under the expected name so the error
        # message is clear when the path is wrong.
        if not file_path.is_file():
            raise FileNotFoundError(
                f"JSON export file not found: '{file_path}'. "
                "Verify the path and re-run."
            )

        count: int = dispatch[table_name]()
        return count

    # ------------------------------------------------------------------
    # Named query methods
    # ------------------------------------------------------------------

    def get_known_entities(self) -> list[dict[str, Any]]:
        """Return all entity records from the ``entities`` working table.

        Each returned dict is reconstructed from the stored raw JSON blob so
        that every field present in the original export is available, not only
        the scalar columns indexed for querying.  At minimum every dict
        contains ``id``, ``name``, ``type``, and ``aliases`` keys (populated
        from the scalar columns when the raw JSON does not supply them).

        Returns:
            A ``list[dict]`` with one entry per entity record.  Returns an
            empty list if the ``entities`` table has not been populated yet.

        Raises:
            sqlite3.OperationalError: If the ``entities`` table does not exist
                (i.e. :meth:`load_json_export` has not been called for
                entities yet).
        """
        cursor = self._conn.execute(
            "SELECT entity_id, name, entity_type, aliases, raw_json FROM entities"
        )
        rows = cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            record = _row_to_dict(row)
            results.append(record)
        return results

    def get_known_relationships(self) -> list[dict[str, Any]]:
        """Return all relationship records from the ``relationships`` table.

        Each returned dict is reconstructed from the stored raw JSON blob so
        that every field from the original export is preserved.

        Returns:
            A ``list[dict]`` with one entry per relationship record.  Returns
            an empty list if the ``relationships`` table is not populated.

        Raises:
            sqlite3.OperationalError: If the ``relationships`` table does not
                exist.
        """
        cursor = self._conn.execute(
            "SELECT relationship_id, source_entity, target_entity,"
            " relationship_type, weight, raw_json FROM relationships"
        )
        rows = cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            record = _row_to_dict(row)
            results.append(record)
        return results

    def get_persons_registry(self) -> list[dict[str, Any]]:
        """Return all records from the ``persons`` working table.

        Each returned dict is reconstructed from the stored raw JSON blob so
        that every field from the original export is preserved.

        Returns:
            A ``list[dict]`` with one entry per person record.  Returns an
            empty list if the ``persons`` table has not been populated yet.

        Raises:
            sqlite3.OperationalError: If the ``persons`` table does not exist.
        """
        cursor = self._conn.execute(
            "SELECT person_id, name, category, aliases, raw_json FROM persons"
        )
        rows = cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            record = _row_to_dict(row)
            results.append(record)
        return results

    # ------------------------------------------------------------------
    # Post-MVP stubs
    # ------------------------------------------------------------------

    def paginated_query(
        self,
        sql: str,
        params: tuple[Any, ...],
        page_size: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Execute a paginated SQL query and return (page, total_count).

        Args:
            sql: The base SQL SELECT query (without LIMIT/OFFSET clauses).
            params: Parameterised values for the query (``?`` placeholders).
            page_size: Maximum number of rows to return in this page.
            offset: Number of rows to skip before returning results.

        Returns:
            A tuple of (page_results, total_count) where *page_results* is a
            list of dicts and *total_count* is the total number of matching
            rows ignoring pagination.

        Raises:
            NotImplementedError: Always — this method is reserved for
                Post-MVP implementation (FR-007).
        """
        raise NotImplementedError(
            "paginated_query is a Post-MVP feature (FR-007) and has not been "
            "implemented yet."
        )

    def get_efta_range(
        self, dataset: int, start: int, end: int
    ) -> list[dict[str, Any]]:
        """Return documents in a given EFTA number range within a dataset.

        Args:
            dataset: DOJ dataset number (1–12).
            start: Inclusive lower bound of the EFTA number range.
            end: Inclusive upper bound of the EFTA number range.

        Returns:
            A list of dicts with at minimum an ``efta_number`` field, each
            falling within the inclusive [start, end] range for *dataset*.

        Raises:
            NotImplementedError: Always — this method is reserved for
                Post-MVP implementation (FR-009).
        """
        raise NotImplementedError(
            "get_efta_range is a Post-MVP feature (FR-009) and has not been "
            "implemented yet."
        )

    def get_document_versions(self, efta_number: str) -> list[dict[str, Any]]:
        """Return all available versions of a document identified by EFTA number.

        Args:
            efta_number: EFTA-format document identifier (e.g.
                ``"EFTA00039186"``).

        Returns:
            A list of dicts, one per document version.

        Raises:
            NotImplementedError: Always — this method is reserved for
                Post-MVP implementation (FR-010).
        """
        raise NotImplementedError(
            "get_document_versions is a Post-MVP feature (FR-010) and has not "
            "been implemented yet."
        )

    def get_redactions_for_document(
        self, efta_number: str
    ) -> list[dict[str, Any]]:
        """Return all redaction records for a given document.

        Args:
            efta_number: EFTA-format document identifier (e.g.
                ``"EFTA00039186"``).

        Returns:
            A list of dicts, one per redaction record, each containing
            coordinate and document-version fields.

        Raises:
            NotImplementedError: Always — this method is reserved for
                Post-MVP implementation (FR-011).
        """
        raise NotImplementedError(
            "get_redactions_for_document is a Post-MVP feature (FR-011) and "
            "has not been implemented yet."
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a :class:`sqlite3.Row` to a plain ``dict``.

    If a ``raw_json`` column is present and parseable, the function returns
    the *merged* record: the raw JSON dict is used as the base so that all
    original fields are preserved, then the scalar columns overlay any keys
    they supply (ensuring ``id``, ``name``, ``type``, ``aliases``, etc. are
    always present at the top level).

    Args:
        row: A ``sqlite3.Row`` instance with ``row_factory = sqlite3.Row``.

    Returns:
        A plain :class:`dict` with string keys and JSON-compatible values.
    """
    base: dict[str, Any] = dict(row)
    raw_json_str: str | None = base.pop("raw_json", None)

    if raw_json_str:
        try:
            parsed: Any = json.loads(raw_json_str)
            if isinstance(parsed, dict):
                # Start from the raw JSON so upstream fields are preserved,
                # then overlay the indexed scalar columns.
                merged: dict[str, Any] = dict(parsed)
                for k, v in base.items():
                    if v is not None:
                        merged[k] = v
                return merged
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse raw_json for row; returning scalar columns only.")

    return base
