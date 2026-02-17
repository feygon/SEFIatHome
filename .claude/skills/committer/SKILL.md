# Committer — SEFI@Home Project Context

> Read `~/.claude/skills/committer/SKILL.md` first for the full role definition,
> quality gates, commit format, and workflow.
> The content below is SEFI@Home-specific only.

---

## SEFI Quality Gate (addition)

- [ ] `docs/api/` contains at least one `.md` file for modules this task touched
  → STOP: `COMMIT BLOCKED: docs/api/ not written.`

## SEFI Workflow (additions after generic step 4 — Commit)

After the main commit:

5. Update the task file: change `**Status:**` from `tested` to `done`.
6. Update `todo/SUMMARY.md`: mark this task as done in the table.
7. Update `ROADMAP.md`: add a `✅ Implemented (US-NNN)` note for this component.
8. Stage and commit those documentation updates:
   `docs: mark <task-id> complete in roadmap and todo`
9. Push all commits.
10. Spawn or invoke an existing Librarian Committee agent (see `.claude/skills/orchestrator/SKILL.md`
    for the full prompt template) to append assertions to `docs/assertions.md`
    and commit them separately.

## SEFI Stage Command

```bash
git -C <repo> add src/ tests/ docs/ todo/ pyproject.toml
```
