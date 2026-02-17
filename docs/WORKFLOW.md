# SEFI@Home Development Workflow

## Overview

Orchestrated multi-agent workflow for requirements-driven development with HITL gates and epistemic review.

---

## Agents & Skills

| Agent | Skills | Role |
|-------|--------|------|
| **Orchestrator** | `/orchestrate`, `/pm`, `/decompose`, `/prd`, `/ralph` | Coordinate all agents, HITL gates |
| **Requirements Reviewer** | `/requirements`, `/distributed` | Validate specs and decomposition |
| **Programmer** | `/program`, `/git` | Implement tasks, document APIs |
| **Tester** | `/test`, `/maintainability`, `/readable`, `/reliability` | Test, review, manage fix pipeline |
| **Troubleshoot (Ralph)** | `/troubleshoot` | Debug loops from fix_plan.md |
| **Librarian** | `/library` | Epistemic standards, accessibility |

---

## Workflow Flowchart

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            ORCHESTRATOR                                  │
│                 /orchestrate, /pm, /decompose, /prd, /ralph             │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: REQUIREMENTS                                                    │
│                                                                          │
│   Orchestrator ──► Requirements Reviewer ──► /plans/requirements.md     │
│                    /requirements, /distributed                           │
│                                  │                                       │
│                                  ▼                                       │
│                          [HITL GATE: Approve requirements]               │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECOMPOSE                                                       │
│                                                                          │
│   Orchestrator ──► /decompose ──► /todo/US-001.md, US-002.md, ...       │
│                                           │                              │
│                                           ▼                              │
│                        ┌──────────────────────────────────┐              │
│                        │ Requirements Reviewer            │              │
│                        │ /requirements                    │              │
│                        │                                  │              │
│                        │ Validates:                       │              │
│                        │ - Each task traces to a req      │              │
│                        │ - No requirements missed         │              │
│                        │ - Tasks are right-sized          │              │
│                        │ - Acceptance criteria testable   │              │
│                        └────────────────┬─────────────────┘              │
│                                         │                                │
│                                         ▼                                │
│                          [HITL GATE: Approve task breakdown]             │
└─────────────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: IMPLEMENT (PARALLEL)                                            │
│                                                                          │
│   Orchestrator spawns multiple Programmers (Sonnet or Opus):            │
│                                                                          │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│   │ Programmer (S)   │  │ Programmer (O)   │  │ Programmer (S)   │      │
│   │ /program, /git   │  │ /program, /git   │  │ /program, /git   │      │
│   │ Claims US-001    │  │ Claims US-002    │  │ Claims US-004    │      │
│   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘      │
│            │                     │                     │                 │
│            ▼                     ▼                     ▼                 │
│        /src/*               /src/*                /src/*                 │
│        /docs/api/*          /docs/api/*           /docs/api/*            │
│                                                                          │
│            └──────────────────┬──────────────────────┘                   │
│                               ▼                                          │
│                    [API Contract Conflict?]                              │
│                          │         │                                     │
│                         YES       NO                                     │
│                          │         │                                     │
│                          ▼         │                                     │
│              [HITL GATE: Resolve]  │                                     │
│                          │         │                                     │
│                          └────┬────┘                                     │
└───────────────────────────────┼─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: TEST (per completed programmer)                                 │
│                                                                          │
│   Orchestrator spawns Tester after each Programmer completes:           │
│                                                                          │
│   ┌─────────────────────────────────────────────┐                        │
│   │ Tester                                      │                        │
│   │ /test, /maintainability, /readable,         │                        │
│   │ /reliability                                │                        │
│   └─────────────────────┬───────────────────────┘                        │
│                         │                                                │
│                         ▼                                                │
│                   [Tests Pass?]                                          │
│                    │         │                                           │
│                   YES       NO                                           │
│                    │         │                                           │
│                    │         ▼                                           │
│                    │   ┌─────────────────────────┐                       │
│                    │   │ Update /todo/fix_plan.md│                       │
│                    │   └───────────┬─────────────┘                       │
│                    │               │                                     │
│                    │               ▼                                     │
│                    │   ┌─────────────────────────┐                       │
│                    │   │ Troubleshoot (Ralph)    │◄──┐                   │
│                    │   │ /troubleshoot           │   │                   │
│                    │   └───────────┬─────────────┘   │                   │
│                    │               │                 │                   │
│                    │               ▼                 │                   │
│                    │         [Fixed?]                │                   │
│                    │          │    │                 │                   │
│                    │         YES   NO────────────────┘                   │
│                    │          │    (loop, aggregates debug log)          │
│                    │          │                                          │
│                    └────┬─────┘                                          │
│                         │                                                │
│                         ▼                                                │
│                  /testing/reports/*                                      │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 5: DOCUMENTATION                                                   │
│                                                                          │
│   ┌─────────────────────────────────────────────┐                        │
│   │ Librarian                                   │                        │
│   │ /library                                    │                        │
│   └─────────────────────┬───────────────────────┘                        │
│                         │                                                │
│                         ▼                                                │
│              ┌──────────────────────┐                                    │
│              │ Review:              │                                    │
│              │ - Accessibility      │                                    │
│              │ - Epistemic claims   │                                    │
│              │ - Harvest patterns   │                                    │
│              │   from debug logs    │                                    │
│              └──────────┬───────────┘                                    │
│                         │                                                │
│                         ▼                                                │
│                  [HITL GATE: Epistemic review]                           │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 6: DEPLOY                                                          │
│                                                                          │
│   Programmer (or Orchestrator) ──► /git ──► GitHub Actions              │
│                                                                          │
│                         │                                                │
│                         ▼                                                │
│                  [HITL GATE: Final approval]                             │
│                         │                                                │
│                         ▼                                                │
│                      DONE                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## HITL Gates

| Gate | Phase | Blocking | What's Reviewed |
|------|-------|----------|-----------------|
| Requirements approved | 1 | Yes | /plans/requirements.md |
| Task breakdown approved | 2 | Yes | /todo/US-*.md validated by Req Reviewer |
| API conflict resolution | 3 | Yes | /docs/api-contracts.md |
| Epistemic review | 5 | Yes | /docs/assertions.md |
| Final deploy approval | 6 | Yes | All documentation complete |

---

## Documentation Flow

| Phase | Agent | Creates | Consumed By | At Phase |
|-------|-------|---------|-------------|----------|
| 1 | Req Reviewer | `/plans/requirements.md` | Orchestrator, Decomposer | 2 |
| 2 | Orchestrator | `/todo/US-*.md` | Req Reviewer, Programmers | 2, 3 |
| 2 | Req Reviewer | Validation notes in todos | Programmers | 3 |
| 3 | Programmer | `/src/*` code | Tester | 4 |
| 3 | Programmer | `/docs/api/*.md` | Other Programmers, Tester | 3, 4 |
| 3 | Programmer | Docstrings, type hints | Tester, Librarian | 4, 5 |
| 4 | Tester | `/testing/test_*.py` | Troubleshoot | 4 |
| 4 | Tester | `/testing/reports/*.md` | Librarian, HITL | 5, 6 |
| 4 | Tester | `/todo/fix_plan.md` | Troubleshoot | 4 |
| 4 | Troubleshoot | `/testing/debug/FIX-*.md` | Next Ralph iteration, Librarian | 4, 5 |
| 5 | Librarian | `/docs/library/glossary.md` | All agents | All |
| 5 | Librarian | `/docs/library/patterns.md` | Programmers | 3 |
| 5 | Librarian | `/docs/library/decisions.md` | All agents, HITL | All |
| 5 | Librarian | `/docs/assertions.md` | HITL | 6 |

---

## Documentation Requirements

### MUST (Blocking)

| Document | Why Blocking |
|----------|--------------|
| `/plans/requirements.md` | Can't decompose without it |
| `/todo/US-*.md` | Programmers need tasks to claim |
| `/todo/fix_plan.md` | Troubleshoot needs targets |
| `/docs/api/*.md` | Parallel programmers need contracts |
| `/testing/test_*.py` | Can't test without tests |
| `/testing/debug/FIX-*.md` | Ralph loops need iteration memory |
| Docstrings (public API) | Acceptance criterion |
| Type hints | Typecheck must pass |
| `/docs/assertions.md` | HITL needs epistemic review |

### SHOULD (Quality Improvement)

| Document | Benefit |
|----------|---------|
| `/testing/reports/*.md` | Helpful for HITL context |
| `/docs/library/glossary.md` | Improves consistency |
| `/docs/library/patterns.md` | Helps future agents |
| `/docs/library/decisions.md` | Records architectural rationale |

---

## Ralph Loop Aggregation

Debug logs are **infrastructure**, not optional documentation:

```
Ralph Iteration 1 ──► writes debug log
        │
        ▼
Ralph Iteration 2 ──► reads log ──► avoids hypothesis 1 ──► writes new finding
        │
        ▼
Ralph Iteration 3 ──► reads log ──► avoids 1 & 2 ──► finds fix
        │
        ▼
Librarian ──► reads full log ──► extracts pattern for /docs/library/
```

Each iteration **appends** to `FIX-*.md`. Next iteration **reads** full history. Librarian **harvests** patterns after resolution.

---

## Folder Structure

```
SEFIatHome/
├── /src                    # Source code (Programmer)
├── /docs                   # Documentation
│   ├── /api               # API contracts (Programmer)
│   └── /library           # Curated standards (Librarian)
├── /testing               # Tests and reports
│   ├── test_*.py          # Tests (Tester)
│   ├── /reports           # Test reports (Tester)
│   └── /debug             # FIX-*.md logs (Troubleshoot)
├── /plans                 # Requirements (Req Reviewer)
│   └── requirements.md
├── /todo                  # Task files (Orchestrator)
│   ├── US-*.md
│   ├── fix_plan.md
│   └── SUMMARY.md
└── ROADMAP.md
```
