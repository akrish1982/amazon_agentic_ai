# Design Document: Cloud-Native Data Lakehouse

**REDACTED** Bank
**Author:** Ananth — Senior Data Architect, AWS
**Status:** Delivered — production single source of truth for analytics & ML
```
NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.
```

---

## 1. Context & Problem Statement

**REDACTED**'s analytics and ML estate spanned:

- A legacy on-prem Teradata EDW (system of analytics for finance, risk, regulatory).
- A Hadoop/Hive cluster for "big data" workloads, which had become an operational liability.
- A growing collection of point-solution data marts (SQL Server, Oracle) per line of business.
- Direct connections from data scientists to source OLTP systems (frowned upon, but reality).

This created predictable problems: duplicate definitions of the same KPI, model training sets that didn't match reporting figures, slow feature engineering loops, and no consistent path to land core banking and risk data for ML.

**Goal:** Build a cloud-native lakehouse on AWS that serves as the single source of truth for ML feature engineering and downstream analytics, ingesting **5TB+ daily** from core banking, card, deposits, and risk systems.

**Non-goals (Phase 1):** Decommissioning Teradata; supporting sub-second OLAP queries; replacing operational systems.

---

## 2. Requirements

| Type | Requirement |
|---|---|
| Functional | Daily ingestion from 40+ source systems |
| Functional | ACID semantics for late-arriving data, GDPR/CCPA deletes, schema evolution |
| Functional | Point-in-time correct reads ("what did we know about this customer on 2022-08-14?") |
| Functional | Time travel & rollback for failed pipelines |
| Functional | Both batch and streaming ingestion paths into the same tables |
| Non-functional | 5TB+/day ingestion, with peak hourly bursts of 800GB |
| Non-functional | Query performance: 90% of feature backfills <30 min over 13 months of history |
| Non-functional | Cost: linear scaling with data volume; no over-provisioned reservations |
| Compliance | PII tokenization at landing; row-level security; immutable audit log |

---

## 3. High-Level Architecture

```
                ┌──────────────────────────────────┐
   Sources ───► │  Landing zone (S3 raw, parquet)  │
                └──────────────┬───────────────────┘
                               │
                  ┌────────────┴────────────┐
                  │  Bronze (Delta Lake)    │  ← schema enforced, dedup, PII tokenized
                  └────────────┬────────────┘
                               │
                  ┌────────────┴────────────┐
                  │  Silver (Delta Lake)    │  ← conformed, business keys, SCD2
                  └────────────┬────────────┘
                               │
                  ┌────────────┴────────────┐
                  │  Gold (Delta Lake)      │  ← feature views, semantic layer
                  └────┬─────────┬──────────┘
                       │         │
                  Databricks   Athena / Redshift Spectrum / SageMaker
```

Three storage zones, all on S3 with Delta Lake table format. Compute is Databricks for transformations and SageMaker/Athena for consumption.

---

## 4. Key Design Decisions

### 4.1 Table format: Delta Lake (vs. Iceberg vs. Hudi vs. plain Parquet)

**Decision:** Delta Lake.

**Alternatives considered:**

| Option | Strengths | Why not chosen |
|---|---|---|
| Plain Parquet + Glue Catalog | Simple, open | No ACID, no upserts, painful late-arriving data |
| Apache Hudi | Strong CDC story, copy-on-write & merge-on-read | Operational complexity higher in 2021–2022; smaller AWS-native ecosystem |
| Apache Iceberg | Open governance, hidden partitioning, EMR/Athena/Trino support | In 2022 the Databricks-native experience for Iceberg was weaker; merge performance lagged |
| **Delta Lake (chosen)** | Best-in-class Databricks integration, mature MERGE, OPTIMIZE/Z-ORDER, time travel | Tighter coupling to Databricks (acceptable given Databricks was the chosen compute) |

**Reasoning:**

- Databricks was already the chosen compute platform (decision driven by team skillset and a pre-existing enterprise agreement). Delta was the path of least friction.
- The MERGE INTO performance for upserts on large tables was material: silver-layer SCD2 jobs that would have taken 90+ minutes in Iceberg-on-EMR completed in 18–25 minutes on Delta.
- Time travel was non-negotiable for ML reproducibility. All three formats support it; Delta's was the most ergonomic.

**What I'd reconsider today (2026):** Iceberg's ecosystem has matured significantly; for a green-field design today I'd revisit. The decision was correct in 2022.

### 4.2 Medallion architecture (Bronze / Silver / Gold)

**Decision:** Three-tier medallion with explicit contracts between tiers.

**Reasoning:**

- **Bronze** is the immutable raw landing — mirrors the source system, including bad records. Lets us replay any downstream layer without re-reading source systems.
- **Silver** applies dedup, type casting, business keys, SCD2 history, and PII tokenization. This is the "trustworthy historical truth" layer.
- **Gold** is purpose-built for consumers — feature views for ML, dimensional models for BI. Multiple gold tables can derive from the same silver tables with different grain.

