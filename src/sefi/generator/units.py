"""Work unit dataclass and generator for SEFI@Home verify_finding type.

This module implements the ``WorkUnit`` dataclass and the ``WorkUnitGenerator``
class.  Each generated ``verify_finding`` unit contains a single claim drawn
from rhowardstone report data, one or more cited EFTA numbers, the
corresponding resolved DOJ PDF URLs, and mandatory instruction text that
includes the de-anonymization prohibition required by EC-007.

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
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
# WorkUnit dataclass
# ---------------------------------------------------------------------------

@dataclass
class WorkUnit:
    """A self-contained unit of analytical work for a SEFI@Home volunteer.

    The ``verify_finding`` type contains a single claim drawn from rhowardstone
    reports together with cited EFTA numbers and resolved DOJ PDF URLs.  The
    worker fetches each PDF directly from justice.gov and returns a structured
    verdict.

    Attributes
    ----------
    unit_id:
        Unique identifier for this work unit.  Format: ``"verify-{hex12}"``.
    type:
        Work unit type string.  For this module: ``"verify_finding"``.
    path:
        Research path number (1–5).  Verify_finding uses path 5 (Verification).
    difficulty:
        Difficulty label — one of ``"low"``, ``"medium"``, or ``"high"``.
    scaling:
        Scaling behaviour — one of ``"linear"``, ``"multiplying"``,
        ``"plateau"``, or ``"aggregation"``.
    optimal_batch:
        Human-readable description of the recommended batch size.
    input:
        Dictionary containing claim text, cited EFTA numbers, resolved DOJ PDF
        URLs, and ``source_verified`` provenance flag.
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

        # input — dict with required keys for verify_finding
        if not isinstance(self.input, dict):
            raise TypeError("input must be a dict")
        if self.type == "verify_finding":
            self._validate_verify_input(self.input)

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


# ---------------------------------------------------------------------------
# Claim record type alias
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


# ---------------------------------------------------------------------------
# WorkUnitGenerator
# ---------------------------------------------------------------------------

