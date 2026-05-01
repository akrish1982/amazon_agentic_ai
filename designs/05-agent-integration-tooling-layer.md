# Design Doc: Agent Integration & Tooling Layer

**Status:** Production
**Domain:** Platform Engineering / Agentic AI Infrastructure
**Stack:** AWS Lambda, AWS Step Functions, Amazon API Gateway, custom control-plane abstractions (MCP-aligned), AWS IAM

---

## 1. Context

Agents are only as useful as the tools they can call. The agentic underwriting platform (Doc 04) needed reliable, governed access to core banking systems: the loan origination system, customer CRM, compliance databases, document repositories, sanction screening services, and risk modeling endpoints.

Each of these systems had:
- A different authentication model (mTLS, OAuth, API keys, IAM, SOAP with WS-Security in one notable case).
- A different rate limit posture.
- A different failure-mode vocabulary.
- A different team's on-call rotation behind it.

Without an integration layer, every agent would have had to know about every system — and every change to a downstream system would have rippled into every agent. That coupling would have killed the platform.

This document covers the layer that sits between agents and core banking systems: how tools are exposed, how they are governed, and how the abstractions are designed so that adding a new tool is a small, predictable amount of work.

## 2. Goals

- Give agents a uniform way to discover, invoke, and reason about tools.
- Decouple agents from the specifics of each downstream system.
- Make tool exposure governable — auth, audit, rate limits, entitlement, and circuit breaking enforced consistently.
- Make the cost of adding a new tool small and the cost of changing an existing tool localized.
- Support the same tool surface for different agent runtimes (LangChain agents, CrewAI agents, future runtimes).

## 3. Non-Goals

- Not a replacement for any system of record. The integration layer is a proxy and policy enforcement point, not a source of truth.
- Not a public API platform. This serves internal agents, not external developers; the design tradeoffs are different.
- Not a workflow orchestrator (that is Step Functions in Doc 04). This layer is below orchestration; it is the *tool layer*.

## 4. Constraints

- Every tool invocation must be auditable end-to-end: who called what, with what arguments, what came back.
- No tool may be invokable without an entitlement check appropriate to the calling context (which agent, on whose behalf).
- Latency overhead added by the integration layer must be small — agents are already slow enough.
- Failure of any single downstream system must not cascade into other tools or other agents.

## 5. Architecture

```
            ┌───────────────────────────────────────────┐
            │  Agent (LangChain / CrewAI / other)       │
            └─────────────────────┬─────────────────────┘
                                  │
                  Tool descriptor + arguments (typed)
                                  │
                                  ▼
            ┌───────────────────────────────────────────┐
            │  Control Plane (MCP-aligned)              │
            │  - tool registry + discovery              │
            │  - auth context resolution                │
            │  - entitlement enforcement                │
            │  - rate limit + circuit breaker           │
            │  - audit log (every call, every response) │
            │  - response shaping + error normalization │
            └─────────────────────┬─────────────────────┘
                                  │
              ┌───────────┬───────┴───────┬───────────┐
              ▼           ▼               ▼           ▼
            Lambda      Lambda          Lambda      Lambda
        (LOS adapter) (CRM adapter)  (KYC adapter) (...)
              │           │               │           │
              ▼           ▼               ▼           ▼
       Loan Origination  CRM     Compliance / KYC   ...
```

### The control plane is a thin, opinionated layer

The control plane does not transform business logic — it normalizes the operational concerns that every tool call shares: identity, entitlement, rate limiting, retry, audit, error classification.

Each tool is implemented as a Lambda adapter behind the control plane. The adapter knows one thing: how to talk to one downstream system. It does not know about agents, prompts, or other tools.

## 6. Key Design Decisions

### 6.1 MCP-style control plane abstraction

The Model Context Protocol pattern — a standard contract for how agents discover and invoke tools — was a natural fit even where we were not using the literal MCP protocol. We adopted MCP-aligned conventions:

- Each tool publishes a typed descriptor: name, description, input schema, output schema, side-effect classification (read / write / external-side-effect).
- Discovery is a control-plane operation, not a hardcoded list inside each agent.
- Invocation is uniform: the agent supplies tool name and arguments; the control plane resolves the adapter, enforces policy, invokes, and returns a normalized response.

The reason for this shape is straightforward: it standardizes the most variable part of the agent ecosystem. Agents come and go; agent frameworks come and go; tools come and go. A stable contract between them means each can evolve without breaking the others.

### 6.2 Side-effect classification is mandatory metadata

Every tool declares whether it is `read`, `write`, or `external_side_effect` (e.g., sends a notification, triggers a downstream workflow). This metadata is consumed by:

- **The agent** — read tools are safe to retry, write tools are not, external-side-effect tools require explicit confirmation in some workflows.
- **The control plane** — write and external-side-effect tools have stricter audit and entitlement requirements.
- **The HITL layer** — tools with side effects above a threshold may require human confirmation before invocation.

This is unglamorous. It is also what makes the platform safe.

### 6.3 Auth context flows from the calling workflow, not from the agent

Agents do not hold credentials. The calling workflow (Step Functions execution in Doc 04) carries an auth context that names the originating principal, the customer scope, and the entitlements granted for this execution. The control plane resolves this context at invocation time and enforces it.

