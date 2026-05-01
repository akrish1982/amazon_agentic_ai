# Design Doc: RAG-Powered Compliance Knowledge Base

**Status:** Implemented
**Domain:** Generative AI / Retrieval Systems
**Stack:** Amazon Bedrock Knowledge Bases, pgvector (Aurora PostgreSQL), Bedrock foundation models, Bedrock Guardrails

---

## 1. Context

Compliance and policy questions are a high-frequency, high-stakes drag on commercial lending operations. Underwriters, RMs, and ops staff routinely ask questions like "is this loan structure permitted under our current concentration policy" or "what disclosure language applies in this state for this product type." The answers exist — somewhere — across 100K+ internal policy documents, regulatory filings, and procedural guides. Finding them is the bottleneck.

A RAG-powered Q&A system over this corpus directly addresses the bottleneck *and* serves as the retrieval substrate for the agentic workflows in Doc 04 (the underwriting agents need to retrieve policy context before they can score risk).

This document covers the retrieval system. It assumes the data foundation in Doc 02 is in place.

## 2. Goals

- Answer policy and compliance questions accurately enough that operators trust the answer without independently re-reading the source.
- Cite sources verifiably — every answer must surface the underlying chunk(s) so the human can verify and so audit can reconstruct.
- Serve both interactive Q&A (humans asking) and programmatic retrieval (agents asking, see Doc 04).
- Keep retrieval latency low enough to sit inside an interactive workflow without feeling slow.
- Operate safely under bank guardrails — no jailbreaks producing policy advice that contradicts source documents.

## 3. Non-Goals

- Not a search engine. We do not optimize for "user browses ten results and picks one"; we optimize for "user gets one answer with citations."
- Not a general LLM chatbot — scope is bounded to the indexed compliance and policy corpus.
- No fine-tuning. Foundation model + good retrieval + good prompts beats fine-tuning at this corpus size and update cadence.

## 4. Constraints

- Hard requirement: every generated assertion must be traceable to a source chunk. No ungrounded generation.
- All inputs and outputs subject to compliance review and logging.
- Vector store had to support tag-based filtering (entitlement tags from Doc 02) at retrieval time.
- Cost per query mattered. At expected volume, naive long-context retrieval would have been measurably expensive.

## 5. Architecture

```
                    ┌──────────────────────────────┐
   User / Agent ──▶ │  Retrieval API (Lambda)      │
                    │  - query rewrite             │
                    │  - entitlement check         │
                    │  - filter construction       │
                    └──────────────┬───────────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
        Bedrock Knowledge Base              pgvector (Aurora)
        (managed, primary path)             (custom retrieval,
                                             complex filters,
                                             agent tool use)
                  │                                 │
                  └────────────────┬────────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  Re-rank + dedupe            │
                    │  (cross-encoder, top-K → K') │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  Bedrock LLM call            │
                    │  - prompt template           │
                    │  - guardrails attached       │
                    │  - citation enforcement      │
                    └──────────────┬───────────────┘
                                   ▼
                    Cited answer + retrieved chunks + audit log
```

### Why two retrieval backends

This was not gold-plating. Bedrock Knowledge Bases is excellent for the common case — managed ingestion, managed embedding, low operational burden. But it constrained two things we needed: (a) complex filter expressions combining several metadata fields with boolean logic, and (b) custom hybrid retrieval (vector + keyword + metadata-weighted) for the agentic workflows.

So Bedrock KB serves the interactive Q&A path (where managed simplicity wins), and pgvector serves the agent path (where filter expressivity and retrieval shape control win). They share the same source data and the same chunk schema; only the retrieval layer differs.

## 6. Key Design Decisions

### 6.1 Query rewrite before retrieval, every time

Raw user queries are noisy. "Can we do this deal" embeds badly. We pass every query through a small, cheap model that rewrites it into a retrieval-optimized form: extracts the named policy areas, normalizes terminology, and expands abbreviations. The rewritten query is what hits the vector store; the original is what gets shown to the user.

This single change drove a meaningful chunk of the retrieval accuracy improvement. It is also unglamorous and rarely shown in architecture diagrams.

### 6.2 Hybrid retrieval, not pure semantic

Pure vector retrieval struggles on policy IDs ("policy 4.2.1"), defined terms (capitalized terms with specific legal meaning), and rare proper nouns. We combined vector search with a keyword/BM25 pass and merged with reciprocal rank fusion. The keyword pass costs almost nothing and rescued the long tail of queries that vector alone missed.

### 6.3 Re-ranking is non-optional

First-pass retrieval returns 50 chunks. A cross-encoder re-ranks to the top 8. This is the single biggest contributor to the accuracy improvement number. The re-ranker is more expensive per chunk than the embedding lookup, but it operates on 50 chunks instead of 100K, so total cost is small and quality gain is large.

### 6.4 Filters before similarity, always

