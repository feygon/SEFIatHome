"""Unit tests for US-001: Project Scaffolding.

Covers every acceptance criterion from todo/US-001.md plus key edge cases.
No live network calls are made; no real filesystem paths are required beyond
the package itself being importable.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _module_docstring(module_name: str) -> str | None:
    """Return the module-level docstring for an importable module."""
    mod = importlib.import_module(module_name)
    return mod.__doc__


# ---------------------------------------------------------------------------
# AC: pyproject.toml contains python_requires = ">=3.10"  (NFR-001)
# ---------------------------------------------------------------------------


class TestPyprojectToml:
    """Tests targeting pyproject.toml content requirements."""

    def test_pyproject_exists(self) -> None:
        """pyproject.toml must exist at the project root."""
        assert PYPROJECT.exists(), "pyproject.toml not found at project root"

    def test_python_requires_present(self) -> None:
        """pyproject.toml must declare python_requires = '>=3.10'."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert 'requires-python = ">=3.10"' in content, (
            "pyproject.toml missing requires-python = '>=3.10'"
        )

    def test_pytest_testpaths_configured(self) -> None:
        """[tool.pytest.ini_options] must point testpaths at 'tests'."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert 'testpaths = ["tests"]' in content, (
            "pyproject.toml missing testpaths = ['tests'] under [tool.pytest.ini_options]"
        )

    def test_mypy_strict_configured(self) -> None:
        """[tool.mypy] must enable strict = true."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "strict = true" in content, (
            "pyproject.toml missing strict = true under [tool.mypy]"
        )

    def test_no_orm_imports_in_pyproject(self) -> None:
        """pyproject.toml must not declare SQLAlchemy, Tortoise, or other ORMs."""
        content = PYPROJECT.read_text(encoding="utf-8").lower()
        forbidden = ["sqlalchemy", "tortoise", "peewee", "piccolo", "databases"]
        for lib in forbidden:
            assert lib not in content, f"ORM library '{lib}' found in pyproject.toml"


# ---------------------------------------------------------------------------
# AC: Python version is 3.10+ (NFR-001)
# ---------------------------------------------------------------------------


class TestPythonVersion:
    """Ensure the interpreter meets the minimum version requirement."""

    def test_python_version_at_least_3_10(self) -> None:
        """The running Python interpreter must be >= 3.10."""
        assert sys.version_info >= (3, 10), (
            f"Python 3.10+ required; running {sys.version}"
        )


# ---------------------------------------------------------------------------
# AC: All __init__.py files have module-level docstrings (NFR-008)
# ---------------------------------------------------------------------------


class TestModuleDocstrings:
    """All package __init__.py files must carry a module-level docstring."""

    MODULES = [
        "sefi",
        "sefi.db",
        "sefi.generator",
        "sefi.api",
        "sefi.validation",
        "sefi.store",
    ]

    @pytest.mark.parametrize("module_name", MODULES)
    def test_module_has_docstring(self, module_name: str) -> None:
        """Each subpackage __init__ must expose a non-empty module docstring."""
        doc = _module_docstring(module_name)
        assert doc and doc.strip(), (
            f"Module '{module_name}' is missing a module-level docstring"
        )


# ---------------------------------------------------------------------------
# AC: config.py has module-level docstring (NFR-008)
# ---------------------------------------------------------------------------


class TestConfigDocstring:
    """config.py and its public symbols must be documented."""

    def test_config_module_docstring(self) -> None:
        """sefi.config module must have a non-empty module docstring."""
        from sefi import config  # noqa: PLC0415

        assert config.__doc__ and config.__doc__.strip(), (
            "sefi.config is missing a module-level docstring"
        )

    def test_appconfig_class_docstring(self) -> None:
        """AppConfig class must have a docstring."""
        from sefi.config import AppConfig  # noqa: PLC0415

        assert AppConfig.__doc__ and AppConfig.__doc__.strip(), (
            "AppConfig class is missing a docstring"
        )

    def test_get_config_function_docstring(self) -> None:
        """get_config() must have a docstring."""
        from sefi.config import get_config  # noqa: PLC0415

        assert get_config.__doc__ and get_config.__doc__.strip(), (
            "get_config() is missing a docstring"
        )


