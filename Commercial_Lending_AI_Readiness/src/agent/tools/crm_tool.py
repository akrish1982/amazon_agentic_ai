"""Tool: lookup_borrower_crm — queries the CRM SQLite database."""
import json
from db.session import get_conn


def lookup_borrower_crm(borrower_id: str, fields: list[str] | None = None) -> str:
    with get_conn() as conn:
        customer = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (borrower_id,)
        ).fetchone()

        if not customer:
            return f"No customer found with ID: {borrower_id}"

        data = dict(customer)

        # Also fetch loan applications
        apps = conn.execute(
            """SELECT app_id, loan_type, requested_amount, purpose, status, submitted_at
               FROM loan_applications WHERE customer_id = ?""",
            (borrower_id,),
        ).fetchall()

    if fields:
        data = {k: v for k, v in data.items() if k in fields}

    result = {
        "customer": data,
        "loan_applications": [dict(a) for a in apps],
    }

    # Flag compliance concerns clearly for the agent
    warnings = []
    if customer["aml_flag"]:
        warnings.append("AML_FLAG: Customer has active AML flag — escalation required")
    if customer["kyc_status"] in ("pending", "expired", "flagged"):
        warnings.append(f"KYC_STATUS: {customer['kyc_status'].upper()} — verify before proceeding")

    if warnings:
        result["compliance_warnings"] = warnings

    return json.dumps(result, indent=2, default=str)
