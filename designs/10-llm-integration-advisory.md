# Design Document: LLM Integration Patterns for Internal Copilot Tooling

**REDACTED** Bank (advisory engagement with their data science team)
**Author:** Ananth — Senior Data Architect, AWS
**Status:** Delivered as architectural guidance + reference implementation patterns
```
NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.
```

---

## 1. Context & Problem Statement

**REDACTED**'s data science team had begun building internal "copilot" tools — assistants for specific roles (underwriter copilot, KYC analyst copilot, contact center agent assist). Initial prototypes worked impressively in demos but degraded in production:

- Hallucinated policies that didn't exist.
- Quoted regulations with confident but wrong citations.
- Cost spiked unpredictably as conversation history grew.
- Latency became unworkable at >4 turns of conversation.
- No clear path to evaluate whether a new prompt or model upgrade was actually better.

The data science team had ML expertise but limited LLM-systems experience. My role: advise on integration patterns and design choices, not own implementation.

**Goal:** Establish reusable patterns and decision frameworks for LLM-backed internal tooling, with emphasis on RAG system design, context window management, and hallucination mitigation.

**Non-goals:** Building the copilots myself; selecting a single model for the bank; replacing the team's ownership of their use cases.

---

## 2. Scope of Advisory

| Area | Output |
|---|---|
| RAG system design | Reference architecture, retrieval evaluation methodology |
| Context window management | Strategies for multi-turn conversations and large-document Q&A |
| Hallucination mitigation | Layered defense pattern; eval harness |
| Model selection | Decision matrix for model choice per use case |
| Cost & latency | Patterns for caching, routing, and budget enforcement |
| Eval & monitoring | Offline eval harness; production telemetry pattern |

---

## 3. RAG System Design

### 3.1 Reference Architecture

```
User query
     │
     ▼
Query rewriter (LLM)  ──► standalone, contextualized query
     │
     ▼
Hybrid retriever (vector + BM25)  ──► candidate chunks
     │
     ▼
Reranker (cross-encoder)  ──► top-K reranked chunks
     │
     ▼
Context assembler (token budget aware)
     │
     ▼
Generation LLM (with citations enforced via prompt + JSON schema)
     │
     ▼
Citation verifier  ──► reject/regenerate if citations don't ground claims
     │
     ▼
Response to user (with citations)
```

### 3.2 Key Choices Recommended

#### Hybrid retrieval over pure vector

**Reasoning:** Pure vector search misses exact-match queries (policy numbers, regulation IDs). Pure BM25 misses paraphrase. RRF fusion of the two consistently outperformed either in the team's eval set (we set this eval up early to make the choice empirical, not opinion).

#### Reranking is non-optional

**Reasoning:** First-stage retrieval optimizes for recall (return everything possibly relevant). Reranking with a cross-encoder optimizes for precision in the top-K that goes into the prompt. Skipping reranking and dumping top-30 vector hits into context produced worse answers and higher cost.

#### Chunking strategy: structured-aware

**Reasoning:** Generic 512-token chunks shred policy documents, splitting a section header from its content. Recommended structured chunking that respects document hierarchy (heading + body stays together), with overlap. For policy documents specifically, chunked at section level with parent breadcrumb preserved as metadata.

#### Query rewriting for multi-turn

**Reasoning:** "What about for commercial customers?" makes no sense to a retriever in isolation. A cheap LLM call that rewrites it to "What is the loan documentation requirement for commercial customers?" given conversation context dramatically improved retrieval quality.

#### Citations are part of the contract, not a feature

**Reasoning:** The model is required (via system prompt and structured output) to return both an answer and citations to source chunks. A post-generation verifier checks that each claim in the answer has a supporting citation; if not, regenerate. This is the single most effective hallucination control at the response layer.

---

## 4. Context Window Management

### 4.1 The Problem

Naive multi-turn implementations append every user message and assistant response to the context window. By turn 6–8, contexts hit 30k+ tokens, latency doubles, and cost grows superlinearly. Even with large-context models, signal-to-noise drops and the model attends less to the most relevant parts.

### 4.2 Patterns Recommended

#### Pattern 1: Sliding window with summary

Keep the last N (typically 4–6) turns verbatim. Older turns get summarized into a single "conversation so far" block. Summary is regenerated periodically, not on every turn.

**Reasoning:** Recent turns matter most for coherence; older turns matter for context. Summarization preserves the latter cheaply.

#### Pattern 2: Working memory + retrieval

For long-running sessions (e.g., an underwriter working a single loan over an hour), persist key facts ("borrower name: X, loan amount: Y, current question under discussion: Z") in a structured working-memory store. Retrieve these on every turn rather than relying on conversation history.

**Reasoning:** Structured state is reliable; conversational state is lossy. The model is much better at "the loan amount is $4.2M" presented as a structured fact than as an inference from 3 turns back.

#### Pattern 3: Tool use for retrieval, not stuffing

When a copilot needs information from a system (e.g., customer balance, recent transactions), recommend tool/function calling rather than pre-fetching and stuffing the context. Tools are pulled only when needed.

**Reasoning:** Pre-stuffing every conceivable fact "just in case" balloons context. Tool calls are pay-per-use; context stuffing is pay-always.

#### Pattern 4: Context budget enforcement

Each prompt has an explicit token budget broken down: system prompt (X tokens), retrieved chunks (Y tokens), conversation history (Z tokens), generation (W tokens). If retrieval returns more than Y, truncate by relevance score, not by document order.

