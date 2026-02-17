# Librarian — SEFI@Home Project Context

> Read `~/.claude/skills/librarian/SKILL.md` first for the full role definition,
> accessibility standards, epistemic review rubric, and HITL flag criteria.
> The content below is SEFI@Home-specific only.

---

## First Task on Spawn

1. Read `docs/library/ETHICS.md` — internalize the 7 research ethics constraints
   and the scope distinction (development artifacts vs. research/analysis artifacts)
2. If `ETHICS.md` is missing, flag HITL before proceeding
3. Confirm by restating the scope and constraints

## SEFI Library Paths

| Document | Path |
|----------|------|
| Ethics | `docs/library/ETHICS.md` |
| Patterns | `docs/library/patterns.md` |
| Glossary | `docs/library/glossary.md` |
| Decisions | `docs/library/decisions.md` |
| Assertions | `docs/assertions.md` |

## SEFI Glossary (seed terms)

| Term | Definition |
|------|------------|
| EFTA | Epstein Files Transparency Act document number; 8-digit identifier (e.g. EFTA00039186) |
| Work Unit | Self-contained analysis task assigned to a volunteer worker; types: `verify_finding`, `decision_chain` |
| Finding | An analytical conclusion from EFTA documents — NOT a code bug |
| EFTA Gap Resolution | Try primary dataset URL → N-1 → N+1 before flagging a document as genuinely missing |
| Zero-corpus | Design constraint: server holds only ~2 MB JSON metadata; workers fetch PDFs directly from justice.gov |

## Accessibility

This project's user has autism, ADHD, and dyslexia. The accessibility standards
in `~/.claude/skills/librarian/SKILL.md` are non-negotiable for all documentation.
