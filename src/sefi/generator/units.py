"""Work unit dataclass and generator for SEFI@Home verify_finding and decision_chain types.

This module implements the ``WorkUnit`` dataclass and the ``WorkUnitGenerator``
class.  Two work unit types are supported:

``verify_finding``
    Each unit contains a single claim drawn from rhowardstone report data, one
    or more cited EFTA numbers, the corresponding resolved DOJ PDF URLs, and
    mandatory instruction text that includes the de-anonymization prohibition
    required by EC-007.

``decision_chain``
    Each unit batches 20–50 document references from the same 30-day time
    window, drawn from the ingested ``knowledge_graph_relationships.json``
    data.  The unit's ``input`` dict includes ``time_window_start``,
    ``time_window_end`` (ISO 8601 date strings), and ``data`` (a list of
    document reference dicts, each containing at minimum ``efta_number`` and
    ``url``).

The generator tracks per-unit assignment state in memory and exposes
``mark_unit_assigned``, ``mark_unit_complete``, and ``generate_unit``.

Design notes
------------
- ``WorkUnit`` is a ``dataclass`` with ``__post_init__`` validation rather than
  a Pydantic model.  Pydantic models are reserved for API boundaries
  (NFR-003).  Internal data structures may use dataclasses.
- Assignment tracking uses two in-memory structures:
    - ``_assignments: dict[str, str | None]``  maps unit_id → worker_id
    - ``_completed: set[str]``                 unit_ids that are done
- DS10 content and image/video file types are excluded at claim-load time
  (EC-002).
- Every unit's ``instructions`` field contains the verbatim de-anonymization
  prohibition required by EC-007.
- ``source_verified`` is always ``False`` for claims from rhowardstone reports
  (EC-006); the claims have not yet been independently confirmed.
- ``decision_chain`` time-window selection groups relationship records by their
  ``date`` field into 30-day buckets.  A bucket must contain at least 20
  unassigned document references to be eligible.  If no eligible bucket
  exists, :exc:`NoAvailableUnitsError` is raised.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Research path for verify_finding units (Verification path).
_VERIFY_PATH: int = 5

#: Difficulty label for verify_finding units.
_VERIFY_DIFFICULTY: str = "low"

#: Scaling type for verify_finding units.
_VERIFY_SCALING: str = "linear"

#: Human-readable batch size description for verify_finding units.
_VERIFY_OPTIMAL_BATCH: str = "1 claim"

#: Verbatim de-anonymization prohibition required by EC-007.
#: This string MUST appear in every generated unit's ``instructions`` field.
DE_ANON_PROHIBITION: str = (
    "Do not attempt to infer or recover redacted content. Analyze patterns only."
)

#: Mandatory constraints dict for verify_finding units.
_VERIFY_CONSTRAINTS: dict[str, Any] = {
    "max_output_tokens": 2000,
    "pii_filter": True,
    "requires_quorum": False,
}

#: Number of hours until a work unit expires.
_DEADLINE_HOURS: int = 24

#: Dataset number for DS10 (media files — excluded per EC-002).
_DS10_DATASET: int = 10

#: File-type suffixes that are excluded from work units (EC-002).
_EXCLUDED_SUFFIXES: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
     ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm",
     ".mp3", ".wav", ".aac", ".flac"}
)

# ---------------------------------------------------------------------------
# decision_chain constants (FR-017, Work Unit Types Reference)
# ---------------------------------------------------------------------------

#: Research path for decision_chain units (NPA Forensics path).
_DC_PATH: int = 3

#: Difficulty label for decision_chain units.
_DC_DIFFICULTY: str = "high"

#: Scaling type for decision_chain units.
_DC_SCALING: str = "multiplying"

#: Human-readable batch size description for decision_chain units.
_DC_OPTIMAL_BATCH: str = "20-50 docs (same 30-day period)"

#: Mandatory constraints dict for decision_chain units.
#: ``requires_quorum=True`` because decision_chain is high-stakes (ethical
#: framework: quorum required).
_DC_CONSTRAINTS: dict[str, Any] = {
    "max_output_tokens": 8000,
    "pii_filter": True,
    "requires_quorum": True,
}

#: Minimum number of document references required in a single decision_chain
#: work unit (FR-013).
_DC_BATCH_MIN: int = 20

#: Maximum number of document references allowed in a single decision_chain
#: work unit (FR-013).
_DC_BATCH_MAX: int = 50

#: Number of days that define a single time window for decision_chain batching.
_DC_WINDOW_DAYS: int = 30

#: EFTA field names to look up (in priority order) when extracting an EFTA
#: number from a relationship record.
_EFTA_FIELD_CANDIDATES: tuple[str, ...] = (
    "efta_number",
    "efta_source",
    "source_efta",
    "efta",
    "document_id",
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class NoAvailableUnitsError(RuntimeError):
    """Raised when no eligible work unit can be generated.

    For ``verify_finding``: all claims are currently assigned or completed.
    For ``decision_chain``: no 30-day time window has the minimum number (20)
    of unassigned document references.
    """


# ---------------------------------------------------------------------------
# WorkUnit dataclass
# ---------------------------------------------------------------------------

@dataclass
class WorkUnit:
    """A self-contained unit of analytical work for a SEFI@Home volunteer.

    Two unit types are defined:

    ``verify_finding``
        Contains a single claim drawn from rhowardstone reports together with
        cited EFTA numbers and resolved DOJ PDF URLs.  The worker fetches each
        PDF directly from justice.gov and returns a structured verdict.

    ``decision_chain``
        Contains 20–50 document references from within a single 30-day time
        window.  The worker maps the communication graph (who → whom → when →
        topic) and returns patterns observed across the batch.

    Attributes
    ----------
    unit_id:
        Unique identifier for this work unit.
        - ``verify_finding`` format: ``"verify-{hex12}"``
        - ``decision_chain`` format: ``"dc-{hex12}"``
    type:
        Work unit type string — one of ``"verify_finding"`` or
        ``"decision_chain"``.
    path:
        Research path number (1–5).
        - ``verify_finding``: path 5 (Verification)
        - ``decision_chain``: path 3 (NPA Forensics)
    difficulty:
        Difficulty label — one of ``"low"``, ``"medium"``, or ``"high"``.
    scaling:
        Scaling behaviour — one of ``"linear"``, ``"multiplying"``,
        ``"plateau"``, or ``"aggregation"``.
    optimal_batch:
        Human-readable description of the recommended batch size.
    input:
        Dictionary containing the work payload.
        - ``verify_finding``: ``claim``, ``cited_eftas``, ``efta_urls``,
          ``source_verified``.
        - ``decision_chain``: ``time_window_start``, ``time_window_end``,
          ``data`` (list of doc refs with ``efta_number`` and ``url``).
    instructions:
        Natural-language task description sent to the worker.  Always includes
        the verbatim de-anonymization prohibition (EC-007).
    constraints:
        Hard limits and flags for the worker: ``max_output_tokens``,
        ``pii_filter``, ``requires_quorum``.
    deadline:
        ISO 8601 datetime string after which the unit may be re-assigned.
    source_verified:
        Whether the source claim has been independently verified.  Always
        ``False`` for rhowardstone report claims (EC-006).
    """

    unit_id: str
    type: str
    path: int
    difficulty: str
    scaling: str
    optimal_batch: str
    input: dict[str, Any]
    instructions: str
    constraints: dict[str, Any]
    deadline: str
    source_verified: bool

    def __post_init__(self) -> None:
        """Validate all required fields after dataclass initialisation.

        Raises
        ------
        ValueError
            If any field is missing, empty, or of an incorrect type.
        TypeError
            If a field value has a wrong Python type.
        """
        # unit_id — non-empty string
        if not isinstance(self.unit_id, str) or not self.unit_id.strip():
            raise ValueError("unit_id must be a non-empty string")

        # type — non-empty string
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("type must be a non-empty string")

        # path — integer in 1..5
        if not isinstance(self.path, int) or not (1 <= self.path <= 5):
            raise ValueError("path must be an integer between 1 and 5 inclusive")

        # difficulty — one of the allowed values
        _allowed_difficulties = {"low", "medium", "high"}
        if self.difficulty not in _allowed_difficulties:
            raise ValueError(
                f"difficulty must be one of {_allowed_difficulties}, got {self.difficulty!r}"
            )

        # scaling — one of the allowed values
        _allowed_scaling = {"linear", "multiplying", "plateau", "aggregation"}
        if self.scaling not in _allowed_scaling:
            raise ValueError(
                f"scaling must be one of {_allowed_scaling}, got {self.scaling!r}"
            )

        # optimal_batch — non-empty string
        if not isinstance(self.optimal_batch, str) or not self.optimal_batch.strip():
            raise ValueError("optimal_batch must be a non-empty string")

        # input — dict with type-specific required keys
        if not isinstance(self.input, dict):
            raise TypeError("input must be a dict")
        if self.type == "verify_finding":
            self._validate_verify_input(self.input)
        elif self.type == "decision_chain":
            self._validate_decision_chain_input(self.input)

        # instructions — must contain de-anonymization prohibition
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be a non-empty string")
        if DE_ANON_PROHIBITION not in self.instructions:
            raise ValueError(
                f"instructions must contain the verbatim de-anonymization prohibition: "
                f"{DE_ANON_PROHIBITION!r}"
            )

        # constraints — dict with required keys
        if not isinstance(self.constraints, dict):
            raise TypeError("constraints must be a dict")
        _required_constraint_keys = {"max_output_tokens", "pii_filter", "requires_quorum"}
        missing = _required_constraint_keys - self.constraints.keys()
        if missing:
            raise ValueError(f"constraints is missing required keys: {missing}")

        # deadline — non-empty string (ISO 8601 format)
        if not isinstance(self.deadline, str) or not self.deadline.strip():
            raise ValueError("deadline must be a non-empty ISO 8601 datetime string")

        # source_verified — bool
        if not isinstance(self.source_verified, bool):
            raise TypeError("source_verified must be a bool")

    @staticmethod
    def _validate_verify_input(input_dict: dict[str, Any]) -> None:
        """Validate the ``input`` field for a ``verify_finding`` unit.

        Parameters
        ----------
        input_dict:
            The ``input`` field value to validate.

        Raises
        ------
        ValueError
            If ``claim`` is empty, ``cited_eftas`` is empty, ``efta_urls`` has
            a different length from ``cited_eftas``, or any URL does not look
            like a DOJ PDF URL.
        """
        # claim — non-empty string
        claim = input_dict.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("input.claim must be a non-empty string for verify_finding units")

        # cited_eftas — non-empty list of EFTA-format strings
        cited_eftas = input_dict.get("cited_eftas")
        if not isinstance(cited_eftas, list) or len(cited_eftas) == 0:
            raise ValueError("input.cited_eftas must be a non-empty list for verify_finding units")
        for efta in cited_eftas:
            if not isinstance(efta, str) or not efta.startswith("EFTA") or len(efta) != 12:
                raise ValueError(
                    f"Each cited_efta must be a string in format 'EFTA00000000', got {efta!r}"
                )

        # efta_urls — list of DOJ PDF URLs matching cited_eftas in count
        efta_urls = input_dict.get("efta_urls")
        if not isinstance(efta_urls, list):
            raise ValueError("input.efta_urls must be a list for verify_finding units")
        if len(efta_urls) != len(cited_eftas):
            raise ValueError(
                f"input.efta_urls length ({len(efta_urls)}) must match "
                f"input.cited_eftas length ({len(cited_eftas)})"
            )
        _doj_prefix = "https://www.justice.gov/epstein/files/DataSet%20"
        for url in efta_urls:
            if not isinstance(url, str) or not url.startswith(_doj_prefix):
                raise ValueError(
                    f"Each efta_url must be a valid DOJ PDF URL starting with "
                    f"{_doj_prefix!r}, got {url!r}"
                )

    @staticmethod
    def _validate_decision_chain_input(input_dict: dict[str, Any]) -> None:
        """Validate the ``input`` field for a ``decision_chain`` unit.

        Parameters
        ----------
        input_dict:
            The ``input`` field value to validate.

        Raises
        ------
        ValueError
            If ``time_window_start`` or ``time_window_end`` are absent or
            malformed, if ``time_window_end`` is more than 30 days after
            ``time_window_start``, or if ``data`` does not contain between 20
            and 50 document reference dicts each having ``efta_number`` and
            ``url``.
        """
        # time_window_start — non-empty ISO 8601 date string
        tw_start = input_dict.get("time_window_start")
        if not isinstance(tw_start, str) or not tw_start.strip():
            raise ValueError(
                "input.time_window_start must be a non-empty ISO 8601 date string "
                "for decision_chain units"
            )

        # time_window_end — non-empty ISO 8601 date string
        tw_end = input_dict.get("time_window_end")
        if not isinstance(tw_end, str) or not tw_end.strip():
            raise ValueError(
                "input.time_window_end must be a non-empty ISO 8601 date string "
                "for decision_chain units"
            )

        # Parse and validate window constraint (AC-001)
        try:
            start_date = date.fromisoformat(tw_start)
            end_date = date.fromisoformat(tw_end)
        except ValueError as exc:
            raise ValueError(
                f"input.time_window_start and time_window_end must be valid ISO 8601 "
                f"date strings (YYYY-MM-DD), got start={tw_start!r} end={tw_end!r}"
            ) from exc

        if end_date < start_date:
            raise ValueError(
                f"time_window_end ({tw_end!r}) must not be before "
                f"time_window_start ({tw_start!r})"
            )
        window_days = (end_date - start_date).days
        if window_days > _DC_WINDOW_DAYS:
            raise ValueError(
                f"time_window_end must be within {_DC_WINDOW_DAYS} days of "
                f"time_window_start; got {window_days} days"
            )

        # data — list of 20–50 document reference dicts (FR-013, AC-001)
        data = input_dict.get("data")
        if not isinstance(data, list):
            raise ValueError("input.data must be a list for decision_chain units")
        if not (_DC_BATCH_MIN <= len(data) <= _DC_BATCH_MAX):
            raise ValueError(
                f"input.data must contain between {_DC_BATCH_MIN} and {_DC_BATCH_MAX} "
                f"document references for decision_chain units; got {len(data)}"
            )
        _doj_prefix = "https://www.justice.gov/epstein/files/DataSet%20"
        for i, doc_ref in enumerate(data):
            if not isinstance(doc_ref, dict):
                raise ValueError(
                    f"input.data[{i}] must be a dict, got {type(doc_ref).__name__}"
                )
            efta = doc_ref.get("efta_number")
            if not isinstance(efta, str) or not efta.startswith("EFTA") or len(efta) != 12:
                raise ValueError(
                    f"input.data[{i}].efta_number must be in format 'EFTA00000000', "
                    f"got {efta!r}"
                )
            url = doc_ref.get("url")
            if not isinstance(url, str) or not url.startswith(_doj_prefix):
                raise ValueError(
                    f"input.data[{i}].url must be a valid DOJ PDF URL starting with "
                    f"{_doj_prefix!r}, got {url!r}"
                )


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ClaimRecord = dict[str, Any]
"""A single claim record as loaded from the claims JSON file.

