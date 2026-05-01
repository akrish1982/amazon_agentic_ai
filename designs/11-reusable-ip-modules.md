# Design Document: Reusable IP — CDK Constructs, Terraform Modules, Design Patterns

**Author:** Ananth — Senior Data Architect, AWS
**Audience:** AWS strategic accounts in financial services
**Status:** Adopted across multiple engagements
```
NOTE: These are situations similar to real designs but have been chareterestically altered to ensure the private information is not exposed. Some Tools and Software are replaced by close equivalent ones and some metrics have been meaningfully altered as well.
```

---

## 1. Context & Problem Statement

Engagement after engagement at AWS strategic financial-services accounts surfaced the same set of problems and the same set of solutions, each time rebuilt from scratch:

- A data lakehouse with bronze/silver/gold zones, encryption, lifecycle policies, and access controls.
- A Glue + Step Functions orchestration pattern for medallion ETL.
- An MSK + Spark Structured Streaming pipeline with DLT and observability.
- A SageMaker Feature Store wrapper with tagging conventions and access policies.
- An OpenSearch + Bedrock RAG stack.

Each new engagement spent 3–6 weeks rebuilding the foundation before delivering anything client-specific. Worse: rebuilds drifted in subtle ways — encryption defaults, tagging, retention policy, IAM scoping — meaning every account had a slightly different security posture for the same workload pattern.

**Goal:** Codify the recurring patterns into reusable CDK constructs and Terraform modules that ship with a strong default security posture, accelerate engagement delivery, and converge on a consistent reference architecture across accounts.

**Non-goals:** A general-purpose AWS framework; replacing AWS Solutions Constructs; supporting non-financial-services patterns.

---

## 2. What Got Codified

| Asset | Form | Purpose |
|---|---|---|
| `data-lakehouse-foundation` | Terraform module | S3 zones (bronze/silver/gold), KMS keys, lifecycle, Glue catalog, Lake Formation tags |
| `medallion-etl-orchestrator` | CDK construct (Python) | Step Functions + Glue job framework, retries, error handling, run lineage |
| `streaming-ingestion` | Terraform + CDK hybrid | MSK cluster + topics + Schema Registry + Spark job templates |
| `secure-network-baseline` | Terraform module | VPC, endpoints, NACLs, route tables aligned to common FSI requirements |
| `sagemaker-platform` | CDK construct | Feature Store, model registry, model-approval workflow, CloudWatch dashboards |
| `bedrock-rag-stack` | CDK construct | OpenSearch Serverless collection, Bedrock model invocation IAM, embedding job templates |
| `iam-scoping-toolkit` | Terraform module | Least-privilege IAM policy generators per data-platform persona |

Plus a written set of design patterns documented as ADRs (Architecture Decision Records).

---

## 3. Key Design Decisions

### 3.1 Two IaC tools, not one

**Decision:** CDK for application-layer constructs; Terraform for foundation-layer modules.

**Reasoning:**

- **Foundation layer** (network, KMS, S3, Lake Formation, IAM baseline) is owned by central platform / cloud governance teams who almost universally use Terraform in FSI accounts. Forcing them onto CDK is a non-starter.
- **Application layer** (data pipelines, ML platforms, RAG stacks) is owned by data engineering teams who can be more flexible. CDK's higher-level abstractions and TypeScript/Python ergonomics let us express richer constructs (Step Functions definitions, Glue job graphs) than Terraform's HCL comfortably handles.
- The two layers connect via well-defined interfaces: Terraform-owned resources expose ARNs/IDs through SSM Parameter Store; CDK constructs read from SSM at synth time.

**Trade-offs:**

- Two toolchains, two skill sets. Mitigated by clear ownership boundaries.
- Some duplication risk (e.g., a tag scheme defined in both). Mitigated by a shared module that exports tag conventions to both ecosystems.

### 3.2 Strong defaults; explicit opt-out for relaxation

**Decision:** Every module/construct ships with the strongest security posture as default. Loosening requires an explicit, documented opt-out.

Examples:

- S3 buckets default to: KMS-CMK encryption, public access blocked, versioning on, MFA delete optional but documented, TLS-only bucket policy, lifecycle to Glacier after 365 days.
- IAM roles default to: no wildcard actions, no wildcard resources, condition keys for `aws:SourceAccount` where applicable.
- KMS keys default to: rotation enabled, key policy restricting principals, no `kms:*` grants.

**Reasoning:** Frameworks that ship with permissive defaults and require users to lock things down end up with permissive deployments. The inverse — secure defaults, explicit relaxation — is the right shape for FSI workloads. A code review on `allow_public_access = true` is a legible signal; a code review on the absence of `allow_public_access = false` is invisible.

### 3.3 Tagging is a first-class API, not an afterthought

**Decision:** Every resource accepts a `cost_allocation_tags` and `governance_tags` input; modules merge them with a baseline and apply uniformly. Tag values are validated against allowed lists.

Required tags: `data-classification`, `cost-center`, `environment`, `owner`, `data-domain`, `compliance-scope` (PCI/PII/PHI/none).

**Reasoning:**

