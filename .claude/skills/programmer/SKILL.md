# Programmer — SEFI@Home Project Context

> Read `~/.claude/skills/programmer/SKILL.md` first for the full role definition,
> code standards, documentation format, and completion checklist.
> The content below is SEFI@Home-specific only.

---

## Tech Stack

- **Python 3.10+** — type annotations on every function and method
- **Pydantic v2** — `BaseModel` for all data structures crossing module boundaries
- **Raw SQL** — parameterized queries with `?` placeholders; no ORM
- **Injectable HTTP** — any network access must go through an injectable callable
  so tests can swap in a mock (e.g. `check_url_exists: Callable[[str], bool]`)

## Source Layout

- All source modules: `src/sefi/<subpackage>/<module>.py`
- API docs: `docs/api/<module_name>.md` (create `docs/api/` if missing)

## Constraints

- Do NOT write tests — that is the Tester's job
- Do NOT commit — that is the Committer's job
- Do NOT download corpus databases — zero-corpus design; server fetches on startup
