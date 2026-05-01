"""Compliance database readiness: regulation mapping, version currency, rule completeness."""
import sqlite3
from src.assessment.models import CheckResult

REQUIRED_REGULATIONS = {"ECOA", "BSA", "AML", "SBA", "CRA", "TILA", "OFAC"}
REQUIRED_SEVERITY_LEVELS = {"mandatory", "advisory"}


def run_checks(conn: sqlite3.Connection) -> list[CheckResult]:
    return [
        _regulation_coverage_check(conn),
        _rule_completeness_check(conn),
        _mandatory_rule_check(conn),
        _effective_date_check(conn),
        _loan_type_mapping_check(conn),
    ]


def _regulation_coverage_check(conn: sqlite3.Connection) -> CheckResult:
    rows = conn.execute("SELECT DISTINCT regulation FROM compliance_rules").fetchall()
    present = {r["regulation"] for r in rows}
    missing = REQUIRED_REGULATIONS - present
    coverage = len(present & REQUIRED_REGULATIONS) / len(REQUIRED_REGULATIONS)
    severity = "CRITICAL" if missing else "INFO"
    return CheckResult(
        name="Regulation coverage",
        score=coverage,
        severity=severity,
        details=(
            f"All {len(REQUIRED_REGULATIONS)} required regulations represented"
            if not missing
            else f"Missing regulations: {', '.join(sorted(missing))} — AI agents cannot answer queries on these topics"
        ),
        dimension="coverage",
    )


def _rule_completeness_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN rule_text IS NULL OR length(rule_text) < 50 THEN 1 ELSE 0 END) AS incomplete,
                  SUM(CASE WHEN source_doc_ref IS NULL THEN 1 ELSE 0 END) AS no_citation
           FROM compliance_rules"""
    ).fetchone()
    total = row["total"] or 1
    incomplete = row["incomplete"] or 0
    no_citation = row["no_citation"] or 0
    # Weight incomplete rules more heavily than missing citations
    score = 1.0 - (incomplete * 0.7 + no_citation * 0.3) / total
    score = max(0.0, score)
    severity = "CRITICAL" if incomplete > 0 else ("WARN" if no_citation > 0 else "INFO")
    return CheckResult(
        name="Rule text completeness",
        score=score,
        severity=severity,
        details=f"{incomplete} rules with insufficient text (<50 chars), "
                f"{no_citation} rules missing source citations",
        dimension="completeness",
    )


def _mandatory_rule_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN severity = 'mandatory' THEN 1 ELSE 0 END) AS mandatory_count
           FROM compliance_rules"""
    ).fetchone()
    total = row["total"] or 1
    mandatory_rate = row["mandatory_count"] / total
    # At least 50% of rules should be classified mandatory for a lending compliance DB
    score = min(mandatory_rate / 0.5, 1.0)
    severity = "WARN" if mandatory_rate < 0.40 else "INFO"
    return CheckResult(
        name="Mandatory rule classification",
        score=score,
        severity=severity,
        details=f"{row['mandatory_count']}/{total} rules classified as mandatory severity",
        dimension="completeness",
    )


def _effective_date_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN effective_date IS NULL THEN 1 ELSE 0 END) AS no_date
           FROM compliance_rules"""
    ).fetchone()
    total = row["total"] or 1
    coverage = 1.0 - (row["no_date"] / total)
    severity = "WARN" if coverage < 0.90 else "INFO"
    return CheckResult(
        name="Effective date coverage",
        score=coverage,
        severity=severity,
        details=f"{row['no_date']}/{total} rules missing effective dates "
                "(risk: agents cannot determine which regulations are currently active)",
        dimension="freshness",
    )


def _loan_type_mapping_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN loan_type IS NOT NULL THEN 1 ELSE 0 END) AS typed
           FROM compliance_rules"""
    ).fetchone()
    total = row["total"] or 1
    # Mix of loan-type-specific and universal (NULL) rules is healthy
    # Check: at least one rule per major loan type
    loan_types = {r["loan_type"] for r in conn.execute(
        "SELECT DISTINCT loan_type FROM compliance_rules WHERE loan_type IS NOT NULL"
    ).fetchall()}
    expected = {"SBA", "CRE", "C&I", "construction"}
    mapped = loan_types & expected
    score = len(mapped) / len(expected)
    severity = "WARN" if score < 0.75 else "INFO"
    return CheckResult(
        name="Loan-type rule mapping",
        score=score,
        severity=severity,
        details=f"Loan-type-specific rules present for: {', '.join(sorted(mapped)) or 'none'} "
                f"(missing: {', '.join(sorted(expected - mapped)) or 'none'})",
        dimension="coverage",
    )
