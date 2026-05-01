# Design Doc: Data Foundation & Knowledge Base Readiness for AI Consumption

**Status:** Implemented (foundational layer for Docs 03–05)
**Domain:** Data Engineering / AI Enablement
**Stack:** Amazon S3, AWS Glue, AWS Lake Formation, Amazon Bedrock Knowledge Bases, custom metadata services

---

## 1. Context

Before any agentic AI or RAG system could be built on top of commercial lending data, an honest assessment was required: *what data exists, where does it live, what shape is it in, and is it usable by an LLM?*

The bank's commercial lending estate spanned a CRM (customer and relationship data), several document repositories (signed loan agreements, covenants, financial statements, regulatory filings), and a set of compliance databases (sanction screening, KYC, internal policy registries). These systems had been built independently over many years. Each had its own access pattern, identity model, retention policy, and — critically — its own conception of what "the customer" was.

A naive RAG build on top of this estate would have produced a confidently-wrong agent: retrieving outdated policies, hallucinating across stale and current versions of the same document, and answering with data the requesting agent had no entitlement to see.

This document covers the data readiness program that preceded — and made possible — the RAG and agentic AI work in subsequent docs.

## 2. Goals

- Produce a defensible inventory of customer and policy data across commercial lending systems.
- Establish a curated, governed ingestion path from source systems into S3 in formats consumable by Bedrock Knowledge Bases and downstream agent tools.
- Apply consistent metadata so that retrieval can be filtered by entitlement, recency, jurisdiction, and document type.
- Make the cost of adding a new source system to the AI estate predictable and small.

## 3. Non-Goals

- This is not an MDM program. We did not attempt to resolve a single golden customer record across all source systems. We resolved enough identity to answer the questions the agents needed to answer and explicitly deferred enterprise MDM.
- No reverse ETL. Data flowed source → S3 → AI; we did not write back into source systems from this layer.
- No real-time streaming for the document corpus. Documents change on human time scales (days to quarters); micro-batch ingestion was sufficient.

## 4. Constraints

- Source systems were owned by different teams with different change-management cadences. We could not push schema changes upstream.
- Customer PII and regulated documents were involved. Lake Formation tag-based access control was mandated by the existing data governance program.
- Retention policies for policy documents were jurisdiction-dependent (federal, state, internal). Whatever ingestion ran had to preserve, not erase, the original retention metadata.
- Storage cost mattered at the 100K+ document corpus scale, especially when factoring in vector index storage downstream.

## 5. Architecture

```
Source systems
├── CRM (commercial relationships)        ──┐
├── Document repos (DMS, SharePoint)      ──┤
├── Compliance DBs (KYC, sanctions, AML)  ──┤
└── Policy registry (internal)            ──┘
                                            │
                                            ▼
                          ┌───────────────────────────────┐
                          │  Glue ingestion + metadata    │
                          │  - schema capture             │
                          │  - PII classification         │
                          │  - retention tag preservation │
                          │  - chunking strategy per type │
                          └───────────────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────────┐
                    │  S3 curated zone                     │
                    │  - raw/  (immutable, original form)  │
                    │  - normalized/ (parquet for tabular, │
                    │    cleaned text for documents)       │
                    │  - kb-ready/ (chunked, embedded-     │
                    │    metadata, ingestion manifests)    │
                    └──────────────────────────────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
              Bedrock Knowledge Bases               Agent tool data sources
              (RAG corpus — see Doc 03)             (structured queries — see Doc 05)
```

### Three-zone S3 layout, deliberately

