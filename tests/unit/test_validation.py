"""Tests for US-008: Basic Validation Layer.

Covers every acceptance criterion listed in todo/US-008.md:
    AC-1  EFTA not in ingested exports → rejected, provenance error in errors list (FR-031)
    AC-2  Valid EFTA present in ingested data → passes provenance check (FR-031)
    AC-3  unit_id with existing accepted finding → rejected, references existing finding_id (FR-032)
    AC-4  SSN pattern in result → quarantined: accepted=False, pii_detected=True (EC-001)
    AC-5  US phone pattern in result → quarantined: accepted=False, pii_detected=True (EC-001)
    AC-6  Postal address pattern in result → quarantined: accepted=False, pii_detected=True (EC-001)
    AC-7  Quarantined result stored with status="quarantined", NOT "accepted" (EC-001)
    AC-8  scan_for_pii runs before any acceptance; cannot be bypassed (EC-001)
    AC-9  Clean result (valid EFTA, no dup, no PII) → accepted=True, pii_detected=False (FR-031)
    AC-10 All public methods have type annotations and docstrings (NFR-002, NFR-008)

All database operations use in-memory SQLite (:memory:).
No HTTP calls are made; all external I/O is mocked via unittest.mock.
"""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sefi.db.adapter import DatabaseAdapter
from sefi.store.findings import FindingsStore
from sefi.validation.layer import (
    PIIMatch,
    ResultSubmission,
    ValidationLayer,
    ValidationResult,
    _efta_to_int,
    _serialise_result,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_db_adapter(efta_rows: list[tuple] | None = None) -> DatabaseAdapter:
    """Return a DatabaseAdapter backed by an in-memory SQLite connection.

    Optionally pre-populates the efta_mapping table with (range_start, range_end) rows.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS efta_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            range_start INTEGER,
            range_end INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            name TEXT,
            entity_type TEXT,
            aliases TEXT,
            raw_json TEXT
        )
        """
    )
    if efta_rows:
        conn.executemany(
            "INSERT INTO efta_mapping (range_start, range_end) VALUES (?, ?)",
            efta_rows,
        )
    conn.commit()

    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter._conn = conn
    return adapter


def _make_findings_store() -> FindingsStore:
    """Return a fresh in-memory FindingsStore."""
    return FindingsStore(db_path=Path(":memory:"))


def _make_layer(
    efta_rows: list[tuple] | None = None,
    findings_store: FindingsStore | None = None,
) -> ValidationLayer:
    """Convenience factory for a ValidationLayer with in-memory dependencies."""
    adapter = _make_db_adapter(efta_rows)
    store = findings_store or _make_findings_store()
    return ValidationLayer(db_adapter=adapter, findings_store=store)


def _make_submission(
    unit_id: str = "unit-abc",
    worker_id: str = "worker-001",
    result: dict[str, Any] | None = None,
    cited_eftas: list[str] | None = None,
    unit_type: str = "verify_finding",
) -> ResultSubmission:
    """Build a minimal ResultSubmission for tests."""
    return ResultSubmission(
        unit_id=unit_id,
        worker_id=worker_id,
        result=result if result is not None else {"verdict": "supported"},
        cited_eftas=cited_eftas if cited_eftas is not None else [],
        unit_type=unit_type,
    )


