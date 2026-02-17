# SEFI@Home: FastAPI + SQLite Prototype Roadmap

**Version:** 1.0
**Date:** 2026-02-16
**Purpose:** Implementation guide for building the distributed analysis platform prototype

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Summary](#architecture-summary)
3. [Data Layer: rhowardstone Databases](#data-layer-rhowardstone-databases)
4. [Component Specifications](#component-specifications)
   - [Component 1: Database Adapter](#component-1-database-adapter)
   - [Component 2: Work Unit Generator](#component-2-work-unit-generator)
   - [Component 3: Distribution API](#component-3-distribution-api)
   - [Component 4: Validation Layer](#component-4-validation-layer)
   - [Component 5: Findings Store](#component-5-findings-store)
   - [Component 6: Coverage Dashboard](#component-6-coverage-dashboard)
5. [Work Unit Types Reference](#work-unit-types-reference)
6. [API Contracts](#api-contracts)
7. [Implementation Phases](#implementation-phases)
8. [Decisions Requiring Human Input](#decisions-requiring-human-input)
9. [Token Cost Estimates](#token-cost-estimates)
10. [Testing Strategy](#testing-strategy)
11. [Ethical Constraints (Hardcoded)](#ethical-constraints-hardcoded)

---

## Project Overview

SEFI@Home (Search the Epstein Files Investigation) is a distributed analysis platform that coordinates volunteer "reasoning tokens" instead of CPU cycles. Workers (LLMs or humans) claim work units containing pre-materialized text slices, perform structured analysis, and return JSON findings with EFTA document provenance.

**Key Design Principles:**

- Workers never need the 6GB+ source databases; they receive text slices via API
- Every finding traces back to specific EFTA document numbers and pages
- Scaling behavior varies by task type (linear, multiplying, plateau, aggregation)
- PII protection is enforced at the validation layer, not trusted to workers
- Results require quorum validation before acceptance

**Source Materials:**

- Design document: `sefi-at-home.jsx` (React dashboard with architecture definitions)
- Upstream databases: [rhowardstone/Epstein-research-data](https://github.com/rhowardstone/Epstein-research-data)
- Analysis reports: [rhowardstone/Epstein-research](https://github.com/rhowardstone/Epstein-research)

---

## Architecture Summary

```
+-------------------+
|   Data Layer      |  SQLite databases (rhowardstone)
+-------------------+
         |
         v
+-------------------+
| Work Unit Generator|  Partitions corpus into analyzable chunks
+-------------------+
         |
         v
+-------------------+
| Distribution API  |  FastAPI endpoints for workers
+-------------------+
         |
         v
+-------------------+
| Validation Layer  |  Quorum, PII filter, consistency checks
+-------------------+
         |
         v
+-------------------+
|   Output Layer    |  Findings DB, coverage dashboard, GitHub sync
+-------------------+
```

---

## Data Layer: rhowardstone Databases

The following SQLite databases from rhowardstone/Epstein-research-data are required:

| Database | Size | Contents | Used By |
|----------|------|----------|---------|
| `full_text_corpus.db` | 6.08 GB | 1.38M documents, 2.73M pages with OCR text | Gap Analysis, Cross-Reference Audit, Document Classification, NPA Timeline, Decision Chain, Verification |
| `redaction_analysis_v2.db` | 0.95 GB | 2.59M redaction records with coordinates and hidden text | Redaction Consistency Check |
| `transcripts.db` | 2.5 MB | 1,530 audio/video transcript records | Timeline verification, cross-reference |
| `knowledge_graph.db` | 764 KB | 524 entities, 2,096 connections | Shell Company Mapping, Money Flow Tracing, Entity linking |

### Database Schema Requirements

Before implementation, obtain or reverse-engineer schemas for:

- `full_text_corpus.db`: tables for documents, pages, text content, EFTA numbers, dataset membership
- `redaction_analysis_v2.db`: redaction coordinates, document versions, hidden text fields
- `knowledge_graph.db`: entity nodes, relationship edges, confidence scores

**Action Required:** Contact rhowardstone via GitHub Issue to confirm schema details and request any undocumented table structures.

---

## Data Acquisition Strategy

### Download Sources

| Data Type | Source | Limit | Recommended |
|-----------|--------|-------|-------------|
| JSON exports (entities, persons, relationships) | GitHub | Minimal | ✅ Direct download |
| Small databases (knowledge_graph.db, transcripts.db) | GitHub | Minimal | ✅ Direct download |
| Large databases (full_text_corpus.db) | GitHub LFS | 1 GB/month free | ❌ Use Archive.org |
| Large databases | **Archive.org** | None | ✅ Recommended |

### Archive.org Mirrors (rhowardstone's existing endpoints)

These are public and already set up — no configuration needed:

```bash
# Dataset 9 (largest, 103.6 GB raw)
wget https://archive.org/download/Epstein-Dataset-9-2026-01-30/full.tar.bz2

# Dataset 11 (25.6 GB)
wget https://archive.org/download/Epstein-Data-Sets-So-Far/DataSet%2011.zip

# Datasets 1-5 combined
wget https://archive.org/download/combined-all-epstein-files/[files]
```

### Search: No Meilisearch Needed

**Critical simplification:** rhowardstone's `full_text_corpus.db` already includes an **FTS5 full-text search index**.

SQLite FTS5 provides:
- Fast full-text search across 2.7M pages
- No external service required
- No rate limits
- Built into the database

```python
# FTS5 search — already works out of the box
import sqlite3
conn = sqlite3.connect('full_text_corpus.db')

results = conn.execute("""
    SELECT efta_number, page_number,
           snippet(pages_fts, 2, '<b>', '</b>', '...', 32)
    FROM pages_fts
    WHERE pages_fts MATCH 'southern trust'
    LIMIT 20
""").fetchall()
```

**Do NOT add Meilisearch** unless you specifically need features FTS5 lacks (typo tolerance, faceting, etc.). For SEFI@Home prototype, FTS5 is sufficient.

### Hosting Considerations

| Scenario | Data Location | Notes |
|----------|---------------|-------|
| **MVP Development** | JSON exports only (~2MB) | No corpus download needed |
| **MVP Workers** | None | Fetch PDFs directly from DOJ URLs |
| **Full Server (later)** | Full corpus | Only if scaling beyond MVP |

### Zero-Corpus MVP Architecture

The MVP does NOT require downloading the 6GB corpus. Instead:

1. **Work units embed DOJ URLs** — Workers fetch PDFs directly from justice.gov
2. **Orchestration data only** — We need JSON exports (~2MB total), not the corpus
3. **DOJ serves the documents** — No bandwidth cost on our side

```
┌─────────────────────────────────────────────────────┐
│  SEFI@Home Server (MVP)                            │
│  - persons_registry.json (~500KB)                  │
│  - knowledge_graph_relationships.json (~200KB)     │
│  - rhowardstone report claims (~1MB)               │
│  - findings.db (generated)                         │
└───────────────────────┬─────────────────────────────┘
                        │ GET /work
                        ▼
              ┌─────────────────────┐
              │  Work Unit JSON     │
              │  - claim text       │
              │  - DOJ PDF URLs     │◄─────────────┐
              │  - instructions     │              │
              └─────────┬───────────┘              │
                        │                          │
                        ▼                          │
              ┌─────────────────────┐    ┌─────────┴─────────┐
              │  Worker (Claude)    │───►│  justice.gov      │
              │  Fetches PDFs       │    │  (serves PDFs)    │
              │  Analyzes           │    └───────────────────┘
              │  Returns findings   │
              └─────────┬───────────┘
                        │ POST /result
                        ▼
              ┌─────────────────────┐
              │  findings.db        │
              └─────────────────────┘
```

**When to download full corpus:**
- Only if DOJ rate-limits our workers
- Only if we need FTS5 search for work unit generation
- Only if scaling to thousands of workers

For MVP with 10-50 work units: **zero corpus download required**.

---

## Existing Metadata: Do Not Re-Extract

**Critical:** rhowardstone has already performed substantial extraction work. The prototype should **ingest these existing exports** rather than re-extracting from raw documents.

### Pre-Extracted JSON/CSV Files (Ingest These)

| File | Records | Contents | Prototype Action |
|------|---------|----------|------------------|
| `knowledge_graph_entities.json` | 524 | 489 people, 12 shell companies, 9 orgs, 7 properties, 4 aircraft, 3 locations with aliases | **Ingest as seed data** for entity linking |
| `knowledge_graph_relationships.json` | 2,096 | Typed edges (traveled_with, owned_by, victim_of, etc.) with weights and date ranges | **Ingest as seed data** for relationship mapping |
| `persons_registry.json` | 1,614 | Unified person registry from 6 sources with categories and aliases | **Ingest as canonical person list** |
| `extracted_entities_filtered.json` | 8,081 | 3,881 names, 2,238 phones, 1,489 amounts, 357 emails, 116 orgs | **Ingest as extracted entities** — do not re-extract |
| `document_summary.csv.gz` | 519,438 | Per-document redaction stats (proper vs bad vs recoverable) | **Ingest for redaction audit** — stats already computed |
| `reconstructed_pages_high_interest.json.gz` | 39,588 | Pages with text recovered from redactions | **Ingest for redaction analysis** — already reconstructed |
| `image_catalog.csv.gz` | 38,955 | AI-analyzed images with people, objects, settings | **Reference only** (text-only analysis policy) |
| `efta_dataset_mapping.json` | — | EFTA number ranges mapped to 12 DOJ datasets | **Required for gap resolution** (see below) |

---

## EFTA Gap Resolution Logic

**Important:** Apparent gaps between EFTA number ranges are often NOT missing documents. The DOJ's filing was inconsistent — documents may exist in adjacent datasets.

### The Problem

EFTA numbers are organized into 12 datasets, each covering a range. But ranges aren't perfectly contiguous:

```
Dataset 5: EFTA00005000 – EFTA00006000
Dataset 6: EFTA00006001 – EFTA00007000

Gap observed: EFTA00005587 – EFTA00005704 not in Dataset 5
Reality: These documents exist in Dataset 4 or Dataset 6
```

### Resolution Algorithm

> ✅ Implemented (US-003) — `src/sefi/db/efta.py` provides `build_url()`, `resolve_efta()`, `get_primary_dataset()`, `ResolutionResult`, `EftaNumber`, and `EftaUrl`.

Before flagging an EFTA as "missing," the Gap Analysis work unit must try adjacent datasets:

```python
def resolve_efta(efta_number: int, primary_dataset: int) -> ResolutionResult:
    """
    Attempt to resolve an EFTA number to a valid DOJ URL.
    Returns the URL and dataset where found, or marks as genuinely missing.
    """
    datasets_to_try = [primary_dataset, primary_dataset - 1, primary_dataset + 1]

    for ds in datasets_to_try:
        if ds < 1 or ds > 12:
            continue
        url = f"https://www.justice.gov/epstein/files/DataSet%20{ds}/EFTA{efta_number:08d}.pdf"
        if check_url_exists(url):  # HEAD request or cached lookup
            return ResolutionResult(
                found=True,
                url=url,
                dataset=ds,
                was_adjacent=(ds != primary_dataset)
            )

    return ResolutionResult(found=False, genuinely_missing=True)
```

### Work Unit Generator Update

The Gap Analysis generator must:

1. Use `efta_dataset_mapping.json` to determine primary dataset for each EFTA range
2. Include adjacent dataset info in work unit context
3. Instruct workers to try fallback resolution before reporting gaps

### Gap Analysis Result Schema Update

```json
{
  "gaps_found": 14,
  "gaps": [
    {
      "start": 39187,
      "end": 39201,
      "size": 14,
      "resolution_attempts": [
        {"dataset": 9, "result": "not_found"},
        {"dataset": 8, "result": "not_found"},
        {"dataset": 10, "result": "not_found"}
      ],
      "status": "genuinely_missing",
      "adjacent_context": "..."
    }
  ],
  "false_positives_avoided": 3,
  "notes": "3 apparent gaps resolved via adjacent dataset lookup"
}
```

### Work Unit Focus Adjustment

| Original Work Unit | Status | Adjusted Focus |
|--------------------|--------|----------------|
| Entity Extraction | ✅ Already done | **Verify & extend** existing 8,081 entities |
| Shell Company Mapping | ✅ Partial (12 known) | **Link** known shells to amounts; discover new ones |
| Redaction Analysis | ✅ Already done | **Audit patterns** across 39,588 reconstructed pages |
| Document Classification | ❌ Not done | Still needed |
| Gap Analysis | ❌ Not done | Still needed (with resolution logic below) |
| NPA Timeline | ❌ Not done | Still needed |
| Decision Chain Mapping | ❌ Not done | Still needed |
| Money Flow Tracing | ❌ Not done | Build on extracted entities |
| Finding Verification | ❌ Not done | Verify claims in rhowardstone reports |

### Component 1 Update: Database Adapter Must Load JSON Exports

✅ Implemented (US-002) — `src/sefi/db/ingest.py` provides `IngestManager` with `ingest_all()` loading all four JSON exports into SQLite working tables (`persons`, `entities`, `relationships`, `efta_mapping`).

Add methods to ingest pre-extracted JSON files into working tables:

```python
class DatabaseAdapter:
    # ... existing methods ...

    def load_json_export(self, file_path: Path, table_name: str) -> int:
        """Load rhowardstone JSON export into a working table. Returns record count."""
        ...

    def get_known_entities(self) -> List[Dict]:
        """Return all entities from knowledge_graph_entities.json."""
        ...

    def get_known_relationships(self) -> List[Dict]:
        """Return all relationships from knowledge_graph_relationships.json."""
        ...

    def get_persons_registry(self) -> List[Dict]:
        """Return unified person registry."""
        ...
```

---

## Component Specifications

### Component 1: Database Adapter

> ✅ Implemented (US-004)

**Purpose:** Read-only interface to rhowardstone SQLite databases

**Responsibilities:**

- Connection pooling for concurrent reads
- Query execution with parameterization (prevent SQL injection)
- Result pagination for large queries
- Schema validation on startup

**Dependencies:** None (foundational component)

**Databases Used:** All four databases

**Interface:**

```python
class DatabaseAdapter:
    def __init__(self, db_paths: Dict[str, Path]): ...

    def query(self, db_name: str, sql: str, params: tuple) -> List[Dict]: ...

    def paginated_query(self, db_name: str, sql: str, params: tuple,
                        page_size: int, offset: int) -> Tuple[List[Dict], int]: ...

    def get_efta_range(self, dataset: int, start: int, end: int) -> List[Dict]: ...

    def get_document_versions(self, efta_number: str) -> List[Dict]: ...

    def get_redactions_for_document(self, efta_number: str) -> List[Dict]: ...
```

**Testing:** Unit tests with a small sample database (first 1000 documents)

---

### Component 2: Work Unit Generator

> ✅ Partially Implemented (US-003) — EFTA URL builder and gap resolution algorithm complete in `src/sefi/db/efta.py`.
> ✅ Implemented (US-005) — `WorkUnit` dataclass and `WorkUnitGenerator` with `verify_finding` type complete in `src/sefi/generator/units.py`.
> ✅ Implemented (US-006) — `decision_chain` generator with 30-day time-window bucketing and batch size enforcement (20–50 docs) complete in `src/sefi/generator/units.py`.

**Purpose:** Partition the corpus into self-contained work units based on task type and scaling behavior

**Responsibilities:**

- Generate work units for each of the 10 work unit types
- Apply scaling-aware batching (different batch sizes for linear vs. multiplying tasks)
- Pre-materialize text content so workers don't need database access
- Track which ranges/documents have been assigned
- Manage dependencies between extraction and aggregation units

**Dependencies:** Database Adapter

**Databases Used:** `full_text_corpus.db`, `redaction_analysis_v2.db`

**Scaling Behavior Implementation:**

| Scaling Type | Batch Strategy |
|--------------|----------------|
| `linear` | Fixed batch size (e.g., 20 documents per unit) |
| `multiplying` | Larger batches from same time window or dataset (e.g., 50-100 transactions) |
| `plateau` | Batch to sweet spot then stop (e.g., 500 pages for cross-references) |
| `aggregation` | Two-phase: extraction units (1 doc each) + aggregation units (50+ results) |

**Interface:**

```python
class WorkUnitGenerator:
    def __init__(self, db_adapter: DatabaseAdapter): ...

    def generate_unit(self, unit_type: str,
                      constraints: Optional[Dict] = None) -> WorkUnit: ...

    def generate_batch(self, unit_type: str, count: int) -> List[WorkUnit]: ...

    def get_pending_aggregation_units(self, extraction_type: str) -> List[WorkUnit]: ...

    def mark_unit_assigned(self, unit_id: str, worker_id: str) -> None: ...

    def mark_unit_complete(self, unit_id: str) -> None: ...

@dataclass
class WorkUnit:
    unit_id: str           # e.g., "gap-ds9-039025-040000"
    type: str              # e.g., "gap_analysis"
    path: int              # Research path 1-5
    difficulty: str        # "low", "medium", "high"
    scaling: str           # "linear", "multiplying", "plateau", "aggregation"
    optimal_batch: str     # Human-readable batch description
    input: WorkUnitInput   # Pre-materialized data
    instructions: str      # What the worker should do
    constraints: Dict      # max_output_tokens, requires_quorum, etc.
    deadline: datetime
```

**Testing:** Integration tests generating units for each type, verify batch sizes match scaling rules

---

### Component 3: Distribution API

**Purpose:** FastAPI server exposing work units to external workers

**Responsibilities:**

- `GET /work` - Claim an available work unit
- `POST /result` - Submit analysis results
- `GET /status` - Project statistics and coverage
- `POST /dispute` - Flag a result for re-analysis
- Worker authentication (API key based)
- Rate limiting per worker

**Dependencies:** Work Unit Generator, Validation Layer

**Databases Used:** None directly (works through generator)

**Endpoints:**

```
GET  /work
     ?type={work_unit_type}     # Optional filter
     ?difficulty={low|medium|high}
     ?path={1-5}
     -> WorkUnit JSON

POST /result
     Body: ResultSubmission JSON
     -> AcceptanceResponse JSON

GET  /status
     -> ProjectStats JSON

POST /dispute
     Body: DisputeRequest JSON
     -> DisputeResponse JSON

GET  /health
     -> HealthCheck JSON
```

**Authentication:**

- API key in header: `X-SEFI-API-Key: <key>`
- Keys map to worker_id for tracking
- Consider OAuth for future scaling

**Testing:** API contract tests, load testing with simulated workers

---

### Component 4: Validation Layer

**Purpose:** Ensure result quality before acceptance into findings database

**Responsibilities:**

- **Quorum Validator:** Require N-of-M agreement for results (default: 2-of-3)
- **PII Guardian:** Scan outputs for victim-identifying information, quarantine matches
- **Consistency Checker:** Cross-check against known-good reference data
- **Provenance Logger:** Verify all claims trace to valid EFTA documents

**Dependencies:** Database Adapter (for reference checks), Findings Store (for quorum tracking)

**Databases Used:** `full_text_corpus.db` (document existence verification)

**Interface:**

```python
class ValidationLayer:
    def __init__(self, db_adapter: DatabaseAdapter,
                 findings_store: FindingsStore,
                 pii_patterns: List[str]): ...

    def validate_result(self, result: ResultSubmission) -> ValidationResult: ...

    def check_quorum(self, unit_id: str) -> QuorumStatus: ...

    def scan_for_pii(self, text: str) -> List[PIIMatch]: ...

    def verify_provenance(self, citations: List[Citation]) -> List[ProvenanceError]: ...

@dataclass
class ValidationResult:
    accepted: bool
    quorum_status: QuorumStatus  # "pending", "achieved", "disputed"
    pii_detected: bool
    pii_matches: List[PIIMatch]  # If detected, result is quarantined
    provenance_valid: bool
    errors: List[str]
```

**PII Detection Approach:**

- Pattern matching for known victim name formats (redacted in source, may leak in outputs)
- Address/phone number detection
- Social security number patterns
- Known victim name list (if available from DOJ reporting channel)

**Action Required:** Determine PII pattern list. Consider consulting with EFTA@usdoj.gov about known patterns.

**Testing:** Unit tests with synthetic PII, integration tests with quorum scenarios

---

### Component 5: Findings Store

> ✅ Implemented (US-007)

**Purpose:** Persistent storage for validated analysis results

**Responsibilities:**

- Store accepted findings with full provenance
- Index by EFTA document, entity, date, finding type
- Support queries for coverage calculation
- Export to structured formats (JSON, CSV)
- Track finding history and corrections

**Dependencies:** Validation Layer (receives validated results)

**Databases Used:** Creates new `findings.db`

**Schema (findings.db):**

```sql
CREATE TABLE findings (
    finding_id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    submitted_at TIMESTAMP NOT NULL,
    validated_at TIMESTAMP,
    status TEXT DEFAULT 'pending',  -- pending, accepted, disputed, quarantined
    result_json TEXT NOT NULL,
    quorum_count INTEGER DEFAULT 1,
    FOREIGN KEY (unit_id) REFERENCES work_units(unit_id)
);

CREATE TABLE citations (
    citation_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    efta_number TEXT NOT NULL,
    page_number INTEGER,
    quote TEXT,
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id)
);

CREATE TABLE corrections (
    correction_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    corrected_by TEXT NOT NULL,
    corrected_at TIMESTAMP NOT NULL,
    reason TEXT,
    original_json TEXT,
    corrected_json TEXT
);

CREATE INDEX idx_findings_unit_type ON findings(unit_type);
CREATE INDEX idx_findings_status ON findings(status);
CREATE INDEX idx_citations_efta ON citations(efta_number);
```

**Interface:**

```python
class FindingsStore:
    def __init__(self, db_path: Path): ...

    def store_finding(self, finding: Finding) -> str: ...

    def get_findings_for_document(self, efta_number: str) -> List[Finding]: ...

    def get_coverage(self, unit_type: str) -> CoverageStats: ...

    def export_findings(self, format: str, filters: Dict) -> bytes: ...

    def apply_correction(self, finding_id: str, correction: Correction) -> None: ...
```

**Testing:** CRUD tests, export format verification, concurrent write handling

---

### Component 6: Coverage Dashboard

**Purpose:** Web interface showing analysis progress and project statistics

**Responsibilities:**

- Display coverage percentage per work unit type
- Show leaderboard of worker contributions
- Visualize corpus coverage heatmap by dataset
- Real-time updates via WebSocket (optional for MVP)

**Dependencies:** Findings Store, Distribution API (for status endpoint)

**Implementation Options:**

1. **Minimal (Phase 1):** Static HTML served by FastAPI, refresh to update
2. **Interactive (Phase 2):** React frontend (can reuse `sefi-at-home.jsx` components)
3. **Real-time (Phase 3):** WebSocket updates for live progress

**Endpoints (served by Distribution API):**

```
GET /dashboard
    -> HTML page

GET /api/coverage
    -> CoverageStats JSON

GET /api/leaderboard
    -> List[WorkerStats] JSON
```

**Testing:** Smoke tests for page load, API response validation

---

## Work Unit Types Reference

| ID | Name | Path | Difficulty | Scaling | Optimal Batch | Est. Tokens | Database |
|----|------|------|------------|---------|---------------|-------------|----------|
| `gap_analysis` | Gap Analysis | 2 | low | linear | 1,000 EFTA numbers | ~2K/range | full_text_corpus.db |
| `cross_ref_audit` | Cross-Reference Audit | 2 | medium | plateau | 500 pages (same dataset) | ~20K/batch | full_text_corpus.db |
| `document_classify` | Document Classification | 2 | low | linear | 20 documents | ~1K/doc | full_text_corpus.db |
| `npa_timeline` | NPA Timeline Extraction | 3 | high | aggregation | 1 doc extract, 50+ events aggregate | ~8K/doc | full_text_corpus.db |
| `decision_chain` | Decision Chain Mapping | 3 | high | multiplying | 20-50 docs (same 30-day period) | ~30-40K/batch | full_text_corpus.db |
| `entity_extraction` | Financial Entity NER | 4 | medium | aggregation | 20 pages extract, 200+ records dedupe | ~4K/batch | full_text_corpus.db |
| `money_flow` | Money Flow Tracing | 4 | high | multiplying | 50-100 transactions | ~20K/batch | knowledge_graph.db |
| `shell_mapping` | Shell Company Mapping | 4 | medium | plateau | 10-20 entity mentions | ~3K/cluster | knowledge_graph.db |
| `redaction_compare` | Redaction Consistency Check | 1 | medium | plateau | All versions of 1 document | ~8K/doc | redaction_analysis_v2.db |
| `verify_finding` | Finding Verification | 5 | low | linear | 1 claim | ~4K/claim | full_text_corpus.db |

**Research Paths:**

1. Redaction Audit
2. Gap Analysis
3. NPA Forensics
4. Financial Network
5. Verification

---

## API Contracts

### GET /work Response

```json
{
  "unit_id": "gap-ds9-039025-040000",
  "type": "gap_analysis",
  "path": 2,
  "difficulty": "low",
  "scaling": "linear",
  "optimal_batch": "1,000 EFTA numbers",
  "input": {
    "database": "full_text_corpus.db",
    "query": "SELECT efta_number FROM pages WHERE efta_number BETWEEN 39025 AND 40000 ORDER BY efta_number",
    "context": "DS9 range - email evidence dataset",
    "data": ["EFTA00039025", "EFTA00039026", "..."]
  },
  "instructions": "Identify all gaps in EFTA numbering. For each gap, check if adjacent documents reference the missing numbers. Report: gap_start, gap_end, gap_size, adjacent_context.",
  "constraints": {
    "max_output_tokens": 2000,
    "pii_filter": true,
    "requires_quorum": false
  },
  "deadline": "2026-02-17T00:00:00Z"
}
```

### POST /result Request

```json
{
  "unit_id": "gap-ds9-039025-040000",
  "worker_id": "claude-session-abc123",
  "result": {
    "gaps_found": 14,
    "gaps": [
      {
        "start": 39187,
        "end": 39201,
        "size": 14,
        "adjacent_before": "EFTA00039186: Email re: NPA discussion",
        "adjacent_after": "EFTA00039202: FBI 302 interview",
        "assessment": "Gap falls within NPA correspondence sequence"
      }
    ],
    "coverage": {
      "range_start": 39025,
      "range_end": 40000,
      "total_present": 961,
      "total_missing": 14
    }
  },
  "provenance": {
    "model": "claude-opus-4-5",
    "timestamp": "2026-02-16T18:30:00Z",
    "session_tokens_used": 1847
  }
}
```

### POST /result Response

```json
{
  "accepted": true,
  "finding_id": "finding-abc123",
  "quorum_status": "achieved",
  "pii_detected": false,
  "next_unit_available": true
}
```

---

## Implementation Phases

### MVP Phase 1: Zero-Corpus Prototype (Week 1)

**Goal:** Working prototype with 2 work unit types, no corpus download

**Data Required:**
- [ ] Download `persons_registry.json` (~500KB)
- [ ] Download `knowledge_graph_relationships.json` (~200KB)
- [ ] Extract claims from rhowardstone reports (~1MB)
- [ ] Download `efta_dataset_mapping.json` (for URL construction)

**Components:**
- [ ] Work Unit Generator (verify_finding + decision_chain only)
- [ ] Distribution API (GET /work, POST /result, GET /status)
- [ ] Basic Findings Store (SQLite)
- [ ] DOJ URL builder (EFTA → PDF URL)

**Work Unit Structure:**
```json
{
  "unit_id": "verify-claim-047",
  "type": "verify_finding",
  "claim": "Acosta met with Epstein's lawyers in March 2008",
  "cited_eftas": ["EFTA00039186"],
  "efta_urls": ["https://justice.gov/epstein/files/DataSet%209/EFTA00039186.pdf"],
  "instructions": "Fetch the PDF. Does it support the claim?"
}
```

**Deliverable:** Claim a work unit → Worker fetches from DOJ → Submit findings

**Cost:** ~$15 (10 verify_finding + 2 decision_chain batches)

---

### MVP Phase 2: Validation & Writeup (Week 2)

**Goal:** Document what MVP found, light validation

**Components:**
- [ ] Basic provenance check (cited EFTA exists)
- [ ] Result deduplication
- [ ] Findings export (JSON/CSV)

**Deliverable:** "What $15 of Claude API time discovered" — shareable report

**Cost:** ~$5-10 for additional testing

---

### Post-MVP: Scale If Warranted

Only pursue these if MVP demonstrates value:

| Phase | Trigger | What It Adds |
|-------|---------|--------------|
| **Corpus Download** | DOJ rate-limits workers | Local PDF serving |
| **More Work Units** | Verify findings compelling | Other 8 types |
| **Validation Layer** | Multiple workers contributing | Quorum, PII Guardian |
| **Dashboard** | Public interest | Coverage viz, leaderboard |
| **Full Infrastructure** | Grant/funding secured | Auth, scaling, GitHub sync |

**Do not build beyond MVP until MVP proves the concept.**

---

## Decisions Requiring Human Input

### Before Development Starts

1. **rhowardstone Coordination**
   - Has contact been made via GitHub Issue?
   - Is there buy-in for SEFI@Home using their databases?
   - Can we get schema documentation or sample data?

2. **Hosting Strategy**
   - Local development only for Phase 1-4?
   - Cloud deployment for Phase 5? (Consider cost implications)
   - Where will the 6GB+ databases be hosted?

3. **API Funding Model**
   - Self-funded prototype ($200-500)?
   - Crowdfunding for pilot?
   - Grant application strategy?

### During Development

4. **PII Pattern List**
   - What specific patterns should trigger quarantine?
   - Should we contact EFTA@usdoj.gov for guidance?

5. **Quorum Configuration**
   - Default 2-of-3, or different per work unit type?
   - Higher quorum for findings involving named individuals?

6. **Worker Registration**
   - Open registration or invite-only for pilot?
   - Any vetting process for workers?

### After Pilot

7. **Finding Publication**
   - Automatic GitHub sync, or human review first?
   - What constitutes a "verified finding" worthy of publication?

8. **Scale-Up Architecture**
   - Stay on SQLite or migrate to PostgreSQL?
   - Single server or distributed?

---

## Token Cost Estimates

### Per Work Unit Type (Single Unit)

| Type | Tokens In | Tokens Out | Estimated Cost* |
|------|-----------|------------|-----------------|
| gap_analysis | ~1.5K | ~0.5K | $0.05 |
| cross_ref_audit | ~15K | ~5K | $0.50 |
| document_classify | ~0.8K | ~0.2K | $0.03 |
| npa_timeline | ~6K | ~2K | $0.20 |
| decision_chain | ~25K | ~10K | $0.90 |
| entity_extraction | ~3K | ~1K | $0.10 |
| money_flow | ~15K | ~5K | $0.50 |
| shell_mapping | ~2K | ~1K | $0.08 |
| redaction_compare | ~6K | ~2K | $0.20 |
| verify_finding | ~3K | ~1K | $0.10 |

*Estimates based on Claude Sonnet pricing (~$3/1M input, $15/1M output). Opus costs approximately 5x more.

### Corpus Coverage Estimates

| Goal | Work Units | Est. Cost (Sonnet) |
|------|------------|-------------------|
| 10% DS9 coverage (gap analysis) | ~100 units | ~$5 |
| 10% DS9 coverage (cross-ref audit) | ~50 units | ~$25 |
| Full DS9 NPA timeline | ~500 extraction + 10 aggregation | ~$110 |
| Full financial network map | ~200 money flow + 50 shell mapping | ~$105 |

### MVP Budget

| Phase | Estimated Cost |
|-------|---------------|
| MVP Phase 1 (Zero-Corpus Prototype) | $15 |
| MVP Phase 2 (Validation & Writeup) | $5-10 |
| **Total MVP** | **$20-25** |

### Post-MVP Budget (Only If Warranted)

| Expansion | Estimated Cost |
|-----------|---------------|
| Additional work unit types | $50-100 |
| Full validation layer | $30-50 |
| Pilot at scale (100+ units) | $100-200 |

---

## Testing Strategy

### Unit Tests (Per Component)

- Database Adapter: Query execution, pagination, error handling
- Work Unit Generator: Batch sizing per scaling type, dependency resolution
- Validation Layer: PII detection, quorum logic, provenance verification
- Findings Store: CRUD operations, concurrent access

### Integration Tests

- End-to-end work unit lifecycle (claim -> process -> validate -> store)
- API contract compliance
- Multi-worker quorum scenarios

### Test Data

- Create `test_corpus.db` with first 1,000 documents from full_text_corpus.db
- Synthetic redaction data for redaction_compare testing
- Known-answer test cases for verification

### Load Testing

- Simulate 10 concurrent workers claiming/submitting
- Measure API response times under load
- Verify no race conditions in unit assignment

---

## Ethical Constraints (Hardcoded)

These are not configurable. They are implemented as validation layer rules that reject non-compliant results.

1. **PII Guardian runs on ALL outputs before acceptance**
   - Implementation: Regex patterns + known name matching
   - Action: Quarantine result, log for review

2. **No work units involve images or video**
   - Implementation: Work Unit Generator excludes DS10 media files
   - Note: Text-only analysis; visual content not processed

3. **Victim names detected in output -> unit quarantined + reported**
   - Implementation: PII Guardian pattern matching
   - Action: Result quarantined, optional email to EFTA@usdoj.gov

4. **All results are public domain**
   - Implementation: No licensing restrictions on findings
   - Note: Federal government source material

5. **Quorum of 3 required for findings involving named individuals**
   - Implementation: Quorum Validator detects person names, raises threshold
   - Note: Higher bar for potentially sensitive findings

6. **Unverified FBI tips clearly labeled**
   - Implementation: Source tracking in Work Unit metadata
   - Note: Tips from public submissions marked as unverified

7. **No attempt to de-anonymize redactions**
   - Implementation: Work unit instructions explicitly prohibit this
   - Note: Analysis of redaction patterns only, not content recovery

---

## Appendix A: Directory Structure

✅ Implemented (US-001) — Project scaffolding complete: pyproject.toml, src/sefi/ package hierarchy, config.py, subpackage inits, and tests/ tree are all in place.

```
sefi-at-home/
├── README.md
├── ROADMAP.md                 # This document
├── pyproject.toml
├── requirements.txt
├── src/
│   ├── sefi/
│   │   ├── __init__.py
│   │   ├── config.py          # Configuration management
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py     # Component 1: Database Adapter
│   │   │   └── schemas.py     # Database schema definitions
│   │   ├── generator/
│   │   │   ├── __init__.py
│   │   │   ├── units.py       # Component 2: Work Unit Generator
│   │   │   ├── types.py       # Work unit type definitions
│   │   │   └── scaling.py     # Scaling behavior logic
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── main.py        # Component 3: FastAPI app
│   │   │   ├── routes.py      # API endpoints
│   │   │   ├── models.py      # Pydantic models
│   │   │   └── auth.py        # Authentication
│   │   ├── validation/
│   │   │   ├── __init__.py
│   │   │   ├── layer.py       # Component 4: Validation Layer
│   │   │   ├── pii.py         # PII Guardian
│   │   │   ├── quorum.py      # Quorum Validator
│   │   │   └── provenance.py  # Provenance Logger
│   │   ├── store/
│   │   │   ├── __init__.py
│   │   │   └── findings.py    # Component 5: Findings Store
│   │   └── dashboard/
│   │       ├── __init__.py
│   │       ├── routes.py      # Component 6: Dashboard routes
│   │       └── templates/     # HTML templates
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── data/
│   ├── sample/                # Sample databases for testing
│   └── findings.db            # Generated findings database
└── docs/
    ├── api.md                 # API documentation
    └── work_units.md          # Work unit type documentation
```

---

## Appendix B: Quick Start for Subagents

If you are a subagent assigned to implement a specific component:

1. **Read this entire roadmap** to understand the system context
2. **Check the "Dependencies" section** of your assigned component
3. **Use the interface specifications** as your contract
4. **Write tests first** using the testing strategy section
5. **Flag any blockers** related to "Decisions Requiring Human Input"

Your component should be:
- Independently testable with mock dependencies
- Type-annotated (Python 3.10+)
- Documented with docstrings
- Compliant with ethical constraints

---

*End of Roadmap*
