"""Tool: compute_dscr_ltv — pure financial calculations, no DB call."""
import json


def compute_dscr_ltv(
    noi: float,
    annual_debt_service: float,
    appraised_value: float,
    loan_amount: float,
) -> str:
    dscr = noi / annual_debt_service if annual_debt_service else 0.0
    ltv = (loan_amount / appraised_value * 100) if appraised_value else 0.0

    # Policy thresholds (from underwriting_policy_v3.txt)
    dscr_thresholds = {"C&I": 1.25, "CRE": 1.20, "SBA": 1.15, "construction": 1.20}
    ltv_thresholds = {"owner-occupied CRE": 80.0, "investment CRE": 75.0, "equipment": 70.0}

    dscr_flags = [
        f"BELOW minimum for {loan_type} ({threshold}x)"
        for loan_type, threshold in dscr_thresholds.items()
        if dscr < threshold
    ]

    ltv_flags = [
        f"EXCEEDS maximum for {prop_type} ({threshold}%)"
        for prop_type, threshold in ltv_thresholds.items()
        if ltv > threshold
    ]

    result = {
        "dscr": round(dscr, 4),
        "ltv_percent": round(ltv, 2),
        "inputs": {
            "noi": noi,
            "annual_debt_service": annual_debt_service,
            "appraised_value": appraised_value,
            "loan_amount": loan_amount,
        },
        "dscr_policy_alerts": dscr_flags or ["DSCR meets all standard thresholds"],
        "ltv_policy_alerts": ltv_flags or ["LTV within all standard thresholds"],
        "summary": (
            f"DSCR: {dscr:.2f}x | LTV: {ltv:.1f}% | "
            f"{'POLICY CONCERNS' if dscr_flags or ltv_flags else 'Within policy'}"
        ),
    }
    return json.dumps(result, indent=2)
