"""Tests for US-006: WorkUnitGenerator — decision_chain type.

Covers every acceptance criterion listed in todo/US-006.md:
    AC-1  Generated decision_chain unit has all required WorkUnit fields (FR-017)
    AC-2  input.data contains between 20 and 50 document references (FR-013)
    AC-3  All doc refs in a unit come from within the same 30-day time window (FR-013)
    AC-4  input includes time_window_start and time_window_end as ISO 8601 date
          strings; time_window_end is within 30 days of time_window_start (AC-001)
    AC-5  type field is exactly "decision_chain" (FR-013)
    AC-6  path=3, difficulty="high", scaling="multiplying",
          optimal_batch="20-50 docs (same 30-day period)" per FR-017 table
    AC-7  The same unit_id is never assigned to two workers simultaneously (FR-018)
    AC-8  After mark_unit_complete(unit_id) the unit does not reappear (FR-019)
    AC-9  No generated unit references DS10 content or image/video files (EC-002)
    AC-10 All new code includes type annotations and docstrings (NFR-002, NFR-008)

All HTTP calls are mocked — no live requests to justice.gov or any external URL.
No file I/O: relationships are injected directly as Python lists.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from sefi.generator.units import (
    DE_ANON_PROHIBITION,
    NoAvailableUnitsError,
    WorkUnit,
    WorkUnitGenerator,
    _DC_BATCH_MAX,
    _DC_BATCH_MIN,
    _DC_DIFFICULTY,
    _DC_OPTIMAL_BATCH,
    _DC_PATH,
    _DC_SCALING,
    _DC_WINDOW_DAYS,
    _DC_CONSTRAINTS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOJ_PREFIX = "https://www.justice.gov/epstein/files/DataSet%20"


def _doj_url(efta_int: int, dataset: int = 9) -> str:
    """Return a fake-but-valid DOJ PDF URL."""
    return f"{DOJ_PREFIX}{dataset}/EFTA{efta_int:08d}.pdf"


def _fake_url_builder(efta_number: int, dataset: int) -> str:
    """Stub url_builder — returns a valid DOJ URL without HTTP call."""
    return _doj_url(efta_number, dataset)


def _make_relationship(
    efta_int: int,
    date_str: str = "2003-01-15",
    dataset: int = 9,
    relationship_type: str = "communication",
    source_entity: str = "Person-A",
    target_entity: str = "Person-B",
) -> dict[str, Any]:
    """Build a minimal relationship record for testing."""
    return {
        "efta_number": f"EFTA{efta_int:08d}",
        "date": date_str,
        "dataset": dataset,
        "relationship_type": relationship_type,
        "source_entity": source_entity,
        "target_entity": target_entity,
    }


def _make_relationships(
    count: int,
    base_efta: int = 10000,
    date_str: str = "2003-01-15",
    dataset: int = 9,
) -> list[dict[str, Any]]:
    """Build *count* distinct relationship records all on the same date."""
    return [
        _make_relationship(base_efta + i, date_str=date_str, dataset=dataset)
        for i in range(count)
    ]


def _make_generator(
    relationships: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> WorkUnitGenerator:
    """Create a WorkUnitGenerator with stub url_builder and given relationships."""
    if relationships is None:
        # Default: 30 relationships in the same window — enough for a unit
        relationships = _make_relationships(30)
    if claims is None:
        claims = []
    return WorkUnitGenerator(
        claims=claims,
        relationships=relationships,
        url_builder=_fake_url_builder,
    )


# ---------------------------------------------------------------------------
# AC-1: All required top-level fields present on a decision_chain unit (FR-017)
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "unit_id",
    "type",
    "path",
    "difficulty",
    "scaling",
    "optimal_batch",
    "input",
    "instructions",
    "constraints",
    "deadline",
    "source_verified",
}


def test_dc_all_required_fields_present():
    """AC-1: Generated decision_chain unit has all required top-level fields."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    for field_name in REQUIRED_FIELDS:
        assert hasattr(unit, field_name), f"Missing field: {field_name}"


def test_dc_unit_id_format():
    """AC-1: unit_id has the format 'dc-{12 hex chars}'."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.unit_id.startswith("dc-"), f"Bad prefix: {unit.unit_id!r}"
    suffix = unit.unit_id[len("dc-"):]
    assert len(suffix) == 12, f"Expected 12-char hex suffix, got len={len(suffix)}"
    assert all(c in "0123456789abcdef" for c in suffix), f"Non-hex suffix: {suffix!r}"


def test_dc_unit_type_is_decision_chain():
    """AC-1 / AC-5: unit.type is exactly 'decision_chain'."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.type == "decision_chain"


