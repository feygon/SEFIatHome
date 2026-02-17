"""FindingsStore: SQLite-backed persistence for SEFI@Home analysis results.

This module implements the :class:`FindingsStore` class and the Pydantic
models :class:`Finding` and :class:`CoverageStats` that cross module
boundaries.

Schema overview (findings.db)
------------------------------
- ``findings``  — accepted/pending/disputed/quarantined analysis results.
- ``citations`` — EFTA document citations linked to each finding.
- ``work_units`` — minimal stub table; exists only to satisfy the FOREIGN KEY
  constraint on ``findings.unit_id``.  Populated externally by the Work Unit
  Generator; this module never writes to it directly.

Design notes
-------------
- :meth:`FindingsStore.__init__` accepts a ``db_path: Path``.  Pass
  ``Path(":memory:")`` or a temp-dir path in tests.
- :meth:`FindingsStore.store_finding` is idempotent: if ``finding_id`` already
  exists, the existing row is returned without error (supports POST /result
  idempotency per AC-003 resolution note).
- All SQL uses parameterised ``?`` placeholders (NFR-004).
- ``PRAGMA foreign_keys = OFF`` is set for MVP because the ``work_units`` stub
  table is not guaranteed to be pre-populated in all test scenarios.  A comment
  in :meth:`_init_schema` explains the rationale.
- EFTA number strings are validated against ``^EFTA\\d{8}$`` before any insert
  into the ``citations`` table (DR-011).
- JSON export wraps findings in ``{"license": "CC0-1.0", "findings": [...]}``
  (EC-004).
- CSV export uses ``csv.DictWriter`` with ``extrasaction="ignore"``; all
  accepted findings are included when no filters are applied.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Regex pattern that EFTA number strings must match (DR-011).
_EFTA_PATTERN: re.Pattern[str] = re.compile(r"^EFTA\d{8}$")

#: Allowed status values for the ``findings.status`` column (DR-007).
_VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "accepted", "disputed", "quarantined"}
)

#: CC0 license identifier included in all JSON exports (EC-004).
_LICENSE: str = "CC0-1.0"

#: Column names for the findings table (used for CSV export ordering).
_FINDINGS_COLUMNS: tuple[str, ...] = (
    "finding_id",
    "unit_id",
    "unit_type",
    "worker_id",
    "submitted_at",
    "validated_at",
    "status",
    "result_json",
    "quorum_count",
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A single analysis result submitted by a worker.

    All fields cross module boundaries (e.g., API → Findings Store) and are
    therefore defined as a Pydantic v2 ``BaseModel``.

    Attributes
    ----------
    finding_id:
        Unique identifier for this finding (e.g. ``"finding-abc123"``).
    unit_id:
        The work unit this finding is associated with.
    unit_type:
        The work unit type (e.g. ``"verify_finding"``).
    worker_id:
        Identifier of the worker that submitted the result.
    submitted_at:
        ISO 8601 datetime string at which the result was submitted.
    validated_at:
        ISO 8601 datetime string at which the result was validated, or
        ``None`` if not yet validated.
    status:
        One of ``"pending"``, ``"accepted"``, ``"disputed"``,
        ``"quarantined"``.
    result_json:
        JSON-serialised string of the worker's result payload.
    quorum_count:
        Number of agreeing submissions for this finding (default 1).
    citations:
        List of :class:`Citation` objects linked to this finding.  May be
        empty if no citations are attached at store time.
    """

    finding_id: str
    unit_id: str
    unit_type: str
    worker_id: str
    submitted_at: str
    validated_at: str | None = None
    status: str = "pending"
    result_json: str
    quorum_count: int = 1
    citations: list["Citation"] = []

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        """Validate that *status* is one of the allowed values.

        Parameters
        ----------
        v:
            The status string to validate.

        Returns
        -------
        str
            The validated status string.

        Raises
        ------
        ValueError
            If *v* is not one of ``"pending"``, ``"accepted"``,
            ``"disputed"``, or ``"quarantined"``.
        """
        if v not in _VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_STATUSES)}, got {v!r}"
            )
        return v

    @field_validator("finding_id", "unit_id", "unit_type", "worker_id", "submitted_at")
    @classmethod
    def _non_empty_string(cls, v: str) -> str:
        """Reject empty or whitespace-only strings for required text fields.

        Parameters
        ----------
        v:
            The field value to validate.

        Returns
        -------
        str
            The validated string.

        Raises
        ------
        ValueError
            If *v* is empty or consists only of whitespace.
        """
        if not v or not v.strip():
            raise ValueError("Field must be a non-empty string.")
        return v


