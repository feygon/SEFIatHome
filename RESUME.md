# SEFI@Home — Session Resume

## Project Summary

SEFI@Home (Search the Epstein Files Investigation) is a distributed analysis platform inspired by BOINC. Instead of compute cycles, volunteers donate reasoning tokens to analyze the DOJ Epstein Files. The MVP is zero-corpus: work units contain DOJ PDF URLs, workers fetch directly from justice.gov, server stores findings in SQLite. Cost: ~$0 using Claude Max subscription manually.

## Current State

**Ready to start orchestrator.** All infrastructure complete:
- 17 skills in `.claude/skills/`
- 6 agent types defined (Orchestrator, Req Reviewer, Programmer, Tester, Troubleshoot, Librarian)
- Workflow documented with HITL gates
- Folder structure created

## Key Documents

| Document | Purpose |
|----------|---------|
| `ROADMAP.md` | Technical spec, MVP phases, costs |
| `docs/WORKFLOW.md` | Agent workflow, skills mapping, documentation flow |
| `prd.json` | 8 MVP user stories (if using Ralph loops) |
| `.claude/skills/*/SKILL.md` | Agent capabilities |

## Next Action

```
/orchestrate requirements
```

This spawns Requirements Reviewer to create `/plans/requirements.md` from `ROADMAP.md`.

## Critical Logic: EFTA Gap Resolution

EFTA numbers in gap ranges exist in adjacent datasets. Before flagging missing:
1. Try primary dataset URL
2. Try dataset N-1
3. Try dataset N+1
4. Only then flag as genuinely missing

## Accessibility (SYSTEM DIRECTIVE)

User has autism, ADHD, dyslexia. Apply always:
- TLDR at start of long responses
- Bullet points over prose
- Bold for emphasis (not italics)
- No walls of text
- Tables for structured data
- Define acronyms on first use
- Colorblind-safe palettes (blue/amber/magenta)
