# Tester — SEFI@Home Project Context

> Read `~/.claude/skills/tester/SKILL.md` first for the full role definition,
> test documentation standards, fix plan format, and Ralph loop protocol.
> The content below is SEFI@Home-specific only.

---

## Test Constraints

- **No live HTTP** — mock ALL external calls with `unittest.mock` or `pytest-mock`;
  no live requests to justice.gov or any other external URL
- **In-memory SQLite** — use `:memory:` for all database tests; never touch a file DB
- **Test directory** — `tests/`
- **Run command** — `python -m pytest tests/ -x -q`

## Fix Plan Path

Failures go in `todo/fix_plan.md`.
