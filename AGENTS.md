# SEFI@Home - Agent Documentation

## Project Overview

SEFI@Home (Search the Epstein Files Investigation) is a distributed analysis platform inspired by BOINC/SETI@Home. Instead of distributing compute, we distribute reasoning — volunteers (human or LLM) analyze document slices and return structured findings.

## Architecture (MVP)

```
Zero-Corpus Design:
- Server holds only JSON metadata (~2MB)
- Work units contain DOJ PDF URLs
- Workers fetch PDFs directly from justice.gov
- Server stores findings in SQLite
```

## Key Patterns

### EFTA Numbers
- Universal document identifier across all DOJ releases
- Format: EFTA00000001 to EFTA02731783
- URL pattern: `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{XXXXXXXX}.pdf`
- Gap resolution: Try adjacent datasets if primary 404s

### Work Unit Types (MVP)
1. **verify_finding** (linear scaling)
   - Input: Claim + cited EFTA URLs
   - Output: Verified / Disputed / Insufficient Evidence
   - One claim per unit

2. **decision_chain** (multiplying scaling)
   - Input: 20-50 documents from same time window
   - Output: Communication graph (who → whom → when → topic)
   - Concentration reveals patterns

### Data Sources
- `persons_registry.json` - 1,614 people with categories
- `knowledge_graph_entities.json` - 524 entities (people, shells, orgs)
- `knowledge_graph_relationships.json` - 2,096 typed edges
- `efta_dataset_mapping.json` - EFTA → Dataset mapping

## Gotchas

1. **Don't download the 6GB corpus** - MVP uses DOJ URLs directly
2. **Gap EFTAs aren't missing** - Try adjacent datasets before flagging
3. **FTS5 exists but we don't need it** - Workers fetch PDFs, not text
4. **No auth for MVP** - Add later if scaling

## Code Conventions

- Python 3.10+
- Type hints on all functions
- Pydantic for data models
- FastAPI for HTTP
- SQLite with raw SQL (no ORM)
- pytest for testing

## External Resources

- rhowardstone/Epstein-research-data: Source JSON exports
- rhowardstone/Epstein-research: Analysis reports to verify
- justice.gov/epstein: Document PDFs

## Ethical Constraints

- PII Guardian: Block victim-identifying information in outputs
- Provenance: Every finding traces to EFTA document
- No de-anonymization: Analyze redaction patterns, not content
- Public domain: All findings are CC0