def test_dc_instructions_non_empty():
    """AC-1: unit.instructions is a non-empty string."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert isinstance(unit.instructions, str) and unit.instructions.strip()


def test_dc_instructions_contains_de_anon_prohibition():
    """AC-1: instructions contains the verbatim de-anonymization prohibition (EC-007)."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert DE_ANON_PROHIBITION in unit.instructions, (
        f"De-anon prohibition not found.\nInstructions: {unit.instructions!r}"
    )


def test_dc_deadline_is_iso8601_approximately_24h():
    """AC-1: unit.deadline is ISO 8601, approximately 24 h from now."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert isinstance(unit.deadline, str) and unit.deadline.strip()
    dt = datetime.fromisoformat(unit.deadline)
    now = datetime.now(tz=timezone.utc)
    delta_hours = (dt.replace(tzinfo=timezone.utc) - now).total_seconds() / 3600
    assert 23.98 <= delta_hours <= 24.02, f"Unexpected deadline delta: {delta_hours}h"


def test_dc_source_verified_is_false():
    """AC-1: unit.source_verified is always False for decision_chain units (EC-006)."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.source_verified is False


# ---------------------------------------------------------------------------
# AC-2: input.data contains between 20 and 50 document references (FR-013)
# ---------------------------------------------------------------------------

def test_dc_data_contains_at_least_20_refs():
    """AC-2: input.data has at least 20 document references."""
    gen = _make_generator(relationships=_make_relationships(20))
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) >= 20


def test_dc_data_contains_at_most_50_refs():
    """AC-2: input.data has at most 50 document references."""
    # Provide 80 relationships to ensure capping at 50
    gen = _make_generator(relationships=_make_relationships(80))
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) <= 50


def test_dc_data_batch_capped_at_50_when_more_available():
    """AC-2: When >50 docs are in the window, exactly 50 are returned."""
    gen = _make_generator(relationships=_make_relationships(60))
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) == 50


def test_dc_data_is_list_of_dicts():
    """AC-2: input.data is a list of dicts."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    data = unit.input["data"]
    assert isinstance(data, list)
    for doc_ref in data:
        assert isinstance(doc_ref, dict), f"Expected dict, got {type(doc_ref)}"


def test_dc_each_doc_ref_has_efta_number_and_url():
    """AC-2: Every doc ref in input.data has 'efta_number' and 'url' keys."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    for i, doc_ref in enumerate(unit.input["data"]):
        assert "efta_number" in doc_ref, f"data[{i}] missing 'efta_number'"
        assert "url" in doc_ref, f"data[{i}] missing 'url'"


def test_dc_efta_numbers_are_valid_format():
    """AC-2: Each doc ref's efta_number is in 'EFTA{8digits}' format."""
    efta_re = re.compile(r"^EFTA\d{8}$")
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    for i, doc_ref in enumerate(unit.input["data"]):
        efta = doc_ref["efta_number"]
        assert efta_re.match(efta), f"data[{i}].efta_number invalid: {efta!r}"


