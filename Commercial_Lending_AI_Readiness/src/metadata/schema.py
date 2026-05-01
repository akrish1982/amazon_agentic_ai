"""Canonical document metadata schema for the lending AI knowledge base."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

DocType = Literal["policy", "guideline", "regulation", "form", "memo"]
RiskTier = Literal["low", "medium", "high", "critical"]
Jurisdiction = Literal["federal", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL",
                       "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
                       "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
                       "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
                       "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]


@dataclass
class DocumentMetadata:
    # Required at ingest
    doc_id: str
    source_key: str
    doc_type: DocType
    ingested_at: datetime

    # Auto-tagged (enrichment)
    regulation_refs: list[str] = field(default_factory=list)
    loan_types: list[str] = field(default_factory=list)
    effective_date: date | None = None
    expiry_date: date | None = None
    jurisdiction: str = "federal"
    risk_tier: RiskTier = "medium"
    version: str = ""
    keywords: list[str] = field(default_factory=list)

    # S3 storage info
    s3_key: str = ""
    file_size_bytes: int = 0
    checksum: str = ""

    def s3_tags(self) -> dict[str, str]:
        """Max 10 S3 object tags — used for server-side filtering and lifecycle policies."""
        tags = {
            "doc_type": self.doc_type,
            "risk_tier": self.risk_tier,
            "jurisdiction": self.jurisdiction,
        }
        if self.regulation_refs:
            tags["regulation_refs"] = ",".join(self.regulation_refs[:3])  # S3 tag max 256 chars
        if self.loan_types:
            tags["loan_types"] = ",".join(self.loan_types)
        if self.version:
            tags["version"] = self.version
        if self.effective_date:
            tags["effective_date"] = str(self.effective_date)
        if self.expiry_date:
            tags["expiry_date"] = str(self.expiry_date)
        return tags
