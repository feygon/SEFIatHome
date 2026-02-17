"""Unit tests for US-004: DatabaseAdapter (JSON Methods).

Covers every acceptance criterion from todo/US-004.md plus key error paths
and edge cases.  All HTTP calls are mocked (there are none in the adapter
itself, but IngestManager filesystem calls use tmp_path).  All database
tests use in-memory SQLite (:memory:).

No live network calls are made; no real data files are required.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sefi.db.adapter import DatabaseAdapter, _row_to_dict


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    """Open a fresh in-memory SQLite connection with Row factory."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _write_json(directory: Path, filename: str, data: Any) -> Path:
    """Serialise *data* to JSON and write it to *directory/filename*."""
    path = directory / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _minimal_persons(n: int = 3) -> list[dict[str, Any]]:
    return [
        {"id": str(i), "name": f"Person {i}", "category": "subject", "aliases": []}
        for i in range(n)
    ]


def _minimal_entities(n: int = 3) -> list[dict[str, Any]]:
    return [
        {"id": str(i), "name": f"Entity {i}", "type": "person", "aliases": []}
        for i in range(n)
    ]


def _minimal_relationships(n: int = 3) -> list[dict[str, Any]]:
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


def _make_adapter_with_data(
    tmp_path: Path, *, persons: int = 3, entities: int = 3, rels: int = 3, efta: int = 3
) -> DatabaseAdapter:
    """Return a DatabaseAdapter backed by an in-memory DB with synthetic data loaded."""
    _write_json(tmp_path, "persons_registry.json", _minimal_persons(persons))
    _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(entities))
    _write_json(tmp_path, "knowledge_graph_relationships.json", _minimal_relationships(rels))
    _write_json(tmp_path, "efta_dataset_mapping.json", _minimal_efta_array(efta))

    conn = sqlite3.connect(":memory:")
    adapter = DatabaseAdapter(conn)
    adapter.load_json_export(tmp_path / "persons_registry.json", "persons")
    adapter.load_json_export(tmp_path / "knowledge_graph_entities.json", "entities")
    adapter.load_json_export(
        tmp_path / "knowledge_graph_relationships.json", "relationships"
    )
    adapter.load_json_export(tmp_path / "efta_dataset_mapping.json", "efta_mapping")
    return adapter


# ---------------------------------------------------------------------------
# AC-1: load_json_export() returns int == number of records loaded  (FR-001)
# ---------------------------------------------------------------------------


class TestLoadJsonExport:
    """load_json_export(file_path, table_name) must return the record count."""

    def test_returns_int_for_persons(self, tmp_path: Path) -> None:
        """Return value must be an int equal to the number of person records."""
        n = 7
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(n))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(tmp_path / "persons_registry.json", "persons")
        assert isinstance(count, int)
        assert count == n

    def test_returns_int_for_entities(self, tmp_path: Path) -> None:
        """Return value must be an int equal to the number of entity records."""
        n = 5
        _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(n))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            tmp_path / "knowledge_graph_entities.json", "entities"
        )
        assert isinstance(count, int)
        assert count == n

    def test_returns_int_for_relationships(self, tmp_path: Path) -> None:
        """Return value must be an int equal to the number of relationship records."""
        n = 4
        _write_json(
            tmp_path,
            "knowledge_graph_relationships.json",
            _minimal_relationships(n),
        )
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            tmp_path / "knowledge_graph_relationships.json", "relationships"
        )
        assert isinstance(count, int)
        assert count == n

    def test_returns_int_for_efta_mapping(self, tmp_path: Path) -> None:
        """Return value must be an int equal to the number of efta_mapping records."""
        n = 3
        _write_json(tmp_path, "efta_dataset_mapping.json", _minimal_efta_array(n))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            tmp_path / "efta_dataset_mapping.json", "efta_mapping"
        )
        assert isinstance(count, int)
        assert count == n

    def test_raises_file_not_found_for_missing_file(self, tmp_path: Path) -> None:
        """load_json_export must raise FileNotFoundError when the file does not exist."""
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        with pytest.raises(FileNotFoundError):
            adapter.load_json_export(tmp_path / "persons_registry.json", "persons")

    def test_raises_value_error_for_unknown_table(self, tmp_path: Path) -> None:
        """load_json_export must raise ValueError for an unrecognised table_name."""
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(2))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        with pytest.raises(ValueError, match="Unknown table_name"):
            adapter.load_json_export(tmp_path / "persons_registry.json", "bogus_table")

    def test_returns_correct_count_at_canonical_persons_scale(
        self, tmp_path: Path
    ) -> None:
        """load_json_export must return 1614 for a 1614-record persons file."""
        n = 1614
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(n))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(tmp_path / "persons_registry.json", "persons")
        assert count == n

    def test_returns_correct_count_at_canonical_entities_scale(
        self, tmp_path: Path
    ) -> None:
        """load_json_export must return 524 for a 524-record entities file."""
        n = 524
        _write_json(tmp_path, "knowledge_graph_entities.json", _minimal_entities(n))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            tmp_path / "knowledge_graph_entities.json", "entities"
        )
        assert count == n

    def test_returns_correct_count_at_canonical_relationships_scale(
        self, tmp_path: Path
    ) -> None:
        """load_json_export must return 2096 for a 2096-record relationships file."""
        n = 2096
        _write_json(
            tmp_path,
            "knowledge_graph_relationships.json",
            _minimal_relationships(n),
        )
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            tmp_path / "knowledge_graph_relationships.json", "relationships"
        )
        assert count == n


