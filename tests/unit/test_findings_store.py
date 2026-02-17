"""Tests for US-007: FindingsStore, Finding, Citation, and CoverageStats.

Covers every acceptance criterion listed in todo/US-007.md:
    AC-1  findings and citations tables created with correct schema (FR-038, DR-007, DR-008)
    AC-2  idx_findings_unit_type and idx_findings_status indexes created on init (DR-010)
    AC-3  idx_citations_efta index created on citations on init (DR-008)
    AC-4  store_finding persists a finding retrievable after simulated restart (FR-038)
    AC-5  get_findings_for_document returns exactly 3 when 3 citing findings exist (FR-039)
    AC-6  get_findings_for_document returns empty list when none exist (FR-039)
    AC-7  export_findings("json", {}) returns valid JSON bytes parseable as list (FR-040)
    AC-8  export_findings("csv", {}) returns valid UTF-8 CSV bytes with header + data rows (FR-040)
    AC-9  JSON export includes top-level "license": "CC0-1.0" field (EC-004)
    AC-10 get_coverage("verify_finding") returns CoverageStats with valid fields (FR-041)
    AC-11 status values constrained to allowed set (DR-007)
    AC-12 Invalid efta_number raises ValueError before insert (DR-011)
    AC-13 All SQL uses parameterized ? placeholders (NFR-004)
    AC-14 All methods include type annotations and docstrings (NFR-002, NFR-008)

All HTTP calls would be mocked if needed — none occur in FindingsStore.
All database operations use in-memory SQLite (:memory:).
"""
from __future__ import annotations

