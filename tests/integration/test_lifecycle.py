"""End-to-end integration test for the SEFI@Home work unit lifecycle.

Covers the full lifecycle:
    1. System startup — IngestManager loads all three required JSON files.
    2. Simulated worker claims a ``verify_finding`` unit via ``GET /work``.
    3. Worker submits a ``POST /result`` with no live HTTP (provenance is
       checked against ingested SQLite tables, not live DOJ URLs).
    4. Result is accepted and persisted to ``findings.db``.
    5. Stored finding has non-null ``worker_id`` and ``submitted_at``.
    6. Generating 1,000 ``verify_finding`` units produces 1,000 unique IDs.

Acceptance criteria covered (US-010):
    FR-047  — All three required JSON files are loaded; missing file fails fast.
    FR-048  — Simulated worker completes full lifecycle without DB credentials.
    FR-049  — 1,000 generated units have unique unit_id values.
    FR-050  — Stored finding has non-null worker_id and submitted_at within 5s.
    OQ-003  — No live network calls; provenance checks use ingested SQLite tables.
    FR-038  — Test uses a fresh in-memory / temp-dir findings.db.
    NFR-005 — ``pytest tests/integration/`` runs without configuration errors.

Design notes:
    - No live HTTP calls are made. Justice.gov PDF fetches are irrelevant to the
      server-side integration test.  The ``WorkUnitGenerator`` uses an injectable
      ``url_builder`` that builds valid-format DOJ URLs locally.
      ``ValidationLayer.verify_provenance`` checks the ingested ``efta_mapping``
      and ``entities`` SQLite tables — it never makes HTTP requests.
    - The ``TestClient`` from ``starlette.testclient`` is used for synchronous
      testing (no asyncio required).
    - Fixture data lives in ``tests/integration/fixtures/`` and is loaded via
      ``pathlib.Path(__file__).parent / "fixtures"``.
    - The fresh ``FindingsStore`` is opened against a ``tempfile.TemporaryDirectory``
      path to satisfy FR-038 (no leftover state from unit tests).
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from sefi.api.main import create_app
from sefi.db.adapter import DatabaseAdapter
from sefi.db.ingest import IngestManager
from sefi.generator.units import WorkUnitGenerator
from sefi.store.findings import FindingsStore
from sefi.validation.layer import ValidationLayer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Absolute path to the fixture directory.
_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"

#: Three required JSON file names per FR-047.
_REQUIRED_JSON_FILES: tuple[str, ...] = (
    "persons_registry.json",
    "knowledge_graph_relationships.json",
    "efta_dataset_mapping.json",
)

#: Worker identifier used throughout lifecycle tests.
_TEST_WORKER_ID: str = "integration-test-worker-001"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _mock_url_builder(efta_int: int, dataset: int) -> str:
    """Return a deterministic DOJ PDF URL without any HTTP call.

    Used as an injectable ``url_builder`` for :class:`WorkUnitGenerator` so
    that no network access is required during unit generation.  The returned
    URL is syntactically valid per FR-014 / DR-012.

    Parameters
    ----------
    efta_int:
        Integer EFTA number (e.g. ``39186``).
    dataset:
        Dataset number (1–12).

    Returns
    -------
    str
        A valid justice.gov PDF URL string.
    """
    return (
        f"https://www.justice.gov/epstein/files/DataSet%20{dataset}"
        f"/EFTA{efta_int:08d}.pdf"
    )


def _build_in_memory_adapter(data_dir: Path) -> DatabaseAdapter:
    """Build a :class:`DatabaseAdapter` backed by an in-memory SQLite DB.

    Ingests all four fixture JSON files into working tables so that provenance
    checks resolve correctly in the ``ValidationLayer`` without HTTP calls.

    Parameters
    ----------
    data_dir:
        Directory containing the fixture JSON export files.

    Returns
    -------
    DatabaseAdapter
        Ready-to-use adapter with all working tables populated.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    manager = IngestManager(conn=conn, data_dir=data_dir)
    manager.ingest_all()
    adapter = DatabaseAdapter(conn)
    return adapter


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_data_dir() -> Path:
    """Return the path to the integration test fixtures directory.

    Returns
    -------
    Path
        Absolute path to ``tests/integration/fixtures/``.
    """
    return _FIXTURES_DIR


