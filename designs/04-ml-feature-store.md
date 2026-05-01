# Design Document: ML Feature Store

**REDACTED** Bank
**Author:** Ananth — Senior Data Architect, AWS
**Status:** Delivered — 12+ models in production using shared features
```
NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.
```

---

## 1. Context & Problem Statement

Before this initiative, every ML team at **REDACTED** built features in isolation. Common consequences:

- The same feature ("90-day average daily balance") was implemented 4–6 times with subtly different definitions (calendar days vs. business days; including pending vs. posted; per-account vs. per-customer).
- Each model team spent 40–60% of project time on feature engineering rather than modeling.
- No way to know which features were actually being used in production, or by which models.
- Training-serving skew was endemic: features computed by Spark batch jobs at training time were re-implemented by application code at scoring time, with predictable drift.
- Audit and model-risk teams had no canonical answer to "what is the definition of feature X used by model Y on date Z?"

**Goal:** Implement an ML feature store that standardizes feature definitions, enables reuse across models, and reduces feature engineering lead time across all in-scope ML initiatives.

**Non-goals:** Building a custom feature store; supporting non-ML analytics use cases; mandating feature store usage for prototype/research work.

---

## 2. Requirements

| Type | Requirement |
|---|---|
| Functional | Single canonical definition per feature, versioned and discoverable |
| Functional | Both offline (training) and online (inference) retrieval from same definition |
| Functional | Point-in-time correct training data generation |
| Functional | Feature lineage: which raw tables, which transformation, which job |
| Functional | Access controls per feature group |
| Non-functional | Online retrieval p99 < 50ms |
| Non-functional | Offline backfill of 18 months of features for a model in <2 hours |
| Compliance | SR 11-7 model risk: feature definitions immutable once a model goes to production using a specific version |

---

## 3. High-Level Architecture

```
                Feature definitions (Python, in Git)
                            │
                ┌───────────┴───────────┐
                │                       │
     Offline materialization      Online materialization
     (Spark/Databricks)           (Streaming → Online store)
                │                       │
                ▼                       ▼
     S3 + Delta (offline store)   DynamoDB (online store)
                │                       │
                └───────────┬───────────┘
                            │
                  SageMaker Feature Store
                  (metadata, governance,
                   point-in-time joins)
                            │
                            ▼
                  Training pipelines / Inference services
```

---

## 4. Key Design Decisions

### 4.1 Build vs. buy: SageMaker Feature Store, not custom

**Decision:** SageMaker Feature Store as the system of record.

**Alternatives considered:**

| Option | Why not chosen |
|---|---|
| Feast (open source) | Strong, but operational ownership of online store, registry DB, and serving layer was overhead we didn't want |
| Tecton | Excellent product, but commercial SaaS in a regulated environment had procurement friction |
| Databricks Feature Store | Tied tightly to Databricks; we wanted online serving outside Databricks for SageMaker-hosted models |
| Custom on DynamoDB + S3 | We could build it. We shouldn't. |
| **SageMaker Feature Store (chosen)** | Native AWS, integrated with SageMaker training/inference, manages online + offline stores, point-in-time joins out of the box |

**Reasoning:**

- SageMaker hosting was the existing model-serving platform. SageMaker Feature Store integrates natively — feature retrieval at inference time is a one-line SDK call.
- Online (DynamoDB) and offline (S3 + Glue) stores are managed; we don't operate them.
- Point-in-time joins are first-class, which avoided a category of bug we'd seen on prior projects.

**Trade-offs:**

- Less feature flexibility than Feast (e.g., custom transforms at retrieval time are limited). Acceptable; we pushed transforms upstream into materialization jobs.
- Cost of online store scales with row count and read/write volume. Mitigated by feature group TTLs on rarely-queried features.

### 4.2 Feature definition as code

**Decision:** Every feature is defined in a Python module, in Git, with the schema:

```python
@feature(
    name="customer_90d_avg_daily_balance",
    entity="customer_id",
    dtype=Decimal,
    owner="risk-modeling-team",
    sla_freshness="P1D",
    pii=False,
    description="90-day average daily ending balance across all deposit accounts",
)
def transform(spine: DataFrame, deposits: DataFrame) -> DataFrame:
    ...
```

CI/CD validates: schema correctness, owner exists, description is non-empty, no name collisions, transformation passes unit tests.

**Reasoning:**

- Definitions in code are reviewed via PR. No ad-hoc feature creation; every feature has an owner and a description before it lands in the registry.
- Same Python module is imported by both offline materialization (Spark job) and online materialization (streaming job). One source of truth.
- Renaming or changing semantics requires a new feature name + version — old consumers continue using the old definition until they migrate.

