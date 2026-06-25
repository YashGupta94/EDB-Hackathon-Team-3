import math
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


_EXISTING_PRODUCT_ALIASES: dict = {
    "current_account": ["current account", "premier current account", "student current account"],
    "cash_isa": ["cash isa"],
    "stocks_isa": ["stocks & shares isa", "stocks and shares isa"],
    "lifetime_isa": ["lifetime isa"],
    "junior_isa": ["junior isa"],
    "fixed_bond": ["fixed-rate bond", "fixed rate bond"],
    "regular_saver": ["regular saver"],
    "mortgage": ["mortgage"],
    "help_to_save": ["help to save"],
    "insurance": ["home insurance", "buildings insurance", "contents insurance"],
}


def _score_product(product: dict, age: int, annual_income: float, total_assets: float,
                   existing_types: list[str], life_stage: str, has_childcare: bool,
                   has_mortgage: bool, income_band: str) -> tuple[int, str]:
    """Score a product 0-100 for relevance to this customer. Returns (score, reason)."""
    ptype = product["product_type"]
    score = 0
    reasons = []

    existing_lower = [e.lower() for e in existing_types]
    aliases = _EXISTING_PRODUCT_ALIASES.get(ptype, [ptype.replace("_", " ")])
    already_has = any(any(alias in e for alias in aliases) for e in existing_lower)

    age_ok = (product["min_age"] is None or age >= product["min_age"]) and \
             (product["max_age"] is None or age <= product["max_age"])
    if not age_ok:
        return 0, "Not eligible (age requirement not met)"

    requires_ca = product.get("requires_current_account", False)
    has_ca = any("current" in e for e in existing_lower)
    if requires_ca and not has_ca:
        return 0, "Requires a current account with us"

    if ptype == "current_account":
        is_premier_product = "premier" in product["name"].lower()
        is_student_product = "student" in product["name"].lower()
        already_has_premier = any("premier" in e for e in existing_lower)
        eligible_for_premier = (income_band == "75k_plus" or total_assets >= 100000)

        if is_premier_product:
            if not eligible_for_premier:
                return 0, "Not eligible — Premier requires income £75,000+ or savings £100,000+"
            if already_has_premier:
                return 0, "Already holds a Premier account"
            score = 90
            if income_band == "75k_plus":
                reasons.append("Income qualifies for Premier benefits — airport lounges, travel insurance, £25/month")
            else:
                reasons.append("Savings qualify for Premier status — exclusive benefits worth £300+/year")
        elif is_student_product:
            if age > 25:
                return 0, "Student account requires current full-time education (up to age 25)"
            if already_has:
                return 0, "Already holds a current account"
            score = 70
            reasons.append("No fees, 0% overdraft up to £1,000, and exclusive student perks")
        else:
            if already_has:
                return 0, "Already holds a current account"
            if eligible_for_premier:
                return 0, "Income/savings qualify for Premier — consider upgrading for better value"
            score = 40
            reasons.append("No monthly fee current account — open in minutes with card access")

    elif ptype == "cash_isa":
        if already_has:
            return 0, "Already holds a Cash ISA"
        score = 75
        reasons.append("Tax-free interest at 4.5% AER, £20,000 annual allowance")
        if annual_income > 50000:
            score += 10
            reasons.append("Higher-rate taxpayer benefits more from tax-free wrapper")
        if life_stage in ("Young Professional", "Established Professional"):
            score += 10
            reasons.append("Ideal accumulation phase for ISA allowance")

    elif ptype == "stocks_isa":
        if already_has:
            return 0, "Already holds a Stocks & Shares ISA"
        if age < 50:
            score = 70
            reasons.append("Long investment horizon for tax-free equity growth")
        else:
            score = 45
            reasons.append("Stocks & Shares ISA for portfolio growth — moderate risk at this life stage")
        if life_stage in ("Young Professional", "Established Professional", "Young Family"):
            score += 15
            reasons.append("Suitable for medium-to-long term wealth building")

    elif ptype == "lifetime_isa":
        if already_has:
            return 0, "Already holds a Lifetime ISA"
        if not (18 <= age <= 39):
            return 0, "Must be opened before age 40"
        score = 85
        reasons.append("25% government bonus up to £1,000/year — best return available")
        if not has_mortgage:
            score += 10
            reasons.append("Eligible for first-home purchase up to £450,000")
        if age >= 36:
            score += 8
            reasons.append("Urgency: eligibility closes at age 40 — act soon")

    elif ptype == "junior_isa":
        if not has_childcare:
            return 0, "Only relevant for customers with dependent children"
        if already_has:
            return 0, "Already holds a Junior ISA"
        score = 88
        reasons.append("Tax-free savings for your child up to £9,000/year")
        reasons.append("£9,000 annual allowance — excellent for education or house deposit fund")

    elif ptype == "fixed_bond":
        if already_has:
            return 0, "Already holds a Fixed-Rate Bond — consider our current rates at renewal"
        if total_assets < product.get("min_balance", 1000):
            return 0, f"Minimum deposit £{product['min_balance']:,.0f} not met"
        if life_stage in ("Pre-Retirement", "Retired"):
            score = 80
            reasons.append("Guaranteed return ideal for retirement income planning")
        elif total_assets > 20000:
            score = 65
            reasons.append("Lock in guaranteed rate on excess cash")
        else:
            score = 40
            reasons.append("Guaranteed return with no risk")
        rate = product.get("interest_rate", 0)
        reasons.append(f"{rate*100:.1f}% AER fixed — beats most variable savings rates")

    elif ptype == "easy_access_savings":
        if any("savings" in e for e in existing_lower):
            return 0, "Already holds a savings product"
        score = 60
        reasons.append("3.8% AER with instant access — good emergency fund home")
        if life_stage in ("Young Professional", "Student / Early Career"):
            score += 10
            reasons.append("Flexible account suited to variable income")

    elif ptype == "regular_saver":
        if not has_ca:
            return 0, "Requires existing current account"
        if already_has:
            return 0, "Already holds a Regular Saver"
        score = 78
        reasons.append("7.0% AER fixed 12 months — highest available rate")
        reasons.append("Builds saving discipline with £25–£500/month deposits")

    elif ptype == "mortgage":
        if has_mortgage:
            return 0, "Already holds a mortgage"
        if life_stage in ("Young Professional", "Established Professional", "Young Family"):
            score = 55
            reasons.append("First-time buyer or next-home mortgage at 4.8% fixed 2 years")
        else:
            score = 30
            reasons.append("Residential mortgage available")

    elif ptype == "help_to_save":
        if income_band not in ("under_25k",):
            return 0, "Only available to Universal Credit or Working Tax Credit recipients"
        score = 82
        reasons.append("50% government bonus — save £600/year and receive £300 bonus")

    elif ptype == "insurance":
        if has_mortgage:
            score = 92
            reasons.append("Buildings & contents insurance essential for new homeowners")
            reasons.append("24/7 emergency home assist included")
        else:
            score = 35
            reasons.append("Contents insurance for renters available from £28.50/month")

    return score, " | ".join(reasons)