# ---------------------------------------------------------------------------
# AC: AppConfig is a pydantic.BaseModel subclass (NFR-003)
# ---------------------------------------------------------------------------


class TestAppConfigIsPydantic:
    """AppConfig must derive from pydantic.BaseModel (directly or via BaseSettings)."""

    def test_appconfig_is_basemodel_subclass(self) -> None:
        """AppConfig must be a subclass of pydantic.BaseModel."""
        from sefi.config import AppConfig  # noqa: PLC0415

        assert issubclass(AppConfig, BaseModel), (
            "AppConfig does not inherit from pydantic.BaseModel"
        )


# ---------------------------------------------------------------------------
# AC: No ORM imports anywhere in scaffolding (NFR-004)
# ---------------------------------------------------------------------------


class TestNoOrmImports:
    """The scaffolding must not import any ORM library."""

    SOURCE_FILES = [
        SRC_ROOT / "sefi" / "__init__.py",
        SRC_ROOT / "sefi" / "config.py",
        SRC_ROOT / "sefi" / "db" / "__init__.py",
        SRC_ROOT / "sefi" / "generator" / "__init__.py",
        SRC_ROOT / "sefi" / "api" / "__init__.py",
        SRC_ROOT / "sefi" / "validation" / "__init__.py",
        SRC_ROOT / "sefi" / "store" / "__init__.py",
    ]

    FORBIDDEN_IMPORTS = [
        "sqlalchemy",
        "tortoise",
        "peewee",
        "piccolo",
        "databases",
    ]

    @pytest.mark.parametrize("src_file", SOURCE_FILES, ids=lambda p: p.name)
    def test_no_orm_in_file(self, src_file: Path) -> None:
        """Each source file must not import ORM libraries."""
        import re  # noqa: PLC0415

        content = src_file.read_text(encoding="utf-8")
        # Only flag actual import statements, not mentions in comments/docstrings
        import_lines = [
            line for line in content.splitlines()
            if re.match(r"^\s*(import|from)\s+", line)
        ]
        import_text = "\n".join(import_lines).lower()
        for lib in self.FORBIDDEN_IMPORTS:
            assert lib not in import_text, (
                f"ORM library '{lib}' imported in {src_file}"
            )

    def test_sefi_init_uses_no_orm(self) -> None:
        """sefi package root __init__.py must not reference sqlite3 for ORM usage."""
        import sefi  # noqa: PLC0415

        # sqlite3 is allowed; ORM wrappers are not
        assert "sqlalchemy" not in (sefi.__doc__ or "").lower()


# ---------------------------------------------------------------------------
# AC: get_config() reads env vars with sensible defaults
# ---------------------------------------------------------------------------


