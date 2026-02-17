"""FastAPI application factory for the SEFI@Home Distribution API.

Exposes a :func:`create_app` factory function that instantiates the
:class:`fastapi.FastAPI` application, wires up the dependency-injected
components (:class:`~sefi.generator.units.WorkUnitGenerator`,
:class:`~sefi.validation.layer.ValidationLayer`,
:class:`~sefi.store.findings.FindingsStore`), and registers the API router
defined in :mod:`sefi.api.routes`.

Usage::

    # Production startup (uvicorn)
    uvicorn sefi.api.main:app --host 0.0.0.0 --port 8000

    # Testing — pass mock dependencies
    from sefi.api.main import create_app
    app = create_app(generator=mock_gen, validation_layer=mock_vl,
                     findings_store=mock_store)

The production ``app`` object is created by calling :func:`create_app` with
defaults sourced from :mod:`sefi.config`.  Components are attached to
``app.state`` so that FastAPI route handlers can retrieve them via
``request.app.state``.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import FastAPI

from sefi.api.routes import router
from sefi.db.adapter import DatabaseAdapter
from sefi.generator.units import WorkUnitGenerator
from sefi.store.findings import FindingsStore
from sefi.validation.layer import ValidationLayer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    generator: WorkUnitGenerator | None = None,
    validation_layer: ValidationLayer | None = None,
    findings_store: FindingsStore | None = None,
    findings_db_path: Path | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the SEFI@Home FastAPI application.

    All three core components — :class:`~sefi.generator.units.WorkUnitGenerator`,
    :class:`~sefi.validation.layer.ValidationLayer`, and
    :class:`~sefi.store.findings.FindingsStore` — are injected via parameters.
    When a parameter is ``None`` the factory builds a default instance using
    production paths.

    This design means tests can pass lightweight mocks without any filesystem
    or database setup.

    Parameters
    ----------
    generator:
        Pre-built :class:`~sefi.generator.units.WorkUnitGenerator`.  If
        ``None``, a default is constructed using the data files in
        *data_dir*.
    validation_layer:
        Pre-built :class:`~sefi.validation.layer.ValidationLayer`.  If
        ``None``, a default is constructed sharing the findings store's
        SQLite connection.
    findings_store:
        Pre-built :class:`~sefi.store.findings.FindingsStore`.  If ``None``,
        a default is opened at *findings_db_path*.
    findings_db_path:
        Path to the SQLite findings database.  Defaults to
        ``data/findings.db`` relative to the current working directory.
        Ignored when *findings_store* is provided.
    data_dir:
        Directory containing the rhowardstone JSON exports.  Defaults to
        ``data/`` relative to the current working directory.  Ignored when
        *generator* is provided.

    Returns
    -------
    FastAPI
        A fully-configured application instance with all routes registered
        and dependencies attached to ``app.state``.
    """
    app = FastAPI(
        title="SEFI@Home Distribution API",
        description=(
            "Distributes analytical work units to volunteer workers "
            "and collects structured findings about the DOJ Epstein Files."
        ),
        version=_get_version(),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---- resolve data directory ----
    resolved_data_dir = data_dir if data_dir is not None else Path("data")

    # ---- FindingsStore ----
    if findings_store is None:
        if findings_db_path is None:
            findings_db_path = resolved_data_dir / "findings.db"
        findings_store = FindingsStore(db_path=findings_db_path)
        logger.info("FindingsStore initialised at %s", findings_db_path)

    # ---- DatabaseAdapter (shared SQLite connection for validation lookups) ----
    db_adapter = _build_db_adapter(resolved_data_dir)

    # ---- WorkUnitGenerator ----
    if generator is None:
        generator = _build_generator(resolved_data_dir)
        logger.info("WorkUnitGenerator initialised from %s", resolved_data_dir)

    # ---- ValidationLayer ----
    if validation_layer is None:
        validation_layer = ValidationLayer(
            db_adapter=db_adapter,
            findings_store=findings_store,
        )
        logger.info("ValidationLayer initialised")

    # ---- Attach to app.state ----
    app.state.generator = generator
    app.state.validation_layer = validation_layer
    app.state.findings_store = findings_store

    # ---- Register routes ----
    app.include_router(router)

    return app


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Return the installed package version.

    Falls back to ``"unknown"`` if the package is not installed.

    Returns
    -------
    str
        Version string from ``pyproject.toml``.
    """
    import importlib.metadata  # local import keeps module-level imports clean

    try:
        return importlib.metadata.version("sefi-at-home")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _build_db_adapter(data_dir: Path) -> DatabaseAdapter:
    """Build a :class:`~sefi.db.adapter.DatabaseAdapter` over an in-memory SQLite DB.

    The adapter is used by the :class:`~sefi.validation.layer.ValidationLayer`
    for EFTA provenance lookups.  For MVP a fresh in-memory connection is
    created and the JSON exports in *data_dir* are ingested if present.

    Parameters
    ----------
    data_dir:
        Directory containing the rhowardstone JSON export files.

    Returns
    -------
    DatabaseAdapter
        An adapter ready for provenance queries.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    adapter = DatabaseAdapter(conn)

    # Ingest available JSON exports into working tables
    _try_ingest(adapter, data_dir / "knowledge_graph_entities.json", "entities")
    _try_ingest(adapter, data_dir / "efta_dataset_mapping.json", "efta_mapping")

    return adapter


def _try_ingest(adapter: DatabaseAdapter, path: Path, table_name: str) -> None:
    """Attempt to ingest a JSON export file; log a warning if absent.

    Parameters
    ----------
    adapter:
        The :class:`~sefi.db.adapter.DatabaseAdapter` to load data into.
    path:
        Full filesystem path to the JSON export file.
    table_name:
        Target SQLite working table name.
    """
    if not path.exists():
        logger.warning(
            "JSON export not found — skipping ingest: %s (table: %s)",
            path,
            table_name,
        )
        return
    try:
        count = adapter.load_json_export(path, table_name)
        logger.info("Ingested %d records from %s into table '%s'", count, path, table_name)
    except Exception as exc:  # noqa: BLE001 — log and continue; provenance checks degrade gracefully
        logger.warning("Failed to ingest %s: %s", path, exc)


def _build_generator(data_dir: Path) -> WorkUnitGenerator:
    """Build the default :class:`~sefi.generator.units.WorkUnitGenerator`.

    Uses ``data/sample_claims.json`` for ``verify_finding`` units and
    ``data/knowledge_graph_relationships.json`` for ``decision_chain`` units.
    Both paths are relative to *data_dir*.  Missing files cause the generator
    to start with empty lists (which raises :exc:`~sefi.generator.units.NoAvailableUnitsError`
    when a unit is requested).

    Parameters
    ----------
    data_dir:
        Directory containing the work unit source data files.

    Returns
    -------
    WorkUnitGenerator
        A generator ready to produce work units.
    """
    claims_path = data_dir / "sample_claims.json"
    relationships_path = data_dir / "knowledge_graph_relationships.json"

    return WorkUnitGenerator(
        claims_path=claims_path if claims_path.exists() else None,
        relationships_path=relationships_path if relationships_path.exists() else None,
    )


# ---------------------------------------------------------------------------
# Production application instance
# ---------------------------------------------------------------------------

#: Module-level application object for production use with uvicorn:
#:
#:   uvicorn sefi.api.main:app --host 0.0.0.0 --port 8000
app: FastAPI = create_app()
