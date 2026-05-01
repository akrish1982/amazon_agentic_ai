from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["CRITICAL", "WARN", "INFO"]


@dataclass
class CheckResult:
    name: str
    score: float        # 0.0 – 1.0
    severity: Severity
    details: str
    dimension: str      # completeness|freshness|consistency|format|coverage


@dataclass
class DomainScore:
    domain: str         # crm|documents|compliance
    score: float        # 0 – 100
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(c.severity == "CRITICAL" for c in self.checks)

    @property
    def critical_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == "CRITICAL"]

    @property
    def warn_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == "WARN"]


@dataclass
class AssessmentReport:
    crm: DomainScore
    documents: DomainScore
    compliance: DomainScore

    @property
    def composite_index(self) -> float:
        """Weighted composite AI Readiness Index (0–100)."""
        return round(
            self.crm.score * 0.35
            + self.documents.score * 0.40
            + self.compliance.score * 0.25,
            1,
        )

    @property
    def readiness_grade(self) -> str:
        idx = self.composite_index
        if idx >= 85:
            return "A — Ready for AI agent consumption"
        if idx >= 70:
            return "B — Minor remediation needed"
        if idx >= 55:
            return "C — Significant gaps; partial deployment only"
        return "D — Not ready; remediation required before AI use"
