# SEFI@Home — Todo Summary

| ID | Title | Status | Depends On |
|----|-------|--------|------------|
| US-001 | Project Scaffolding | done | — |
| US-002 | Data Fetch & Ingest Bootstrap | done | US-001 |
| US-003 | EFTA URL Builder & Gap Resolution | done | US-001, US-002 |
| US-004 | Database Adapter (JSON Methods) | done | US-001, US-002 |
| US-005 | Work Unit Generator: verify_finding | done | US-001, US-003, US-004 |
| US-006 | Work Unit Generator: decision_chain | done | US-001, US-003, US-005 |
| US-007 | Findings Store | done | US-001 |
| US-008 | Basic Validation Layer | done | US-001, US-004, US-007 |
| US-009 | Distribution API | done | US-001, US-005, US-006, US-007, US-008 |
| US-010 | End-to-End Integration | pending | US-001, US-002, US-003, US-004, US-005, US-006, US-007, US-008, US-009 |

## Dependency Graph

```
US-001 (foundation)
  ├── US-002 (ingest)
  │     ├── US-003 (EFTA/URL)
  │     │     └── US-005 (verify_finding generator)
  │     │           └── US-006 (decision_chain generator)
  │     └── US-004 (DB adapter)
  │           ├── US-005 (verify_finding generator)
  │           └── US-008 (validation layer)
  ├── US-007 (findings store)
  │     └── US-008 (validation layer)
  │           └── US-009 (API)
  │                 └── US-010 (integration)
  └── [all stories depend on US-001]
```

## Requirement Coverage

| Requirement | Story |
|-------------|-------|
| NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-008 | US-001 |
| FR-047, DR-001, DR-002, DR-003, DR-004 | US-002 |
| FR-014, FR-015, FR-016, DR-011, DR-012 | US-003 |
| FR-001, FR-002, FR-003, FR-004 | US-004 |
| FR-012, FR-017, FR-018, FR-019, EC-002, EC-006, EC-007 | US-005 |
| FR-013, FR-017, FR-018, FR-019 | US-006 |
| FR-038, FR-039, FR-040, FR-041, DR-007, DR-008, DR-010, DR-011, EC-004 | US-007 |
| FR-031, FR-032, EC-001, EC-002, EC-007 | US-008 |
| FR-023, FR-024, FR-025, FR-026, AC-001 — AC-005 | US-009 |
| FR-047, FR-048, FR-049, FR-050 | US-010 |

## Model Assignment

All stories: `sonnet` (no opus required for MVP scaffolding)

## Notes

- US-001 is the only story with no dependencies. All other stories depend on it at minimum.
- US-010 depends on all other stories and serves as the final integration gate.
- Post-MVP requirements (FR-005 through FR-011, FR-020 through FR-022, FR-027 through FR-030, FR-033 through FR-037, FR-042, FR-043, FR-044 through FR-046, NFR-006, NFR-007, NFR-009 through NFR-011, EC-003, EC-005, DR-005, DR-006, DR-009, AC-006 through AC-008) are intentionally excluded from all stories in this todo list.