def test_dc_urls_are_valid_doj_prefix():
    """AC-2: Each doc ref's url starts with the DOJ PDF prefix."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    for i, doc_ref in enumerate(unit.input["data"]):
        url = doc_ref["url"]
        assert isinstance(url, str), f"data[{i}].url must be a string"
        assert url.startswith(DOJ_PREFIX), f"data[{i}].url has wrong prefix: {url!r}"


# ---------------------------------------------------------------------------
# AC-3: All doc refs come from within the same 30-day time window (FR-013)
# ---------------------------------------------------------------------------

def test_dc_doc_refs_within_30_day_window():
    """AC-3: All doc ref dates fall within the declared 30-day time window."""
    # Create relationships spanning two distinct 30-day windows — pick a window
    early_rels = _make_relationships(25, base_efta=10000, date_str="2003-01-05")
    late_rels = _make_relationships(25, base_efta=11000, date_str="2003-06-05")
    gen = _make_generator(relationships=early_rels + late_rels)
    unit = gen.generate_unit("decision_chain")

    tw_start = date.fromisoformat(unit.input["time_window_start"])
    tw_end = date.fromisoformat(unit.input["time_window_end"])

    for i, doc_ref in enumerate(unit.input["data"]):
        doc_date_str = doc_ref.get("date")
        if doc_date_str:
            doc_date = date.fromisoformat(doc_date_str)
            assert tw_start <= doc_date <= tw_end, (
                f"data[{i}] date {doc_date_str!r} outside window "
                f"[{tw_start}, {tw_end}]"
            )


def test_dc_single_window_always_satisfied_for_homogeneous_input():
    """AC-3: All 30 docs from the same date → all fall in the same window."""
    gen = _make_generator(relationships=_make_relationships(30, date_str="2003-03-10"))
    unit = gen.generate_unit("decision_chain")
    tw_start = date.fromisoformat(unit.input["time_window_start"])
    tw_end = date.fromisoformat(unit.input["time_window_end"])
    assert (tw_end - tw_start).days == _DC_WINDOW_DAYS


# ---------------------------------------------------------------------------
# AC-4: time_window_start and time_window_end are ISO 8601; end - start ≤ 30 days
# ---------------------------------------------------------------------------

def test_dc_time_window_start_is_iso8601():
    """AC-4: time_window_start is a valid ISO 8601 date string."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    tw_start = unit.input.get("time_window_start")
    assert isinstance(tw_start, str) and tw_start.strip()
    # Should parse without raising
    date.fromisoformat(tw_start)


def test_dc_time_window_end_is_iso8601():
    """AC-4: time_window_end is a valid ISO 8601 date string."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    tw_end = unit.input.get("time_window_end")
    assert isinstance(tw_end, str) and tw_end.strip()
    date.fromisoformat(tw_end)


def test_dc_time_window_end_within_30_days_of_start():
    """AC-4: time_window_end is exactly 30 days after time_window_start."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    start = date.fromisoformat(unit.input["time_window_start"])
    end = date.fromisoformat(unit.input["time_window_end"])
    delta = (end - start).days
    assert delta <= _DC_WINDOW_DAYS, (
        f"Window span is {delta} days, expected ≤ {_DC_WINDOW_DAYS}"
    )


def test_dc_time_window_end_not_before_start():
    """AC-4: time_window_end is never before time_window_start."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    start = date.fromisoformat(unit.input["time_window_start"])
    end = date.fromisoformat(unit.input["time_window_end"])
    assert end >= start


# ---------------------------------------------------------------------------
# AC-5: type field is exactly "decision_chain" — already covered in AC-1 tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# AC-6: path=3, difficulty="high", scaling="multiplying",
#        optimal_batch="20-50 docs (same 30-day period)" (FR-017)
# ---------------------------------------------------------------------------

def test_dc_path_is_3():
    """AC-6: unit.path is 3 (NPA Forensics path)."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.path == _DC_PATH == 3


def test_dc_difficulty_is_high():
    """AC-6: unit.difficulty is 'high'."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.difficulty == _DC_DIFFICULTY == "high"


def test_dc_scaling_is_multiplying():
    """AC-6: unit.scaling is 'multiplying'."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.scaling == _DC_SCALING == "multiplying"


def test_dc_optimal_batch_value():
    """AC-6: unit.optimal_batch is '20-50 docs (same 30-day period)'."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.optimal_batch == _DC_OPTIMAL_BATCH == "20-50 docs (same 30-day period)"


def test_dc_constraints_values():
    """AC-6: constraints dict has max_output_tokens=8000, pii_filter=True, requires_quorum=True."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    assert unit.constraints["max_output_tokens"] == 8000
    assert unit.constraints["pii_filter"] is True
    assert unit.constraints["requires_quorum"] is True


def test_dc_constraints_dict_is_a_copy():
    """AC-6: Mutating one unit's constraints does not affect the next unit."""
    rels = _make_relationships(60)  # enough for 2 units from different windows
    # Split into two separate 30-day windows
    rels_window1 = _make_relationships(30, base_efta=10000, date_str="2003-01-05")
    rels_window2 = _make_relationships(30, base_efta=11000, date_str="2003-06-05")
    gen = _make_generator(relationships=rels_window1 + rels_window2)

    unit1 = gen.generate_unit("decision_chain")
    unit1.constraints["max_output_tokens"] = 99999
    gen.mark_unit_complete(unit1.unit_id)

    unit2 = gen.generate_unit("decision_chain")
    assert unit2.constraints["max_output_tokens"] == 8000