# ---------------------------------------------------------------------------
# AC-2: get_known_entities() — list[dict] with id, name, type, aliases  (FR-002)
# ---------------------------------------------------------------------------


class TestGetKnownEntities:
    """get_known_entities() must return list[dict] with required fields."""

    def test_returns_list(self, tmp_path: Path) -> None:
        """Return type must be a list."""
        adapter = _make_adapter_with_data(tmp_path, entities=5)
        result = adapter.get_known_entities()
        assert isinstance(result, list)

    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        """Every element must be a plain dict, not a sqlite3.Row."""
        adapter = _make_adapter_with_data(tmp_path, entities=4)
        result = adapter.get_known_entities()
        for item in result:
            assert isinstance(item, dict), f"Expected dict, got {type(item)}"

    def test_record_count_matches_ingested(self, tmp_path: Path) -> None:
        """Number of returned records must equal the number ingested."""
        n = 6
        adapter = _make_adapter_with_data(tmp_path, entities=n)
        result = adapter.get_known_entities()
        assert len(result) == n

    def test_canonical_scale_524_records(self, tmp_path: Path) -> None:
        """get_known_entities() must return 524 records when 524 were loaded."""
        adapter = _make_adapter_with_data(tmp_path, entities=524)
        result = adapter.get_known_entities()
        assert len(result) == 524

    def test_each_dict_has_id_field(self, tmp_path: Path) -> None:
        """Each entity dict must contain an 'id' or 'entity_id' field."""
        adapter = _make_adapter_with_data(tmp_path, entities=3)
        for record in adapter.get_known_entities():
            assert "id" in record or "entity_id" in record, (
                f"Neither 'id' nor 'entity_id' in {list(record.keys())}"
            )

    def test_each_dict_has_name_field(self, tmp_path: Path) -> None:
        """Each entity dict must contain a 'name' field."""
        adapter = _make_adapter_with_data(tmp_path, entities=3)
        for record in adapter.get_known_entities():
            assert "name" in record

    def test_each_dict_has_type_field(self, tmp_path: Path) -> None:
        """Each entity dict must contain a 'type' or 'entity_type' field."""
        adapter = _make_adapter_with_data(tmp_path, entities=3)
        for record in adapter.get_known_entities():
            assert "type" in record or "entity_type" in record, (
                f"Neither 'type' nor 'entity_type' in {list(record.keys())}"
            )

    def test_each_dict_has_aliases_field(self, tmp_path: Path) -> None:
        """Each entity dict must contain an 'aliases' field."""
        adapter = _make_adapter_with_data(tmp_path, entities=3)
        for record in adapter.get_known_entities():
            assert "aliases" in record

    def test_empty_table_returns_empty_list(self, tmp_path: Path) -> None:
        """get_known_entities() must return [] when no entities have been loaded."""
        _write_json(tmp_path, "knowledge_graph_entities.json", [])
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(
            tmp_path / "knowledge_graph_entities.json", "entities"
        )
        assert adapter.get_known_entities() == []

    def test_name_values_match_source(self, tmp_path: Path) -> None:
        """Entity names returned must match the source data."""
        records = [
            {"id": "e1", "name": "Alice", "type": "person", "aliases": []},
            {"id": "e2", "name": "BetaCorp", "type": "shell_company", "aliases": []},
        ]
        _write_json(tmp_path, "knowledge_graph_entities.json", records)
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(
            tmp_path / "knowledge_graph_entities.json", "entities"
        )
        result = adapter.get_known_entities()
        names = {r.get("name") for r in result}
        assert "Alice" in names
        assert "BetaCorp" in names


