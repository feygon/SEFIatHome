# Data Fetch Commands

Re-run these commands to update JSON exports from rhowardstone when upstream data evolves.

## Source Repository

https://github.com/rhowardstone/Epstein-research-data

## Fetch Commands

```bash
cd d:\repos\SEFIatHome\data

# Unified person registry (1,614 records)
curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/persons_registry.json

# Knowledge graph entities (524 records)
curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/knowledge_graph_entities.json

# Knowledge graph relationships (2,096 records)
curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/knowledge_graph_relationships.json

# EFTA to dataset mapping
curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/efta_dataset_mapping.json
```

## One-liner

```bash
cd d:\repos\SEFIatHome\data && curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/persons_registry.json && curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/knowledge_graph_entities.json && curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/knowledge_graph_relationships.json && curl -O https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main/efta_dataset_mapping.json
```

## Last Fetched

[Update this date after each fetch]

---

_These files are public domain (U.S. government records under EFTA)._
