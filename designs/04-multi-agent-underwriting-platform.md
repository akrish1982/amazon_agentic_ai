# Design Doc: Multi-Agent Loan Underwriting Platform

**Status:** Production
**Domain:** Agentic AI / Lending Operations
**Stack:** Amazon Bedrock, LangChain, CrewAI, Amazon SageMaker, AWS Step Functions, AWS Lambda

---

## 1. Context

Small business loan underwriting is a structured but judgment-heavy process. An incoming application goes through document intake (financial statements, tax returns, formation docs), regulatory and KYC validation, risk scoring, policy compatibility checks, and human review before approval or escalation.

Pre-platform, the median underwriter decision time was approximately 48 hours. The actual underwriter judgment portion of that time was small — minutes, not hours. The rest was waiting on intake, parsing, validation, and information assembly.

The opportunity was clear: automate everything that was procedural, give the underwriter a fully-prepared decision package, and reserve human attention for actual judgment calls.

This was the platform's flagship use case — and the proving ground for the bank's agentic AI architecture more broadly.

## 2. Goals

- Cut underwriter decision time materially while preserving (or improving) decision quality.
- Process daily loan transaction volume reliably with bounded tail latency.
- Build a multi-agent architecture that other lending workflows can adopt later — this is a *platform*, not a one-off automation.
- Keep humans in the loop on every decision; the agents propose, humans dispose.
- Make every agent action auditable.

## 3. Non-Goals

- No fully-autonomous approval. Every decision crosses a human boundary before commitment.
- No replacement of the loan origination system of record — the agents read from and write to it, but it remains authoritative.
- No customer-facing agent in v1. Agents operate behind the underwriter UI; the customer experiences the speed improvement, not the agent itself.

## 4. Constraints

- Regulatory: every decision input, intermediate score, and rationale must be reproducible months later.
- Latency: end-to-end agent processing for a standard application has a target SLA inside the underwriter's working session — no waiting overnight for the agent to finish.
- Volume: 20K+ daily loan transactions across the small business book.
- Cost: must be defensible against the alternative of hiring more underwriters; cost per processed application is a tracked metric.

## 5. Architecture

```
Application intake event
         │
         ▼
   Step Functions orchestration ──── (durable, observable, retryable)
         │
         ├──▶ Document Parsing Agent
         │      - intake docs from Doc 02 pipeline
         │      - structured extraction (tables, signatures, dates)
         │      - flags missing/illegible documents
         │
         ├──▶ Regulatory Validation Agent
         │      - KYC, sanctions, AML screening
         │      - jurisdiction-specific disclosure check
         │      - retrieves policy via Doc 03 RAG
         │
         ├──▶ Risk Scoring Agent
         │      - calls SageMaker risk models
         │      - augments with retrieved policy context
         │      - produces score + explanation
         │
         └──▶ Decision Synthesis Agent
                - assembles decision package
                - identifies points of judgment for human
                - prepares HITL escalation payload
                       │
                       ▼
            Underwriter HITL queue ─── human decision ──▶ LOS commit
                       │
                       └─── feedback loop into eval / retraining
```

The orchestrator is **Step Functions**, not an in-process agent loop. The agent framework (LangChain + CrewAI) handles the *intra-agent* reasoning; Step Functions handles the *inter-agent* workflow.

## 6. Key Design Decisions

### 6.1 Orchestration outside the agent framework

This is the most consequential decision in the design.

CrewAI and LangChain both support multi-agent workflows in-process. We chose to orchestrate at the Step Functions layer instead. Reasons:

- **Durability.** A long-running underwriting workflow that crashes mid-execution must resume, not restart. Step Functions execution state is durable; an in-process Python agent loop is not.
- **Observability.** Every state transition is visible in the Step Functions console. With an in-process loop, observability is whatever you build into your logging.
- **Retry semantics.** Per-step retry policy with exponential backoff and dead-letter queues comes for free. In-loop, you build it yourself and probably get it wrong.
- **Cost containment.** A runaway agent loop in-process can spend unbounded model tokens before anyone notices. Step Functions enforces step-level timeouts and per-execution caps as a hard wall.
- **Polyglot future.** Today every agent is Python. We did not want the orchestration layer to assume that forever.

The downside is that agent-to-agent messages flow through Step Functions state rather than in-process objects, which adds serialization overhead. We accepted this and tuned payload sizes to keep state under limits.

### 6.2 A2A communication is structured, not free-form text

Agents communicate via well-typed message schemas, not natural language summaries. The Document Parsing Agent emits a `ParsedApplication` object with named fields; the Regulatory Validation Agent consumes it and emits a `ValidationResult` with explicit pass/fail per check.

Free-form text handoff between agents was tempting (and is the default in some frameworks). We rejected it because:

- Downstream agents had to re-parse the previous agent's prose, which was both expensive and error-prone.
- Auditing required re-reading prose to figure out what actually happened. Structured messages are auditable by inspection.
- Schema evolution is manageable; "the previous agent's prose changed slightly" is not.

