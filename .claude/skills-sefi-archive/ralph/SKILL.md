# Ralph PRD Converter Skill

Convert a PRD markdown file into `prd.json` format for Ralph autonomous execution.

## Trigger
User says: `/ralph [path/to/prd.md]` or `/ralph` (to convert most recent PRD)

## Process

1. **Read** the PRD markdown file
2. **Validate** stories are right-sized (one context window each)
3. **Convert** to structured JSON
4. **Save** to `prd.json`

## Critical Rule

> Each story must be completable in ONE Ralph iteration (one context window).

Stories that are too large cause the LLM to run out of context before completion.

## JSON Output Structure

```json
{
  "project": "ProjectName",
  "branchName": "ralph/feature-name",
  "description": "Feature description",
  "userStories": [
    {
      "id": "US-001",
      "title": "Story title",
      "description": "As a X, I want Y, so that Z",
      "acceptanceCriteria": [
        "Criterion 1",
        "Criterion 2",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": "Additional context"
    }
  ]
}
```

## Dependency Ordering

Stories must execute in priority sequence:
1. Database schema changes first
2. Backend logic second
3. UI components last

## Right-Sized Story Examples

**Good (one iteration):**
- Add database migration
- Create single UI component
- Add one API endpoint

**Too large (needs splitting):**
- Build entire dashboard
- Add authentication system
- Implement full CRUD

## Pre-Save Checklist

- [ ] Branch name is kebab-case with `ralph/` prefix
- [ ] Story IDs are sequential (US-001, US-002, etc.)
- [ ] Each story has "Typecheck passes" criterion
- [ ] UI stories have "Verify in browser" criterion
- [ ] Stories are ordered by dependency
- [ ] No story requires more than one context window