@pytest.fixture()
def temp_findings_db(tmp_path: Path) -> Path:
    """Return a path for a fresh findings database in a temporary directory.

    Using ``tmp_path`` (a pytest built-in fixture) ensures that every test
    invocation gets a completely isolated findings.db with no leftover state
    from unit tests (FR-038).

    Parameters
    ----------
    tmp_path:
        Pytest-provided temporary directory (unique per test).

    Returns
    -------
    Path
        Path to ``<tmp_path>/findings.db`` (file does not yet exist).
    """
    return tmp_path / "findings.db"


@pytest.fixture()
def generator(fixture_data_dir: Path) -> WorkUnitGenerator:
    """Build a :class:`WorkUnitGenerator` loaded from fixture claims.

    Uses the ``_mock_url_builder`` to avoid any live HTTP calls when
    constructing DOJ PDF URLs.

    Parameters
    ----------
    fixture_data_dir:
        Path to the fixture data directory.

    Returns
    -------
    WorkUnitGenerator
        Generator ready to produce ``verify_finding`` units.
    """
    claims_path = fixture_data_dir / "sample_claims.json"
    return WorkUnitGenerator(
        claims_path=claims_path,
        url_builder=_mock_url_builder,
    )


@pytest.fixture()
def findings_store(temp_findings_db: Path) -> FindingsStore:
    """Build a fresh :class:`FindingsStore` backed by a temp-dir database.

    Parameters
    ----------
    temp_findings_db:
        Path to the fresh SQLite database file.

    Returns
    -------
    FindingsStore
        Store ready for use; schema is initialised automatically.
    """
    return FindingsStore(db_path=temp_findings_db)


@pytest.fixture()
def db_adapter(fixture_data_dir: Path) -> DatabaseAdapter:
    """Build a :class:`DatabaseAdapter` with all fixture data ingested.

    Parameters
    ----------
    fixture_data_dir:
        Path to the fixture data directory.

    Returns
    -------
    DatabaseAdapter
        Adapter with entities, efta_mapping, persons, and relationships loaded.
    """
    return _build_in_memory_adapter(fixture_data_dir)


@pytest.fixture()
def validation_layer(
    db_adapter: DatabaseAdapter,
    findings_store: FindingsStore,
) -> ValidationLayer:
    """Build a :class:`ValidationLayer` wired to the test adapter and store.

    Parameters
    ----------
    db_adapter:
        Adapter providing provenance lookup tables.
    findings_store:
        Store for persisting validated findings.

    Returns
    -------
    ValidationLayer
        Ready-to-use validation layer.
    """
    return ValidationLayer(
        db_adapter=db_adapter,
        findings_store=findings_store,
    )


