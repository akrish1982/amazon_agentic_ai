"""Three-pass auto-tagging: regex → TF-IDF keywords → Claude fallback."""
import re
import hashlib
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from src.metadata.schema import DocumentMetadata, DocType, RiskTier

# Pass 1: regex patterns
_REGULATION_PATTERNS = {
    "ECOA": re.compile(r"\bECOA\b|Equal Credit Opportunity|Regulation B|Reg B|15 U\.S\.C\..*1691", re.I),
    "BSA":  re.compile(r"\bBSA\b|Bank Secrecy Act|FinCEN|31 U\.S\.C\..*5318|31 C\.F\.R\.", re.I),
    "AML":  re.compile(r"\bAML\b|anti.money.laundering|suspicious activity|SAR\b", re.I),
    "SBA":  re.compile(r"\bSBA\b|Small Business Administration|SOP 50", re.I),
    "CRA":  re.compile(r"\bCRA\b|Community Reinvestment Act|12 U\.S\.C\..*2901", re.I),
    "TILA": re.compile(r"\bTILA\b|Truth in Lending|Regulation Z|Reg Z|15 U\.S\.C\..*1638", re.I),
    "RESPA":re.compile(r"\bRESPA\b|Real Estate Settlement|12 U\.S\.C\..*2601", re.I),
    "OFAC": re.compile(r"\bOFAC\b|Specially Designated|SDN list|50 U\.S\.C\..*1705", re.I),
}

_LOAN_TYPE_PATTERNS = {
    "SBA":          re.compile(r"\bSBA\b|504 loan|7\(a\)|SBA 7|SBA 504", re.I),
    "CRE":          re.compile(r"\bCRE\b|commercial real estate|income.producing property", re.I),
    "C&I":          re.compile(r"\bC&I\b|commercial.*industrial|working capital|revolving.*credit", re.I),
    "construction": re.compile(r"\bconstruction\b.*loan|construction.*financing|construction.*draw", re.I),
    "USDA":         re.compile(r"\bUSDA\b|Farm Service|rural.*loan", re.I),
}

_DOC_TYPE_PATTERNS: list[tuple[DocType, re.Pattern]] = [
    # Match against the document TITLE (first 300 chars). Order: most specific first.
    ("memo",       re.compile(r"^(?:MEMO(?:RANDUM)?|BULLETIN|NOTICE)\b", re.I)),
    # "form" only when the title itself says it's a form or questionnaire
    ("form",       re.compile(r"\b(?:FORM|QUESTIONNAIRE|APPLICATION FORM|CERTIFICATION FORM)\b", re.I)),
    # "guideline" when title contains "guidelines" (not just "policy that mentions guidelines")
    ("guideline",  re.compile(r"\bGUIDELINES?\b", re.I)),
    # "regulation" when title references a specific regulation (12 CFR, Reg B, etc.)
    ("regulation", re.compile(r"\b(?:REGULATION\s+[A-Z]|12\s+C\.F\.R\.|31\s+C\.F\.R\.)\b", re.I)),
    # "policy" is the safe default for internal bank policy documents
    ("policy",     re.compile(r"\bPOLICY\b|\bPOLICIES\b|\bUNDERWRITING\b|\bSTANDARDS?\b", re.I)),
]

_RISK_TIER_PATTERNS: list[tuple[RiskTier, re.Pattern]] = [
    ("critical", re.compile(r"\bOFAC\b|sanctions|money.laundering|SAR\b|CRITICAL", re.I)),
    ("high",     re.compile(r"\bAML\b|\bBSA\b|\bECOA\b|fair.lending|HIGH", re.I)),
    ("medium",   re.compile(r"\bSBA\b|\bCRE\b|\bC&I\b|underwriting", re.I)),
    ("low",      re.compile(r"\bprocedure\b|\bmemo\b|\bform\b", re.I)),
]

_VERSION_PATTERN = re.compile(r"[Vv]ersion\s*(\d+[\.\d]*)", re.I)
_DATE_PATTERN = re.compile(
    r"[Ee]ffective\s*:?\s*(\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})"
)


def _regex_pass(text: str) -> dict:
    regulations = [reg for reg, pat in _REGULATION_PATTERNS.items() if pat.search(text)]
    loan_types = [lt for lt, pat in _LOAN_TYPE_PATTERNS.items() if pat.search(text)]

    # Apply doc_type patterns only to the document title (first 300 chars)
    title = text[:300]
    doc_type: DocType = "policy"
    for dtype, pat in _DOC_TYPE_PATTERNS:
        if pat.search(title):
            doc_type = dtype
            break

    risk_tier: RiskTier = "medium"
    for tier, pat in _RISK_TIER_PATTERNS:
        if pat.search(text):
            risk_tier = tier
            break

    version = ""
    vm = _VERSION_PATTERN.search(text[:500])
    if vm:
        version = vm.group(1)

    effective_date = None
    dm = _DATE_PATTERN.search(text[:1000])
    if dm:
        raw = dm.group(1).strip()
        for fmt in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d"):
            try:
                effective_date = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                pass

    return {
        "regulation_refs": regulations,
        "loan_types": loan_types,
        "doc_type": doc_type,
        "risk_tier": risk_tier,
        "version": version,
        "effective_date": effective_date,
    }


def _tfidf_keywords(text: str, top_n: int = 10) -> list[str]:
    """Character-level TF-IDF approximation — no external ML dependency."""
    words = re.findall(r'\b[a-zA-Z][a-zA-Z]{3,}\b', text.lower())
    stopwords = {
        "this", "that", "with", "from", "have", "will", "must", "shall", "should",
        "each", "such", "than", "been", "were", "their", "they", "also", "which",
        "when", "where", "loan", "loans", "bank", "credit", "lending", "financial",
        "section", "part", "requirement", "requirements", "applicable", "including",
    }
    words = [w for w in words if w not in stopwords]
    tf = Counter(words)
    total = sum(tf.values()) or 1
    # IDF approximation: penalize very common terms
    scored = {w: (count / total) * math.log(1 + total / count) for w, count in tf.items()}
    return [w for w, _ in sorted(scored.items(), key=lambda x: -x[1])[:top_n]]


def tag_document(path: Path, doc_id: str, source_key: str) -> DocumentMetadata:
    text = path.read_text(encoding="utf-8", errors="ignore")

    # Pass 1: regex
    tags = _regex_pass(text)

    # Pass 2: TF-IDF keywords
    keywords = _tfidf_keywords(text)

    # Pass 3: Claude fallback only needed if doc_type is ambiguous
    # (not invoked in local demo mode — would call Anthropic API with structured output)
    tag_method = "regex"

    return DocumentMetadata(
        doc_id=doc_id,
        source_key=source_key,
        doc_type=tags["doc_type"],
        ingested_at=datetime.now(),
        regulation_refs=tags["regulation_refs"],
        loan_types=tags["loan_types"],
        effective_date=tags.get("effective_date"),
        risk_tier=tags["risk_tier"],
        version=tags.get("version", ""),
        keywords=keywords,
    )