def _seed_accepted_finding(store: FindingsStore, unit_id: str) -> str:
    """Insert an accepted finding row directly into the store's DB and return finding_id."""
    finding_id = f"finding-existing-{unit_id[:8]}"
    store._conn.execute(
        """
        INSERT INTO findings
            (finding_id, unit_id, unit_type, worker_id, submitted_at,
             validated_at, status, result_json, quorum_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            finding_id,
            unit_id,
            "verify_finding",
            "worker-seed",
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:00:00Z",
            "accepted",
            "{}",
            1,
        ),
    )
    store._conn.commit()
    return finding_id


# ---------------------------------------------------------------------------
# AC-1: EFTA not in ingested exports → rejected with provenance error (FR-031)
# ---------------------------------------------------------------------------


def test_unknown_efta_is_rejected():
    """AC-1: Result citing an unknown EFTA is rejected with accepted=False."""
    layer = _make_layer(efta_rows=[])  # empty DB — no EFTAs present
    sub = _make_submission(cited_eftas=["EFTA00099999"])
    result = layer.validate_result(sub)

    assert result.accepted is False


def test_unknown_efta_produces_provenance_error():
    """AC-1: Errors list contains a provenance-related message for unknown EFTA."""
    layer = _make_layer(efta_rows=[])
    sub = _make_submission(cited_eftas=["EFTA00099999"])
    result = layer.validate_result(sub)

    assert len(result.errors) >= 1
    assert any("Provenance error" in e or "EFTA00099999" in e for e in result.errors)


def test_multiple_unknown_eftas_all_reported():
    """AC-1: Each unknown EFTA gets its own provenance error entry."""
    layer = _make_layer(efta_rows=[])
    sub = _make_submission(cited_eftas=["EFTA00000001", "EFTA00000002"])
    result = layer.validate_result(sub)

    assert result.accepted is False
    assert len(result.errors) == 2


def test_unknown_efta_result_not_stored():
    """AC-1: A provenance-rejected result is not stored in the findings table."""
    store = _make_findings_store()
    adapter = _make_db_adapter(efta_rows=[])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)
    sub = _make_submission(unit_id="unit-nostore", cited_eftas=["EFTA99999999"])
    layer.validate_result(sub)

    cursor = store._conn.execute(
        "SELECT COUNT(*) FROM findings WHERE unit_id = ?", ("unit-nostore",)
    )
    assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# AC-2: Valid EFTA present in ingested data → passes provenance check (FR-031)
# ---------------------------------------------------------------------------


def test_valid_efta_in_efta_mapping_range_passes():
    """AC-2: EFTA whose numeric value falls within a mapping range passes provenance."""
    # EFTA00039186 → numeric 39186; provide a range that includes it
    layer = _make_layer(efta_rows=[(1, 100000)])
    sub = _make_submission(cited_eftas=["EFTA00039186"])
    result = layer.validate_result(sub)

    assert result.accepted is True
    assert result.pii_detected is False


def test_valid_efta_in_entities_table_passes():
    """AC-2: EFTA found in the entities table passes provenance even without efta_mapping row."""
    adapter = _make_db_adapter(efta_rows=[])  # empty efta_mapping
    # Insert EFTA directly into entities
    adapter._conn.execute(
        "INSERT INTO entities (entity_id, name, entity_type) VALUES (?, ?, ?)",
        ("EFTA00001234", "Doc 1234", "document"),
    )
    adapter._conn.commit()

    store = _make_findings_store()
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)
    sub = _make_submission(cited_eftas=["EFTA00001234"])
    result = layer.validate_result(sub)

    assert result.accepted is True


def test_no_cited_eftas_passes_provenance():
    """AC-2: Submission with empty cited_eftas passes provenance (nothing to verify)."""
    layer = _make_layer(efta_rows=[])
    sub = _make_submission(cited_eftas=[])
    result = layer.validate_result(sub)

    assert result.accepted is True


def test_verify_provenance_returns_empty_list_for_valid_efta():
    """AC-2: verify_provenance returns [] when EFTA is in range."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    errors = layer.verify_provenance(["EFTA00039186"])
    assert errors == []


def test_verify_provenance_returns_error_for_unknown_efta():
    """AC-1: verify_provenance returns non-empty list for unknown EFTA."""
    layer = _make_layer(efta_rows=[])
    errors = layer.verify_provenance(["EFTA00099999"])
    assert len(errors) == 1
    assert "EFTA00099999" in errors[0]


# ---------------------------------------------------------------------------
# AC-3: Duplicate unit_id with accepted finding → rejected, references finding_id (FR-032)
# ---------------------------------------------------------------------------


def test_duplicate_unit_id_is_rejected():
    """AC-3: Submitting a result for a unit_id with an existing accepted finding → rejected."""
    store = _make_findings_store()
    existing_id = _seed_accepted_finding(store, "unit-dup-001")

    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)
    sub = _make_submission(unit_id="unit-dup-001", cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.accepted is False


def test_duplicate_rejection_references_existing_finding_id():
    """AC-3: Error message or finding_id in ValidationResult references the existing finding."""
    store = _make_findings_store()
    existing_id = _seed_accepted_finding(store, "unit-dup-002")

    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)
    sub = _make_submission(unit_id="unit-dup-002", cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    # Either the finding_id field or the errors list must reference the existing finding_id
    references_existing = (result.finding_id == existing_id) or any(
        existing_id in e for e in result.errors
    )
    assert references_existing, (
        f"Expected reference to '{existing_id}' in result. "
        f"finding_id={result.finding_id!r}, errors={result.errors!r}"
    )


def test_check_deduplication_returns_error_for_duplicate():
    """AC-3: check_deduplication returns (error_msg, finding_id) for an existing accepted finding."""
    store = _make_findings_store()
    existing_id = _seed_accepted_finding(store, "unit-dedup-test")
    adapter = _make_db_adapter()
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    error_msg, fid = layer.check_deduplication("unit-dedup-test")
    assert error_msg is not None
    assert fid == existing_id


def test_check_deduplication_returns_none_for_new_unit():
    """AC-3: check_deduplication returns (None, None) when no accepted finding exists."""
    store = _make_findings_store()
    adapter = _make_db_adapter()
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    error_msg, fid = layer.check_deduplication("unit-brand-new")
    assert error_msg is None
    assert fid is None


def test_pending_finding_does_not_trigger_dedup():
    """AC-3: A pending (not accepted) finding for the same unit_id does not block new submissions."""
    store = _make_findings_store()
    # Insert a PENDING finding — should not trigger deduplication
    store._conn.execute(
        """
        INSERT INTO findings
            (finding_id, unit_id, unit_type, worker_id, submitted_at,
             status, result_json, quorum_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "finding-pending-001",
            "unit-pending",
            "verify_finding",
            "worker-p",
            "2025-01-01T00:00:00Z",
            "pending",
            "{}",
            1,
        ),
    )
    store._conn.commit()

    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)
    sub = _make_submission(unit_id="unit-pending", cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.accepted is True


# ---------------------------------------------------------------------------
# AC-4: SSN pattern → quarantined (EC-001)
# ---------------------------------------------------------------------------


def test_ssn_in_result_quarantines():
    """AC-4: Result containing SSN pattern is quarantined (accepted=False, pii_detected=True)."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(
        result={"note": "Worker SSN is 123-45-6789"},
        cited_eftas=["EFTA00001000"],
    )
    result = layer.validate_result(sub)

    assert result.accepted is False
    assert result.pii_detected is True


def test_ssn_in_worker_id_quarantines():
    """AC-4: SSN embedded in worker_id field is detected during PII scan."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(
        worker_id="agent-123-45-6789",
        result={"verdict": "ok"},
    )
    result = layer.validate_result(sub)

    assert result.pii_detected is True
    assert result.accepted is False


def test_scan_for_pii_detects_ssn():
    """AC-4: scan_for_pii returns a PIIMatch with pattern_name='ssn' for SSN text."""
    layer = _make_layer()
    matches = layer.scan_for_pii("Social security: 123-45-6789 is confidential")
    assert any(m.pattern_name == "ssn" for m in matches)


def test_scan_for_pii_no_match_returns_empty():
    """AC-4: scan_for_pii returns empty list for clean text."""
    layer = _make_layer()
    matches = layer.scan_for_pii("No PII here. Just a normal sentence.")
    assert matches == []


# ---------------------------------------------------------------------------
# AC-5: US phone pattern → quarantined (EC-001)
# ---------------------------------------------------------------------------


def test_phone_number_in_result_quarantines():
    """AC-5: Result containing US phone number is quarantined."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(
        result={"contact": "Call me at 555-867-5309"},
        cited_eftas=["EFTA00001000"],
    )
    result = layer.validate_result(sub)

    assert result.accepted is False
    assert result.pii_detected is True