- **`raw/`** — exact bytes from the source system, never edited, never deleted on the AI side. This is the audit anchor. If a regulator asks "what did the agent see," we trace through normalized → raw and prove provenance.
- **`normalized/`** — cleaned, deduplicated, encoded consistently (UTF-8, normalized whitespace, OCR'd if needed). Tabular data lands as Parquet; documents land as text + a sidecar JSON of structural metadata (page breaks, headings, tables extracted separately).
- **`kb-ready/`** — chunked, with chunk-level metadata, in the exact shape Bedrock Knowledge Bases ingests. This zone is regenerable from `normalized/` and is treated as a derived artifact.

Keeping these three zones separate cost storage but bought us the ability to re-chunk, re-embed, or change KB engines later without re-ingesting from source.

## 6. Key Design Decisions

### 6.1 Metadata is part of the chunk, not bolted on

Every chunk carries: `document_id`, `document_type`, `effective_date`, `superseded_by` (nullable), `jurisdiction`, `business_line`, `entitlement_tags`, `source_system`, `last_validated_at`. These travel with the chunk into the vector store and are filterable at retrieval time.

The reason: the dominant failure mode of an enterprise RAG system is not bad embeddings, it is *retrieving a correct answer from a document that no longer applies*. A 2019 policy and the 2024 superseding policy will both have high semantic similarity to the query. Retrieval must be able to filter, not just rank.

### 6.2 Chunking strategy is per document type, not global

Loan agreements, regulatory filings, internal policies, and CRM notes have wildly different structural shapes. A single chunking config (e.g., "1024 tokens with 200 overlap") would have served none of them well.

| Doc type | Chunking approach | Rationale |
|---|---|---|
| Loan agreements | Section-aware (clause boundaries) | Clauses are the atomic unit a question targets. Splitting mid-clause produces useless retrievals. |
| Regulatory filings | Heading-aware with table preservation | Tables answer a meaningful share of regulatory questions; flattening them to prose lost information. |
| Policies | Paragraph-level with policy ID anchoring | Policies are queried by reference ("policy 4.2.1") as often as by content; chunk IDs must preserve that. |
| CRM notes | Conversation-turn aware | Notes are inherently chronological dialogue between RM and customer; respecting turn boundaries preserved coherence. |

### 6.3 Identity resolution: pragmatic, not perfect

We did not build a master patient/customer entity. Instead, we built a **customer crosswalk** keyed off the loan account number (the one identifier that was reliably present everywhere) plus a few high-confidence joins (tax ID, primary email). When the crosswalk could not confidently resolve, the chunk was tagged `entity_resolution_confidence: low` and downstream agents were configured to either escalate or refuse rather than guess.

Building enterprise MDM was a multi-year program. Building a fit-for-purpose crosswalk was six weeks. The agents needed the latter, not the former.

### 6.4 PII classification at ingest, not at query

Glue jobs ran a PII classifier on every chunk and wrote `pii_classes` into chunk metadata. This let us enforce entitlements at *retrieval* time rather than at *generation* time. Filtering at retrieval is cheaper, safer, and easier to audit than redacting LLM output.

### 6.5 Ingestion is incremental and reversible

Source change events (or scheduled diffs where events were not available) drove incremental updates. Each ingestion batch produced a manifest naming the chunks added, modified, or marked superseded. Rollback was a manifest replay in reverse. We never accepted "rebuild the whole corpus" as a recovery posture — at 100K+ documents the rebuild window was longer than the acceptable RTO.

## 7. Alternatives Considered

| Option | Why rejected |
|---|---|
| Point Bedrock Knowledge Bases at SharePoint / DMS directly via connector | Connectors did not preserve our entitlement tags or retention metadata; we would have lost the governance story. Also no control over chunking strategy per document type. |
| Vector-first design (load everything, filter later) | At our corpus size, vector storage and retrieval cost over the wrong-but-similar long tail would have been substantial, and retrieval quality would have suffered from the noise. Filtering at ingest beat filtering at query. |
| Single golden chunking config tuned to "average" document | Tested and abandoned. Recall on loan agreement clauses dropped sharply when chunks crossed clause boundaries. The per-type cost was justified. |
| Use a third-party data prep tool | Evaluated several. None preserved AWS-native lineage to Lake Formation tags, which the data governance team required. The build-vs-buy crossed in our favor given the existing Glue investment. |

## 8. Risks & Mitigations

- **Risk:** Stale documents retrieved as authoritative.
  **Mitigation:** `effective_date` and `superseded_by` chunk metadata; retrieval filters force currency by default; agents can opt into historical retrieval explicitly when answering historical questions.
- **Risk:** PII leakage through retrieval.
  **Mitigation:** Entitlement tags travel with chunks; retrieval enforces tag intersection with caller identity; PII chunks excluded by default unless the calling agent has the corresponding entitlement.
- **Risk:** Source system schema drift breaks ingestion silently.
  **Mitigation:** Glue jobs assert expected schema and fail loudly on drift, rather than coercing into the old shape. Failures route to a data engineering on-call queue.
- **Risk:** Re-chunking corpus invalidates downstream evals.
  **Mitigation:** Eval set is anchored to source documents (and ranges within them), not to chunk IDs, so re-chunking does not silently change what "right" means.

## 9. Outcomes

- 100K+ policy and regulatory documents ingested into the curated zone with consistent metadata.
- Single, repeatable ingestion path adopted as the bank's default for new AI-consuming data sources.
- Enabled the downstream RAG retrieval-quality numbers reported in Doc 03 — those numbers were not won at the embedding layer; they were won here.

## 10. What I'd Do Differently

- Build the chunk-level eval harness *before* the first big ingest, not after. We learned which chunking choices were wrong by losing a week to bad retrieval results that we could have caught with a 200-question eval set up front.
- Treat the metadata schema as a versioned contract from day one. We added fields organically and paid migration tax later.
- Invest earlier in document-type classification — knowing what type a document is is a precondition for chunking it correctly, and we leaned on filename heuristics longer than we should have.

## 11. Future Work

- Continuous PII reclassification as the classifier improves — chunks should not be permanently labeled by the classifier version that ingested them.
- Cross-system entity resolution upgrade (this is the natural on-ramp into a real MDM program if the bank funds one).
- Time-travel retrieval — answer "what was the policy on date X" by querying chunks valid on that date. The metadata supports it; the retrieval layer does not yet.