# ---------------------------------------------------------------------------
# AC-7: Same unit_id never assigned to two workers simultaneously (FR-018)
# ---------------------------------------------------------------------------

def test_dc_double_assignment_raises():
    """AC-7: mark_unit_assigned raises ValueError on duplicate assignment."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    gen.mark_unit_assigned(unit.unit_id, "worker-A")
    with pytest.raises(ValueError, match="already assigned"):
        gen.mark_unit_assigned(unit.unit_id, "worker-B")


def test_dc_unit_docs_not_reused_while_assigned():
    """AC-7: Documents consumed by an active unit are not included in the next unit.

    When the first 30 docs are assigned, the second generate_unit call must
    draw from a *different* window (not the same efta_number set).
    """
    rels_w1 = _make_relationships(30, base_efta=10000, date_str="2003-01-05")
    rels_w2 = _make_relationships(30, base_efta=11000, date_str="2003-06-05")
    gen = _make_generator(relationships=rels_w1 + rels_w2)

    unit1 = gen.generate_unit("decision_chain")
    unit1_eftas = {d["efta_number"] for d in unit1.input["data"]}

    gen.mark_unit_assigned(unit1.unit_id, "worker-A")

    unit2 = gen.generate_unit("decision_chain")
    unit2_eftas = {d["efta_number"] for d in unit2.input["data"]}

    # The two sets must be disjoint — no doc appears in both active units
    overlap = unit1_eftas & unit2_eftas
    assert not overlap, f"Docs {overlap} appear in both assigned units simultaneously"


def test_dc_mark_unit_assigned_unknown_id_raises():
    """AC-7: mark_unit_assigned raises KeyError for unknown unit_id."""
    gen = _make_generator()
    with pytest.raises(KeyError):
        gen.mark_unit_assigned("dc-nonexistentunit", "worker-X")


def test_dc_mark_unit_assigned_completed_unit_raises():
    """AC-7: mark_unit_assigned raises ValueError on an already-completed unit."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    gen.mark_unit_complete(unit.unit_id)
    with pytest.raises(ValueError, match="already completed"):
        gen.mark_unit_assigned(unit.unit_id, "worker-A")


# ---------------------------------------------------------------------------
# AC-8: After mark_unit_complete, unit does not reappear (FR-019)
# ---------------------------------------------------------------------------

def test_dc_completed_unit_docs_released_back_to_pool():
    """AC-8: After mark_unit_complete, the released docs can appear in new units.

    Both windows have exactly 20 docs (minimum), so after completing the first
    unit those docs are released; a second generate call can produce a unit from
    either window.
    """
    rels = _make_relationships(20, base_efta=10000, date_str="2003-01-05")
    gen = _make_generator(relationships=rels)

    unit1 = gen.generate_unit("decision_chain")
    gen.mark_unit_complete(unit1.unit_id)

    # After completion the pool should be replenished — should not raise
    unit2 = gen.generate_unit("decision_chain")
    assert unit2.unit_id != unit1.unit_id, "Completed unit_id must not be reissued"


def test_dc_mark_unit_complete_unknown_id_raises():
    """AC-8: mark_unit_complete raises KeyError for unknown unit_id."""
    gen = _make_generator()
    with pytest.raises(KeyError):
        gen.mark_unit_complete("dc-doesnotexist1")


def test_dc_get_status_tracks_completion():
    """AC-8: get_status accurately reflects completed count after mark_unit_complete."""
    gen = _make_generator()
    assert gen.get_status()["total_completed"] == 0
    unit = gen.generate_unit("decision_chain")
    gen.mark_unit_complete(unit.unit_id)
    assert gen.get_status()["total_completed"] == 1


def test_dc_generate_raises_when_all_docs_active():
    """AC-8: generate_unit raises NoAvailableUnitsError when all docs are in active units.

    Use exactly _DC_BATCH_MIN docs so there are none left for a second unit
    until the first is completed.
    """
    rels = _make_relationships(_DC_BATCH_MIN, base_efta=10000, date_str="2003-01-05")
    gen = _make_generator(relationships=rels)

    unit1 = gen.generate_unit("decision_chain")
    gen.mark_unit_assigned(unit1.unit_id, "worker-A")

    with pytest.raises(NoAvailableUnitsError):
        gen.generate_unit("decision_chain")