Expected keys:
    claim_id (str): Unique claim identifier.
    claim (str): The claim text.
    cited_eftas (list[str]): EFTA numbers cited for this claim.
    primary_datasets (list[int]): Primary dataset number for each EFTA.
    source_verified (bool): Whether the source has been independently verified.
"""

RelationshipRecord = dict[str, Any]
"""A single relationship record as loaded from knowledge_graph_relationships.json.

Expected keys (at minimum):
    date (str): ISO 8601 date string for when this relationship was documented.
    efta_number (str | None): EFTA number of the source document, if present.
    source_entity (str): Source entity identifier.
    target_entity (str): Target entity identifier.
    relationship_type (str): Type of relationship.
"""

DocRef = dict[str, Any]
"""A document reference dict used in decision_chain ``input.data``.

Required keys:
    efta_number (str): EFTA-format document identifier (e.g. ``"EFTA00039186"``).
    url (str): Canonical DOJ PDF URL for this document.

Optional additional keys from the source relationship record are preserved.
"""


# ---------------------------------------------------------------------------
# WorkUnitGenerator
# ---------------------------------------------------------------------------

class WorkUnitGenerator:
    """Generates ``verify_finding`` and ``decision_chain`` work units.

    Each call to :meth:`generate_unit` returns a fresh :class:`WorkUnit` for
    the requested unit type.

    Assignment state is tracked in two in-memory structures:

    - ``_assignments``: ``dict[str, str | None]`` — maps unit_id to the
      worker_id that claimed it (or ``None`` if generated but not yet assigned).
    - ``_completed``: ``set[str]`` — unit_ids that have been marked complete.

    Parameters
    ----------
    claims:
        List of claim dicts for ``verify_finding`` generation.  Takes
        precedence over ``claims_path`` if both are provided.
    claims_path:
        Path to a JSON file containing an array of claim dicts.  Defaults to
        ``data/sample_claims.json`` relative to the current directory.
    relationships:
        List of relationship dicts for ``decision_chain`` generation.  Each
        dict must contain at minimum a ``date`` field (ISO 8601) and an EFTA
        number field (see :data:`_EFTA_FIELD_CANDIDATES`).  Takes precedence
        over ``relationships_path`` if both are provided.
    relationships_path:
        Path to a JSON file containing the knowledge graph relationships array.
        Defaults to ``data/knowledge_graph_relationships.json``.
    url_builder:
        Callable ``(efta_int: int, dataset: int) -> str`` for DOJ URL
        construction.  Defaults to ``sefi.db.efta.build_url``.  Injectable
        for testing without network access.
    """

    def __init__(
        self,
        claims: list[ClaimRecord] | None = None,
        claims_path: Path | str | None = None,
        relationships: list[RelationshipRecord] | None = None,
        relationships_path: Path | str | None = None,
        url_builder: Any = None,
    ) -> None:
        """Initialise the generator.

        Parameters
        ----------
        claims:
            Pre-loaded list of claim dicts.  Takes precedence over
            ``claims_path``.
        claims_path:
            Path to the JSON claims file.  Falls back to
            ``data/sample_claims.json`` when neither ``claims`` nor
            ``claims_path`` is given.
        relationships:
            Pre-loaded list of relationship dicts for decision_chain units.
            Takes precedence over ``relationships_path``.
        relationships_path:
            Path to the JSON relationships file.  Falls back to
            ``data/knowledge_graph_relationships.json`` when neither
            ``relationships`` nor ``relationships_path`` is given.
        url_builder:
            Callable ``(efta_int: int, dataset: int) -> str`` for DOJ URL
            construction.  Defaults to ``sefi.db.efta.build_url``.
        """
        if url_builder is None:
            from sefi.db.efta import build_url  # local import to allow mocking
            self._url_builder = build_url
        else:
            self._url_builder = url_builder

        # ---- claims (verify_finding) ----
        if claims is not None:
            raw_claims = claims
        else:
            if claims_path is None:
                claims_path = Path("data") / "sample_claims.json"
            raw_claims = self._load_json_list(Path(claims_path), label="claims")

        # Filter out any claims referencing DS10 or excluded file types (EC-002)
        self._claims: list[ClaimRecord] = self._filter_claims(raw_claims)

        # ---- relationships (decision_chain) ----
        if relationships is not None:
            raw_relationships = relationships
        else:
            if relationships_path is None:
                relationships_path = (
                    Path("data") / "knowledge_graph_relationships.json"
                )
            rpath = Path(relationships_path)
            if rpath.exists():
                raw_relationships = self._load_json_list(rpath, label="relationships")
            else:
                # Relationships file not yet downloaded — start with empty list.
                # decision_chain generation will raise NoAvailableUnitsError.
                raw_relationships = []

        # Filter out DS10 and image/video references (EC-002)
        self._relationships: list[RelationshipRecord] = self._filter_relationships(
            raw_relationships
        )

        # ---- assignment tracking (shared across both types) ----

        # unit_id → worker_id (None = generated but not yet assigned)
        self._assignments: dict[str, str | None] = {}

        # unit_ids that have been fully completed
        self._completed: set[str] = set()

        # ---- verify_finding bookkeeping ----

        # unit_id → claim record
        self._unit_to_claim: dict[str, ClaimRecord] = {}

        # claim_id → unit_id (to detect if a claim already has a live unit)
        self._claim_to_unit: dict[str, str] = {}

        # ---- decision_chain bookkeeping ----

        # unit_id → frozenset of doc-ref keys (efta_number values) used in that unit
        self._unit_to_doc_keys: dict[str, frozenset[str]] = {}

        # set of efta_number values currently consumed by an active (non-completed) unit
        self._active_dc_keys: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_unit(self, unit_type: str = "verify_finding") -> WorkUnit:
        """Generate and return the next available work unit for *unit_type*.

        Dispatches to the appropriate private method using a ``match``
        statement (Python 3.10+).

        Parameters
        ----------
        unit_type:
            One of ``"verify_finding"`` or ``"decision_chain"``.  Defaults to
            ``"verify_finding"`` for backwards compatibility.

        Returns
        -------
        WorkUnit
            A fully-populated and validated work unit.

        Raises
        ------
        NoAvailableUnitsError
            If no eligible unit can be generated for the requested type.
        ValueError
            If *unit_type* is not a recognised type string.
        """
        match unit_type:
            case "verify_finding":
                return self._generate_verify_finding()
            case "decision_chain":
                return self._generate_decision_chain()
            case _:
                raise ValueError(
                    f"Unknown unit_type {unit_type!r}. "
                    "Supported types: 'verify_finding', 'decision_chain'."
                )

    def mark_unit_assigned(self, unit_id: str, worker_id: str) -> None:
        """Record that a worker has claimed a specific work unit.

        Parameters
        ----------
        unit_id:
            The unit_id to mark as assigned.
        worker_id:
            The identifier of the worker claiming the unit.

        Raises
        ------
        KeyError
            If ``unit_id`` was never generated by this generator.
        ValueError
            If the unit is already assigned to a worker or already completed.
        """
        if unit_id not in self._assignments:
            raise KeyError(f"Unknown unit_id: {unit_id!r}. Generate the unit first.")
        if unit_id in self._completed:
            raise ValueError(f"Unit {unit_id!r} is already completed.")
        current_worker = self._assignments[unit_id]
        if current_worker is not None:
            raise ValueError(
                f"Unit {unit_id!r} is already assigned to worker {current_worker!r}. "
                "Double-assignment is not permitted."
            )
        self._assignments[unit_id] = worker_id

    def mark_unit_complete(self, unit_id: str) -> None:
        """Mark a work unit as fully processed.

        After this call the unit will not appear in subsequent
        :meth:`generate_unit` calls (FR-019).

        For ``decision_chain`` units the document keys consumed by the unit
        are released back to the available pool so that future units may draw
        from overlapping time windows if needed.

        Parameters
        ----------
        unit_id:
            The unit_id to mark as complete.

        Raises
        ------
        KeyError
            If ``unit_id`` was never generated by this generator.
        """
        if unit_id not in self._assignments:
            raise KeyError(f"Unknown unit_id: {unit_id!r}. Generate the unit first.")
        self._completed.add(unit_id)
        # Release assignment slot
        self._assignments[unit_id] = None

        # Release verify_finding claim mapping
        claim_record = self._unit_to_claim.get(unit_id)
        if claim_record is not None:
            claim_id = str(claim_record.get("claim_id", ""))
            if self._claim_to_unit.get(claim_id) == unit_id:
                del self._claim_to_unit[claim_id]

        # Release decision_chain doc keys
        doc_keys = self._unit_to_doc_keys.pop(unit_id, frozenset())
        self._active_dc_keys -= doc_keys

    def get_status(self) -> dict[str, int]:
        """Return a summary of generator state.

        Returns
        -------
        dict[str, int]
            Dictionary with keys:

            - ``total_claims``: number of filtered verify_finding claims.
            - ``total_relationships``: number of filtered relationship records.
            - ``total_generated``: number of units ever generated.
            - ``total_assigned``: number currently assigned to a worker.
            - ``total_completed``: number fully completed.
        """
        total_assigned = sum(
            1
            for unit_id, worker in self._assignments.items()
            if worker is not None and unit_id not in self._completed
        )
        return {
            "total_claims": len(self._claims),
            "total_relationships": len(self._relationships),
            "total_generated": len(self._assignments),
            "total_assigned": total_assigned,
            "total_completed": len(self._completed),
        }

    # ------------------------------------------------------------------
    # Private dispatch methods
    # ------------------------------------------------------------------

    def _generate_verify_finding(self) -> WorkUnit:
        """Generate the next available ``verify_finding`` work unit.

        Iterates through the internal claims list looking for a claim that has
        no currently-assigned (or completed) work unit.

        Returns
        -------
        WorkUnit
            A fully-populated verify_finding work unit.

        Raises
        ------
        NoAvailableUnitsError
            If all claims have active assignments or are already completed.
        """
        for claim in self._claims:
            claim_id = str(claim.get("claim_id", ""))
            # Skip if this claim already has a live (unfinished) unit
            if claim_id in self._claim_to_unit:
                existing_unit_id = self._claim_to_unit[claim_id]
                if existing_unit_id not in self._completed:
                    continue  # still assigned or in-flight

            unit = self._build_verify_unit(claim)
            # Register assignment tracking
            self._assignments[unit.unit_id] = None  # generated, not yet assigned
            self._unit_to_claim[unit.unit_id] = claim
            self._claim_to_unit[claim_id] = unit.unit_id
            return unit

        raise NoAvailableUnitsError(
            "No available claims — all claims are currently assigned or completed. "
            "Submit results to free up capacity."
        )

    def _generate_decision_chain(self) -> WorkUnit:
        """Generate the next available ``decision_chain`` work unit.

        Selects a 30-day time window with at least 20 unassigned document
        references, then builds a unit from up to 50 of those references.

        Returns
        -------
        WorkUnit
            A fully-populated decision_chain work unit.

        Raises
        ------
        NoAvailableUnitsError
            If no 30-day window contains at least 20 unassigned document
            references.
        """
        window_start, doc_refs = self._select_time_window()
        unit = self._build_decision_chain_unit(window_start, doc_refs)

        # Track which doc keys this unit consumes
        consumed_keys: frozenset[str] = frozenset(
            ref["efta_number"] for ref in doc_refs
        )
        self._assignments[unit.unit_id] = None
        self._unit_to_doc_keys[unit.unit_id] = consumed_keys
        self._active_dc_keys |= consumed_keys
        return unit

    # ------------------------------------------------------------------
    # decision_chain private helpers
    # ------------------------------------------------------------------

    def _select_time_window(self) -> tuple[date, list[DocRef]]:
        """Select a 30-day time window containing enough unassigned doc refs.

        Groups all relationship records that have a usable EFTA number and a
        parseable ``date`` field into 30-day buckets anchored at the earliest
        date in the dataset.  The buckets are evaluated in chronological order;
        the first bucket with at least :data:`_DC_BATCH_MIN` unassigned
        documents is selected.  Up to :data:`_DC_BATCH_MAX` documents are
        returned from the selected bucket.

        Returns
        -------
        tuple[date, list[DocRef]]
            A tuple of ``(window_start_date, doc_refs)`` where
            ``window_start_date`` is the :class:`~datetime.date` that begins
            the selected 30-day window and ``doc_refs`` is a list of between
            :data:`_DC_BATCH_MIN` and :data:`_DC_BATCH_MAX` document reference
            dicts.

        Raises
        ------
        NoAvailableUnitsError
            If no window meets the minimum document count requirement, or if
            the relationships list is empty.
        """
        if not self._relationships:
            raise NoAvailableUnitsError(
                "No relationship records loaded — cannot generate decision_chain units. "
                "Ensure knowledge_graph_relationships.json is present in the data/ directory."
            )

        # Build list of (parsed_date, doc_ref) pairs, skipping records without
        # a usable EFTA number or a parseable date.
        dated_refs: list[tuple[date, DocRef]] = []
        for rel in self._relationships:
            doc_ref = self._relationship_to_doc_ref(rel)
            if doc_ref is None:
                continue  # no usable EFTA or URL
            date_str = str(rel.get("date", "")).strip()
            if not date_str:
                continue
            try:
                # Support both full ISO 8601 datetimes and plain dates
                parsed_date = _parse_date_field(date_str)
            except ValueError:
                continue  # skip records with unparseable dates

            # Skip doc refs currently consumed by an active unit (FR-018)
            efta_key = doc_ref["efta_number"]
            if efta_key in self._active_dc_keys:
                continue

            dated_refs.append((parsed_date, doc_ref))

        if not dated_refs:
            raise NoAvailableUnitsError(
                "No unassigned relationship records with usable EFTA numbers and "
                "dates — cannot generate decision_chain units."
            )

        # Determine bucket boundaries: 30-day windows starting at the minimum date
        min_date = min(d for d, _ in dated_refs)

        # Group into 30-day windows
        buckets: dict[date, list[DocRef]] = {}
        for parsed_date, doc_ref in dated_refs:
            delta_days = (parsed_date - min_date).days
            bucket_index = delta_days // _DC_WINDOW_DAYS
            bucket_start = min_date + timedelta(days=bucket_index * _DC_WINDOW_DAYS)
            buckets.setdefault(bucket_start, []).append(doc_ref)

        # Find the first eligible bucket (chronological order, ≥ min docs)
        for bucket_start in sorted(buckets):
            candidates = buckets[bucket_start]
            if len(candidates) >= _DC_BATCH_MIN:
                selected = candidates[:_DC_BATCH_MAX]
                return bucket_start, selected

        raise NoAvailableUnitsError(
            f"No 30-day time window contains at least {_DC_BATCH_MIN} unassigned "
            "document references. Submit completed units or add more relationship data."
        )

    def _relationship_to_doc_ref(
        self, rel: RelationshipRecord
    ) -> DocRef | None:
        """Convert a relationship record to a document reference dict.

        Attempts to extract an EFTA number from the relationship record by
        checking each candidate field name in :data:`_EFTA_FIELD_CANDIDATES`.
        If a valid EFTA number is found, constructs the DOJ PDF URL and returns
        a doc ref dict.  Returns ``None`` if no usable EFTA number is found or
        if the EFTA format is invalid.

        Parameters
        ----------
        rel:
            A single relationship record from the knowledge graph.

        Returns
        -------
        DocRef | None
            A doc ref dict with ``efta_number``, ``url``, and any additional
            fields from the relationship record; or ``None`` if the record
            cannot produce a valid doc ref.
        """
        efta_str: str | None = None
        for field_name in _EFTA_FIELD_CANDIDATES:
            candidate = rel.get(field_name)
            if isinstance(candidate, str) and candidate.startswith("EFTA") and len(candidate) == 12:
                if candidate[4:].isdigit():
                    efta_str = candidate
                    break

        if efta_str is None:
            return None

        # Check for excluded file types (EC-002)
        for suffix in _EXCLUDED_SUFFIXES:
            if efta_str.lower().endswith(suffix):
                return None

        # Build the DOJ URL; dataset defaults to 9 (most common) if not
        # present in the relationship record.
        dataset: int = int(rel.get("dataset", rel.get("primary_dataset", 9)))
        efta_int = int(efta_str[4:])
        url = self._url_builder(efta_int, dataset)

        doc_ref: DocRef = {
            "efta_number": efta_str,
            "url": url,
        }
        # Preserve additional relationship metadata that may help the worker
        for extra_key in ("date", "relationship_type", "source_entity", "target_entity"):
            value = rel.get(extra_key)
            if value is not None:
                doc_ref[extra_key] = value

        return doc_ref

    def _build_decision_chain_unit(
        self,
        window_start: date,
        doc_refs: list[DocRef],
    ) -> WorkUnit:
        """Construct a ``decision_chain`` :class:`WorkUnit` from selected doc refs.

        Parameters
        ----------
        window_start:
            The first day of the selected 30-day time window.
        doc_refs:
            List of document reference dicts, between 20 and 50 entries.

        Returns
        -------
        WorkUnit
            A fully-populated and validated decision_chain work unit.
        """
        unit_id = f"dc-{uuid.uuid4().hex[:12]}"

        window_end: date = window_start + timedelta(days=_DC_WINDOW_DAYS)
        tw_start_str = window_start.isoformat()
        tw_end_str = window_end.isoformat()

        deadline = (
            datetime.now(tz=timezone.utc) + timedelta(hours=_DEADLINE_HOURS)
        ).isoformat()

        instructions = (
            "You have been provided with a batch of 20–50 DOJ document references "
            "from a single 30-day time window. Using the PDF URLs in "
            "`input.data[*].url`, fetch and read each document. Map the "
            "communication graph: identify who communicated with whom, when, and "
            "on what topic. Return a structured JSON result with fields: "
            "`communication_graph` (list of objects, each with `from`, `to`, "
            "`when` (ISO 8601 date), `topic`, and `efta_reference`) and "
            "`patterns_observed` (string summarising recurring patterns). "
            f"{DE_ANON_PROHIBITION}"
        )

        input_dict: dict[str, Any] = {
            "time_window_start": tw_start_str,
            "time_window_end": tw_end_str,
            "data": list(doc_refs),
        }

        return WorkUnit(
            unit_id=unit_id,
            type="decision_chain",
            path=_DC_PATH,
            difficulty=_DC_DIFFICULTY,
            scaling=_DC_SCALING,
            optimal_batch=_DC_OPTIMAL_BATCH,
            input=input_dict,
            instructions=instructions,
            constraints=dict(_DC_CONSTRAINTS),  # copy so caller can't mutate template
            deadline=deadline,
            source_verified=False,  # EC-006: relationship data not independently verified
        )

    # ------------------------------------------------------------------
    # verify_finding private helpers
    # ------------------------------------------------------------------

    def _build_unit(self, claim: ClaimRecord) -> WorkUnit:
        """Backwards-compatible alias for :meth:`_build_verify_unit`.

        Kept so that code and tests written against US-005 that reference
        ``_build_unit`` continue to work after the US-006 rename.

        Parameters
        ----------
        claim:
            A validated claim dict.

        Returns
        -------
        WorkUnit
            A fully-populated verify_finding work unit.
        """
        return self._build_verify_unit(claim)

    def _build_verify_unit(self, claim: ClaimRecord) -> WorkUnit:
        """Construct a ``WorkUnit`` from a single claim record.

        Parameters
        ----------
        claim:
            A validated claim dict containing ``claim``, ``cited_eftas``, and
            ``primary_datasets``.

        Returns
        -------
        WorkUnit
            A fully-populated and validated work unit.

        Raises
        ------
        ValueError
            If the claim dict is missing required keys or contains invalid data.
        """
        unit_id = f"verify-{uuid.uuid4().hex[:12]}"
        cited_eftas: list[str] = claim.get("cited_eftas", [])
        primary_datasets: list[int] = claim.get("primary_datasets", [])

        if not cited_eftas:
            raise ValueError(
                f"Claim {claim.get('claim_id')!r} has no cited_eftas — cannot build unit."
            )
        if len(cited_eftas) != len(primary_datasets):
            raise ValueError(
                f"Claim {claim.get('claim_id')!r}: cited_eftas length ({len(cited_eftas)}) "
                f"must match primary_datasets length ({len(primary_datasets)})."
            )

        efta_urls: list[str] = []
        for efta_str, dataset in zip(cited_eftas, primary_datasets):
            # Parse the integer portion from "EFTA00039186" → 39186
            efta_int = self._parse_efta_int(efta_str)
            url = self._url_builder(efta_int, dataset)
            efta_urls.append(url)

        claim_text: str = str(claim.get("claim", "")).strip()
        source_verified: bool = bool(claim.get("source_verified", False))

        deadline = (
            datetime.now(tz=timezone.utc) + timedelta(hours=_DEADLINE_HOURS)
        ).isoformat()

        instructions = (
            "Review the cited DOJ PDF document(s) at the URLs provided in "
            "`input.efta_urls`. Determine whether the document supports, "
            "disputes, or provides insufficient evidence for the claim in "
            "`input.claim`. Return a structured JSON result with fields: "
            "`verdict` (one of: verified, disputed, insufficient_evidence), "
            "`reasoning` (string), and `citations` (list of objects with "
            "`efta_number`, optional `page_number`, and optional `quote`). "
            f"{DE_ANON_PROHIBITION}"
        )

        input_dict: dict[str, Any] = {
            "claim": claim_text,
            "cited_eftas": cited_eftas,
            "efta_urls": efta_urls,
            "source_verified": source_verified,
        }

        return WorkUnit(
            unit_id=unit_id,
            type="verify_finding",
            path=_VERIFY_PATH,
            difficulty=_VERIFY_DIFFICULTY,
            scaling=_VERIFY_SCALING,
            optimal_batch=_VERIFY_OPTIMAL_BATCH,
            input=input_dict,
            instructions=instructions,
            constraints=dict(_VERIFY_CONSTRAINTS),  # copy so caller can't mutate the template
            deadline=deadline,
            source_verified=source_verified,
        )

    # ------------------------------------------------------------------
    # Shared private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json_list(path: Path, label: str = "data") -> list[dict[str, Any]]:
        """Load and parse a JSON file containing a top-level array.

        Parameters
        ----------
        path:
            Path to the JSON file.
        label:
            Human-readable label used in error messages (e.g. ``"claims"``).

        Returns
        -------
        list[dict[str, Any]]
            Parsed list of dicts.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If the file is not valid JSON or the top-level value is not a list.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"{label.capitalize()} file not found: {path}. "
                f"Create the file or pass a {label} list directly."
            )
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {label} file {path}: {exc}") from exc

        if not isinstance(data, list):
            raise ValueError(
                f"{label.capitalize()} file {path} must contain a JSON array at the "
                f"top level, got {type(data).__name__}"
            )
        return data  # type: ignore[return-value]

    # Keep the old name as an alias so any existing code (tests) that calls
    # _load_claims still works.
    @staticmethod
    def _load_claims(path: Path) -> list[ClaimRecord]:
        """Load and parse a JSON claims file.

        Deprecated alias for :meth:`_load_json_list`.  Kept for backwards
        compatibility with tests written against US-005.

        Parameters
        ----------
        path:
            Path to the JSON claims file.

        Returns
        -------
        list[ClaimRecord]
            Parsed list of claim dicts.
        """
        return WorkUnitGenerator._load_json_list(path, label="claims")

    @staticmethod
    def _filter_claims(claims: list[ClaimRecord]) -> list[ClaimRecord]:
        """Remove claims that reference DS10 or image/video content (EC-002).

        DS10 is the media-files dataset.  Any claim whose ``primary_datasets``
        list contains 10 is excluded.  Any claim whose cited EFTA filenames
        suggest image or video content (detected by suffix) is also excluded.

        Parameters
        ----------
        claims:
            Raw list of claim dicts as loaded from JSON.

        Returns
        -------
        list[ClaimRecord]
            Filtered claims that are safe to distribute as work units.
        """
        filtered: list[ClaimRecord] = []
        for claim in claims:
            datasets: list[int] = claim.get("primary_datasets", [])
            if _DS10_DATASET in datasets:
                continue  # EC-002: no DS10 content

            # Check for excluded file suffixes in any EFTA reference context
            # (In practice EFTA URLs always end in .pdf; this is a defence-in-depth check)
            eftas: list[str] = claim.get("cited_eftas", [])
            skip = False
            for efta in eftas:
                for suffix in _EXCLUDED_SUFFIXES:
                    if efta.lower().endswith(suffix):
                        skip = True
                        break
                if skip:
                    break
            if skip:
                continue

            filtered.append(claim)
        return filtered

    @staticmethod
    def _filter_relationships(
        relationships: list[RelationshipRecord],
    ) -> list[RelationshipRecord]:
        """Remove relationship records that reference DS10 or media content (EC-002).

        Excluded records are those where any EFTA candidate field value ends
        with an excluded suffix, or where a ``dataset`` field value equals 10.

        Parameters
        ----------
        relationships:
            Raw list of relationship dicts.

        Returns
        -------
        list[RelationshipRecord]
            Filtered relationships safe to use in work units.
        """
        filtered: list[RelationshipRecord] = []
        for rel in relationships:
            # Exclude DS10 media dataset
            dataset_val = rel.get("dataset", rel.get("primary_dataset"))
            if dataset_val is not None and int(dataset_val) == _DS10_DATASET:
                continue

            # Check EFTA candidate fields for excluded suffixes
            skip = False
            for field_name in _EFTA_FIELD_CANDIDATES:
                efta_val = rel.get(field_name, "")
                if isinstance(efta_val, str):
                    for suffix in _EXCLUDED_SUFFIXES:
                        if efta_val.lower().endswith(suffix):
                            skip = True
                            break
                if skip:
                    break
            if skip:
                continue

            filtered.append(rel)
        return filtered

    @staticmethod
    def _parse_efta_int(efta_str: str) -> int:
        """Parse an EFTA string like ``'EFTA00039186'`` into its integer part.

        Parameters
        ----------
        efta_str:
            EFTA string in the format ``EFTA{8 digits}``.

        Returns
        -------
        int
            The numeric portion of the EFTA identifier.

        Raises
        ------
        ValueError
            If the string does not conform to the expected format.
        """
        if not efta_str.startswith("EFTA") or len(efta_str) != 12:
            raise ValueError(
                f"EFTA string must be in format 'EFTA00000000', got {efta_str!r}"
            )
        numeric_part = efta_str[4:]
        if not numeric_part.isdigit():
            raise ValueError(
                f"EFTA numeric portion must be all digits, got {numeric_part!r}"
            )
        return int(numeric_part)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_date_field(date_str: str) -> date:
    """Parse a date string that may be a full ISO 8601 datetime or a plain date.

    Accepts strings in the following formats:
    - ``"YYYY-MM-DD"``
    - ``"YYYY-MM-DDTHH:MM:SS"`` (with optional timezone offset)
    - ``"YYYY-MM-DDTHH:MM:SS.ffffff"``

    Parameters
    ----------
    date_str:
        The date or datetime string to parse.

    Returns
    -------
    date
        The :class:`~datetime.date` portion of the parsed value.

    Raises
    ------
    ValueError
        If the string cannot be parsed as a date or datetime.
    """
    # Try plain date first
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        pass
    # Try full datetime (strip timezone offset if present for compatibility)
    try:
        # Python 3.10 fromisoformat does not handle 'Z' suffix; normalise
        normalised = date_str.rstrip("Z").split("+")[0].split("-")
        # Rejoin — handle negative UTC offsets carefully by only stripping trailing tz
        # Fall back to datetime.fromisoformat after normalising 'Z'
        dt_str = date_str
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str).date()
    except ValueError as exc:
        raise ValueError(
            f"Cannot parse date field value {date_str!r}: expected ISO 8601 date "
            "or datetime string."
        ) from exc
