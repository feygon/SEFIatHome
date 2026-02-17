# Maintainability Rubric

## Trigger
`/maintainability [file or PR]`

## Rubric

Evaluate maintainability using this rubric. Score 0–3 each and propose improvements in priority order that reduce long-term change cost.

| Criterion | Score 0-3 |
|-----------|-----------|
| Small blast radius | |
| Stable interfaces | |
| Separation of concerns | |
| Complexity controlled | |
| Maintainable abstractions | |
| Consistent patterns | |
| Explicit dependency boundaries | |
| Validated configuration | |
| Resilient integrations | |
| Fast reliable tests | |
| Coverage of change-prone behavior | |
| Good observability | |
| Robust error handling/invariants | |
| Maintainable security | |
| Predictable performance | |
| Strong onboarding/runbooks | |

## Output Format

```markdown
# Maintainability Review: [file]

## Scores
| Criterion | Score | Notes |
|-----------|-------|-------|
| ... | X/3 | ... |

## Total: X/48

## Prioritized Improvements
1. [Highest impact fix]
2. [Next priority]
...
```
