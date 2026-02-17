"""API contract tests for US-009: Distribution API (GET /work, POST /result,
GET /status, GET /health).

All HTTP calls are mocked; no live requests to justice.gov or any external URL
are made.  Database operations use in-memory SQLite (:memory:).

Coverage map
------------
- AC-001 : GET /work returns WorkUnitResponse when unit available
- AC-001 : GET /work returns {"available": false} when no units available
- AC-003 : POST /result valid body → 200 with required fields
- FR-024 : POST /result invalid body → 422
- idempotency: duplicate unit_id returns existing finding_id
- FR-025/AC-004 : GET /status → 200 with all required fields, non-negative ints
- AC-004 ordering: total_units_completed <= total_units_assigned <= total_units_generated
- FR-026/AC-005 : GET /health → 200 with status/version/findings_db_reachable
- AC-005 : GET /health returns 200 even when findings_db is unreachable
- NFR-003 : all models are Pydantic BaseModel subclasses
- NFR-002/NFR-008 : POST /result unit_id not found → 404
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sefi.api.main import create_app
from sefi.api.models import (
    AcceptanceResponse,
    HealthResponse,
    ResultSubmission,
    StatusResponse,
    WorkUnitConstraints,
    WorkUnitInput,
    WorkUnitResponse,
)
from sefi.generator.units import NoAvailableUnitsError, WorkUnit, WorkUnitGenerator
from sefi.store.findings import FindingsStore
from sefi.validation.layer import ValidationLayer, ValidationResult


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

_DOJ_PREFIX = "https://www.justice.gov/epstein/files/DataSet%20"
_FAKE_DEADLINE = "2099-01-01T00:00:00+00:00"
_DE_ANON = "Do not attempt to infer or recover redacted content. Analyze patterns only."


def _make_verify_unit(unit_id: str = "verify-abc123456789") -> WorkUnit:
    """Build a minimal valid verify_finding WorkUnit for test use."""
    return WorkUnit(
        unit_id=unit_id,
        type="verify_finding",
        path=5,
        difficulty="low",
        scaling="linear",
        optimal_batch="1 claim",
        input={
            "claim": "Test claim about Epstein.",
            "cited_eftas": ["EFTA00039186"],
            "efta_urls": [f"{_DOJ_PREFIX}9/EFTA00039186.pdf"],
            "source_verified": False,
        },
        instructions=f"Review the claim. {_DE_ANON}",
        constraints={"max_output_tokens": 2000, "pii_filter": True, "requires_quorum": False},
        deadline=_FAKE_DEADLINE,
        source_verified=False,
    )


def _make_memory_store() -> FindingsStore:
    """Create an in-memory FindingsStore for testing."""
    return FindingsStore(db_path=Path(":memory:"))


def _make_mock_generator(unit: WorkUnit | None = None, *, raises: bool = False) -> MagicMock:
    """Return a mock WorkUnitGenerator.

    If *unit* is provided it will be returned by generate_unit().
    If *raises* is True, generate_unit() raises NoAvailableUnitsError.
    """
    gen = MagicMock(spec=WorkUnitGenerator)
    if raises:
        gen.generate_unit.side_effect = NoAvailableUnitsError("no units")
    elif unit is not None:
        gen.generate_unit.return_value = unit
    # Default: returns a unit each time
    gen._assignments = {}
    gen._unit_to_claim = {}
    gen._unit_to_doc_keys = {}
    gen.get_status.return_value = {
        "total_generated": 0,
        "total_assigned": 0,
        "total_completed": 0,
    }
    return gen


def _make_mock_validation_layer(
    *,
    accepted: bool = True,
    pii_detected: bool = False,
    finding_id: str = "finding-test000001",
    errors: list[str] | None = None,
    existing_id: str | None = None,
) -> MagicMock:
    """Return a mock ValidationLayer."""
    vl = MagicMock(spec=ValidationLayer)
    vl.check_deduplication.return_value = (None, existing_id)
    vl.validate_result.return_value = ValidationResult(
        accepted=accepted,
        quorum_status="achieved",
        pii_detected=pii_detected,
        errors=errors or [],
        finding_id=finding_id if accepted else None,
    )
    return vl


def _make_test_client(
    generator: Any = None,
    validation_layer: Any = None,
    findings_store: Any = None,
) -> TestClient:
    """Create a TestClient backed by a fully-injectable test app."""
    if findings_store is None:
        findings_store = _make_memory_store()
    if generator is None:
        unit = _make_verify_unit()
        generator = _make_mock_generator(unit=unit)
        generator._assignments = {unit.unit_id: None}
    if validation_layer is None:
        validation_layer = _make_mock_validation_layer()
    app = create_app(
        generator=generator,
        validation_layer=validation_layer,
        findings_store=findings_store,
    )
    return TestClient(app)


def _valid_result_body(unit_id: str = "verify-abc123456789") -> dict[str, Any]:
    """Return a minimal valid POST /result body."""
    return {
        "unit_id": unit_id,
        "worker_id": "worker-001",
        "result": {"verdict": "verified", "reasoning": "Checked the docs."},
        "provenance": {
            "model": "claude-opus-4-5",
            "timestamp": "2099-01-01T00:00:00+00:00",
            "session_tokens_used": 100,
        },
    }


# ---------------------------------------------------------------------------
# Pydantic model tests (NFR-003)
# ---------------------------------------------------------------------------


class TestPydanticModels:
    """All API request/response bodies must be Pydantic BaseModel subclasses."""

    def test_work_unit_response_is_pydantic_model(self) -> None:
        """WorkUnitResponse inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(WorkUnitResponse, BaseModel)

    def test_result_submission_is_pydantic_model(self) -> None:
        """ResultSubmission inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(ResultSubmission, BaseModel)

    def test_acceptance_response_is_pydantic_model(self) -> None:
        """AcceptanceResponse inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(AcceptanceResponse, BaseModel)

    def test_status_response_is_pydantic_model(self) -> None:
        """StatusResponse inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(StatusResponse, BaseModel)

    def test_health_response_is_pydantic_model(self) -> None:
        """HealthResponse inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(HealthResponse, BaseModel)

    def test_work_unit_input_is_pydantic_model(self) -> None:
        """WorkUnitInput inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(WorkUnitInput, BaseModel)

    def test_work_unit_constraints_is_pydantic_model(self) -> None:
        """WorkUnitConstraints inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(WorkUnitConstraints, BaseModel)


