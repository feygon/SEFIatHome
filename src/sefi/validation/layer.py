"""Validation layer for SEFI@Home.

Enforces quality and ethical constraints on submitted worker results before
they are written to the findings store.

Processing order (hard-coded, non-bypassable):

1. **PII scan** — :meth:`ValidationLayer.scan_for_pii` runs over the full
   serialised result text.  Any match immediately quarantines the result;
   subsequent checks are *skipped* (short-circuit).
2. **Provenance check** — :meth:`ValidationLayer.verify_provenance` confirms
   that every cited EFTA number appears in the ingested ``entities`` or
   ``efta_mapping`` working table.
3. **Deduplication check** — :meth:`ValidationLayer.check_deduplication`
   rejects the submission if an accepted finding for the same ``unit_id``
   already exists in the :class:`~sefi.store.findings.FindingsStore`.

A quarantined result **is** written to the database with
``status="quarantined"`` and is **never** written with ``status="accepted"``.

Notes
-----
- Full quorum validation (N-of-M agreement) is POST-MVP.  For MVP,
  ``quorum_status`` is always ``"achieved"`` on the first accepted result.
- PII patterns are an MVP stub labelled ``# MVP STUB``.  The full
  victim-name pattern list is deferred to OQ-004.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from sefi.db.adapter import DatabaseAdapter
from sefi.store.findings import Finding, FindingsStore


# ---------------------------------------------------------------------------
# PII patterns  # MVP STUB
# ---------------------------------------------------------------------------
# The patterns below cover the three MVP-required PII categories.
# A full victim-name pattern list (EC-001 / OQ-004) is deferred to post-MVP.

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # SSN: ###-##-####
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # US phone number (many formats)
    (
        "phone",
        re.compile(
            r"\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
    ),
    # Postal/street address: number + street name + street type
    (
        "postal_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Za-z0-9\s,.]+(?:Street|St|Avenue|Ave|"
            r"Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct)\b"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Pydantic models crossing module boundaries
# ---------------------------------------------------------------------------


class PIIMatch(BaseModel):
    """A single PII pattern match found within a result's text.

    Attributes
    ----------
    pattern_name:
        Human-readable name of the pattern that matched
        (e.g. ``"ssn"``, ``"phone"``, ``"postal_address"``).
    matched_text:
        The exact substring that triggered the match.
    """

    pattern_name: str
    matched_text: str


class ResultSubmission(BaseModel):
    """A result submitted by a worker for a specific work unit.

    This is the input to :meth:`ValidationLayer.validate_result`.

    Attributes
    ----------
    unit_id:
        Identifier of the work unit being answered.
    worker_id:
        Identifier of the submitting worker (e.g. a Claude session ID).
    result:
        Arbitrary result payload (any JSON-serialisable structure).
    cited_eftas:
        List of EFTA document numbers cited in the result
        (e.g. ``["EFTA00039186"]``).  May be empty.
    unit_type:
        The work unit type string (e.g. ``"verify_finding"``).  Defaults
        to ``"unknown"`` when not provided.
    """

    unit_id: str
    worker_id: str
    result: dict[str, Any]
    cited_eftas: list[str] = []
    unit_type: str = "unknown"


class ValidationResult(BaseModel):
    """The outcome of running :meth:`ValidationLayer.validate_result`.

    Attributes
    ----------
    accepted:
        ``True`` if the result passed all validation checks and was stored
        as ``status="accepted"``; ``False`` otherwise.
    quorum_status:
        Quorum resolution status.  Always ``"achieved"`` for MVP (single
        worker).  Full N-of-M logic is post-MVP.
    pii_detected:
        ``True`` if one or more PII patterns matched the result text.
    errors:
        List of human-readable error messages explaining rejection reasons.
    finding_id:
        The ``finding_id`` assigned to the stored finding, or ``None`` if
        no finding was created.
    """

    accepted: bool
    quorum_status: str = "achieved"
    pii_detected: bool = False
    errors: list[str] = []
    finding_id: str | None = None


# ---------------------------------------------------------------------------
# ValidationLayer
# ---------------------------------------------------------------------------


class ValidationLayer:
    """Validates worker result submissions before accepting them to storage.

    Responsibilities
    ----------------
    1. Run PII scan on all result text (hard requirement, cannot be bypassed).
    2. Verify provenance: every cited EFTA must appear in the ingested working
       tables (``entities`` or ``efta_mapping``).
    3. Deduplicate: reject if an accepted finding for ``unit_id`` already
       exists.

    If validation passes, the finding is stored with ``status="accepted"``.
    If PII is detected, the finding is stored with ``status="quarantined"``.
    All other failures result in no finding being stored.

    Parameters
    ----------
    db_adapter:
        :class:`~sefi.db.adapter.DatabaseAdapter` used for provenance
        lookups against the ``entities`` and ``efta_mapping`` working tables.
    findings_store:
        :class:`~sefi.store.findings.FindingsStore` used for deduplication
        queries and to persist validated or quarantined findings.
    """

    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        findings_store: FindingsStore,
    ) -> None:
        """Initialise the validation layer.

        Parameters
        ----------
        db_adapter:
            Adapter providing access to the ingested working tables.
        findings_store:
            Store for persisting accepted and quarantined findings.
        """
        self._db_adapter = db_adapter
        self._findings_store = findings_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_result(self, result: ResultSubmission) -> ValidationResult:
        """Validate a submitted result and persist it if accepted or quarantined.

        Processing order is fixed and non-bypassable:

        1. ``scan_for_pii`` — short-circuits on any match, quarantines.
        2. ``verify_provenance`` — rejects on any unknown cited EFTA.
        3. ``check_deduplication`` — rejects if an accepted finding for the
           same ``unit_id`` already exists.

        A clean result (valid EFTA citations, no duplicate, no PII) is stored
        with ``status="accepted"`` and :attr:`ValidationResult.accepted` is
        ``True``.

        Parameters
        ----------
        result:
            The :class:`ResultSubmission` to validate.

        Returns
        -------
        ValidationResult
            The outcome of all checks, including ``accepted``,
            ``pii_detected``, ``errors``, and the assigned ``finding_id``
            (if a finding was stored).
        """
        result_text = _serialise_result(result)

        # ------------------------------------------------------------------
        # Step 1: PII scan (always first; short-circuits on match).
        # ------------------------------------------------------------------
        pii_matches = self.scan_for_pii(result_text)
        if pii_matches:
            finding_id = self._store_finding(result, status="quarantined")
            return ValidationResult(
                accepted=False,
                quorum_status="achieved",
                pii_detected=True,
                errors=[
                    f"PII detected — pattern '{m.pattern_name}' matched "
                    f"text {m.matched_text!r}"
                    for m in pii_matches
                ],
                finding_id=finding_id,
            )

        # ------------------------------------------------------------------
        # Step 2: Provenance check.
        # ------------------------------------------------------------------
        provenance_errors = self.verify_provenance(result.cited_eftas)
        if provenance_errors:
            return ValidationResult(
                accepted=False,
                quorum_status="achieved",
                pii_detected=False,
                errors=provenance_errors,
                finding_id=None,
            )

        # ------------------------------------------------------------------
        # Step 3: Deduplication check.
        # ------------------------------------------------------------------
        dedup_error, existing_id = self.check_deduplication(result.unit_id)
        if dedup_error:
            return ValidationResult(
                accepted=False,
                quorum_status="achieved",
                pii_detected=False,
                errors=[dedup_error],
                finding_id=existing_id,
            )

        # ------------------------------------------------------------------
        # All checks passed — store as accepted.
        # ------------------------------------------------------------------
        finding_id = self._store_finding(result, status="accepted")
        return ValidationResult(
            accepted=True,
            quorum_status="achieved",
            pii_detected=False,
            errors=[],
            finding_id=finding_id,
        )

    def scan_for_pii(self, text: str) -> list[PIIMatch]:
        """Scan *text* for PII patterns and return all matches.

        Applies every pattern in the MVP pattern list (SSN, US phone,
        postal address).  All matches across all patterns are returned.

        This method is called on the **full serialised result text** (not just
        individual fields) to ensure nothing slips through.

        .. note::
            **# MVP STUB** — Only three pattern categories are implemented.
            A full victim-name pattern list is deferred to OQ-004.

        Parameters
        ----------
        text:
            The string to scan for PII.

        Returns
        -------
        list[PIIMatch]
            All PII matches found.  Empty list if text is clean.
        """
        matches: list[PIIMatch] = []
        for pattern_name, pattern in _PII_PATTERNS:
            for m in pattern.finditer(text):
                matches.append(
                    PIIMatch(pattern_name=pattern_name, matched_text=m.group())
                )
        return matches

    def verify_provenance(self, cited_eftas: list[str]) -> list[str]:
        """Check that all cited EFTA numbers exist in the ingested working tables.

        A cited EFTA is considered valid if its numeric portion (the 8-digit
        suffix of the ``EFTA########`` string) appears as a ``range_start`` or
        ``range_end`` value in the ``efta_mapping`` table, **or** if the full
        EFTA string appears in the ``entities`` table (field ``entity_id`` or
        any alias).

        For MVP the provenance check is intentionally broad: if the numeric
        portion of the EFTA falls within *any* range in ``efta_mapping``, it is
        considered present.  This avoids false rejections caused by the sparse
        JSON exports not listing every individual EFTA number.

        Parameters
        ----------
        cited_eftas:
            List of EFTA strings from the submission (e.g.
            ``["EFTA00039186"]``).

        Returns
        -------
        list[str]
            Human-readable error messages for each EFTA that could not be
            verified.  Empty list means all citations are valid (or no
            citations were supplied).
        """
        if not cited_eftas:
            return []

        errors: list[str] = []
        for efta in cited_eftas:
            if not self._efta_is_known(efta):
                errors.append(
                    f"Provenance error: cited EFTA '{efta}' not found in "
                    "ingested exports (entities or efta_mapping tables)."
                )
        return errors

    def check_deduplication(self, unit_id: str) -> tuple[str | None, str | None]:
        """Check whether an accepted finding already exists for *unit_id*.

        Parameters
        ----------
        unit_id:
            The work unit identifier to check.

        Returns
        -------
        tuple[str | None, str | None]
            A two-element tuple ``(error_message, existing_finding_id)``.

            * If no accepted finding exists: ``(None, None)``.
            * If a duplicate exists: ``(error_message, existing_finding_id)``
              where *error_message* references the pre-existing finding ID.
        """
        existing_id = self._get_accepted_finding_id(unit_id)
        if existing_id is not None:
            msg = (
                f"Duplicate submission rejected: unit_id '{unit_id}' already "
                f"has an accepted finding with finding_id '{existing_id}'."
            )
            return msg, existing_id
        return None, None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _efta_is_known(self, efta: str) -> bool:
        """Return True if *efta* can be located in the ingested working tables.

        Two lookup strategies are tried in order:

        1. **efta_mapping table** — extract the numeric portion of *efta* and
           check whether it falls within any stored ``(range_start, range_end)``
           range.
        2. **entities table** — check whether the ``entity_id`` column contains
           *efta* exactly, or whether the ``aliases`` JSON column contains *efta*
           as a value.

        Parameters
        ----------
        efta:
            EFTA string to look up (e.g. ``"EFTA00039186"``).

        Returns
        -------
        bool
            ``True`` if the EFTA is considered present; ``False`` otherwise.
        """
        numeric = _efta_to_int(efta)

        # --- efta_mapping range lookup -----------------------------------
        if numeric is not None:
            try:
                cursor = self._db_adapter._conn.execute(
                    """
                    SELECT 1
                    FROM efta_mapping
                    WHERE range_start IS NOT NULL
                      AND range_end IS NOT NULL
                      AND ? BETWEEN range_start AND range_end
                    LIMIT 1
                    """,
                    (numeric,),
                )
                if cursor.fetchone() is not None:
                    return True
            except Exception:  # noqa: BLE001 — table may not exist yet
                pass

        # --- entities table lookup ---------------------------------------
        try:
            cursor = self._db_adapter._conn.execute(
                "SELECT 1 FROM entities WHERE entity_id = ? LIMIT 1",
                (efta,),
            )
            if cursor.fetchone() is not None:
                return True
        except Exception:  # noqa: BLE001 — table may not exist
            pass

        return False

    def _get_accepted_finding_id(self, unit_id: str) -> str | None:
        """Query the findings store for an accepted finding on *unit_id*.

        Parameters
        ----------
        unit_id:
            Work unit ID to check.

        Returns
        -------
        str | None
            The ``finding_id`` of the first accepted finding for *unit_id*,
            or ``None`` if none exists.
        """
        try:
            cursor = self._findings_store._conn.execute(
                """
                SELECT finding_id
                FROM findings
                WHERE unit_id = ? AND status = 'accepted'
                LIMIT 1
                """,
                (unit_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                return row[0]
        except Exception:  # noqa: BLE001 — db may be uninitialised
            pass
        return None

    def _store_finding(
        self, result: ResultSubmission, status: str
    ) -> str:
        """Persist *result* to the findings store with the given *status*.

        Generates a UUID-based ``finding_id`` and records the current UTC
        timestamp as both ``submitted_at`` and ``validated_at``.

        Parameters
        ----------
        result:
            The :class:`ResultSubmission` to persist.
        status:
            ``"accepted"`` or ``"quarantined"``.

        Returns
        -------
        str
            The newly generated ``finding_id``.
        """
        finding_id = f"finding-{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=timezone.utc).isoformat()

        finding = Finding(
            finding_id=finding_id,
            unit_id=result.unit_id,
            unit_type=result.unit_type,
            worker_id=result.worker_id,
            submitted_at=now,
            validated_at=now,
            status=status,
            result_json=json.dumps(result.result),
            quorum_count=1,
            citations=[],
        )
        self._findings_store.store_finding(finding)
        return finding_id


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _serialise_result(result: ResultSubmission) -> str:
    """Serialise the full :class:`ResultSubmission` to a single string for PII scanning.

    The entire submission (including ``unit_id``, ``worker_id``, and the nested
    ``result`` payload) is JSON-serialised so that no field escapes the PII
    scan.

    Parameters
    ----------
    result:
        The submission to serialise.

    Returns
    -------
    str
        A compact JSON string representation of the entire submission.
    """
    return json.dumps(result.model_dump(), ensure_ascii=False, default=str)


def _efta_to_int(efta: str) -> int | None:
    """Extract the numeric suffix from an EFTA string.

    Accepts strings in ``EFTA########`` format (e.g. ``"EFTA00039186"`` →
    ``39186``).  Returns ``None`` for any string that does not start with
    ``"EFTA"`` or whose suffix is not a valid integer.

    Parameters
    ----------
    efta:
        The EFTA string to parse.

    Returns
    -------
    int | None
        The integer EFTA number, or ``None`` if unparseable.
    """
    if not isinstance(efta, str) or not efta.upper().startswith("EFTA"):
        return None
    suffix = efta[4:]
    try:
        return int(suffix)
    except ValueError:
        return None