# ---------------------------------------------------------------------------
# AC-3: get_known_relationships() — list[dict] with 2096 records  (FR-003)
# ---------------------------------------------------------------------------


class TestGetKnownRelationships:
    """get_known_relationships() must return list[dict] with correct count."""

    def test_returns_list(self, tmp_path: Path) -> None:
        """Return type must be a list."""
        adapter = _make_adapter_with_data(tmp_path, rels=4)
        result = adapter.get_known_relationships()
        assert isinstance(result, list)

    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        """Every element must be a plain dict."""
        adapter = _make_adapter_with_data(tmp_path, rels=3)
        for item in adapter.get_known_relationships():
            assert isinstance(item, dict)

    def test_record_count_matches_ingested(self, tmp_path: Path) -> None:
        """Number of returned records must equal the number ingested."""
        n = 8
        adapter = _make_adapter_with_data(tmp_path, rels=n)
        assert len(adapter.get_known_relationships()) == n

    def test_canonical_scale_2096_records(self, tmp_path: Path) -> None:
        """get_known_relationships() must return 2096 records when 2096 were loaded."""
        adapter = _make_adapter_with_data(tmp_path, rels=2096)
        result = adapter.get_known_relationships()
        assert len(result) == 2096

    def test_empty_table_returns_empty_list(self, tmp_path: Path) -> None:
        """get_known_relationships() must return [] when no rels have been loaded."""
        _write_json(tmp_path, "knowledge_graph_relationships.json", [])
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(
            tmp_path / "knowledge_graph_relationships.json", "relationships"
        )
        assert adapter.get_known_relationships() == []

    def test_source_and_target_fields_present(self, tmp_path: Path) -> None:
        """Relationship dicts must include source and target identifiers."""
        records = [
            {"id": "r1", "source": "a", "target": "b", "type": "knows", "weight": 0.5}
        ]
        _write_json(tmp_path, "knowledge_graph_relationships.json", records)
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(
            tmp_path / "knowledge_graph_relationships.json", "relationships"
        )
        result = adapter.get_known_relationships()
        assert len(result) == 1
        r = result[0]
        # source may come from raw_json as 'source', or from scalar as 'source_entity'
        assert "source" in r or "source_entity" in r


# ---------------------------------------------------------------------------
# AC-4: get_persons_registry() — list[dict] with 1614 records  (FR-004)
# ---------------------------------------------------------------------------


class TestGetPersonsRegistry:
    """get_persons_registry() must return list[dict] with correct count."""

    def test_returns_list(self, tmp_path: Path) -> None:
        """Return type must be a list."""
        adapter = _make_adapter_with_data(tmp_path, persons=5)
        assert isinstance(adapter.get_persons_registry(), list)

    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        """Every element must be a plain dict, not a sqlite3.Row."""
        adapter = _make_adapter_with_data(tmp_path, persons=4)
        for item in adapter.get_persons_registry():
            assert isinstance(item, dict)

    def test_record_count_matches_ingested(self, tmp_path: Path) -> None:
        """Number of returned records must equal the number ingested."""
        n = 10
        adapter = _make_adapter_with_data(tmp_path, persons=n)
        assert len(adapter.get_persons_registry()) == n

    def test_canonical_scale_1614_records(self, tmp_path: Path) -> None:
        """get_persons_registry() must return 1614 records when 1614 were loaded."""
        adapter = _make_adapter_with_data(tmp_path, persons=1614)
        result = adapter.get_persons_registry()
        assert len(result) == 1614

    def test_empty_table_returns_empty_list(self, tmp_path: Path) -> None:
        """get_persons_registry() must return [] when no persons have been loaded."""
        _write_json(tmp_path, "persons_registry.json", [])
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(tmp_path / "persons_registry.json", "persons")
        assert adapter.get_persons_registry() == []

    def test_name_values_match_source(self, tmp_path: Path) -> None:
        """Person names returned must match the source data."""
        records = [
            {"id": "p1", "name": "Jeffrey Epstein", "category": "subject", "aliases": []},
            {"id": "p2", "name": "Ghislaine Maxwell", "category": "associate", "aliases": []},
        ]
        _write_json(tmp_path, "persons_registry.json", records)
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        adapter.load_json_export(tmp_path / "persons_registry.json", "persons")
        result = adapter.get_persons_registry()
        names = {r.get("name") for r in result}
        assert "Jeffrey Epstein" in names
        assert "Ghislaine Maxwell" in names