# ---------------------------------------------------------------------------
# GET /work — AC-001
# ---------------------------------------------------------------------------


class TestGetWork:
    """Tests for GET /work endpoint."""

    def test_work_available_returns_200(self) -> None:
        """GET /work returns HTTP 200 when a unit is available (AC-001)."""
        client = _make_test_client()
        response = client.get("/work")
        assert response.status_code == 200

    def test_work_available_body_passes_work_unit_response_validation(self) -> None:
        """GET /work body is valid WorkUnitResponse when unit is available (AC-001)."""
        client = _make_test_client()
        response = client.get("/work")
        data = response.json()
        # Must validate as WorkUnitResponse without raising
        model = WorkUnitResponse.model_validate(data)
        assert model.available is True

    def test_work_available_includes_all_expected_fields(self) -> None:
        """GET /work includes unit_id, type, path, difficulty, and constraints."""
        client = _make_test_client()
        data = client.get("/work").json()
        assert data["available"] is True
        assert data["unit_id"] is not None
        assert data["type"] == "verify_finding"
        assert data["path"] == 5
        assert data["difficulty"] == "low"
        assert data["constraints"] is not None
        assert "max_output_tokens" in data["constraints"]
        assert "pii_filter" in data["constraints"]
        assert "requires_quorum" in data["constraints"]

    def test_work_available_input_has_verify_finding_fields(self) -> None:
        """verify_finding units include claim, cited_eftas, efta_urls in input."""
        client = _make_test_client()
        data = client.get("/work").json()
        inp = data["input"]
        assert inp["claim"] is not None
        assert inp["cited_eftas"] is not None
        assert inp["efta_urls"] is not None
        assert inp["source_verified"] is False

    def test_work_unavailable_returns_200_with_available_false(self) -> None:
        """GET /work returns HTTP 200 with available=false when no units available (AC-001)."""
        gen = _make_mock_generator(raises=True)
        client = _make_test_client(generator=gen)
        response = client.get("/work")
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False

    def test_work_unavailable_body_is_minimal(self) -> None:
        """GET /work unavailable response only mandates available key."""
        gen = _make_mock_generator(raises=True)
        client = _make_test_client(generator=gen)
        data = client.get("/work").json()
        assert "available" in data
        assert data["available"] is False

    def test_work_unavailable_passes_work_unit_response_validation(self) -> None:
        """Unavailable response also passes WorkUnitResponse.model_validate."""
        gen = _make_mock_generator(raises=True)
        client = _make_test_client(generator=gen)
        data = client.get("/work").json()
        model = WorkUnitResponse.model_validate(data)
        assert model.available is False


