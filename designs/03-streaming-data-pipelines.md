# Design Document: Real-Time Streaming Data Pipelines

**REDACTED** Bank
**Author:** Ananth — Senior Data Architect, AWS
**Status:** Delivered — production for fraud detection & transaction monitoring
```
NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.
```

---

## 1. Context & Problem Statement

Fraud detection and transaction monitoring models at **REDACTED** were trained on near-real-time data but scored on batch features that lagged 6–24 hours. The result: models technically performant offline, but degraded materially in production because they were scoring against stale features. Card-not-present fraud and account takeover patterns evolve in minutes, not hours.

In parallel, the data science team wanted "feature freshness as a first-class SLA" — the ability to declare that a feature must be no older than N seconds at inference time, and have the platform enforce it.

**Goal:** Build streaming data pipelines that deliver core banking and card events into the lakehouse and the feature store with **sub-second** availability, suitable for online feature lookup at model inference time.

**Non-goals:** Replacing the batch ingestion path; sub-millisecond pipelines (we are not a market-data shop); event sourcing as a pattern for the whole bank.

---

## 2. Requirements

| Type | Requirement |
|---|---|
| Functional | Ingest from 8 high-value event sources (card auth, ACH, wire, online banking, mobile, deposit, debit, alert) |
| Functional | Sub-second end-to-end latency p95 from source publish to feature-store availability |
| Functional | Exactly-once semantics for downstream feature aggregation |
| Functional | Same data also lands in lakehouse Delta tables for offline parity with online features |
| Non-functional | 25k events/sec sustained, 80k events/sec peak |
| Non-functional | Zero data loss; replayability for at least 7 days |
| Non-functional | Schema evolution without consumer downtime |
| Compliance | PCI-DSS scope minimization; PII tokenization in stream |

---

## 3. High-Level Architecture

```
Source systems  ──► Kafka (MSK)  ──► Schema Registry
                          │
                          ├──► Spark Structured Streaming (Databricks)
                          │           │
                          │           ├──► Bronze Delta (raw, 1:1 with topic)
                          │           ├──► Silver Delta (parsed, tokenized, conformed)
                          │           └──► Online feature store (SageMaker Feature Store)
                          │
                          └──► Flink (Kinesis Data Analytics) for sub-second windowed aggregations
                                      │
                                      └──► Feature store online layer
```

Two streaming engines, deliberately. Spark Structured Streaming for lakehouse landing and feature parity (offline + online from the same code). Flink for the latency-critical windowed aggregations that needed lower tail latency than Spark micro-batches could deliver.

---

## 4. Key Design Decisions

### 4.1 Message bus: Amazon MSK (Kafka), not Kinesis Data Streams

**Decision:** Self-managed-ish Kafka via MSK with Schema Registry.

**Alternatives considered:**

| Option | Why not chosen |
|---|---|
| Kinesis Data Streams | Solid AWS-native option, but: 1MB record limit was tight for some payloads; per-shard partition keys gave less flexibility than Kafka's; existing **REDACTED** engineering teams had Kafka skills, not Kinesis |
| MSK Serverless | Promising, but in 2022 throughput limits and partition counts wouldn't scale to peak volume |
| Self-managed Kafka on EC2 | Operational burden we did not want; ZooKeeper/KRaft maintenance is real work |
| **MSK provisioned (chosen)** | Right balance of managed ops and Kafka feature parity |

**Reasoning:**

- Multi-consumer pattern: lakehouse, feature store, and a downstream alerting system all consume from the same topics independently. Kafka's consumer-group model is more natural here than Kinesis fan-out.
- Schema Registry support (Confluent or AWS Glue Schema Registry) was non-negotiable for schema evolution.
- 7-day retention for replay was easy to configure and cheap relative to Kinesis extended retention.

### 4.2 Why two streaming engines (Spark + Flink)

**Decision:** Spark Structured Streaming for landing & parity; Flink for low-latency stateful aggregations.

**Reasoning:**

- Spark Structured Streaming runs on Databricks micro-batches with default trigger of ~1–5 seconds. Excellent for landing into Delta Lake (which it integrates with natively), and for parity with batch logic — same DataFrame transformations work for both.
- Flink delivers true event-at-a-time processing with materially lower tail latency for stateful operations (e.g., "transaction count for this card in the last 60 seconds" with rolling windows). Spark micro-batches added 1–3 seconds of inherent latency that some fraud features couldn't tolerate.
- Two engines is operational overhead, but the alternative — forcing every workload onto Spark — would have meant features either too stale or implemented twice (once in batch Spark, once in a custom Flink job anyway).

**Trade-offs:**

- Two skill sets to maintain. Mitigated by clear ownership: data engineering owns Spark; a smaller specialized team owns Flink.
- Two state backends to operate. Acceptable for the latency benefit.

