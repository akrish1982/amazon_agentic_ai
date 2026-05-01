"""Populate all tables with realistic commercial lending seed data."""
import json
from db.session import get_conn

CUSTOMERS = [
    ("CUST-001", "Apex Manufacturing LLC", "82-1234567", "332999", 12, 4_200_000, 720,
     "07-123-4567", "555-0101", "cfo@apexmfg.com", "450 Industrial Blvd", "TX", "Sarah Chen",
     "approved", 0, "2026-01-15"),
    ("CUST-002", "Riverfront Hospitality Group", "45-9876543", "721110", 8, 2_800_000, 680,
     None, "555-0102", "owner@riverfronthotel.com", "12 Harbor View Dr", "FL", "James Patel",
     "approved", 0, "2026-02-01"),
    ("CUST-003", "GreenLeaf Agri Partners", "91-3456789", "111991", 3, 950_000, 640,
     "07-654-3210", "555-0103", None, "Rural Route 4", "IA", "Maria Torres",
     "pending", 0, "2026-03-10"),
    ("CUST-004", "Northstar Real Estate Dev", "63-7890123", "531110", 15, 9_500_000, 755,
     "07-111-2222", "555-0104", "finance@northstardev.com", "88 Commerce Plaza", "NY", "Sarah Chen",
     "approved", 0, "2025-12-01"),
    ("CUST-005", "Coastal Medical Supplies Inc", "27-5551234", "423450", 6, 1_750_000, 695,
     "07-333-4444", "555-0105", "ar@coastalmed.com", "2200 Health Pkwy", "CA", "James Patel",
     "approved", 0, "2026-01-20"),
    ("CUST-006", "Delta Logistics Partners", "58-4321987", "484121", 4, 3_100_000, 660,
     None, "555-0106", "ops@deltalog.com", "5500 Freight Way", "GA", "Maria Torres",
     "flagged", 1, "2026-03-05"),
    ("CUST-007", "Summit Construction Group", "74-6543210", "236220", 20, 14_000_000, 780,
     "07-555-6666", "555-0107", "cfo@summitcg.com", "One Builder Plaza", "CO", "Sarah Chen",
     "approved", 0, "2025-11-01"),
    ("CUST-008", "Lakeside Veterinary Clinics", "36-8901234", "541940", 9, 820_000, 710,
     None, "555-0108", "admin@lakevets.com", "300 Pet Care Ln", "MN", "James Patel",
     "approved", 0, "2026-02-28"),
]

LOAN_APPLICATIONS = [
    ("APP-001", "CUST-001", "C&I", 1_500_000, "Equipment purchase and working capital",
     1_800_000, 187_500, 162_000, "underwriting", "2026-04-01", None),
    ("APP-002", "CUST-002", "SBA", 850_000, "Hotel renovation — SBA 7(a)",
     1_200_000, 98_000, 82_500, "submitted", "2026-04-10", None),
    ("APP-003", "CUST-004", "CRE", 2_500_000, "Mixed-use commercial acquisition",
     4_100_000, 312_000, 228_000, "underwriting", "2026-03-15", None),
    ("APP-004", "CUST-007", "construction", 5_000_000, "Office park development",
     7_500_000, 550_000, 480_000, "approved", "2026-02-01", "2026-04-20"),
    ("APP-005", "CUST-005", "SBA", 450_000, "Medical equipment — SBA 504",
     600_000, 72_000, 58_000, "approved", "2026-03-01", "2026-04-15"),
]

