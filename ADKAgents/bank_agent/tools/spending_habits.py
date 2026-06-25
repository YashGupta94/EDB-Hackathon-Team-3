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


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)


def _bar(value: float, max_value: float, width: int = 30) -> str:
    if max_value <= 0:
        return ""
    filled = int((value / max_value) * width)
    return "█" * filled + " " * (width - filled)


def _format_currency(value: float) -> str:
    return f"${value:,.2f}"


def _render_top_spend(df: pd.DataFrame, group_key: str, title: str) -> str:
    if df.empty:
        return f"No {title.lower()} found.\n"

    grouped = df.groupby(group_key)["amount"].sum().abs().sort_values(ascending=False)
    top = grouped.head(5)
    max_amount = top.max() if not top.empty else 0.0

    lines = [f"Top {title}:\n"]
    for label, amount in top.items():
        lines.append(f"  {label:20} | {_bar(amount, max_amount)} | {_format_currency(amount)}")
    lines.append("")
    return "\n".join(lines)


def _render_daily_spend(df: pd.DataFrame) -> str:
    if df.empty:
        return "No daily spending data available.\n"

    daily = df.groupby("txn_date")["amount"].sum().abs().sort_index()
    max_amount = daily.max() if not daily.empty else 0.0
    lines = ["Daily spending trend (last 30 days):\n"]
    for txn_date, amount in daily.items():
        lines.append(f"  {txn_date:%Y-%m-%d} | {_bar(amount, max_amount)} | {_format_currency(amount)}")
    lines.append("")
    return "\n".join(lines)


@traced_tool
def spending_habits_report() -> str:
    """Summarizes recent spending habits across the bank and ecommerce datasets."""
    try:
        if not PROJECT_ID:
            return "Spending Habits Error: GOOGLE_CLOUD_PROJECT is not set in the environment."
        if not BQ_DATASET:
            return "Spending Habits Error: BQ_DATASET is not set in the bank_agent/.env file."
        if not ECOMMERCE_DATASET:
            return "Spending Habits Error: ECOMMERCE_DATASET is not set in the bank_agent/.env file."

        client = _bq_client()

        bank_sql = f"""
            SELECT
                DATE(date) AS txn_date,
                description,
                amount,
                type
            FROM `{BQ_DATASET}.transactions`
            WHERE DATE(date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY txn_date DESC
        """
        bank_df = client.query(bank_sql).to_dataframe()

        if not bank_df.empty:
            bank_df["txn_date"] = pd.to_datetime(bank_df["txn_date"]) 
            expenses_df = bank_df[bank_df["amount"] < 0].copy()
            spending_total = -expenses_df["amount"].sum()
            income_total = bank_df[bank_df["amount"] > 0]["amount"].sum()
            expense_count = len(expenses_df)
            average_spend = -expenses_df["amount"].mean() if not expenses_df.empty else 0.0
            top_descriptions = _render_top_spend(expenses_df, "description", "Bank spending categories")
            daily_chart = _render_daily_spend(expenses_df)
            last_month_expenses = expenses_df.sort_values("txn_date", ascending=False)

            bank_summary = [
                "Bank spending summary (last 30 days):",
                f"  Total spending: {_format_currency(spending_total)}",
                f"  Total income:   {_format_currency(income_total)}",
                f"  Expense count:  {expense_count}",
                f"  Avg expense:    {_format_currency(average_spend)}",
                "",
                top_descriptions,
                daily_chart,
            ]
        else:
            bank_summary = ["Bank spending summary: No recent bank transactions were found in the last 30 days.\n"]
            last_month_expenses = pd.DataFrame()

        ecommerce_sql = f"""
            SELECT
                o.order_id,
                DATE(o.order_date) AS order_date,
                u.email,
                p.name AS product_name,
                p.category,
                o.quantity,
                p.price,
                o.quantity * p.price AS total
            FROM `{ECOMMERCE_DATASET}.orders` o
            JOIN `{ECOMMERCE_DATASET}.users` u ON u.user_id = o.user_id
            JOIN `{ECOMMERCE_DATASET}.products` p ON p.product_id = o.product_id
            WHERE DATE(o.order_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY order_date DESC
        """
        ecommerce_df = client.query(ecommerce_sql).to_dataframe()

        if not ecommerce_df.empty:
            ecommerce_total = ecommerce_df["total"].sum()
            order_count = len(ecommerce_df)
            orders_by_category = ecommerce_df.groupby("category")["total"].sum().abs().sort_values(ascending=False)
            max_ecom = orders_by_category.max() if not orders_by_category.empty else 0.0
            lines = ["Ecommerce spending summary (last 30 days):",
                     f"  Total ecommerce spend: {_format_currency(ecommerce_total)}",
                     f"  Orders placed: {order_count}",
                     "",
                     "Top ecommerce categories:\n"]
            for category, total in orders_by_category.head(5).items():
                lines.append(f"  {category:20} | {_bar(total, max_ecom)} | {_format_currency(total)}")
            lines.append("")
            ecommerce_summary = "\n".join(lines)
        else:
            ecommerce_summary = "Ecommerce spending summary: No ecommerce orders were found in the last 30 days.\n"

        expense_lines = [
            "Expenses in the last 30 days:",
        ]
        if not last_month_expenses.empty:
            for _, row in last_month_expenses.iterrows():
                expense_lines.append(
                    f"  {row['txn_date'].date()} | {row['description'][:30]:30} | {_format_currency(-row['amount'])} | {row['type']}"
                )
        else:
            expense_lines.append("  No bank expenses found in the last 30 days.")

        report_sections = [
            "Spending habits report:\n",
            "".join(bank_summary),
            ecommerce_summary,
            "\n".join(expense_lines),
        ]

        return "\n".join(report_sections)

    except Exception as e:
        return f"Spending Habits Report Error: {str(e)}"


