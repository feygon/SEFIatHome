"""Pydantic models for the SEFI@Home Distribution API (Component 3).

All request and response bodies are defined here as Pydantic v2 ``BaseModel``
subclasses (NFR-003).  No raw dicts are used at API boundaries.

Models
------
- :class:`WorkUnitInput`   — the ``input`` sub-object of a work unit
- :class:`WorkUnitConstraints` — the ``constraints`` sub-object
- :class:`WorkUnitResponse` — ``GET /work`` response body (AC-001)
- :class:`ProvenanceInfo`  — provenance metadata inside a result submission
- :class:`ResultSubmission` — ``POST /result`` request body (AC-002)
- :class:`AcceptanceResponse` — ``POST /result`` response body (AC-003)
- :class:`StatusResponse`  — ``GET /status`` response body (AC-004)
- :class:`HealthResponse`  — ``GET /health`` response body (AC-005)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# GET /work — WorkUnitResponse  (AC-001)
# ---------------------------------------------------------------------------


class WorkUnitInput(BaseModel):
    """The ``input`` sub-object of a :class:`WorkUnitResponse`.

    Fields are a superset of the base schema to accommodate the special
    ``verify_finding`` and ``decision_chain`` extra fields required by AC-001.

    Attributes
    ----------
    database:
        Name of the source database for this work unit (e.g.
        ``"full_text_corpus.db"``).
    query:
        Optional SQL or search query string pre-materialised for the worker.
    context:
        Human-readable description of the data slice (e.g. dataset range).
    data:
        Pre-materialised data payload — a list of strings or dicts.
    claim:
        ``verify_finding`` only — the claim text to verify.
    cited_eftas:
        ``verify_finding`` only — EFTA numbers cited by the claim.
    efta_urls:
        ``verify_finding`` only — resolved DOJ PDF URLs matching
        ``cited_eftas`` in order and count.
    source_verified:
        ``verify_finding`` only — whether the source claim has been
        independently verified (EC-006).  Always ``False`` for rhowardstone
        report claims.
    time_window_start:
        ``decision_chain`` only — ISO 8601 start date of the 30-day window.
    time_window_end:
        ``decision_chain`` only — ISO 8601 end date of the 30-day window.
    """

    database: str = ""
    query: str | None = None
    context: str = ""
    data: list[Any] = Field(default_factory=list)

    # verify_finding extras
    claim: str | None = None
    cited_eftas: list[str] | None = None
    efta_urls: list[str] | None = None
    source_verified: bool | None = None

    # decision_chain extras
    time_window_start: str | None = None
    time_window_end: str | None = None

    model_config = {"extra": "allow"}


class WorkUnitConstraints(BaseModel):
    """Hard limits and flags passed to a worker alongside a work unit.

    Attributes
    ----------
    max_output_tokens:
        Maximum tokens the worker may use in its result.
    pii_filter:
        Whether the PII Guardian is applied to this unit's result.
    requires_quorum:
        Whether multiple independent submissions are required before the
        result is accepted.
    """

    max_output_tokens: int
    pii_filter: bool
    requires_quorum: bool

    model_config = {"extra": "allow"}


class WorkUnitResponse(BaseModel):
    """Response body for ``GET /work``.

    Mirrors the full :class:`~sefi.generator.units.WorkUnit` dataclass schema
    (AC-001).  When no unit is available the endpoint returns HTTP 200 with
    ``{"available": false}``; when a unit *is* available this model is
    populated and ``available`` is omitted (defaults to ``True``).

    Attributes
    ----------
    available:
        ``False`` when no work units are currently available.  Defaults to
        ``True`` — omitted from serialisation when a unit is present.
    unit_id:
        Unique identifier for this work unit.
    type:
        Work unit type string (e.g. ``"verify_finding"``).
    path:
        Research path number (1–5).
    difficulty:
        Difficulty label — ``"low"``, ``"medium"``, or ``"high"``.
    scaling:
        Scaling behaviour — ``"linear"``, ``"multiplying"``, ``"plateau"``,
        or ``"aggregation"``.
    optimal_batch:
        Human-readable recommended batch size description.
    input:
        Pre-materialised work payload.
    instructions:
        Natural-language task description (always includes de-anonymization
        prohibition per EC-007).
    constraints:
        Hard limits for the worker.
    deadline:
        ISO 8601 datetime after which the unit may be re-assigned.
    """

    available: bool = True
    unit_id: str | None = None
    type: str | None = None
    path: int | None = None
    difficulty: str | None = None
    scaling: str | None = None
    optimal_batch: str | None = None
    input: WorkUnitInput | None = None
    instructions: str | None = None
    constraints: WorkUnitConstraints | None = None
    deadline: str | None = None


# ---------------------------------------------------------------------------
# POST /result — ResultSubmission  (AC-002)
# ---------------------------------------------------------------------------


class ProvenanceInfo(BaseModel):
    """Provenance metadata attached to a ``POST /result`` submission.

    Attributes
    ----------
    model:
        Model identifier used by the worker (e.g. ``"claude-opus-4-5"`` or
        ``"human"``).
    timestamp:
        ISO 8601 datetime at which the worker completed the analysis.
    session_tokens_used:
        Non-negative integer count of tokens consumed in this session.
    """

    model: str
    timestamp: str
    session_tokens_used: int = Field(ge=0)


class ResultSubmission(BaseModel):
    """Request body for ``POST /result`` (AC-002).

    Attributes
    ----------
    unit_id:
        Identifier of the work unit being answered.  Must correspond to an
        existing unit that has been generated.
    worker_id:
        Non-empty identifier of the submitting worker.
    result:
        Arbitrary JSON-serialisable result payload.  Structure varies by
        unit type (see AC-002).
    provenance:
        Metadata about the model and session that produced this result.
    """

    unit_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    result: dict[str, Any]
    provenance: ProvenanceInfo


# ---------------------------------------------------------------------------
# POST /result — AcceptanceResponse  (AC-003)
# ---------------------------------------------------------------------------


class AcceptanceResponse(BaseModel):
    """Response body for ``POST /result`` (AC-003).

    Attributes
    ----------
    accepted:
        ``True`` if the result passed all validation checks and was stored.
    finding_id:
        The assigned finding identifier.  Present when ``accepted=True`` and
        also present on idempotent duplicate submission of an already-accepted
        unit (returning the existing id).
    quorum_status:
        One of ``"achieved"``, ``"pending"``, or ``"disputed"``.
    pii_detected:
        ``True`` if the PII Guardian matched any pattern in the result text.
    next_unit_available:
        ``True`` if at least one more work unit is immediately available.
    errors:
        Human-readable rejection reasons.  Empty list when ``accepted=True``.
    """

    accepted: bool
    finding_id: str | None = None
    quorum_status: str
    pii_detected: bool
    next_unit_available: bool
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# GET /status — StatusResponse  (AC-004)
# ---------------------------------------------------------------------------


class StatusResponse(BaseModel):
    """Response body for ``GET /status`` (AC-004).

    Attributes
    ----------
    total_units_generated:
        Count of work units ever generated.  Non-negative integer.
    total_units_assigned:
        Count of work units currently assigned to a worker.  Non-negative;
        ``<= total_units_generated``.
    total_units_completed:
        Count of work units that have been fully processed.  Non-negative;
        ``<= total_units_assigned``.
    total_findings_accepted:
        Count of findings with ``status="accepted"`` in the store.
    total_findings_quarantined:
        Count of findings with ``status="quarantined"`` in the store.
    coverage_by_type:
        Per-unit-type coverage percentage (0.0–100.0).
    """

    total_units_generated: int = Field(ge=0)
    total_units_assigned: int = Field(ge=0)
    total_units_completed: int = Field(ge=0)
    total_findings_accepted: int = Field(ge=0)
    total_findings_quarantined: int = Field(ge=0)
    coverage_by_type: dict[str, float]


# ---------------------------------------------------------------------------
# GET /health — HealthResponse  (AC-005)
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response body for ``GET /health`` (AC-005).

    Attributes
    ----------
    status:
        Always ``"ok"`` (HTTP 200).  If ``findings.db`` is unreachable, HTTP
        status is still 200 and ``findings_db_reachable`` is ``False``.
    version:
        Package version string sourced from ``pyproject.toml`` via
        ``importlib.metadata``.
    findings_db_reachable:
        ``True`` if the SQLite findings database responded successfully to a
        lightweight probe query; ``False`` otherwise.
    """

    status: str = "ok"
    version: str
    findings_db_reachable: bool
