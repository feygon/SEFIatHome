# Distributed Systems Design Rubric

## Trigger
`/distributed [design doc]`

## Rubric

Evaluate a distributed system design using this rubric. Score 0–3 each and propose prioritized improvements.

| Criterion | Score 0-3 |
|-----------|-----------|
| Explicit requirements and failure/security models | |
| Domain-aligned service boundaries and contracts | |
| Justified consistency model | |
| Clear cross-service transaction approach (saga/outbox/etc.) | |
| Idempotency/ordering/dedup | |
| Storage and sharding strategy | |
| Correct caching | |
| Load management/backpressure | |
| Cost-aware performance | |
| Resilience patterns | |
| Strong observability/ops with SLOs and runbooks | |
| Safe deploy and schema evolution | |
| Distributed testing including fault injection | |

## Output Format

```markdown
# Distributed Systems Review: [component]

## Scores
| Criterion | Score | Notes |
|-----------|-------|-------|
| ... | X/3 | ... |

## Total: X/39

## Prioritized Improvements
1. [Highest impact fix]
2. [Next priority]
...
```
