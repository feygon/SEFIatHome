# ETHICS.md — SEFI@Home Research Ethics Constraints

**TLDR:** Seven hardcoded rules govern all research artifacts (Epstein Files analysis). They are not guidelines — they block acceptance. Development artifacts (code, tests, infrastructure) are not subject to these rules.

---

## Table of Contents

1. [Scope Distinction](#scope-distinction)
2. [Key Term Definitions](#key-term-definitions)
3. [The 7 Ethical Constraints](#the-7-ethical-constraints)
4. [Ethics Review Checklist](#ethics-review-checklist)
5. [Implementation Locations](#implementation-locations)

---

## Scope Distinction

**These constraints apply to research artifacts only.** The table below defines the boundary.

| Artifact Type | Examples | Ethical Constraints Apply? |
|---|---|---|
| **Development** | Python code, tests, API docs, infrastructure config, bug reports, code review findings, technical documentation | No |
| **Research** | EFTA document analysis findings, claims about people/events/relationships, entity extractions, timeline entries, work unit results, quoted or summarized EFTA content | **Yes — all 7 constraints** |

**EFTA** = Epstein Files Transparency Act (the source document corpus hosted by the U.S. Department of Justice).

---

## Key Term Definitions

**Findings**
Analytical conclusions derived from Epstein Files Transparency Act (EFTA) document content. This term does NOT refer to code bugs, test failures, or technical discoveries. When the word "findings" appears in an ethics context, it refers exclusively to research conclusions about people, events, relationships, or patterns in the EFTA corpus.

**Research Artifact**
Any output that quotes, summarizes, extracts from, or draws analytical conclusions about EFTA documents. Includes but is not limited to: work unit results, entity lists, timeline entries, named-individual claims, and redaction pattern analyses.

**Development Artifact**
Any output that describes the behavior, structure, or quality of the codebase or infrastructure. These artifacts are not subject to ethical constraints, even if they mention people (e.g., code authors, ticket assignees).

**PII**
Personally Identifiable Information. Any data that could identify a specific individual, including but not limited to: names, addresses, phone numbers, email addresses, financial account numbers, and biometric data.

**HITL**
Human-in-the-Loop. A required pause for human review before an automated process continues.

---

## The 7 Ethical Constraints

These are **hardcoded rules**. They are not guidelines. A research artifact that fails any constraint is **blocked from acceptance** until the constraint is satisfied.

---

### Constraint 1 — PII Guardian Scan

| Field | Value |
|---|---|
| **Scope** | All research artifacts |
| **Trigger** | Any research artifact submitted for acceptance |
| **Required action** | Run PII Guardian scan before acceptance; block if PII detected |
| **Implementation** | `src/sefi/validation/pii.py` |

- Every research output must pass a PII Guardian scan before it enters the accepted corpus.
- A failed scan blocks acceptance; it does not produce a warning that can be overridden.

---

### Constraint 2 — Text-Only Analysis

| Field | Value |
|---|---|
| **Scope** | All work units |
| **Trigger** | Work unit creation or assignment |
| **Required action** | Reject work units that reference images or video |
| **Implementation** | `src/sefi/workers/work_unit.py` |

- No work units may involve image or video content.
- Analysis is restricted to text documents only.
- Work units referencing non-text media are rejected at creation.

---

### Constraint 3 — Victim Name Quarantine

| Field | Value |
|---|---|
| **Scope** | All research artifacts |
| **Trigger** | Victim name detected in output |
| **Required action** | Quarantine the artifact immediately; report to EFTA@usdoj.gov |
| **Implementation** | `src/sefi/validation/victim_names.py` |

- Victim names are never published, stored in the accepted corpus, or passed between agents.
- Detection triggers automatic quarantine of the artifact.
- Quarantine events are reported to EFTA@usdoj.gov as required by law.
- "Victim" means any individual identified or identifiable as a victim in EFTA documents.

---

### Constraint 4 — Public Domain (CC0)

| Field | Value |
|---|---|
| **Scope** | All research results |
| **Trigger** | Research result accepted into corpus |
| **Required action** | License under CC0 (no rights reserved) |
| **Implementation** | `src/sefi/output/metadata.py` |

- All accepted research results are released as **CC0** (Creative Commons Zero — no rights reserved, full public domain dedication).
- No research output may be marked proprietary, restricted, or confidential.

---

### Constraint 5 — Quorum of 3 for Named Individuals

| Field | Value |
|---|---|
| **Scope** | Findings that name specific individuals |
| **Trigger** | A research finding includes the name of a living or deceased named individual |
| **Required action** | Require independent agreement from 3 separate agents (quorum) before acceptance |
| **Implementation** | `src/sefi/quorum/named_individual.py` |

- No finding that names an individual may be accepted on the basis of a single agent's output.
- Three independent agent analyses must agree before the finding is accepted.
- Quorum is checked automatically; findings without quorum are held pending.

---

### Constraint 6 — Unverified FBI Tips Labeled

| Field | Value |
|---|---|
| **Scope** | Research artifacts that cite or summarize FBI tip content |
| **Trigger** | Source material is an FBI tip or unverified third-party report |
| **Required action** | Label the finding as UNVERIFIED; do not present as established fact |
| **Implementation** | `src/sefi/validation/source_labels.py` |

- FBI tips and unverified reports must be explicitly labeled **UNVERIFIED** in any output.
- Unverified material may be included in the corpus but must never be presented as confirmed fact.
- The label must be machine-readable (structured field) and human-readable (visible in output).

---

### Constraint 7 — No De-anonymization

| Field | Value |
|---|---|
| **Scope** | All research artifacts involving redacted content |
| **Trigger** | Analysis of redacted EFTA documents |
| **Required action** | Analyze redaction patterns only; do not attempt to recover redacted content |
| **Implementation** | `src/sefi/validation/redaction_policy.py` |

- Agents may analyze the presence, frequency, and patterns of redactions.
- Agents may NOT attempt to infer, reconstruct, or recover the content behind redactions.
- Any output that appears to recover redacted content is blocked and flagged for HITL review.

---

## Ethics Review Checklist

Use this checklist before accepting any artifact. **The first gate must pass before the remaining checks apply.**

- [ ] **GATE: Is this a research artifact?** If no, stop — no constraints apply. If yes, continue.
- [ ] **Constraint 1:** PII Guardian scan passed with no PII detected?
- [ ] **Constraint 2:** Work unit is text-only (no image or video content)?
- [ ] **Constraint 3:** No victim names detected? (If detected, quarantine and report before proceeding.)
- [ ] **Constraint 4:** Output is marked CC0 / public domain?
- [ ] **Constraint 5:** If the finding names an individual — quorum of 3 agents confirmed?
- [ ] **Constraint 6:** All unverified FBI tips or third-party reports labeled UNVERIFIED?
- [ ] **Constraint 7:** No attempt to recover redacted content — pattern analysis only?

**All boxes must be checked before acceptance.** A research artifact with any unchecked box is blocked.

---

## Implementation Locations

| Constraint | Module |
|---|---|
| 1 — PII Guardian | `src/sefi/validation/pii.py` |
| 2 — Text-Only | `src/sefi/workers/work_unit.py` |
| 3 — Victim Quarantine | `src/sefi/validation/victim_names.py` |
| 4 — CC0 Licensing | `src/sefi/output/metadata.py` |
| 5 — Quorum of 3 | `src/sefi/quorum/named_individual.py` |
| 6 — Source Labels | `src/sefi/validation/source_labels.py` |
| 7 — No De-anonymization | `src/sefi/validation/redaction_policy.py` |

---

_Maintained by the SEFI@Home Librarian. Last updated: 2026-02-16._