@traced_tool
def spending_habits_for_user(customer_or_user_id: str = "") -> str:
    """Returns a personalized spending summary and expenses for a customer or user."""
    try:
        identifier = str(customer_or_user_id).strip()
        if not identifier:
            return (
                "Please provide a customer ID or ecommerce user ID so I can "
                "generate a personalized spending habits report."
            )

        client = _bq_client()

        bank_query = f"""
            SELECT
                DATE(t.date) AS txn_date,
                t.description,
                t.amount,
                t.type
            FROM `{BQ_DATASET}.transactions` t
            JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
            WHERE a.customer_id = @identifier
              AND DATE(t.date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY txn_date DESC
        """
        bank_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("identifier", "STRING", identifier)
            ]
        )
        bank_df = client.query(bank_query, job_config=bank_job_config).to_dataframe()
        if not bank_df.empty:
            bank_df["txn_date"] = pd.to_datetime(bank_df["txn_date"])
            bank_expenses = bank_df[bank_df["amount"] < 0].copy()
            bank_spend = -bank_expenses["amount"].sum()
            bank_income = bank_df[bank_df["amount"] > 0]["amount"].sum()
            bank_summary = [
                f"Bank spending for customer {identifier} (last 30 days):",
                f"  Total spend: {_format_currency(bank_spend)}",
                f"  Total income: {_format_currency(bank_income)}",
                f"  Expense transactions: {len(bank_expenses)}",
                "",
                _render_top_spend(bank_expenses, "description", "Bank spending categories"),
                _render_daily_spend(bank_expenses),
            ]
        else:
            bank_summary = [
                f"No bank spending found for customer ID {identifier} in the last 30 days.\n"
            ]
            bank_expenses = pd.DataFrame()

        ecommerce_filter = "u.email = @identifier" if "@" in identifier else "u.user_id = @identifier"
        ecommerce_query = f"""
            SELECT
                DATE(o.order_date) AS order_date,
                u.user_id,
                u.email,
                p.name AS product_name,
                p.category,
                o.quantity,
                p.price,
                o.quantity * p.price AS total
            FROM `{ECOMMERCE_DATASET}.orders` o
            JOIN `{ECOMMERCE_DATASET}.users` u ON u.user_id = o.user_id
            JOIN `{ECOMMERCE_DATASET}.products` p ON p.product_id = o.product_id
            WHERE {ecommerce_filter}
              AND DATE(o.order_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            ORDER BY order_date DESC
        """
        ecommerce_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("identifier", "STRING", identifier)
            ]
        )
        ecommerce_df = client.query(ecommerce_query, job_config=ecommerce_job_config).to_dataframe()
        if not ecommerce_df.empty:
            ecommerce_total = ecommerce_df["total"].sum()
            ecommerce_summary_lines = [
                f"Ecommerce spend for {identifier} (last 30 days):",
                f"  Total order value: {_format_currency(ecommerce_total)}",
                f"  Orders: {len(ecommerce_df)}",
                "",
                _render_top_spend(ecommerce_df.rename(columns={"category": "description"}), "description", "Ecommerce categories"),
            ]
            ecommerce_summary = "\n".join(ecommerce_summary_lines)
        else:
            ecommerce_summary = f"No ecommerce spending found for {identifier} in the last 30 days.\n"

        expense_lines = [
            "Recent expenses and orders:\n"
        ]
        if not bank_expenses.empty:
            for _, row in bank_expenses.sort_values("txn_date", ascending=False).iterrows():
                expense_lines.append(
                    f"  BANK | {row['txn_date'].date()} | {row['description'][:30]:30} | {_format_currency(-row['amount'])} | {row['type']}"
                )
        if not ecommerce_df.empty:
            for _, row in ecommerce_df.iterrows():
                expense_lines.append(
                    f"  ECOM | {row['order_date'].date()} | {row['product_name'][:30]:30} | {_format_currency(row['total'])} | {row['category']}"
                )
        if len(expense_lines) == 1:
            expense_lines.append("  No recent spending records found for this ID.")

        return "\n".join(["".join(bank_summary), ecommerce_summary, "\n".join(expense_lines)])

    except Exception as e:
        return f"Spending Habits Error: {str(e)}"