### 4.3 Exactly-once semantics

**Decision:** End-to-end exactly-once via:

- Kafka idempotent producers + transactions at source publishers.
- Spark Structured Streaming with `checkpointLocation` and Delta's atomic commits (Delta + Spark together provide exactly-once writes).
- Flink with checkpointing every 30 seconds, two-phase commit sinks where supported.

**Reasoning:** "At-least-once + idempotent downstream consumers" was on the table, but feature aggregations (counts, sums) are not naturally idempotent without keyed deduplication. Exactly-once at the platform level was simpler than pushing dedup into every downstream consumer.

### 4.4 Schema evolution

**Decision:** Avro with Schema Registry, **backward-compatible evolution only** enforced by registry policy.

**Reasoning:**

- Producers and consumers deploy independently. Backward-compatible evolution (additive fields with defaults, no removals or type changes) lets producers ship new fields without coordinating consumer rollouts.
- Forbidden changes (field removal, type narrowing) are blocked at registry-level — a producer attempting to publish a breaking schema simply cannot.
- Avro vs. Protobuf: Avro chosen for tighter schema-registry tooling and smaller serialized footprint at our payload sizes.

### 4.5 PII tokenization in stream

**Decision:** Tokenize PII fields (PAN, account number, SSN) inline in the streaming job, before they land in bronze Delta. Tokenization vault accessed via VPC endpoint.

**Reasoning:**

- Bronze tables are accessed by analysts and pipelines that should not be in PCI scope. Tokenizing at the stream boundary keeps bronze out of PCI scope (with documented controls).
- Inline tokenization adds 4–8 ms of latency per event, well within budget. Vault calls are batched per micro-batch.
- Format-preserving tokens preserve PAN BIN ranges and length, enabling downstream business logic without detokenization.

### 4.6 Online/offline feature parity

**Decision:** Online features (sub-second freshness) and offline features (batch-computed for training) must be produced from the same logical definition and tested against each other for skew.

Implementation: feature definitions in Python; the streaming job and the batch job both import the same transformation function. A nightly skew job samples online and offline computations of the same feature for the same entity and alerts on divergence beyond tolerance.

**Reasoning:** Training-serving skew is one of the most common silent ML failures. Architecturally enforcing parity, rather than trusting two separate implementations to stay in sync, eliminates an entire class of model-degradation bug.

### 4.7 Backpressure & failure handling

**Decision:**

- Kafka topic partition counts sized for **2x peak observed throughput** to allow consumer parallelism headroom.
- Spark structured streaming with rate limits per micro-batch to avoid runaway memory on traffic spikes.
- Dead-letter topic (DLT) per source: malformed or schema-violating events get routed to DLT with original payload, error, and timestamp for triage. DLT is a first-class tier, not a forgotten dumping ground — there is an on-call alert when DLT depth exceeds threshold.

**Reasoning:** Streaming systems fail in subtle ways: a single malformed record can stall a job indefinitely if you let it. DLT pattern gives us "fail forward" semantics: bad data is captured for inspection, but the stream keeps moving.

### 4.8 Observability

Per-pipeline metrics published to CloudWatch + Datadog: input rate, output rate, end-to-end latency (p50/p95/p99), backlog, checkpoint duration, DLT depth.

SLOs declared and tracked: e.g., "card-auth pipeline p95 e2e latency < 800ms over 30-day window."

---

## 5. Trade-offs Accepted

- **Two engines (Spark + Flink) increase operational surface.** Justified by latency requirements; revisited annually.
- **Sub-second guarantee is p95, not p99.** Tail-latency events do happen — checkpoint overhead, GC pauses. We documented this with the consuming model teams; their fallback when an online feature is stale is to use the most recent value with a freshness flag, not to fail the inference call.
- **MSK ZooKeeper operational toil** (later mitigated by KRaft migration). At time of design, MSK didn't yet offer KRaft GA, and we accepted ZooKeeper-mode complexity.

---

## 6. Outcome

- Sub-second p95 end-to-end latency achieved on all 8 in-scope source systems.
- 25k events/sec sustained; tested to 110k events/sec without degradation.
- Fraud model precision improved by 6 percentage points after switching from batch to streaming features (training-serving skew was the dominant culprit, now eliminated).
- Pattern reused for transaction monitoring and AML alerting downstream.

---

## 7. What I'd Reconsider

- For a 2026 redesign, I'd evaluate Apache Iceberg + EMR Serverless or a unified engine like Apache Beam to reduce the two-engine split.
- We invested heavily in custom DLT triage tooling. Would adopt an off-the-shelf option (e.g., a DLT replay UI) if one were mature now.
- Should have set explicit SLOs (with error budgets) earlier in the project rather than declaring them mid-stabilization. Without an error budget, every blip looked like an outage.