import csv
import inspect
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sefi.store.findings import (
    Citation,
    CoverageStats,
    Finding,
    FindingsStore,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_store() -> FindingsStore:
    """Return a fresh in-memory FindingsStore."""
    return FindingsStore(db_path=Path(":memory:"))


def _make_finding(
    finding_id: str = "finding-abc123",
    unit_id: str = "verify-aabbccdd1122",
    unit_type: str = "verify_finding",
    worker_id: str = "worker-001",
    submitted_at: str = "2025-01-01T00:00:00Z",
    validated_at: str | None = None,
    status: str = "pending",
    result_json: str = '{"verdict": "supported"}',
    quorum_count: int = 1,
    citations: list[Citation] | None = None,
) -> Finding:
    """Construct a valid Finding for tests."""
    return Finding(
        finding_id=finding_id,
        unit_id=unit_id,
        unit_type=unit_type,
        worker_id=worker_id,
        submitted_at=submitted_at,
        validated_at=validated_at,
        status=status,
        result_json=result_json,
        quorum_count=quorum_count,
        citations=citations or [],
    )


def _make_citation(
    citation_id: str = "cit-001",
    finding_id: str = "finding-abc123",
    efta_number: str = "EFTA00039186",
    page_number: int | None = None,
    quote: str | None = None,
) -> Citation:
    """Construct a valid Citation for tests."""
    return Citation(
        citation_id=citation_id,
        finding_id=finding_id,
        efta_number=efta_number,
        page_number=page_number,
        quote=quote,
    )


def _get_sqlite_indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of index names for the given table from the SQLite master table."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _get_table_names(conn: sqlite3.Connection) -> set[str]:
    """Return all table names present in the database."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# AC-1: findings and citations tables created with correct schema (FR-038, DR-007, DR-008)
# ---------------------------------------------------------------------------


def test_schema_creates_findings_table():
    """AC-1: __init__ creates the findings table."""
    store = _make_store()
    tables = _get_table_names(store._conn)
    assert "findings" in tables


def test_schema_creates_citations_table():
    """AC-1: __init__ creates the citations table."""
    store = _make_store()
    tables = _get_table_names(store._conn)
    assert "citations" in tables


def test_findings_table_has_required_columns():
    """AC-1: findings table has all required columns from DR-007."""
    store = _make_store()
    cur = store._conn.cursor()
    cur.execute("PRAGMA table_info(findings)")
    cols = {row[1] for row in cur.fetchall()}
    required = {
        "finding_id",
        "unit_id",
        "unit_type",
        "worker_id",
        "submitted_at",
        "validated_at",
        "status",
        "result_json",
        "quorum_count",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


def test_citations_table_has_required_columns():
    """AC-1: citations table has all required columns from DR-008."""
    store = _make_store()
    cur = store._conn.cursor()
    cur.execute("PRAGMA table_info(citations)")
    cols = {row[1] for row in cur.fetchall()}
    required = {"citation_id", "finding_id", "efta_number", "page_number", "quote"}
    assert required.issubset(cols), f"Missing columns: {required - cols}"


def test_findings_status_check_constraint_rejects_invalid():
    """AC-1: status CHECK constraint prevents invalid values at the SQL level."""
    store = _make_store()
    # Enable FK/CHECK enforcement for this test
    store._conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            """
            INSERT INTO findings
                (finding_id, unit_id, unit_type, worker_id, submitted_at,
                 status, result_json, quorum_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("f-bad", "u-1", "verify_finding", "w-1", "2025-01-01", "INVALID", "{}", 1),
        )
        store._conn.commit()


# ---------------------------------------------------------------------------
# AC-2: idx_findings_unit_type and idx_findings_status indexes created (DR-010)
# ---------------------------------------------------------------------------


def test_idx_findings_unit_type_exists():
    """AC-2: idx_findings_unit_type index is created on findings table."""
    store = _make_store()
    indexes = _get_sqlite_indexes(store._conn, "findings")
    assert "idx_findings_unit_type" in indexes


def test_idx_findings_status_exists():
    """AC-2: idx_findings_status index is created on findings table."""
    store = _make_store()
    indexes = _get_sqlite_indexes(store._conn, "findings")
    assert "idx_findings_status" in indexes


# ---------------------------------------------------------------------------
# AC-3: idx_citations_efta index created on citations (DR-008)
# ---------------------------------------------------------------------------


def test_idx_citations_efta_exists():
    """AC-3: idx_citations_efta index is created on citations table."""
    store = _make_store()
    indexes = _get_sqlite_indexes(store._conn, "citations")
    assert "idx_citations_efta" in indexes


# ---------------------------------------------------------------------------
# AC-4: store_finding persists a finding retrievable across restart (FR-038)
# ---------------------------------------------------------------------------


def test_store_finding_returns_finding_id():
    """AC-4: store_finding returns the finding_id string."""
    store = _make_store()
    finding = _make_finding()
    result = store.store_finding(finding)
    assert result == finding.finding_id


def test_store_finding_persists_all_fields(tmp_path):
    """AC-4: After store_finding, all fields are intact on reload (simulated restart)."""
    db_file = tmp_path / "findings.db"
    store1 = FindingsStore(db_path=db_file)
    finding = _make_finding(
        finding_id="finding-persist",
        unit_id="verify-unit001",
        unit_type="verify_finding",
        worker_id="worker-42",
        submitted_at="2025-06-15T10:00:00Z",
        validated_at="2025-06-15T11:00:00Z",
        status="accepted",
        result_json='{"verdict": "supported"}',
        quorum_count=3,
    )
    store1.store_finding(finding)
    del store1

    # Simulated restart: open a new store pointing at the same file
    store2 = FindingsStore(db_path=db_file)
    cur = store2._conn.cursor()
    cur.execute(
        "SELECT * FROM findings WHERE finding_id = ?",
        (finding.finding_id,),
    )
    row = dict(cur.fetchone())

    assert row["finding_id"] == "finding-persist"
    assert row["unit_id"] == "verify-unit001"
    assert row["unit_type"] == "verify_finding"
    assert row["worker_id"] == "worker-42"
    assert row["submitted_at"] == "2025-06-15T10:00:00Z"
    assert row["validated_at"] == "2025-06-15T11:00:00Z"
    assert row["status"] == "accepted"
    assert row["result_json"] == '{"verdict": "supported"}'
    assert row["quorum_count"] == 3


def test_store_finding_idempotent():
    """AC-4: Calling store_finding twice with the same finding_id is idempotent."""
    store = _make_store()
    finding = _make_finding()
    id1 = store.store_finding(finding)
    id2 = store.store_finding(finding)  # Should not raise
    assert id1 == id2 == finding.finding_id

    # Only one row should exist
    cur = store._conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM findings WHERE finding_id = ?",
        (finding.finding_id,),
    )
    assert cur.fetchone()[0] == 1


