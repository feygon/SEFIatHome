"""Unit tests for US-002: Data Fetch & Ingest Bootstrap.

Covers every acceptance criterion from todo/US-002.md plus key error paths
and edge cases.  All filesystem interaction is mocked via tmp_path; no live
network calls are made; database tests use in-memory SQLite (:memory:).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sefi.db.ingest import (
    IngestManager,
    IngestResult,
    _first_not_none,
    _int_or_none,
    _json_field,
    _normalise_efta_mapping,
    _scalar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    """Open a fresh in-memory SQLite connection."""
    return sqlite3.connect(":memory:")


def _write_json(directory: Path, filename: str, data: Any) -> Path:
    """Serialise *data* to JSON and write it to *directory/filename*."""
    path = directory / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _minimal_persons(n: int = 3) -> list[dict[str, Any]]:
    """Return a minimal persons_registry-style list of *n* records."""
    return [
        {"id": str(i), "name": f"Person {i}", "category": "subject", "aliases": []}
        for i in range(n)
    ]


def _minimal_entities(n: int = 3) -> list[dict[str, Any]]:
    """Return a minimal knowledge_graph_entities-style list of *n* records."""
    return [
        {
            "id": str(i),
            "name": f"Entity {i}",
            "type": "person",
            "aliases": [],
        }
        for i in range(n)
    ]


def _minimal_relationships(n: int = 3) -> list[dict[str, Any]]:
    """Return a minimal knowledge_graph_relationships-style list of *n* records."""
    return [
        {
            "id": str(i),
            "source": f"entity_{i}",
            "target": f"entity_{i + 1}",
            "type": "knows",
            "weight": 0.9,
        }
        for i in range(n)
    ]


def _minimal_efta_array(n: int = 3) -> list[dict[str, Any]]:
    """Return a minimal efta_dataset_mapping array-style list."""
    return [
        {
            "dataset_number": i + 1,
            "range_start": i * 100,
            "range_end": (i + 1) * 100 - 1,
        }
        for i in range(n)
    ]


def _write_all_files(tmp: Path, *, n: int = 3) -> None:
    """Write all four required JSON files into *tmp* with *n* records each."""
    _write_json(tmp, "persons_registry.json", _minimal_persons(n))
    _write_json(tmp, "knowledge_graph_entities.json", _minimal_entities(n))
    _write_json(tmp, "knowledge_graph_relationships.json", _minimal_relationships(n))
    _write_json(tmp, "efta_dataset_mapping.json", _minimal_efta_array(n))


# ---------------------------------------------------------------------------
# AC: ingest_all() returns a dict of {table_name: record_count}  (FR-047)
# ---------------------------------------------------------------------------


class TestIngestAllReturnShape:
    """ingest_all() must return a dict mapping table names to record counts."""

    def test_returns_dict_with_four_keys(self, tmp_path: Path) -> None:
        """ingest_all() must return exactly the four expected table-name keys."""
        _write_all_files(tmp_path, n=2)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        result = mgr.ingest_all()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"persons", "entities", "relationships", "efta_mapping"}

    def test_values_are_integers(self, tmp_path: Path) -> None:
        """All values in the returned dict must be non-negative integers."""
        _write_all_files(tmp_path, n=5)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        result = mgr.ingest_all()
        for table, count in result.items():
            assert isinstance(count, int), f"Count for '{table}' is not int"
            assert count >= 0, f"Count for '{table}' is negative"

    def test_counts_match_written_records(self, tmp_path: Path) -> None:
        """Returned counts must match the number of records written to each file."""
        n = 7
        _write_all_files(tmp_path, n=n)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        result = mgr.ingest_all()
        assert result["persons"] == n
        assert result["entities"] == n
        assert result["relationships"] == n
        assert result["efta_mapping"] == n

    def test_tables_are_queryable_after_ingest_all(self, tmp_path: Path) -> None:
        """All four tables must exist and be queryable after ingest_all()."""
        _write_all_files(tmp_path, n=4)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_all()
        for table in ("persons", "entities", "relationships", "efta_mapping"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            assert row is not None and row[0] == 4, f"Table '{table}' not populated"


# ---------------------------------------------------------------------------
# AC: persons_registry.json → 1,614 records  (DR-001) — validated with fake data
# ---------------------------------------------------------------------------


class TestIngestPersons:
    """Tests for ingest_persons() covering happy-path and error cases."""

    def test_ingest_persons_returns_correct_count(self, tmp_path: Path) -> None:
        """ingest_persons() must return the exact count of records in the file."""
        n = 10
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_persons()
        assert count == n

    def test_persons_table_row_count_matches(self, tmp_path: Path) -> None:
        """The persons table must contain exactly as many rows as the file had records."""
        n = 8
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_persons()
        (db_count,) = conn.execute("SELECT COUNT(*) FROM persons").fetchone()
        assert db_count == n

    def test_persons_accepts_dr001_scale(self, tmp_path: Path) -> None:
        """ingest_persons() must handle 1,614 records without error (DR-001 scale)."""
        records = _minimal_persons(1614)
        _write_json(tmp_path, "persons_registry.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_persons()
        assert count == 1614

    def test_persons_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """ingest_persons() must raise FileNotFoundError when the file is absent."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError, match="persons_registry.json"):
            mgr.ingest_persons()

    def test_persons_raw_json_stored(self, tmp_path: Path) -> None:
        """Each person record must store a raw_json blob in the persons table."""
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(2))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_persons()
        rows = conn.execute("SELECT raw_json FROM persons").fetchall()
        for (raw,) in rows:
            assert raw is not None
            decoded = json.loads(raw)
            assert isinstance(decoded, dict)

    def test_persons_is_idempotent(self, tmp_path: Path) -> None:
        """Calling ingest_persons() twice must not duplicate rows."""
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(5))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_persons()
        mgr.ingest_persons()
        (count,) = conn.execute("SELECT COUNT(*) FROM persons").fetchone()
        assert count == 5


