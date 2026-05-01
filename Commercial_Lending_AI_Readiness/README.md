# Commercial Lending AI Readiness — End-to-End Showcase

A production-pattern Python project demonstrating end-to-end AI readiness for commercial lending systems. Showcases the full pipeline from raw data assessment through agentic tool use, using AWS-native patterns (S3, Glue, Bedrock) with a fully runnable local mode.

## What This Demonstrates

| Pillar | What It Shows |
|--------|--------------|
| **1. Data Readiness Assessment** | Weighted rubric engine evaluating CRM, document repositories, and compliance databases for AI agent consumption. Surfaces CRITICAL/WARN findings that block or degrade RAG quality. |
| **2. S3/Glue Ingestion Pipeline** | boto3 multipart upload with content-addressed keys (`lending-docs/{year}/{month}/{doc_type}/{doc_id}`), AWS Glue Data Catalog registration, and idempotent re-ingestion. |
| **3. Metadata Tagging Strategy** | Three-pass auto-tagger (regex → TF-IDF keywords → Claude fallback) producing regulation refs, loan type tags, risk tier, version, and S3 object tags across 100K+ documents. |
| **4. Knowledge Base Structuring** | HYBRID chunking (semantic section split + fixed overlap for large sections), deterministic embeddings locally or Amazon Titan via Bedrock, SQLite-backed vector store. |
| **5. RAG Retrieval** | Query expansion → embed → over-fetch → MMR rerank with metadata boosts (risk tier, recency). XML-tagged context assembly for Claude prompts. |
| **6. Agent Tool Use** | `LendingComplianceAgent` using Anthropic `tool_use` API with 4 tools: KB search, CRM lookup, compliance rules, DSCR/LTV calculator. Agentic loop with source citation enforcement. |

## Architecture

```
amazon_agentic_ai/
├── config/                 # Settings, boto3 session factory
├── data/seed/              # Sample policy documents (CRE, SBA, ECOA, BSA, C&I)
├── db/                     # SQLite schema + seed data (CRM, compliance rules, KB)
└── src/
    ├── assessment/         # Pillar 1: Data readiness checks by domain
    │   └── checks/         # crm_checks, document_checks, compliance_checks
    ├── ingestion/          # Pillar 2: S3 uploader, Glue catalog, pipeline orchestrator
    ├── metadata/           # Pillar 3: DocumentMetadata schema, auto_tagger
    ├── knowledge_base/     # Pillar 4: Chunker, embedder, vector store, indexer, Bedrock KB
    ├── retrieval/          # Pillar 5: Query pipeline, MMR reranker, context builder
    └── agent/              # Pillar 6: Claude agent, tool registry, 4 tools
        └── tools/
scripts/
├── bootstrap.py            # One-shot: init DB → seed → ingest → index
└── run_demo.py             # End-to-end showcase demo
```

## Quick Start

```bash
# Install dependencies
pip install anthropic boto3 python-dotenv

# Copy and edit environment config
cp .env.example .env
# Add your ANTHROPIC_API_KEY for the live agent demo (optional for pillars 1-5)

# Initialize everything
python scripts/bootstrap.py

# Run the full showcase
python scripts/run_demo.py
```

## AWS Integration

The project runs locally by default (SQLite + local filesystem). Set flags in `.env` to activate real AWS services:

```bash
USE_REAL_S3=true           # boto3 multipart upload to S3
USE_REAL_GLUE=true         # Glue Data Catalog registration
USE_BEDROCK_EMBEDDINGS=true # Amazon Titan Embed v2 (1536-dim)
USE_BEDROCK_KB=true         # Amazon Bedrock Knowledge Base retrieve() API
```

### S3 Key Strategy
```
s3://{bucket}/lending-docs/{year}/{month}/{doc_type}/{doc_id}.{ext}
```
Object tags carry metadata for server-side filtering without reading file content.

### Glue Catalog Schema
`lending_catalog.policy_documents` — Athena-queryable table over the S3 prefix, enabling SQL queries across 100K+ ingested documents.

### Bedrock Knowledge Base
See `src/knowledge_base/bedrock_kb.py` for the production `retrieve()` pattern with hybrid (semantic + keyword) search and metadata filtering.

## Assessment Scoring

The **AI Readiness Index** (0–100) is a weighted composite:

| Domain | Weight | Key Dimensions |
|--------|--------|----------------|
| CRM | 35% | Completeness, KYC coverage, OFAC freshness, AML consistency |
| Documents | 40% | Format parseability, regulation tag coverage, version currency |
| Compliance | 25% | Regulation coverage, rule completeness, effective dates |

**CRITICAL findings cap the domain score at 40** regardless of other checks — ensuring blockers are surfaced even when most metrics are healthy.

## Chunking Strategy

`HYBRID` mode (default):
1. **Semantic split** on section headers (`## 3.1 DSCR Requirements`, `1.2 Eligible Uses`, etc.)
2. If a section > 600 tokens: **fixed split** with 64-token overlap within that section
3. Each `Chunk` carries full `DocumentMetadata` (regulation_refs, loan_types, risk_tier) for metadata-filtered retrieval

## Agent Tool Use

The `LendingComplianceAgent` follows the standard Anthropic `tool_use` agentic loop:

```python
client = anthropic.Anthropic(api_key=...)
agent = LendingComplianceAgent(client)
result = agent.run(
    "Is borrower CUST-001 eligible for a $1.5M C&I loan? "
    "NOI $187,500, annual debt service $162,000, collateral $1.8M."
)
```

The agent autonomously:
1. Calls `lookup_borrower_crm` → surfaces KYC/AML status
2. Calls `check_compliance_rules(ECOA)` → verifies no fair lending blockers
3. Calls `query_policy_knowledge_base` → retrieves C&I underwriting standards
4. Calls `compute_dscr_ltv` → calculates 1.16x DSCR, 83.3% LTV, compares to policy
5. Returns a sourced analysis with conditions and human-review requirement

## Key Design Decisions

- **No LLM dependency for tagging**: regex + TF-IDF handles >95% of documents; Claude fallback only for ambiguous cases
- **Content-addressed IDs**: `doc_id = SHA-256(content)[:16]` — identical documents deduplicated automatically
- **MMR reranking**: λ=0.7 balances relevance vs diversity; same-document chunk penalty forces result diversity
- **Compliance-first system prompt**: agent always checks AML/OFAC before credit analysis
- **Human-in-the-loop**: system prompt enforces that all credit decisions require licensed officer review

## Data Model

8 commercial lending borrowers (CRM), 5 loan applications (SBA, CRE, C&I, construction), 10 compliance rules across ECOA / BSA / AML / SBA / CRA / TILA / OFAC, 7 policy documents (91 chunks after HYBRID chunking).
