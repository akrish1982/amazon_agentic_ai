"""CRM data readiness checks: completeness, freshness, dedup, KYC coverage."""
import sqlite3
from datetime import datetime, timedelta
from src.assessment.models import CheckResult


def run_checks(conn: sqlite3.Connection) -> list[CheckResult]:
    return [
        _completeness_check(conn),
        _kyc_coverage_check(conn),
        _ofac_freshness_check(conn),
        _contact_coverage_check(conn),
        _aml_flag_consistency_check(conn),
    ]


def _completeness_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN ein IS NULL OR ein = '' THEN 1 ELSE 0 END) AS missing_ein,
             SUM(CASE WHEN naics_code IS NULL THEN 1 ELSE 0 END) AS missing_naics,
             SUM(CASE WHEN annual_revenue IS NULL THEN 1 ELSE 0 END) AS missing_revenue
           FROM customers"""
    ).fetchone()

    total = row["total"] or 1
    missing = row["missing_ein"] + row["missing_naics"] + row["missing_revenue"]
    fields_total = total * 3
    completeness = 1.0 - (missing / fields_total)

    severity = "INFO" if completeness >= 0.95 else ("WARN" if completeness >= 0.85 else "CRITICAL")
    return CheckResult(
        name="CRM field completeness",
        score=completeness,
        severity=severity,
        details=f"{missing}/{fields_total} mandatory field values missing "
                f"(EIN: {row['missing_ein']}, NAICS: {row['missing_naics']}, Revenue: {row['missing_revenue']})",
        dimension="completeness",
    )


def _kyc_coverage_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN kyc_status = 'approved' THEN 1 ELSE 0 END) AS approved,
                  SUM(CASE WHEN kyc_status = 'pending' THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN kyc_status = 'expired' THEN 1 ELSE 0 END) AS expired
           FROM customers"""
    ).fetchone()
    total = row["total"] or 1
    approved_rate = row["approved"] / total
    severity = "INFO" if approved_rate >= 0.90 else ("WARN" if approved_rate >= 0.75 else "CRITICAL")
    return CheckResult(
        name="KYC approval coverage",
        score=approved_rate,
        severity=severity,
        details=f"{row['approved']}/{total} customers KYC-approved "
                f"(pending: {row['pending']}, expired: {row['expired']})",
        dimension="completeness",
    )


def _ofac_freshness_check(conn: sqlite3.Connection) -> CheckResult:
    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN ofac_checked_at IS NULL OR ofac_checked_at < ? THEN 1 ELSE 0 END) AS stale
           FROM customers""",
        (cutoff,),
    ).fetchone()
    total = row["total"] or 1
    fresh_rate = 1.0 - (row["stale"] / total)
    severity = "CRITICAL" if fresh_rate < 0.90 else ("WARN" if fresh_rate < 0.97 else "INFO")
    return CheckResult(
        name="OFAC screening freshness",
        score=fresh_rate,
        severity=severity,
        details=f"{row['stale']}/{total} customers have stale OFAC checks (>365 days old)",
        dimension="freshness",
    )


def _contact_coverage_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN phone IS NULL AND email IS NULL THEN 1 ELSE 0 END) AS no_contact
           FROM customers"""
    ).fetchone()
    total = row["total"] or 1
    coverage = 1.0 - (row["no_contact"] / total)
    severity = "WARN" if coverage < 0.95 else "INFO"
    return CheckResult(
        name="Contact information coverage",
        score=coverage,
        severity=severity,
        details=f"{row['no_contact']}/{total} customers missing both phone and email",
        dimension="completeness",
    )


def _aml_flag_consistency_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN aml_flag = 1 AND kyc_status != 'flagged' THEN 1 ELSE 0 END) AS inconsistent
           FROM customers"""
    ).fetchone()
    total = row["total"] or 1
    consistency = 1.0 - (row["inconsistent"] / total)
    severity = "CRITICAL" if row["inconsistent"] > 0 else "INFO"
    return CheckResult(
        name="AML flag / KYC status consistency",
        score=consistency,
        severity=severity,
        details=(
            f"{row['inconsistent']} customers have AML flag set but KYC status is not 'flagged' — "
            "AI agents may make incorrect risk assessments"
            if row["inconsistent"] > 0
            else "AML flags and KYC status are consistent across all records"
        ),
        dimension="consistency",
    )
