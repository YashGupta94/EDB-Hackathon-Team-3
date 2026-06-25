import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

from ..observability.tool_tracer import traced_tool

load_dotenv(
    str(Path(__file__).resolve().parent.parent / ".env"),
    override=False,
)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
BQ_DATASET = os.getenv("BQ_DATASET", "")
ECOMMERCE_DATASET = os.getenv("ECOMMERCE_DATASET", "ecommerce_data")

_CATEGORY_MAP = {
    "rent": "Housing", "mortgage": "Housing", "council tax": "Housing",
    "buildings insurance": "Housing", "contents insurance": "Housing",
    "stamp duty": "Housing", "solicitor": "Housing", "conveyancing": "Housing",
    "train": "Transport", "tfl": "Transport", "bus": "Transport",
    "fuel": "Transport", "car insurance": "Transport", "parking": "Transport",
    "uber": "Transport", "scotrail": "Transport", "season ticket": "Transport",
    "tesco": "Groceries", "sainsbury": "Groceries", "waitrose": "Groceries",
    "asda": "Groceries", "m&s food": "Groceries", "aldi": "Groceries",
    "lidl": "Groceries", "supermarket": "Groceries",
    "restaurant": "Dining Out", "deliveroo": "Dining Out", "just eat": "Dining Out",
    "costa": "Dining Out", "starbucks": "Dining Out", "coffee shop": "Dining Out",
    "mcdonald": "Dining Out", "nando": "Dining Out", "pret": "Dining Out",
    "pizza": "Dining Out", "greggs": "Dining Out", "itsu": "Dining Out",
    "netflix": "Entertainment", "spotify": "Entertainment", "amazon prime": "Entertainment",
    "cinema": "Entertainment", "disney+": "Entertainment", "sky": "Entertainment",
    "steam": "Entertainment", "streaming": "Entertainment",
    "gym": "Health & Fitness", "pharmacy": "Health & Fitness", "dentist": "Health & Fitness",
    "health insurance": "Health & Fitness", "bupa": "Health & Fitness",
    "nhs": "Health & Fitness", "boots": "Health & Fitness",
    "amazon": "Shopping", "asos": "Shopping", "john lewis": "Shopping",
    "next": "Shopping", "marks & spencer": "Shopping", "zara": "Shopping",
    "homebase": "Shopping", "ikea": "Shopping",
    "electricity": "Utilities", "edf": "Utilities", "gas": "Utilities",
    "water": "Utilities", "broadband": "Utilities", "mobile": "Utilities",
    "british gas": "Utilities", "scottish power": "Utilities",
    "isa transfer": "Savings", "savings transfer": "Savings", "pension": "Savings",
    "childcare": "Childcare", "nursery": "Childcare", "mothercare": "Childcare",
    "holiday": "Travel", "easyjet": "Travel", "tui": "Travel",
    "hotel": "Travel", "flight": "Travel", "airbnb": "Travel",
    "salary": "Income", "payroll": "Income", "freelance": "Income",
    "pension income": "Income", "interest": "Income", "dividend": "Income",
    "probate": "Income", "estate": "Income",
}


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)


def _categorise(description: str) -> str:
    desc_lower = description.lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in desc_lower:
            return cat
    return "Other"


def _bar(value: float, max_value: float, width: int = 20) -> str:
    if max_value <= 0:
        return ""
    filled = int((value / max_value) * width)
    return "█" * filled + "░" * (width - filled)


def _fmt(value: float) -> str:
    return f"£{value:,.2f}"


def _render_category_breakdown(df: pd.DataFrame, cat_col: str, title: str) -> str:
    if df.empty:
        return f"No {title.lower()} found.\n"
    grouped = df.groupby(cat_col)["amount"].sum().abs().sort_values(ascending=False)
    top = grouped.head(8)
    max_amt = top.max() if not top.empty else 0.0
    lines = [f"{title}:"]
    for label, amount in top.items():
        lines.append(f"  {str(label):22} {_bar(amount, max_amt)} {_fmt(amount)}")
    lines.append("")
    return "\n".join(lines)