def test_phone_number_with_country_code_quarantines():
    """AC-5: Phone number with +1 country code is quarantined."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(
        result={"note": "Reach at +1-800-555-0100"},
        cited_eftas=["EFTA00001000"],
    )
    result = layer.validate_result(sub)

    assert result.pii_detected is True


def test_scan_for_pii_detects_phone():
    """AC-5: scan_for_pii returns a PIIMatch with pattern_name='phone' for phone text."""
    layer = _make_layer()
    matches = layer.scan_for_pii("Contact: (202) 555-0172")
    assert any(m.pattern_name == "phone" for m in matches)


# ---------------------------------------------------------------------------
# AC-6: Postal address pattern → quarantined (EC-001)
# ---------------------------------------------------------------------------


def test_postal_address_in_result_quarantines():
    """AC-6: Result containing a postal address is quarantined."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(
        result={"address": "Lives at 123 Main Street"},
        cited_eftas=["EFTA00001000"],
    )
    result = layer.validate_result(sub)

    assert result.accepted is False
    assert result.pii_detected is True


def test_postal_address_avenue_quarantines():
    """AC-6: Address with 'Avenue' suffix is quarantined."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(result={"loc": "456 Oak Avenue"})
    result = layer.validate_result(sub)

    assert result.pii_detected is True


def test_postal_address_blvd_quarantines():
    """AC-6: Address with 'Blvd' suffix is quarantined."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(result={"home": "1 Sunset Blvd is historic"})
    result = layer.validate_result(sub)

    assert result.pii_detected is True


