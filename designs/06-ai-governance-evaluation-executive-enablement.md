# Design Doc: AI Governance, Evaluation & Executive Enablement

**Status:** Implemented (continuous practice, not a one-time deliverable)
**Domain:** AI Governance / Engineering Practice / Executive Communication

---

## 1. Context

Agentic AI is risky to deploy and easy to misrepresent. Two failure modes were specifically in scope:

1. **Engineering-side failure** — shipping an agent that performs well in development and degrades silently in production, or that meets aggregate accuracy targets while failing on the few cases where failure is expensive.
2. **Communication-side failure** — investing serious capital in agentic AI capabilities and being unable to defend the investment to the VP/C-suite in business terms, leading to budget reductions or political pressure to repurpose work mid-stream.

This document covers two interlocking workstreams: pre-production agent evaluation (so the engineering side does not silently regress) and architectural roadmap communication (so the leadership side stays aligned). Both are necessary; either alone is insufficient.

## 2. Goals

- Establish a repeatable, defensible evaluation framework that runs before any agent change reaches production.
- Measure the dimensions that actually matter for a banking-context agent: accuracy, latency, compliance adherence, cost.
- Produce executive-ready architectural roadmaps that translate agentic AI investments into quantified business outcomes — without overpromising.
- Build a feedback loop so production behavior informs eval, and eval results inform investment decisions.

## 3. Non-Goals

- Not a model risk management framework replacement. The bank has an existing MRM program; this complements it for LLM-based components, it does not replace it.
- Not an automated decision-making system about deployment. Eval results inform; humans decide.
- Not a vendor selection framework — the question of "which foundation model" is informed by these evals but is not the primary purpose.

## 4. Constraints

- Eval must be executable on every meaningful change (prompt change, model swap, retrieval config change, tool change), not only on "major releases."
- Eval data sets must respect customer privacy — production traces used for eval are sampled and PII-redacted before they enter the eval corpus.
- Executive communication must avoid both undersell ("we built some AI things") and oversell ("AI will replace underwriters"); credibility is the long-term currency.

## 5. Architecture of the Eval Framework

```
┌─────────────────────────────────────────────────────────┐
│ Eval Corpus (versioned)                                 │
│  - golden questions + expected behaviors                │
│  - production-sampled cases (PII-redacted)              │
│  - adversarial / red-team cases                         │
│  - regression cases (every past production incident)    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Eval Harness (CI-integrated)                            │
│  - runs candidate agent config against full corpus      │
│  - records: outcome, latency, cost, retrieval hits,     │
│    tool calls, citation coverage, guardrail triggers    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Scoring                                                 │
│  - deterministic checks (citation present, schema       │
│    valid, expected tool called, etc.)                   │
│  - LLM-as-judge (with rubric + reference answer)        │
│  - human-in-the-loop spot checks for high-stakes cases  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Report                                                  │
│  - aggregate metrics                                    │
│  - regression diff vs. prior baseline                   │
│  - per-segment breakdown (which case classes regressed) │
│  - go / no-go recommendation (advisory, not binding)    │
└─────────────────────────────────────────────────────────┘
```

## 6. Key Design Decisions

### 6.1 Evaluate dimensions, not "quality"

A single quality score hides everything that matters. We measure four dimensions independently:

- **Accuracy** — does the agent produce the correct outcome? Measured against expected behaviors per case.
- **Latency** — distribution, not just mean. The 99th percentile is what users feel.
- **Compliance adherence** — did the agent stay within policy? Did it cite sources where required? Did it refuse where it should refuse?
- **Cost** — total token spend, model selection, tool invocation count per case.

Improvements often trade off across these. Surfacing the trade-off is the point. A change that improves accuracy by a few points while doubling cost is a different decision than one that improves accuracy at flat cost.

### 6.2 The eval corpus is versioned and additive

Every production incident becomes a regression case. The corpus only grows. This is the single most valuable property of the framework — we cannot ship a regression of a past failure without seeing it in the eval report.

The corpus is versioned because changes to the corpus itself change what "passing" means. We track corpus version alongside agent version.

### 6.3 LLM-as-judge with care

LLM-as-judge is used for cases where the correct answer is a free-form rationale, citation pattern, or judgment call. It is not used for cases where a deterministic check exists (citation present? tool called? schema valid?). Determinism beats LLM judgment whenever determinism is possible.

When LLM-as-judge is used, we constrain it: an explicit rubric, a reference answer, a structured output. We also calibrate it periodically against human ratings to detect drift in judge behavior.

### 6.4 Production sampling feeds eval, with redaction

A small fraction of production traces are sampled, PII-redacted, and fed back into the eval corpus. This catches the case-mix drift problem: the questions users ask in production rarely match the questions designers anticipate. Production sampling closes the loop.

Redaction is enforced and audited; under no circumstances do raw production traces enter the eval corpus.

### 6.5 Eval is mandatory but advisory

Eval results are required for any change to a production agent configuration. The results do not auto-approve or auto-block deployment. They go to a human reviewer who applies judgment, especially on changes that improve some metrics while regressing others.

