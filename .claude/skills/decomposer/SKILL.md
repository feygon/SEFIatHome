# Task Decomposer — SEFI@Home Project Context

> Read `~/.claude/skills/decomposer/SKILL.md` first for the full decomposition rules,
> task file template, right-sizing guidance, and output summary format.
> The content below is SEFI@Home-specific only.

---

## Input Documents

| Document | Path |
|----------|------|
| Requirements | `plans/requirements.md` |
| Architecture | `ROADMAP.md` |

## Output Paths

| Artifact | Path |
|----------|------|
| Task files | `todo/US-XXX.md` |
| Task summary | `todo/SUMMARY.md` |
| Source files | `src/sefi/<subpackage>/<module>.py` |
| Test files | `tests/test_<module>.py` |

## orchestrator.sh-Compatible Status Fields

The `orchestrator.sh` pipeline parses these exact field formats. Use them verbatim:

```markdown
**Status:** pending
**Depends On:** US-001, US-002
**Model:** sonnet
```

Valid `**Status:**` values: `pending`, `in_progress`, `in_review`, `tested`, `done`,
`failed_programmer`, `failed_tester`, `failed_committer`.

Valid `**Model:**` values: `sonnet`, `opus`.