# ---------------------------------------------------------------------------
# AC: knowledge_graph_relationships.json → 2,096 records  (DR-002)
# ---------------------------------------------------------------------------


class TestIngestRelationships:
    """Tests for ingest_relationships() covering happy-path and error cases."""

    def test_ingest_relationships_returns_correct_count(self, tmp_path: Path) -> None:
        """ingest_relationships() must return the exact count of records in the file."""
        n = 12
        _write_json(
            tmp_path,
            "knowledge_graph_relationships.json",
            _minimal_relationships(n),
        )
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_relationships()
        assert count == n

    def test_relationships_table_row_count_matches(self, tmp_path: Path) -> None:
        """The relationships table must contain exactly as many rows as the file had."""
        n = 6
        _write_json(
            tmp_path,
            "knowledge_graph_relationships.json",
            _minimal_relationships(n),
        )
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_relationships()
        (db_count,) = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()
        assert db_count == n

    def test_relationships_accepts_dr002_scale(self, tmp_path: Path) -> None:
        """ingest_relationships() must handle 2,096 records without error (DR-002 scale)."""
        records = _minimal_relationships(2096)
        _write_json(tmp_path, "knowledge_graph_relationships.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_relationships()
        assert count == 2096

    def test_relationships_missing_file_raises_file_not_found(
        self, tmp_path: Path
    ) -> None:
        """ingest_relationships() must raise FileNotFoundError when the file is absent."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(
            FileNotFoundError, match="knowledge_graph_relationships.json"
        ):
            mgr.ingest_relationships()

    def test_relationships_alternative_key_names(self, tmp_path: Path) -> None:
        """Relationships using 'from'/'to' key names must still be ingested."""
        records = [{"id": "r1", "from": "a", "to": "b", "type": "knows"}]
        _write_json(tmp_path, "knowledge_graph_relationships.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_relationships()
        assert count == 1
        row = conn.execute(
            "SELECT source_entity, target_entity FROM relationships"
        ).fetchone()
        assert row == ("a", "b")


# ---------------------------------------------------------------------------
# AC: efta_dataset_mapping.json populates a usable working table  (DR-003)
# ---------------------------------------------------------------------------


class TestIngestEftaMapping:
    """Tests for ingest_efta_mapping() covering array and dict JSON structures."""

    def test_efta_array_style_returns_correct_count(self, tmp_path: Path) -> None:
        """ingest_efta_mapping() with an array-style file returns the array length."""
        data = _minimal_efta_array(5)
        _write_json(tmp_path, "efta_dataset_mapping.json", data)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_efta_mapping()
        assert count == 5

    def test_efta_dict_style_returns_correct_count(self, tmp_path: Path) -> None:
        """ingest_efta_mapping() with a dict-style file returns one row per key."""
        data = {
            "1": {"range_start": 0, "range_end": 99},
            "2": {"range_start": 100, "range_end": 199},
        }
        _write_json(tmp_path, "efta_dataset_mapping.json", data)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_efta_mapping()
        assert count == 2

    def test_efta_table_has_range_columns(self, tmp_path: Path) -> None:
        """The efta_mapping table must expose range_start, range_end, dataset_number."""
        data = [{"dataset_number": 3, "range_start": 10, "range_end": 20}]
        _write_json(tmp_path, "efta_dataset_mapping.json", data)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_efta_mapping()
        row = conn.execute(
            "SELECT dataset_number, range_start, range_end FROM efta_mapping"
        ).fetchone()
        assert row == (3, 10, 20)

    def test_efta_table_queryable_for_range_lookup(self, tmp_path: Path) -> None:
        """A query filtering by range_start <= X <= range_end must work."""
        data = [
            {"dataset_number": 1, "range_start": 0, "range_end": 99},
            {"dataset_number": 2, "range_start": 100, "range_end": 199},
        ]
        _write_json(tmp_path, "efta_dataset_mapping.json", data)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_efta_mapping()
        row = conn.execute(
            "SELECT dataset_number FROM efta_mapping "
            "WHERE range_start <= ? AND range_end >= ?",
            (150, 150),
        ).fetchone()
        assert row is not None
        assert row[0] == 2

    def test_efta_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """ingest_efta_mapping() must raise FileNotFoundError when the file is absent."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError, match="efta_dataset_mapping.json"):
            mgr.ingest_efta_mapping()

    def test_efta_dict_list_values(self, tmp_path: Path) -> None:
        """A dict-style file whose values are lists of sub-ranges must expand them."""
        data = {
            "1": [
                {"range_start": 0, "range_end": 49},
                {"range_start": 50, "range_end": 99},
            ]
        }
        _write_json(tmp_path, "efta_dataset_mapping.json", data)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_efta_mapping()
        assert count == 2


# ---------------------------------------------------------------------------
# AC: knowledge_graph_entities.json → 524 records  (DR-004)
# ---------------------------------------------------------------------------


class TestIngestEntities:
    """Tests for ingest_entities() covering happy-path and error cases."""

    def test_ingest_entities_returns_correct_count(self, tmp_path: Path) -> None:
        """ingest_entities() must return the exact count of records in the file."""
        n = 15
        _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_entities()
        assert count == n

    def test_entities_accepts_dr004_scale(self, tmp_path: Path) -> None:
        """ingest_entities() must handle 524 records without error (DR-004 scale)."""
        records = _minimal_entities(524)
        _write_json(tmp_path, "knowledge_graph_entities.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_entities()
        assert count == 524

    def test_entities_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """ingest_entities() must raise FileNotFoundError when the file is absent."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError, match="knowledge_graph_entities.json"):
            mgr.ingest_entities()

    def test_entities_table_row_count_matches(self, tmp_path: Path) -> None:
        """The entities table must contain exactly as many rows as the file had."""
        n = 9
        _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_entities()
        (db_count,) = conn.execute("SELECT COUNT(*) FROM entities").fetchone()
        assert db_count == n

    def test_entities_entity_type_stored(self, tmp_path: Path) -> None:
        """Entity type values must be stored in the entity_type column."""
        records = [
            {"id": "1", "name": "Alpha", "type": "person"},
            {"id": "2", "name": "BetaCorp", "type": "shell_company"},
        ]
        _write_json(tmp_path, "knowledge_graph_entities.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        mgr.ingest_entities()
        types = {
            row[0]
            for row in conn.execute("SELECT entity_type FROM entities").fetchall()
        }
        assert "person" in types
        assert "shell_company" in types


# ---------------------------------------------------------------------------
# AC: Missing file raises FileNotFoundError naming the file  (FR-047)
# ---------------------------------------------------------------------------


class TestMissingFileErrors:
    """ingest_all() must raise FileNotFoundError naming each missing file."""

    @pytest.mark.parametrize(
        "missing_file",
        [
            "persons_registry.json",
            "knowledge_graph_entities.json",
            "knowledge_graph_relationships.json",
            "efta_dataset_mapping.json",
        ],
    )
    def test_ingest_all_raises_for_each_missing_file(
        self, tmp_path: Path, missing_file: str
    ) -> None:
        """ingest_all() must raise FileNotFoundError when any single file is absent."""
        # Write all files, then remove the one under test.
        _write_all_files(tmp_path, n=2)
        (tmp_path / missing_file).unlink()

        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError) as exc_info:
            mgr.ingest_all()
        # The error message must name the missing file.
        assert missing_file in str(exc_info.value)

    def test_ingest_all_raises_when_data_dir_empty(self, tmp_path: Path) -> None:
        """ingest_all() must raise FileNotFoundError when data dir has no files at all."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.ingest_all()

    def test_error_message_is_human_readable(self, tmp_path: Path) -> None:
        """The FileNotFoundError message must be non-empty and mention the filename."""
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError) as exc_info:
            mgr.ingest_all()
        msg = str(exc_info.value)
        assert len(msg) > 20, "Error message is too short to be human-readable"
        # Must name at least one of the required files.
        required_files = list(
            {
                "persons_registry.json",
                "knowledge_graph_entities.json",
                "knowledge_graph_relationships.json",
                "efta_dataset_mapping.json",
            }
        )
        assert any(f in msg for f in required_files)

    def test_no_partial_write_on_missing_file(self, tmp_path: Path) -> None:
        """When ingest_all() fails on a missing file, no tables should be written."""
        # Write only one file — ingest_all must fail before any DB write.
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(2))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.ingest_all()
        # persons table must NOT exist if validation stopped execution.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "persons" not in tables