# ---------------------------------------------------------------------------
# AC-9: No DS10 or image/video content (EC-002)
# ---------------------------------------------------------------------------

def test_dc_ds10_relationships_excluded():
    """AC-9: Relationship records with dataset=10 are filtered out."""
    # Create 20 safe + 10 DS10 records all in the same window.
    safe_rels = _make_relationships(25, base_efta=10000, date_str="2003-01-10")
    ds10_rels = [
        {
            "efta_number": f"EFTA{20000 + i:08d}",
            "date": "2003-01-10",
            "dataset": 10,  # DS10 — must be excluded
            "relationship_type": "comm",
            "source_entity": "A",
            "target_entity": "B",
        }
        for i in range(10)
    ]
    gen = _make_generator(relationships=safe_rels + ds10_rels)
    status = gen.get_status()
    # Only safe records should survive filtering
    assert status["total_relationships"] == 25


def test_dc_image_suffix_relationships_excluded():
    """AC-9: Relationships whose EFTA field ends with an image suffix are excluded."""
    image_rels = [
        {
            "efta_number": "EFTA00000001.jpg",  # image suffix — excluded
            "date": "2003-01-10",
            "dataset": 9,
            "relationship_type": "comm",
        }
    ]
    safe_rels = _make_relationships(25, base_efta=10000, date_str="2003-01-10")
    gen = _make_generator(relationships=safe_rels + image_rels)
    assert gen.get_status()["total_relationships"] == 25


def test_dc_video_suffix_relationships_excluded():
    """AC-9: Relationships whose EFTA field ends with a video suffix are excluded."""
    video_rels = [
        {
            "efta_number": "EFTA00000002.mp4",  # video suffix — excluded
            "date": "2003-01-10",
            "dataset": 9,
            "relationship_type": "comm",
        }
    ]
    safe_rels = _make_relationships(25, base_efta=10000, date_str="2003-01-10")
    gen = _make_generator(relationships=safe_rels + video_rels)
    assert gen.get_status()["total_relationships"] == 25


def test_dc_generated_unit_urls_not_ds10():
    """AC-9: No URL in a generated unit references DataSet%2010."""
    gen = _make_generator()
    unit = gen.generate_unit("decision_chain")
    for doc_ref in unit.input["data"]:
        url = doc_ref["url"]
        assert "DataSet%2010" not in url, f"DS10 URL found in unit: {url!r}"


# ---------------------------------------------------------------------------
# AC-10: Type annotations and docstrings (NFR-002, NFR-008)
# ---------------------------------------------------------------------------

def test_dc_generate_decision_chain_has_docstring():
    """AC-10: WorkUnitGenerator._generate_decision_chain has a docstring."""
    fn = WorkUnitGenerator._generate_decision_chain
    assert fn.__doc__ and fn.__doc__.strip()


def test_dc_select_time_window_has_docstring():
    """AC-10: WorkUnitGenerator._select_time_window has a docstring."""
    fn = WorkUnitGenerator._select_time_window
    assert fn.__doc__ and fn.__doc__.strip()


def test_dc_relationship_to_doc_ref_has_docstring():
    """AC-10: WorkUnitGenerator._relationship_to_doc_ref has a docstring."""
    fn = WorkUnitGenerator._relationship_to_doc_ref
    assert fn.__doc__ and fn.__doc__.strip()


def test_dc_build_decision_chain_unit_has_docstring():
    """AC-10: WorkUnitGenerator._build_decision_chain_unit has a docstring."""
    fn = WorkUnitGenerator._build_decision_chain_unit
    assert fn.__doc__ and fn.__doc__.strip()


def test_dc_filter_relationships_has_docstring():
    """AC-10: WorkUnitGenerator._filter_relationships has a docstring."""
    fn = WorkUnitGenerator._filter_relationships
    assert fn.__doc__ and fn.__doc__.strip()


# ---------------------------------------------------------------------------
# Error path: NoAvailableUnitsError
# ---------------------------------------------------------------------------

def test_dc_raises_no_available_when_relationships_empty():
    """NoAvailableUnitsError raised when relationships list is empty."""
    gen = _make_generator(relationships=[])
    with pytest.raises(NoAvailableUnitsError, match="No relationship records"):
        gen.generate_unit("decision_chain")


