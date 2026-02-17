# SEFI@Home — Requirements Document

**Version:** 1.0
**Date:** 2026-02-16
**Status:** Draft — Pending HITL Gate Review
**Source Document:** `ROADMAP.md` v1.0 (2026-02-16)
**Produced By:** Requirements Reviewer Agent

---

## Table of Contents

1. [Document Metadata](#document-metadata)
2. [Executive Summary](#executive-summary)
3. [Scope](#scope)
4. [Functional Requirements](#functional-requirements-fr)
   - [Component 1: Database Adapter](#component-1-database-adapter)
   - [Component 2: Work Unit Generator](#component-2-work-unit-generator)
   - [Component 3: Distribution API](#component-3-distribution-api)
   - [Component 4: Validation Layer](#component-4-validation-layer)
   - [Component 5: Findings Store](#component-5-findings-store)
   - [Component 6: Coverage Dashboard](#component-6-coverage-dashboard)
   - [System-Level Functional Requirements](#system-level-functional-requirements)
5. [Non-Functional Requirements](#non-functional-requirements-nfr)
6. [Ethical Constraints](#ethical-constraints-ec)
7. [Data Requirements](#data-requirements-dr)
8. [API Contracts](#api-contracts-ac)
9. [Out of Scope (MVP)](#out-of-scope-mvp)
10. [Open Questions (Blocking HITL Gate)](#open-questions-blocking-hitl-gate)
11. [Requirements Review Score](#requirements-review-score)

---

## Document Metadata

| Field | Value |
|-------|-------|
| Document Title | SEFI@Home Requirements Document |
| Version | 1.0 |
| Date | 2026-02-16 |
| Derived From | `ROADMAP.md` v1.0 |
| Author | Requirements Reviewer Agent |
| Review Status | Awaiting HITL Gate Approval |
| MVP Scope | Phase 1 (Week 1) + Phase 2 (Week 2) only |
| Technology Stack | Python 3.10+, FastAPI, SQLite, Pydantic, pytest (no ORM) |

---

## Executive Summary

SEFI@Home is a distributed document-analysis platform that coordinates volunteer "reasoning tokens" (LLM workers or human analysts) to systematically analyze the Epstein Files released by the DOJ. Instead of distributing CPU cycles (as BOINC does), SEFI@Home distributes structured analysis tasks called "work units."

The MVP is a zero-corpus prototype. The server holds only JSON metadata (~2MB). Workers receive work units containing direct DOJ PDF URLs and fetch documents themselves from justice.gov. The server stores only JSON metadata and findings.

MVP implements exactly two work unit types: `verify_finding` and `decision_chain`. All seven ethical constraints are hardcoded and non-configurable. The EFTA gap resolution algorithm (try primary dataset, then N-1, then N+1) is critical logic that must be correctly implemented before any gap-related work units are issued.

The MVP is estimated at $20–25 of API costs and is intended to prove the concept before any further investment.

---

## Scope

### In Scope (MVP — Phase 1 + Phase 2)

- Work Unit Generator: `verify_finding` and `decision_chain` types only
- Distribution API: `GET /work`, `POST /result`, `GET /status` endpoints
- Findings Store: SQLite-backed persistence of accepted findings
- DOJ URL builder: EFTA number → PDF URL construction
- Basic provenance check: cited EFTA number exists
- Result deduplication
- Findings export: JSON and CSV formats
- Ingestion of pre-extracted rhowardstone JSON exports (persons registry, knowledge graph, EFTA dataset mapping)
- All seven ethical constraints enforced as hardcoded validation rules

### In Scope (Post-MVP, Conditional on Value Demonstration)

- Full corpus download and local PDF serving
- All remaining 8 work unit types
- Full Validation Layer with quorum logic and PII Guardian
- Coverage Dashboard (Component 6)
- Worker authentication (API key system)
- Rate limiting
- GitHub sync for findings publication
- Real-time WebSocket dashboard updates

### Out of Scope

See dedicated section below.

---

## Functional Requirements (FR)

Requirements are tagged:
- `[MVP]` — required for MVP (Phase 1 + Phase 2)
- `[POST-MVP]` — after MVP proves value
- `[OPEN]` — requires human decision before implementation

Each requirement includes:
- Unique identifier
- Source section in ROADMAP.md
- Assigned component
- Acceptance criterion (pass/fail verifiable test)

---

### Component 1: Database Adapter

**Source:** ROADMAP.md §"Component 1: Database Adapter"

**FR-001** `[MVP]`
The Database Adapter must load rhowardstone JSON export files into in-memory or SQLite working tables.
- Component: 1
- Source: ROADMAP.md §"Component 1 Update: Database Adapter Must Load JSON Exports"
- Acceptance Criterion: Given a valid JSON export file path and target table name, `load_json_export(file_path, table_name)` returns the integer count of records loaded; count matches the record count of the source file.

**FR-002** `[MVP]`
The Database Adapter must expose `get_known_entities()` returning all entities from `knowledge_graph_entities.json`.
- Component: 1
- Source: ROADMAP.md §"Component 1 Update"
- Acceptance Criterion: Return value is a non-empty `List[Dict]` with 524 records when the standard export is loaded. Each dict contains at minimum: entity id, name, type, and aliases fields.

**FR-003** `[MVP]`
The Database Adapter must expose `get_known_relationships()` returning all relationships from `knowledge_graph_relationships.json`.
- Component: 1
- Source: ROADMAP.md §"Component 1 Update"
- Acceptance Criterion: Return value is a non-empty `List[Dict]` with 2,096 records when the standard export is loaded.

**FR-004** `[MVP]`
The Database Adapter must expose `get_persons_registry()` returning the unified person registry from `persons_registry.json`.
- Component: 1
- Source: ROADMAP.md §"Component 1 Update"
- Acceptance Criterion: Return value is a non-empty `List[Dict]` with 1,614 records when the standard export is loaded.

**FR-005** `[POST-MVP]`
The Database Adapter must support read-only connection pooling for concurrent access to all four rhowardstone SQLite databases.
- Component: 1
- Source: ROADMAP.md §"Component 1: Database Adapter — Responsibilities"
- Acceptance Criterion: Given 10 simultaneous read queries to any database, all queries complete successfully without deadlock or connection error within a 5-second window.

**FR-006** `[POST-MVP]`
The Database Adapter must execute all SQL queries using parameterized statements; string interpolation into SQL is prohibited.
- Component: 1
- Source: ROADMAP.md §"Component 1: Responsibilities — Query execution with parameterization"
- Acceptance Criterion: Code review confirms no SQL string interpolation; unit test with a malicious parameter value (e.g., `'; DROP TABLE findings; --`) confirms the value is treated as data, not executable SQL.

**FR-007** `[POST-MVP]`
The Database Adapter must support paginated queries via `paginated_query()`, returning a tuple of (results page, total count).
- Component: 1
- Source: ROADMAP.md §"Component 1: Interface — paginated_query"
- Acceptance Criterion: Given a query that matches 500 records and `page_size=100, offset=200`, the method returns exactly 100 records and total count of 500.

**FR-008** `[POST-MVP]`
The Database Adapter must validate database schemas on startup and raise a descriptive error if expected tables or columns are absent.
- Component: 1
- Source: ROADMAP.md §"Component 1: Responsibilities — Schema validation on startup"
- Acceptance Criterion: When initialized against a database missing a required table, the adapter raises a `SchemaValidationError` with the missing table name in the message before any queries are attempted.

**FR-009** `[POST-MVP]`
The Database Adapter must expose `get_efta_range(dataset, start, end)` returning all documents in a given EFTA number range within a specified dataset.
- Component: 1
- Source: ROADMAP.md §"Component 1: Interface"
- Acceptance Criterion: Given dataset=9, start=39025, end=40000, returns a list of dicts with `efta_number` field values falling within the inclusive range.

**FR-010** `[POST-MVP]`
The Database Adapter must expose `get_document_versions(efta_number)` returning all available versions of a document.
- Component: 1
- Source: ROADMAP.md §"Component 1: Interface"
- Acceptance Criterion: Given an EFTA number with multiple known versions, returns a list with one entry per version; given an EFTA with one version, returns a list of length 1.

**FR-011** `[POST-MVP]`
The Database Adapter must expose `get_redactions_for_document(efta_number)` returning all redaction records for a given document.
- Component: 1
- Source: ROADMAP.md §"Component 1: Interface"
- Acceptance Criterion: Given a known redacted EFTA number, returns a non-empty list of redaction records each containing coordinate and document version fields.

---

### Component 2: Work Unit Generator

**Source:** ROADMAP.md §"Component 2: Work Unit Generator"

**FR-012** `[MVP]`
The Work Unit Generator must generate `verify_finding` work units, each containing exactly one claim, one or more cited EFTA numbers, and the corresponding DOJ PDF URLs for those EFTA numbers.
- Component: 2
- Source: ROADMAP.md §"MVP Phase 1", AGENTS.md §"Work Unit Types (MVP)"
- Acceptance Criterion: A generated `verify_finding` unit contains: `unit_id`, `type="verify_finding"`, `claim` (non-empty string), `cited_eftas` (list of at least 1 EFTA string), `efta_urls` (list of valid justice.gov PDF URLs matching cited EFTAs in count and order), and `instructions`.

**FR-013** `[MVP]`
The Work Unit Generator must generate `decision_chain` work units, each containing 20–50 documents from the same 30-day time window.
- Component: 2
- Source: ROADMAP.md §"Work Unit Types Reference", AGENTS.md §"decision_chain"
- Acceptance Criterion: A generated `decision_chain` unit contains: `unit_id`, `type="decision_chain"`, `input.data` with between 20 and 50 document references, and a time window constraint verifiable from document metadata.

**FR-014** `[MVP]`
The Work Unit Generator must construct DOJ PDF URLs using the pattern `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf` where `{N}` is the dataset number (1–12) and `{XXXXXXXX}` is the zero-padded 8-digit EFTA number.
- Component: 2
- Source: ROADMAP.md §"Zero-Corpus MVP Architecture", AGENTS.md §"EFTA Numbers"
- Acceptance Criterion: Given EFTA number 39186 and dataset 9, the constructed URL is exactly `https://www.justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf`.

**FR-015** `[MVP]`
The Work Unit Generator must use `efta_dataset_mapping.json` to determine the primary dataset for any given EFTA number range before constructing URLs.
- Component: 2
- Source: ROADMAP.md §"EFTA Gap Resolution Logic — Work Unit Generator Update"
- Acceptance Criterion: Given an EFTA number that falls within a known mapping range, the generator assigns the correct dataset number as primary. Unit test with known EFTA-to-dataset mappings confirms correctness.

**FR-016** `[MVP]`
The Work Unit Generator must implement the EFTA gap resolution algorithm: for any EFTA number to be looked up, first try the primary dataset, then dataset N-1, then dataset N+1, before marking the document as genuinely missing. Dataset numbers below 1 or above 12 are skipped.
- Component: 2
- Source: ROADMAP.md §"EFTA Gap Resolution Logic — Resolution Algorithm"
- Acceptance Criterion: Given an EFTA number not found in its primary dataset but present in dataset N+1, the resolution returns `found=True`, `url` pointing to the N+1 URL, and `was_adjacent=True`. Given an EFTA not found in primary, N-1, or N+1, returns `found=False, genuinely_missing=True`.

**FR-017** `[MVP]`
Each generated `WorkUnit` dataclass instance must contain all fields defined in the interface specification: `unit_id`, `type`, `path`, `difficulty`, `scaling`, `optimal_batch`, `input`, `instructions`, `constraints`, `deadline`.
- Component: 2
- Source: ROADMAP.md §"Component 2: Interface — WorkUnit dataclass"
- Acceptance Criterion: Pydantic or dataclass validation on any generated unit passes without error; any field missing or of wrong type causes the generator to raise before returning.

**FR-018** `[MVP]`
The Work Unit Generator must track which work units have been assigned to workers, preventing double-assignment of the same unit.
- Component: 2
- Source: ROADMAP.md §"Component 2: Responsibilities — Track which ranges/documents have been assigned"
- Acceptance Criterion: Given a unit already assigned to worker A, a subsequent call to `generate_unit()` or `mark_unit_assigned()` for the same unit raises an error or returns a different unit; the same unit is never assigned to two workers simultaneously.

**FR-019** `[MVP]`
The Work Unit Generator must expose `mark_unit_complete(unit_id)` to mark a unit finished after a valid result is submitted.
- Component: 2
- Source: ROADMAP.md §"Component 2: Interface"
- Acceptance Criterion: After `mark_unit_complete("unit-abc")`, the unit no longer appears in available work for `generate_unit()` calls.

**FR-020** `[POST-MVP]`
The Work Unit Generator must support all 10 work unit types defined in the Work Unit Types Reference table.
- Component: 2
- Source: ROADMAP.md §"Work Unit Types Reference"
- Acceptance Criterion: Each of the 10 type strings (`gap_analysis`, `cross_ref_audit`, `document_classify`, `npa_timeline`, `decision_chain`, `entity_extraction`, `money_flow`, `shell_mapping`, `redaction_compare`, `verify_finding`) can be passed to `generate_unit(unit_type=...)` without raising a `NotImplementedError` or equivalent.

**FR-021** `[POST-MVP]`
The Work Unit Generator must apply scaling-aware batch sizing: `linear` tasks use fixed batch sizes; `multiplying` tasks use larger batches from the same time window or dataset; `plateau` tasks batch to the defined sweet spot then stop; `aggregation` tasks use a two-phase extraction + aggregation approach.
- Component: 2
- Source: ROADMAP.md §"Component 2: Scaling Behavior Implementation"
- Acceptance Criterion: Integration test for each scaling type confirms generated unit batch sizes match the optimal batch sizes specified in the Work Unit Types Reference table within a 20% tolerance.

**FR-022** `[POST-MVP]`
The Work Unit Generator must expose `get_pending_aggregation_units(extraction_type)` returning aggregation-phase work units ready to process when sufficient extraction units have completed.
- Component: 2
- Source: ROADMAP.md §"Component 2: Interface"
- Acceptance Criterion: Given 50+ completed extraction units of type `npa_timeline`, `get_pending_aggregation_units("npa_timeline")` returns at least one aggregation unit.

---

### Component 3: Distribution API

**Source:** ROADMAP.md §"Component 3: Distribution API"

**FR-023** `[MVP]`
The Distribution API must expose `GET /work` returning a single available work unit as JSON, conforming to the WorkUnit schema defined in the API Contracts section.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints", §"API Contracts — GET /work Response"
- Acceptance Criterion: `GET /work` with no query parameters returns HTTP 200 with a JSON body that passes Pydantic `WorkUnit` validation. When no units are available, returns HTTP 204 or a JSON body with an explicit empty/unavailable indicator.

**FR-024** `[MVP]`
The Distribution API must expose `POST /result` accepting a `ResultSubmission` JSON body and returning an `AcceptanceResponse` JSON body.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints", §"API Contracts — POST /result"
- Acceptance Criterion: A valid `POST /result` body (as defined in the API Contracts section) returns HTTP 200 with `accepted`, `finding_id`, `quorum_status`, `pii_detected`, and `next_unit_available` fields. An invalid body returns HTTP 422.

**FR-025** `[MVP]`
The Distribution API must expose `GET /status` returning aggregate project statistics.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints"
- Acceptance Criterion: `GET /status` returns HTTP 200 with a JSON body containing at minimum: total work units generated, total units completed, total findings accepted. All counts are non-negative integers.

**FR-026** `[MVP]`
The Distribution API must expose `GET /health` returning a health check response.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints"
- Acceptance Criterion: `GET /health` returns HTTP 200 with a JSON body confirming the service is running. Response time must be under 500ms under no-load conditions.

**FR-027** `[POST-MVP]`
The Distribution API must expose `POST /dispute` accepting a `DisputeRequest` body and returning a `DisputeResponse`, allowing workers to flag a result for re-analysis.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints"
- Acceptance Criterion: A valid dispute request against an existing `finding_id` returns HTTP 200 and the finding's status is updated to `disputed` in the Findings Store.

**FR-028** `[POST-MVP]`
`GET /work` must support optional query parameters `type`, `difficulty`, and `path` to filter available work units.
- Component: 3
- Source: ROADMAP.md §"Component 3: Endpoints — GET /work"
- Acceptance Criterion: `GET /work?type=verify_finding` returns only units with `type="verify_finding"`. `GET /work?difficulty=low` returns only low-difficulty units. `GET /work?path=2` returns only path-2 units. Invalid filter values return HTTP 422.

**FR-029** `[POST-MVP]`
The Distribution API must authenticate requests using an API key passed in the `X-SEFI-API-Key` header; each key must map to a unique `worker_id` for contribution tracking.
- Component: 3
- Source: ROADMAP.md §"Component 3: Authentication"
- Acceptance Criterion: A request with a valid API key returns the expected response. A request with a missing or invalid key returns HTTP 401. The `worker_id` derived from the key is stored with any submitted result.

**FR-030** `[POST-MVP]`
The Distribution API must enforce per-worker rate limiting.
- Component: 3
- Source: ROADMAP.md §"Component 3: Responsibilities — Rate limiting per worker"
- Acceptance Criterion: Given a worker exceeding the defined rate limit (rate limit value is `[OPEN]` — see OQ-005), subsequent requests within the limit window return HTTP 429 with a `Retry-After` header.

---

### Component 4: Validation Layer

**Source:** ROADMAP.md §"Component 4: Validation Layer"

**FR-031** `[MVP]`
The Validation Layer must perform a basic provenance check on every submitted result, verifying that all cited EFTA numbers correspond to documents known to exist (either in the JSON exports or via a resolvable DOJ URL).
- Component: 4
- Source: ROADMAP.md §"MVP Phase 2 — Basic provenance check"
- Acceptance Criterion: A result citing an EFTA number that cannot be resolved (not in exports, no valid DOJ URL response) is rejected with a provenance error. A result citing a valid EFTA is accepted (subject to other checks).

**FR-032** `[MVP]`
The Validation Layer must deduplicate result submissions, rejecting results for a `unit_id` that already has an `accepted` finding.
- Component: 4
- Source: ROADMAP.md §"MVP Phase 2 — Result deduplication"
- Acceptance Criterion: Submitting the same `unit_id` a second time after the first result is accepted returns a response with `accepted=false` and an explanation referencing the existing `finding_id`.

**FR-033** `[POST-MVP]`
The Validation Layer must implement a Quorum Validator requiring N-of-M agreement for results, with a default of 2-of-3 (configurable per HITL decision OQ-005).
- Component: 4
- Source: ROADMAP.md §"Component 4: Responsibilities — Quorum Validator"
- Acceptance Criterion: A result for a unit requiring quorum returns `quorum_status="pending"` until a second agreeing submission arrives, then `quorum_status="achieved"`. Disagreeing submissions trigger `quorum_status="disputed"`.

**FR-034** `[POST-MVP]`
The Validation Layer must implement a PII Guardian that scans every result output for victim-identifying information before acceptance; results with PII matches are quarantined, not accepted.
- Component: 4
- Source: ROADMAP.md §"Component 4: Responsibilities — PII Guardian", §"Ethical Constraints — #1, #3"
- Acceptance Criterion: A result containing a string matching the PII pattern list returns `accepted=false`, `pii_detected=true`, and the result's status in the Findings Store is set to `quarantined`. The result is not written to the accepted findings dataset.

**FR-035** `[POST-MVP]`
The PII Guardian must detect at minimum: victim name format matches, postal addresses, phone numbers, and Social Security Number patterns.
- Component: 4
- Source: ROADMAP.md §"Component 4: PII Detection Approach"
- Acceptance Criterion: Unit tests with synthetic test strings containing each pattern type confirm detection rates of 100% for SSNs and phone numbers; false positive rate is documented. (Victim name list patterns are `[OPEN]` — see OQ-004.)

**FR-036** `[POST-MVP]`
The Validation Layer must implement a Provenance Logger that verifies all claims in a result trace to valid EFTA document citations.
- Component: 4
- Source: ROADMAP.md §"Component 4: Responsibilities — Provenance Logger"
- Acceptance Criterion: `verify_provenance(citations)` returns an empty error list when all citations reference valid EFTA numbers. It returns one `ProvenanceError` per invalid citation.

**FR-037** `[POST-MVP]`
The Validation Layer must enforce quorum threshold of 3-of-M (not 2-of-3) for any finding that contains named individuals in the result output.
- Component: 4
- Source: ROADMAP.md §"Ethical Constraints — #5"
- Acceptance Criterion: A result containing a named individual (detected by Pydantic field or text analysis) is not marked `accepted` until three independent agreeing submissions exist.

---

### Component 5: Findings Store

**Source:** ROADMAP.md §"Component 5: Findings Store"

**FR-038** `[MVP]`
The Findings Store must persist accepted findings to a SQLite database (`findings.db`) using the schema defined in the Data Requirements section.
- Component: 5
- Source: ROADMAP.md §"Component 5: Schema (findings.db)"
- Acceptance Criterion: After `store_finding(finding)`, the finding is retrievable by `finding_id` from `findings.db` with all fields intact. Database file persists across process restarts.

**FR-039** `[MVP]`
The Findings Store must expose `get_findings_for_document(efta_number)` returning all findings that cite a given EFTA document.
- Component: 5
- Source: ROADMAP.md §"Component 5: Interface"
- Acceptance Criterion: Given an EFTA number with 3 associated findings, returns a list of exactly 3 findings. Given an EFTA with no findings, returns an empty list.

**FR-040** `[MVP]`
The Findings Store must support export of findings to JSON and CSV formats via `export_findings(format, filters)`.
- Component: 5
- Source: ROADMAP.md §"MVP Phase 2 — Findings export (JSON/CSV)", §"Component 5: Responsibilities"
- Acceptance Criterion: `export_findings("json", {})` returns valid JSON bytes parseable into a list of finding objects. `export_findings("csv", {})` returns valid UTF-8 CSV bytes with a header row. Both formats include all accepted findings when no filter is applied.

**FR-041** `[MVP]`
The Findings Store must expose `get_coverage(unit_type)` returning coverage statistics for a given work unit type.
- Component: 5
- Source: ROADMAP.md §"Component 5: Responsibilities — Support queries for coverage calculation"
- Acceptance Criterion: `get_coverage("verify_finding")` returns a `CoverageStats` object containing at minimum: units completed, units total, and a percentage value between 0.0 and 100.0.

**FR-042** `[POST-MVP]`
The Findings Store must support `apply_correction(finding_id, correction)` to record corrections to accepted findings, preserving the original result in the `corrections` table.
- Component: 5
- Source: ROADMAP.md §"Component 5: Interface — apply_correction"
- Acceptance Criterion: After `apply_correction("finding-abc", correction)`, a row exists in the `corrections` table with `finding_id="finding-abc"`, `original_json` matching the pre-correction state, and `corrected_json` matching the new state.

**FR-043** `[POST-MVP]`
The Findings Store must handle concurrent write operations without data corruption or lost updates.
- Component: 5
- Source: ROADMAP.md §"Testing Strategy — Concurrent write handling"
- Acceptance Criterion: Load test with 10 simultaneous workers each submitting a distinct finding results in exactly 10 findings stored with no duplicates and no SQLite locking errors.

---

### Component 6: Coverage Dashboard

**Source:** ROADMAP.md §"Component 6: Coverage Dashboard"

**FR-044** `[POST-MVP]`
The Coverage Dashboard must expose `GET /dashboard` serving a static HTML page displaying current analysis progress.
- Component: 6
- Source: ROADMAP.md §"Component 6: Endpoints"
- Acceptance Criterion: `GET /dashboard` returns HTTP 200 with `Content-Type: text/html`. The page contains coverage percentages for at minimum the two MVP work unit types.

**FR-045** `[POST-MVP]`
The Coverage Dashboard must expose `GET /api/coverage` returning a `CoverageStats` JSON object.
- Component: 6
- Source: ROADMAP.md §"Component 6: Endpoints"
- Acceptance Criterion: `GET /api/coverage` returns HTTP 200 with a JSON body containing per-type coverage percentages. Values are between 0.0 and 100.0.

**FR-046** `[POST-MVP]`
The Coverage Dashboard must expose `GET /api/leaderboard` returning a list of worker contribution statistics.
- Component: 6
- Source: ROADMAP.md §"Component 6: Endpoints"
- Acceptance Criterion: `GET /api/leaderboard` returns HTTP 200 with a JSON list where each entry contains at minimum `worker_id` and `units_completed` (a non-negative integer).

---

### System-Level Functional Requirements

**FR-047** `[MVP]`
The system must ingest the following rhowardstone JSON export files before generating any work units: `persons_registry.json`, `knowledge_graph_relationships.json`, `efta_dataset_mapping.json`.
- Component: System
- Source: ROADMAP.md §"MVP Phase 1 — Data Required"
- Acceptance Criterion: On system startup (or an explicit `ingest` command), all three files are loaded and their record counts are logged. If any file is missing, startup fails with a descriptive error identifying the missing file.

**FR-048** `[MVP]`
Workers must be able to complete the full work unit lifecycle — claim unit, fetch referenced PDFs from DOJ, submit findings — without any direct database access on the server side.
- Component: System
- Source: ROADMAP.md §"Zero-Corpus MVP Architecture"
- Acceptance Criterion: An end-to-end integration test with a simulated worker that has no database credentials successfully claims a unit, processes it (using mock HTTP calls to justice.gov), and submits a valid result that is accepted.

**FR-049** `[MVP]`
The system must generate unique `unit_id` values for every work unit; no two units share the same `unit_id`.
- Component: System
- Source: ROADMAP.md §"Component 2: WorkUnit dataclass — unit_id"
- Acceptance Criterion: Generating 1,000 work units and collecting all `unit_id` values produces a set of size 1,000 (no duplicates).

**FR-050** `[MVP]`
Every finding stored in `findings.db` must include a `worker_id` field identifying the worker that submitted it, and a `submitted_at` timestamp.
- Component: System
- Source: ROADMAP.md §"Component 5: Schema — worker_id, submitted_at"
- Acceptance Criterion: After submitting a result, the stored finding row has non-null `worker_id` and `submitted_at` fields. `submitted_at` is within 5 seconds of the submission time.

---

## Non-Functional Requirements (NFR)

**NFR-001** `[MVP]`
The system must be implemented in Python 3.10 or higher.
- Component: System
- Source: ROADMAP.md §"Appendix B", AGENTS.md §"Code Conventions"
- Acceptance Criterion: `python --version` in the project environment returns `3.10.x` or higher. The `pyproject.toml` specifies `python_requires = ">=3.10"`.

**NFR-002** `[MVP]`
All functions and methods must include type annotations.
- Component: System
- Source: ROADMAP.md §"Appendix B — Type-annotated (Python 3.10+)", AGENTS.md §"Code Conventions"
- Acceptance Criterion: Running `mypy src/` with strict mode produces zero "Missing type annotation" errors.

**NFR-003** `[MVP]`
All data models exchanged over the API must be defined as Pydantic models.
- Component: System
- Source: AGENTS.md §"Code Conventions — Pydantic for data models"
- Acceptance Criterion: Code review confirms all API request/response bodies and internal data transfer objects are defined as `pydantic.BaseModel` subclasses. No raw dicts are accepted at API boundaries.

**NFR-004** `[MVP]`
All database access must use raw SQL with parameterized queries; no ORM (e.g., SQLAlchemy, Tortoise) is permitted.
- Component: System
- Source: AGENTS.md §"Code Conventions — SQLite with raw SQL (no ORM)"
- Acceptance Criterion: Code review confirms no ORM imports exist in any source file. All `sqlite3` calls use the parameter substitution form (`?` placeholders), not string formatting.

**NFR-005** `[MVP]`
The test suite must use pytest.
- Component: System
- Source: AGENTS.md §"Code Conventions — pytest for testing"
- Acceptance Criterion: `pytest tests/` runs without configuration errors and all tests pass on a clean checkout.

**NFR-006** `[MVP]`
The server must hold no more than ~2MB of metadata in total for the MVP zero-corpus design. Source corpus databases must not be downloaded during MVP.
- Component: System
- Source: ROADMAP.md §"Zero-Corpus MVP Architecture", §"Hosting Considerations"
- Acceptance Criterion: A fresh checkout and startup of the MVP server, after ingesting the required JSON exports, has a `data/` directory totaling less than 5MB (allowing headroom for `findings.db` growth during testing).

**NFR-007** `[MVP]`
The MVP total API token cost must not exceed $25 USD for Phase 1 + Phase 2 combined.
- Component: System
- Source: ROADMAP.md §"Token Cost Estimates — MVP Budget: $20-25"
- Acceptance Criterion: After completing Phase 1 (10 `verify_finding` + 2 `decision_chain` batches) and Phase 2 validation, API cost logs show cumulative spend at or below $25.

**NFR-008** `[MVP]`
All source code must include module-level and function-level docstrings.
- Component: System
- Source: ROADMAP.md §"Appendix B — Documented with docstrings"
- Acceptance Criterion: Running `pydocstyle src/` produces zero missing-docstring errors.

**NFR-009** `[POST-MVP]`
The API must handle 10 concurrent workers without race conditions in work unit assignment.
- Component: System
- Source: ROADMAP.md §"Testing Strategy — Load Testing — Simulate 10 concurrent workers"
- Acceptance Criterion: Load test with 10 concurrent workers simultaneously calling `GET /work` results in each worker receiving a distinct `unit_id` with no unit assigned to two workers.

**NFR-010** `[POST-MVP]`
`GET /work` API response time must be under 500ms at the 95th percentile under a load of 10 concurrent workers.
- Component: System
- Source: ROADMAP.md §"Testing Strategy — Load Testing — Measure API response times under load" (implicit threshold)
- Acceptance Criterion: `locust` or equivalent load test with 10 workers shows P95 response time for `GET /work` below 500ms.

**NFR-011** `[POST-MVP]`
The system must be deployable on a single server; horizontal scaling is not required for MVP or Post-MVP phases.
- Component: System
- Source: ROADMAP.md §"Decisions Requiring Human Input — Scale-Up Architecture" (SQLite implies single-server), §"Post-MVP: Scale If Warranted"
- Acceptance Criterion: The deployment guide describes a single-server deployment with no external service dependencies beyond Python and SQLite.

---

## Ethical Constraints (EC)

All ethical constraints are hardcoded and non-configurable. They are implemented as validation layer rules. No runtime flag, environment variable, or API parameter may disable or bypass these constraints.

**Source:** ROADMAP.md §"Ethical Constraints (Hardcoded)"

**EC-001** `[MVP]`
PII Guardian must run on ALL result outputs before acceptance. Any result that triggers the PII Guardian must be quarantined and must not be written to the accepted findings dataset.
- Component: 4 (Validation Layer)
- Source: ROADMAP.md §"Ethical Constraints — #1"
- Implementation: Regex pattern matching + known name matching in `src/sefi/validation/pii.py`
- Acceptance Criterion: A result containing a phone number pattern submitted via `POST /result` returns `accepted=false` and `pii_detected=true`; the finding is stored with `status="quarantined"`, not `status="accepted"`.

**EC-002** `[MVP]`
Work units must never involve images or video. The Work Unit Generator must exclude DS10 media files and must not generate any unit type that involves image or video content.
- Component: 2 (Work Unit Generator)
- Source: ROADMAP.md §"Ethical Constraints — #2"
- Implementation: Generator filter in `src/sefi/generator/units.py` that excludes DS10 and skips any document record with image/video content type
- Acceptance Criterion: Inspection of all generated work units for `verify_finding` and `decision_chain` confirms zero instances reference image files, video files, or DS10 content.

**EC-003** `[MVP]`
When the PII Guardian detects victim names in a result output, the result must be quarantined and the incident must be logged. Optional: notification to `EFTA@usdoj.gov`.
- Component: 4 (Validation Layer)
- Source: ROADMAP.md §"Ethical Constraints — #3"
- Implementation: PII Guardian in `src/sefi/validation/pii.py`; quarantine in findings store
- Acceptance Criterion: A synthetic result containing a string from the victim name test list triggers: (a) `status="quarantined"` in findings store, (b) a log entry at ERROR level containing the unit_id and match type.

**EC-004** `[MVP]`
All findings produced by the system must be released as public domain with no licensing restrictions.
- Component: 5 (Findings Store), System
- Source: ROADMAP.md §"Ethical Constraints — #4", AGENTS.md §"Ethical Constraints — Public domain: All findings are CC0"
- Implementation: Findings export includes `"license": "CC0"` metadata; README documents the license
- Acceptance Criterion: The findings export JSON contains a top-level `"license": "CC0-1.0"` field. The project README states findings are public domain / CC0.

**EC-005** `[POST-MVP]`
For any finding that contains named individuals, the quorum threshold must be raised to 3-of-M (not the default 2-of-3). This threshold is not configurable below 3.
- Component: 4 (Validation Layer)
- Source: ROADMAP.md §"Ethical Constraints — #5"
- Implementation: Quorum Validator in `src/sefi/validation/quorum.py`; person name detection triggers elevated threshold
- Acceptance Criterion: A result containing a named individual is not marked `accepted` after 2 agreeing submissions. A third agreeing submission triggers `quorum_status="achieved"`.

**EC-006** `[MVP]`
All work unit metadata must clearly label whether source material originates from verified official documents or unverified public tips. Unverified tips must be marked as such in work unit metadata and in any derived finding.
- Component: 2 (Work Unit Generator), 5 (Findings Store)
- Source: ROADMAP.md §"Ethical Constraints — #6"
- Implementation: `WorkUnit` and `Finding` include a `source_verified: bool` field
- Acceptance Criterion: Work units derived from rhowardstone report claims have `source_verified=false` (pending verification). Findings derived from unverified units inherit `source_verified=false` and this field is preserved in all export formats.

**EC-007** `[MVP]`
Work unit instructions must explicitly prohibit any attempt to de-anonymize redacted content. Analysis of redaction patterns is permitted; inferring or recovering redacted content is not.
- Component: 2 (Work Unit Generator)
- Source: ROADMAP.md §"Ethical Constraints — #7", AGENTS.md §"Ethical Constraints — No de-anonymization"
- Implementation: Standard instruction template includes explicit prohibition language
- Acceptance Criterion: Every generated work unit's `instructions` field contains a verbatim prohibition statement (e.g., "Do not attempt to infer or recover redacted content. Analyze patterns only.").

---

## Data Requirements (DR)

**Source:** ROADMAP.md §"Component 5: Schema (findings.db)", §"Existing Metadata: Do Not Re-Extract", §"Data Layer: rhowardstone Databases"

### Input Data Files (Ingest; Do Not Re-Extract)

**DR-001** `[MVP]`
`persons_registry.json` must be ingested as the canonical person list. File contains 1,614 records. Each record must include at minimum: person identifier, name, category, and aliases.
- Source: ROADMAP.md §"Existing Metadata — persons_registry.json"
- Acceptance Criterion: Ingestion returns record count of 1,614. Each record validates against a Pydantic schema requiring the four minimum fields.

**DR-002** `[MVP]`
`knowledge_graph_relationships.json` must be ingested as seed relationship data. File contains 2,096 typed edges with weights and date ranges.
- Source: ROADMAP.md §"Existing Metadata — knowledge_graph_relationships.json"
- Acceptance Criterion: Ingestion returns record count of 2,096. Each record validates against a schema requiring: source entity, target entity, relationship type, and weight.

**DR-003** `[MVP]`
`efta_dataset_mapping.json` must be ingested to enable DOJ URL construction and EFTA gap resolution. File maps EFTA number ranges to the 12 DOJ datasets.
- Source: ROADMAP.md §"Existing Metadata — efta_dataset_mapping.json"
- Acceptance Criterion: After ingestion, a lookup of any EFTA number returns the correct primary dataset number (verifiable against the known range table). Lookup of an out-of-range EFTA returns a descriptive error.

**DR-004** `[MVP]`
`knowledge_graph_entities.json` must be ingested as seed entity data. File contains 524 entities including 489 people, 12 shell companies, 9 organizations, 7 properties, 4 aircraft, and 3 locations.
- Source: ROADMAP.md §"Existing Metadata — knowledge_graph_entities.json"
- Acceptance Criterion: Ingestion returns record count of 524. Breakdown by type matches the documented composition (489 people, 12 shells, etc.) within ±5 (to allow for data updates).

**DR-005** `[POST-MVP]`
`extracted_entities_filtered.json` (8,081 records) must be ingested as a read-only reference for entity linking; entities must not be re-extracted from source documents.
- Source: ROADMAP.md §"Existing Metadata — extracted_entities_filtered.json"
- Acceptance Criterion: After ingestion, `get_known_entities()` returns 8,081 records without any additional extraction step running.

**DR-006** `[POST-MVP]`
`document_summary.csv.gz` (519,438 records) and `reconstructed_pages_high_interest.json.gz` (39,588 records) must be ingested for redaction audit work units; redaction statistics must not be re-computed from source.
- Source: ROADMAP.md §"Existing Metadata — document_summary.csv.gz, reconstructed_pages_high_interest.json.gz"
- Acceptance Criterion: Ingestion of `document_summary.csv.gz` produces a working table with 519,438 rows. Ingestion of `reconstructed_pages_high_interest.json.gz` produces a working table with 39,588 rows.

### Output Database Schema (findings.db)

**DR-007** `[MVP]`
The `findings` table in `findings.db` must be created with the following schema and constraints:

```sql
CREATE TABLE findings (
    finding_id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    submitted_at TIMESTAMP NOT NULL,
    validated_at TIMESTAMP,
    status TEXT DEFAULT 'pending',
    result_json TEXT NOT NULL,
    quorum_count INTEGER DEFAULT 1,
    FOREIGN KEY (unit_id) REFERENCES work_units(unit_id)
);
```

- Source: ROADMAP.md §"Component 5: Schema (findings.db)"
- Acceptance Criterion: `pragma table_info(findings)` on a freshly created `findings.db` confirms all columns, types, and constraints match the specification exactly. `status` values are constrained to: `pending`, `accepted`, `disputed`, `quarantined`.

**DR-008** `[MVP]`
The `citations` table in `findings.db` must be created with the following schema:

```sql
CREATE TABLE citations (
    citation_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    efta_number TEXT NOT NULL,
    page_number INTEGER,
    quote TEXT,
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id)
);

CREATE INDEX idx_citations_efta ON citations(efta_number);
```

- Source: ROADMAP.md §"Component 5: Schema (findings.db)"
- Acceptance Criterion: The index exists and is used (confirmed via `EXPLAIN QUERY PLAN`) for queries filtering by `efta_number`.

**DR-009** `[POST-MVP]`
The `corrections` table in `findings.db` must be created with the following schema:

```sql
CREATE TABLE corrections (
    correction_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    corrected_by TEXT NOT NULL,
    corrected_at TIMESTAMP NOT NULL,
    reason TEXT,
    original_json TEXT,
    corrected_json TEXT
);
```

- Source: ROADMAP.md §"Component 5: Schema (findings.db)"
- Acceptance Criterion: After applying a correction, the `corrections` table contains a row with non-null `original_json` and `corrected_json` and the original finding's `result_json` matches `original_json`.

**DR-010** `[MVP]`
The `findings` table must have the following indexes:

```sql
CREATE INDEX idx_findings_unit_type ON findings(unit_type);
CREATE INDEX idx_findings_status ON findings(status);
```

- Source: ROADMAP.md §"Component 5: Schema (findings.db)"
- Acceptance Criterion: Both indexes exist in `findings.db` after schema initialization, confirmed by `pragma index_list(findings)`.

**DR-011** `[MVP]`
EFTA numbers in all tables and data structures must conform to the format `EFTA{XXXXXXXX}` where `{XXXXXXXX}` is a zero-padded 8-digit integer (e.g., `EFTA00039186`).
- Source: ROADMAP.md §"API Contracts — GET /work Response", AGENTS.md §"EFTA Numbers"
- Acceptance Criterion: A Pydantic validator on the `efta_number` field rejects strings that do not match the regex `^EFTA\d{8}$` with a descriptive validation error.

**DR-012** `[MVP]`
DOJ PDF URLs must conform to the pattern `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf` where `{N}` is an integer between 1 and 12 and `{XXXXXXXX}` is an 8-digit zero-padded integer.
- Source: ROADMAP.md §"EFTA Gap Resolution Logic", AGENTS.md §"EFTA Numbers"
- Acceptance Criterion: A Pydantic validator on URL fields rejects strings that do not match the expected pattern. The URL builder function is tested against 5 known EFTA-to-dataset mappings and produces correct URLs for all 5.

---

## API Contracts (AC)

**Source:** ROADMAP.md §"API Contracts"

### AC-001: GET /work — Response Schema `[MVP]`

Endpoint returns a single work unit JSON object.

```json
{
  "unit_id": "string",
  "type": "string (one of: verify_finding, decision_chain, [POST-MVP: 8 additional types])",
  "path": "integer (1-5)",
  "difficulty": "string (one of: low, medium, high)",
  "scaling": "string (one of: linear, multiplying, plateau, aggregation)",
  "optimal_batch": "string",
  "input": {
    "database": "string",
    "query": "string (optional)",
    "context": "string",
    "data": "array of strings or objects"
  },
  "instructions": "string (non-empty, includes de-anonymization prohibition)",
  "constraints": {
    "max_output_tokens": "integer",
    "pii_filter": "boolean",
    "requires_quorum": "boolean"
  },
  "deadline": "string (ISO 8601 datetime)"
}
```

- Acceptance Criterion: Every response from `GET /work` passes Pydantic validation against this schema. `type` field must be one of the defined work unit type strings. `path` must be between 1 and 5 inclusive.
- HTTP Status Codes: 200 (unit available), 204 or `{"available": false}` (no units available), 401 (invalid API key, POST-MVP only), 429 (rate limited, POST-MVP only).

**Special `verify_finding` fields:**

For units of type `verify_finding`, the `input` object must also include:
- `claim`: non-empty string describing the claim to verify
- `cited_eftas`: array of EFTA-format strings
- `efta_urls`: array of valid justice.gov PDF URLs, length matching `cited_eftas`

**Special `decision_chain` fields:**

For units of type `decision_chain`, the `input` object must also include:
- `time_window_start`: ISO 8601 date string
- `time_window_end`: ISO 8601 date string (within 30 days of start)
- `data`: array of 20–50 document references

---

### AC-002: POST /result — Request Schema `[MVP]`

```json
{
  "unit_id": "string (must match an existing, assigned unit_id)",
  "worker_id": "string (non-empty)",
  "result": "object (structure varies by unit type — see below)",
  "provenance": {
    "model": "string (e.g., 'claude-opus-4-5' or 'human')",
    "timestamp": "string (ISO 8601 datetime)",
    "session_tokens_used": "integer (non-negative)"
  }
}
```

- Acceptance Criterion: A body missing any required field returns HTTP 422 with a Pydantic validation error identifying the missing field. A body with a `unit_id` not found in the system returns HTTP 404.

**`verify_finding` result structure:**

```json
{
  "verdict": "string (one of: verified, disputed, insufficient_evidence)",
  "reasoning": "string",
  "citations": [
    {
      "efta_number": "string (EFTA format)",
      "page_number": "integer (optional)",
      "quote": "string (optional)"
    }
  ]
}
```

**`decision_chain` result structure:**

```json
{
  "communication_graph": [
    {
      "from": "string",
      "to": "string",
      "when": "string (ISO 8601 date)",
      "topic": "string",
      "efta_reference": "string (EFTA format)"
    }
  ],
  "patterns_observed": "string"
}
```

---

### AC-003: POST /result — Response Schema `[MVP]`

```json
{
  "accepted": "boolean",
  "finding_id": "string (present if accepted=true)",
  "quorum_status": "string (one of: achieved, pending, disputed)",
  "pii_detected": "boolean",
  "next_unit_available": "boolean"
}
```

- Acceptance Criterion: If `accepted=false` and `pii_detected=true`, no `finding_id` is returned. If `accepted=false` for non-PII reasons, an `errors` array is included with at least one descriptive string. If `accepted=true`, `finding_id` is a non-empty string matching the stored finding.

---

### AC-004: GET /status — Response Schema `[MVP]`

```json
{
  "total_units_generated": "integer (non-negative)",
  "total_units_assigned": "integer (non-negative)",
  "total_units_completed": "integer (non-negative)",
  "total_findings_accepted": "integer (non-negative)",
  "total_findings_quarantined": "integer (non-negative)",
  "coverage_by_type": {
    "verify_finding": "float (0.0 to 100.0)",
    "decision_chain": "float (0.0 to 100.0)"
  }
}
```

- Acceptance Criterion: All integer fields are non-negative. `total_units_completed <= total_units_assigned <= total_units_generated`. Coverage percentages are between 0.0 and 100.0 inclusive.

---

### AC-005: GET /health — Response Schema `[MVP]`

```json
{
  "status": "string (must be 'ok')",
  "version": "string",
  "findings_db_reachable": "boolean"
}
```

- Acceptance Criterion: Returns HTTP 200 within 500ms. If `findings.db` is unreachable, `findings_db_reachable=false` but HTTP status is still 200 (health check should not itself fail).

---

### AC-006: POST /dispute — Request/Response Schema `[POST-MVP]`

**Request:**
```json
{
  "finding_id": "string",
  "worker_id": "string",
  "reason": "string (non-empty)",
  "counter_evidence": "object (optional, same structure as result by type)"
}
```

**Response:**
```json
{
  "dispute_id": "string",
  "finding_id": "string",
  "status": "string (must be 'disputed')"
}
```

- Acceptance Criterion: A valid dispute against an existing `finding_id` returns HTTP 200, the finding status in `findings.db` is updated to `disputed`, and a log entry is created.

---

### AC-007: GET /api/coverage — Response Schema `[POST-MVP]`

```json
{
  "by_type": {
    "<unit_type>": {
      "completed": "integer",
      "total": "integer",
      "percent": "float (0.0 to 100.0)"
    }
  },
  "by_dataset": {
    "<dataset_N>": "float (0.0 to 100.0)"
  }
}
```

- Acceptance Criterion: `percent` equals `(completed / total) * 100` rounded to 2 decimal places. `completed <= total` for all types.

---

### AC-008: GET /api/leaderboard — Response Schema `[POST-MVP]`

```json
[
  {
    "worker_id": "string",
    "units_completed": "integer (non-negative)",
    "findings_accepted": "integer (non-negative)",
    "last_active": "string (ISO 8601 datetime)"
  }
]
```

- Acceptance Criterion: List is sorted by `units_completed` descending. Workers with zero completed units are excluded. Returns an empty list if no workers have contributed.

---

## Out of Scope (MVP)

The following items are explicitly deferred until after MVP demonstrates value. They must not be built during Phase 1 or Phase 2.

| Item | Rationale | Trigger for Activation |
|------|-----------|----------------------|
| Downloading `full_text_corpus.db` (6.08 GB) | Zero-corpus design; DOJ serves PDFs directly | DOJ rate-limits workers |
| Downloading `redaction_analysis_v2.db` (0.95 GB) | Not needed for `verify_finding` or `decision_chain` | Scaling to redaction work units |
| FTS5 full-text search | Workers fetch PDFs; server-side search not needed | Scaling to thousands of workers |
| Meilisearch or any external search service | FTS5 sufficient if ever needed | Specific feature gap identified |
| Work unit types other than `verify_finding` and `decision_chain` | 8 types deferred | MVP findings prove value |
| Full Validation Layer (Quorum Validator, PII Guardian pattern matching) | Phase 2 adds only basic provenance check | Multiple workers contributing |
| Worker authentication (API key system) | Not needed for solo/small pilot | Public pilot launch |
| Rate limiting | Not needed for solo/small pilot | Public pilot launch |
| Coverage Dashboard (Component 6) | Phase 3 feature | Public interest demonstrated |
| POST /dispute endpoint | Post-MVP validation feature | Full validation layer activation |
| GitHub sync for findings publication | Human review gate required first | Post-pilot decision |
| PostgreSQL migration | SQLite sufficient for MVP scale | Scale requiring multi-server |
| Corpus heatmap visualization | Dashboard is deferred | Dashboard activation |
| Real-time WebSocket updates | Phase 3 dashboard feature | Dashboard activation |
| `apply_correction()` workflow | Corrections require human review gate | Post-pilot |
| OAuth or federated authentication | API key sufficient for pilot | Scale requiring public auth |

---

## Open Questions (Blocking HITL Gate)

The following questions must be resolved by human decision before the indicated phase of implementation. Questions marked `[BLOCKS MVP]` must be answered before any code is written. Questions marked `[BLOCKS POST-MVP]` may be deferred until the MVP is complete.

**OQ-001** `[RESOLVED 2026-02-16]` — rhowardstone Coordination
- **Resolution:** No contact required. All four MVP JSON exports are publicly available from `https://github.com/rhowardstone/Epstein-research-data` and are public domain (U.S. government records under EFTA). Fetch commands documented in `/data/fetch.md`. Data does not require rhowardstone's cooperation.
- **Impact:** None blocking. MVP data acquisition is self-service.

**OQ-002** `[RESOLVED 2026-02-16]` — Hosting Strategy for Phase 1-2
- **Resolution:** Local development only. No cloud deployment for Phase 1-2. Single-developer prototype on the cheap.
- **Impact on testing:** Concurrent worker tests use simulated/mock workers on localhost. No external network configuration needed.

**OQ-003** `[RESOLVED 2026-02-16]` — API Funding Model
- **Resolution:** No current funding. Live API worker testing deferred until MVP looks worthwhile, at which point ~$20-25 will be sourced from a collaborator.
- **Impact on development:** The full test suite must work without live API calls. All worker behavior during development is tested via mocks/simulations. Live DOJ PDF fetching is not required to build or validate the server-side code.
- **Gate:** Live worker testing is a post-build milestone, not a development prerequisite.

**OQ-004** `[BLOCKS POST-MVP]` — PII Pattern List
What specific patterns should trigger PII Guardian quarantine beyond the four specified in FR-035 (victim name formats, postal addresses, phone numbers, SSNs)? Should the project contact `EFTA@usdoj.gov` for official guidance on known victim name patterns?
- Source: ROADMAP.md §"Component 4: PII Detection Approach", §"Decisions Requiring Human Input — PII Pattern List"
- Impact if unresolved: PII Guardian may have unacceptably high false negative rates for victim name detection. Contacting DOJ requires a human decision on whether to make that contact.
- Required Decision: Approved PII pattern list + decision on DOJ contact.

**OQ-005** `[BLOCKS POST-MVP]` — Quorum Configuration
Should the default quorum remain 2-of-3 for non-individual findings, or should it vary by work unit type? For example, should `decision_chain` require higher quorum than `verify_finding`?
- Source: ROADMAP.md §"Decisions Requiring Human Input — Quorum Configuration"
- Impact if unresolved: Quorum Validator cannot be implemented without knowing the per-type thresholds.
- Required Decision: Quorum table specifying N-of-M per work unit type (or confirmation that 2-of-3 applies uniformly to non-individual findings).

**OQ-006** `[BLOCKS POST-MVP]` — Worker Registration Policy
When opening to external workers: open registration, invite-only pilot, or institutional vetting? What constitutes an acceptable worker?
- Source: ROADMAP.md §"Decisions Requiring Human Input — Worker Registration"
- Impact if unresolved: Authentication system cannot be designed without knowing the registration model.
- Required Decision: Registration policy document approved by project owner.

**OQ-007** `[BLOCKS POST-MVP]` — Finding Publication Gate
What constitutes a "verified finding" worthy of publication? Is automatic GitHub sync acceptable, or must every finding pass human review first?
- Source: ROADMAP.md §"Decisions Requiring Human Input — Finding Publication"
- Impact if unresolved: Findings Store export and GitHub sync features cannot be built without knowing the publication gate.
- Required Decision: Publication policy: auto-sync threshold OR human-review-first workflow.

**OQ-008** `[OPEN]` — Scale-Up Architecture Decision Point
At what point (number of workers, findings, or time elapsed) should the team evaluate migrating from SQLite to PostgreSQL and from a single server to distributed infrastructure?
- Source: ROADMAP.md §"Decisions Requiring Human Input — Scale-Up Architecture"
- Impact if unresolved: SQLite can support MVP without issue; this decision only matters if the project scales.
- Required Decision: Documented scale triggers (e.g., "if > 100 concurrent workers, evaluate PostgreSQL").

---

## Requirements Review Score

This section applies the Requirements Reviewer rubric from `.claude/skills/requirements-reviewer/SKILL.md` and the Distributed Systems rubric from `.claude/skills/distributed-systems/SKILL.md` to the source specification (`ROADMAP.md`).

### Requirements Reviewer Rubric

| Section | Clarity (0-3) | Completeness (0-3) | Testability (0-3) | Feasibility (0-3) | Independence (0-3) | Notes |
|---------|--------------|-------------------|-------------------|-------------------|--------------------|-------|
| Project Overview / Architecture | 3 | 2 | 2 | 3 | 2 | Clear purpose; zero-corpus design well explained. Missing: formal system context diagram with component boundaries. External dependency on DOJ URL availability unstated. |
| Component 1 (Database Adapter) | 3 | 2 | 3 | 3 | 2 | Interface well-defined. Gap: schema details for all four DBs not confirmed (blocked on rhowardstone). Pooling semantics (max connections?) unspecified. |
| Component 2 (Work Unit Generator) | 3 | 2 | 2 | 3 | 2 | Scaling behavior table is excellent. Gap: no specification of what happens when all units are exhausted. Aggregation dependency trigger unspecified. |
| Component 3 (Distribution API) | 3 | 3 | 3 | 3 | 3 | Best-specified component. Rate limit values unspecified (deferred to HITL). No-units-available behavior for GET /work not specified in roadmap (addressed in AC-001 above). |
| Component 4 (Validation Layer) | 2 | 1 | 2 | 2 | 2 | PII pattern list is an open question. Quorum N-of-M per type unspecified. "Consistency Checker" referenced but never elaborated. |
| Component 5 (Findings Store) | 3 | 3 | 3 | 3 | 3 | Schema fully defined. Interface complete. Concurrent write handling addressed in testing. Strongest section. |
| Component 6 (Coverage Dashboard) | 2 | 1 | 2 | 3 | 2 | Three implementation options listed but no selection made. Refresh strategy unspecified. |
| Work Unit Types Reference | 3 | 2 | 2 | 3 | 2 | Token estimates present. Batch sizes present. Missing: success definition per type; no output schema for 8 post-MVP types. |
| EFTA Gap Resolution | 3 | 3 | 3 | 3 | 3 | Best-documented algorithm. Pseudocode, schema update, and unit focus table all present. |
| Ethical Constraints | 3 | 2 | 2 | 3 | 2 | All 7 stated. Implementation notes present. Gap: PII pattern list unresolved. |
| Testing Strategy | 2 | 2 | 2 | 2 | 2 | Section exists but lacks specific thresholds, coverage targets, and CI/CD guidance. |
| Data Acquisition / Ingest | 3 | 3 | 3 | 3 | 2 | Excellent. Record counts, file sizes, recommended actions all specified. Archive.org mirrors documented. |

**Overall Score: 12.3/15 — PASS (threshold: 8/15)**

### Overall Recommendation

**APPROVED — All MVP blockers resolved 2026-02-16. Ready for Phase 2 (Decompose).**

The ROADMAP.md is well above the block threshold on requirements quality. EFTA gap resolution, data acquisition, and API contracts are strong. MVP scope is clearly bounded.

#### Critical Gaps — Resolved (2026-02-16)

1. **OQ-001 — rhowardstone data access** ✅ Resolved. JSON exports are public domain on GitHub. No contact required. See OQ-001.
2. **Consistency Checker scope** ✅ Default applied: cross-checks against rhowardstone pre-extracted data only (persons registry, entities, relationships). No cross-worker comparison in MVP — single developer, no quorum needed.
3. **GET /work empty state** ✅ Default applied: HTTP 200 with `{"available": false}`. Workers poll on this response.
4. **POST /result idempotency** ✅ Default applied: idempotent. Duplicate submission for an already-accepted `unit_id` returns the existing `finding_id` with `accepted: true`. No error raised.
5. **DOJ URL fallback** ✅ Default applied: exponential backoff on HTTP 4xx/5xx. Moot during development — all worker tests use mocked HTTP. Live fallback deferred to post-build.

#### Deferred

- **PII Guardian pattern list (OQ-004):** Specific victim name patterns gathered during Post-MVP phase. MVP covers SSNs, phone numbers, postal addresses only.

---

*End of SEFI@Home Requirements Document*
*Generated: 2026-02-16 | Reviewer: Requirements Reviewer Agent (Sonnet) | Source: ROADMAP.md v1.0*