# ---------------------------------------------------------------------------
# AC: Record counts logged at INFO level after each file load  (FR-047)
# ---------------------------------------------------------------------------


class TestLogging:
    """Record counts must be logged at INFO level after each file ingest."""

    def test_ingest_persons_logs_count_at_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_persons() must emit at least one INFO-level log with the count."""
        n = 4
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            mgr.ingest_persons()
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records, "No INFO log emitted by ingest_persons()"
        assert any(str(n) in r.message for r in info_records), (
            f"No INFO log message contains the count '{n}'"
        )

    def test_ingest_entities_logs_count_at_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_entities() must emit at least one INFO-level log with the count."""
        n = 6
        _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            mgr.ingest_entities()
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records
        assert any(str(n) in r.message for r in info_records)

    def test_ingest_relationships_logs_count_at_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_relationships() must emit at least one INFO-level log with the count."""
        n = 3
        _write_json(
            tmp_path,
            "knowledge_graph_relationships.json",
            _minimal_relationships(n),
        )
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            mgr.ingest_relationships()
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records
        assert any(str(n) in r.message for r in info_records)

    def test_ingest_efta_logs_count_at_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_efta_mapping() must emit at least one INFO-level log with the count."""
        n = 5
        _write_json(tmp_path, "efta_dataset_mapping.json", _minimal_efta_array(n))
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            mgr.ingest_efta_mapping()
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records
        assert any(str(n) in r.message for r in info_records)

    def test_ingest_all_logs_info_for_all_four_tables(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_all() must emit INFO logs mentioning all four table names."""
        _write_all_files(tmp_path, n=2)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            mgr.ingest_all()
        all_messages = " ".join(r.message for r in caplog.records)
        for table in ("persons", "entities", "relationships", "efta_mapping"):
            assert table in all_messages, (
                f"No INFO log mentions table '{table}'"
            )


# ---------------------------------------------------------------------------
# AC: SQL uses parameterised ? placeholders; no string interpolation  (NFR-004)
# ---------------------------------------------------------------------------


class TestSqlParameterization:
    """Verify SQL uses ? parameters, not f-strings or % formatting."""

    def test_ingest_py_source_has_no_sql_fstrings(self) -> None:
        """ingest.py must not concatenate user data into SQL via f-strings."""
        import inspect  # noqa: PLC0415

        import sefi.db.ingest as ingest_module  # noqa: PLC0415

        source = inspect.getsource(ingest_module)
        # Heuristic: look for execute( with an f-string argument.
        # A genuine f-string SQL injection pattern would have f" or f' followed
        # by SQL keywords on the same expression passed to execute().
        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Flag lines that call .execute(f"  or .execute(f'
            if ".execute(f" in stripped or '.execute(f"' in stripped:
                pytest.fail(
                    f"Possible SQL f-string injection at ingest.py line {lineno}: {line!r}"
                )

    def test_all_inserts_use_placeholder_tuple(self, tmp_path: Path) -> None:
        """A successful ingest must complete without sqlite3 raising ProgrammingError."""
        # If SQL had format-string injection issues, sqlite3 would raise
        # ProgrammingError on incorrect number of bindings.
        _write_all_files(tmp_path, n=3)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        # Should complete without raising any sqlite3 error.
        result = mgr.ingest_all()
        assert len(result) == 4


# ---------------------------------------------------------------------------
# AC: All functions have type annotations and docstrings  (NFR-002, NFR-008)
# ---------------------------------------------------------------------------


class TestTypeAnnotationsAndDocstrings:
    """Public API must have type annotations and docstrings."""

    def test_ingest_manager_has_docstring(self) -> None:
        """IngestManager class must have a non-empty docstring."""
        assert IngestManager.__doc__ and IngestManager.__doc__.strip()

    def test_ingest_result_has_docstring(self) -> None:
        """IngestResult must have a non-empty docstring."""
        assert IngestResult.__doc__ and IngestResult.__doc__.strip()

    def test_ingest_all_has_docstring(self) -> None:
        """IngestManager.ingest_all must have a non-empty docstring."""
        assert IngestManager.ingest_all.__doc__ and IngestManager.ingest_all.__doc__.strip()

    def test_ingest_persons_has_docstring(self) -> None:
        """IngestManager.ingest_persons must have a non-empty docstring."""
        assert IngestManager.ingest_persons.__doc__ and IngestManager.ingest_persons.__doc__.strip()

    def test_ingest_entities_has_docstring(self) -> None:
        """IngestManager.ingest_entities must have a non-empty docstring."""
        assert IngestManager.ingest_entities.__doc__ and IngestManager.ingest_entities.__doc__.strip()

    def test_ingest_relationships_has_docstring(self) -> None:
        """IngestManager.ingest_relationships must have a non-empty docstring."""
        assert (
            IngestManager.ingest_relationships.__doc__
            and IngestManager.ingest_relationships.__doc__.strip()
        )

    def test_ingest_efta_mapping_has_docstring(self) -> None:
        """IngestManager.ingest_efta_mapping must have a non-empty docstring."""
        assert (
            IngestManager.ingest_efta_mapping.__doc__
            and IngestManager.ingest_efta_mapping.__doc__.strip()
        )

    def test_ingest_all_return_annotation(self) -> None:
        """ingest_all() must be annotated to return dict[str, int]."""
        import inspect  # noqa: PLC0415

        hints = IngestManager.ingest_all.__annotations__
        assert "return" in hints, "ingest_all() has no return annotation"

    def test_ingest_persons_return_annotation(self) -> None:
        """ingest_persons() must be annotated to return int."""
        hints = IngestManager.ingest_persons.__annotations__
        assert "return" in hints

    def test_ingest_manager_init_annotations(self) -> None:
        """__init__ parameters must all be annotated."""
        import inspect  # noqa: PLC0415

        sig = inspect.signature(IngestManager.__init__)
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            assert param.annotation is not inspect.Parameter.empty, (
                f"IngestManager.__init__ parameter '{name}' lacks type annotation"
            )


# ---------------------------------------------------------------------------
# AC: IngestResult is a valid Pydantic v2 model  (NFR-003)
# ---------------------------------------------------------------------------


class TestIngestResultPydantic:
    """IngestResult must behave as a proper Pydantic v2 BaseModel."""

    def test_ingest_result_is_pydantic_model(self) -> None:
        """IngestResult must be a subclass of pydantic.BaseModel."""
        from pydantic import BaseModel  # noqa: PLC0415

        assert issubclass(IngestResult, BaseModel)

    def test_ingest_result_validates_table_counts(self) -> None:
        """IngestResult must accept a valid table_counts dict."""
        r = IngestResult(table_counts={"persons": 5, "entities": 3})
        assert r.table_counts["persons"] == 5

    def test_ingest_result_rejects_non_dict(self) -> None:
        """IngestResult must reject table_counts that is not a dict."""
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError):
            IngestResult(table_counts="not_a_dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Unit tests for module-level helper functions."""

    # _first_not_none
    def test_first_not_none_returns_first_non_none(self) -> None:
        assert _first_not_none(None, 0, 5) == 0  # 0 is non-None, must not be skipped

    def test_first_not_none_all_none_returns_none(self) -> None:
        assert _first_not_none(None, None) is None

    def test_first_not_none_first_value_wins(self) -> None:
        assert _first_not_none(1, 2, 3) == 1

    # _scalar
    def test_scalar_none_returns_none(self) -> None:
        assert _scalar(None) is None

    def test_scalar_string_passthrough(self) -> None:
        assert _scalar("hello") == "hello"

    def test_scalar_int_to_str(self) -> None:
        assert _scalar(42) == "42"

    def test_scalar_list_to_str(self) -> None:
        result = _scalar([1, 2, 3])
        assert isinstance(result, str)

    # _json_field
    def test_json_field_none_returns_none(self) -> None:
        assert _json_field(None) is None

    def test_json_field_list_serialised(self) -> None:
        result = _json_field(["a", "b"])
        assert result is not None
        assert json.loads(result) == ["a", "b"]

    def test_json_field_dict_serialised(self) -> None:
        result = _json_field({"key": "value"})
        assert result is not None
        assert json.loads(result) == {"key": "value"}

    # _int_or_none
    def test_int_or_none_with_int(self) -> None:
        assert _int_or_none(5) == 5

    def test_int_or_none_with_str_int(self) -> None:
        assert _int_or_none("42") == 42

    def test_int_or_none_with_none(self) -> None:
        assert _int_or_none(None) is None

    def test_int_or_none_with_garbage(self) -> None:
        assert _int_or_none("not_a_number") is None

    # _normalise_efta_mapping
    def test_normalise_efta_array(self) -> None:
        data = [{"dataset_number": 1, "range_start": 0, "range_end": 99}]
        result = _normalise_efta_mapping(data)
        assert len(result) == 1
        assert result[0]["dataset_number"] == 1
        assert result[0]["range_start"] == 0

    def test_normalise_efta_dict_flat(self) -> None:
        data = {"1": {"range_start": 0, "range_end": 99}}
        result = _normalise_efta_mapping(data)
        assert len(result) == 1
        assert result[0]["dataset_number"] == 1

    def test_normalise_efta_dict_with_list_value(self) -> None:
        data = {
            "2": [
                {"range_start": 0, "range_end": 49},
                {"range_start": 50, "range_end": 99},
            ]
        }
        result = _normalise_efta_mapping(data)
        assert len(result) == 2
        for r in result:
            assert r["dataset_number"] == 2

    def test_normalise_efta_unexpected_type_returns_one_record(self) -> None:
        result = _normalise_efta_mapping("unexpected_string")
        assert len(result) == 1

    def test_normalise_efta_primitive_dict_values(self) -> None:
        """Dict values that are primitives must produce one record each."""
        data = {"1": "some_value", "2": 42}
        result = _normalise_efta_mapping(data)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Edge-case / error-path tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge-case and error-path coverage."""

    def test_ingest_persons_empty_array(self, tmp_path: Path) -> None:
        """An empty persons_registry.json must ingest 0 records without error."""
        _write_json(tmp_path, "persons_registry.json", [])
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_persons()
        assert count == 0

    def test_ingest_persons_non_array_raises_value_error(self, tmp_path: Path) -> None:
        """A persons_registry.json that is a JSON object must raise ValueError."""
        _write_json(tmp_path, "persons_registry.json", {"key": "value"})
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        with pytest.raises(ValueError, match="JSON array"):
            mgr.ingest_persons()

    def test_ingest_relationships_empty_array(self, tmp_path: Path) -> None:
        """An empty relationships file must ingest 0 records without error."""
        _write_json(tmp_path, "knowledge_graph_relationships.json", [])
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_relationships()
        assert count == 0

    def test_ingest_entities_records_with_null_fields(self, tmp_path: Path) -> None:
        """Entities with null optional fields must be ingested without error."""
        records = [{"id": None, "name": None, "type": None, "aliases": None}]
        _write_json(tmp_path, "knowledge_graph_entities.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_entities()
        assert count == 1

    def test_ingest_all_second_call_is_idempotent(self, tmp_path: Path) -> None:
        """Calling ingest_all() twice must yield consistent counts on second call."""
        _write_all_files(tmp_path, n=3)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        first = mgr.ingest_all()
        second = mgr.ingest_all()
        assert first == second

    def test_persons_with_alternate_id_key(self, tmp_path: Path) -> None:
        """person_id key (instead of id) must be accepted by ingest_persons()."""
        records = [{"person_id": "p1", "name": "Alice", "category": "subject"}]
        _write_json(tmp_path, "persons_registry.json", records)
        conn = _make_conn()
        mgr = IngestManager(conn, tmp_path)
        count = mgr.ingest_persons()
        assert count == 1
        row = conn.execute("SELECT person_id FROM persons").fetchone()
        assert row[0] == "p1"
