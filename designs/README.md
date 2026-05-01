# Agentic AI Platform — Design Doc Set

This set of design documents covers the architecture decisions, tradeoffs, and outcomes of an agentic AI platform built for commercial small-business lending in a large bank context. Each doc is self-contained but the set tells a layered story: data → retrieval → agents → integration → governance, with a self-service deflection use case as the standalone entry point.

## Reading order

The docs are numbered for layered reading, but each works on its own:

1. **[IVR Self-Service Deflection](01-ivr-self-service-deflection.md)** — Standalone Connect + Lex deflection of routine small-business loan inquiries. Smallest blast radius; first proving ground for "AI in the contact channel."
2. **[Data Foundation & Knowledge Base Readiness](02-data-foundation-kb-readiness.md)** — The unglamorous prerequisite: making 100K+ policy documents and lending data AI-consumable, with metadata that supports entitlement, currency, and provenance. Everything downstream depends on this.
3. **[RAG-Powered Compliance Knowledge Base](03-rag-compliance-knowledge-base.md)** — Bedrock Knowledge Bases + pgvector serving both human Q&A and downstream agents. Where the retrieval-quality and latency wins were earned.
4. **[Multi-Agent Loan Underwriting Platform](04-multi-agent-underwriting-platform.md)** — The flagship use case. Step Functions–orchestrated multi-agent workflow with HITL escalation, cutting underwriter cycle time from 48h to under 6h.
5. **[Agent Integration & Tooling Layer](05-agent-integration-tooling-layer.md)** — The MCP-aligned control plane between agents and core banking systems. Where coupling, governance, and failure isolation are managed.
6. **[AI Governance, Evaluation & Executive Enablement](06-ai-governance-evaluation-executive-enablement.md)** — The pre-production eval framework and the executive roadmap practice that keep the platform safe to ship and funded across budget cycles.

## How the docs relate

```
                 ┌────────────────────────────────────────┐
                 │ Doc 06 — Governance & Eval             │
                 │ (cross-cutting; applies to all below)  │
                 └────────────────────────────────────────┘
                                   │
   ┌───────────────────────────────┼───────────────────────────────┐
   │                               │                               │
   ▼                               ▼                               ▼
Doc 01                         Doc 04                         Doc 05
IVR Deflection                 Multi-Agent                    Tooling Layer
(standalone)                   Underwriting                   (used by Doc 04)
                                   │                               │
                                   ▼                               │
                               Doc 03                              │
                               RAG KB ────────────────────────────┘
                               (used by Doc 04 and standalone Q&A)
                                   │
                                   ▼
                               Doc 02
                               Data Foundation
                               (prerequisite for Doc 03 and Doc 04)
```

## Common conventions across docs

- **Status, domain, stack** at the top of each doc.
- **Goals / Non-Goals / Constraints** before architecture, so the design choices are anchored to what they were optimizing for.
- **Key Design Decisions** with explicit reasoning — including the choices that were counterintuitive or that traded off one good thing for another.
- **Alternatives Considered** in table form — the choices we didn't make are as informative as the ones we did.
- **What I'd Do Differently** section in every doc — the things that were learned the expensive way.

## Notes on the documents

These are written as engineering design documents — the kind that would go into a tech-spec review or a portfolio. They favor reasoning over implementation detail; they assume AWS and agentic AI fluency in the reader. They do not include code samples, IAM policies, or Terraform — those would live in companion implementation docs.