class Citation(BaseModel):
    """A single EFTA document citation linked to a finding.

    Attributes
    ----------
    citation_id:
        Unique identifier for this citation row.
    finding_id:
        The finding this citation is attached to.
    efta_number:
        EFTA document identifier in ``EFTA{8 digits}`` format (DR-011).
    page_number:
        Optional page number within the EFTA document.
    quote:
        Optional verbatim quote from the document supporting the finding.
    """

    citation_id: str
    finding_id: str
    efta_number: str
    page_number: int | None = None
    quote: str | None = None

    @field_validator("efta_number")
    @classmethod
    def _validate_efta_number(cls, v: str) -> str:
        """Validate that *efta_number* matches ``^EFTA\\d{8}$`` (DR-011).

        Parameters
        ----------
        v:
            The EFTA number string to validate.

        Returns
        -------
        str
            The validated EFTA number string.

        Raises
        ------
        ValueError
            If *v* does not match the required pattern.
        """
        if not _EFTA_PATTERN.match(v):
            raise ValueError(
                f"efta_number must match pattern ^EFTA\\d{{8}}$ (e.g. 'EFTA00039186'), "
                f"got {v!r}"
            )
        return v


class CoverageStats(BaseModel):
    """Coverage statistics for a given work unit type.

    Attributes
    ----------
    unit_type:
        The work unit type these stats apply to.
    units_completed:
        Number of work units with at least one accepted finding.
    units_total:
        Total number of work units of this type ever stored.
    percent:
        Coverage percentage: ``(units_completed / units_total) * 100``, or
        ``0.0`` when ``units_total`` is zero.  Always in the range
        ``[0.0, 100.0]``.
    """

    unit_type: str
    units_completed: int
    units_total: int
    percent: float


# ---------------------------------------------------------------------------
# FindingsStore
# ---------------------------------------------------------------------------


