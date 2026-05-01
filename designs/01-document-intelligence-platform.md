# Design Document: AI-Powered Document Intelligence Platform

**REDACTED** Bank
**Author:** Ananth — Senior Data Architect, AWS
**Status:** Delivered

NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.

---

## 1. Context & Problem Statement

**REDACTED**'s commercial lending, KYC, and loan operations teams processed a high volume of unstructured documents daily — loan packets, financial statements, tax returns (1040, K-1, 1120), trust agreements, articles of incorporation, and customer correspondence. Analysts manually located fields, reconciled them across documents, and re-keyed them into downstream systems.

Pain points:

- Average review time of 35–55 minutes per loan packet, with bottlenecks in underwriting SLAs.
- High variance between reviewers (precision and completeness).
- Existing OCR tooling captured raw text but did not understand layout, field semantics, or cross-document relationships.
- Search over the document corpus was keyword-only; analysts could not ask "show me all loan packets where the borrower's stated revenue conflicts with the tax return."

**Goal:** Reduce manual document review effort by at least 50% while keeping a human-in-the-loop for any extraction below confidence threshold, and expose semantic search across the document corpus.

**Non-goals:** Fully autonomous underwriting decisions; replacement of the system of record; processing of documents outside the in-scope corpus (we deliberately avoided scope creep into call transcripts and emails in phase 1).

---

## 2. Requirements

| Type | Requirement |
|---|---|
| Functional | Extract ~120 named fields across 14 document types |
| Functional | Semantic search ("find documents discussing collateral substitution") |
| Functional | Cross-document reconciliation (e.g., revenue on app vs. tax return) |
| Functional | Human review queue for low-confidence extractions |
| Non-functional | <5 min end-to-end latency per document for 95th percentile |
| Non-functional | All data, models, and inference within **REDACTED**'s AWS account; no data egress |
| Non-functional | Auditability: every extraction must link to source page, bbox, and prompt |
| Compliance | SOC 2, GLBA, internal model risk management (SR 11-7) |

---

## 3. High-Level Architecture

```
S3 (raw docs)
    │
    ▼
Textract (OCR + layout) ──► S3 (parsed JSON, page images)
    │
    ▼
Chunker / Page router ──► Document classifier (small LLM)
    │
    ▼
Field extractor (Bedrock Claude / Titan) ──► Confidence scorer
    │                                               │
    ▼                                               ▼
DynamoDB (extracted fields)              SQS → human review queue
    │
    ▼
Embedding generator (Titan Embed) ──► OpenSearch Serverless (vector + BM25)
    │
    ▼
Reconciliation engine (Step Functions + Lambda)
    │
    ▼
API Gateway → underwriter UI
```

---

## 4. Key Design Decisions

### 4.1 Extraction approach: LLM-based, not template-based

**Decision:** Use a generative LLM (Anthropic Claude on Bedrock) with structured output prompting, not a fine-tuned form-extraction model or template/anchor-based extraction.

**Alternatives considered:**

1. **Textract Queries / AnalyzeDocument** — works for structured forms (W-2, simple 1040) but degrades sharply on free-form attachments, addenda, and bank-specific loan packets.
2. **Fine-tuned LayoutLM / Donut** — strong on visually-rich documents but required several thousand labeled examples per doc type. **REDACTED** had inconsistent labeled data and a moving target on field definitions.
3. **Rules + regex on OCR text** — brittle; failed any time the layout changed.
4. **LLM with structured output (chosen).**

**Reasoning:**

- 14 document types × ~10 fields each = 140 schemas. Building and maintaining 140 templates is a perpetual cost.
- LLMs handle layout drift, paraphrased headers ("Total Income" vs. "Gross Receipts"), and cross-page context naturally.
- Schema-constrained generation (JSON schema in the prompt + regex post-validator) gave us structured output reliably.
- Confidence scoring via log-probability proxies + verifier prompt let us route uncertain extractions to humans.

**Trade-offs accepted:**

- Higher per-document cost (~$0.04/document vs. ~$0.002 for Textract Queries). This was a non-issue given the analyst-hour savings.
- Non-determinism: mitigated with `temperature=0`, fixed prompts versioned in Git, and golden-set regression tests on every prompt change.

### 4.2 Why two-stage (classify → extract), not one-stage

