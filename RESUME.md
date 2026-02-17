# SEFI@Home — Session Resume

## Project Summary

SEFI@Home (Search the Epstein Files Investigation) is a distributed analysis platform inspired by BOINC. Instead of compute cycles, volunteers donate reasoning tokens to analyze the DOJ Epstein Files. The MVP is zero-corpus: work units contain DOJ PDF URLs, workers fetch directly from justice.gov, server stores findings in SQLite.

**GitHub:** https://github.com/feygon/SEFIatHome

---

## Current State (2026-02-17)

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: Requirements | ✅ Done | `/plans/requirements.md` approved |
| Phase 2: Decompose | ✅ Done | 10 US stories in `/todo/` |
| Phase 3: Implement | ✅ Done | All 10 stories committed and pushed |
| Phase 4: Test | ✅ Done | 582 tests pass, all mocked |
| Phase 5: Documentation | ⚠️ Partial | **`/docs/api/` was NOT written by programmers — must be backfilled** |
| Phase 6: Deploy | ⏳ Blocked | No API funding yet; live workers deferred |

---

## IMMEDIATE NEXT ACTION

**Backfill missing `/docs/api/` documentation**, then proceed to Phase 5 (Librarian review).

```
Spawn a general-purpose (Sonnet) agent with this directive:

  Read every module under src/sefi/ and write docs/api/<module>.md
  for each one. Modules: config, db/adapter, db/ingest, db/efta,
  generator/units, store/findings, validation/layer, api/models,
  api/routes, api/main. Then git add docs/api/ && git commit && git push.
```

After docs are written, the next action is:
```
/orchestrate document
Spawn Librarian to create /docs/assertions.md and run epistemic review.
HITL gate before Phase 6.
```

---

## Key Decisions Made

| Decision | Resolution |
|----------|-----------|
| rhowardstone data access (OQ-001) | Public domain on GitHub; no contact needed |
| Hosting (OQ-002) | Local only; single-developer prototype |
| API funding (OQ-003) | Deferred; full test suite uses mocks; live workers need ~$20-25 |
| GET /work empty state | HTTP 200 `{"available": false}` |
| POST /result idempotency | Returns existing `finding_id` silently |
| Consistency Checker | Cross-checks rhowardstone pre-extracted data only |
| PII patterns (OQ-004) | Deferred to Post-MVP; MVP covers SSN/phone/postal only |

---

## What Was Built

### Source modules (`src/sefi/`)

| Module | Purpose |
|--------|---------|
| `config.py` | Settings and paths |
| `db/adapter.py` | DatabaseAdapter — loads JSON exports, serves entities/persons/relationships |
| `db/ingest.py` | IngestManager + `ensure_data_files()` (auto-fetch from GitHub on startup) |
| `db/efta.py` | EFTA URL builder + gap resolution (primary → N-1 → N+1) |
| `generator/units.py` | WorkUnit dataclass + `verify_finding` and `decision_chain` generators |
| `store/findings.py` | FindingsStore — persist, query, export JSON/CSV, coverage stats |
| `validation/layer.py` | ValidationLayer — provenance check, dedup, PII guardian |
| `api/main.py` + `routes.py` + `models.py` | FastAPI — GET /work, POST /result, GET /status, GET /health |

### Tests

- 582 tests, all pass
- All HTTP mocked (no live justice.gov calls)
- In-memory SQLite for database tests
- Integration test: full lifecycle claim → submit → verify stored

### Infrastructure

- `orchestrator.sh` — 3-agent pipeline (Programmer → Tester → Committer) with dep-checking and token-limit retry
- `data/sample_claims.json` — hand-crafted seed claims for `verify_finding`
- `data/FETCH.md` — manual fetch reference (server auto-fetches on startup)

---

## Known Issues / Tech Debt

- **`/docs/api/` missing** — programmers skipped this; must be backfilled before Phase 5 HITL gate
- **`/docs/assertions.md` missing** — Librarian hasn't run yet
- **`/todo/fix_plan.md` is empty** — no Ralph loops were needed (all tests passed first time)
- **Orchestrator skill bug (FIXED)** — programmer prompt now includes docs/api directive; committer now gates on docs presence
- **Testing strategy** — flagged as weakest spec section; no formal test strategy doc written

---

## How to Run

```bash
# Install
pip install -e ".[dev]"

# Run server (auto-fetches data on first start)
uvicorn src.sefi.api.main:app --reload

# Run tests
python -m pytest tests/ -q

# Run orchestrator (next pending story)
bash orchestrator.sh

# Run orchestrator (all pending stories)
bash orchestrator.sh --loop
```

---

## Open Questions (Post-MVP)

| ID | Question |
|----|---------|
| OQ-004 | PII pattern list — gather specific victim name patterns |
| OQ-005 | Quorum config — 2-of-3 default or per-type? |
| OQ-006 | Worker registration — open or invite-only? |
| OQ-007 | Finding publication gate — auto-sync or human review? |
| OQ-008 | Scale trigger — when to evaluate PostgreSQL? |

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `ROADMAP.md` | Full technical spec |
| `plans/requirements.md` | Approved MVP requirements (all OQs resolved) |
| `docs/WORKFLOW.md` | 6-phase agent workflow with HITL gates |
| `docs/library/ETHICS.md` | 7 hardcoded research ethics constraints |
| `todo/SUMMARY.md` | All 10 stories with status |
| `.claude/skills/*/SKILL.md` | Agent capabilities |
| `orchestrator.sh` | Autonomous implementation pipeline |

---

## Critical Logic: EFTA Gap Resolution

Before flagging an EFTA number as missing:
1. Try primary dataset URL
2. Try dataset N-1
3. Try dataset N+1
4. Only then flag as genuinely missing

Implemented in `src/sefi/db/efta.py`.

---

## Accessibility (SYSTEM DIRECTIVE)

User has autism, ADHD, dyslexia. Apply always:
- TLDR at start of long responses
- Bullet points over prose
- Bold for emphasis (not italics)
- No walls of text
- Tables for structured data
- Define acronyms on first use
- Colorblind-safe palettes (blue/amber/magenta)
