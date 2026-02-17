# Generator Units

**Module:** `sefi.generator.units`
**Purpose:** Defines the `WorkUnit` dataclass and `WorkUnitGenerator` class that produce `verify_finding` and `decision_chain` work units with in-memory assignment tracking.

## Classes

### NoAvailableUnitsError
Custom `RuntimeError` raised when no eligible work unit can be generated. For `verify_finding`: all claims are currently assigned or completed. For `decision_chain`: no 30-day time window has the minimum number (20) of unassigned document references.

### WorkUnit
A dataclass representing a self-contained unit of analytical work for a SEFI@Home volunteer. Validation is performed in `__post_init__`.

**Two unit types are defined:**

- `verify_finding` — contains a single claim with cited EFTA numbers and resolved DOJ PDF URLs. Path 5, difficulty `low`, scaling `linear`.
- `decision_chain` — contains 20–50 document references from a single 30-day time window. Path 3, difficulty `high`, scaling `multiplying`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `unit_id` | `str` | Unique identifier (`"verify-{hex12}"` or `"dc-{hex12}"`). |
| `type` | `str` | `"verify_finding"` or `"decision_chain"`. |
| `path` | `int` | Research path number (1–5). |
| `difficulty` | `str` | `"low"`, `"medium"`, or `"high"`. |
| `scaling` | `str` | `"linear"`, `"multiplying"`, `"plateau"`, or `"aggregation"`. |
| `optimal_batch` | `str` | Human-readable recommended batch size. |
| `input` | `dict[str, Any]` | Work payload (type-specific keys). |
| `instructions` | `str` | Natural-language task description; always includes the de-anonymization prohibition (EC-007). |
| `constraints` | `dict[str, Any]` | Hard limits: `max_output_tokens`, `pii_filter`, `requires_quorum`. |
| `deadline` | `str` | ISO 8601 datetime after which the unit may be re-assigned. |
| `source_verified` | `bool` | Always `False` for rhowardstone report claims (EC-006). |

### WorkUnitGenerator
Generates `verify_finding` and `decision_chain` work units. Tracks assignment state in memory.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `generate_unit` | `unit_type: str = "verify_finding"` | `WorkUnit` | Generate and return the next available work unit for the requested type. Raises `NoAvailableUnitsError` if none are available; `ValueError` for unrecognised `unit_type`. |
| `mark_unit_assigned` | `unit_id: str`, `worker_id: str` | `None` | Record that a worker has claimed a specific work unit. Raises `KeyError` if `unit_id` was never generated; `ValueError` if already assigned or completed. |
| `mark_unit_complete` | `unit_id: str` | `None` | Mark a work unit as fully processed. Releases assignment slot and, for `decision_chain` units, releases consumed document keys back to the available pool. Raises `KeyError` if `unit_id` was never generated. |
| `get_status` | — | `dict[str, int]` | Return a summary dict with keys `total_claims`, `total_relationships`, `total_generated`, `total_assigned`, `total_completed`. |

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `claims` | `list \| None` | `None` | Pre-loaded claim dicts (takes precedence over `claims_path`). |
| `claims_path` | `Path \| str \| None` | `None` | Path to JSON claims file; defaults to `data/sample_claims.json`. |
| `relationships` | `list \| None` | `None` | Pre-loaded relationship dicts (takes precedence over `relationships_path`). |
| `relationships_path` | `Path \| str \| None` | `None` | Path to JSON relationships file; defaults to `data/knowledge_graph_relationships.json`. |
| `url_builder` | `callable \| None` | `None` | Callable `(efta_int, dataset) -> str` for DOJ URL construction; defaults to `sefi.db.efta.build_url`. |

## Usage Example

```python
from sefi.generator.units import WorkUnitGenerator, NoAvailableUnitsError

generator = WorkUnitGenerator(
    claims=[
        {
            "claim_id": "c001",
            "claim": "Subject A met Subject B on date X.",
            "cited_eftas": ["EFTA00039186"],
            "primary_datasets": [9],
            "source_verified": False,
        }
    ]
)

try:
    unit = generator.generate_unit("verify_finding")
    print(unit.unit_id, unit.type)
    generator.mark_unit_assigned(unit.unit_id, "worker-abc")
    # ... worker processes the unit ...
    generator.mark_unit_complete(unit.unit_id)
except NoAvailableUnitsError:
    print("No units available right now.")

print(generator.get_status())
```