def test_store_finding_with_citations_persists_citations():
    """AC-4: Citations attached to a finding are also persisted."""
    store = _make_store()
    citation = _make_citation(
        citation_id="cit-xyz",
        finding_id="finding-with-cits",
        efta_number="EFTA00001234",
        page_number=7,
        quote="Some quote here",
    )
    finding = _make_finding(
        finding_id="finding-with-cits",
        citations=[citation],
    )
    store.store_finding(finding)

    cur = store._conn.cursor()
    cur.execute(
        "SELECT * FROM citations WHERE citation_id = ?",
        ("cit-xyz",),
    )
    row = dict(cur.fetchone())
    assert row["citation_id"] == "cit-xyz"
    assert row["finding_id"] == "finding-with-cits"
    assert row["efta_number"] == "EFTA00001234"
    assert row["page_number"] == 7
    assert row["quote"] == "Some quote here"


# ---------------------------------------------------------------------------
# AC-5 & AC-6: get_findings_for_document (FR-039)
# ---------------------------------------------------------------------------


def test_get_findings_for_document_returns_three_when_three_citing():
    """AC-5: Returns exactly 3 findings when 3 findings cite the same EFTA."""
    store = _make_store()
    efta = "EFTA00039186"

    for i in range(3):
        citation = _make_citation(
            citation_id=f"cit-{i}",
            finding_id=f"finding-{i:03d}",
            efta_number=efta,
        )
        finding = _make_finding(
            finding_id=f"finding-{i:03d}",
            worker_id=f"worker-{i}",
            citations=[citation],
        )
        store.store_finding(finding)

    results = store.get_findings_for_document(efta)
    assert len(results) == 3


def test_get_findings_for_document_returns_empty_when_none():
    """AC-6: Returns an empty list when no findings cite the given EFTA."""
    store = _make_store()
    results = store.get_findings_for_document("EFTA00099999")
    assert results == []


def test_get_findings_for_document_returns_finding_objects():
    """AC-5: Return values are Finding instances with citations attached."""
    store = _make_store()
    efta = "EFTA00012345"
    citation = _make_citation(
        citation_id="cit-A",
        finding_id="finding-A",
        efta_number=efta,
    )
    finding = _make_finding(finding_id="finding-A", citations=[citation])
    store.store_finding(finding)

    results = store.get_findings_for_document(efta)
    assert len(results) == 1
    assert isinstance(results[0], Finding)
    assert results[0].finding_id == "finding-A"
    assert len(results[0].citations) == 1
    assert results[0].citations[0].efta_number == efta


def test_get_findings_for_document_rejects_invalid_efta():
    """AC-6 / DR-011: Invalid efta_number raises ValueError."""
    store = _make_store()
    with pytest.raises(ValueError, match="EFTA"):
        store.get_findings_for_document("NOT_AN_EFTA")


def test_get_findings_for_document_does_not_return_other_efta_findings():
    """AC-5: Only findings citing the queried EFTA are returned."""
    store = _make_store()

    cit_a = _make_citation(citation_id="cit-A", finding_id="finding-A", efta_number="EFTA00000001")
    cit_b = _make_citation(citation_id="cit-B", finding_id="finding-B", efta_number="EFTA00000002")
    store.store_finding(_make_finding(finding_id="finding-A", citations=[cit_a]))
    store.store_finding(_make_finding(finding_id="finding-B", citations=[cit_b]))

    results = store.get_findings_for_document("EFTA00000001")
    assert len(results) == 1
    assert results[0].finding_id == "finding-A"


# ---------------------------------------------------------------------------
# AC-7: export_findings("json", {}) returns valid JSON bytes (FR-040)
# ---------------------------------------------------------------------------


def test_export_json_returns_bytes():
    """AC-7: export_findings('json', {}) returns bytes."""
    store = _make_store()
    result = store.export_findings("json", {})
    assert isinstance(result, bytes)


def test_export_json_is_parseable():
    """AC-7: JSON bytes are parseable into a dict with 'findings' list."""
    store = _make_store()
    store.store_finding(_make_finding(finding_id="f-json-1"))
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert "findings" in parsed
    assert isinstance(parsed["findings"], list)
    assert len(parsed["findings"]) == 1