**Reasoning:** Without explicit budgets, growth happens silently and one component crowds out another. Explicit budgets force trade-offs to be deliberate.

---

## 5. Hallucination Mitigation

A layered defense, because no single technique is sufficient.

### Layer 1: Grounding via RAG

The first defense: don't ask the model to recall — ask it to read. Retrieve relevant content and instruct the model to answer **only from the provided context**.

System-prompt language matters: "If the context does not contain the answer, say 'I don't have that information' — do not infer or extrapolate."

### Layer 2: Citation enforcement

Require structured citations linking claims to source chunks. Reject responses that cannot be grounded.

### Layer 3: Self-consistency for high-stakes answers

For high-stakes queries (e.g., policy interpretation), sample N responses and check for consistency. Disagreement among samples is a strong signal of model uncertainty — surface this to the user as "low confidence" rather than picking one.

### Layer 4: Verifier model

A second LLM call grades the first response: "Given this question and these source chunks, is this answer fully supported?" Verifier disagreement triggers regeneration or escalation.

### Layer 5: Calibrated abstention

Train the team to view "I don't know" as a feature, not a failure. The system prompt and few-shot examples should explicitly reward abstention. A copilot that admits uncertainty 8% of the time but is correct 99% of the time it does answer is more useful than one that always answers and is right 87% of the time — particularly in regulated contexts.

### Layer 6: Eval harness

Hallucination is invisible without measurement. Recommended an eval set per use case with:

- Questions where the answer is in the corpus (test recall + faithfulness).
- Questions where the answer is **not** in the corpus (test abstention).
- Adversarial questions designed to elicit fabrication.

This eval is gated in CI: a prompt or model change cannot deploy without running it.

### What does NOT mitigate hallucination (despite popular claims)

- **Bigger models alone.** Smaller hallucination rates, but not zero, and without grounding/citation the failure mode is the same.
- **Higher temperature controls.** Lowering temperature reduces variance but doesn't address fabrication on out-of-distribution queries.
- **"Be accurate" in the system prompt.** The model already wants to be accurate. Telling it again does not help; giving it grounded sources does.

---

## 6. Model Selection Framework

Recommended a use-case-driven decision matrix rather than a single bank-wide model:

| Use case characteristic | Likely fit |
|---|---|
| Long, complex documents; low volume; high stakes | Larger frontier model (Claude Opus / similar) |
| High-volume Q&A with strong RAG grounding | Mid-tier model (Claude Sonnet / similar) |
| Classification, routing, simple extraction | Smaller, cheaper model (Haiku / similar) |
| Strict data-residency, sensitive data | Bedrock-hosted models, in-account, no cross-region |

**Routing pattern:** A cheap classifier model determines query intent; the orchestrator routes to the appropriate generator. Most queries don't need the largest model.

---

## 7. Cost & Latency Patterns

- **Prompt caching** for stable system prompts and few-shot examples. Material cost reduction for repeated calls.
- **Semantic caching** for FAQ-like queries: if a new query is semantically similar to a recent one and the underlying corpus hasn't changed, serve the cached answer.
- **Async + streaming** for user-facing responses: stream tokens as generated rather than waiting for completion. Perceived latency drops dramatically.
- **Per-team budget enforcement** at the gateway: a misbehaving prototype cannot consume the entire monthly LLM budget.

---

## 8. Eval & Monitoring Patterns

### Offline eval

- Per-use-case eval sets: ~100–500 examples, refreshed quarterly.
- Metrics: faithfulness, answer relevance, citation accuracy, abstention precision.
- LLM-as-judge for scaling, with periodic human spot-checks for calibration.
- Eval gated in CI; prompt changes require eval pass.

### Online monitoring

- User feedback signals (thumbs up/down) logged per response.
- Sampled production responses re-evaluated by judge model, surfacing drift.
- Retrieval-quality metrics (top-K hit rate against logged user clicks/dwell).
- Refusal/abstention rate as a leading indicator: a sudden drop may indicate the model has started "trying harder" to answer — not necessarily good.

---

## 9. What I Specifically Pushed Back On

A few patterns I advised against, with reasoning:

- **"Just fine-tune"** — proposed early as a hallucination cure-all. Fine-tuning helps style and format; it does not reliably prevent fabrication on unseen facts. Recommended RAG first, fine-tune later only with measured ROI.
- **One giant copilot for everything** — the team initially wanted one assistant for all bank workflows. Recommended use-case-scoped copilots: smaller corpora, sharper system prompts, easier evals, clearer ownership. Same backbone model can serve them all.
- **Vector-DB-as-knowledge-base** — proposed as a way to "give the model all the bank's knowledge." Vector DBs are retrievers, not knowledge bases. They have no enforcement of source-of-truth, no governance. Recommended treating the lakehouse as the system of record; the vector DB is a derived index.

---

## 10. Outcome of the Advisory

- Two production copilots launched on these patterns, with measured hallucination rates below targets set during design.
- Eval harness adopted by the data science team and expanded across subsequent LLM projects.
- The team developed a self-serve LLM platform that abstracted these patterns; subsequent use cases launched in weeks rather than months.

---

## 11. What I'd Reconsider

- Should have written up the patterns earlier as a living internal playbook rather than slide decks. Knowledge transfer was bottlenecked on synchronous meetings for too long.
- Underweighted observability tooling in early advice — "log everything" sounds obvious but the team needed concrete schema recommendations sooner.
- Spent too long on model selection debates that the field rendered moot within a quarter. The pattern of *abstracting model choice behind a routing layer* matters more than picking today's best model.