def test_scan_for_pii_detects_postal_address():
    """AC-6: scan_for_pii returns a PIIMatch for a postal address string."""
    layer = _make_layer()
    matches = layer.scan_for_pii("Meet at 42 Baker Street tomorrow")
    assert any(m.pattern_name == "postal_address" for m in matches)


# ---------------------------------------------------------------------------
# AC-7: Quarantined result stored with status="quarantined", NOT "accepted" (EC-001)
# ---------------------------------------------------------------------------


def test_pii_result_stored_as_quarantined_not_accepted():
    """AC-7: A PII-containing result is stored with status='quarantined' in findings table."""
    store = _make_findings_store()
    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    sub = _make_submission(
        result={"ssn": "999-88-7777"},
        cited_eftas=["EFTA00001000"],
    )
    vr = layer.validate_result(sub)

    assert vr.finding_id is not None, "A finding_id should be assigned for quarantined results"
    cursor = store._conn.execute(
        "SELECT status FROM findings WHERE finding_id = ?", (vr.finding_id,)
    )
    row = cursor.fetchone()
    assert row is not None, "Quarantined finding was not written to DB"
    assert row[0] == "quarantined"


def test_pii_result_not_stored_as_accepted():
    """AC-7: No row with status='accepted' is written for a quarantined result."""
    store = _make_findings_store()
    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    sub = _make_submission(result={"ssn": "111-22-3333"}, unit_id="unit-quarantine-check")
    layer.validate_result(sub)

    cursor = store._conn.execute(
        "SELECT COUNT(*) FROM findings WHERE unit_id = ? AND status = 'accepted'",
        ("unit-quarantine-check",),
    )
    assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# AC-8: PII scan runs before provenance and deduplication; cannot be bypassed (EC-001)
# ---------------------------------------------------------------------------


def test_pii_scan_runs_before_provenance_check():
    """AC-8: PII is caught even when the cited EFTA is invalid (PII takes priority)."""
    layer = _make_layer(efta_rows=[])  # no valid EFTAs
    # The EFTA is unknown, but PII should still be reported first (short-circuit)
    sub = _make_submission(
        result={"data": "SSN: 987-65-4321"},
        cited_eftas=["EFTA99999999"],  # would fail provenance
    )
    result = layer.validate_result(sub)

    # Must be flagged as PII, not just provenance error
    assert result.pii_detected is True
    assert result.accepted is False


def test_pii_scan_runs_before_deduplication_check():
    """AC-8: PII is caught even when a duplicate finding already exists."""
    store = _make_findings_store()
    _seed_accepted_finding(store, "unit-pii-dedup")
    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    sub = _make_submission(
        unit_id="unit-pii-dedup",
        result={"phone": "202-555-0100"},
        cited_eftas=["EFTA00001000"],
    )
    result = layer.validate_result(sub)

    # PII should be the reason for rejection, and pii_detected must be True
    assert result.pii_detected is True
    assert result.accepted is False