def test_export_json_includes_all_findings():
    """AC-7: JSON export includes all stored findings when no filters applied."""
    store = _make_store()
    for i in range(5):
        store.store_finding(_make_finding(finding_id=f"f-{i}", worker_id=f"w-{i}"))
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert len(parsed["findings"]) == 5


def test_export_json_empty_store_returns_empty_list():
    """AC-7: JSON export on an empty store returns empty findings list."""
    store = _make_store()
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert parsed["findings"] == []


# ---------------------------------------------------------------------------
# AC-8: export_findings("csv", {}) returns valid UTF-8 CSV bytes (FR-040)
# ---------------------------------------------------------------------------


def test_export_csv_returns_bytes():
    """AC-8: export_findings('csv', {}) returns bytes."""
    store = _make_store()
    result = store.export_findings("csv", {})
    assert isinstance(result, bytes)


def test_export_csv_is_valid_utf8():
    """AC-8: CSV bytes decode as UTF-8."""
    store = _make_store()
    result = store.export_findings("csv", {})
    decoded = result.decode("utf-8")
    assert isinstance(decoded, str)


def test_export_csv_has_header_row():
    """AC-8: CSV output starts with a header row."""
    store = _make_store()
    result = store.export_findings("csv", {})
    decoded = result.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    # Reading fieldnames triggers header parsing
    assert reader.fieldnames is not None
    assert len(reader.fieldnames) > 0


def test_export_csv_has_one_data_row_per_finding():
    """AC-8: CSV output has one data row per stored finding."""
    store = _make_store()
    for i in range(3):
        store.store_finding(_make_finding(finding_id=f"f-csv-{i}", worker_id=f"w-{i}"))
    result = store.export_findings("csv", {})
    decoded = result.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)
    assert len(rows) == 3


def test_export_csv_header_contains_expected_columns():
    """AC-8: CSV header contains finding_id, unit_id, status, etc."""
    store = _make_store()
    result = store.export_findings("csv", {})
    decoded = result.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    fieldnames = set(reader.fieldnames or [])
    required_cols = {"finding_id", "unit_id", "unit_type", "worker_id", "status"}
    assert required_cols.issubset(fieldnames), f"Missing CSV columns: {required_cols - fieldnames}"


def test_export_csv_empty_store_has_only_header():
    """AC-8: CSV export on empty store has a header but zero data rows."""
    store = _make_store()
    result = store.export_findings("csv", {})
    decoded = result.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)
    assert rows == []


# ---------------------------------------------------------------------------
# AC-9: JSON export includes top-level "license": "CC0-1.0" (EC-004)
# ---------------------------------------------------------------------------


def test_export_json_includes_cc0_license_field():
    """AC-9: JSON export top-level object has 'license': 'CC0-1.0'."""
    store = _make_store()
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert "license" in parsed
    assert parsed["license"] == "CC0-1.0"


def test_export_json_license_present_even_when_empty():
    """AC-9: License field present even when findings list is empty."""
    store = _make_store()
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert parsed["license"] == "CC0-1.0"
    assert parsed["findings"] == []


# ---------------------------------------------------------------------------
# AC-10: get_coverage returns CoverageStats with valid fields (FR-041)
# ---------------------------------------------------------------------------


def test_get_coverage_returns_coverage_stats_instance():
    """AC-10: get_coverage returns a CoverageStats instance."""
    store = _make_store()
    result = store.get_coverage("verify_finding")
    assert isinstance(result, CoverageStats)


def test_get_coverage_empty_store():
    """AC-10: get_coverage on empty store returns zeros and 0.0 percent."""
    store = _make_store()
    stats = store.get_coverage("verify_finding")
    assert stats.units_total == 0
    assert stats.units_completed == 0
    assert stats.percent == 0.0


def test_get_coverage_units_total_counts_all_statuses():
    """AC-10: units_total counts all findings regardless of status."""
    store = _make_store()
    statuses = ["pending", "accepted", "disputed", "quarantined"]
    for i, status in enumerate(statuses):
        store.store_finding(_make_finding(
            finding_id=f"f-cov-{i}",
            unit_type="verify_finding",
            worker_id=f"w-{i}",
            status=status,
        ))
    stats = store.get_coverage("verify_finding")
    assert stats.units_total == 4
    assert stats.unit_type == "verify_finding"


