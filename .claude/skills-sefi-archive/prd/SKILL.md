# PRD Generator Skill

Generate a structured Product Requirements Document for a new feature.

## Trigger
User says: `/prd [feature description]`

## Process

1. **Collect** feature description from user
2. **Ask** 3-5 clarifying questions with lettered options (A, B, C, D format)
3. **Generate** PRD based on responses
4. **Save** to `tasks/prd-[feature-name].md`

## PRD Structure

```markdown
# PRD: [Feature Name]

## Introduction/Overview
[What this feature does and why]

## Goals
[Measurable objectives]

## User Stories
[Small, implementable in one session each]

## Functional Requirements
[Numbered, explicit requirements]

## Non-Goals
[What this feature explicitly does NOT do]

## Design & Technical Considerations
[Architecture notes, constraints]

## Success Metrics
[How we measure success]

## Open Questions
[Unresolved decisions]
```

## Rules

- User stories must be small enough to implement in ONE focused session
- UI stories must include browser verification acceptance criterion
- Acceptance criteria must be verifiable, not vague
- Write for junior developers—explicit, unambiguous language
- Every story needs "Typecheck passes" criterion

## Example User Story

```markdown
### US-001: Add priority column to tasks table

**As a** developer
**I want** a priority column in the database
**So that** tasks can be ordered by importance

**Acceptance Criteria:**
- [ ] Migration adds `priority` INTEGER column with default 0
- [ ] Typecheck passes
- [ ] Migration runs without errors
```