# ---------------------------------------------------------------------------
# AC-5: All SQL uses ? parameterised placeholders — no f-strings / .format()
#       in SQL strings  (NFR-004)
# ---------------------------------------------------------------------------


class TestSqlParameterization:
    """SQL in adapter.py must use ? placeholders; no f-string or .format()."""

    def test_adapter_py_has_no_sql_fstrings(self) -> None:
        """adapter.py must not use f-strings as SQL arguments to execute()."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".execute(f" in stripped or '.execute(f"' in stripped:
                pytest.fail(
                    f"Possible SQL f-string at adapter.py line {lineno}: {line!r}"
                )

    def test_adapter_py_has_no_sql_format_calls(self) -> None:
        """adapter.py must not use .format() to build SQL strings."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        # Look for execute(... .format( patterns — heuristic check.
        # We allow .format() for non-SQL strings (e.g. error messages).
        # Flag only lines that contain both execute and .format( on the same line.
        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".execute(" in stripped and ".format(" in stripped:
                pytest.fail(
                    f"Possible SQL .format() injection at adapter.py line {lineno}: {line!r}"
                )


# ---------------------------------------------------------------------------
# AC-6: No ORM imports in adapter.py  (NFR-004)
# ---------------------------------------------------------------------------


class TestNoOrmImports:
    """adapter.py must not import any ORM libraries."""

    def test_no_sqlalchemy_import(self) -> None:
        """adapter.py must not import SQLAlchemy."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        assert "sqlalchemy" not in source.lower(), "SQLAlchemy found in adapter.py"

    def test_no_peewee_import(self) -> None:
        """adapter.py must not import Peewee."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        assert "peewee" not in source.lower(), "Peewee ORM found in adapter.py"

    def test_no_tortoise_import(self) -> None:
        """adapter.py must not import Tortoise ORM."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        assert "tortoise" not in source.lower(), "Tortoise ORM found in adapter.py"

    def test_no_django_orm_import(self) -> None:
        """adapter.py must not import Django ORM."""
        import sefi.db.adapter as adapter_module  # noqa: PLC0415

        source = inspect.getsource(adapter_module)
        assert "django.db" not in source, "Django ORM import found in adapter.py"


# ---------------------------------------------------------------------------
# AC-7: All methods have type annotations and docstrings  (NFR-002, NFR-008)
# ---------------------------------------------------------------------------


class TestTypeAnnotationsAndDocstrings:
    """All public DatabaseAdapter methods must have annotations and docstrings."""

    def test_class_has_docstring(self) -> None:
        """DatabaseAdapter must have a non-empty class docstring."""
        assert DatabaseAdapter.__doc__ and DatabaseAdapter.__doc__.strip()

    def test_init_has_docstring(self) -> None:
        """__init__ must have a non-empty docstring."""
        assert DatabaseAdapter.__init__.__doc__ and DatabaseAdapter.__init__.__doc__.strip()

    def test_load_json_export_has_docstring(self) -> None:
        """load_json_export must have a non-empty docstring."""
        assert DatabaseAdapter.load_json_export.__doc__
        assert DatabaseAdapter.load_json_export.__doc__.strip()

    def test_get_known_entities_has_docstring(self) -> None:
        """get_known_entities must have a non-empty docstring."""
        assert DatabaseAdapter.get_known_entities.__doc__
        assert DatabaseAdapter.get_known_entities.__doc__.strip()

    def test_get_known_relationships_has_docstring(self) -> None:
        """get_known_relationships must have a non-empty docstring."""
        assert DatabaseAdapter.get_known_relationships.__doc__
        assert DatabaseAdapter.get_known_relationships.__doc__.strip()

    def test_get_persons_registry_has_docstring(self) -> None:
        """get_persons_registry must have a non-empty docstring."""
        assert DatabaseAdapter.get_persons_registry.__doc__
        assert DatabaseAdapter.get_persons_registry.__doc__.strip()

    def test_load_json_export_return_annotation(self) -> None:
        """load_json_export must be annotated to return int."""
        hints = DatabaseAdapter.load_json_export.__annotations__
        assert "return" in hints, "load_json_export has no return annotation"

    def test_get_known_entities_return_annotation(self) -> None:
        """get_known_entities must be annotated to return list[dict[...]]."""
        hints = DatabaseAdapter.get_known_entities.__annotations__
        assert "return" in hints

    def test_get_known_relationships_return_annotation(self) -> None:
        """get_known_relationships must be annotated."""
        hints = DatabaseAdapter.get_known_relationships.__annotations__
        assert "return" in hints

    def test_get_persons_registry_return_annotation(self) -> None:
        """get_persons_registry must be annotated."""
        hints = DatabaseAdapter.get_persons_registry.__annotations__
        assert "return" in hints

    def test_init_conn_parameter_annotated(self) -> None:
        """DatabaseAdapter.__init__ conn parameter must be type-annotated."""
        sig = inspect.signature(DatabaseAdapter.__init__)
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            assert param.annotation is not inspect.Parameter.empty, (
                f"__init__ parameter '{name}' lacks type annotation"
            )

    def test_post_mvp_stubs_have_docstrings(self) -> None:
        """Post-MVP stub methods must all have docstrings."""
        for method_name in (
            "paginated_query",
            "get_efta_range",
            "get_document_versions",
            "get_redactions_for_document",
        ):
            method = getattr(DatabaseAdapter, method_name)
            assert method.__doc__ and method.__doc__.strip(), (
                f"{method_name} is missing a docstring"
            )


# ---------------------------------------------------------------------------
# AC-8: Return types are list[dict] — not raw sqlite3.Row objects  (FR-002)
# ---------------------------------------------------------------------------


class TestReturnTypesAreListDict:
    """The get_* methods must return list[dict], not sqlite3.Row objects."""

    def test_entities_not_sqlite_rows(self, tmp_path: Path) -> None:
        """get_known_entities() must not return sqlite3.Row objects."""
        adapter = _make_adapter_with_data(tmp_path, entities=2)
        for item in adapter.get_known_entities():
            assert not isinstance(item, sqlite3.Row), "Got sqlite3.Row instead of dict"

    def test_relationships_not_sqlite_rows(self, tmp_path: Path) -> None:
        """get_known_relationships() must not return sqlite3.Row objects."""
        adapter = _make_adapter_with_data(tmp_path, rels=2)
        for item in adapter.get_known_relationships():
            assert not isinstance(item, sqlite3.Row)

    def test_persons_not_sqlite_rows(self, tmp_path: Path) -> None:
        """get_persons_registry() must not return sqlite3.Row objects."""
        adapter = _make_adapter_with_data(tmp_path, persons=2)
        for item in adapter.get_persons_registry():
            assert not isinstance(item, sqlite3.Row)

    def test_entities_dicts_are_subscriptable(self, tmp_path: Path) -> None:
        """Dict items from get_known_entities() must support key access."""
        adapter = _make_adapter_with_data(tmp_path, entities=1)
        results = adapter.get_known_entities()
        assert len(results) == 1
        # If it were a Row this would require column lookup by index.
        item = results[0]
        _ = item["name"]  # Must not raise KeyError or TypeError

    def test_persons_dicts_support_json_serialization(self, tmp_path: Path) -> None:
        """Person dicts must be JSON-serialisable (plain Python types only)."""
        adapter = _make_adapter_with_data(tmp_path, persons=3)
        results = adapter.get_persons_registry()
        # json.dumps would raise if sqlite3.Row or non-serialisable type present
        serialised = json.dumps(results)
        assert len(serialised) > 2  # non-empty JSON array


# ---------------------------------------------------------------------------
# AC: DatabaseAdapter.__init__ accepts sqlite3.Connection or a path  (Notes)
# ---------------------------------------------------------------------------


class TestDatabaseAdapterInit:
    """DatabaseAdapter must accept both a connection object and a file path."""

    def test_accepts_sqlite3_connection(self) -> None:
        """Passing a live sqlite3.Connection must not raise."""
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        assert adapter is not None

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Passing a string path to a SQLite file must work without error."""
        db_path = str(tmp_path / "test.db")
        adapter = DatabaseAdapter(db_path)
        assert adapter is not None

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        """Passing a pathlib.Path to a SQLite file must work without error."""
        db_path = tmp_path / "test.db"
        adapter = DatabaseAdapter(db_path)
        assert adapter is not None

    def test_row_factory_set_on_connection(self) -> None:
        """The adapter must set row_factory to sqlite3.Row on the connection."""
        conn = sqlite3.connect(":memory:")
        DatabaseAdapter(conn)
        assert conn.row_factory is sqlite3.Row


