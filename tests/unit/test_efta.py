"""Unit tests for US-003: EFTA URL Builder & Gap Resolution.

Covers every acceptance criterion from todo/US-003.md plus key error paths
and edge cases.  All HTTP calls are mocked — no live network requests are made.
Database tests use in-memory SQLite (:memory:).

Acceptance criteria verified:
  AC1  build_url(39186, 9) == exact canonical URL (FR-014)
  AC2  Dataset numbers <1 or >12 are silently skipped (FR-016)
  AC3  EFTA found in N+1 -> ResolutionResult(found=True, was_adjacent=True) (FR-016)
  AC4  EFTA not found anywhere -> ResolutionResult(found=False, genuinely_missing=True) (FR-016)
  AC5  build_url zero-pads EFTA to exactly 8 digits (DR-012)
  AC6  EftaNumber rejects strings not matching ^EFTA\\d{8}$ (DR-011)
  AC7  EftaUrl rejects strings not matching the canonical URL pattern (DR-012)
  AC8  resolve_efta uses efta_mapping table to look up primary dataset (FR-015)
  AC9  All functions have type annotations and docstrings (NFR-002, NFR-008)
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from typing import Callable
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from sefi.db.efta import (
    EftaNumber,
    EftaUrl,
    ResolutionResult,
    build_url,
    get_primary_dataset,
    resolve_efta,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_conn_with_mapping(
    ranges: list[tuple[int, int, int]],
) -> sqlite3.Connection:
    """Return an in-memory connection with efta_mapping pre-populated.

    Args:
        ranges: List of (dataset_number, range_start, range_end) tuples.

    Returns:
        Open in-memory SQLite connection.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE efta_mapping (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_number INTEGER,
            range_start    INTEGER,
            range_end      INTEGER,
            raw_json       TEXT NOT NULL
        )
        """
    )
    for ds, start, end in ranges:
        conn.execute(
            "INSERT INTO efta_mapping (dataset_number, range_start, range_end, raw_json)"
            " VALUES (?, ?, ?, ?)",
            (ds, start, end, "{}"),
        )
    conn.commit()
    return conn


def _stub_exists(url_map: dict[str, bool]) -> Callable[[str], bool]:
    """Return a check_url_exists stub that consults *url_map*.

    URLs absent from the map return False by default.
    """
    def _check(url: str) -> bool:
        return url_map.get(url, False)
    return _check


# ---------------------------------------------------------------------------
# AC1 — build_url exact canonical URL (FR-014)
# ---------------------------------------------------------------------------


class TestBuildUrlCanonical:
    """AC1: build_url(39186, 9) returns the exact canonical DOJ PDF URL."""

    def test_exact_canonical_url(self) -> None:
        expected = "https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf"
        assert build_url(efta_number=39186, dataset=9) == expected

    def test_url_contains_percent20_not_literal_space(self) -> None:
        url = build_url(39186, 9)
        assert "%20" in url, "URL must use %20, not a literal space"
        assert " " not in url, "URL must not contain a literal space"

    def test_url_contains_percent20_not_plus(self) -> None:
        url = build_url(39186, 9)
        assert "DataSet+" not in url, "URL must not use + encoding"

    def test_url_scheme_and_host(self) -> None:
        url = build_url(39186, 9)
        assert url.startswith("https://www.justice.gov/epstein/files/")

    def test_url_ends_with_pdf(self) -> None:
        url = build_url(39186, 9)
        assert url.endswith(".pdf")


# ---------------------------------------------------------------------------
# AC5 — zero-padding to exactly 8 digits (DR-012)
# ---------------------------------------------------------------------------


class TestBuildUrlZeroPadding:
    """AC5: EFTA numbers are zero-padded to exactly 8 digits in the filename."""

    def test_single_digit_padded_to_8(self) -> None:
        url = build_url(1, 1)
        assert "EFTA00000001.pdf" in url

    def test_five_digit_padded_to_8(self) -> None:
        url = build_url(39186, 9)
        assert "EFTA00039186.pdf" in url

    def test_eight_digit_not_padded(self) -> None:
        url = build_url(12345678, 1)
        assert "EFTA12345678.pdf" in url

    def test_filename_always_has_exactly_8_efta_digits(self) -> None:
        pattern = re.compile(r"EFTA(\d+)\.pdf$")
        for num in [1, 100, 99999, 12345678]:
            url = build_url(num, 5)
            m = pattern.search(url)
            assert m is not None, f"No EFTA filename found in {url}"
            assert len(m.group(1)) == 8, (
                f"Expected 8-digit padding for {num}, got '{m.group(1)}'"
            )

    def test_dataset_number_in_url(self) -> None:
        for ds in range(1, 13):
            url = build_url(39186, ds)
            assert f"DataSet%20{ds}/" in url


# ---------------------------------------------------------------------------
# AC6 — EftaNumber validator (DR-011)
# ---------------------------------------------------------------------------


class TestEftaNumberValidator:
    """AC6: EftaNumber rejects strings not matching ^EFTA\\d{8}$."""

    def test_valid_efta_number_accepted(self) -> None:
        en = EftaNumber(value="EFTA00039186")
        assert en.value == "EFTA00039186"

    def test_valid_efta_number_all_zeros(self) -> None:
        en = EftaNumber(value="EFTA00000000")
        assert en.value == "EFTA00000000"

    def test_valid_efta_number_max_digits(self) -> None:
        en = EftaNumber(value="EFTA99999999")
        assert en.value == "EFTA99999999"

    def test_rejects_missing_prefix(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="00039186")

    def test_rejects_lowercase_efta(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="efta00039186")

    def test_rejects_fewer_than_8_digits(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="EFTA0003918")

    def test_rejects_more_than_8_digits(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="EFTA000391860")

    def test_rejects_letters_in_digit_section(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="EFTA0003918X")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="")

    def test_rejects_just_efta(self) -> None:
        with pytest.raises(ValidationError):
            EftaNumber(value="EFTA")


# ---------------------------------------------------------------------------
# AC7 — EftaUrl validator (DR-012)
# ---------------------------------------------------------------------------


class TestEftaUrlValidator:
    """AC7: EftaUrl rejects strings not matching the canonical DOJ URL pattern."""

    def test_valid_url_accepted(self) -> None:
        url = "https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf"
        eu = EftaUrl(value=url)
        assert eu.value == url

    def test_rejects_http_scheme(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="http://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf")

    def test_rejects_literal_space(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.justice.gov/epstein/files/DataSet 9/EFTA00039186.pdf")

    def test_rejects_wrong_host(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.doj.gov/epstein/files/DataSet%209/EFTA00039186.pdf")

    def test_rejects_dataset_0(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%200/EFTA00039186.pdf")

    def test_rejects_dataset_13(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%2013/EFTA00039186.pdf")

    def test_accepts_dataset_1(self) -> None:
        EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%201/EFTA00039186.pdf")

    def test_accepts_dataset_12(self) -> None:
        EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%2012/EFTA00039186.pdf")

    def test_rejects_non_pdf_extension(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.html")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="")

    def test_rejects_wrong_efta_digit_count(self) -> None:
        with pytest.raises(ValidationError):
            EftaUrl(value="https://www.justice.gov/epstein/files/DataSet%209/EFTA0039186.pdf")


# ---------------------------------------------------------------------------
# AC2 — Dataset boundary skipping (FR-016)
# ---------------------------------------------------------------------------


class TestDatasetBoundarySkipping:
    """AC2: Dataset numbers <1 or >12 are skipped silently during resolution."""

    def test_primary_dataset_1_skips_n_minus_1(self) -> None:
        """When primary=1, dataset 0 must be silently skipped (not tried)."""
        call_log: list[str] = []

        def check(url: str) -> bool:
            call_log.append(url)
            return False

        resolve_efta(39186, 1, check)
        # Should try dataset 1 and dataset 2, NOT dataset 0.
        checked_datasets = [
            int(re.search(r"DataSet%20(\d+)", u).group(1))  # type: ignore[union-attr]
            for u in call_log
        ]
        assert 0 not in checked_datasets
        assert 1 in checked_datasets
        assert 2 in checked_datasets

    def test_primary_dataset_12_skips_n_plus_1(self) -> None:
        """When primary=12, dataset 13 must be silently skipped."""
        call_log: list[str] = []

        def check(url: str) -> bool:
            call_log.append(url)
            return False

        resolve_efta(39186, 12, check)
        checked_datasets = [
            int(re.search(r"DataSet%20(\d+)", u).group(1))  # type: ignore[union-attr]
            for u in call_log
        ]
        assert 13 not in checked_datasets
        assert 12 in checked_datasets
        assert 11 in checked_datasets

    def test_mid_range_primary_tries_all_three(self) -> None:
        """When primary=5, all three of [5, 4, 6] must be tried."""
        call_log: list[str] = []

        def check(url: str) -> bool:
            call_log.append(url)
            return False

        resolve_efta(39186, 5, check)
        checked_datasets = {
            int(re.search(r"DataSet%20(\d+)", u).group(1))  # type: ignore[union-attr]
            for u in call_log
        }
        assert checked_datasets == {4, 5, 6}


# ---------------------------------------------------------------------------
# AC3 — Found in N+1 (FR-016)
# ---------------------------------------------------------------------------


class TestResolveEftaFoundAdjacent:
    """AC3: EFTA found in N+1 yields ResolutionResult(found=True, was_adjacent=True)."""

    def test_found_in_n_plus_1(self) -> None:
        primary = 5
        n_plus_1_url = build_url(39186, primary + 1)
        stub = _stub_exists({n_plus_1_url: True})  # only N+1 exists

        result = resolve_efta(39186, primary, stub)

        assert result.found is True
        assert result.was_adjacent is True
        assert result.dataset == primary + 1
        assert result.url == n_plus_1_url
        assert result.genuinely_missing is False

    def test_found_in_n_minus_1(self) -> None:
        primary = 5
        n_minus_1_url = build_url(39186, primary - 1)
        stub = _stub_exists({n_minus_1_url: True})  # only N-1 exists

        result = resolve_efta(39186, primary, stub)

        assert result.found is True
        assert result.was_adjacent is True
        assert result.dataset == primary - 1
        assert result.url == n_minus_1_url
        assert result.genuinely_missing is False

    def test_found_in_primary_not_adjacent(self) -> None:
        primary = 5
        primary_url = build_url(39186, primary)
        stub = _stub_exists({primary_url: True})

        result = resolve_efta(39186, primary, stub)

        assert result.found is True
        assert result.was_adjacent is False
        assert result.dataset == primary
        assert result.genuinely_missing is False

    def test_primary_tried_before_adjacent(self) -> None:
        """Resolution order must be [primary, N-1, N+1]."""
        primary = 5
        order: list[int] = []

        def check(url: str) -> bool:
            ds = int(re.search(r"DataSet%20(\d+)", url).group(1))  # type: ignore[union-attr]
            order.append(ds)
            return True  # accept first hit

        resolve_efta(39186, primary, check)
        assert order[0] == primary, "Primary must be tried first"

    def test_n_minus_1_tried_before_n_plus_1(self) -> None:
        """After primary, N-1 is tried before N+1."""
        primary = 5
        order: list[int] = []

        def check(url: str) -> bool:
            ds = int(re.search(r"DataSet%20(\d+)", url).group(1))  # type: ignore[union-attr]
            order.append(ds)
            return False  # never found

        resolve_efta(39186, primary, check)
        assert order == [5, 4, 6], f"Expected [5, 4, 6], got {order}"


# ---------------------------------------------------------------------------
# AC4 — Genuinely missing (FR-016)
# ---------------------------------------------------------------------------


class TestResolveEftaGenuinelyMissing:
    """AC4: EFTA not found anywhere yields ResolutionResult(found=False, genuinely_missing=True)."""

    def test_all_missing(self) -> None:
        result = resolve_efta(99999, 9, lambda url: False)

        assert result.found is False
        assert result.genuinely_missing is True
        assert result.url is None
        assert result.dataset is None
        assert result.was_adjacent is False

    def test_genuinely_missing_at_boundary_primary_1(self) -> None:
        result = resolve_efta(1, 1, lambda url: False)
        assert result.found is False
        assert result.genuinely_missing is True

    def test_genuinely_missing_at_boundary_primary_12(self) -> None:
        result = resolve_efta(1, 12, lambda url: False)
        assert result.found is False
        assert result.genuinely_missing is True


# ---------------------------------------------------------------------------
# AC8 — get_primary_dataset uses efta_mapping table (FR-015)
# ---------------------------------------------------------------------------


class TestGetPrimaryDataset:
    """AC8: resolve_efta uses efta_dataset_mapping.json (via ingest working table)."""

    def test_returns_correct_dataset_for_number_in_range(self) -> None:
        conn = _make_conn_with_mapping([(9, 35000, 45000)])
        result = get_primary_dataset(39186, conn)
        assert result == 9

    def test_returns_none_when_efta_outside_all_ranges(self) -> None:
        conn = _make_conn_with_mapping([(9, 35000, 45000)])
        result = get_primary_dataset(1, conn)
        assert result is None

    def test_returns_lowest_dataset_on_overlap(self) -> None:
        """If multiple ranges match, the smallest dataset_number is returned."""
        conn = _make_conn_with_mapping([
            (9, 35000, 45000),
            (5, 35000, 45000),  # overlapping range, lower dataset
        ])
        result = get_primary_dataset(39186, conn)
        assert result == 5

    def test_exact_range_boundary_start(self) -> None:
        conn = _make_conn_with_mapping([(9, 39186, 50000)])
        result = get_primary_dataset(39186, conn)
        assert result == 9

    def test_exact_range_boundary_end(self) -> None:
        conn = _make_conn_with_mapping([(9, 30000, 39186)])
        result = get_primary_dataset(39186, conn)
        assert result == 9

    def test_one_outside_boundary(self) -> None:
        conn = _make_conn_with_mapping([(9, 39187, 50000)])
        result = get_primary_dataset(39186, conn)
        assert result is None

    def test_null_ranges_are_skipped(self) -> None:
        """Rows with NULL range_start or range_end must not match anything."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE efta_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_number INTEGER,
                range_start    INTEGER,
                range_end      INTEGER,
                raw_json       TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO efta_mapping (dataset_number, range_start, range_end, raw_json)"
            " VALUES (?, NULL, NULL, ?)",
            (9, "{}"),
        )
        conn.commit()
        result = get_primary_dataset(39186, conn)
        assert result is None

    def test_uses_parameterised_query_not_fstring(self) -> None:
        """SQL in get_primary_dataset must not use f-strings (no injection risk)."""
        import sefi.db.efta as efta_module

        source = inspect.getsource(get_primary_dataset)
        assert "f'" not in source, "get_primary_dataset must not use f-string SQL"
        assert 'f"' not in source, "get_primary_dataset must not use f-string SQL"


