"""Central tool registry: Anthropic tool definitions + dispatch."""
from src.agent.tools.knowledge_base_tool import query_policy_knowledge_base
from src.agent.tools.crm_tool import lookup_borrower_crm
from src.agent.tools.compliance_tool import check_compliance_rules
from src.agent.tools.calculator_tool import compute_dscr_ltv

TOOL_DEFINITIONS = [
    {
        "name": "query_policy_knowledge_base",
        "description": (
            "Search the lending policy knowledge base for relevant regulations, "
            "underwriting criteria, and compliance requirements. Returns retrieved "
            "policy chunks with source attribution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about lending policy or compliance",
                },
                "loan_type": {
                    "type": "string",
                    "enum": ["SBA", "CRE", "C&I", "construction", "USDA", "all"],
                    "description": "Filter results to a specific loan type (default: all)",
                },
                "regulation": {
                    "type": "string",
                    "description": "Optional regulation filter e.g. 'ECOA', 'BSA', 'OFAC'",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to retrieve (default: 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_borrower_crm",
        "description": (
            "Look up borrower/customer information from the CRM system. "
            "Returns profile data, KYC/AML status, and existing loan applications."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "borrower_id": {
                    "type": "string",
                    "description": "Customer ID (e.g. 'CUST-001')",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: specific fields to return (returns all if omitted)",
                },
            },
            "required": ["borrower_id"],
        },
    },
    {
        "name": "check_compliance_rules",
        "description": (
            "Check applicable compliance rules for a given regulation category, "
            "loan amount, and borrower type. Returns mandatory and advisory rules."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_category": {
                    "type": "string",
                    "enum": ["ECOA", "BSA", "CRA", "TILA", "RESPA", "AML", "OFAC", "SBA"],
                    "description": "The regulation to check rules for",
                },
                "loan_amount": {
                    "type": "number",
                    "description": "Loan amount in USD — used to filter amount-threshold rules",
                },
                "borrower_type": {
                    "type": "string",
                    "enum": ["individual", "business", "non-profit"],
                    "description": "Type of borrower entity",
                },
            },
            "required": ["rule_category"],
        },
    },
    {
        "name": "compute_dscr_ltv",
        "description": (
            "Calculate Debt Service Coverage Ratio (DSCR) and Loan-to-Value (LTV) "
            "for a commercial loan. Compares results against standard policy thresholds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "noi": {
                    "type": "number",
                    "description": "Net Operating Income (annual, USD)",
                },
                "annual_debt_service": {
                    "type": "number",
                    "description": "Total annual principal + interest payments (USD)",
                },
                "appraised_value": {
                    "type": "number",
                    "description": "Appraised value of collateral (USD)",
                },
                "loan_amount": {
                    "type": "number",
                    "description": "Proposed loan amount (USD)",
                },
            },
            "required": ["noi", "annual_debt_service", "appraised_value", "loan_amount"],
        },
    },
]

_DISPATCH = {
    "query_policy_knowledge_base": query_policy_knowledge_base,
    "lookup_borrower_crm": lookup_borrower_crm,
    "check_compliance_rules": check_compliance_rules,
    "compute_dscr_ltv": compute_dscr_ltv,
}


def dispatch(tool_name: str, tool_input: dict) -> str:
    fn = _DISPATCH.get(tool_name)
    if not fn:
        return f"Unknown tool: {tool_name}"
    return fn(**tool_input)