- Tagging is what makes cost allocation, FinOps, and security audits work. Inconsistency makes reports useless.
- Validating values prevents typos like `pci` vs. `PCI` from fragmenting reports.
- Treating tags as a first-class input rather than a "TODO" comment forces tagging to happen during the engagement, not after.

### 3.4 Composable, not opinionated about the whole stack

**Decision:** Each construct/module solves one problem and exposes outputs that other modules consume. No "deploy a complete data platform with one command" mega-module.

**Reasoning:**

- Real engagements have local constraints — an existing VPC, a non-standard catalog, an inherited KMS key. A monolithic deployment that owns everything is unusable in those contexts.
- Composition lets a client adopt one piece (say, the streaming module) without buying into the rest.
- Smaller modules are independently versionable and testable.

### 3.5 Versioning and consumer compatibility

**Decision:** Semantic versioning. Every module/construct has a `CHANGELOG.md` and a `MIGRATION.md` for major-version bumps. Consumers pin to a specific version.

**Reasoning:**

- Multiple engagements consume the same modules at different cadences. An unversioned shared library with surprise breaking changes is worse than no shared library at all.
- Major-version bumps with explicit migration guides let mature engagements upgrade on their schedule.

### 3.6 Configuration over code customization

**Decision:** Modules are configured via input variables, not by forking the source. If a client needs a behavior the module doesn't support, the path is a feature contribution to the module, not a fork.

**Reasoning:** Forks proliferate, drift, and defeat the purpose of shared IP. By making the upstream the only path, the modules improve over time rather than fragmenting.

### 3.7 Testing strategy

**Decision:**

- Terraform: `terraform-compliance` for policy assertions (e.g., "all S3 buckets must be encrypted") + `tflint` for syntactic correctness.
- CDK: snapshot tests on synthesized CloudFormation + targeted unit tests on construct logic.
- Both: integration test stack deployed to a sandbox account in CI, validated, then destroyed.

**Reasoning:** These modules deploy security-sensitive primitives. Regressions on, say, encryption defaults are exactly the kind of bug that hurts a client. Policy-as-tests catch them before merge.

### 3.8 Documentation is part of the deliverable

**Decision:** Each module ships with:

- `README.md`: what it does, when to use it, when not to use it.
- `EXAMPLES/`: minimal and full example deployments.
- `ADR/`: design decisions with reasoning (this is how I think; this is how to extend it without breaking it).
- `SECURITY.md`: the security posture, defaults, and what changes when you flip each flag.

**Reasoning:** Modules without documentation get rebuilt because nobody trusts them. Trust is earned by visible, auditable design choices.

---

## 4. Notable Patterns Codified

### Pattern: Lake Formation tag-based access control

Rather than per-table IAM grants, the foundation module establishes LF tags (`data-classification`, `business-domain`) and grants are made on tag combinations. Adding a new table doesn't require new grants — it inherits permissions from its tags. Documented with examples.

### Pattern: Step Functions error envelope

Every Glue/Lambda task in the orchestrator emits a structured error envelope: `{step, error_class, error_message, retryable, context}`. The state machine routes retryable errors to retry, non-retryable to a triage queue with full context. Eliminates the "Step Functions failed, no idea why" experience.

### Pattern: KMS key per data domain

Foundation module creates one KMS key per data domain (deposits, cards, lending, …) rather than one bank-wide. Limits blast radius; aligns with internal data-domain ownership; key policies become enforceable boundaries.

### Pattern: Cost-center attribution at compute level

Tag every Glue job, EMR cluster, MSK cluster, and SageMaker training job with the cost center of the consuming team. Cost Explorer reports become per-team without manual reconciliation.

### Pattern: Run-lineage table

Every pipeline writes to a `pipeline_runs` Iceberg table with run_id, inputs, outputs, status, durations. Becomes the substrate for SLO dashboards and a "what was the data quality on date X" audit trail.

---

## 5. Distribution & Adoption

- Internal Git monorepo, mirrored to artifact registries (Terraform Cloud private modules, CodeArtifact for CDK packages).
- Versioned releases with release notes.
- Quarterly review with adopting accounts: what's missing, what's awkward, what should be deprecated.
- Office-hours channel for consumers; a small backlog of upstream contributions per quarter.

---

## 6. Trade-offs Accepted

- **Maintenance overhead.** Shared IP is a product, not a one-time deliverable. Requires ongoing time investment between engagements. Justified by per-engagement acceleration.
- **Coupling risk.** Multiple consumers on the same module means a bug affects many at once. Mitigated by versioning + consumer pinning.
- **Not-invented-here resistance.** Some account teams initially preferred to build their own. Adopted as adoption stories accumulated and time-savings became measurable.

---

## 7. Outcome

- Adopted across multiple AWS strategic financial-services accounts.
- Typical engagement foundation work compressed from 3–6 weeks to 3–7 days.
- Convergence on consistent security posture across accounts: encryption-by-default, scoped IAM, validated tagging, run lineage.
- Bug fixes and security improvements made once and inherited everywhere on next version bump.

---

## 8. What I'd Reconsider

- Started with too many small modules; should have consolidated some that were always used together.
- Underinvested in the contribution path — making it easy for engagement teams to upstream improvements would have accelerated maturation.
- Should have published a public landing page summarizing patterns (without proprietary detail) earlier, both for talent attraction and for cross-account peer learning.