def test_pii_short_circuit_does_not_run_further_checks():
    """AC-8: When PII is detected, provenance and dedup checks are skipped.

    We verify this by using an unknown EFTA: if provenance ran after PII,
    there'd be a provenance error too. But the spec says PII short-circuits,
    so the errors list must only contain PII errors.
    """
    layer = _make_layer(efta_rows=[])  # no valid EFTAs — provenance would fail
    sub = _make_submission(
        result={"ssn": "555-44-3333"},
        cited_eftas=["EFTA99999999"],
    )
    result = layer.validate_result(sub)

    assert result.pii_detected is True
    # All errors should be PII-related only
    for err in result.errors:
        assert "PII" in err or "pattern" in err, (
            f"Expected only PII errors when short-circuiting, got: {err!r}"
        )


# ---------------------------------------------------------------------------
# AC-9: Clean result accepted (FR-031)
# ---------------------------------------------------------------------------


def test_clean_result_is_accepted():
    """AC-9: Clean result with valid EFTA, no dup, no PII → accepted=True."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.accepted is True
    assert result.pii_detected is False


def test_clean_result_pii_detected_false():
    """AC-9: pii_detected is False for a clean result."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00050000"])
    result = layer.validate_result(sub)

    assert result.pii_detected is False


def test_clean_result_errors_empty():
    """AC-9: errors list is empty for a clean result."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00050000"])
    result = layer.validate_result(sub)

    assert result.errors == []


def test_clean_result_finding_id_assigned():
    """AC-9: A clean result gets a finding_id string (not None)."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.finding_id is not None
    assert isinstance(result.finding_id, str)
    assert len(result.finding_id) > 0