**Decision:** First classify the document type with a small/cheap LLM call, then route to a doc-type-specific extraction prompt.

**Reasoning:**

- A generic "extract all fields" prompt produced lower precision and higher token cost (large schema in every prompt).
- Doc-type-specific prompts could include few-shot examples tuned to that document, improving F1 by ~9 points on the harder doc types (trust agreements, K-1s).
- Misclassification was rare (<1.5%) and caught by downstream validators (e.g., a "1040" with no SSN field is suspicious).

### 4.3 Vector store: OpenSearch Serverless with vector + BM25 hybrid

**Decision:** OpenSearch Serverless with `knn_vector` field + BM25, hybrid retrieval at query time.

**Alternatives considered:**

| Option | Why rejected |
|---|---|
| Pinecone | Data residency + procurement friction with a third-party SaaS in regulated environment |
| pgvector on Aurora | Workable, but at 5M+ chunks the recall/latency trade-offs got painful, and we wanted managed scaling |
| Kendra | Strong out-of-box, but cost scales with document count and we lost control over chunking strategy |
| OpenSearch Serverless (chosen) | In-account, hybrid retrieval, mature ACL story, scales to billions of vectors |

**Reasoning:**

- Pure vector search missed exact-match queries ("loan number 4471829"). Pure BM25 missed paraphrase. Hybrid (RRF fusion of the two) consistently beat either alone in our offline eval (nDCG@10 +14% over vector-only).
- OpenSearch ACLs let us enforce row-level security: an underwriter in commercial cannot retrieve consumer documents.

### 4.4 Chunking strategy

**Decision:** Page-level chunking with parent-document attribution, plus a "section" chunk derived from layout headings. Embed both granularities; retrieve at section level, expand to page for context.

**Reasoning:**

- Naive 512-token chunks shredded financial tables. Page-level kept tables intact.
- Section-level chunking gave us the right granularity for "discussing X" queries.
- Embedding both is ~2× cost but materially better recall on multi-page documents.

### 4.5 Confidence and human-in-the-loop

**Decision:** Two-signal confidence: (a) self-consistency across N=3 sampled extractions at temperature 0.3; (b) verifier LLM call asking "is this field value supported by this passage?" with citation.

Threshold: extractions below 0.85 confidence routed to A2I (Amazon Augmented AI) review queue. Field-level — not document-level — so analysts only see the 2–3 fields that need attention.

**Reasoning:** Document-level routing forced reviewers to re-check fields the model got right. Field-level routing was the single biggest contributor to the 65% effort reduction.

### 4.6 Auditability

Every extracted field stored with:

```json
{
  "field": "borrower_annual_revenue",
  "value": 4250000,
  "confidence": 0.92,
  "source": {
    "document_id": "...",
    "page": 7,
    "bbox": [123, 445, 678, 489],
    "supporting_text": "..."
  },
  "model": "claude-3-sonnet-20240229",
  "prompt_version": "v14",
  "extracted_at": "..."
}
```

**Reasoning:** SR 11-7 model risk management requires lineage. Auditors needed to reproduce any extraction.

---

## 5. Hallucination Mitigation

| Risk | Mitigation |
|---|---|
| Model invents a value not in the document | Verifier pass: "quote the exact text supporting this value." If no quote, mark as `null` |
| Model confuses similar fields ("net income" vs. "operating income") | Doc-type-specific prompts with explicit definitions; few-shot disambiguation examples |
| Model normalizes incorrectly ($4.25M → 4250000) | Two-step: extract raw text → deterministic normalization in code |
| Schema drift | JSON schema validator on output; failures retry with corrective prompt, then escalate to human queue |

---

## 6. Outcome

- **65% reduction** in average analyst review time per loan packet.
- 92% straight-through processing rate on the highest-volume document types after 4 months of prompt tuning.
- Reusable extraction framework adopted by two other lines of business.

---

## 7. What I'd Reconsider

- Started with a single monolithic OpenSearch collection. Should have partitioned by line of business from day one — splitting later was painful.
- Underestimated prompt-versioning discipline at the start. Eventually moved prompts to Git with semantic versioning and golden-set CI; should have done this on day one.
- Should have invested earlier in synthetic eval-set generation for tail doc types where production volume was too low to monitor drift effectively.