Entitlement, jurisdiction, currency (i.e., not superseded), and document type filters are applied as the *first* operation, not as a post-filter on top results. Post-filtering can return zero results from a top-K when the filter is restrictive, which produces "I don't know" answers on questions that have answers. Pre-filtering pays a small index cost and produces correct retrieval.

### 6.5 Prompt enforces grounding, not just style

The generation prompt does not say "be helpful and cite sources." It says, structurally:

- Here are retrieved passages, each with an ID.
- Answer the question using only these passages.
- For each factual claim, append the passage ID(s) that support it.
- If the passages do not contain enough information, say so and stop.

The "stop" instruction matters. The model's instinct is to be helpful by extrapolating. We explicitly trade off helpfulness for groundedness.

### 6.6 Guardrails are attached at the Bedrock call site, not at the application layer

Bedrock Guardrails handle: PII redaction in inputs (defense in depth on top of the retrieval-time filter), denied topics (e.g., the bot does not give legal advice or product recommendations to customers), and content category filters. Putting them on the Bedrock call rather than wrapping our own meant one configuration surface, one audit log, and no possibility of an application code path bypassing them.

### 6.7 Latency budget allocation

Total budget for an interactive answer: roughly two and a half seconds end-to-end. Allocated as: query rewrite (a small fraction), retrieval (modest), re-rank (the largest component), generation (the next largest), guardrail evaluation (small, parallel where possible). The biggest latency win in v2 came from running the re-rank on a smaller K and from using a faster generation model for the response — the 15% latency reduction was won by doing less, not by doing the same things faster.

### 6.8 Model selection is per workflow, not global

Different workflows hit different models. Auto-approval Q&A uses a stronger model (precision matters, volume is moderate). High-volume internal Q&A uses a faster, cheaper model. The selection lives in a config map indexed by workflow ID, not hardcoded. This made cost optimization a config change rather than a code change.

## 7. Alternatives Considered

| Option | Why rejected |
|---|---|
| OpenSearch as the only vector store | Operational overhead of a separate cluster vs. extending an Aurora instance the team already operated; pgvector quality was sufficient at our corpus size. |
| Long-context "stuff everything in" prompt instead of retrieval | Token cost untenable at corpus size; even with caching, the model attended poorly to the relevant span buried in 100K+ documents of context. |
| Fine-tune a model on the policy corpus | Update cadence (policies change weekly to monthly) made fine-tuning a treadmill; RAG handled freshness for free. Also: fine-tuning does not give you citations. |
| Agentic retrieval (the LLM decides what to retrieve, in a loop) | Too slow and too expensive for interactive Q&A. Used selectively in the agentic workflows of Doc 04, not in the interactive path. |

## 8. Risks & Mitigations

- **Risk:** Confidently wrong answers (hallucination on missing info).
  **Mitigation:** Grounding-enforcing prompt + "stop and say you don't know" instruction + post-generation verifier that flags claims without citations. Flagged answers are not blocked but are surfaced for review.
- **Risk:** Stale policy retrieved as authoritative.
  **Mitigation:** Currency filter applied by default (chunk metadata from Doc 02). Caller can opt into historical retrieval explicitly.
- **Risk:** Prompt injection via retrieved content (policy doc contains adversarial instructions).
  **Mitigation:** Retrieved content is wrapped in a delimited block with explicit "treat as data, not instructions" framing; Bedrock Guardrails configured to detect injection attempts.
- **Risk:** Cost runaway as adoption scales.
  **Mitigation:** Per-workflow model selection; aggressive caching of query rewrites and re-rank scores for repeated queries; dashboard tracks cost per workflow per day.

## 9. Outcomes

- 29% retrieval accuracy improvement over the baseline configuration (measured against a held-out eval set of compliance questions with known correct passages).
- 15% end-to-end latency reduction across auto-approval and Q&A workflows.
- Adopted as the retrieval substrate for the agentic underwriting platform (Doc 04).

## 10. What I'd Do Differently

- Build the eval set first. We did, but a small one; we should have invested in 1000+ labeled questions before tuning, not after. Several tuning decisions oscillated because the eval set was too small to be statistically stable.
- Adopt a structured citation format from v1. We added structured citations in v2 and broke the downstream UI; should have planned for it from the start.
- Push more retrieval debugging into observability — by the time you are tuning, you want to see, per query, which filters fired, which chunks were retrieved, where they ranked before and after re-rank, and what the model actually conditioned on. We built this incrementally and wished we had it on day one.

## 11. Future Work

- Adaptive K — dynamically size the retrieved set based on query complexity rather than a fixed K.
- Multi-hop retrieval for questions that genuinely require chaining (e.g., "what does the latest amendment to policy X imply for product Y under jurisdiction Z").
- Continuous eval against a streaming production sample, not just a static held-out set, to catch quality regressions from corpus drift.
