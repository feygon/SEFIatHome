# Database Adapter

**Module:** `sefi.db.adapter`
**Purpose:** Provides the high-level read interface over the ingested rhowardstone JSON working tables stored in SQLite.

## Classes

### DatabaseAdapter
High-level read interface over SEFI@Home ingested working tables. Wraps `IngestManager` for data loading and exposes named query methods for entities, relationships, and persons.

All SQL queries use `?` parameterised placeholders. No ORM is used.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `load_json_export` | `file_path: Path \| str`, `table_name: str` | `int` | Load a rhowardstone JSON export file into a working table. Dispatches to the appropriate `IngestManager` method by `table_name`. Returns count of records loaded. Raises `FileNotFoundError` if the file is absent, `ValueError` for unsupported `table_name`. |
| `get_known_entities` | — | `list[dict[str, Any]]` | Return all entity records from the `entities` table, reconstructed from stored raw JSON blobs. Raises `sqlite3.OperationalError` if the `entities` table does not exist. |
| `get_known_relationships` | — | `list[dict[str, Any]]` | Return all relationship records from the `relationships` table, reconstructed from stored raw JSON blobs. Raises `sqlite3.OperationalError` if the table does not exist. |
| `get_persons_registry` | — | `list[dict[str, Any]]` | Return all records from the `persons` table, reconstructed from stored raw JSON blobs. Raises `sqlite3.OperationalError` if the table does not exist. |
| `paginated_query` | `sql: str`, `params: tuple`, `page_size: int`, `offset: int` | `tuple[list[dict], int]` | Post-MVP stub (FR-007). Always raises `NotImplementedError`. |
| `get_efta_range` | `dataset: int`, `start: int`, `end: int` | `list[dict[str, Any]]` | Post-MVP stub (FR-009). Always raises `NotImplementedError`. |
| `get_document_versions` | `efta_number: str` | `list[dict[str, Any]]` | Post-MVP stub (FR-010). Always raises `NotImplementedError`. |
| `get_redactions_for_document` | `efta_number: str` | `list[dict[str, Any]]` | Post-MVP stub (FR-011). Always raises `NotImplementedError`. |

**Supported `table_name` values for `load_json_export`:**

| `table_name` | Expected file |
|---|---|
| `persons` | `persons_registry.json` |
| `entities` | `knowledge_graph_entities.json` |
| `relationships` | `knowledge_graph_relationships.json` |
| `efta_mapping` | `efta_dataset_mapping.json` |

## Usage Example

```python
import sqlite3
from pathlib import Path
from sefi.db.adapter import DatabaseAdapter

conn = sqlite3.connect(":memory:")
adapter = DatabaseAdapter(conn)

adapter.load_json_export(Path("data/persons_registry.json"), "persons")
persons = adapter.get_persons_registry()
print(f"Loaded {len(persons)} persons")

adapter.load_json_export(Path("data/knowledge_graph_entities.json"), "entities")
entities = adapter.get_known_entities()
print(f"Loaded {len(entities)} entities")
```