class WorkUnitGenerator:
    """Generates ``verify_finding`` work units from a pre-loaded claims list.

    Each call to ``generate_unit()`` returns a fresh ``WorkUnit`` built from
    the next available unassigned claim.  The generator cycles through claims
    in order, skipping those that are currently assigned or already completed.

    Assignment state is tracked in two in-memory structures:

    - ``_assignments``: ``dict[str, str | None]`` — maps unit_id to the
      worker_id that claimed it (or ``None`` if unassigned but generated).
    - ``_completed``: ``set[str]`` — unit_ids that have been marked complete.

    A ``unit_id`` → ``ClaimRecord`` index (``_unit_to_claim``) is maintained so
    that ``mark_unit_complete`` can locate the underlying claim.

    Parameters
    ----------
    claims:
        List of claim dicts.  Each dict must contain at minimum:
        ``claim``, ``cited_eftas``, and ``primary_datasets``.
        If not provided, the generator attempts to load from ``claims_path``.
    claims_path:
        Path to a JSON file containing a list of claim dicts.  Used only when
        ``claims`` is not supplied.  Defaults to ``data/sample_claims.json``
        relative to the current working directory.
    url_builder:
        Callable that takes ``(efta_number: int, dataset: int)`` and returns
        a DOJ PDF URL string.  Defaults to the ``build_url`` function from
        ``sefi.db.efta``.  Injectable for testing without network access.
    """

    def __init__(
        self,
        claims: list[ClaimRecord] | None = None,
        claims_path: Path | str | None = None,
        url_builder: Any = None,
    ) -> None:
        """Initialise the generator with a list of claims.

        Parameters
        ----------
        claims:
            Pre-loaded list of claim dicts.  Takes precedence over
            ``claims_path`` if both are provided.
        claims_path:
            Path to the JSON claims file.  Falls back to
            ``data/sample_claims.json`` if neither ``claims`` nor a valid
            ``claims_path`` is given.
        url_builder:
            Callable ``(efta_int: int, dataset: int) -> str`` for DOJ URL
            construction.  Defaults to ``sefi.db.efta.build_url``.
        """
        if url_builder is None:
            from sefi.db.efta import build_url  # local import to allow mocking
            self._url_builder = build_url
        else:
            self._url_builder = url_builder

        if claims is not None:
            raw_claims = claims
        else:
            if claims_path is None:
                claims_path = Path("data") / "sample_claims.json"
            raw_claims = self._load_claims(Path(claims_path))

        # Filter out any claims referencing DS10 or excluded file types (EC-002)
        self._claims: list[ClaimRecord] = self._filter_claims(raw_claims)

        # unit_id → worker_id (None means generated but unassigned)
        self._assignments: dict[str, str | None] = {}

        # unit_ids that have been fully completed
        self._completed: set[str] = set()

        # unit_id → claim record (for lookup in mark_unit_complete)
        self._unit_to_claim: dict[str, ClaimRecord] = {}

        # claim_id → unit_id (to detect if a claim already has a live unit)
        self._claim_to_unit: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_unit(self) -> WorkUnit:
        """Generate and return the next available ``verify_finding`` work unit.

        Iterates through the internal claims list looking for a claim that has
        no currently-assigned (or completed) work unit.  A new ``WorkUnit`` is
        created and tracked before being returned.

        Returns
        -------
        WorkUnit
            A fully-populated and validated work unit.

        Raises
        ------
        RuntimeError
            If all claims have active assignments or are already completed.
        """
        for claim in self._claims:
            claim_id = str(claim.get("claim_id", ""))
            # Skip if this claim already has a live (unfinished) unit
            if claim_id in self._claim_to_unit:
                existing_unit_id = self._claim_to_unit[claim_id]
                if existing_unit_id not in self._completed:
                    continue  # still assigned or in-flight

            unit = self._build_unit(claim)
            # Register assignment tracking
            self._assignments[unit.unit_id] = None  # generated, not yet assigned
            self._unit_to_claim[unit.unit_id] = claim
            self._claim_to_unit[claim_id] = unit.unit_id
            return unit

        raise RuntimeError(
            "No available claims — all claims are currently assigned or completed. "
            "Submit results to free up capacity."
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

        After this call the unit will not appear in subsequent ``generate_unit``
        calls (FR-019).

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
        # Release the assignment slot
        self._assignments[unit_id] = None
        # Remove claim-to-unit mapping so the claim could potentially be
        # re-assigned in post-MVP workflows (e.g., for quorum re-verification).
        claim_record = self._unit_to_claim.get(unit_id)
        if claim_record is not None:
            claim_id = str(claim_record.get("claim_id", ""))
            if self._claim_to_unit.get(claim_id) == unit_id:
                del self._claim_to_unit[claim_id]

    def get_status(self) -> dict[str, int]:
        """Return a summary of generator state.

        Returns
        -------
        dict[str, int]
            Dictionary with keys:
            - ``total_claims``: number of filtered claims available.
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
            "total_generated": len(self._assignments),
            "total_assigned": total_assigned,
            "total_completed": len(self._completed),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_claims(path: Path) -> list[ClaimRecord]:
        """Load and parse a JSON file containing an array of claim dicts.

        Parameters
        ----------
        path:
            Path to the JSON claims file.

        Returns
        -------
        list[ClaimRecord]
            Parsed list of claim dicts.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If the file is not valid JSON or the top-level value is not a list.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"Claims file not found: {path}. "
                "Create data/sample_claims.json or pass a claims list directly."
            )
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in claims file {path}: {exc}") from exc

        if not isinstance(data, list):
            raise ValueError(
                f"Claims file {path} must contain a JSON array at the top level, "
                f"got {type(data).__name__}"
            )
        return data  # type: ignore[return-value]

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

    def _build_unit(self, claim: ClaimRecord) -> WorkUnit:
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
