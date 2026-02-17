# Config

**Module:** `sefi.config`
**Purpose:** Centralises all application configuration, reading runtime settings from environment variables with sensible defaults.

## Classes

### AppConfig
Application-wide configuration loaded from environment variables via `pydantic-settings`. All other modules must obtain configuration through this class rather than reading `os.environ` directly.

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| validate_log_level | v: str | str | Validates that `log_level` is one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Returns the uppercased value. Raises `ValueError` for unrecognised levels. |

**Attributes:**

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_dir` | `Path` | `Path("data")` | Directory containing rhowardstone JSON exports and other data files. Set via `DATA_DIR` env var. |
| `findings_db_path` | `Path` | `Path("data/findings.db")` | Path to the SQLite findings database. Set via `FINDINGS_DB_PATH` env var. |
| `log_level` | `str` | `"INFO"` | Logging verbosity. Set via `LOG_LEVEL` env var. Case-insensitive. |

## Functions

### get_config() -> AppConfig
Returns the application configuration resolved from environment variables and an optional `.env` file. Environment variable names are case-insensitive. Reads `.env` from the current working directory if present.

## Usage Example

```python
from sefi.config import get_config

config = get_config()
print(config.data_dir)          # Path('data')
print(config.findings_db_path)  # Path('data/findings.db')
print(config.log_level)         # 'INFO'
```