# ---------------------------------------------------------------------------
# AC9 — Type annotations and docstrings (NFR-002, NFR-008)
# ---------------------------------------------------------------------------


class TestTypeAnnotationsAndDocstrings:
    """AC9: All public functions have type annotations and docstrings."""

    @pytest.mark.parametrize("fn", [build_url, get_primary_dataset, resolve_efta])
    def test_function_has_docstring(self, fn: Callable) -> None:
        assert fn.__doc__ and fn.__doc__.strip(), (
            f"{fn.__name__} must have a non-empty docstring"
        )

    @pytest.mark.parametrize("fn", [build_url, get_primary_dataset, resolve_efta])
    def test_function_has_return_annotation(self, fn: Callable) -> None:
        hints = fn.__annotations__
        assert "return" in hints, f"{fn.__name__} must have a return type annotation"

    def test_build_url_parameter_annotations(self) -> None:
        hints = build_url.__annotations__
        assert "efta_number" in hints
        assert "dataset" in hints

    def test_get_primary_dataset_parameter_annotations(self) -> None:
        hints = get_primary_dataset.__annotations__
        assert "efta_number" in hints
        assert "conn" in hints

    def test_resolve_efta_parameter_annotations(self) -> None:
        hints = resolve_efta.__annotations__
        assert "efta_number" in hints
        assert "primary_dataset" in hints
        assert "check_url_exists" in hints

    @pytest.mark.parametrize(
        "cls", [ResolutionResult, EftaNumber, EftaUrl]
    )
    def test_class_has_docstring(self, cls: type) -> None:
        assert cls.__doc__ and cls.__doc__.strip(), (
            f"{cls.__name__} must have a non-empty docstring"
        )