The agents *think* in natural language (that's what LLMs do); they *communicate* in structured types.

### 6.3 SageMaker risk model is a tool, not an agent

Risk scoring is a domain where the bank has invested in classical ML models for years. Those models are validated, monitored, and well-understood. The Risk Scoring Agent does not *replace* them — it *invokes* them as a tool, then enriches the result with policy context retrieved from the RAG layer.

This was a values decision as much as a technical one. The bank's model risk management framework knows how to govern a SageMaker model. It does not (yet) know how to govern an LLM that produces a risk score. By keeping the model where it was and using the LLM for orchestration, retrieval, and explanation, we stayed inside the existing governance regime.

### 6.4 Human-in-the-loop is the destination, not the exception

Every workflow ends at an underwriter review queue. The agents do not "approve" anything. What they produce is a decision-ready package: extracted data, validation results, risk score with rationale, retrieved policy citations, and an explicit list of points the human should focus on ("this applicant has X which is unusual; flag Y triggered; recommend Z").

Counterintuitive observation: making the human handoff *richer* did more for cycle time than removing the human from the loop would have. The 48-hour-to-under-6-hour win came from underwriters spending their time on judgment instead of on assembly.

### 6.5 Escalation is graduated, not binary

Three escalation tiers:

- **Standard** — clean application, all checks pass, package goes to standard underwriter queue.
- **Attention** — one or more soft flags (atypical financials, edge-case structure), package goes to standard queue but flags are highlighted.
- **Senior review** — hard flags (high-risk jurisdiction, concentration policy concern, KYC ambiguity), package routes to senior underwriter queue with the agent's specific concerns surfaced.

Routing logic lives in the Decision Synthesis Agent and is itself auditable.

### 6.6 The decision package is the artifact of record

The artifact persisted to durable storage is not "the agent's output" — it is the full decision package: every input, every retrieval, every model call, every intermediate score, every prompt, every model version. Reproducibility is non-negotiable.

This is expensive in storage. We accepted the cost because the alternative — being unable to reconstruct an agent decision under regulatory inquiry — was unacceptable.

### 6.7 Framework selection: LangChain *and* CrewAI, deliberately

Not redundancy. LangChain is used for the *tool-using* agents (Document Parsing, Regulatory Validation) where the strength is the breadth of tool integrations and prompt utilities. CrewAI is used where multi-agent role specialization with defined responsibilities mapped naturally onto the team metaphor (the synthesis stage, where multiple specialist sub-agents contribute to one assembled output).

We could have done everything in either framework. The cost of using both was a slightly larger surface area to maintain; the benefit was using each for what it does best.

## 7. Alternatives Considered

| Option | Why rejected |
|---|---|
| Single monolithic agent doing all stages | Hit context window limits on real applications; failure isolation impossible (one stage's bad output corrupts everything downstream); no way to scale horizontally per stage. |
| In-process LangGraph orchestration instead of Step Functions | Reasonable choice for smaller scale, but lost the durability and observability properties we needed at production volume. Cost of building those properties ourselves outweighed the simplicity. |
| End-to-end auto-approval (no HITL) for clean applications | Regulatory and reputational risk untenable in v1. May revisit selectively later, but the HITL path was the right answer for launch. |
| Replace the SageMaker risk model with LLM-as-judge | Model governance burden was not worth taking on simultaneously with a new architecture. Decoupled the risk-model conversation from the agent-platform conversation deliberately. |
| Streaming agent responses to the underwriter UI | UX-attractive but complicates auditability (what was committed vs. what was shown intermediate); deferred. |

## 8. Risks & Mitigations

- **Risk:** Agent makes a subtle but material error that the human approves without noticing.
  **Mitigation:** Decision package highlights anomalies and forces explicit acknowledgment of flagged items; sample-based audit of approved packages cross-checks for missed flags.
- **Risk:** Cost spike from agent loops in unusual application shapes.
  **Mitigation:** Per-step timeouts, per-execution token budget enforced by the orchestrator, alerting on outliers.
- **Risk:** Model drift over time degrades scoring or extraction quality.
  **Mitigation:** Continuous eval framework (see Doc 06) running against a streaming sample; regression alerts.
- **Risk:** Policy retrieval miss leads to applying superseded policy.
  **Mitigation:** Currency filtering at retrieval (Doc 03); decision package surfaces *which* policy version was applied so the human can verify.
- **Risk:** A2A schema drift breaks downstream agents silently.
  **Mitigation:** Schemas are versioned; consumers assert expected version and fail loudly on mismatch rather than coercing.

## 9. Outcomes

- Daily processing volume of 20K+ loan transactions sustained.
- Median underwriter decision time reduced from 48 hours to under 6 hours.
- Pattern (Step Functions + agent steps + structured A2A + HITL) adopted as the bank's reference architecture for subsequent agentic workflows.

## 10. What I'd Do Differently

- Invest in the structured A2A schema before the first agent. We discovered the right shape by iterating; should have spec'd it up front and saved rework.
- Build the decision-package replay tool early. Being able to re-run a historical decision against a new agent version is essential for safe rollout, and we built it after the fact.
- Make the HITL UI a first-class part of the design, not a downstream consumer. Underwriter feedback should flow back into the agent training and prompting loop with low friction; we under-invested in this initially.

## 11. Future Work

- Selective auto-approval for narrow, low-risk segments (with explicit governance approval and a controlled rollout).
- Customer-facing agent for application status and document collection (folds back into Doc 01's Connect/Lex foundation).
- Cross-product reuse of the agent platform for other lending products.
- Active learning loop — use HITL decisions and underwriter overrides as a structured feedback signal to improve agent prompts and tool usage over time.
