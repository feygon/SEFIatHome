# API Main

**Module:** `sefi.api.main`
**Purpose:** FastAPI application factory that instantiates and wires together all core components (`WorkUnitGenerator`, `ValidationLayer`, `FindingsStore`) and registers the API router.

## Functions

### create_app(generator, validation_layer, findings_store, findings_db_path, data_dir) -> FastAPI
Create and configure the SEFI@Home FastAPI application.

All three core components are injected via parameters. When a parameter is `None`, the factory builds a default instance using production paths. This design lets tests pass lightweight mocks without any filesystem or database setup.

When `generator` is `None` the factory also calls `ensure_data_files` to auto-download missing rhowardstone JSON exports on first run; network errors are logged as warnings but do not prevent startup.

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| `generator` | `WorkUnitGenerator \| None` | `None` | Pre-built generator; if `None`, built from data files in `data_dir`. |
| `validation_layer` | `ValidationLayer \| None` | `None` | Pre-built validation layer; if `None`, built sharing the findings store connection. |
| `findings_store` | `FindingsStore \| None` | `None` | Pre-built findings store; if `None`, opened at `findings_db_path`. |
| `findings_db_path` | `Path \| None` | `None` | Path to the SQLite findings database; defaults to `data/findings.db`. Ignored when `findings_store` is provided. |
| `data_dir` | `Path \| None` | `None` | Directory containing the rhowardstone JSON exports; defaults to `data/`. Ignored when `generator` is provided. |

Returns a fully-configured `FastAPI` instance with all routes registered and components attached to `app.state`.

**Module-level object:**

```
app: FastAPI = create_app()
```

This is the production application instance for use with uvicorn: `uvicorn sefi.api.main:app`.

## Usage Example

```python
# Production startup (via uvicorn CLI)
# uvicorn sefi.api.main:app --host 0.0.0.0 --port 8000

# Programmatic use with custom paths
from pathlib import Path
from sefi.api.main import create_app

app = create_app(
    findings_db_path=Path("/var/data/findings.db"),
    data_dir=Path("/var/data"),
)

# Testing — inject mocks to avoid disk/network I/O
from unittest.mock import MagicMock
from sefi.api.main import create_app
from fastapi.testclient import TestClient

mock_gen = MagicMock()
mock_vl = MagicMock()
mock_store = MagicMock()

app = create_app(
    generator=mock_gen,
    validation_layer=mock_vl,
    findings_store=mock_store,
)
client = TestClient(app)
response = client.get("/health")
assert response.status_code == 200
```