class FindingsStore:
    """Persistent SQLite storage for validated SEFI@Home analysis results.

    On initialisation the database is created (if it does not exist) with the
    ``findings``, ``citations``, and ``work_units`` (stub) tables and the
    required indexes.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Pass ``Path(":memory:")`` or a
        temp-dir path for tests.

    Notes
    -----
    - ``PRAGMA foreign_keys = OFF`` is used for MVP because the ``work_units``
      table is a stub and not guaranteed to contain a row for every
      ``unit_id`` that a finding references.  When the Work Unit Generator
      is integrated and pre-populates ``work_units``, this pragma can be
      enabled safely.
    - :meth:`store_finding` is idempotent: a duplicate ``finding_id``
      returns the existing row without raising an error.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialise the store and create the database schema if needed.

        Parameters
        ----------
        db_path:
            Filesystem path to the SQLite database.  A new file is created
            if it does not exist.  ``Path(":memory:")`` is supported for
            in-process testing.
        """
        self._db_path: Path = db_path
        self._conn: sqlite3.Connection = self._open_connection(db_path)
        self._init_schema()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_finding(self, finding: Finding) -> str:
        """Persist a finding to the database, skipping duplicates.

        If a row with the same ``finding_id`` already exists, the existing
        row is left unchanged and the ``finding_id`` is returned.  This
        makes the operation idempotent (AC-003 resolution note).

        Citations attached to ``finding.citations`` are inserted alongside
        the finding row; existing citation rows are silently skipped (also
        idempotent).

        Parameters
        ----------
        finding:
            The :class:`Finding` to persist.

        Returns
        -------
        str
            The ``finding_id`` of the stored (or pre-existing) finding.

        Raises
        ------
        ValueError
            If any citation's ``efta_number`` does not match
            ``^EFTA\\d{8}$`` (DR-011).
        """
        # Validate citation EFTA numbers before touching the database (DR-011)
        for citation in finding.citations:
            if not _EFTA_PATTERN.match(citation.efta_number):
                raise ValueError(
                    f"Invalid efta_number {citation.efta_number!r} in citation "
                    f"{citation.citation_id!r}: must match ^EFTA\\d{{8}}$"
                )

        cur = self._conn.cursor()

        # Idempotency check: if the finding_id already exists, return early.
        cur.execute(
            "SELECT finding_id FROM findings WHERE finding_id = ?",
            (finding.finding_id,),
        )
        if cur.fetchone() is not None:
            return finding.finding_id

        # Insert the finding row.
        cur.execute(
            """
            INSERT INTO findings
                (finding_id, unit_id, unit_type, worker_id, submitted_at,
                 validated_at, status, result_json, quorum_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding.finding_id,
                finding.unit_id,
                finding.unit_type,
                finding.worker_id,
                finding.submitted_at,
                finding.validated_at,
                finding.status,
                finding.result_json,
                finding.quorum_count,
            ),
        )

        # Insert citation rows (idempotent via INSERT OR IGNORE).
        for citation in finding.citations:
            cur.execute(
                """
                INSERT OR IGNORE INTO citations
                    (citation_id, finding_id, efta_number, page_number, quote)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    citation.citation_id,
                    citation.finding_id,
                    citation.efta_number,
                    citation.page_number,
                    citation.quote,
                ),
            )

        self._conn.commit()
        return finding.finding_id

    def get_findings_for_document(self, efta_number: str) -> list[Finding]:
        """Return all findings that cite a given EFTA document.

        Queries the ``citations`` table (indexed on ``efta_number``) and
        joins to ``findings`` to reconstruct full :class:`Finding` objects
        including their citations.

        Parameters
        ----------
        efta_number:
            EFTA document identifier in ``EFTA{8 digits}`` format.

        Returns
        -------
        list[Finding]
            All findings whose citation list includes *efta_number*.  Empty
            list if none exist.

        Raises
        ------
        ValueError
            If *efta_number* does not match ``^EFTA\\d{8}$`` (DR-011).
        """
        if not _EFTA_PATTERN.match(efta_number):
            raise ValueError(
                f"efta_number {efta_number!r} does not match ^EFTA\\d{{8}}$"
            )

        cur = self._conn.cursor()

        # Find all finding_ids that cite this EFTA.
        cur.execute(
            "SELECT DISTINCT finding_id FROM citations WHERE efta_number = ?",
            (efta_number,),
        )
        finding_ids = [row[0] for row in cur.fetchall()]

        if not finding_ids:
            return []

        findings: list[Finding] = []
        for fid in finding_ids:
            finding = self._load_finding_by_id(fid)
            if finding is not None:
                findings.append(finding)

        return findings

    def export_findings(self, format: str, filters: dict[str, Any]) -> bytes:
        """Export findings as JSON or CSV bytes.

        JSON format
        -----------
        Returns ``{"license": "CC0-1.0", "findings": [...]}`` where each
        element is a dict of the finding row columns (EC-004).

        CSV format
        ----------
        Returns UTF-8 encoded CSV bytes with a header row followed by one
        data row per accepted finding.  Column order matches
        :data:`_FINDINGS_COLUMNS`.

        Parameters
        ----------
        format:
            Export format: ``"json"`` or ``"csv"``.
        filters:
            Optional dict of column → value filters applied to the SQL
            query (e.g. ``{"status": "accepted"}``).  Only supported
            filter keys are ``status``, ``unit_type``, and ``worker_id``.
            Unknown keys are silently ignored.

        Returns
        -------
        bytes
            Serialised export in the requested format (UTF-8 encoded).

        Raises
        ------
        ValueError
            If *format* is not ``"json"`` or ``"csv"``.
        """
        if format not in ("json", "csv"):
            raise ValueError(f"Unsupported export format {format!r}; use 'json' or 'csv'.")

        rows = self._query_findings(filters)

        if format == "json":
            return self._export_json(rows)
        else:
            return self._export_csv(rows)

    def get_coverage(self, unit_type: str) -> CoverageStats:
        """Return coverage statistics for *unit_type*.

        ``units_total`` counts all findings rows of the given type (any
        status).  ``units_completed`` counts those with
        ``status = 'accepted'``.

        Parameters
        ----------
        unit_type:
            Work unit type string (e.g. ``"verify_finding"``).

        Returns
        -------
        CoverageStats
            A :class:`CoverageStats` instance with ``units_completed``,
            ``units_total``, and ``percent`` (0.0–100.0).
        """
        cur = self._conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM findings WHERE unit_type = ?",
            (unit_type,),
        )
        total_row = cur.fetchone()
        units_total: int = total_row[0] if total_row else 0

        cur.execute(
            "SELECT COUNT(*) FROM findings WHERE unit_type = ? AND status = 'accepted'",
            (unit_type,),
        )
        completed_row = cur.fetchone()
        units_completed: int = completed_row[0] if completed_row else 0

        percent: float = (
            round((units_completed / units_total) * 100.0, 2) if units_total > 0 else 0.0
        )

        return CoverageStats(
            unit_type=unit_type,
            units_completed=units_completed,
            units_total=units_total,
            percent=percent,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _open_connection(db_path: Path) -> sqlite3.Connection:
        """Open a SQLite connection and configure pragmas.

        Parameters
        ----------
        db_path:
            Path (or ``:memory:``) for the SQLite database.

        Returns
        -------
        sqlite3.Connection
            A configured connection with ``row_factory = sqlite3.Row`` and
            foreign key enforcement disabled for MVP (see module-level
            docstring).
        """
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        # PRAGMA foreign_keys = OFF for MVP:
        # The `work_units` table is a stub; it is not pre-populated in all
        # test scenarios and the Work Unit Generator manages its own state in
        # memory.  Disabling FK enforcement lets us store findings without
        # requiring a matching work_units row.  Re-enable once the WUG
        # integrates and writes to work_units before findings are stored.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        """Create the database tables and indexes if they do not exist.

        Tables created:
        - ``work_units`` — minimal stub satisfying the FK reference in
          ``findings`` (not written to by this class).
        - ``findings`` — primary result storage (DR-007, DR-010).
        - ``citations`` — per-EFTA citations linked to findings (DR-008).

        Indexes created:
        - ``idx_findings_unit_type`` on ``findings(unit_type)`` (DR-010).
        - ``idx_findings_status`` on ``findings(status)`` (DR-010).
        - ``idx_citations_efta`` on ``citations(efta_number)`` (DR-008).
        """
        cur = self._conn.cursor()

        # Minimal work_units stub so FK references are satisfied when
        # PRAGMA foreign_keys = ON is used in future.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS work_units (
                unit_id TEXT PRIMARY KEY,
                unit_type TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # findings table (DR-007) — status CHECK enforces allowed values.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                unit_id TEXT NOT NULL,
                unit_type TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                submitted_at TIMESTAMP NOT NULL,
                validated_at TIMESTAMP,
                status TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending','accepted','disputed','quarantined')),
                result_json TEXT NOT NULL,
                quorum_count INTEGER DEFAULT 1,
                FOREIGN KEY (unit_id) REFERENCES work_units(unit_id)
            )
            """
        )

        # citations table (DR-008)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS citations (
                citation_id TEXT PRIMARY KEY,
                finding_id TEXT NOT NULL,
                efta_number TEXT NOT NULL,
                page_number INTEGER,
                quote TEXT,
                FOREIGN KEY (finding_id) REFERENCES findings(finding_id)
            )
            """
        )

        # Indexes (DR-010, DR-008)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_findings_unit_type ON findings(unit_type)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_citations_efta ON citations(efta_number)"
        )

        self._conn.commit()

    def _load_finding_by_id(self, finding_id: str) -> Finding | None:
        """Load a single finding row plus its citations from the database.

        Parameters
        ----------
        finding_id:
            The primary key of the finding to load.

        Returns
        -------
        Finding | None
            The reconstructed :class:`Finding`, or ``None`` if not found.
        """
        cur = self._conn.cursor()

        cur.execute(
            "SELECT * FROM findings WHERE finding_id = ?",
            (finding_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        row_dict = dict(row)

        # Load citations for this finding.
        cur.execute(
            "SELECT * FROM citations WHERE finding_id = ?",
            (finding_id,),
        )
        citation_rows = cur.fetchall()
        citations = [Citation(**dict(c)) for c in citation_rows]

        return Finding(
            finding_id=row_dict["finding_id"],
            unit_id=row_dict["unit_id"],
            unit_type=row_dict["unit_type"],
            worker_id=row_dict["worker_id"],
            submitted_at=row_dict["submitted_at"],
            validated_at=row_dict.get("validated_at"),
            status=row_dict["status"],
            result_json=row_dict["result_json"],
            quorum_count=row_dict["quorum_count"],
            citations=citations,
        )

    def _query_findings(
        self, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Query the findings table with optional column filters.

        Only the keys ``status``, ``unit_type``, and ``worker_id`` are
        honoured; others are ignored.

        Parameters
        ----------
        filters:
            Dict of column → value pairs for WHERE clause predicates.

        Returns
        -------
        list[dict[str, Any]]
            List of row dicts from the ``findings`` table.
        """
        _allowed_filter_keys: frozenset[str] = frozenset(
            {"status", "unit_type", "worker_id"}
        )
        active_filters = {
            k: v for k, v in filters.items() if k in _allowed_filter_keys
        }

        if active_filters:
            clauses = " AND ".join(f"{k} = ?" for k in active_filters)
            sql = f"SELECT * FROM findings WHERE {clauses}"  # noqa: S608 — safe: keys are allow-listed
            params = tuple(active_filters.values())
        else:
            sql = "SELECT * FROM findings"
            params = ()

        cur = self._conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _export_json(rows: list[dict[str, Any]]) -> bytes:
        """Serialise findings rows as CC0-labelled JSON bytes (EC-004).

        Parameters
        ----------
        rows:
            List of finding row dicts.

        Returns
        -------
        bytes
            UTF-8 encoded JSON bytes in the format
            ``{"license": "CC0-1.0", "findings": [...]}``.
        """
        payload: dict[str, Any] = {
            "license": _LICENSE,
            "findings": rows,
        }
        return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

    @staticmethod
    def _export_csv(rows: list[dict[str, Any]]) -> bytes:
        """Serialise findings rows as UTF-8 CSV bytes.

        Uses :data:`_FINDINGS_COLUMNS` as the column order.  Missing values
        are rendered as empty strings.

        Parameters
        ----------
        rows:
            List of finding row dicts.

        Returns
        -------
        bytes
            UTF-8 encoded CSV bytes with a header row followed by one data
            row per finding.
        """
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=list(_FINDINGS_COLUMNS),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue().encode("utf-8")
