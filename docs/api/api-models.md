# API Models

**Module:** `sefi.api.models`
**Purpose:** Defines all Pydantic v2 request and response body models for the SEFI@Home Distribution API endpoints.

## Classes

### WorkUnitInput
The `input` sub-object of a `WorkUnitResponse`. Fields are a superset to accommodate both `verify_finding` and `decision_chain` extra fields. Extra fields are allowed via `model_config`.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `database` | `str` | `""` | Name of the source database for this work unit. |
| `query` | `str \| None` | `None` | Optional SQL or search query string pre-materialised for the worker. |
| `context` | `str` | `""` | Human-readable description of the data slice. |
| `data` | `list[Any]` | `[]` | Pre-materialised data payload. |
| `claim` | `str \| None` | `None` | `verify_finding` only — the claim text to verify. |
| `cited_eftas` | `list[str] \| None` | `None` | `verify_finding` only — EFTA numbers cited by the claim. |
| `efta_urls` | `list[str] \| None` | `None` | `verify_finding` only — resolved DOJ PDF URLs. |
| `source_verified` | `bool \| None` | `None` | `verify_finding` only — whether the source claim has been independently verified. |
| `time_window_start` | `str \| None` | `None` | `decision_chain` only — ISO 8601 start date of the 30-day window. |
| `time_window_end` | `str \| None` | `None` | `decision_chain` only — ISO 8601 end date of the 30-day window. |

### WorkUnitConstraints
Hard limits and flags passed to a worker alongside a work unit. Extra fields are allowed via `model_config`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `max_output_tokens` | `int` | Maximum tokens the worker may use in its result. |
| `pii_filter` | `bool` | Whether the PII Guardian is applied to this unit's result. |
| `requires_quorum` | `bool` | Whether multiple independent submissions are required before the result is accepted. |

### WorkUnitResponse
Response body for `GET /work` (AC-001). When no unit is available, returns `{"available": false}`.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `available` | `bool` | `True` | `False` when no work units are currently available. |
| `unit_id` | `str \| None` | `None` | Unique identifier for this work unit. |
| `type` | `str \| None` | `None` | Work unit type string. |
| `path` | `int \| None` | `None` | Research path number (1–5). |
| `difficulty` | `str \| None` | `None` | Difficulty label. |
| `scaling` | `str \| None` | `None` | Scaling behaviour string. |
| `optimal_batch` | `str \| None` | `None` | Human-readable recommended batch size description. |
| `input` | `WorkUnitInput \| None` | `None` | Pre-materialised work payload. |
| `instructions` | `str \| None` | `None` | Natural-language task description including de-anonymization prohibition. |
| `constraints` | `WorkUnitConstraints \| None` | `None` | Hard limits for the worker. |
| `deadline` | `str \| None` | `None` | ISO 8601 datetime after which the unit may be re-assigned. |

### ProvenanceInfo
Provenance metadata attached to a `POST /result` submission.

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `str` | Model identifier used by the worker (e.g. `"claude-opus-4-5"` or `"human"`). |
| `timestamp` | `str` | ISO 8601 datetime at which the worker completed the analysis. |
| `session_tokens_used` | `int` | Non-negative count of tokens consumed in this session. |

### ResultSubmission
Request body for `POST /result` (AC-002).

| Attribute | Type | Description |
|-----------|------|-------------|
| `unit_id` | `str` | Identifier of the work unit being answered (min length 1). |
| `worker_id` | `str` | Non-empty identifier of the submitting worker (min length 1). |
| `result` | `dict[str, Any]` | Arbitrary JSON-serialisable result payload. |
| `provenance` | `ProvenanceInfo` | Metadata about the model and session that produced this result. |

### AcceptanceResponse
Response body for `POST /result` (AC-003).

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `accepted` | `bool` | — | `True` if the result passed all validation checks and was stored. |
| `finding_id` | `str \| None` | `None` | The assigned finding identifier. Present when `accepted=True` and on idempotent re-submission. |
| `quorum_status` | `str` | — | One of `"achieved"`, `"pending"`, or `"disputed"`. |
| `pii_detected` | `bool` | — | `True` if the PII Guardian matched any pattern in the result text. |
| `next_unit_available` | `bool` | — | `True` if at least one more work unit is immediately available. |
| `errors` | `list[str]` | `[]` | Human-readable rejection reasons. |

### StatusResponse
Response body for `GET /status` (AC-004).

| Attribute | Type | Description |
|-----------|------|-------------|
| `total_units_generated` | `int` | Count of work units ever generated (non-negative). |
| `total_units_assigned` | `int` | Count of work units currently assigned to a worker. |
| `total_units_completed` | `int` | Count of work units fully processed. |
| `total_findings_accepted` | `int` | Count of findings with `status="accepted"`. |
| `total_findings_quarantined` | `int` | Count of findings with `status="quarantined"`. |
| `coverage_by_type` | `dict[str, float]` | Per-unit-type coverage percentage (0.0–100.0). |

### HealthResponse
Response body for `GET /health` (AC-005).

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `str` | `"ok"` | Always `"ok"` (HTTP 200). |
| `version` | `str` | — | Package version string from `pyproject.toml`. |
| `findings_db_reachable` | `bool` | — | `True` if the SQLite findings database responded to a probe query. |

## Usage Example

```python
from sefi.api.models import ResultSubmission, ProvenanceInfo

submission = ResultSubmission(
    unit_id="verify-abc123",
    worker_id="worker-001",
    result={"verdict": "verified", "reasoning": "The document confirms the claim."},
    provenance=ProvenanceInfo(
        model="claude-opus-4-5",
        timestamp="2025-01-01T12:00:00+00:00",
        session_tokens_used=1500,
    ),
)
print(submission.model_dump_json())
```