def test_dc_raises_no_available_when_no_eligible_window():
    """NoAvailableUnitsError raised when no window has ≥20 unassigned docs."""
    # Only 19 relationships in the window — below the 20 minimum
    rels = _make_relationships(_DC_BATCH_MIN - 1, base_efta=10000, date_str="2003-01-10")
    gen = _make_generator(relationships=rels)
    with pytest.raises(NoAvailableUnitsError):
        gen.generate_unit("decision_chain")


def test_dc_raises_no_available_when_no_valid_efta():
    """NoAvailableUnitsError raised when all relationship records lack a valid EFTA."""
    bad_rels = [
        {"date": "2003-01-10", "some_other_field": "not_efta"}
        for _ in range(25)
    ]
    gen = _make_generator(relationships=bad_rels)
    with pytest.raises(NoAvailableUnitsError):
        gen.generate_unit("decision_chain")


def test_dc_raises_on_unknown_unit_type():
    """generate_unit raises ValueError for an unrecognised unit_type."""
    gen = _make_generator()
    with pytest.raises(ValueError, match="Unknown unit_type"):
        gen.generate_unit("unknown_type")


# ---------------------------------------------------------------------------
# Edge cases: date parsing
# ---------------------------------------------------------------------------

def test_dc_datetime_string_dates_are_accepted():
    """Relationship records with full ISO 8601 datetimes (not just dates) are handled."""
    rels = [
        _make_relationship(
            10000 + i,
            date_str="2003-02-10T14:30:00",  # full datetime string
            dataset=9,
        )
        for i in range(25)
    ]
    gen = _make_generator(relationships=rels)
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) >= _DC_BATCH_MIN


def test_dc_zulu_datetime_strings_are_accepted():
    """Relationship records with 'Z' suffix datetimes are accepted."""
    rels = [
        _make_relationship(
            10000 + i,
            date_str="2003-03-01T00:00:00Z",
            dataset=9,
        )
        for i in range(25)
    ]
    gen = _make_generator(relationships=rels)
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) >= _DC_BATCH_MIN


def test_dc_records_with_unparseable_dates_skipped():
    """Records with unparseable date fields are silently skipped."""
    bad_date_rels = [
        {"efta_number": f"EFTA{90000 + i:08d}", "date": "not-a-date", "dataset": 9}
        for i in range(5)
    ]
    good_rels = _make_relationships(25, base_efta=10000, date_str="2003-01-10")
    gen = _make_generator(relationships=bad_date_rels + good_rels)
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) >= _DC_BATCH_MIN


# ---------------------------------------------------------------------------
# Edge case: EFTA candidate field fallback priority
# ---------------------------------------------------------------------------

def test_dc_efta_source_field_used_as_fallback():
    """_relationship_to_doc_ref uses 'efta_source' when 'efta_number' is absent."""
    rels = [
        {
            "efta_source": f"EFTA{20000 + i:08d}",  # alternate EFTA field
            "date": "2003-01-15",
            "dataset": 9,
        }
        for i in range(25)
    ]
    gen = _make_generator(relationships=rels)
    unit = gen.generate_unit("decision_chain")
    assert len(unit.input["data"]) >= _DC_BATCH_MIN


# ---------------------------------------------------------------------------
# WorkUnit validation: decision_chain-specific (NFR-002)
# ---------------------------------------------------------------------------

def _valid_dc_unit_kwargs() -> dict[str, Any]:
    """Return valid kwargs for constructing a decision_chain WorkUnit directly."""
    data = [
        {
            "efta_number": f"EFTA{10000 + i:08d}",
            "url": f"{DOJ_PREFIX}9/EFTA{10000 + i:08d}.pdf",
        }
        for i in range(25)
    ]
    return {
        "unit_id": "dc-aabbccdd1122",
        "type": "decision_chain",
        "path": 3,
        "difficulty": "high",
        "scaling": "multiplying",
        "optimal_batch": "20-50 docs (same 30-day period)",
        "input": {
            "time_window_start": "2003-01-01",
            "time_window_end": "2003-01-31",
            "data": data,
        },
        "instructions": f"Analyze the batch. {DE_ANON_PROHIBITION}",
        "constraints": {
            "max_output_tokens": 8000,
            "pii_filter": True,
            "requires_quorum": True,
        },
        "deadline": "2099-01-01T00:00:00+00:00",
        "source_verified": False,
    }