**Contracts between tiers:** Schema, freshness SLA, and quality expectations are codified in YAML and enforced by Great Expectations checks gated on pipeline progression. A silver table cannot publish if it fails its data quality contract; bronze keeps flowing.

### 4.3 Ingestion: DMS for relational, Kafka for events, Glue for files

**Decision:** No single ingestion framework — pick the right tool per source class.

| Source class | Tool | Why |
|---|---|---|
| Oracle / SQL Server / DB2 (CDC) | AWS DMS → S3 → Delta MERGE | Mature, log-based CDC; doesn't load source systems |
| Kafka topics (real-time events) | Spark Structured Streaming (Databricks) | See streaming design doc |
| Mainframe extracts (flat files) | Glue jobs | Simple file landing, schedule-driven |
| SaaS APIs (Salesforce, ServiceNow) | Fivetran → S3 | Buy vs. build: connector maintenance is a tax we don't want |

**Reasoning:** Insisting on a single tool is a common architectural failure mode — you end up using a hammer for screws. Each tool here is the strongest for its class, and they all converge on the bronze layer.

### 4.4 Partitioning & layout

**Decision:**

- **Bronze:** partition by `ingestion_date`. Append-only.
- **Silver:** partition by **business event date** (e.g., `transaction_date`), with Z-ORDER on `customer_id` and the join keys most-used downstream.
- **Gold:** partition driven by the consumer's access pattern; many gold tables are partitioned by `as_of_date` for point-in-time queries.

**Reasoning:**

- Partitioning by ingestion_date in bronze makes replay trivial and avoids the small-files problem at landing.
- Switching to event-date in silver aligns physical layout with how analysts and ML pipelines query.
- Z-ORDER on join keys cut downstream query I/O by 60–80% for the common access patterns; the cost is OPTIMIZE jobs, run nightly.

### 4.5 PII handling

**Decision:** Format-preserving tokenization at the bronze→silver boundary using a centralized vault. Silver and gold contain only tokens; reverse mapping requires explicit, audited access.

**Reasoning:**

- ML feature engineering rarely needs raw PII; tokens are sufficient as join keys.
- Centralizing the vault avoids per-pipeline custom logic and prevents accidental leaks.
- Format-preserving (vs. random tokens) keeps downstream type checks and length-dependent logic working without modification.

### 4.6 Late-arriving data & SCD2

**Decision:** Silver dimension tables modeled as SCD Type 2 with `valid_from`, `valid_to`, `is_current`. Late-arriving facts re-open the appropriate dimension version and write at the historically correct version key.

**Reasoning:** Risk and finance routinely receive corrections 30–90 days after the fact. ML training sets must reflect "what we knew at the time" — not the corrected truth, otherwise we leak future information into training. SCD2 + point-in-time joins is the standard solution.

### 4.7 Streaming and batch into the same tables

**Decision:** Both paths write to the same Delta tables using `MERGE INTO` for streaming and structured writes for batch. Streaming for fraud-relevant tables; batch for everything else.

**Reasoning:** Avoids the lambda architecture problem of two parallel codebases. Delta's ACID guarantees make concurrent streaming and batch writes safe with proper isolation levels.

### 4.8 Catalog, lineage, and discovery

**Decision:** Unity Catalog (Databricks) as the primary catalog, with metadata also published to Glue Catalog for Athena/Redshift Spectrum interoperability.

Lineage captured automatically by Databricks for SQL/Notebook workflows; supplemented by OpenLineage emitters for Spark jobs.

**Reasoning:** Two consumer audiences — data scientists in Databricks notebooks, and analysts/BI in Athena — needed catalog visibility. Dual publication was less effort than forcing one audience onto the other's tool.

---

## 5. Trade-offs Accepted

- **Vendor coupling to Databricks.** Delta + Unity Catalog deepen this. Acceptable given organizational commitment, but documented as a risk.
- **Storage cost duplication.** Bronze + silver + gold means we hold the same logical data 2–3 times. Lifecycle policies move bronze to S3-IA after 30 days and Glacier after 180. Net storage cost remained <8% of total platform cost.
- **Schema evolution discipline.** Delta supports schema evolution but allowing it freely creates archaeology problems. We require explicit, reviewed schema-change PRs for silver and gold; bronze allows additive evolution automatically.

---

## 6. Outcome

- 5.4 TB average daily ingestion sustained, with 9 TB peak days during month-end risk reporting cycles.
- 40+ source systems integrated.
- Designated single source of truth for ML feature engineering across the bank.
- Average backfill time over 13 months of history: 21 minutes (vs. 4–8 hours on the legacy stack).

---

## 7. What I'd Reconsider

- Should have invested in a formal data contract framework earlier instead of tribal-knowledge YAML.
- Underestimated the political work of getting source-system owners to commit to schema-change SLAs. Architecture was easy; governance was the hard part.
- Would evaluate Iceberg seriously for a 2026 redesign, especially given AWS S3 Tables.
