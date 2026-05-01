"""Tool: check_compliance_rules — looks up applicable rules by regulation and loan params."""
import json
from db.session import get_conn


def check_compliance_rules(
    rule_category: str,
    loan_amount: float | None = None,
    borrower_type: str | None = None,
) -> str:
    reg = rule_category.upper()

    with get_conn() as conn:
        query = "SELECT * FROM compliance_rules WHERE regulation = ?"
        params: list = [reg]

        if loan_amount is not None:
            query += " AND (min_loan_amount IS NULL OR min_loan_amount <= ?)"
            params.append(loan_amount)
            query += " AND (max_loan_amount IS NULL OR max_loan_amount >= ?)"
            params.append(loan_amount)

        if borrower_type:
            query += " AND (borrower_type IS NULL OR borrower_type = ?)"
            params.append(borrower_type)

        query += " ORDER BY severity"
        rules = conn.execute(query, params).fetchall()

    if not rules:
        return f"No compliance rules found for regulation: {reg}"

    result = {
        "regulation": reg,
        "applicable_rules": [
            {
                "rule_id": r["rule_id"],
                "category": r["category"],
                "severity": r["severity"],
                "rule_text": r["rule_text"],
                "source": r["source_doc_ref"],
                "effective_date": r["effective_date"],
            }
            for r in rules
        ],
        "mandatory_count": sum(1 for r in rules if r["severity"] == "mandatory"),
    }
    return json.dumps(result, indent=2, default=str)
