"""ReadinessScorer: weighted rubric engine for all three data domains."""
import sqlite3
from src.assessment.models import AssessmentReport, CheckResult, DomainScore
from src.assessment.checks import crm_checks, document_checks, compliance_checks

# Dimension weights per domain (must sum to 1.0)
WEIGHTS = {
    "crm": {
        "completeness": 0.30,
        "freshness":    0.25,
        "consistency":  0.20,
        "format":       0.15,
        "coverage":     0.10,
    },
    "documents": {
        "completeness": 0.25,
        "freshness":    0.15,
        "consistency":  0.20,
        "format":       0.30,
        "coverage":     0.10,
    },
    "compliance": {
        "completeness": 0.20,
        "freshness":    0.30,
        "consistency":  0.25,
        "format":       0.15,
        "coverage":     0.10,
    },
}

CRITICAL_SCORE_CAP = 40.0  # Any CRITICAL finding caps domain score at 40


def _score_domain(checks: list[CheckResult], domain: str) -> DomainScore:
    weights = WEIGHTS[domain]
    dimension_scores: dict[str, list[float]] = {d: [] for d in weights}

    for check in checks:
        dim = check.dimension
        if dim in dimension_scores:
            dimension_scores[dim].append(check.score)

    weighted_sum = 0.0
    for dim, weight in weights.items():
        scores = dimension_scores[dim]
        avg = sum(scores) / len(scores) if scores else 1.0
        weighted_sum += avg * weight

    raw_score = round(weighted_sum * 100, 1)

    has_critical = any(c.severity == "CRITICAL" for c in checks)
    final_score = min(raw_score, CRITICAL_SCORE_CAP) if has_critical else raw_score

    return DomainScore(domain=domain, score=final_score, checks=checks)


class ReadinessScorer:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def score(self) -> AssessmentReport:
        crm = _score_domain(crm_checks.run_checks(self.conn), "crm")
        docs = _score_domain(document_checks.run_checks(self.conn), "documents")
        compliance = _score_domain(compliance_checks.run_checks(self.conn), "compliance")
        return AssessmentReport(crm=crm, documents=docs, compliance=compliance)