def test_clean_result_quorum_status_achieved():
    """AC-9: quorum_status defaults to 'achieved' for MVP."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.quorum_status == "achieved"


def test_clean_result_stored_as_accepted():
    """AC-9: Accepted finding is persisted with status='accepted'."""
    store = _make_findings_store()
    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    sub = _make_submission(cited_eftas=["EFTA00001000"])
    vr = layer.validate_result(sub)

    cursor = store._conn.execute(
        "SELECT status FROM findings WHERE finding_id = ?", (vr.finding_id,)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "accepted"


# ---------------------------------------------------------------------------
# AC-10: All public methods have type annotations and docstrings (NFR-002, NFR-008)
# ---------------------------------------------------------------------------

_PUBLIC_API_METHODS = [
    ValidationLayer.__init__,
    ValidationLayer.validate_result,
    ValidationLayer.scan_for_pii,
    ValidationLayer.verify_provenance,
    ValidationLayer.check_deduplication,
]


@pytest.mark.parametrize("method", _PUBLIC_API_METHODS)
def test_public_method_has_docstring(method):
    """AC-10: Each public method has a non-empty docstring."""
    assert method.__doc__ and method.__doc__.strip(), (
        f"{method.__qualname__} is missing a docstring"
    )


@pytest.mark.parametrize("method", _PUBLIC_API_METHODS)
def test_public_method_has_type_annotations(method):
    """AC-10: Each public method has type annotations on all parameters and return value."""
    hints = method.__annotations__
    sig = inspect.signature(method)
    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        assert param_name in hints, (
            f"{method.__qualname__} param '{param_name}' missing type annotation"
        )
    assert "return" in hints, (
        f"{method.__qualname__} is missing a return type annotation"
    )


def test_pii_match_model_has_docstring():
    """AC-10: PIIMatch Pydantic model has a docstring."""
    assert PIIMatch.__doc__ and PIIMatch.__doc__.strip()


def test_result_submission_model_has_docstring():
    """AC-10: ResultSubmission Pydantic model has a docstring."""
    assert ResultSubmission.__doc__ and ResultSubmission.__doc__.strip()


def test_validation_result_model_has_docstring():
    """AC-10: ValidationResult Pydantic model has a docstring."""
    assert ValidationResult.__doc__ and ValidationResult.__doc__.strip()


# ---------------------------------------------------------------------------
# Additional edge cases and error paths
# ---------------------------------------------------------------------------


def test_validation_result_model_fields():
    """ValidationResult Pydantic model instantiates correctly with all fields."""
    vr = ValidationResult(
        accepted=True,
        quorum_status="achieved",
        pii_detected=False,
        errors=[],
        finding_id="finding-xyz",
    )
    assert vr.accepted is True
    assert vr.quorum_status == "achieved"
    assert vr.pii_detected is False
    assert vr.errors == []
    assert vr.finding_id == "finding-xyz"


def test_result_submission_defaults():
    """ResultSubmission has sensible defaults for optional fields."""
    sub = ResultSubmission(
        unit_id="u-1",
        worker_id="w-1",
        result={},
    )
    assert sub.cited_eftas == []
    assert sub.unit_type == "unknown"


def test_efta_to_int_valid():
    """_efta_to_int correctly parses EFTA00039186 → 39186."""
    assert _efta_to_int("EFTA00039186") == 39186


def test_efta_to_int_returns_none_for_invalid():
    """_efta_to_int returns None for non-EFTA strings."""
    assert _efta_to_int("NOTANEFTA") is None
    assert _efta_to_int("") is None
    assert _efta_to_int("EFTA-bad") is None


def test_efta_to_int_case_insensitive():
    """_efta_to_int is case-insensitive for the 'EFTA' prefix."""
    assert _efta_to_int("efta00039186") == 39186


def test_serialise_result_includes_all_fields():
    """_serialise_result JSON contains unit_id, worker_id, result, and cited_eftas."""
    import json

    sub = _make_submission(
        unit_id="unit-ser",
        worker_id="worker-ser",
        result={"key": "val"},
        cited_eftas=["EFTA00001234"],
    )
    text = _serialise_result(sub)
    parsed = json.loads(text)
    assert "unit-ser" in text
    assert "worker-ser" in text
    assert "EFTA00001234" in text


def test_scan_for_pii_returns_pii_match_objects():
    """scan_for_pii returns PIIMatch instances with pattern_name and matched_text."""
    layer = _make_layer()
    matches = layer.scan_for_pii("SSN: 123-45-6789")
    assert len(matches) >= 1
    m = matches[0]
    assert isinstance(m, PIIMatch)
    assert m.pattern_name == "ssn"
    assert "123-45-6789" in m.matched_text


def test_multiple_pii_types_all_detected():
    """scan_for_pii detects multiple PII categories in a single text block."""
    layer = _make_layer()
    text = "SSN 123-45-6789 and phone 555-867-5309 and addr 1 Oak Street nearby"
    matches = layer.scan_for_pii(text)
    pattern_names = {m.pattern_name for m in matches}
    assert "ssn" in pattern_names
    assert "phone" in pattern_names
    assert "postal_address" in pattern_names


def test_provenance_check_does_not_reject_empty_efta_list():
    """verify_provenance returns empty errors when cited_eftas is an empty list."""
    layer = _make_layer(efta_rows=[])
    errors = layer.verify_provenance([])
    assert errors == []


def test_pii_quarantine_result_finding_id_not_none():
    """Quarantined result has a non-None finding_id (the stored row's ID)."""
    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(result={"x": "phone: 800-555-0199"})
    result = layer.validate_result(sub)

    assert result.pii_detected is True
    assert result.finding_id is not None


def test_dedup_finding_id_field_points_to_existing():
    """Dedup rejection sets finding_id to the existing accepted finding's ID."""
    store = _make_findings_store()
    existing_id = _seed_accepted_finding(store, "unit-dedup-fid")
    adapter = _make_db_adapter(efta_rows=[(1, 999999)])
    layer = ValidationLayer(db_adapter=adapter, findings_store=store)

    sub = _make_submission(unit_id="unit-dedup-fid", cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)

    assert result.finding_id == existing_id


def test_clean_result_no_http_calls_made(monkeypatch):
    """Validate that no HTTP calls occur during normal validation (no network I/O)."""
    # Patch urllib to ensure no network access happens
    import urllib.request

    def _no_http(*args, **kwargs):
        raise AssertionError("HTTP call was made during validation — not allowed!")

    monkeypatch.setattr(urllib.request, "urlopen", _no_http)

    layer = _make_layer(efta_rows=[(1, 999999)])
    sub = _make_submission(cited_eftas=["EFTA00001000"])
    result = layer.validate_result(sub)
    assert result.accepted is True
