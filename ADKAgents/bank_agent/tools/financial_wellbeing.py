import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext
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


def _score_bar(score: int, max_score: int = 25, width: int = 20) -> str:
    filled = int((score / max_score) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {score}/{max_score}"


def _emergency_fund_score(savings: float, monthly_expenses: float) -> tuple[int, str]:
    if monthly_expenses <= 0:
        return 12, "Unable to calculate — no expense data"
    months_covered = savings / monthly_expenses
    if months_covered >= 6:
        return 25, f"Excellent — {months_covered:.1f} months of expenses covered (target: 3–6 months)"
    if months_covered >= 3:
        return 20, f"Good — {months_covered:.1f} months covered (target: 3–6 months)"
    if months_covered >= 1:
        return 10, f"Needs attention — only {months_covered:.1f} months covered (target: 3 months minimum)"
    return 3, f"Critical — less than 1 month of expenses in accessible savings (£{savings:,.0f} vs £{monthly_expenses:,.0f}/month needed)"


def _savings_rate_score(monthly_savings: float, monthly_income: float) -> tuple[int, str]:
    if monthly_income <= 0:
        return 12, "Unable to calculate — no income detected"
    rate = (monthly_savings / monthly_income) * 100
    if rate >= 20:
        return 25, f"Excellent — saving {rate:.1f}% of income (target: 20%+)"
    if rate >= 10:
        return 18, f"Good — saving {rate:.1f}% of income (target: 20%)"
    if rate >= 5:
        return 10, f"Fair — saving {rate:.1f}% of income (target: 20%)"
    return 3, f"Low — only {rate:.1f}% of income saved (target: minimum 5%)"


def _debt_score(monthly_debt_payments: float, monthly_income: float, total_debt: float) -> tuple[int, str]:
    if monthly_income <= 0:
        return 12, "Unable to calculate — no income detected"
    if total_debt == 0 and monthly_debt_payments == 0:
        return 25, "Excellent — no debt commitments"
    dti = (monthly_debt_payments / monthly_income) * 100
    if dti <= 15:
        return 22, f"Very good — debt payments are {dti:.1f}% of income (healthy threshold: <28%)"
    if dti <= 28:
        return 16, f"Manageable — debt payments are {dti:.1f}% of income (threshold: 28%)"
    if dti <= 43:
        return 8, f"High — debt payments are {dti:.1f}% of income (risk threshold exceeded)"
    return 2, f"Critical — debt payments are {dti:.1f}% of income (above 43% severely limits financial flexibility)"


def _budget_score(customer_id: str, client: bigquery.Client) -> tuple[int, str]:
    try:
        sql = f"""
            WITH actual AS (
                SELECT t.category, SUM(ABS(t.amount)) AS actual_spend
                FROM `{BQ_DATASET}.transactions` t
                JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
                WHERE a.customer_id = @cid
                  AND t.amount < 0
                  AND t.category != 'Savings'
                  AND DATE(t.date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
                GROUP BY t.category
            ),
            budget AS (
                SELECT category, monthly_budget_gbp
                FROM `{BQ_DATASET}.budgets`
                WHERE customer_id = @cid
            )
            SELECT
                b.category,
                b.monthly_budget_gbp AS budget,
                COALESCE(a.actual_spend, 0) AS actual,
                COALESCE(a.actual_spend, 0) - b.monthly_budget_gbp AS variance
            FROM budget b
            LEFT JOIN actual a ON b.category = a.category
        """
        df = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        if df.empty:
            return 12, "No budget data configured for this customer"

        over_budget = df[df["variance"] > 0]
        categories_over = len(over_budget)
        total_cats = len(df)
        pct_on_budget = ((total_cats - categories_over) / total_cats) * 100 if total_cats > 0 else 0

        total_budget = df["budget"].sum()
        total_actual = df["actual"].sum()
        total_variance = total_actual - total_budget

        if categories_over == 0:
            score = 25
            detail = f"Excellent — within budget across all {total_cats} categories"
        elif categories_over <= 1:
            score = 18
            detail = f"Good — {categories_over}/{total_cats} categories over budget"
        elif categories_over <= 2:
            score = 12
            detail = f"Fair — {categories_over}/{total_cats} categories over budget"
        else:
            score = 5
            detail = f"Needs work — {categories_over}/{total_cats} categories over budget"

        over_list = ""
        if not over_budget.empty:
            items = [f"{r['category']} (£{r['variance']:+,.0f})" for _, r in over_budget.iterrows()]
            over_list = f"  Categories over: {', '.join(items)}"

        variance_str = f"Total monthly variance: £{total_variance:+,.0f}"
        full_detail = f"{detail}. {variance_str}"
        if over_list:
            full_detail += f"\n{over_list}"
        return score, full_detail

    except Exception:
        return 12, "Budget data unavailable"


def _isa_utilisation(customer_id: str, client: bigquery.Client) -> tuple[str, str]:
    try:
        sql = f"""
            SELECT product_type, balance
            FROM `{BQ_DATASET}.accounts`
            WHERE customer_id = @cid
              AND LOWER(product_type) LIKE '%isa%'
        """
        df = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()
        if df.empty:
            return "None", "No ISA held — £20,000 annual allowance completely unused"
        total = df["balance"].sum()
        types = ", ".join(df["product_type"].tolist())
        return types, f"£{total:,.2f} across {types} — review annual allowance usage"
    except Exception:
        return "Unknown", "ISA data unavailable"


@traced_tool
def calculate_wellbeing_score(customer_id: str, tool_context: ToolContext) -> str:
    """Calculates a comprehensive Financial Wellbeing Score (0–100) for a customer.
    The score covers four pillars: Emergency Fund, Savings Rate, Debt Management,
    and Budget Adherence. Includes an ISA utilisation check and personalised action plan.

    Args:
        customer_id: The customer ID (e.g. C001). If empty, falls back to the verified session customer.

    Returns:
        A formatted wellbeing report with score breakdown and recommendations.
    """
    try:
        if not customer_id:
            customer_id = tool_context.state.get("verified_customer_id", "")
        if not customer_id:
            return "No customer ID provided and no verified customer in session. Please verify customer identity first."
        if not tool_context.state.get("identity_verified"):
            return "Customer identity has not been verified. Please verify the customer via customer_agent before accessing personal data."
        if not PROJECT_ID or not BQ_DATASET:
            return "Error: GOOGLE_CLOUD_PROJECT or BQ_DATASET not configured."

        client = _bq_client()

        cust_sql = f"""
            SELECT c.name, c.age,
                   a.product_type, a.balance
            FROM `{BQ_DATASET}.customers` c
            LEFT JOIN `{BQ_DATASET}.accounts` a ON c.customer_id = a.customer_id
            WHERE c.customer_id = @cid
        """
        cust_df = client.query(
            cust_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        if cust_df.empty:
            return f"No customer found for ID {customer_id}."

        name = str(cust_df.iloc[0]["name"])
        total_savings = cust_df[cust_df["balance"] > 0]["balance"].sum()
        total_debt = abs(cust_df[cust_df["balance"] < 0]["balance"].sum())
        accessible_savings = cust_df[
            cust_df["product_type"].str.lower().str.contains("savings|current|isa", na=False)
            & (cust_df["balance"] > 0)
        ]["balance"].sum()

        txn_sql = f"""
            SELECT t.amount, t.category, t.description, DATE(t.date) AS txn_date
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

        monthly_income = 0.0
        monthly_expenses = 0.0
        monthly_savings_contributions = 0.0
        monthly_debt_payments = 0.0
        if not txn_df.empty:
            monthly_income = txn_df[txn_df["amount"] > 0]["amount"].sum() / 3.0
            monthly_expenses = abs(txn_df[txn_df["amount"] < 0]["amount"].sum()) / 3.0
            sav = txn_df[(txn_df["category"] == "Savings") & (txn_df["amount"] > 0)]
            monthly_savings_contributions = sav["amount"].sum() / 3.0
            housing_txns = txn_df[
                (txn_df["category"] == "Housing") & (txn_df["amount"] < 0) &
                (txn_df["description"].str.lower().str.contains("mortgage"))
            ]
            monthly_debt_payments = abs(housing_txns["amount"].sum()) / 3.0

        ef_score, ef_detail = _emergency_fund_score(accessible_savings, monthly_expenses)
        sr_score, sr_detail = _savings_rate_score(monthly_savings_contributions, monthly_income)
        dt_score, dt_detail = _debt_score(monthly_debt_payments, monthly_income, total_debt)
        bud_score, bud_detail = _budget_score(customer_id, client)

        total_score = ef_score + sr_score + dt_score + bud_score

        if total_score >= 80:
            rating = "Excellent ★★★★★"
            summary = "Your finances are in great shape. Focus on optimising tax efficiency and long-term growth."
        elif total_score >= 65:
            rating = "Good ★★★★"
            summary = "Solid financial foundations. A few targeted improvements could unlock significant benefits."
        elif total_score >= 50:
            rating = "Fair ★★★"
            summary = "Some areas need attention. Prioritise building your emergency fund and increasing savings rate."
        elif total_score >= 35:
            rating = "Needs Improvement ★★"
            summary = "Multiple financial risks identified. We recommend speaking with one of our financial advisers."
        else:
            rating = "At Risk ★"
            summary = "Urgent action recommended. Please contact us to discuss a financial health plan."

        isa_types, isa_detail = _isa_utilisation(customer_id, client)

        actions = []
        if ef_score < 15:
            actions.append("• Open an Easy Access Savings Account to build a 3-month emergency fund")
        if sr_score < 15:
            actions.append("• Set up a standing order to a savings account (even £50/month builds the habit)")
        if bud_score < 15:
            actions.append("• Review your budget — use our app's spending tracker to stay on target")
        if isa_types == "None":
            actions.append("• Open a Cash ISA before April 5th to use this year's £20,000 allowance")
        if total_debt > 0 and monthly_debt_payments / max(monthly_income, 1) > 0.28:
            actions.append("• Consider overpaying your mortgage to reduce long-term interest costs")
        if not actions:
            actions.append("• Consider a Stocks & Shares ISA or Fixed-Rate Bond to maximise returns")
            actions.append("• Review your ISA allowance annually — any unused allowance cannot be carried forward")

        return "\n".join([
            f"Financial Wellbeing Report — {name} ({customer_id})",
            f"{'='*55}",
            f"",
            f"Overall Score: {total_score}/100  |  Rating: {rating}",
            f"",
            f"Summary: {summary}",
            f"",
            f"{'─'*55}",
            f"Pillar 1 — Emergency Fund  {_score_bar(ef_score)}",
            f"  {ef_detail}",
            f"  Accessible savings: £{accessible_savings:,.2f}  |  Monthly expenses: £{monthly_expenses:,.2f}",
            f"",
            f"Pillar 2 — Savings Rate    {_score_bar(sr_score)}",
            f"  {sr_detail}",
            f"  Monthly savings contributions: £{monthly_savings_contributions:,.2f}  |  Monthly income: £{monthly_income:,.2f}",
            f"",
            f"Pillar 3 — Debt Management {_score_bar(dt_score)}",
            f"  {dt_detail}",
            f"  Total outstanding debt: £{total_debt:,.2f}  |  Monthly debt payments: £{monthly_debt_payments:,.2f}",
            f"",
            f"Pillar 4 — Budget Control  {_score_bar(bud_score)}",
            f"  {bud_detail}",
            f"",
            f"{'─'*55}",
            f"ISA Utilisation:",
            f"  {isa_detail}",
            f"",
            f"Recommended Actions:",
            "\n".join(actions),
        ])

    except Exception as e:
        print(f"[financial_wellbeing] ERROR for customer_id={customer_id!r}: {type(e).__name__}: {e}")
        return f"Financial Wellbeing Error: {str(e)}"
