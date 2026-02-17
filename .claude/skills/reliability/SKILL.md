# Reliability Rubric

## Trigger
`/reliability [file or system]`

## Rubric

Evaluate reliability using this rubric. Score 0–3 each and propose prioritized fixes that reduce outage and data-corruption risk.

| Criterion | Score 0-3 |
|-----------|-----------|
| Safe failure/degradation | |
| Idempotency | |
| Correct timeouts/retries/backoff | |
| Explicit error handling | |
| State consistency/atomicity | |
| Concurrency correctness | |
| Dependency isolation | |
| Resource limits/load shedding | |
| Boundary validation | |
| Actionable logs | |
| SLO metrics | |
| Traces/diagnosability | |
| Integration tests for failure modes | |
| Invariant/fuzz tests | |
| Failure injection readiness | |
| Safe deploy/rollback/migrations | |

## Output Format

```markdown
# Reliability Review: [component]

## Scores
| Criterion | Score | Risk |
|-----------|-------|------|
| ... | X/3 | HIGH/MED/LOW |

## Total: X/48

## Prioritized Fixes (by outage/corruption risk)
1. [Highest risk fix]
2. [Next priority]
...
```