def test_get_coverage_units_completed_counts_only_accepted():
    """AC-10: units_completed counts only accepted findings."""
    store = _make_store()
    for i in range(3):
        store.store_finding(_make_finding(
            finding_id=f"f-acc-{i}",
            worker_id=f"w-{i}",
            status="accepted",
        ))
    for i in range(2):
        store.store_finding(_make_finding(
            finding_id=f"f-pend-{i}",
            worker_id=f"w-p-{i}",
            status="pending",
        ))
    stats = store.get_coverage("verify_finding")
    assert stats.units_completed == 3
    assert stats.units_total == 5


def test_get_coverage_percent_is_correct():
    """AC-10: percent is (units_completed / units_total) * 100."""
    store = _make_store()
    # 1 accepted out of 4 total = 25.0%
    store.store_finding(_make_finding(finding_id="f-a", worker_id="w-a", status="accepted"))
    for i in range(3):
        store.store_finding(_make_finding(
            finding_id=f"f-p-{i}",
            worker_id=f"w-p-{i}",
            status="pending",
        ))
    stats = store.get_coverage("verify_finding")
    assert stats.percent == 25.0


def test_get_coverage_percent_range():
    """AC-10: percent is between 0.0 and 100.0."""
    store = _make_store()
    store.store_finding(_make_finding(finding_id="f-p", worker_id="w-1", status="pending"))
    store.store_finding(_make_finding(finding_id="f-a", worker_id="w-2", status="accepted"))
    stats = store.get_coverage("verify_finding")
    assert 0.0 <= stats.percent <= 100.0


def test_get_coverage_different_unit_type_isolated():
    """AC-10: Coverage query is scoped to the given unit_type only."""
    store = _make_store()
    store.store_finding(_make_finding(
        finding_id="f-vf", unit_type="verify_finding", worker_id="w-1", status="accepted"
    ))
    store.store_finding(_make_finding(
        finding_id="f-dc", unit_type="decision_chain", worker_id="w-2", status="accepted"
    ))
    stats_vf = store.get_coverage("verify_finding")
    stats_dc = store.get_coverage("decision_chain")
    assert stats_vf.units_total == 1
    assert stats_dc.units_total == 1


# ---------------------------------------------------------------------------
# AC-11: status constrained to allowed values (DR-007)
# ---------------------------------------------------------------------------


def test_finding_valid_status_pending():
    """AC-11: 'pending' is a valid status."""
    f = _make_finding(status="pending")
    assert f.status == "pending"


def test_finding_valid_status_accepted():
    """AC-11: 'accepted' is a valid status."""
    f = _make_finding(status="accepted")
    assert f.status == "accepted"


def test_finding_valid_status_disputed():
    """AC-11: 'disputed' is a valid status."""
    f = _make_finding(status="disputed")
    assert f.status == "disputed"


def test_finding_valid_status_quarantined():
    """AC-11: 'quarantined' is a valid status."""
    f = _make_finding(status="quarantined")
    assert f.status == "quarantined"


def test_finding_invalid_status_raises():
    """AC-11: Invalid status raises ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="status"):
        Finding(
            finding_id="f-bad",
            unit_id="u-1",
            unit_type="verify_finding",
            worker_id="w-1",
            submitted_at="2025-01-01T00:00:00Z",
            status="unknown_status",
            result_json="{}",
        )


# ---------------------------------------------------------------------------
# AC-12: Invalid efta_number raises ValueError (DR-011)
# ---------------------------------------------------------------------------


def test_citation_valid_efta_number():
    """AC-12: Valid EFTA number passes Citation validation."""
    cit = _make_citation(efta_number="EFTA00039186")
    assert cit.efta_number == "EFTA00039186"


def test_citation_invalid_efta_number_raises():
    """AC-12: Citation with invalid efta_number raises ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="efta_number"):
        Citation(
            citation_id="c-bad",
            finding_id="f-1",
            efta_number="BADFORMAT",
        )


def test_citation_efta_too_short_raises():
    """AC-12: EFTA number with fewer than 8 digits raises ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Citation(
            citation_id="c-short",
            finding_id="f-1",
            efta_number="EFTA001",  # only 3 digits
        )


def test_citation_efta_wrong_prefix_raises():
    """AC-12: EFTA number with wrong prefix raises ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Citation(
            citation_id="c-prefix",
            finding_id="f-1",
            efta_number="efta00039186",  # lowercase prefix
        )


