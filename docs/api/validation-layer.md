# Validation Layer

**Module:** `sefi.validation.layer`
**Purpose:** Enforces quality and ethical constraints on submitted worker results before they are written to the findings store, running PII scanning, provenance checking, and deduplication in a fixed non-bypassable order.

## Classes

### PIIMatch
Pydantic model representing a single PII pattern match found within a result's text.

| Attribute | Type | Description |
|-----------|------|-------------|
| `pattern_name` | `str` | Human-readable name of the matched pattern (e.g. `"ssn"`, `"phone"`, `"postal_address"`). |
| `matched_text` | `str` | The exact substring that triggered the match. |

### ResultSubmission
Pydantic model for a result submitted by a worker, used as input to `ValidationLayer.validate_result`.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `unit_id` | `str` | — | Identifier of the work unit being answered. |
| `worker_id` | `str` | — | Identifier of the submitting worker. |
| `result` | `dict[str, Any]` | — | Arbitrary result payload. |
| `cited_eftas` | `list[str]` | `[]` | List of EFTA document numbers cited in the result. |
| `unit_type` | `str` | `"unknown"` | The work unit type string. |

### ValidationResult
Pydantic model representing the outcome of `ValidationLayer.validate_result`.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `accepted` | `bool` | — | `True` if the result passed all checks and was stored as `status="accepted"`. |
| `quorum_status` | `str` | `"achieved"` | Always `"achieved"` for MVP (full N-of-M quorum is post-MVP). |
| `pii_detected` | `bool` | `False` | `True` if one or more PII patterns matched. |
| `errors` | `list[str]` | `[]` | Human-readable rejection reasons. |
| `finding_id` | `str \| None` | `None` | The `finding_id` assigned to the stored finding, or `None` if no finding was created. |

### ValidationLayer
Validates worker result submissions before accepting them to storage. Processing order is fixed: PII scan (short-circuits on any match, quarantines) -> provenance check -> deduplication check.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `validate_result` | `result: ResultSubmission` | `ValidationResult` | Run all three validation checks in order and persist the finding if accepted or quarantined. PII-detected results are stored with `status="quarantined"`. Clean results are stored with `status="accepted"`. Other failures produce no finding. |
| `scan_for_pii` | `text: str` | `list[PIIMatch]` | Scan text for PII patterns (SSN, US phone, postal address — MVP stub). All matches across all patterns are returned. Empty list means text is clean. |
| `verify_provenance` | `cited_eftas: list[str]` | `list[str]` | Check that all cited EFTA numbers exist in the `efta_mapping` or `entities` working tables. Returns a list of human-readable error messages for any unknown citations; empty list means all are valid. |
| `check_deduplication` | `unit_id: str` | `tuple[str \| None, str \| None]` | Check whether an accepted finding already exists for `unit_id`. Returns `(None, None)` if no duplicate exists; `(error_message, existing_finding_id)` if a duplicate is found. |

## Usage Example

```python
import sqlite3
from pathlib import Path
from sefi.db.adapter import DatabaseAdapter
from sefi.store.findings import FindingsStore
from sefi.validation.layer import ValidationLayer, ResultSubmission

conn = sqlite3.connect(":memory:")
adapter = DatabaseAdapter(conn)
store = FindingsStore(db_path=Path(":memory:"))
layer = ValidationLayer(db_adapter=adapter, findings_store=store)

submission = ResultSubmission(
    unit_id="verify-abc123",
    worker_id="worker-001",
    result={"verdict": "verified", "reasoning": "Document confirms the claim."},
    cited_eftas=["EFTA00039186"],
    unit_type="verify_finding",
)

outcome = layer.validate_result(submission)
print(outcome.accepted)     # True or False
print(outcome.finding_id)   # e.g. "finding-xyz789"
print(outcome.errors)       # [] if accepted
```
