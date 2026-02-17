# Requirements Reviewer — SEFI@Home Project Context

> Read `~/.claude/skills/requirements-reviewer/SKILL.md` first for the full rubric,
> review process, output format, and blocking criteria.
> The content below is SEFI@Home-specific only.

---

## Input

Primary specification: `ROADMAP.md`
Also read: `docs/library/ETHICS.md` — check that requirements comply with the
7 research ethics constraints and respect the scope distinction (development
artifacts vs. research/analysis artifacts).

## Output

Write the review to: `plans/requirements.md`

## SEFI-Specific Checks (additions to standard rubric)

- **Zero-corpus constraint** — no requirement may depend on a locally stored
  corpus; workers must fetch documents directly from justice.gov
- **Ethics compliance** — every requirement touching research output must be
  compatible with the constraints in `docs/library/ETHICS.md`
- **Open questions** — unresolved decisions must be listed as `OQ-NNN` items
  in a `## Open Questions` section; none may be silently deferred

## Open Question Format

```markdown
## Open Questions

| ID | Question | Blocking? |
|----|----------|-----------|
| OQ-001 | [Question] | Yes / No |
```

A review is not APPROVED until all blocking OQs are resolved or explicitly
deferred with documented rationale.
