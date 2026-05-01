"""Document repository readiness checks: coverage, format, classification."""
import sqlite3
from pathlib import Path
from config.settings import BASE_DIR
from src.assessment.models import CheckResult

POLICY_DIR = BASE_DIR / "data" / "seed" / "policy_documents"

REQUIRED_DOC_TYPES = {"policy", "guideline", "regulation"}
REGULATION_KEYWORDS = ["ECOA", "BSA", "AML", "SBA", "CRA", "TILA", "RESPA", "OFAC"]


def run_checks(conn: sqlite3.Connection) -> list[CheckResult]:
    return [
        _doc_count_coverage(),
        _format_consistency_check(),
        _regulation_tag_coverage(conn),
        _version_currency_check(conn),
        _orphan_chunks_check(conn),
    ]


def _doc_count_coverage() -> CheckResult:
    doc_files = list(POLICY_DIR.glob("*.txt")) + list(POLICY_DIR.glob("*.pdf"))
    count = len(doc_files)
    # For a real lending institution, ~100K documents expected; demo has seed set
    # Score scales from 0 at 0 docs to 1.0 at 10+ docs (demo scale)
    score = min(count / 10.0, 1.0)
    severity = "CRITICAL" if count == 0 else ("WARN" if count < 5 else "INFO")
    return CheckResult(
        name="Policy document coverage",
        score=score,
        severity=severity,
        details=f"{count} policy documents found in repository (expected: 100K+ in production)",
        dimension="coverage",
    )


def _format_consistency_check() -> CheckResult:
    doc_files = list(POLICY_DIR.glob("*"))
    parseable = [f for f in doc_files if f.suffix in {".txt", ".pdf", ".docx", ".md"}]
    total = len(doc_files) or 1
    rate = len(parseable) / total
    severity = "WARN" if rate < 0.95 else "INFO"
    return CheckResult(
        name="Document format parseability",
        score=rate,
        severity=severity,
        details=f"{len(parseable)}/{total} documents in machine-parseable format "
                f"({total - len(parseable)} in unsupported formats)",
        dimension="format",
    )


def _regulation_tag_coverage(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN regulation_refs IS NULL OR regulation_refs = '[]' THEN 1 ELSE 0 END) AS untagged
           FROM document_tags"""
    ).fetchone()
    total = row["total"] or 0
    if total == 0:
        return CheckResult(
            name="Regulation tag coverage",
            score=0.0,
            severity="CRITICAL",
            details="No documents have been tagged yet — metadata pipeline not run",
            dimension="completeness",
        )
    untagged = row["untagged"] or 0
    rate = 1.0 - (untagged / total)
    severity = "CRITICAL" if rate < 0.80 else ("WARN" if rate < 0.95 else "INFO")
    return CheckResult(
        name="Regulation tag coverage",
        score=rate,
        severity=severity,
        details=f"{untagged}/{total} ingested documents missing regulation reference tags",
        dimension="completeness",
    )


def _version_currency_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN version IS NULL THEN 1 ELSE 0 END) AS no_version
           FROM document_tags"""
    ).fetchone()
    total = row["total"] or 0
    if total == 0:
        return CheckResult(
            name="Document version currency",
            score=0.5,
            severity="WARN",
            details="No tagged documents to evaluate version currency",
            dimension="freshness",
        )
    no_version = row["no_version"] or 0
    rate = 1.0 - (no_version / total)
    severity = "WARN" if rate < 0.90 else "INFO"
    return CheckResult(
        name="Document version currency",
        score=rate,
        severity=severity,
        details=f"{no_version}/{total} documents missing version metadata "
                "(risk: agents may retrieve outdated policy versions)",
        dimension="freshness",
    )


def _orphan_chunks_check(conn: sqlite3.Connection) -> CheckResult:
    row = conn.execute(
        """SELECT COUNT(*) AS orphans FROM document_chunks
           WHERE doc_id NOT IN (SELECT doc_id FROM policy_documents)"""
    ).fetchone()
    orphans = row["orphans"] or 0
    score = 1.0 if orphans == 0 else max(0.0, 1.0 - orphans / 100)
    severity = "CRITICAL" if orphans > 10 else ("WARN" if orphans > 0 else "INFO")
    return CheckResult(
        name="Knowledge base integrity (orphan chunks)",
        score=score,
        severity=severity,
        details=f"{orphans} chunks reference documents not in the policy_documents table",
        dimension="consistency",
    )
