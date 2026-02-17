"""Ingest module for SEFI@Home.

Loads the four rhowardstone JSON export files into SQLite working tables.
Validates that all required files are present before any table is touched,
and logs record counts at INFO level after each file is ingested.

Supported files and their target tables:
    persons_registry.json           -> persons
    knowledge_graph_entities.json   -> entities
    knowledge_graph_relationships.json -> relationships
    efta_dataset_mapping.json       -> efta_mapping
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Maps (file basename) -> (working table name).
_FILE_TABLE_MAP: dict[str, str] = {
    "persons_registry.json": "persons",
    "knowledge_graph_entities.json": "entities",
    "knowledge_graph_relationships.json": "relationships",
    "efta_dataset_mapping.json": "efta_mapping",
}


class IngestResult(BaseModel):
    """Summary of a completed ingest operation.

    Attributes:
        table_counts: Mapping of table name to number of records loaded.
    """

    table_counts: dict[str, int]


class IngestManager:
    """Manages loading of rhowardstone JSON exports into SQLite working tables.

    Each call to :meth:`ingest_all` is idempotent: it drops and recreates the
    four working tables before inserting, so repeated calls produce consistent
    state.

    Args:
        conn: An open :class:`sqlite3.Connection`.  The caller is responsible
            for opening and closing the connection.  Pass an in-memory
            connection (``sqlite3.connect(":memory:")``) for tests.
        data_dir: Directory that contains the four JSON export files.
    """

    def __init__(self, conn: sqlite3.Connection, data_dir: Path) -> None:
        """Initialise the manager.

        Args:
            conn: An open SQLite connection.
            data_dir: Path to the directory that holds the JSON exports.
        """
        self._conn = conn
        self._data_dir = data_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_all(self) -> dict[str, int]:
        """Load all four rhowardstone JSON export files into working tables.

        Files are validated for existence before any database writes occur.
        If any required file is missing, an :class:`FileNotFoundError` is
        raised immediately with the missing filename in the message — no
        partial ingest takes place.

        Record counts are logged at ``INFO`` level after each file is loaded.

        Returns:
            A dict mapping each working table name to the number of records
            inserted, e.g.::

                {
                    "persons": 1614,
                    "entities": 524,
                    "relationships": 2096,
                    "efta_mapping": 12,
                }

        Raises:
            FileNotFoundError: If any of the four required JSON files is
                absent from the configured *data_dir*.  The error message
                includes the missing filename.
        """
        self._validate_files_exist()

        counts: dict[str, int] = {}
        counts["persons"] = self.ingest_persons()
        counts["entities"] = self.ingest_entities()
        counts["relationships"] = self.ingest_relationships()
        counts["efta_mapping"] = self.ingest_efta_mapping()
        return counts

    def ingest_persons(self) -> int:
        """Load ``persons_registry.json`` into the ``persons`` working table.

        Creates (or recreates) the ``persons`` table with columns derived from
        the known schema of the rhowardstone export.  Each record stores the
        raw JSON blob alongside indexed scalar fields for efficient lookup.

        Returns:
            The number of person records inserted.

        Raises:
            FileNotFoundError: If ``persons_registry.json`` is absent.
        """
        path = self._require_file("persons_registry.json")
        records: list[dict[str, Any]] = self._load_json_array(path)

        self._conn.execute("DROP TABLE IF EXISTS persons")
        self._conn.execute(
            """
            CREATE TABLE persons (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id   TEXT,
                name        TEXT,
                category    TEXT,
                aliases     TEXT,
                raw_json    TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_persons_name ON persons (name)"
        )

        for record in records:
            self._conn.execute(
                """
                INSERT INTO persons (person_id, name, category, aliases, raw_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _scalar(record.get("id") or record.get("person_id")),
                    _scalar(record.get("name")),
                    _scalar(record.get("category")),
                    _json_field(record.get("aliases")),
                    json.dumps(record),
                ),
            )

        self._conn.commit()
        count = len(records)
        logger.info("Ingested %d records into table 'persons'", count)
        return count

    def ingest_entities(self) -> int:
        """Load ``knowledge_graph_entities.json`` into the ``entities`` table.

        Creates (or recreates) the ``entities`` table.  Each row stores scalar
        fields used for filtering (entity type, name) alongside the full JSON
        blob so no data is lost.

        Returns:
            The number of entity records inserted.

        Raises:
            FileNotFoundError: If ``knowledge_graph_entities.json`` is absent.
        """
        path = self._require_file("knowledge_graph_entities.json")
        records: list[dict[str, Any]] = self._load_json_array(path)

        self._conn.execute("DROP TABLE IF EXISTS entities")
        self._conn.execute(
            """
            CREATE TABLE entities (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id   TEXT,
                name        TEXT,
                entity_type TEXT,
                aliases     TEXT,
                raw_json    TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (entity_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name)"
        )

        for record in records:
            self._conn.execute(
                """
                INSERT INTO entities (entity_id, name, entity_type, aliases, raw_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _scalar(record.get("id") or record.get("entity_id")),
                    _scalar(record.get("name")),
                    _scalar(record.get("type") or record.get("entity_type")),
                    _json_field(record.get("aliases")),
                    json.dumps(record),
                ),
            )

        self._conn.commit()
        count = len(records)
        logger.info("Ingested %d records into table 'entities'", count)
        return count

    def ingest_relationships(self) -> int:
        """Load ``knowledge_graph_relationships.json`` into ``relationships``.

        Creates (or recreates) the ``relationships`` table.  Typed edges are
        stored with scalar source/target/type fields for graph traversal plus
        the raw JSON blob.

        Returns:
            The number of relationship records inserted.

        Raises:
            FileNotFoundError: If ``knowledge_graph_relationships.json`` is absent.
        """
        path = self._require_file("knowledge_graph_relationships.json")
        records: list[dict[str, Any]] = self._load_json_array(path)

        self._conn.execute("DROP TABLE IF EXISTS relationships")
        self._conn.execute(
            """
            CREATE TABLE relationships (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                relationship_id   TEXT,
                source_entity     TEXT,
                target_entity     TEXT,
                relationship_type TEXT,
                weight            REAL,
                raw_json          TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships (source_entity)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships (target_entity)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships (relationship_type)"
        )

        for record in records:
            # Accept multiple possible key names from upstream JSON.
            source = _scalar(
                record.get("source")
                or record.get("source_entity")
                or record.get("from")
            )
            target = _scalar(
                record.get("target")
                or record.get("target_entity")
                or record.get("to")
            )
            rel_type = _scalar(
                record.get("type")
                or record.get("relationship_type")
                or record.get("relation")
            )
            weight_raw = record.get("weight") or record.get("confidence")
            weight: float | None = float(weight_raw) if weight_raw is not None else None
            rel_id = _scalar(record.get("id") or record.get("relationship_id"))

            self._conn.execute(
                """
                INSERT INTO relationships
                    (relationship_id, source_entity, target_entity,
                     relationship_type, weight, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rel_id, source, target, rel_type, weight, json.dumps(record)),
            )

        self._conn.commit()
        count = len(records)
        logger.info("Ingested %d records into table 'relationships'", count)
        return count

    def ingest_efta_mapping(self) -> int:
        """Load ``efta_dataset_mapping.json`` into the ``efta_mapping`` table.

        The upstream file maps EFTA number ranges to DOJ dataset numbers.  Its
        top-level structure may be a JSON array of range objects *or* a JSON
        object keyed by dataset number.  Either way every logical record is
        stored with ``range_start``, ``range_end``, and ``dataset_number``
        scalar columns where the values can be extracted; otherwise only the
        raw JSON blob is stored so no data is lost.

        Returns:
            The number of mapping records inserted.

        Raises:
            FileNotFoundError: If ``efta_dataset_mapping.json`` is absent.
        """
        path = self._require_file("efta_dataset_mapping.json")
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)

        records = _normalise_efta_mapping(data)

        self._conn.execute("DROP TABLE IF EXISTS efta_mapping")
        self._conn.execute(
            """
            CREATE TABLE efta_mapping (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_number INTEGER,
                range_start    INTEGER,
                range_end      INTEGER,
                raw_json       TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_efta_dataset ON efta_mapping (dataset_number)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_efta_range ON efta_mapping (range_start, range_end)"
        )

        for record in records:
            self._conn.execute(
                """
                INSERT INTO efta_mapping
                    (dataset_number, range_start, range_end, raw_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.get("dataset_number"),
                    record.get("range_start"),
                    record.get("range_end"),
                    json.dumps(record),
                ),
            )

        self._conn.commit()
        count = len(records)
        logger.info("Ingested %d records into table 'efta_mapping'", count)
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_files_exist(self) -> None:
        """Verify all four required JSON files are present in *data_dir*.

        Args: (none — uses ``self._data_dir``)

        Raises:
            FileNotFoundError: For the *first* missing file found, with the
                filename included in the error message.
        """
        for filename in _FILE_TABLE_MAP:
            path = self._data_dir / filename
            if not path.is_file():
                raise FileNotFoundError(
                    f"Required data file is missing: '{filename}'. "
                    f"Expected at: {path}. "
                    f"Run the fetch commands in data/FETCH.md to download it."
                )

    def _require_file(self, filename: str) -> Path:
        """Return the :class:`Path` for *filename* or raise if absent.

        Args:
            filename: Basename of the required file.

        Returns:
            Absolute path to the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = self._data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Required data file is missing: '{filename}'. "
                f"Expected at: {path}. "
                f"Run the fetch commands in data/FETCH.md to download it."
            )
        return path

    def _load_json_array(self, path: Path) -> list[dict[str, Any]]:
        """Read *path* and return its contents as a list of dicts.

        Args:
            path: Path to a JSON file whose top-level value is a JSON array.

        Returns:
            A list of dicts (one per record).

        Raises:
            ValueError: If the file does not contain a JSON array at the top
                level.
        """
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(
                f"Expected a JSON array in '{path.name}', "
                f"got {type(data).__name__}."
            )
        return data  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public class surface)
# ---------------------------------------------------------------------------


def _scalar(value: Any) -> str | None:
    """Coerce *value* to a string suitable for a SQLite TEXT column.

    Args:
        value: Any JSON-decoded value.

    Returns:
        The string representation of *value*, or ``None`` if *value* is
        ``None``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _json_field(value: Any) -> str | None:
    """Serialise *value* to a JSON string for storage in a TEXT column.

    Args:
        value: Any JSON-serialisable value, or ``None``.

    Returns:
        A compact JSON string, or ``None`` if *value* is ``None``.
    """
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"))


def _normalise_efta_mapping(data: Any) -> list[dict[str, Any]]:
    """Convert the raw EFTA mapping JSON into a uniform list of dicts.

    The upstream file may be structured as:

    * A JSON **array** where each element is a mapping record (preferred).
    * A JSON **object** keyed by dataset number, where each value describes
      the range(s) for that dataset.

    In either case the returned list has one dict per logical record with
    at least a ``raw_json`` key.  Scalar ``dataset_number``, ``range_start``,
    and ``range_end`` keys are populated wherever the upstream data supplies
    them.

    Args:
        data: The Python object produced by ``json.loads()`` on the file.

    Returns:
        A normalised list of mapping dicts.
    """
    if isinstance(data, list):
        # Array of records — attempt to extract scalar fields from each.
        result: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                result.append({"raw_json": json.dumps(item)})
                continue
            record: dict[str, Any] = dict(item)
            # Normalise range_start / range_end from various possible key names.
            # Use explicit None checks so that 0 is not treated as missing.
            record["range_start"] = _int_or_none(
                _first_not_none(
                    item.get("range_start"),
                    item.get("start"),
                    item.get("efta_start"),
                )
            )
            record["range_end"] = _int_or_none(
                _first_not_none(
                    item.get("range_end"),
                    item.get("end"),
                    item.get("efta_end"),
                )
            )
            record["dataset_number"] = _int_or_none(
                _first_not_none(
                    item.get("dataset_number"),
                    item.get("dataset"),
                    item.get("dataset_id"),
                )
            )
            result.append(record)
        return result

    if isinstance(data, dict):
        # Object keyed by dataset — each value may be a dict with range info
        # or itself a list of sub-ranges.
        result = []
        for key, value in data.items():
            dataset_num = _int_or_none(key)
            if isinstance(value, list):
                for sub in value:
                    record = sub if isinstance(sub, dict) else {"data": sub}
                    record = dict(record)
                    record.setdefault("dataset_number", dataset_num)
                    record["range_start"] = _int_or_none(
                        _first_not_none(
                            record.get("range_start"),
                            record.get("start"),
                            record.get("efta_start"),
                        )
                    )
                    record["range_end"] = _int_or_none(
                        _first_not_none(
                            record.get("range_end"),
                            record.get("end"),
                            record.get("efta_end"),
                        )
                    )
                    result.append(record)
            elif isinstance(value, dict):
                record = dict(value)
                record.setdefault("dataset_number", dataset_num)
                record["range_start"] = _int_or_none(
                    _first_not_none(
                        record.get("range_start"),
                        record.get("start"),
                        record.get("efta_start"),
                    )
                )
                record["range_end"] = _int_or_none(
                    _first_not_none(
                        record.get("range_end"),
                        record.get("end"),
                        record.get("efta_end"),
                    )
                )
                result.append(record)
            else:
                # Primitive value — store as-is.
                result.append(
                    {
                        "dataset_number": dataset_num,
                        "range_start": None,
                        "range_end": None,
                        "value": value,
                    }
                )
        return result

    # Unexpected structure — wrap the whole thing as one blob record.
    return [{"dataset_number": None, "range_start": None, "range_end": None}]


def _first_not_none(*values: Any) -> Any:
    """Return the first value in *values* that is not ``None``.

    Unlike ``or``-chaining, this correctly handles falsy-but-non-None values
    such as ``0``, ``""`` or ``False``.

    Args:
        *values: Candidate values, tried in order.

    Returns:
        The first non-``None`` value, or ``None`` if all candidates are ``None``.
    """
    for v in values:
        if v is not None:
            return v
    return None


def _int_or_none(value: Any) -> int | None:
    """Convert *value* to ``int`` if possible, otherwise return ``None``.

    Args:
        value: Any value.

    Returns:
        Integer conversion of *value*, or ``None`` on failure.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