# ---------------------------------------------------------------------------
# ResolutionResult dataclass shape
# ---------------------------------------------------------------------------


class TestResolutionResultShape:
    """ResolutionResult must have the exact fields described in US-003."""

    def test_all_fields_present(self) -> None:
        r = ResolutionResult(found=True)
        assert hasattr(r, "found")
        assert hasattr(r, "url")
        assert hasattr(r, "dataset")
        assert hasattr(r, "was_adjacent")
        assert hasattr(r, "genuinely_missing")

    def test_default_found_false_result(self) -> None:
        r = ResolutionResult(found=False, genuinely_missing=True)
        assert r.found is False
        assert r.url is None
        assert r.dataset is None
        assert r.was_adjacent is False
        assert r.genuinely_missing is True

    def test_found_result_with_all_fields(self) -> None:
        url = build_url(39186, 9)
        r = ResolutionResult(found=True, url=url, dataset=9, was_adjacent=False)
        assert r.found is True
        assert r.url == url
        assert r.dataset == 9


# ---------------------------------------------------------------------------
# Integration: check_url_exists is injectable / no live HTTP calls
# ---------------------------------------------------------------------------


class TestCheckUrlExistsInjectable:
    """check_url_exists must be injectable — no hardcoded HTTP calls in resolve_efta."""

    def test_mock_callable_is_called(self) -> None:
        mock_check = MagicMock(return_value=False)
        resolve_efta(39186, 9, mock_check)
        assert mock_check.called

    def test_no_requests_import_in_efta_module(self) -> None:
        """efta.py must not directly import requests or urllib at module level."""
        import sefi.db.efta as efta_module

        # Check the module's source for hard-coded HTTP imports
        source = inspect.getsource(efta_module)
        assert "import requests" not in source, (
            "efta.py must not import requests (use injectable check_url_exists)"
        )
        assert "urllib.request.urlopen" not in source, (
            "efta.py must not call urlopen directly"
        )

    def test_resolve_efta_does_not_import_http_libs(self) -> None:
        """The resolve_efta function source must not reference HTTP client calls."""
        source = inspect.getsource(resolve_efta)
        for bad in ("requests.head", "requests.get", "urlopen", "http.client"):
            assert bad not in source, (
                f"resolve_efta must not hardcode '{bad}' — use injectable callable"
            )

    def test_stub_returning_true_gives_found_result(self) -> None:
        result = resolve_efta(39186, 5, lambda url: True)
        assert result.found is True

    def test_stub_returning_false_gives_missing_result(self) -> None:
        result = resolve_efta(39186, 5, lambda url: False)
        assert result.found is False
        assert result.genuinely_missing is True