# ---------------------------------------------------------------------------
# POST /result — AC-002, AC-003, FR-024
# ---------------------------------------------------------------------------


class TestPostResult:
    """Tests for POST /result endpoint."""

    def _client_with_known_unit(
        self,
        unit_id: str = "verify-abc123456789",
        *,
        validation_layer: Any = None,
    ) -> TestClient:
        """Build a client where *unit_id* is already registered in the generator."""
        unit = _make_verify_unit(unit_id)
        gen = _make_mock_generator(unit=unit)
        gen._assignments = {unit_id: None}
        gen._unit_to_claim = {unit_id: {"claim_id": "claim-001"}}
        gen._unit_to_doc_keys = {}
        if validation_layer is None:
            validation_layer = _make_mock_validation_layer(finding_id="finding-test000001")
        return _make_test_client(generator=gen, validation_layer=validation_layer)

    # --- valid submission ---

    def test_valid_submission_returns_200(self) -> None:
        """POST /result with valid body returns HTTP 200 (AC-003)."""
        client = self._client_with_known_unit()
        resp = client.post("/result", json=_valid_result_body())
        assert resp.status_code == 200

    def test_valid_submission_body_has_all_required_fields(self) -> None:
        """POST /result response contains accepted, finding_id, quorum_status,
        pii_detected, next_unit_available (AC-003)."""
        client = self._client_with_known_unit()
        data = client.post("/result", json=_valid_result_body()).json()
        assert "accepted" in data
        assert "quorum_status" in data
        assert "pii_detected" in data
        assert "next_unit_available" in data
        # finding_id key must be present (may be None if rejected, but key must exist)
        assert "finding_id" in data

    def test_valid_submission_accepted_true(self) -> None:
        """POST /result accepted=True when validation passes."""
        client = self._client_with_known_unit()
        data = client.post("/result", json=_valid_result_body()).json()
        assert data["accepted"] is True
        assert data["finding_id"] is not None

    def test_valid_submission_response_validates_as_acceptance_response(self) -> None:
        """POST /result response passes AcceptanceResponse.model_validate."""
        client = self._client_with_known_unit()
        data = client.post("/result", json=_valid_result_body()).json()
        model = AcceptanceResponse.model_validate(data)
        assert model.accepted is True

    # --- invalid body ---

    def test_invalid_body_missing_unit_id_returns_422(self) -> None:
        """POST /result with missing unit_id returns HTTP 422 (FR-024)."""
        client = _make_test_client()
        body = _valid_result_body()
        del body["unit_id"]
        resp = client.post("/result", json=body)
        assert resp.status_code == 422

    def test_invalid_body_missing_worker_id_returns_422(self) -> None:
        """POST /result with missing worker_id returns HTTP 422."""
        client = _make_test_client()
        body = _valid_result_body()
        del body["worker_id"]
        resp = client.post("/result", json=body)
        assert resp.status_code == 422

    def test_invalid_body_missing_result_returns_422(self) -> None:
        """POST /result with missing result field returns HTTP 422."""
        client = _make_test_client()
        body = _valid_result_body()
        del body["result"]
        resp = client.post("/result", json=body)
        assert resp.status_code == 422

    def test_invalid_body_missing_provenance_returns_422(self) -> None:
        """POST /result with missing provenance returns HTTP 422."""
        client = _make_test_client()
        body = _valid_result_body()
        del body["provenance"]
        resp = client.post("/result", json=body)
        assert resp.status_code == 422

    def test_empty_body_returns_422(self) -> None:
        """POST /result with empty body returns HTTP 422."""
        client = _make_test_client()
        resp = client.post("/result", json={})
        assert resp.status_code == 422

    def test_empty_unit_id_returns_422(self) -> None:
        """POST /result with empty string unit_id returns HTTP 422."""
        client = _make_test_client()
        body = _valid_result_body()
        body["unit_id"] = ""
        resp = client.post("/result", json=body)
        assert resp.status_code == 422

    # --- unit not found ---

    def test_unknown_unit_id_returns_404(self) -> None:
        """POST /result with unit_id not in generator returns HTTP 404."""
        gen = _make_mock_generator()
        gen._assignments = {}  # empty — unit_id not known
        client = _make_test_client(generator=gen)
        resp = client.post("/result", json=_valid_result_body("unknown-unit"))
        assert resp.status_code == 404

    # --- idempotency ---

    def test_duplicate_submission_returns_existing_finding_id(self) -> None:
        """Duplicate submission for already-accepted unit_id returns existing finding_id
        with accepted=True (idempotency requirement)."""
        existing_id = "finding-existing001"
        unit_id = "verify-abc123456789"
        # check_deduplication returns an existing finding
        vl = _make_mock_validation_layer(existing_id=existing_id)
        vl.check_deduplication.return_value = (
            f"Duplicate: already accepted as {existing_id}",
            existing_id,
        )
        client = self._client_with_known_unit(unit_id=unit_id, validation_layer=vl)
        data = client.post("/result", json=_valid_result_body(unit_id)).json()
        assert data["accepted"] is True
        assert data["finding_id"] == existing_id

    def test_duplicate_submission_returns_200(self) -> None:
        """Duplicate submission returns HTTP 200."""
        existing_id = "finding-existing001"
        unit_id = "verify-abc123456789"
        vl = _make_mock_validation_layer(existing_id=existing_id)
        vl.check_deduplication.return_value = (
            f"Duplicate: already accepted as {existing_id}",
            existing_id,
        )
        client = self._client_with_known_unit(unit_id=unit_id, validation_layer=vl)
        resp = client.post("/result", json=_valid_result_body(unit_id))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /status — FR-025, AC-004
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for GET /status endpoint."""

    def _client_with_status(
        self,
        total_generated: int = 5,
        total_assigned: int = 3,
        total_completed: int = 2,
    ) -> TestClient:
        gen = _make_mock_generator()
        gen.get_status.return_value = {
            "total_generated": total_generated,
            "total_assigned": total_assigned,
            "total_completed": total_completed,
        }
        return _make_test_client(generator=gen)

    def test_status_returns_200(self) -> None:
        """GET /status returns HTTP 200 (FR-025)."""
        client = self._client_with_status()
        assert client.get("/status").status_code == 200

    def test_status_body_has_all_required_fields(self) -> None:
        """GET /status response includes all AC-004 required fields."""
        client = self._client_with_status()
        data = client.get("/status").json()
        required = {
            "total_units_generated",
            "total_units_assigned",
            "total_units_completed",
            "total_findings_accepted",
            "total_findings_quarantined",
            "coverage_by_type",
        }
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_status_validates_as_status_response_model(self) -> None:
        """GET /status response passes StatusResponse.model_validate."""
        client = self._client_with_status()
        data = client.get("/status").json()
        model = StatusResponse.model_validate(data)
        assert model.total_units_generated >= 0

    def test_status_integer_fields_are_non_negative(self) -> None:
        """All integer fields in GET /status are non-negative (AC-004)."""
        client = self._client_with_status()
        data = client.get("/status").json()
        for field in (
            "total_units_generated",
            "total_units_assigned",
            "total_units_completed",
            "total_findings_accepted",
            "total_findings_quarantined",
        ):
            assert data[field] >= 0, f"Field {field!r} should be >= 0"

    def test_status_ordering_constraint(self) -> None:
        """total_units_completed <= total_units_assigned <= total_units_generated (AC-004)."""
        client = self._client_with_status(
            total_generated=10, total_assigned=6, total_completed=3
        )
        data = client.get("/status").json()
        gen = data["total_units_generated"]
        asgn = data["total_units_assigned"]
        comp = data["total_units_completed"]
        assert comp <= asgn, f"completed ({comp}) must be <= assigned ({asgn})"
        assert asgn <= gen, f"assigned ({asgn}) must be <= generated ({gen})"

    def test_status_coverage_by_type_contains_expected_types(self) -> None:
        """coverage_by_type contains verify_finding and decision_chain keys."""
        client = self._client_with_status()
        data = client.get("/status").json()
        coverage = data["coverage_by_type"]
        assert "verify_finding" in coverage
        assert "decision_chain" in coverage

    def test_status_with_zero_counts(self) -> None:
        """GET /status returns valid response when all counts are zero."""
        client = self._client_with_status(
            total_generated=0, total_assigned=0, total_completed=0
        )
        data = client.get("/status").json()
        assert data["total_units_generated"] == 0
        assert data["total_units_assigned"] == 0
        assert data["total_units_completed"] == 0


# ---------------------------------------------------------------------------
# GET /health — FR-026, AC-005
# ---------------------------------------------------------------------------


class TestGetHealth:
    """Tests for GET /health endpoint."""

    def test_health_returns_200(self) -> None:
        """GET /health returns HTTP 200 (FR-026, AC-005)."""
        client = _make_test_client()
        assert client.get("/health").status_code == 200

    def test_health_body_has_required_fields(self) -> None:
        """GET /health response includes status, version, findings_db_reachable (AC-005)."""
        client = _make_test_client()
        data = client.get("/health").json()
        assert "status" in data
        assert "version" in data
        assert "findings_db_reachable" in data

    def test_health_status_is_ok(self) -> None:
        """GET /health status field is 'ok'."""
        client = _make_test_client()
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_health_version_is_string(self) -> None:
        """GET /health version is a non-empty string."""
        client = _make_test_client()
        data = client.get("/health").json()
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    def test_health_findings_db_reachable_true_when_store_ok(self) -> None:
        """findings_db_reachable is True when SQLite store is reachable."""
        store = _make_memory_store()
        client = _make_test_client(findings_store=store)
        data = client.get("/health").json()
        assert data["findings_db_reachable"] is True

    def test_health_findings_db_reachable_false_when_store_broken(self) -> None:
        """GET /health returns HTTP 200 even if findings_db is unreachable;
        findings_db_reachable is False (AC-005)."""
        # Create a store then close its connection to simulate unreachable DB
        store = _make_memory_store()
        store._conn.close()
        client = _make_test_client(findings_store=store)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["findings_db_reachable"] is False

    def test_health_validates_as_health_response_model(self) -> None:
        """GET /health response passes HealthResponse.model_validate."""
        client = _make_test_client()
        data = client.get("/health").json()
        model = HealthResponse.model_validate(data)
        assert model.status == "ok"

    def test_health_response_time_is_fast(self) -> None:
        """GET /health should respond quickly (no blocking I/O)."""
        import time

        client = _make_test_client()
        start = time.monotonic()
        client.get("/health")
        elapsed_ms = (time.monotonic() - start) * 1000
        # Allow generous margin for test environments; requirement is <500ms
        assert elapsed_ms < 500, f"Health check took {elapsed_ms:.1f}ms (limit 500ms)"


# ---------------------------------------------------------------------------
# POST /result — mark_unit_complete integration
# ---------------------------------------------------------------------------


class TestPostResultMarkComplete:
    """Verify that mark_unit_complete is called on acceptance."""

    def test_mark_unit_complete_called_on_acceptance(self) -> None:
        """mark_unit_complete is invoked when result is accepted."""
        unit_id = "verify-abc123456789"
        unit = _make_verify_unit(unit_id)
        gen = _make_mock_generator(unit=unit)
        gen._assignments = {unit_id: None}
        gen._unit_to_claim = {unit_id: {"claim_id": "claim-001"}}
        gen._unit_to_doc_keys = {}
        vl = _make_mock_validation_layer(accepted=True, finding_id="finding-ok0001")
        client = _make_test_client(generator=gen, validation_layer=vl)
        client.post("/result", json=_valid_result_body(unit_id))
        gen.mark_unit_complete.assert_called_once_with(unit_id)

    def test_mark_unit_complete_not_called_when_rejected(self) -> None:
        """mark_unit_complete is NOT called when validation rejects the result."""
        unit_id = "verify-abc123456789"
        unit = _make_verify_unit(unit_id)
        gen = _make_mock_generator(unit=unit)
        gen._assignments = {unit_id: None}
        gen._unit_to_claim = {unit_id: {"claim_id": "claim-001"}}
        gen._unit_to_doc_keys = {}
        vl = _make_mock_validation_layer(
            accepted=False, errors=["Provenance error: EFTA not found"]
        )
        client = _make_test_client(generator=gen, validation_layer=vl)
        client.post("/result", json=_valid_result_body(unit_id))
        gen.mark_unit_complete.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: real components with in-memory DB
# ---------------------------------------------------------------------------


class TestIntegrationRealComponents:
    """Integration tests using real FindingsStore and ValidationLayer (in-memory SQLite)."""

    def _make_real_app_client(
        self,
        claims: list[dict] | None = None,
    ) -> TestClient:
        """Build a TestClient using real components with in-memory SQLite."""
        import sqlite3 as _sqlite3

        from sefi.db.adapter import DatabaseAdapter
        from sefi.generator.units import WorkUnitGenerator

        # In-memory findings store
        store = _make_memory_store()

        # In-memory db adapter (no data — provenance will pass on empty citations)
        conn = _sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = _sqlite3.Row
        adapter = DatabaseAdapter(conn)

        # Generator with injected claims (no file I/O)
        if claims is None:
            claims = [
                {
                    "claim_id": "claim-001",
                    "claim": "Test claim",
                    "cited_eftas": ["EFTA00039186"],
                    "primary_datasets": [9],
                    "source_verified": False,
                }
            ]

        def mock_url_builder(efta_int: int, dataset: int) -> str:
            return f"{_DOJ_PREFIX}{dataset}/EFTA{efta_int:08d}.pdf"

        gen = WorkUnitGenerator(claims=claims, url_builder=mock_url_builder)
        vl = ValidationLayer(db_adapter=adapter, findings_store=store)

        app = create_app(generator=gen, validation_layer=vl, findings_store=store)
        return TestClient(app)

    def test_full_workflow_get_work_then_submit(self) -> None:
        """Full end-to-end: GET /work then POST /result then GET /status."""
        client = self._make_real_app_client()

        # 1. Get a work unit
        work_resp = client.get("/work")
        assert work_resp.status_code == 200
        work_data = work_resp.json()
        assert work_data["available"] is True
        unit_id = work_data["unit_id"]
        assert unit_id is not None

        # 2. Submit result
        body = _valid_result_body(unit_id)
        result_resp = client.post("/result", json=body)
        assert result_resp.status_code == 200
        result_data = result_resp.json()
        assert result_data["accepted"] is True

        # 3. Check status reflects changes
        status_data = client.get("/status").json()
        assert status_data["total_units_generated"] >= 1

    def test_get_status_after_accepting_finding(self) -> None:
        """total_findings_accepted increments after a valid submission."""
        client = self._make_real_app_client()
        work_data = client.get("/work").json()
        unit_id = work_data["unit_id"]
        client.post("/result", json=_valid_result_body(unit_id))
        status = client.get("/status").json()
        assert status["total_findings_accepted"] >= 1

    def test_idempotent_submission_real_db(self) -> None:
        """Real DB idempotency: second submission for same unit_id returns same finding_id."""
        client = self._make_real_app_client()
        work_data = client.get("/work").json()
        unit_id = work_data["unit_id"]

        first = client.post("/result", json=_valid_result_body(unit_id)).json()
        assert first["accepted"] is True
        finding_id_1 = first["finding_id"]

        second = client.post("/result", json=_valid_result_body(unit_id)).json()
        assert second["accepted"] is True
        assert second["finding_id"] == finding_id_1


# ---------------------------------------------------------------------------
# POST /result — PII quarantine path
# ---------------------------------------------------------------------------


class TestPostResultPIIPath:
    """Verify PII detection returns correct AcceptanceResponse."""

    def test_pii_result_not_accepted(self) -> None:
        """PII in result causes accepted=False and pii_detected=True."""
        unit_id = "verify-abc123456789"
        unit = _make_verify_unit(unit_id)
        gen = _make_mock_generator(unit=unit)
        gen._assignments = {unit_id: None}
        gen._unit_to_claim = {unit_id: {"claim_id": "claim-001"}}
        gen._unit_to_doc_keys = {}
        vl = _make_mock_validation_layer(
            accepted=False,
            pii_detected=True,
            errors=["PII detected — pattern 'ssn' matched text '123-45-6789'"],
        )
        client = _make_test_client(generator=gen, validation_layer=vl)
        data = client.post("/result", json=_valid_result_body(unit_id)).json()
        assert data["accepted"] is False
        assert data["pii_detected"] is True
        assert len(data["errors"]) > 0