COMPLIANCE_RULES = [
    ("RULE-ECOA-001", "ECOA", "Anti-discrimination",
     "Lender must not discriminate based on race, color, religion, national origin, sex, marital status, or age. "
     "15 U.S.C. § 1691. All credit decisions must be documented with non-discriminatory underwriting criteria.",
     None, None, None, None, "mandatory", "1974-10-28", "ECOA §202.6"),
    ("RULE-ECOA-002", "ECOA", "Adverse action",
     "Provide written notice within 30 days of adverse credit decision stating specific reasons. "
     "Reg B §202.9. Must retain records for 25 months for business credit.",
     None, None, None, "business", "mandatory", "1974-10-28", "Reg B §202.9"),
    ("RULE-BSA-001", "BSA", "SAR filing",
     "File Suspicious Activity Report (FinCEN 111) within 30 days of detection for transactions "
     "≥$5,000 involving suspected money laundering or fraud. 31 U.S.C. § 5318(g).",
     None, 5_000, None, None, "mandatory", "1970-10-26", "BSA §5318(g)"),
    ("RULE-BSA-002", "BSA", "CTR filing",
     "File Currency Transaction Report (FinCEN 112) for cash transactions exceeding $10,000. "
     "31 C.F.R. § 1010.311. Aggregation rules apply across same-day transactions.",
     None, 10_000, None, None, "mandatory", "1970-10-26", "BSA §1010.311"),
    ("RULE-CRA-001", "CRA", "Community reinvestment",
     "Banks must affirmatively help meet credit needs of all community segments, including LMI. "
     "12 U.S.C. § 2901. CRE loans in assessment areas count toward CRA credit.",
     "CRE", None, None, None, "advisory", "1977-10-12", "CRA §2901"),
    ("RULE-SBA-001", "SBA", "SBA 7(a) eligibility",
     "Borrower must be for-profit, operate in US, have reasonable owner equity, and have exhausted "
     "other financing. Maximum loan amount $5M. SBA SOP 50 10 7.",
     "SBA", None, 5_000_000, "business", "mandatory", "2023-01-01", "SBA SOP 50 10 7"),
    ("RULE-SBA-002", "SBA", "SBA 504 eligibility",
     "Tangible net worth ≤$20M and average net income ≤$6.5M for 2 years. Fixed assets only. "
     "CDC/SBA 504 debenture max $5.5M for standard projects, $5.5M for energy public policy.",
     "SBA", None, 5_500_000, "business", "mandatory", "2023-01-01", "SBA SOP 50 10 7 §2"),
    ("RULE-TILA-001", "TILA", "APR disclosure",
     "Disclose APR, finance charge, amount financed, and total of payments before consummation. "
     "15 U.S.C. § 1638. Business credit >$54,600 is generally exempt from Reg Z consumer provisions.",
     None, None, 54_600, "individual", "mandatory", "1968-07-01", "TILA §1638"),
    ("RULE-AML-001", "AML", "Customer due diligence",
     "Collect and verify beneficial ownership for legal entity customers with 25%+ ownership. "
     "31 C.F.R. § 1010.230. CDD must be refreshed on material change or at least every 3 years.",
     None, None, None, "business", "mandatory", "2018-05-11", "FinCEN CDD Rule §1010.230"),
    ("RULE-OFAC-001", "OFAC", "Sanctions screening",
     "Screen all parties against OFAC SDN list before loan origination and at account review. "
     "50 U.S.C. § 1705. Zero-tolerance — any match requires immediate blocking and reporting.",
     None, None, None, None, "mandatory", "1977-12-28", "OFAC §1705"),
]


def seed_all() -> None:
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO customers
               (customer_id,business_name,ein,naics_code,years_in_business,annual_revenue,
                credit_score,duns_number,phone,email,address,state,relationship_mgr,
                kyc_status,aml_flag,ofac_checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            CUSTOMERS,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO loan_applications
               (app_id,customer_id,loan_type,requested_amount,purpose,collateral_value,
                noi,annual_debt_service,status,submitted_at,decided_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            LOAN_APPLICATIONS,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO compliance_rules
               (rule_id,regulation,category,rule_text,loan_type,min_loan_amount,
                max_loan_amount,borrower_type,severity,effective_date,source_doc_ref)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            COMPLIANCE_RULES,
        )
    print(f"  Seeded {len(CUSTOMERS)} customers, {len(LOAN_APPLICATIONS)} loan apps, "
          f"{len(COMPLIANCE_RULES)} compliance rules")