def _render_mom_comparison(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> str:
    if current_df.empty:
        return ""
    current_by_cat = current_df.groupby("category")["amount"].sum().abs()
    prior_by_cat = prior_df.groupby("category")["amount"].sum().abs() if not prior_df.empty else pd.Series(dtype=float)

    lines = ["Month-on-Month Category Comparison (last 30 days vs prior 30 days):"]
    all_cats = sorted(set(current_by_cat.index) | set(prior_by_cat.index))
    for cat in all_cats:
        curr = current_by_cat.get(cat, 0.0)
        prior = prior_by_cat.get(cat, 0.0)
        if curr == 0 and prior == 0:
            continue
        if prior > 0:
            delta_pct = ((curr - prior) / prior) * 100
            arrow = "▲" if delta_pct > 5 else ("▼" if delta_pct < -5 else "→")
            delta_str = f"{arrow} {delta_pct:+.0f}%  ({_fmt(prior)} → {_fmt(curr)})"
        else:
            delta_str = f"▲ NEW  (this month: {_fmt(curr)})"
        lines.append(f"  {str(cat):22} {delta_str}")
    lines.append("")
    return "\n".join(lines)


def _render_anomalies(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    expenses = df[df["amount"] < 0].copy()
    if expenses.empty:
        return ""
    cat_mean = expenses.groupby("category")["amount"].mean().abs()
    anomalies = []
    for _, row in expenses.iterrows():
        cat = row["category"]
        mean = cat_mean.get(cat, 0)
        txn_amount = abs(row["amount"])
        if mean > 0 and txn_amount > mean * 2.5 and txn_amount > 50:
            anomalies.append({
                "date": str(row.get("txn_date", row.get("date", "")))[:10],
                "description": str(row["description"])[:35],
                "amount": txn_amount,
                "category": cat,
                "mean": mean,
            })

    if not anomalies:
        return ""

    lines = ["Unusual Spending Detected (>2.5× category average):"]
    for a in anomalies[:5]:
        lines.append(
            f"  ⚠ {a['date']}  {a['description']:35}  {_fmt(a['amount'])}  "
            f"(avg {_fmt(a['mean'])} in {a['category']})"
        )
    lines.append("")
    return "\n".join(lines)


@traced_tool
def spending_habits_report() -> str:
    """Summarises recent spending habits across all customers with category breakdown,
    daily trend, and ecommerce data."""
    try:
        if not PROJECT_ID:
            return "Error: GOOGLE_CLOUD_PROJECT not set."
        if not BQ_DATASET:
            return "Error: BQ_DATASET not set in bank_agent/.env."

        client = _bq_client()

        bank_sql = f"""
            SELECT DATE(date) AS txn_date, description, amount, type,
                   COALESCE(category, 'Other') AS category
            FROM `{BQ_DATASET}.transactions`
            WHERE DATE(date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY txn_date DESC
        """
        bank_df = client.query(bank_sql).to_dataframe()

        if not bank_df.empty:
            bank_df["txn_date"] = pd.to_datetime(bank_df["txn_date"])
            if "category" not in bank_df.columns or bank_df["category"].isna().all():
                bank_df["category"] = bank_df["description"].apply(_categorise)
            expenses_df = bank_df[bank_df["amount"] < 0].copy()
            spending_total = -expenses_df["amount"].sum()
            income_total = bank_df[bank_df["amount"] > 0]["amount"].sum()

            bank_summary = "\n".join([
                "Bank spending summary (last 30 days):",
                f"  Total spending : {_fmt(spending_total)}",
                f"  Total income   : {_fmt(income_total)}",
                f"  Transactions   : {len(expenses_df)}",
                "",
                _render_category_breakdown(expenses_df, "category", "Spending by Category"),
            ])
        else:
            bank_summary = "No recent bank transactions in the last 30 days.\n"

        ecommerce_sql = f"""
            SELECT DATE(o.order_date) AS order_date, u.email, p.name AS product_name,
                   p.category, o.quantity, p.price, o.quantity * p.price AS total
            FROM `{ECOMMERCE_DATASET}.orders` o
            JOIN `{ECOMMERCE_DATASET}.users` u ON u.user_id = o.user_id
            JOIN `{ECOMMERCE_DATASET}.products` p ON p.product_id = o.product_id
            WHERE DATE(o.order_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY order_date DESC
        """
        try:
            ecommerce_df = client.query(ecommerce_sql).to_dataframe()
            if not ecommerce_df.empty:
                ecommerce_total = ecommerce_df["total"].sum()
                cats = ecommerce_df.groupby("category")["total"].sum().sort_values(ascending=False)
                max_ecom = cats.max() if not cats.empty else 0.0
                lines = [
                    "Ecommerce spending summary (last 30 days):",
                    f"  Total ecommerce spend : {_fmt(ecommerce_total)}",
                    f"  Orders placed         : {len(ecommerce_df)}",
                    "",
                    "Top ecommerce categories:",
                ]
                for category, total in cats.head(5).items():
                    lines.append(f"  {str(category):22} {_bar(total, max_ecom)} {_fmt(total)}")
                ecommerce_summary = "\n".join(lines)
            else:
                ecommerce_summary = "No ecommerce orders in the last 30 days."
        except Exception:
            ecommerce_summary = "Ecommerce data unavailable."

        return "\n\n".join([bank_summary, ecommerce_summary])

    except Exception as e:
        return f"Spending Habits Report Error: {str(e)}"


@traced_tool
def spending_habits_for_user(customer_or_user_id: str = "") -> str:
    """Returns a personalised spending summary for a specific customer including:
    spending by category, month-on-month category comparison, anomaly detection,
    and ecommerce orders for the last 30 days.

    Args:
        customer_or_user_id: Customer ID (e.g. C001) or ecommerce user email/ID.

    Returns:
        Formatted spending report with category breakdown, MoM trends, and anomalies.
    """
    try:
        identifier = str(customer_or_user_id).strip()
        if not identifier:
            return "Please provide a customer ID or ecommerce user ID."

        client = _bq_client()

        current_sql = f"""
            SELECT DATE(t.date) AS txn_date, t.description, t.amount, t.type,
                   COALESCE(t.category, 'Other') AS category
            FROM `{BQ_DATASET}.transactions` t
            JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
            WHERE a.customer_id = @identifier
              AND DATE(t.date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY txn_date DESC
        """
        job_cfg = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("identifier", "STRING", identifier)]
        )
        current_df = client.query(current_sql, job_config=job_cfg).to_dataframe()

        prior_sql = f"""
            SELECT DATE(t.date) AS txn_date, t.description, t.amount, t.type,
                   COALESCE(t.category, 'Other') AS category
            FROM `{BQ_DATASET}.transactions` t
            JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
            WHERE a.customer_id = @identifier
              AND DATE(t.date) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
                                   AND DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY txn_date DESC
        """
        prior_df = client.query(prior_sql, job_config=job_cfg).to_dataframe()

        if not current_df.empty:
            current_df["txn_date"] = pd.to_datetime(current_df["txn_date"])
            if current_df["category"].isna().all():
                current_df["category"] = current_df["description"].apply(_categorise)
        if not prior_df.empty:
            prior_df["txn_date"] = pd.to_datetime(prior_df["txn_date"])
            if prior_df["category"].isna().all():
                prior_df["category"] = prior_df["description"].apply(_categorise)

        if not current_df.empty:
            expenses = current_df[current_df["amount"] < 0].copy()
            income = current_df[current_df["amount"] > 0]["amount"].sum()
            total_spend = -expenses["amount"].sum()
            net = income - total_spend

            bank_section = "\n".join([
                f"Bank spending for {identifier} — last 30 days:",
                f"  Income   : {_fmt(income)}",
                f"  Expenses : {_fmt(total_spend)}",
                f"  Net      : {_fmt(net)}  ({'surplus' if net >= 0 else 'deficit'})",
                "",
                _render_category_breakdown(expenses, "category", "Spending by Category"),
                _render_mom_comparison(
                    expenses,
                    prior_df[prior_df["amount"] < 0].copy() if not prior_df.empty else pd.DataFrame(),
                ),
                _render_anomalies(current_df),
                "Recent transactions:",
            ])
            txn_lines = []
            for _, row in expenses.sort_values("txn_date", ascending=False).head(15).iterrows():
                txn_lines.append(
                    f"  {row['txn_date'].date()}  {str(row['description'])[:32]:32}  "
                    f"{_fmt(-row['amount'])}  [{row['category']}]"
                )
            bank_section = bank_section + "\n" + "\n".join(txn_lines)
        else:
            bank_section = f"No bank transactions found for {identifier} in the last 30 days."

        ecommerce_filter = "u.email = @identifier" if "@" in identifier else "u.user_id = @identifier"
        ecommerce_sql = f"""
            SELECT DATE(o.order_date) AS order_date, p.name AS product_name,
                   p.category, o.quantity, p.price, o.quantity * p.price AS total
            FROM `{ECOMMERCE_DATASET}.orders` o
            JOIN `{ECOMMERCE_DATASET}.users` u ON u.user_id = o.user_id
            JOIN `{ECOMMERCE_DATASET}.products` p ON p.product_id = o.product_id
            WHERE {ecommerce_filter}
              AND DATE(o.order_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY order_date DESC
        """
        try:
            ecom_df = client.query(
                ecommerce_sql,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ScalarQueryParameter("identifier", "STRING", identifier)]
                ),
            ).to_dataframe()
            if not ecom_df.empty:
                ecom_total = ecom_df["total"].sum()
                ecom_section = "\n".join([
                    f"Ecommerce orders for {identifier} — last 30 days:",
                    f"  Total: {_fmt(ecom_total)}  |  Orders: {len(ecom_df)}",
                    "",
                    _render_category_breakdown(ecom_df, "category", "Ecommerce categories"),
                ])
            else:
                ecom_section = f"No ecommerce orders found for {identifier} in the last 30 days."
        except Exception:
            ecom_section = "Ecommerce data unavailable."

        return "\n\n".join([bank_section, ecom_section])

    except Exception as e:
        return f"Spending Habits Error: {str(e)}"