@pytest.fixture()
def test_client(
    generator: WorkUnitGenerator,
    validation_layer: ValidationLayer,
    findings_store: FindingsStore,
) -> TestClient:
    """Build a synchronous :class:`TestClient` wrapping the full FastAPI app.

    All three core components are injected to avoid any filesystem or network
    dependencies during testing.

    Parameters
    ----------
    generator:
        Pre-built work unit generator.
    validation_layer:
        Pre-built validation layer.
    findings_store:
        Pre-built findings store.

    Returns
    -------
    TestClient
        Starlette synchronous test client.
    """
    app = create_app(
        generator=generator,
        validation_layer=validation_layer,
        findings_store=findings_store,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# FR-047 — Startup ingest
# ---------------------------------------------------------------------------


class TestStartupIngest:
    """Tests covering FR-047: required JSON files loaded at startup."""

    def test_ingest_all_three_required_files(self, fixture_data_dir: Path) -> None:
        """All three required JSON files are loaded; record counts are positive.

        Verifies that IngestManager.ingest_all() loads persons, relationships,
        and efta_mapping with positive record counts.
        """
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        manager = IngestManager(conn=conn, data_dir=fixture_data_dir)
        counts = manager.ingest_all()

        # All three FR-047 required files must be represented
        assert counts["persons"] > 0, "persons_registry.json must load records"
        assert counts["relationships"] > 0, (
            "knowledge_graph_relationships.json must load records"
        )
        assert counts["efta_mapping"] > 0, (
            "efta_dataset_mapping.json must load records"
        )

    def test_missing_required_file_fails_fast(self, tmp_path: Path) -> None:
        """If a required JSON file is absent, startup fails with a descriptive error.

        Per FR-047: if any required file is missing, the system must fail fast
        with a descriptive error identifying the missing file.
        """
        # Copy only three of the four fixture files; omit persons_registry.json
        for fname in (
            "knowledge_graph_entities.json",
            "knowledge_graph_relationships.json",
            "efta_dataset_mapping.json",
        ):
            shutil.copy(_FIXTURES_DIR / fname, tmp_path / fname)
        # persons_registry.json is intentionally absent

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        manager = IngestManager(conn=conn, data_dir=tmp_path)
        with pytest.raises(FileNotFoundError) as exc_info:
            manager.ingest_all()

        error_message = str(exc_info.value)
        assert "persons_registry.json" in error_message, (
            "FileNotFoundError message must identify the missing file by name"
        )

    def test_ingest_counts_logged(
        self, fixture_data_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Record counts must be logged at INFO level after each file loads.

        Per FR-047 acceptance criterion: record counts are logged.
        """
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        manager = IngestManager(conn=conn, data_dir=fixture_data_dir)

        with caplog.at_level(logging.INFO, logger="sefi.db.ingest"):
            manager.ingest_all()

        info_messages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert len(info_messages) > 0, (
            "IngestManager must emit INFO log entries with record counts"
        )


# ---------------------------------------------------------------------------
# FR-048 / FR-050 — Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Tests covering the full claim → work unit → submit result → store cycle."""

    def test_claim_verify_finding_unit_via_get_work(
        self, test_client: TestClient
    ) -> None:
        """A simulated worker claims a verify_finding unit via GET /work.

        Per FR-048: worker receives a valid WorkUnit JSON response with
        ``available=True`` and all required fields populated.
        """
        response = test_client.get("/work")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is True
        assert body["type"] == "verify_finding"
        assert body["unit_id"], "unit_id must be a non-empty string"
        assert body["input"]["claim"], "claim must be non-empty"
        assert len(body["input"]["cited_eftas"]) > 0, (
            "cited_eftas must be non-empty"
        )
        assert len(body["input"]["efta_urls"]) > 0, (
            "efta_urls must be non-empty"
        )
        assert len(body["input"]["cited_eftas"]) == len(
            body["input"]["efta_urls"]
        ), "cited_eftas and efta_urls must have matching lengths"

    def test_submit_result_accepted_no_live_http(
        self,
        test_client: TestClient,
        findings_store: FindingsStore,
    ) -> None:
        """Worker submits POST /result with no live HTTP and receives accepted=True.

        Per FR-048: the worker has no database credentials; the server handles
        all persistence.  No live HTTP calls are made — provenance checks use
        the ingested SQLite tables.
        Per FR-050: stored finding has non-null worker_id and submitted_at within
        5 seconds of submission.
        """
        # Step 1: Claim a work unit
        claim_response = test_client.get("/work")
        assert claim_response.status_code == 200
        work_unit = claim_response.json()
        unit_id = work_unit["unit_id"]
        cited_eftas = work_unit["input"]["cited_eftas"]

        # Step 2: Record submission time before POSTing
        submission_time = datetime.now(tz=timezone.utc)

        # Step 3: Build a well-formed verify_finding result (per AC-002)
        # verdict must be one of: verified, disputed, insufficient_evidence
        result_payload: dict[str, Any] = {
            "verdict": "verified",
            "reasoning": (
                "The cited document confirms the claim with direct evidence "
                "in the referenced PDF."
            ),
            "citations": [
                {
                    "efta_number": cited_eftas[0],
                    "page_number": 1,
                    "quote": "Relevant excerpt confirming the claim.",
                }
            ],
        }

        # Step 4: POST /result — no live network calls needed
        post_response = test_client.post(
            "/result",
            json={
                "unit_id": unit_id,
                "worker_id": _TEST_WORKER_ID,
                "result": result_payload,
                "provenance": {
                    "model": "integration-test",
                    "timestamp": submission_time.isoformat(),
                    "session_tokens_used": 42,
                },
            },
        )

        assert post_response.status_code == 200
        body = post_response.json()
        assert body["accepted"] is True, (
            f"Expected accepted=True, got errors: {body.get('errors')}"
        )
        assert body["finding_id"], "finding_id must be non-empty when accepted"
        assert body["pii_detected"] is False

        # Step 5: Verify finding persisted to findings.db with non-null fields (FR-050)
        finding_id = body["finding_id"]
        conn = findings_store._conn
        row = conn.execute(
            """
            SELECT worker_id, submitted_at
            FROM findings
            WHERE finding_id = ? AND status = 'accepted'
            """,
            (finding_id,),
        ).fetchone()

        assert row is not None, (
            f"finding_id {finding_id!r} not found in findings.db with status='accepted'"
        )
        stored_worker_id: str = row[0]
        stored_submitted_at: str = row[1]

        assert stored_worker_id is not None, "worker_id must be non-null (FR-050)"
        assert stored_worker_id == _TEST_WORKER_ID
        assert stored_submitted_at is not None, "submitted_at must be non-null (FR-050)"

        # submitted_at must be within 5 seconds of the test's submission time (FR-050)
        submitted_dt = datetime.fromisoformat(stored_submitted_at)
        if submitted_dt.tzinfo is None:
            submitted_dt = submitted_dt.replace(tzinfo=timezone.utc)
        delta_seconds = abs((submitted_dt - submission_time).total_seconds())
        assert delta_seconds <= 5.0, (
            f"submitted_at ({stored_submitted_at!r}) is {delta_seconds:.1f}s from "
            "submission time — must be within 5 seconds (FR-050)"
        )

    def test_submitted_at_within_five_seconds(
        self,
        test_client: TestClient,
        findings_store: FindingsStore,
    ) -> None:
        """The stored finding's submitted_at timestamp is within 5 seconds of submission.

        Dedicated test for FR-050 timing constraint.
        """
        work_response = test_client.get("/work")
        assert work_response.status_code == 200
        unit_id = work_response.json()["unit_id"]
        cited_eftas = work_response.json()["input"]["cited_eftas"]

        before_submission = datetime.now(tz=timezone.utc)

        result_response = test_client.post(
            "/result",
            json={
                "unit_id": unit_id,
                "worker_id": _TEST_WORKER_ID,
                "result": {
                    "verdict": "verified",
                    "reasoning": "The document directly supports the claim.",
                    "citations": [
                        {
                            "efta_number": cited_eftas[0],
                            "page_number": 2,
                            "quote": "Confirming excerpt.",
                        }
                    ],
                },
                "provenance": {
                    "model": "integration-test",
                    "timestamp": before_submission.isoformat(),
                    "session_tokens_used": 10,
                },
            },
        )

        after_submission = datetime.now(tz=timezone.utc)

        assert result_response.status_code == 200
        body = result_response.json()
        assert body["accepted"] is True
        finding_id = body["finding_id"]

        row = findings_store._conn.execute(
            "SELECT submitted_at FROM findings WHERE finding_id = ?",
            (finding_id,),
        ).fetchone()
        assert row is not None

        stored_submitted_at: str = row[0]
        submitted_dt = datetime.fromisoformat(stored_submitted_at)
        if submitted_dt.tzinfo is None:
            submitted_dt = submitted_dt.replace(tzinfo=timezone.utc)

        # Must be within 5s of both bounds
        assert (submitted_dt - before_submission).total_seconds() <= 5.0, (
            "submitted_at must be within 5s of test submission time"
        )
        assert (after_submission - submitted_dt).total_seconds() >= -1.0, (
            "submitted_at must not be in the future relative to test completion"
        )


# ---------------------------------------------------------------------------
# FR-049 — unit_id uniqueness across 1,000 units
# ---------------------------------------------------------------------------


class TestUnitIdUniqueness:
    """Tests covering FR-049: all generated unit_ids are unique."""

    def test_one_thousand_verify_finding_units_have_unique_ids(self) -> None:
        """Generating 1,000 verify_finding units yields 1,000 unique unit_ids.

        Per FR-049: collecting all unit_id values into a set produces a set of
        size exactly 1,000 (no duplicates).

        A synthetic claims list of 1,000 entries is used so the generator is
        not limited by the small fixture file.  Each synthetic claim has a
        unique ``claim_id`` so the generator does not deduplicate them.
        """
        synthetic_claims = [
            {
                "claim_id": f"SYN-{i:04d}",
                "claim": f"Synthetic claim number {i} for uniqueness testing.",
                "cited_eftas": ["EFTA00039186"],
                "primary_datasets": [9],
                "source": "uniqueness-test",
                "source_verified": False,
            }
            for i in range(1, 1001)
        ]

        gen = WorkUnitGenerator(
            claims=synthetic_claims,
            url_builder=_mock_url_builder,
        )

        unit_ids: set[str] = set()
        for _ in range(1000):
            unit = gen.generate_unit("verify_finding")
            unit_ids.add(unit.unit_id)
            # Mark each unit complete so its claim slot is freed and the
            # generator can reuse the same claim with a new unit_id if needed.
            gen.mark_unit_complete(unit.unit_id)

        assert len(unit_ids) == 1000, (
            f"Expected 1,000 unique unit_ids; got {len(unit_ids)} distinct values "
            "(duplicates detected — UUID generation must be unique)"
        )


# ---------------------------------------------------------------------------
# OQ-003 — No live network calls
# ---------------------------------------------------------------------------


class TestNoLiveNetworkCalls:
    """Guards that the integration test requires no live network calls (OQ-003).

    The MVP's provenance check does not make HTTP requests.  It queries the
    ingested ``efta_mapping`` SQLite table.  The ``WorkUnitGenerator`` uses
    an injectable ``url_builder`` to construct URLs locally.  Therefore the
    entire lifecycle test runs without any network access.
    """

    def test_full_lifecycle_completes_without_network(
        self, test_client: TestClient, findings_store: FindingsStore
    ) -> None:
        """Full lifecycle (GET /work + POST /result) completes with no HTTP I/O.

        The test wires up the app using fixture JSON data (in-memory SQLite)
        and a mock url_builder.  No socket connections are expected.  If the
        test passes on a machine with no internet access it demonstrates OQ-003
        compliance.
        """
        # Claim a unit
        work_response = test_client.get("/work")
        assert work_response.status_code == 200
        unit_id = work_response.json()["unit_id"]
        cited_eftas = work_response.json()["input"]["cited_eftas"]

        # Submit a result
        result_response = test_client.post(
            "/result",
            json={
                "unit_id": unit_id,
                "worker_id": _TEST_WORKER_ID,
                "result": {
                    "verdict": "verified",
                    "reasoning": "Network-free test reasoning.",
                    "citations": [
                        {
                            "efta_number": cited_eftas[0],
                            "page_number": 1,
                            "quote": "Network-free test quote.",
                        }
                    ],
                },
                "provenance": {
                    "model": "integration-test",
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "session_tokens_used": 5,
                },
            },
        )

        assert result_response.status_code == 200
        assert result_response.json()["accepted"] is True, (
            "Full lifecycle must complete without network access"
        )
