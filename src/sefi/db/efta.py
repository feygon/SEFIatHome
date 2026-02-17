"""EFTA URL builder and gap resolution module for SEFI@Home.

This module provides:

* :func:`build_url` — constructs the canonical DOJ PDF URL for an EFTA number
  and dataset number.
* :func:`resolve_efta` — attempts to resolve an EFTA number to a valid DOJ URL
  by trying the primary dataset, then N-1, then N+1 (gap resolution algorithm).
* :func:`get_primary_dataset` — looks up the primary dataset for an EFTA number
  from the ``efta_mapping`` SQLite working table.
* :class:`ResolutionResult` — Pydantic model capturing the outcome of a
  resolution attempt.
* :class:`EftaNumber` — Pydantic model with a field validator that enforces the
  ``^EFTA\\d{8}$`` format.
* :class:`EftaUrl` — Pydantic model with a field validator that enforces the
  canonical DOJ PDF URL pattern.

URL format (exact):
    ``https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf``

where ``{N}`` is a dataset number between 1 and 12 (inclusive) and
``{XXXXXXXX}`` is the EFTA number zero-padded to exactly 8 digits.

Gap resolution order:
    ``[primary, primary - 1, primary + 1]``

Dataset numbers below 1 or above 12 are silently skipped.

Network access is entirely injectable: pass a ``check_url_exists`` callable so
that unit tests can substitute a stub without making real HTTP calls.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Callable

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Regex that a valid EFTA format string must match.
_EFTA_RE: re.Pattern[str] = re.compile(r"^EFTA\d{8}$")

#: Regex that a valid DOJ PDF URL must match.
_URL_RE: re.Pattern[str] = re.compile(
    r"^https://www\.justice\.gov/epstein/files/DataSet%20(\d+)/EFTA\d{8}\.pdf$"
)

#: Inclusive lower bound for valid dataset numbers.
_DATASET_MIN: int = 1

#: Inclusive upper bound for valid dataset numbers.
_DATASET_MAX: int = 12

#: Base URL template; ``{ds}`` is the dataset number, ``{num}`` is the 8-digit
#: zero-padded EFTA integer.
_URL_TEMPLATE: str = (
    "https://www.justice.gov/epstein/files/DataSet%20{ds}/EFTA{num:08d}.pdf"
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ResolutionResult(BaseModel):
    """Outcome of an EFTA gap-resolution attempt.

    Attributes:
        found: ``True`` if the document was located in at least one dataset.
        url: The DOJ PDF URL where the document was found, or ``None`` if not
            found.
        dataset: The dataset number in which the document was found, or
            ``None`` if not found.
        was_adjacent: ``True`` when the document was found in a dataset *other*
            than the primary dataset (i.e. N-1 or N+1).
        genuinely_missing: ``True`` when the document could not be found in the
            primary dataset or either adjacent dataset.
    """

    found: bool
    url: str | None = None
    dataset: int | None = None
    was_adjacent: bool = False
    genuinely_missing: bool = False


class EftaNumber(BaseModel):
    """Validated EFTA format string.

    The ``value`` field must match the pattern ``^EFTA\\d{8}$``
    (e.g. ``EFTA00039186``).  A :class:`ValueError` is raised on
    instantiation if the value does not conform.

    Attributes:
        value: The validated EFTA format string.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _validate_efta_format(cls, v: str) -> str:
        """Reject strings that do not match ``^EFTA\\d{8}$``.

        Args:
            v: The candidate EFTA format string.

        Returns:
            The validated string, unchanged.

        Raises:
            ValueError: If *v* does not match the expected pattern.
        """
        if not _EFTA_RE.match(v):
            raise ValueError(
                f"Invalid EFTA format string: '{v}'. "
                "Expected format: EFTA followed by exactly 8 digits (e.g. EFTA00039186)."
            )
        return v


