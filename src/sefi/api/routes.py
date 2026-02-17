"""FastAPI router for the SEFI@Home Distribution API (Component 3).

Implements all four MVP endpoints:

- ``GET /work``   — claim the next available work unit (FR-023, AC-001)
- ``POST /result`` — submit analysis results (FR-024, AC-002, AC-003)
- ``GET /status``  — project-wide statistics (FR-025, AC-004)
- ``GET /health``  — liveness check (FR-026, AC-005)

Dependencies (injected via FastAPI ``Depends``):

- :class:`~sefi.generator.units.WorkUnitGenerator` — work unit generation
  and assignment tracking.
- :class:`~sefi.validation.layer.ValidationLayer` — PII scanning, provenance
  check, deduplication, and result storage.
- :class:`~sefi.store.findings.FindingsStore` — aggregate statistics queries.

Authentication and rate limiting are POST-MVP.  Stub comments mark each
location where these features will be added.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

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
from sefi.validation.layer import ValidationLayer
from sefi.validation.layer import ResultSubmission as ValidationResultSubmission

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency accessor helpers
# ---------------------------------------------------------------------------


def _get_generator(request: Request) -> WorkUnitGenerator:
    """Extract the :class:`WorkUnitGenerator` from application state.

    Parameters
    ----------
    request:
        The incoming FastAPI request; ``request.app.state.generator`` must
        be set by the app factory.

    Returns
    -------
    WorkUnitGenerator
        The application-scoped generator instance.
    """
    return request.app.state.generator  # type: ignore[no-any-return]


def _get_validation_layer(request: Request) -> ValidationLayer:
    """Extract the :class:`ValidationLayer` from application state.

    Parameters
    ----------
    request:
        The incoming FastAPI request; ``request.app.state.validation_layer``
        must be set by the app factory.

    Returns
    -------
    ValidationLayer
        The application-scoped validation layer instance.
    """
    return request.app.state.validation_layer  # type: ignore[no-any-return]


def _get_findings_store(request: Request) -> FindingsStore:
    """Extract the :class:`FindingsStore` from application state.

    Parameters
    ----------
    request:
        The incoming FastAPI request; ``request.app.state.findings_store``
        must be set by the app factory.

    Returns
    -------
    FindingsStore
        The application-scoped findings store instance.
    """
    return request.app.state.findings_store  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# GET /work
# ---------------------------------------------------------------------------


@router.get(
    "/work",
    response_model=WorkUnitResponse,
    summary="Claim the next available work unit",
    tags=["distribution"],
)
def get_work(
    generator: Annotated[WorkUnitGenerator, Depends(_get_generator)],
) -> WorkUnitResponse:
    """Return the next available work unit or signal that none are available.

    When a unit is available it is returned as a :class:`WorkUnitResponse`
    with ``available=True`` and all fields populated.

    When no units are available, HTTP 200 is returned with
    ``{"available": false}`` (FR-023, AC-001).

    .. note::
        # POST-MVP: add X-SEFI-API-Key auth here
        # POST-MVP: add per-worker rate limiting here

    Parameters
    ----------
    generator:
        Injected :class:`~sefi.generator.units.WorkUnitGenerator` instance.

    Returns
    -------
    WorkUnitResponse
        Populated work unit, or ``{"available": false}`` when exhausted.
    """
    # POST-MVP: add X-SEFI-API-Key auth here
    # POST-MVP: add per-worker rate limiting here

    try:
        unit: WorkUnit = generator.generate_unit()
    except NoAvailableUnitsError:
        return WorkUnitResponse(available=False)

    return _work_unit_to_response(unit)


# ---------------------------------------------------------------------------
# POST /result
# ---------------------------------------------------------------------------


@router.post(
    "/result",
    response_model=AcceptanceResponse,
    summary="Submit analysis results for a work unit",
    tags=["distribution"],
)
def post_result(
    body: ResultSubmission,
    generator: Annotated[WorkUnitGenerator, Depends(_get_generator)],
    validation_layer: Annotated[ValidationLayer, Depends(_get_validation_layer)],
) -> AcceptanceResponse:
    """Accept, validate, and store a worker's result submission.

    Processing flow (per US-009 Notes):

    1. Pydantic validates the request body (HTTP 422 on failure).
    2. ``unit_id`` existence check — HTTP 404 if not known to the generator.
    3. Idempotency check — if the ``unit_id`` already has an accepted
       finding, return the existing ``finding_id`` with ``accepted=True``.
    4. :meth:`~sefi.validation.layer.ValidationLayer.validate_result` —
       PII scan, provenance check, deduplication.
    5. If accepted, :meth:`~sefi.generator.units.WorkUnitGenerator.mark_unit_complete`.
    6. Return :class:`AcceptanceResponse`.

    .. note::
        # POST-MVP: add X-SEFI-API-Key auth here
        # POST-MVP: add per-worker rate limiting here

    Parameters
    ----------
    body:
        Validated :class:`ResultSubmission` request body.
    generator:
        Injected :class:`~sefi.generator.units.WorkUnitGenerator` instance.
    validation_layer:
        Injected :class:`~sefi.validation.layer.ValidationLayer` instance.

    Returns
    -------
    AcceptanceResponse
        Outcome of the validation and storage attempt.

    Raises
    ------
    HTTPException
        404 if ``unit_id`` is not found in the generator's known units.
        422 is raised automatically by FastAPI/Pydantic for invalid bodies.
    """
    # POST-MVP: add X-SEFI-API-Key auth here
    # POST-MVP: add per-worker rate limiting here

    # Step 2: unit_id existence check
    if body.unit_id not in generator._assignments:
        raise HTTPException(
            status_code=404,
            detail=f"unit_id '{body.unit_id}' not found.",
        )

    # Step 3: idempotency — return existing result if already accepted
    _dedup_msg, existing_id = validation_layer.check_deduplication(body.unit_id)
    if existing_id is not None:
        # A finding already exists for this unit_id; return it idempotently.
        next_avail = _check_next_unit_available(generator)
        return AcceptanceResponse(
            accepted=True,
            finding_id=existing_id,
            quorum_status="achieved",
            pii_detected=False,
            next_unit_available=next_avail,
            errors=[],
        )

    # Step 4: run full validation pipeline
    # Map API ResultSubmission → validation layer's ResultSubmission model
    val_submission = ValidationResultSubmission(
        unit_id=body.unit_id,
        worker_id=body.worker_id,
        result=body.result,
        cited_eftas=_extract_cited_eftas(body.result),
        unit_type=_infer_unit_type(generator, body.unit_id),
    )
    validation_result = validation_layer.validate_result(val_submission)

    # Step 5: mark unit complete on acceptance
    if validation_result.accepted:
        try:
            generator.mark_unit_complete(body.unit_id)
        except KeyError:
            # unit_id was valid at step 2 but disappeared; log and continue
            logger.warning("unit_id %r disappeared before mark_unit_complete", body.unit_id)

    # Step 6: determine next-unit availability
    next_avail = _check_next_unit_available(generator)

    return AcceptanceResponse(
        accepted=validation_result.accepted,
        finding_id=validation_result.finding_id,
        quorum_status=validation_result.quorum_status,
        pii_detected=validation_result.pii_detected,
        next_unit_available=next_avail,
        errors=validation_result.errors,
    )


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Retrieve project-wide statistics",
    tags=["distribution"],
)
def get_status(
    generator: Annotated[WorkUnitGenerator, Depends(_get_generator)],
    findings_store: Annotated[FindingsStore, Depends(_get_findings_store)],
) -> StatusResponse:
    """Return aggregate project statistics (FR-025, AC-004).

    All integer fields are guaranteed non-negative.
    ``total_units_completed <= total_units_assigned <= total_units_generated``.

    .. note::
        # POST-MVP: add X-SEFI-API-Key auth here
        # POST-MVP: add per-worker rate limiting here

    Parameters
    ----------
    generator:
        Injected :class:`~sefi.generator.units.WorkUnitGenerator` instance.
    findings_store:
        Injected :class:`~sefi.store.findings.FindingsStore` instance.

    Returns
    -------
    StatusResponse
        Current project statistics.
    """
    # POST-MVP: add X-SEFI-API-Key auth here
    # POST-MVP: add per-worker rate limiting here

    gen_status = generator.get_status()

    total_generated: int = max(0, gen_status.get("total_generated", 0))
    total_assigned: int = max(0, gen_status.get("total_assigned", 0))
    total_completed: int = max(0, gen_status.get("total_completed", 0))

    # Findings counts
    total_accepted: int = _count_findings_by_status(findings_store, "accepted")
    total_quarantined: int = _count_findings_by_status(findings_store, "quarantined")

    # Coverage by MVP work unit types
    coverage: dict[str, float] = {}
    for unit_type in ("verify_finding", "decision_chain"):
        stats = findings_store.get_coverage(unit_type)
        coverage[unit_type] = stats.percent

    return StatusResponse(
        total_units_generated=total_generated,
        total_units_assigned=total_assigned,
        total_units_completed=total_completed,
        total_findings_accepted=total_accepted,
        total_findings_quarantined=total_quarantined,
        coverage_by_type=coverage,
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check",
    tags=["distribution"],
)
def get_health(
    findings_store: Annotated[FindingsStore, Depends(_get_findings_store)],
) -> HealthResponse:
    """Return a liveness check response (FR-026, AC-005).

    Always returns HTTP 200.  If ``findings.db`` is unreachable,
    ``findings_db_reachable`` is ``False`` but the HTTP status is still 200.

    .. note::
        # POST-MVP: add X-SEFI-API-Key auth here

    Parameters
    ----------
    findings_store:
        Injected :class:`~sefi.store.findings.FindingsStore` instance.

    Returns
    -------
    HealthResponse
        Service liveness status.
    """
    # POST-MVP: add X-SEFI-API-Key auth here

    version = _get_package_version()
    db_reachable = _probe_findings_db(findings_store)

    return HealthResponse(
        status="ok",
        version=version,
        findings_db_reachable=db_reachable,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _work_unit_to_response(unit: WorkUnit) -> WorkUnitResponse:
    """Convert a :class:`~sefi.generator.units.WorkUnit` dataclass to a response model.

    Parameters
    ----------
    unit:
        The work unit dataclass produced by the generator.

    Returns
    -------
    WorkUnitResponse
        A fully-populated API response model.
    """
    raw_input: dict = unit.input  # type: ignore[type-arg]

    api_input = WorkUnitInput(
        database=raw_input.get("database", ""),
        query=raw_input.get("query"),
        context=raw_input.get("context", ""),
        data=raw_input.get("data", []),
        # verify_finding extras
        claim=raw_input.get("claim"),
        cited_eftas=raw_input.get("cited_eftas"),
        efta_urls=raw_input.get("efta_urls"),
        source_verified=raw_input.get("source_verified"),
        # decision_chain extras
        time_window_start=raw_input.get("time_window_start"),
        time_window_end=raw_input.get("time_window_end"),
    )

    raw_constraints: dict = unit.constraints  # type: ignore[type-arg]
    api_constraints = WorkUnitConstraints(
        max_output_tokens=raw_constraints["max_output_tokens"],
        pii_filter=raw_constraints["pii_filter"],
        requires_quorum=raw_constraints["requires_quorum"],
    )

    return WorkUnitResponse(
        available=True,
        unit_id=unit.unit_id,
        type=unit.type,
        path=unit.path,
        difficulty=unit.difficulty,
        scaling=unit.scaling,
        optimal_batch=unit.optimal_batch,
        input=api_input,
        instructions=unit.instructions,
        constraints=api_constraints,
        deadline=unit.deadline,
    )


def _check_next_unit_available(generator: WorkUnitGenerator) -> bool:
    """Return ``True`` if the generator can produce at least one more unit.

    Tries ``generate_unit()`` without consuming the unit (does not call
    ``mark_unit_assigned``).  Any exception means no units are available.

    Parameters
    ----------
    generator:
        The active :class:`~sefi.generator.units.WorkUnitGenerator`.

    Returns
    -------
    bool
        ``True`` if another unit is available; ``False`` otherwise.
    """
    try:
        generator.generate_unit()
        return True
    except (NoAvailableUnitsError, Exception):  # noqa: BLE001
        return False


def _extract_cited_eftas(result: dict) -> list[str]:
    """Extract cited EFTA numbers from a result payload if present.

    Looks for a ``citations`` list (``verify_finding`` type) or top-level
    ``efta_reference`` values (``decision_chain`` type).

    Parameters
    ----------
    result:
        The raw result dict from the submission body.

    Returns
    -------
    list[str]
        List of EFTA strings found in the result.  Empty if none found.
    """
    eftas: list[str] = []

    # verify_finding: result.citations[*].efta_number
    citations = result.get("citations")
    if isinstance(citations, list):
        for citation in citations:
            if isinstance(citation, dict):
                efta = citation.get("efta_number")
                if isinstance(efta, str) and efta.startswith("EFTA"):
                    eftas.append(efta)

    # decision_chain: result.communication_graph[*].efta_reference
    comm_graph = result.get("communication_graph")
    if isinstance(comm_graph, list):
        for edge in comm_graph:
            if isinstance(edge, dict):
                efta = edge.get("efta_reference")
                if isinstance(efta, str) and efta.startswith("EFTA"):
                    eftas.append(efta)

    return eftas


def _infer_unit_type(generator: WorkUnitGenerator, unit_id: str) -> str:
    """Infer the unit type from the generator's internal bookkeeping.

    Parameters
    ----------
    generator:
        The active generator instance.
    unit_id:
        The unit_id whose type to look up.

    Returns
    -------
    str
        ``"verify_finding"``, ``"decision_chain"``, or ``"unknown"``.
    """
    claim_record = generator._unit_to_claim.get(unit_id)
    if claim_record is not None:
        return "verify_finding"
    if unit_id in generator._unit_to_doc_keys:
        return "decision_chain"
    return "unknown"


def _count_findings_by_status(store: FindingsStore, status: str) -> int:
    """Count findings with the given status in the store.

    Parameters
    ----------
    store:
        The :class:`~sefi.store.findings.FindingsStore` to query.
    status:
        The status value to filter on (e.g. ``"accepted"``).

    Returns
    -------
    int
        Count of matching findings (non-negative).
    """
    try:
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM findings WHERE status = ?",
            (status,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 — db may not be initialised yet
        return 0


def _get_package_version() -> str:
    """Return the installed package version from ``importlib.metadata``.

    Falls back to ``"unknown"`` if the package is not installed (e.g. during
    development without ``pip install -e .``).

    Returns
    -------
    str
        Version string from ``pyproject.toml`` (e.g. ``"0.1.0"``).
    """
    try:
        return importlib.metadata.version("sefi-at-home")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _probe_findings_db(store: FindingsStore) -> bool:
    """Probe the findings database with a lightweight query.

    Parameters
    ----------
    store:
        The :class:`~sefi.store.findings.FindingsStore` to probe.

    Returns
    -------
    bool
        ``True`` if the database is reachable; ``False`` otherwise.
    """
    try:
        store._conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 — any error means unreachable
        return False
