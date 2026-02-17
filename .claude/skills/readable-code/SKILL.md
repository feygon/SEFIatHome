# Readable Code Rubric

## Trigger
`/readable [file or PR]`

## Rubric

Evaluate code readability using this rubric. Score 0–3 each and list concrete improvements in priority order, referencing specific code lines/constructs.

| Criterion | Score 0-3 |
|-----------|-----------|
| Purpose obvious | |
| Domain-meaningful names | |
| Single responsibility | |
| Local reasoning | |
| Predictable control flow | |
| Manageable function size/parameters | |
| Problem-aligned abstractions | |
| Clear data flow | |
| Good duplication/indirection balance | |
| Consistent conventions | |
| Avoids cleverness | |
| Explicit constraints/errors | |
| "Why" comments | |
| Behavior-describing tests | |
| Discoverable public API | |
| Change-safe design | |

## Output Format

```markdown
# Readability Review: [file]

## Scores
| Criterion | Score | Line/Construct |
|-----------|-------|----------------|
| ... | X/3 | Line 45: `proc_d()` |

## Total: X/48

## Prioritized Improvements
1. Line X: [specific fix]
2. Line Y: [specific fix]
...
```
