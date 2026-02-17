# SEFI@Home - Ralph Agent Instructions

You are an autonomous agent working on the SEFI@Home project. Each iteration, you work on ONE user story from `prd.json`.

## Your Mission

Build a zero-corpus MVP for distributed analysis of the DOJ Epstein Files.

## Critical Files

- `prd.json` - User stories with completion status. Work on the highest-priority incomplete story.
- `progress.txt` - Append your learnings and status after each iteration.
- `ROADMAP.md` - Full technical specification. Read this first.
- `data/` - JSON exports from rhowardstone (download if missing).
- `src/` - Python source code.
- `findings.db` - SQLite database for results (created by the app).

## Iteration Protocol

1. **Read** `prd.json` to find the highest-priority story where `passes: false`
2. **Read** `ROADMAP.md` if you need architectural context
3. **Implement** the story, following acceptance criteria exactly
4. **Test** your implementation (run type checks, unit tests if applicable)
5. **Update** `prd.json` to set `passes: true` if ALL acceptance criteria met
6. **Append** to `progress.txt` what you did and any learnings
7. **Commit** your changes with a descriptive message

## Completion Signal

When ALL stories have `passes: true`, output:

```
<promise>COMPLETE</promise>
```

This signals Ralph to stop iterating.

## Constraints

- Work on ONE story per iteration
- Don't skip stories - complete in priority order
- If blocked, document the blocker in `progress.txt` and continue
- Keep changes focused and testable
- Use Python 3.10+ with type hints
- FastAPI for the server
- SQLite for storage (no ORM for MVP)

## Project Structure

```
SEFIatHome/
├── prd.json              # User stories (read/update each iteration)
├── progress.txt          # Learnings log (append each iteration)
├── ROADMAP.md            # Technical spec
├── CLAUDE.md             # These instructions
├── ralph.sh              # The loop runner
├── data/                 # JSON exports
│   ├── persons_registry.json
│   ├── knowledge_graph_entities.json
│   ├── knowledge_graph_relationships.json
│   └── efta_dataset_mapping.json
├── src/
│   └── sefi/
│       ├── __init__.py
│       ├── models.py     # Pydantic models
│       ├── store.py      # SQLite operations
│       ├── generator.py  # Work unit generation
│       └── api.py        # FastAPI app
└── tests/
```

## Remember

- You are ONE iteration in a loop. Keep context small.
- Git history and `progress.txt` are your memory between iterations.
- If all stories pass, output `<promise>COMPLETE</promise>` and stop.