### 4.3 Online vs. offline store consistency

**Decision:** Online store is updated by the streaming pipeline. Offline store is updated by:

1. Mirror writes from streaming (so online and offline stay near-aligned), AND
2. A nightly batch job that re-derives offline features from the lakehouse silver layer.

When the nightly job's value differs from the streaming-mirrored value beyond tolerance, the batch value wins, and an alert fires for investigation.

**Reasoning:**

- Online store must be fast and fresh; streaming is the right path.
- Offline store must be **complete and correct** for training set generation, which is more important than fresh.
- Nightly reconciliation catches streaming-job bugs and replay scenarios that would otherwise silently drift.

### 4.4 Point-in-time correctness

**Decision:** All training set generation goes through SageMaker Feature Store's `create_dataset` API with explicit event-time joins, never via direct SQL on offline parquet.

**Reasoning:** The most common silent ML bug at financial-services clients I've seen: training labels include information that wasn't actually known at the time of the prediction. SageMaker Feature Store enforces "as-of" joins at the API level. Discipline at the architecture level beats discipline at the individual-engineer level.

### 4.5 Feature groups and ownership

**Decision:** Features grouped by entity + domain + owner. Examples:

- `customer_balance_features` (entity: customer_id, owner: deposits team)
- `card_transaction_velocity_features` (entity: card_id, owner: fraud team)

Each feature group has an owning team in the catalog. Cross-team consumption is allowed; cross-team modification requires owner approval.

**Reasoning:** Reuse without governance produces "feature stew" — nobody knows who owns what, deprecation never happens. Explicit owners enabled deprecation: features below a usage threshold for 90 days are flagged for retirement.

### 4.6 Versioning and immutability

**Decision:** Once a model registered in the model registry references a feature version, that version is immutable in the feature store. New definitions create new versions; old versions are retained at minimum until no production model references them.

**Reasoning:** SR 11-7 model risk management is unambiguous: model behavior must be reproducible. If feature definitions silently change underneath a deployed model, the model's behavior changes without re-validation. Immutability of referenced versions is the architectural guarantee that prevents this.

### 4.7 Discovery and reuse

**Decision:** A web UI (built on top of the SageMaker Feature Store APIs) exposes:

- All feature groups, their owners, descriptions, and SLAs.
- Usage telemetry: which models use which features in production.
- Search by name, entity, owner, tag.
- "Models using this feature" reverse lookup.

**Reasoning:** A feature store nobody can discover is a feature store nobody reuses. Discovery UX was a meaningful driver of the 35% lead-time reduction — data scientists could find existing features in 2 minutes instead of asking around for 2 days.

---

## 5. How the 35% Lead-Time Reduction Was Achieved

Approximate decomposition based on time-tracking before/after:

| Source of savings | Contribution |
|---|---|
| Reuse: existing features found via discovery UI rather than re-built | ~12% |
| Eliminating online/offline parity work (single definition) | ~9% |
| Faster training-set generation (point-in-time API vs. ad-hoc SQL) | ~7% |
| Reduced rework from training-serving skew bugs caught in production | ~5% |
| Faster feature-engineering review cycles (standardized PR template) | ~2% |

The point: it wasn't one thing. The feature store paid off in many small ways simultaneously, which is why a 35% reduction was achievable in aggregate.

---

## 6. Trade-offs Accepted

- **SageMaker lock-in.** All feature retrieval goes through AWS SDKs. Acceptable given the broader AWS commitment; documented as a strategic risk.
- **Initial migration cost.** Existing models had features re-implemented and validated for parity before cutover. ~3 weeks per model on average. Front-loaded cost for long-term gain.
- **Discipline tax.** Adding a feature now requires a PR with description, owner, SLA — slower than ad-hoc Spark notebook work. Right call: the slower path produces shared assets; the fast path produced unmaintainable sprawl.

---

## 7. Outcome

- 12+ production models migrated to the feature store as primary feature source.
- ~110 canonical features across 9 feature groups.
- 35% reduction in feature engineering lead time, measured across model launches before/after rollout.
- Zero production incidents traceable to feature-definition drift in the 9 months following stabilization (vs. 4 such incidents in the 9 months prior).

---

## 8. What I'd Reconsider

- Should have invested in feature monitoring (drift detection on inputs, not just outputs) earlier. Built it in v1.5; should have been v1.0.
- Online TTL policy was too generous initially — DynamoDB costs spiked. Tightened later.
- "Sandbox" feature group for prototype features turned into a graveyard. A 90-day auto-expiry from day one would have prevented sprawl.