def test_dc_workunit_valid_construction():
    """WorkUnit with valid decision_chain fields constructs without error."""
    kwargs = _valid_dc_unit_kwargs()
    unit = WorkUnit(**kwargs)
    assert unit.unit_id == "dc-aabbccdd1122"
    assert unit.type == "decision_chain"


def test_dc_workunit_raises_on_missing_time_window_start():
    """WorkUnit raises ValueError when time_window_start is absent."""
    kwargs = _valid_dc_unit_kwargs()
    del kwargs["input"]["time_window_start"]
    with pytest.raises(ValueError, match="time_window_start"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_missing_time_window_end():
    """WorkUnit raises ValueError when time_window_end is absent."""
    kwargs = _valid_dc_unit_kwargs()
    del kwargs["input"]["time_window_end"]
    with pytest.raises(ValueError, match="time_window_end"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_when_window_exceeds_30_days():
    """WorkUnit raises ValueError when time_window_end is >30 days after start."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["time_window_start"] = "2003-01-01"
    kwargs["input"]["time_window_end"] = "2003-03-01"  # 59 days — too long
    with pytest.raises(ValueError, match="30"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_data_below_minimum():
    """WorkUnit raises ValueError when input.data has fewer than 20 entries."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["data"] = kwargs["input"]["data"][:10]  # only 10 entries
    with pytest.raises(ValueError, match="20"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_data_above_maximum():
    """WorkUnit raises ValueError when input.data has more than 50 entries."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["data"] = [
        {
            "efta_number": f"EFTA{10000 + i:08d}",
            "url": f"{DOJ_PREFIX}9/EFTA{10000 + i:08d}.pdf",
        }
        for i in range(51)
    ]
    with pytest.raises(ValueError, match="50"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_invalid_efta_in_data():
    """WorkUnit raises ValueError when a doc ref's efta_number is malformed."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["data"][0]["efta_number"] = "BADFORMAT"
    with pytest.raises(ValueError):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_invalid_url_in_data():
    """WorkUnit raises ValueError when a doc ref's url doesn't match DOJ prefix."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["data"][0]["url"] = "https://example.com/file.pdf"
    with pytest.raises(ValueError, match="DOJ PDF URL"):
        WorkUnit(**kwargs)


def test_dc_workunit_raises_on_end_before_start():
    """WorkUnit raises ValueError when time_window_end is before time_window_start."""
    kwargs = _valid_dc_unit_kwargs()
    kwargs["input"]["time_window_start"] = "2003-06-01"
    kwargs["input"]["time_window_end"] = "2003-01-01"  # before start
    with pytest.raises(ValueError, match="before"):
        WorkUnit(**kwargs)


# ---------------------------------------------------------------------------
# No live HTTP calls
# ---------------------------------------------------------------------------

def test_dc_no_http_calls_during_generation():
    """No real HTTP calls are made when generating a decision_chain unit."""
    mock_builder = MagicMock(
        side_effect=lambda efta_number, dataset: f"{DOJ_PREFIX}{dataset}/EFTA{efta_number:08d}.pdf"
    )
    rels = _make_relationships(25, base_efta=10000, date_str="2003-01-10")
    gen = WorkUnitGenerator(
        claims=[],
        relationships=rels,
        url_builder=mock_builder,
    )
    unit = gen.generate_unit("decision_chain")
    # url_builder was called once per doc ref — never via HTTP
    assert mock_builder.call_count == len(unit.input["data"])
    for call_args in mock_builder.call_args_list:
        args, _ = call_args
        assert isinstance(args[0], int), "efta_number arg must be int"
        assert isinstance(args[1], int), "dataset arg must be int"


# ---------------------------------------------------------------------------
# get_status integration
# ---------------------------------------------------------------------------

def test_dc_get_status_includes_relationships_count():
    """get_status returns total_relationships matching the filtered relationship count."""
    rels = _make_relationships(30)
    gen = _make_generator(relationships=rels)
    status = gen.get_status()
    assert status["total_relationships"] == 30


def test_dc_get_status_total_generated_increments():
    """get_status.total_generated increments after each generate_unit call."""
    rels_w1 = _make_relationships(25, base_efta=10000, date_str="2003-01-05")
    rels_w2 = _make_relationships(25, base_efta=11000, date_str="2003-06-05")
    gen = _make_generator(relationships=rels_w1 + rels_w2)

    assert gen.get_status()["total_generated"] == 0
    gen.generate_unit("decision_chain")
    assert gen.get_status()["total_generated"] == 1
