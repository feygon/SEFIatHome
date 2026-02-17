# Orchestrator — SEFI@Home Project Context

> Read `~/.claude/skills/orchestrator/SKILL.md` first for the full role definition,
> workflow phases, HITL gates, skill file references, and agent communication protocol.
> The content below is SEFI@Home-specific only.

---

## SEFI Paths

| Artifact | Path |
|----------|------|
| Requirements | `plans/requirements.md` |
| Roadmap | `ROADMAP.md` |
| Task files | `todo/US-XXX.md` |
| Task summary | `todo/SUMMARY.md` |
| Fix plan | `todo/fix_plan.md` |
| API docs | `docs/api/<module>.md` |
| API contracts | `docs/api-contracts.md` |
| Assertions | `docs/assertions.md` |
| Ethics | `docs/library/ETHICS.md` |

## Orchestration Script

Use `orchestrator.sh` to run the 3-agent pipeline (Programmer → Tester → Committer):

```bash
bash orchestrator.sh            # next pending task
bash orchestrator.sh US-NNN     # specific task by ID
bash orchestrator.sh --loop     # all pending tasks in sequence
bash orchestrator.sh --dry-run  # find next task without running
```

## Phase 6: Deploy

```
/orchestrate deploy

Blocked until:
- Epistemic review (Phase 5) HITL gate passes
- API funding secured (~$20–25 for live worker tokens)

Steps when unblocked:
1. Configure live API keys
2. Deploy: uvicorn src.sefi.api.main:app --reload
3. Register initial workers
4. Monitor findings pipeline
```