# ---------------------------------------------------------------------------
# Post-MVP stubs raise NotImplementedError
# ---------------------------------------------------------------------------


class TestPostMvpStubs:
    """Post-MVP stub methods must raise NotImplementedError."""

    def setup_method(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.adapter = DatabaseAdapter(conn)

    def test_paginated_query_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            self.adapter.paginated_query("SELECT 1", (), 10, 0)

    def test_get_efta_range_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            self.adapter.get_efta_range(1, 0, 100)

    def test_get_document_versions_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            self.adapter.get_document_versions("EFTA00001234")

    def test_get_redactions_for_document_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            self.adapter.get_redactions_for_document("EFTA00001234")


# ---------------------------------------------------------------------------
# Helper: _row_to_dict
# ---------------------------------------------------------------------------


class TestRowToDict:
    """Unit tests for the _row_to_dict module-level helper."""

    def _make_row(self, data: dict[str, Any]) -> sqlite3.Row:
        """Create a real sqlite3.Row from a dict using an in-memory connection."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        conn.execute(f"CREATE TABLE t ({cols})")  # noqa: S608 — test helper only
        conn.execute(f"INSERT INTO t VALUES ({placeholders})", list(data.values()))  # noqa: S608
        return conn.execute("SELECT * FROM t").fetchone()

    def test_returns_dict(self) -> None:
        """_row_to_dict must return a plain dict."""
        row = self._make_row({"name": "Alice", "raw_json": json.dumps({"name": "Alice"})})
        result = _row_to_dict(row)
        assert isinstance(result, dict)

    def test_merges_raw_json_with_scalars(self) -> None:
        """_row_to_dict must merge raw_json fields with scalar columns."""
        raw = {"name": "Alice", "extra_field": "extra_value"}
        row = self._make_row({"name": "Alice", "raw_json": json.dumps(raw)})
        result = _row_to_dict(row)
        assert result.get("extra_field") == "extra_value"

    def test_raw_json_column_removed_from_output(self) -> None:
        """raw_json key must be stripped from the returned dict."""
        row = self._make_row({"name": "Bob", "raw_json": json.dumps({"name": "Bob"})})
        result = _row_to_dict(row)
        assert "raw_json" not in result

    def test_handles_missing_raw_json(self) -> None:
        """If raw_json is absent, _row_to_dict must return scalar columns only."""
        row = self._make_row({"name": "Charlie"})
        result = _row_to_dict(row)
        assert result["name"] == "Charlie"

    def test_handles_invalid_raw_json(self) -> None:
        """_row_to_dict must not raise on malformed raw_json — returns scalars."""
        row = self._make_row({"name": "Dave", "raw_json": "NOT_VALID_JSON"})
        result = _row_to_dict(row)
        assert result["name"] == "Dave"

    def test_scalar_overrides_raw_json_for_same_key(self) -> None:
        """Scalar columns should win over raw_json for the same key when non-None."""
        raw = {"name": "OldName"}
        row = self._make_row({"name": "NewName", "raw_json": json.dumps(raw)})
        result = _row_to_dict(row)
        # The scalar 'name' is non-None and should overlay the raw_json 'name'.
        assert result["name"] == "NewName"


# ---------------------------------------------------------------------------
# Error paths — adapter with no data loaded
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Validate error paths when tables are absent."""

    def test_get_known_entities_raises_when_table_missing(self) -> None:
        """get_known_entities() must raise sqlite3.OperationalError when table absent."""
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        with pytest.raises(sqlite3.OperationalError):
            adapter.get_known_entities()

    def test_get_known_relationships_raises_when_table_missing(self) -> None:
        """get_known_relationships() must raise sqlite3.OperationalError."""
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        with pytest.raises(sqlite3.OperationalError):
            adapter.get_known_relationships()

    def test_get_persons_registry_raises_when_table_missing(self) -> None:
        """get_persons_registry() must raise sqlite3.OperationalError."""
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        with pytest.raises(sqlite3.OperationalError):
            adapter.get_persons_registry()

    def test_load_json_export_str_path(self, tmp_path: Path) -> None:
        """load_json_export must accept a str as file_path (not just Path)."""
        _write_json(tmp_path, "persons_registry.json", _minimal_persons(2))
        conn = sqlite3.connect(":memory:")
        adapter = DatabaseAdapter(conn)
        count = adapter.load_json_export(
            str(tmp_path / "persons_registry.json"), "persons"
        )
        assert count == 2
