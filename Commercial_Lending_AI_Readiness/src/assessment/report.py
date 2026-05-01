"""Human-readable assessment report printer."""
from src.assessment.models import AssessmentReport, DomainScore


def _severity_icon(s: str) -> str:
    return {"CRITICAL": "[CRIT]", "WARN": "[WARN]", "INFO": "[  OK]"}[s]


def _bar(score: float, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_report(report: AssessmentReport) -> None:
    print("\n" + "=" * 65)
    print("  COMMERCIAL LENDING DATA READINESS ASSESSMENT")
    print("=" * 65)

    for domain_score in [report.crm, report.documents, report.compliance]:
        _print_domain(domain_score)

    idx = report.composite_index
    print("\n" + "─" * 65)
    print(f"  COMPOSITE AI READINESS INDEX: {idx:.1f}/100  {_bar(idx)}")
    print(f"  Grade: {report.readiness_grade}")
    print("─" * 65 + "\n")


def _print_domain(ds: DomainScore) -> None:
    label = ds.domain.upper().ljust(10)
    bar = _bar(ds.score)
    crit_marker = " [!CRITICAL FINDINGS]" if ds.has_critical else ""
    print(f"\n  {label} {ds.score:5.1f}/100  {bar}{crit_marker}")

    for check in sorted(ds.checks, key=lambda c: {"CRITICAL": 0, "WARN": 1, "INFO": 2}[c.severity]):
        icon = _severity_icon(check.severity)
        score_pct = f"{check.score * 100:5.1f}%"
        print(f"    {icon} {score_pct}  {check.name}")
        print(f"              {check.details}")
