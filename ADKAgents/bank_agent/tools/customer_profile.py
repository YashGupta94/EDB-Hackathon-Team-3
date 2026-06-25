import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from ..observability.tool_tracer import traced_tool

load_dotenv(
    str(Path(__file__).resolve().parent.parent / ".env"),
    override=False,
)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
BQ_DATASET = os.getenv("BQ_DATASET", "")


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)


def _life_stage(age: int, income_band: str, product_types: list[str], has_childcare: bool) -> str:
    if age <= 24:
        return "Student / Early Career"
    if age <= 35:
        return "Young Family" if has_childcare else "Young Professional"
    if age <= 50:
        return "Young Family" if has_childcare else "Established Professional"
    if age <= 65:
        return "Pre-Retirement"
    return "Retired"


def _risk_appetite(age: int, product_types: list[str], savings_rate: float) -> str:
    has_stocks_isa = any("stocks" in p.lower() or "shares" in p.lower() for p in product_types)
    if age < 35 and savings_rate >= 0.15:
        return "Adventurous" if has_stocks_isa else "Moderate"
    if age >= 55:
        return "Conservative"
    return "Moderate"


def _product_gaps(product_types: list[str], age: int) -> list[str]:
    gaps = []
    normalised = [p.lower() for p in product_types]
    has_current = any("current" in p for p in normalised)
    has_savings = any("savings" in p or "isa" in p or "bond" in p for p in normalised)
    has_isa = any("isa" in p for p in normalised)
    has_cash_isa = any("cash isa" in p for p in normalised)
    has_stocks_isa = any("stocks" in p or "shares" in p for p in normalised)
    has_lifetime_isa = any("lifetime" in p for p in normalised)
    has_mortgage = any("mortgage" in p for p in normalised)

    if not has_savings:
        gaps.append("No savings product — missing out on interest")
    if not has_isa:
        gaps.append("No ISA — paying unnecessary tax on savings interest")
    elif not has_cash_isa:
        gaps.append("No Cash ISA — consider adding for tax-free guaranteed returns")
    if not has_stocks_isa and age < 50:
        gaps.append("No Stocks & Shares ISA — missing long-term growth potential")
    if not has_lifetime_isa and 18 <= age <= 39:
        gaps.append("No Lifetime ISA — eligible for 25% government bonus (open before age 40)")
    if has_mortgage and not any("insurance" in p or "protection" in p for p in normalised):
        gaps.append("No mortgage protection insurance detected")
    return gaps


@traced_tool
def get_customer_profile(customer_id: str) -> str:
    """Builds a detailed financial profile for a customer including life stage, income estimate,
    savings overview, product gaps, premier eligibility, and risk appetite.

    Args:
        customer_id: The customer ID (e.g. C001)

    Returns:
        A formatted profile string with all key financial signals.
    """
    try:
        if not PROJECT_ID or not BQ_DATASET:
            return "Error: GOOGLE_CLOUD_PROJECT or BQ_DATASET not configured."

        client = _bq_client()

        cust_sql = f"""
            SELECT customer_id, name, age, gender, postcode, address, email, income_band, dob
            FROM `{BQ_DATASET}.customers`
            WHERE customer_id = @cid
        """
        cust_df = client.query(
            cust_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        if cust_df.empty:
            return f"No customer found for ID {customer_id}."

        cust = cust_df.iloc[0]

        acct_sql = f"""
            SELECT account_id, product_type, balance, opened_date, interest_rate
            FROM `{BQ_DATASET}.accounts`
            WHERE customer_id = @cid
        """
        acct_df = client.query(
            acct_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        txn_sql = f"""
            SELECT t.amount, t.category, t.description, t.date
            FROM `{BQ_DATASET}.transactions` t
            JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
            WHERE a.customer_id = @cid
              AND DATE(t.date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        """
        txn_df = client.query(
            txn_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        product_types = acct_df["product_type"].tolist() if not acct_df.empty else []
        total_assets = acct_df[acct_df["balance"] > 0]["balance"].sum() if not acct_df.empty else 0.0
        total_debt = abs(acct_df[acct_df["balance"] < 0]["balance"].sum()) if not acct_df.empty else 0.0

        monthly_income = 0.0
        monthly_expenses = 0.0
        has_childcare = False
        if not txn_df.empty:
            credits = txn_df[txn_df["amount"] > 0]["amount"]
            debits = txn_df[txn_df["amount"] < 0]["amount"]
            monthly_income = credits.sum() / 3.0
            monthly_expenses = abs(debits.sum()) / 3.0
            has_childcare = txn_df["category"].str.lower().str.contains("childcare").any()

        savings_deposits = 0.0
        if not txn_df.empty:
            sav = txn_df[txn_df["category"] == "Savings"]
            savings_deposits = sav[sav["amount"] > 0]["amount"].sum() / 3.0

        savings_rate = (savings_deposits / monthly_income) if monthly_income > 0 else 0.0

        age = int(cust["age"])
        income_band = str(cust.get("income_band", ""))
        life_stage = _life_stage(age, income_band, product_types, has_childcare)
        risk = _risk_appetite(age, product_types, savings_rate)
        gaps = _product_gaps(product_types, age)

        annual_income_estimate = monthly_income * 12
        premier_eligible = (
            annual_income_estimate >= 75000
            or total_assets >= 100000
            or income_band == "75k_plus"
        )

        has_mortgage = any("mortgage" in p.lower() for p in product_types)
        acct_lines = "\n".join(
            f"  • {row['product_type']} ({row['account_id']})  Balance: £{row['balance']:,.2f}  "
            f"Rate: {row['interest_rate']*100:.1f}%  Opened: {row['opened_date']}"
            for _, row in acct_df.iterrows()
        ) if not acct_df.empty else "  No accounts found."

        gap_lines = "\n".join(f"  ⚠ {g}" for g in gaps) if gaps else "  ✓ No major product gaps detected."

        return "\n".join([
            f"Customer Profile — {cust['name']} ({customer_id})",
            f"{'='*55}",
            f"Age            : {age}  |  Gender: {cust['gender']}  |  Location: {cust['postcode']}",
            f"Life Stage     : {life_stage}",
            f"Income Band    : {income_band}",
            f"Est. Monthly Income  : £{monthly_income:,.2f}  (annualised: £{annual_income_estimate:,.2f})",
            f"Est. Monthly Expenses: £{monthly_expenses:,.2f}",
            f"Monthly Savings Rate : {savings_rate*100:.1f}%",
            f"",
            f"Financial Position:",
            f"  Total Assets : £{total_assets:,.2f}",
            f"  Total Debt   : £{total_debt:,.2f}",
            f"  Has Mortgage : {'Yes' if has_mortgage else 'No'}",
            f"  Has Childcare Costs: {'Yes' if has_childcare else 'No'}",
            f"",
            f"Risk Appetite  : {risk}",
            f"Premier Eligible: {'Yes ★' if premier_eligible else 'No'}",
            f"",
            f"Current Products:",
            acct_lines,
            f"",
            f"Product Gaps & Opportunities:",
            gap_lines,
        ])

    except Exception as e:
        return f"Customer Profile Error: {str(e)}"
