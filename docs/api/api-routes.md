# API Routes

**Module:** `sefi.api.routes`
**Purpose:** Implements all four MVP FastAPI endpoints for the SEFI@Home Distribution API, with dependencies injected from application state.

## Functions

### get_work(generator) -> WorkUnitResponse
`GET /work` — Claim the next available work unit (FR-023, AC-001).

Returns a fully-populated `WorkUnitResponse` when a unit is available. When no units are available returns HTTP 200 with `{"available": false}`. Authentication and rate limiting are post-MVP stubs.

| Arg | Type | Description |
|-----|------|-------------|
| `generator` | `WorkUnitGenerator` | Injected via `Depends(_get_generator)` from `request.app.state.generator`. |

Returns `WorkUnitResponse`.

### post_result(body, generator, validation_layer) -> AcceptanceResponse
`POST /result` — Accept, validate, and store a worker's result submission (FR-024, AC-002, AC-003).

Processing flow:
1. Pydantic validates the request body (HTTP 422 on failure).
2. `unit_id` existence check — HTTP 404 if not known to the generator.
3. Idempotency check — if the `unit_id` already has an accepted finding, return the existing `finding_id` with `accepted=True`.
4. Full validation pipeline (PII scan, provenance check, deduplication).
5. If accepted, marks the unit complete in the generator.
6. Returns `AcceptanceResponse`.

| Arg | Type | Description |
|-----|------|-------------|
| `body` | `ResultSubmission` | Validated request body. |
| `generator` | `WorkUnitGenerator` | Injected via `Depends(_get_generator)`. |
| `validation_layer` | `ValidationLayer` | Injected via `Depends(_get_validation_layer)`. |

Returns `AcceptanceResponse`. Raises `HTTPException` with status 404 if `unit_id` is unknown.

### get_status(generator, findings_store) -> StatusResponse
`GET /status` — Retrieve project-wide statistics (FR-025, AC-004).

Returns aggregate counts across generated, assigned, and completed units, plus accepted and quarantined finding counts and per-type coverage percentages. All integer fields are guaranteed non-negative.

| Arg | Type | Description |
|-----|------|-------------|
| `generator` | `WorkUnitGenerator` | Injected via `Depends(_get_generator)`. |
| `findings_store` | `FindingsStore` | Injected via `Depends(_get_findings_store)`. |

Returns `StatusResponse`.

### get_health(findings_store) -> HealthResponse
`GET /health` — Liveness check (FR-026, AC-005).

Always returns HTTP 200. If `findings.db` is unreachable, `findings_db_reachable` is `False` but the status is still 200.

| Arg | Type | Description |
|-----|------|-------------|
| `findings_store` | `FindingsStore` | Injected via `Depends(_get_findings_store)`. |

Returns `HealthResponse`.

## Usage Example

```python
from fastapi.testclient import TestClient
from sefi.api.main import create_app
from unittest.mock import MagicMock
from sefi.generator.units import NoAvailableUnitsError

mock_gen = MagicMock()
mock_gen.generate_unit.side_effect = NoAvailableUnitsError()

app = create_app(generator=mock_gen, ...)
client = TestClient(app)

response = client.get("/work")
assert response.status_code == 200
assert response.json() == {"available": False}

response = client.get("/health")
assert response.json()["status"] == "ok"
```