class TestGetConfig:
    """Tests for get_config() environment variable handling."""

    def test_defaults_without_env(self) -> None:
        """get_config() must return defaults when no env vars are set."""
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DATA_DIR", "FINDINGS_DB_PATH", "LOG_LEVEL")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            from sefi.config import AppConfig  # noqa: PLC0415

            cfg = AppConfig()
        assert cfg.data_dir == Path("data")
        assert cfg.findings_db_path == Path("data/findings.db")
        assert cfg.log_level == "INFO"

    def test_data_dir_from_env(self) -> None:
        """DATA_DIR env var must override data_dir default."""
        with patch.dict(os.environ, {"DATA_DIR": "/tmp/mydata"}, clear=False):
            from sefi.config import AppConfig  # noqa: PLC0415

            cfg = AppConfig()
        assert cfg.data_dir == Path("/tmp/mydata")

    def test_findings_db_path_from_env(self) -> None:
        """FINDINGS_DB_PATH env var must override findings_db_path default."""
        with patch.dict(
            os.environ, {"FINDINGS_DB_PATH": "/tmp/test.db"}, clear=False
        ):
            from sefi.config import AppConfig  # noqa: PLC0415

            cfg = AppConfig()
        assert cfg.findings_db_path == Path("/tmp/test.db")

    def test_log_level_from_env(self) -> None:
        """LOG_LEVEL env var must override log_level default."""
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=False):
            from sefi.config import AppConfig  # noqa: PLC0415

            cfg = AppConfig()
        assert cfg.log_level == "DEBUG"

    def test_log_level_case_insensitive(self) -> None:
        """LOG_LEVEL must be normalised to uppercase."""
        with patch.dict(os.environ, {"LOG_LEVEL": "warning"}, clear=False):
            from sefi.config import AppConfig  # noqa: PLC0415

            cfg = AppConfig()
        assert cfg.log_level == "WARNING"

    def test_invalid_log_level_raises(self) -> None:
        """An invalid LOG_LEVEL must raise a validation error."""
        from pydantic import ValidationError  # noqa: PLC0415

        from sefi.config import AppConfig  # noqa: PLC0415

        with patch.dict(os.environ, {"LOG_LEVEL": "VERBOSE"}, clear=False):
            with pytest.raises(ValidationError):
                AppConfig()

    def test_get_config_returns_appconfig(self) -> None:
        """get_config() must return an AppConfig instance."""
        from sefi.config import AppConfig, get_config  # noqa: PLC0415

        cfg = get_config()
        assert isinstance(cfg, AppConfig)


# ---------------------------------------------------------------------------
# AC: sefi package exposes __version__ constant
# ---------------------------------------------------------------------------


class TestPackageVersion:
    """The sefi package root must expose a __version__ string."""

    def test_version_is_string(self) -> None:
        """sefi.__version__ must be a non-empty string."""
        import sefi  # noqa: PLC0415

        assert isinstance(sefi.__version__, str) and sefi.__version__, (
            "sefi.__version__ is missing or empty"
        )

    def test_version_semver_format(self) -> None:
        """sefi.__version__ should follow major.minor.patch format."""
        import sefi  # noqa: PLC0415

        parts = sefi.__version__.split(".")
        assert len(parts) == 3, (
            f"sefi.__version__ '{sefi.__version__}' is not in X.Y.Z format"
        )
        for part in parts:
            assert part.isdigit(), (
                f"sefi.__version__ part '{part}' is not numeric"
            )


# ---------------------------------------------------------------------------
# AC: pytest runs without configuration errors (NFR-005) — meta test
# ---------------------------------------------------------------------------


class TestPytestCanDiscover:
    """The test suite itself is discoverable and runnable — proven by execution."""

    def test_tests_init_exists(self) -> None:
        """tests/__init__.py must exist for package-style test discovery."""
        assert (PROJECT_ROOT / "tests" / "__init__.py").exists()

    def test_unit_init_exists(self) -> None:
        """tests/unit/__init__.py must exist."""
        assert (PROJECT_ROOT / "tests" / "unit" / "__init__.py").exists()

    def test_integration_init_exists(self) -> None:
        """tests/integration/__init__.py must exist."""
        assert (PROJECT_ROOT / "tests" / "integration" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# AC: sqlite3 is the only DB library (NFR-004) — positive check
# ---------------------------------------------------------------------------


class TestSqlite3Available:
    """sqlite3 (stdlib) must be importable; no ORM wrapper required."""

    def test_sqlite3_importable(self) -> None:
        """stdlib sqlite3 must be importable in the current environment."""
        import sqlite3 as _sqlite3  # noqa: PLC0415

        assert _sqlite3.sqlite_version, "sqlite3 module loaded but reports no version"

    def test_in_memory_sqlite_works(self) -> None:
        """An in-memory SQLite connection must open and close cleanly."""
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        cur.execute("INSERT INTO t (val) VALUES (?)", ("hello",))
        conn.commit()
        row = cur.execute("SELECT val FROM t WHERE id = 1").fetchone()
        assert row == ("hello",)
        conn.close()