def test_store_finding_with_invalid_efta_raises_before_insert():
    """AC-12: store_finding raises ValueError for invalid efta_number before any DB write."""
    store = _make_store()
    # Bypass Pydantic validation to simulate a directly-constructed invalid Citation
    import re
    # We need to construct a Citation that has an invalid efta_number —
    # since Pydantic blocks this at model level, we test the store-level guard
    # by monkey-patching the pattern check directly.
    finding = _make_finding(finding_id="f-inv-efta")
    # Manually build a Citation bypassing Pydantic
    bad_citation = Citation.model_construct(
        citation_id="cit-bad",
        finding_id="f-inv-efta",
        efta_number="BAD_FORMAT",
        page_number=None,
        quote=None,
    )
    finding_with_bad_cit = finding.model_copy(update={"citations": [bad_citation]})
    with pytest.raises(ValueError, match="Invalid efta_number"):
        store.store_finding(finding_with_bad_cit)

    # Confirm nothing was written to the database
    cur = store._conn.cursor()
    cur.execute("SELECT COUNT(*) FROM findings WHERE finding_id = ?", ("f-inv-efta",))
    assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# AC-13: SQL uses parameterized ? placeholders (NFR-004)
# ---------------------------------------------------------------------------


def test_no_sql_string_interpolation_in_store_finding():
    """AC-13: store_finding source uses no f-string SQL injection patterns."""
    import inspect as _inspect
    source = _inspect.getsource(FindingsStore.store_finding)
    # f-strings used in SQL context would look like f"... {var} ..."
    # The only f-string allowed in query_findings is with allow-listed column names
    # which has an explicit # noqa comment. store_finding must not have any.
    # We check that no raw variable is interpolated into an INSERT statement.
    assert "f\"" not in source.split("INSERT")[1] if "INSERT" in source else True


def test_query_findings_uses_parameterized_placeholders():
    """AC-13: _query_findings builds safe parameterized queries."""
    store = _make_store()
    # Insert a finding with status=accepted, then filter by it
    store.store_finding(_make_finding(finding_id="f-param", status="accepted"))
    # If parameterization were broken, a SQL injection would fail or mismatch
    rows = store._query_findings({"status": "accepted"})
    assert len(rows) == 1
    assert rows[0]["finding_id"] == "f-param"


def test_query_findings_ignores_unknown_filter_keys():
    """AC-13: Unknown filter keys are silently ignored (not interpolated)."""
    store = _make_store()
    store.store_finding(_make_finding(finding_id="f-unk"))
    # Should not raise even with an unknown key; SQL injection attempt is blocked
    rows = store._query_findings({"unknown_key": "value'; DROP TABLE findings; --"})
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# AC-14: All public methods have type annotations and docstrings (NFR-002, NFR-008)
# ---------------------------------------------------------------------------


_PUBLIC_METHODS = [
    FindingsStore.__init__,
    FindingsStore.store_finding,
    FindingsStore.get_findings_for_document,
    FindingsStore.export_findings,
    FindingsStore.get_coverage,
]


@pytest.mark.parametrize("method", _PUBLIC_METHODS)
def test_public_method_has_docstring(method):
    """AC-14: Each public method has a non-empty docstring."""
    assert method.__doc__ and method.__doc__.strip(), (
        f"{method.__qualname__} is missing a docstring"
    )


@pytest.mark.parametrize("method", _PUBLIC_METHODS)
def test_public_method_has_type_annotations(method):
    """AC-14: Each public method has type annotations on all parameters."""
    hints = method.__annotations__
    sig = inspect.signature(method)
    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        assert param_name in hints, (
            f"{method.__qualname__} param '{param_name}' is missing a type annotation"
        )
    assert "return" in hints, (
        f"{method.__qualname__} is missing a return type annotation"
    )


def test_finding_model_has_docstring():
    """AC-14: Finding Pydantic model has a docstring."""
    assert Finding.__doc__ and Finding.__doc__.strip()


def test_citation_model_has_docstring():
    """AC-14: Citation Pydantic model has a docstring."""
    assert Citation.__doc__ and Citation.__doc__.strip()


