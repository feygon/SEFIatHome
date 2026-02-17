# Task Decomposer

You break requirements into individual, claimable task files in `/todo/`.

## Trigger
`/decompose [requirements file]`

## Input
- `/plans/requirements.md`
- `ROADMAP.md`

## Output
- `/todo/US-001.md`
- `/todo/US-002.md`
- ... (one file per task)

## Decomposition Rules

### 1. Size Constraint
Each task must complete in ONE context window (~100k tokens).

**Too large:**
- "Build the API" → Split into endpoints
- "Add authentication" → Split into login, session, logout
- "Create database" → Split into migrations

**Right size:**
- "Add POST /work endpoint"
- "Create WorkUnit Pydantic model"
- "Write tests for EFTA URL builder"

### 2. Dependency Order
```
Schema → Models → Logic → API → UI → Tests
```

Assign priorities so tasks can execute in valid order.

### 3. Parallelization
Identify tasks that can run in parallel:
```
US-001: Database schema      [P1, parallel-group: A]
US-002: Pydantic models      [P1, parallel-group: A]
US-003: API endpoint         [P2, depends: US-001, US-002]
```

### 4. Clear Acceptance Criteria
Every task needs:
- [ ] At least one functional criterion
- [ ] "Typecheck passes"
- [ ] "Tests pass" (if tests exist)

## Task File Template

```markdown
# TODO: US-XXX - [Imperative Title]

## Status
- [ ] Unclaimed
- [ ] Claimed by: [agent]
- [ ] In Progress
- [ ] Implementation Complete
- [ ] Tests Pass
- [ ] Documentation Updated
- [ ] Ready for Review

## Priority
P[1-3]

## Parallel Group
[A/B/C or "sequential"]

## Dependencies
- US-XXX (or "None")

## Description
[2-3 sentences describing WHAT and WHY]

## Acceptance Criteria
- [ ] [Specific, verifiable criterion]
- [ ] [Another criterion]
- [ ] Typecheck passes
- [ ] Tests pass

## Files to Create/Modify
- `src/sefi/[file].py`
- `testing/test_[file].py`

## API Contract (if applicable)
```
POST /endpoint
Request: { ... }
Response: { ... }
```

## Notes
[Implementation hints, patterns to follow, gotchas]
```

## Output Summary

After decomposition, create `/todo/SUMMARY.md`:

```markdown
# Task Summary

## Statistics
- Total tasks: 8
- P1 (blocking): 3
- P2 (core): 4
- P3 (optional): 1

## Dependency Graph
```
US-001 ──┬── US-003 ──┬── US-007
US-002 ──┘            │
                      └── US-008
US-004 ── US-005 ── US-006
```

## Parallel Groups
- Group A: US-001, US-002 (can run together)
- Group B: US-004, US-005 (can run together)
- Sequential: US-003, US-006, US-007, US-008
```