This means an agent cannot escalate its own privileges by deciding to call a more powerful tool. The tools available to it are bounded by the auth context handed to it by the workflow.

### 6.4 Error normalization is a feature, not an afterthought

Downstream systems return errors in wildly different vocabularies: HTTP status codes, SOAP faults, custom error envelopes, free-form text. The control plane normalizes every response into a common error taxonomy: `transient`, `permanent`, `not_found`, `unauthorized`, `rate_limited`, `bad_input`, `degraded`.

Agents reason about this taxonomy, not about the underlying systems. A `transient` error is retryable; a `bad_input` error is not; a `degraded` error means the agent should consider whether to proceed with partial data or escalate. This frees agents from learning the idiosyncrasies of every backend.

### 6.5 Per-tool rate limits and circuit breakers

Each adapter declares its rate limit posture. The control plane enforces it. When a downstream system starts failing or slowing, the circuit breaker opens for that tool — agents calling that tool get a fast `degraded` response and can adapt, while other tools and other agents are unaffected.

The design principle: **failure isolation between tools is more important than maximum throughput on any single tool**. A platform that can lose one tool gracefully is more valuable than one that maximizes individual tool performance and cascades on failure.

### 6.6 Audit is structured, complete, and queryable

Every invocation produces a log record with: caller identity, auth context, tool name and version, full arguments, full response (or error), latency, and the workflow execution that triggered it. Logs land in S3 partitioned for cost-efficient query.

Two non-obvious choices:

- We log full arguments and responses, not summaries. Storage is cheap; "we cannot reconstruct what the agent saw" is expensive.
- We log even on failure. Especially on failure. Failed invocations are the most important to understand later.

### 6.7 Adapters are versioned

Each adapter Lambda is versioned. Tool descriptors include the adapter version. When an adapter changes (e.g., the downstream API contract changed), the new version is published alongside the old, agents migrate, and the old version retires on a schedule. We do not edit-in-place adapters that agents depend on.

### 6.8 The control plane is itself a small surface

Resist the temptation to put business logic in the control plane. Keep it about identity, policy, audit, transport, and error normalization. The moment business logic creeps in, the control plane becomes a deployment chokepoint and a source of incidents. We held this line, sometimes uncomfortably.

## 7. Alternatives Considered

| Option | Why rejected |
|---|---|
| Each agent calls downstream systems directly | The coupling problem — every system change ripples into every agent; no consistent audit; no consistent entitlement enforcement; failure isolation impossible. |
| Use a third-party API gateway as the control plane | Gateways do auth, throttling, and routing well. They do not do typed tool descriptors, side-effect classification, agent-aware error normalization, or workflow-scoped auth context. We would have ended up building the agentic concerns on top anyway. |
| Skip MCP-style descriptors; let agents have hardcoded tool lists | Works for two agents and three tools. Falls apart at platform scale. Adding a tool would require touching every agent that might want it. |
| Synchronous in-process tool calls (no network hop) | Faster but couples agent runtime lifecycle to backend availability; cannot enforce centralized policy; cannot version adapters independently of agents. |

## 8. Risks & Mitigations

- **Risk:** Control plane becomes a single point of failure.
  **Mitigation:** Stateless control-plane Lambda fronted by API Gateway, multi-AZ; degradation modes return `degraded` to agents rather than failing closed; runbook tested for control-plane unavailability.
- **Risk:** Audit log volume explodes at scale.
  **Mitigation:** Partitioned S3 layout, lifecycle policies, summary aggregations for high-volume read tools; full payloads retained for retention period required by compliance.
- **Risk:** Adapter sprawl as more tools are added.
  **Mitigation:** Adapter template + scaffolding; new adapters follow a checklist (descriptor, schemas, error mapping, rate limit declaration, audit verification); review gate on additions.
- **Risk:** Entitlement model becomes too complex to reason about.
  **Mitigation:** Entitlements are coarse-grained (workflow-scoped), not fine-grained per-call; complexity capped by design.

## 9. Outcomes

- Agents in Doc 04 invoke core banking systems through one consistent interface, regardless of underlying system idiosyncrasies.
- New tool onboarding is small and predictable.
- Centralized audit satisfies compliance and incident-investigation needs in one place.
- Failure of one downstream system isolates to the affected tool; other agent workflows continue.

## 10. What I'd Do Differently

- Adopt MCP literal protocol from the start where it could have been used. We adopted MCP-aligned conventions but rolled some of our own contract; converging on the protocol earlier would have saved future migration work and benefited from the broader ecosystem.
- Build the adapter scaffolding before the third adapter, not after the fifth. We hand-built the first few and absorbed the cost of inconsistency.
- Treat error taxonomy as a versioned contract from day one. We extended it organically; some agents had to be re-tuned when the taxonomy stabilized.

## 11. Future Work

- Full MCP protocol adoption where the ecosystem makes it useful (e.g., for tools that have third-party MCP server implementations).
- Tool-usage analytics — which agents call which tools how often, with what error rates, at what cost. Some of this exists; better dashboards would inform platform investment decisions.
- Speculative invocation for read tools — when the agent is reasoning about whether to call a tool, pre-warm the call so the latency is hidden.
- Self-describing tools that publish not only schemas but example invocations and common failure modes, consumable directly by the agent's reasoning prompt.
