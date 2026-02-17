# DB EFTA

**Module:** `sefi.db.efta`
**Purpose:** Constructs canonical DOJ PDF URLs for EFTA documents and resolves EFTA numbers to valid URLs using a gap-resolution algorithm that tries the primary dataset then adjacent datasets N-1 and N+1.

## Classes

### ResolutionResult
Pydantic model capturing the outcome of an EFTA gap-resolution attempt.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `found` | `bool` | — | `True` if the document was located in at least one dataset. |
| `url` | `str \| None` | `None` | The DOJ PDF URL where the document was found, or `None` if not found. |
| `dataset` | `int \| None` | `None` | The dataset number where the document was found, or `None` if not found. |
| `was_adjacent` | `bool` | `False` | `True` when found in N-1 or N+1 rather than the primary dataset. |
| `genuinely_missing` | `bool` | `False` | `True` when the document could not be found in any tried dataset. |

### EftaNumber
Pydantic model with a field validator enforcing the `^EFTA\d{8}$` format (e.g. `EFTA00039186`). Raises `ValueError` on instantiation if the value does not conform.

| Attribute | Type | Description |
|-----------|------|-------------|
| `value` | `str` | The validated EFTA format string. |

### EftaUrl
Pydantic model with a field validator enforcing the canonical DOJ PDF URL pattern `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf`, where `{N}` is 1–12. Raises `ValueError` if the URL does not match or the dataset number is out of range.

| Attribute | Type | Description |
|-----------|------|-------------|
| `value` | `str` | The validated URL string. |

## Functions

### build_url(efta_number: int, dataset: int) -> str
Construct the canonical DOJ PDF URL for an EFTA document. The URL format is exactly `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf` where `{N}` is `dataset` and `{XXXXXXXX}` is `efta_number` zero-padded to 8 digits.

### get_primary_dataset(efta_number: int, conn: sqlite3.Connection) -> int | None
Look up the primary dataset for `efta_number` in the `efta_mapping` SQLite table (populated by `IngestManager`). If multiple rows match (overlapping ranges), returns the one with the smallest `dataset_number`. Returns `None` if the EFTA number falls outside all known ranges.

### resolve_efta(efta_number: int, primary_dataset: int, check_url_exists: Callable[[str], bool]) -> ResolutionResult
Attempt to resolve an EFTA number to a valid DOJ PDF URL. Tries datasets in the order `[primary_dataset, primary_dataset - 1, primary_dataset + 1]`, skipping any outside the valid range 1–12. Returns a `ResolutionResult` on the first dataset where `check_url_exists` returns `True`. If no dataset yields a hit, returns a result with `found=False` and `genuinely_missing=True`. The `check_url_exists` callable is injectable so tests can avoid real HTTP calls.

## Usage Example

```python
import sqlite3
from sefi.db.efta import build_url, get_primary_dataset, resolve_efta

# Build a URL directly
url = build_url(39186, 9)
# 'https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf'

# Look up the primary dataset from the database
conn = sqlite3.connect("data/findings.db")
dataset = get_primary_dataset(39186, conn)

# Resolve with a real HTTP check (or stub for tests)
def check_exists(url: str) -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(url)
        return True
    except Exception:
        return False

result = resolve_efta(39186, dataset or 9, check_exists)
print(result.found, result.url, result.was_adjacent)
```