This is intentional. Auto-gating creates pressure to game the metrics. Advisory framing keeps the reviewer honest about what the metrics mean.

### 6.6 Pre-production red-teaming as a separate track

Adversarial cases — prompt injections, attempts to extract PII, attempts to bypass guardrails, attempts to elicit out-of-scope advice — are run as a separate eval track. They have a higher bar: regression on a red-team case blocks deployment, period.

## 7. Architecture of Executive Enablement

### 7.1 Roadmaps are framed in business outcomes, not capabilities

Bad: "We will deploy multi-agent orchestration with RAG-augmented retrieval and HITL escalation."
Good: "We will reduce underwriter cycle time from 48 hours to under 6 hours on small business loans, freeing capacity equivalent to N FTE that can be redirected to growth segments. The capability investment required is described below."

The first framing is true and useless. The second is true and decision-relevant. VPs and C-suite allocate capital against the second framing.

### 7.2 Quantification is conservative and traceable

Every quantified outcome traces to its source: baseline measurement, projection method, assumptions. Optimistic projections are flagged as such. Ranges, not point estimates, where uncertainty is real.

We do not say "saves $X" without being able to show how X was computed. Credibility lost on one inflated number does not come back.

### 7.3 Roadmaps surface what is *not* being done, not just what is

Every roadmap explicitly names the use cases that were considered and deprioritized, with the reason. This serves two functions: it shows the leadership audience that the recommended path was chosen against alternatives (not by default), and it preempts the "why aren't we doing X" question.

### 7.4 Investment is staged against measurable milestones

Roadmaps stage investment such that each stage produces a measurable result before the next stage is committed. This protects the program from cancellation (each stage delivers value standalone) and from runaway scope (the next stage is contingent on the previous stage's measured outcome).

### 7.5 Translate architectural choices into risk language

Senior leadership cares about risk vocabulary they already use: operational, regulatory, reputational, financial. A statement like "we use HITL escalation" lands differently than "we maintain a regulatory-acceptable accountability boundary by ensuring every credit decision crosses a human reviewer before commitment, which preserves our existing supervisory examination posture."

The second framing is what gets the program through internal risk committees.

### 7.6 Quantified outcomes across the customer base

Roadmaps quantify in terms the business plans against — revenue, cost, capacity, time-to-decision, customer experience metrics — across the full customer base affected (10M customers). This is not because every customer touches every workflow. It is because leadership thinks about the portfolio impact, not the per-workflow impact.

## 8. Alternatives Considered

| Option | Why rejected |
|---|---|
| Manual eval only (read traces, eyeball quality) | Does not scale to the change cadence; not reproducible across reviewers; misses regressions that aren't visually obvious. |
| Vendor eval platform | Several evaluated. None handled our compliance corpus, citation grounding requirements, and audit posture; would have ended up wrapping vendor + custom anyway. |
| Defer governance until after launch | The single most expensive mistake an AI program can make. Retrofitting governance is multiples more expensive than building it in. |
| Ship roadmap once per year | Loses the ability to adjust to learning. We landed on quarterly roadmap revisions with continuous metric reporting in between. |

## 9. Risks & Mitigations

- **Risk:** Eval corpus grows stale relative to production case mix.
  **Mitigation:** Continuous production sampling (with redaction); periodic corpus review.
- **Risk:** Eval becomes a check-the-box exercise with no teeth.
  **Mitigation:** Advisory framing forces reviewer engagement; regression on red-team cases is hard-blocking; periodic audit of approved-despite-regression decisions.
- **Risk:** Executive metrics inflate over time as nobody pushes back.
  **Mitigation:** Every quantified claim traces to source data; quarterly review challenges baselines; external benchmarking where available.
- **Risk:** Roadmap commits to outcomes the architecture cannot deliver.
  **Mitigation:** Architecture review on every roadmap milestone; outcomes are conditional on architectural feasibility, not separate from it.

## 10. Outcomes

- Pre-production eval framework runs on every meaningful change to production agent configurations across the platform.
- Production incidents are added to the eval corpus as regression cases; no incident has recurred.
- Executive roadmaps have translated agentic AI capability investments into quantified lending and marketing outcomes across 10M customers, sustaining the program's funding posture across budget cycles.

## 11. What I'd Do Differently

- Build the eval framework before the first agent went to production. We retrofitted; some early production behavior would have been caught earlier.
- Invest in the executive narrative earlier. The first roadmap underweighted the business-outcome framing and overweighted the architectural one; the second was much better received.
- Establish baseline measurements (cycle time, accuracy, cost) *before* the agent program started, not after. We had to reconstruct some baselines; reconstruction is always more contested than measurement.

## 12. Future Work

- Continuous production eval — not just sampling for the corpus, but real-time scoring of production responses against deterministic checks (citation present, in-corpus grounding, etc.).
- Eval-driven model selection — automated A/B routing of a small production fraction to a candidate model with eval-based promotion criteria.
- Quantified post-deployment outcome tracking — close the loop between roadmap-promised outcomes and observed outcomes, surfaced to leadership without requiring manual reporting.
- Cross-program eval reuse — many of these patterns generalize beyond lending agents to other agentic AI investments the bank may make.
