"""Application configuration for SEFI@Home.

Reads runtime settings from environment variables with sensible defaults.
All configuration is centralised here; no other module reads os.environ directly.
"""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """Application-wide configuration loaded from environment variables.

    Attributes:
        data_dir: Directory containing rhowardstone JSON exports and other data files.
        findings_db_path: Path to the SQLite findings database.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """

    data_dir: Path = Path("data")
    findings_db_path: Path = Path("data/findings.db")
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that log_level is one of the accepted Python logging levels.

        Args:
            v: The raw log level string from the environment.

        Returns:
            The uppercased log level string if valid.

        Raises:
            ValueError: If the value is not a recognised logging level.
        """
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}; got {v!r}")
        return upper


def get_config() -> AppConfig:
    """Return the application configuration, resolved from environment variables.

    Environment variables read (case-insensitive):
        DATA_DIR: Path to the data directory (default: ``data/``).
        FINDINGS_DB_PATH: Path to the findings SQLite database (default: ``data/findings.db``).
        LOG_LEVEL: Logging verbosity level (default: ``INFO``).

    Returns:
        An :class:`AppConfig` instance populated from the environment.
    """
    return AppConfig(
        _env_file=".env",
        _env_file_encoding="utf-8",
    )