class EftaUrl(BaseModel):
    """Validated DOJ PDF URL for an EFTA document.

    The ``value`` field must match the pattern::

        https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf

    where ``{N}`` is a dataset number between 1 and 12 and ``{XXXXXXXX}`` is
    an 8-digit zero-padded EFTA integer.

    Attributes:
        value: The validated URL string.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _validate_url_format(cls, v: str) -> str:
        """Reject strings that do not match the expected DOJ PDF URL pattern.

        Args:
            v: The candidate URL string.

        Returns:
            The validated URL string, unchanged.

        Raises:
            ValueError: If *v* does not match the pattern or if the embedded
                dataset number is outside the range 1–12.
        """
        m = _URL_RE.match(v)
        if not m:
            raise ValueError(
                f"Invalid EFTA URL: '{v}'. "
                "Expected pattern: "
                "https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf"
            )
        dataset_num = int(m.group(1))
        if not (_DATASET_MIN <= dataset_num <= _DATASET_MAX):
            raise ValueError(
                f"Invalid dataset number {dataset_num} in URL '{v}'. "
                f"Dataset number must be between {_DATASET_MIN} and {_DATASET_MAX}."
            )
        return v


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def build_url(efta_number: int, dataset: int) -> str:
    """Construct the canonical DOJ PDF URL for an EFTA document.

    The URL format is exactly::

        https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf

    where ``{N}`` is the *dataset* argument and ``{XXXXXXXX}`` is
    *efta_number* zero-padded to 8 digits.

    Args:
        efta_number: The numeric EFTA identifier (e.g. ``39186``).
        dataset: The DOJ dataset number (1–12).

    Returns:
        The fully-formed DOJ PDF URL string.

    Example::

        >>> build_url(39186, 9)
        'https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf'
    """
    return _URL_TEMPLATE.format(ds=dataset, num=efta_number)


def get_primary_dataset(efta_number: int, conn: sqlite3.Connection) -> int | None:
    """Look up the primary dataset for *efta_number* in the ``efta_mapping`` table.

    The ``efta_mapping`` table is populated by :class:`~sefi.db.ingest.IngestManager`
    from ``efta_dataset_mapping.json``.  This function performs a single
    parameterised query — no string interpolation — to find the dataset whose
    ``range_start <= efta_number <= range_end``.

    If multiple rows match (e.g. overlapping ranges), the one with the smallest
    ``dataset_number`` is returned.

    Args:
        efta_number: The numeric EFTA identifier to look up.
        conn: An open :class:`sqlite3.Connection` that has the ``efta_mapping``
            table available.

    Returns:
        The primary dataset number as an ``int``, or ``None`` if *efta_number*
        falls outside all known ranges.
    """
    cursor = conn.execute(
        """
        SELECT dataset_number
        FROM   efta_mapping
        WHERE  range_start IS NOT NULL
          AND  range_end   IS NOT NULL
          AND  range_start <= ?
          AND  range_end   >= ?
        ORDER BY dataset_number ASC
        LIMIT 1
        """,
        (efta_number, efta_number),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return int(row[0])


def resolve_efta(
    efta_number: int,
    primary_dataset: int,
    check_url_exists: Callable[[str], bool],
) -> ResolutionResult:
    """Attempt to resolve an EFTA number to a valid DOJ PDF URL.

    The resolution algorithm tries datasets in the fixed order::

        [primary_dataset, primary_dataset - 1, primary_dataset + 1]

    For each candidate dataset, the function:

    1. Skips the dataset silently if the number is below 1 or above 12.
    2. Constructs the canonical DOJ PDF URL via :func:`build_url`.
    3. Calls *check_url_exists* to test whether the document is accessible.

    The first dataset for which *check_url_exists* returns ``True`` determines
    the result.  If no dataset yields a hit the document is declared genuinely
    missing.

    Args:
        efta_number: The numeric EFTA identifier to resolve.
        primary_dataset: The dataset number expected to contain this EFTA.
        check_url_exists: A callable that takes a URL string and returns
            ``True`` if the document exists at that URL, ``False`` otherwise.
            In production this performs an HTTP HEAD request; in tests it
            should be a stub/mock so no network calls are made.

    Returns:
        A :class:`ResolutionResult` describing the outcome.

    Example (found in primary)::

        result = resolve_efta(39186, 9, lambda url: True)
        # result.found is True, result.was_adjacent is False

    Example (genuinely missing)::

        result = resolve_efta(99999, 9, lambda url: False)
        # result.found is False, result.genuinely_missing is True
    """
    datasets_to_try: list[int] = [
        primary_dataset,
        primary_dataset - 1,
        primary_dataset + 1,
    ]

    for ds in datasets_to_try:
        if ds < _DATASET_MIN or ds > _DATASET_MAX:
            continue
        url = build_url(efta_number, ds)
        if check_url_exists(url):
            return ResolutionResult(
                found=True,
                url=url,
                dataset=ds,
                was_adjacent=(ds != primary_dataset),
                genuinely_missing=False,
            )

    return ResolutionResult(
        found=False,
        url=None,
        dataset=None,
        was_adjacent=False,
        genuinely_missing=True,
    )
