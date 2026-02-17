# Committer — SEFI@Home Project Context

> Read `~/.claude/skills/committer/SKILL.md` first for the full role definition,
> quality gates, commit format, and workflow.
> The content below is SEFI@Home-specific only.

---

## SEFI Quality Gate (addition)

- [ ] `docs/api/` contains at least one `.md` file for modules this task touched
  → STOP: `COMMIT BLOCKED: docs/api/ not written.`

## SEFI Stage Command

```bash
git -C <repo> add src/ tests/ docs/ todo/ pyproject.toml
```

## SEFI Status Field

Change `**Status:**` in the task file from `tested` to `done` after committing.

## Librarian Committee

After pushing, spawn a Librarian Committee agent (see `.claude/skills/orchestrator/SKILL.md`
for the full prompt template). It appends assertions to `docs/assertions.md` and
commits them separately.
