# Store Findings

**Module:** `sefi.store.findings`
**Purpose:** Provides SQLite-backed persistence for SEFI@Home analysis results, including idempotent storage, citation management, filtered export, and coverage statistics.

## Classes

### Finding
Pydantic model representing a single analysis result submitted by a worker.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `finding_id` | `str` | — | Unique identifier (e.g. `"finding-abc123"`). |
| `unit_id` | `str` | — | The work unit this finding is associated with. |
| `unit_type` | `str` | — | Work unit type (e.g. `"verify_finding"`). |
| `worker_id` | `str` | — | Identifier of the submitting worker. |
| `submitted_at` | `str` | — | ISO 8601 submission datetime. |
| `validated_at` | `str \| None` | `None` | ISO 8601 validation datetime; `None` if not yet validated. |
| `status` | `str` | `"pending"` | One of `"pending"`, `"accepted"`, `"disputed"`, `"quarantined"`. Validated by field validator. |
| `result_json` | `str` | — | JSON-serialised result payload. |
| `quorum_count` | `int` | `1` | Number of agreeing submissions. |
| `citations` | `list[Citation]` | `[]` | Citation objects linked to this finding. |

### Citation
Pydantic model representing a single EFTA document citation linked to a finding.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `citation_id` | `str` | — | Unique identifier for this citation row. |
| `finding_id` | `str` | — | The finding this citation is attached to. |
| `efta_number` | `str` | — | EFTA document identifier matching `^EFTA\d{8}$` (DR-011). Validated by field validator; raises `ValueError` on mismatch. |
| `page_number` | `int \| None` | `None` | Optional page number within the document. |
| `quote` | `str \| None` | `None` | Optional verbatim supporting quote. |

### CoverageStats
Pydantic model reporting coverage statistics for a given work unit type.

| Attribute | Type | Description |
|-----------|------|-------------|
| `unit_type` | `str` | The work unit type these stats apply to. |
| `units_completed` | `int` | Number of work units with at least one accepted finding. |
| `units_total` | `int` | Total number of work units of this type ever stored. |
| `percent` | `float` | Coverage percentage (0.0–100.0). |

### FindingsStore
Persistent SQLite storage for validated SEFI@Home analysis results. On initialisation the database schema is created if it does not exist.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `store_finding` | `finding: Finding` | `str` | Persist a finding to the database. Idempotent: returns existing `finding_id` without error if already stored. Also inserts citation rows (idempotent via `INSERT OR IGNORE`). Raises `ValueError` if any citation's `efta_number` is invalid. |
| `get_findings_for_document` | `efta_number: str` | `list[Finding]` | Return all findings that cite the given EFTA document. Raises `ValueError` if `efta_number` does not match `^EFTA\d{8}$`. |
| `export_findings` | `format: str`, `filters: dict[str, Any]` | `bytes` | Export findings as JSON (`{"license": "CC0-1.0", "findings": [...]}`) or CSV bytes. Supported filter keys: `status`, `unit_type`, `worker_id`. Raises `ValueError` for unsupported format. |
| `get_coverage` | `unit_type: str` | `CoverageStats` | Return coverage statistics for the given work unit type. `units_completed` counts `status="accepted"` rows; `units_total` counts all rows of that type. |

## Usage Example

```python
from pathlib import Path
from sefi.store.findings import FindingsStore, Finding, Citation

store = FindingsStore(db_path=Path(":memory:"))

finding = Finding(
    finding_id="finding-abc123",
    unit_id="verify-def456",
    unit_type="verify_finding",
    worker_id="worker-001",
    submitted_at="2025-01-01T12:00:00+00:00",
    status="accepted",
    result_json='{"verdict": "verified"}',
    citations=[
        Citation(
            citation_id="cite-001",
            finding_id="finding-abc123",
            efta_number="EFTA00039186",
            page_number=3,
        )
    ],
)

fid = store.store_finding(finding)
print(fid)  # "finding-abc123"

json_bytes = store.export_findings("json", {"status": "accepted"})
stats = store.get_coverage("verify_finding")
print(stats.percent)  # 100.0
```