@traced_tool
def recommend_products(customer_id: str) -> str:
    """Analyses a customer's financial profile and recommends the most relevant bank products,
    ranked by suitability with personalised reasoning for each recommendation.

    Args:
        customer_id: The customer ID (e.g. C001)

    Returns:
        A formatted list of up to 5 product recommendations with explanations.
    """
    try:
        if not PROJECT_ID or not BQ_DATASET:
            return "Error: GOOGLE_CLOUD_PROJECT or BQ_DATASET not configured."

        client = _bq_client()

        cust_sql = f"""
            SELECT c.customer_id, c.name, c.age, c.income_band,
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
        age = int(cust_df.iloc[0]["age"])
        income_band = str(cust_df.iloc[0]["income_band"])
        existing_types = cust_df["product_type"].dropna().tolist()
        total_assets = cust_df[cust_df["balance"] > 0]["balance"].sum()
        has_mortgage = any("mortgage" in p.lower() for p in existing_types)

        txn_sql = f"""
            SELECT t.amount, t.category
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
        has_childcare = False
        if not txn_df.empty:
            monthly_income = txn_df[txn_df["amount"] > 0]["amount"].sum() / 3.0
            has_childcare = txn_df["category"].str.lower().str.contains("childcare").any()

        annual_income = monthly_income * 12
        if income_band == "75k_plus":
            annual_income = max(annual_income, 76000)
        elif income_band == "40k_75k":
            annual_income = max(annual_income, 40000)

        has_ca = any("current" in p.lower() for p in existing_types)
        if not has_ca:
            life_stage = "Student / Early Career" if age <= 24 else "Young Professional"
        elif age <= 24:
            life_stage = "Student / Early Career"
        elif age <= 35:
            life_stage = "Young Family" if has_childcare else "Young Professional"
        elif age <= 50:
            life_stage = "Young Family" if has_childcare else "Established Professional"
        elif age <= 65:
            life_stage = "Pre-Retirement"
        else:
            life_stage = "Retired"

        prod_sql = f"""
            SELECT product_id, name, product_type, interest_rate, monthly_fee,
                   min_balance, max_annual_deposit, min_age, max_age,
                   requires_current_account, features, description
            FROM `{BQ_DATASET}.bank_products`
        """
        prod_df = client.query(prod_sql).to_dataframe()

        if prod_df.empty:
            return "No products found in bank_products table."

        scored = []
        for _, row in prod_df.iterrows():
            product = row.to_dict()
            score, reason = _score_product(
                product, age, annual_income, total_assets,
                existing_types, life_stage, has_childcare,
                has_mortgage, income_band,
            )
            if score > 0:
                scored.append((score, product, reason))

        scored.sort(key=lambda x: x[0], reverse=True)
        top5 = scored[:5]

        if not top5:
            return f"No new products to recommend for {name} at this time — their portfolio appears complete."

        lines = [
            f"Product Recommendations — {name} ({customer_id})",
            f"Life Stage: {life_stage}  |  Annual Income Est.: £{annual_income:,.0f}",
            f"{'='*60}",
            "",
        ]
        for rank, (score, product, reason) in enumerate(top5, start=1):
            fee = f"£{product['monthly_fee']:.2f}/month" if product["monthly_fee"] and product["monthly_fee"] > 0 else "No monthly fee"
            rate = f"{product['interest_rate']*100:.1f}% AER" if product["interest_rate"] and product["interest_rate"] > 0 else "N/A"
            _max_dep = product.get("max_annual_deposit")
            annual_limit = (
                f"£{_max_dep:,.0f}/year max deposit"
                if _max_dep and not math.isnan(float(_max_dep)) and _max_dep > 0
                else ""
            )
            min_dep = f"Min deposit £{product['min_balance']:,.0f}" if product.get("min_balance", 0) > 0 else ""
            details = " | ".join(filter(None, [fee, rate, annual_limit, min_dep]))
            lines += [
                f"#{rank}  {product['name']}  [Match score: {score}/100]",
                f"    Why for you: {reason}",
                f"    Details    : {details}",
                f"    Features   : {product['features']}",
                "",
            ]

        lines.append("Speak to an adviser or open any of these products instantly in our app.")
        return "\n".join(lines)

    except Exception as e:
        return f"Product Recommendation Error: {str(e)}"