def test_coverage_stats_model_has_docstring():
    """AC-14: CoverageStats Pydantic model has a docstring."""
    assert CoverageStats.__doc__ and CoverageStats.__doc__.strip()


# ---------------------------------------------------------------------------
# Additional edge cases and error paths
# ---------------------------------------------------------------------------


def test_export_findings_raises_on_invalid_format():
    """export_findings raises ValueError for unsupported format."""
    store = _make_store()
    with pytest.raises(ValueError, match="Unsupported export format"):
        store.export_findings("xml", {})


def test_export_findings_with_status_filter():
    """export_findings filters by status when filter is provided."""
    store = _make_store()
    store.store_finding(_make_finding(finding_id="f-acc", status="accepted"))
    store.store_finding(_make_finding(finding_id="f-pend", worker_id="w-2", status="pending"))
    result = store.export_findings("json", {"status": "accepted"})
    parsed = json.loads(result.decode("utf-8"))
    assert len(parsed["findings"]) == 1
    assert parsed["findings"][0]["finding_id"] == "f-acc"


def test_store_multiple_findings_and_retrieve_all():
    """Multiple findings can be stored and all appear in export."""
    store = _make_store()
    for i in range(10):
        store.store_finding(_make_finding(finding_id=f"f-{i:03d}", worker_id=f"w-{i}"))
    result = store.export_findings("json", {})
    parsed = json.loads(result.decode("utf-8"))
    assert len(parsed["findings"]) == 10


def test_finding_empty_finding_id_raises():
    """Finding rejects empty finding_id."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Finding(
            finding_id="",
            unit_id="u-1",
            unit_type="verify_finding",
            worker_id="w-1",
            submitted_at="2025-01-01T00:00:00Z",
            result_json="{}",
        )


def test_finding_whitespace_only_worker_id_raises():
    """Finding rejects whitespace-only worker_id."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Finding(
            finding_id="f-1",
            unit_id="u-1",
            unit_type="verify_finding",
            worker_id="   ",
            submitted_at="2025-01-01T00:00:00Z",
            result_json="{}",
        )


def test_citation_optional_fields_default_to_none():
    """Citation page_number and quote default to None."""
    cit = Citation(
        citation_id="cit-min",
        finding_id="f-1",
        efta_number="EFTA00000001",
    )
    assert cit.page_number is None
    assert cit.quote is None


def test_finding_default_status_is_pending():
    """Finding default status is 'pending'."""
    f = Finding(
        finding_id="f-default",
        unit_id="u-1",
        unit_type="verify_finding",
        worker_id="w-1",
        submitted_at="2025-01-01T00:00:00Z",
        result_json="{}",
    )
    assert f.status == "pending"


def test_finding_default_quorum_count_is_one():
    """Finding default quorum_count is 1."""
    f = Finding(
        finding_id="f-q",
        unit_id="u-1",
        unit_type="verify_finding",
        worker_id="w-1",
        submitted_at="2025-01-01T00:00:00Z",
        result_json="{}",
    )
    assert f.quorum_count == 1


def test_schema_idempotent_second_init(tmp_path):
    """Calling FindingsStore twice on the same file does not raise (IF NOT EXISTS)."""
    db_file = tmp_path / "idempotent.db"
    store1 = FindingsStore(db_path=db_file)
    store1._conn.close()
    # Second init should not raise even though tables/indexes already exist
    store2 = FindingsStore(db_path=db_file)
    assert store2 is not None


def test_store_and_retrieve_finding_with_no_citations():
    """store_finding works for a finding with no citations."""
    store = _make_store()
    finding = _make_finding(finding_id="f-no-cits", citations=[])
    store.store_finding(finding)

    cur = store._conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM citations WHERE finding_id = ?",
        ("f-no-cits",),
    )
    assert cur.fetchone()[0] == 0


def test_coverage_stats_model_fields():
    """CoverageStats Pydantic model exposes unit_type, units_completed, units_total, percent."""
    stats = CoverageStats(
        unit_type="verify_finding",
        units_completed=5,
        units_total=10,
        percent=50.0,
    )
    assert stats.unit_type == "verify_finding"
    assert stats.units_completed == 5
    assert stats.units_total == 10
    assert stats.percent == 50.0
