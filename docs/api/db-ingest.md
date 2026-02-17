# DB Ingest

**Module:** `sefi.db.ingest`
**Purpose:** Loads the four rhowardstone JSON export files into SQLite working tables, with optional auto-download of missing files.

## Classes

### IngestResult
Pydantic model summarising the outcome of a completed ingest operation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `table_counts` | `dict[str, int]` | Mapping of working table name to number of records loaded. |

### IngestManager
Manages loading of rhowardstone JSON exports into SQLite working tables. Each call to `ingest_all` is idempotent: it drops and recreates all four working tables before inserting.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `ingest_all` | — | `dict[str, int]` | Load all four JSON export files into working tables. Validates that all files exist before writing anything. Returns a dict mapping table name to record count. Raises `FileNotFoundError` if any required file is missing. |
| `ingest_persons` | — | `int` | Load `persons_registry.json` into the `persons` table (drops and recreates). Returns record count. Raises `FileNotFoundError` if the file is absent. |
| `ingest_entities` | — | `int` | Load `knowledge_graph_entities.json` into the `entities` table (drops and recreates). Returns record count. Raises `FileNotFoundError` if the file is absent. |
| `ingest_relationships` | — | `int` | Load `knowledge_graph_relationships.json` into the `relationships` table (drops and recreates). Returns record count. Raises `FileNotFoundError` if the file is absent. |
| `ingest_efta_mapping` | — | `int` | Load `efta_dataset_mapping.json` into the `efta_mapping` table (drops and recreates). Handles both array and object top-level structure. Returns record count. Raises `FileNotFoundError` if the file is absent. |

## Functions

### ensure_data_files(data_dir: Path) -> list[str]
Download any missing rhowardstone JSON exports into `data_dir`. Each of the four required files is downloaded only if it does not already exist locally. Uses stdlib `urllib`; no extra dependencies required. Creates `data_dir` if absent.

Returns a list of filenames that were downloaded (empty if all already present). Raises `OSError` if a download fails.

## Usage Example

```python
import sqlite3
from pathlib import Path
from sefi.db.ingest import IngestManager, ensure_data_files

data_dir = Path("data")

# Download missing files first
downloaded = ensure_data_files(data_dir)
print(f"Downloaded: {downloaded}")

# Ingest into an in-memory SQLite database
conn = sqlite3.connect(":memory:")
manager = IngestManager(conn=conn, data_dir=data_dir)
counts = manager.ingest_all()
# {'persons': 1614, 'entities': 524, 'relationships': 2096, 'efta_mapping': 12}
print(counts)
```
