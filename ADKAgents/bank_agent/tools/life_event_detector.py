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


_HOUSE_PURCHASE_KEYWORDS = ["stamp duty", "sdlt", "conveyancing", "solicitor", "land registry"]
_CHILDCARE_KEYWORDS = ["childcare", "nursery", "creche", "childminder", "baby essentials",
                       "mothercare", "mamas & papas", "nappies", "baby gear"]
_SCHOOL_KEYWORDS = ["school fees", "private school", "prep school", "uniform", "school dinners"]
_WINDFALL_KEYWORDS = ["probate", "estate", "inheritance", "bequest", "legal settlement",
                      "insurance payout", "redundancy", "compensation"]
_RETIREMENT_KEYWORDS = ["pension", "annuity", "drawdown", "retirement"]

_HOUSE_RECS = [
    "Home & contents insurance (BP014) — essential protection for your new property",
    "Consider a Regular Saver (BP011) to rebuild your emergency fund after purchase costs",
    "Mortgage protection insurance — safeguards repayments if you're unable to work",
    "Review your mortgage rate annually — remortgage opportunities may save thousands",
    "Buildings insurance required by your mortgage lender — ensure cover is in place immediately",
]

_CHILDCARE_RECS = [
    "Junior ISA (BP007) — save up to £9,000/year tax-free for your child's future",
    "Child Benefit is worth £25.60/week per child — ensure you are claiming",
    "Review your Emergency Fund — childcare costs significantly increase monthly outgoings",
    "Life & critical illness insurance — especially important now you have a dependent",
    "Flexible Easy Access Savings (BP010) to cover unexpected childcare gaps",
]

_SCHOOL_RECS = [
    "Junior ISA (BP007) remains available for children under 18 — maximise the allowance",
    "Consider a 2-Year Fixed-Rate Bond (BP009) to earmark school fee funds at 5.2% AER",
    "Review household budget — school fees are often 10–15% of household income",
]

_WINDFALL_RECS = [
    "Maximise your ISA allowance immediately — £20,000 into a Cash ISA (BP004) is tax-free",
    "Stocks & Shares ISA (BP005) — invest the remaining £20,000 allowance for long-term growth",
    "2-Year Fixed-Rate Bond (BP009) at 5.2% AER for capital you won't need short-term",
    "Speak to a financial adviser — windfalls over £50,000 benefit from structured planning",
    "Inheritance Tax implications may apply if the estate exceeded the threshold — seek advice",
]

_JOB_CHANGE_RECS = [
    "Ensure your emergency fund covers at least 3 months of expenses during the transition",
    "Review pension contributions — if leaving an employer scheme, consider a SIPP",
    "Check you are not losing employer pension matching — this is effectively free money",
    "Easy Access Savings (BP010) for a financial buffer during salary gap periods",
]

_RETIREMENT_RECS = [
    "Maximise pension contributions before retirement — tax relief available up to £60,000/year",
    "Stocks & Shares ISA (BP005) for tax-free drawdown in retirement to supplement pension",
    "1-Year Fixed-Rate Bond (BP008) to lock in guaranteed income for year 1 of retirement",
    "Review state pension forecast at gov.uk/check-state-pension",
    "Consider pension consolidation — multiple small pots are harder to manage",
]


def _detect_signals(txn_df) -> list[dict]:
    events = []
    if txn_df.empty:
        return events

    txn_df = txn_df.copy()
    txn_df["desc_lower"] = txn_df["description"].str.lower().fillna("")
    txn_df["date_parsed"] = txn_df["date"].astype(str)

    stamp_duty = txn_df[
        txn_df["desc_lower"].str.contains("|".join(_HOUSE_PURCHASE_KEYWORDS))
    ]
    new_mortgage = txn_df[
        (txn_df["desc_lower"].str.contains("mortgage"))
        & (txn_df["amount"] < 0)
    ]

    if not stamp_duty.empty:
        evidence = []
        for _, r in stamp_duty.iterrows():
            evidence.append(f"  • {r['date_parsed'][:10]}  {r['description']}  £{abs(r['amount']):,.2f}")
        if not new_mortgage.empty:
            first_mortgage = new_mortgage.sort_values("date_parsed").iloc[0]
            evidence.append(
                f"  • New monthly mortgage payment of £{abs(first_mortgage['amount']):,.2f} "
                f"from {first_mortgage['date_parsed'][:10]}"
            )
        events.append({
            "event": "House Purchase",
            "confidence": "High",
            "icon": "🏠",
            "evidence": evidence,
            "recommendations": _HOUSE_RECS,
        })
    elif not new_mortgage.empty:
        first = new_mortgage.sort_values("date_parsed").iloc[0]
        events.append({
            "event": "New Mortgage Detected",
            "confidence": "Medium",
            "icon": "🏠",
            "evidence": [f"  • New mortgage payment £{abs(first['amount']):,.2f}/month from {first['date_parsed'][:10]}"],
            "recommendations": _HOUSE_RECS,
        })

    childcare_txns = txn_df[txn_df["desc_lower"].str.contains("|".join(_CHILDCARE_KEYWORDS))]
    if not childcare_txns.empty:
        recurring = childcare_txns[childcare_txns["amount"] < 0]
        monthly_cost = abs(recurring["amount"].sum()) / 3.0
        evidence = []
        for _, r in recurring.sort_values("date_parsed").iterrows():
            evidence.append(f"  • {r['date_parsed'][:10]}  {r['description']}  £{abs(r['amount']):,.2f}")
        events.append({
            "event": "New Dependent / Childcare Costs",
            "confidence": "High" if len(recurring) >= 2 else "Medium",
            "icon": "👶",
            "evidence": evidence + [f"  • Estimated monthly childcare cost: £{monthly_cost:,.2f}"],
            "recommendations": _CHILDCARE_RECS,
        })

    school_txns = txn_df[txn_df["desc_lower"].str.contains("|".join(_SCHOOL_KEYWORDS))]
    if not school_txns.empty:
        evidence = [f"  • {r['date_parsed'][:10]}  {r['description']}  £{abs(r['amount']):,.2f}"
                    for _, r in school_txns.iterrows()]
        events.append({
            "event": "Child Starting School / Education Costs",
            "confidence": "Medium",
            "icon": "🎒",
            "evidence": evidence,
            "recommendations": _SCHOOL_RECS,
        })

    credits = txn_df[txn_df["amount"] > 0].copy()
    income_credits = credits[~credits["desc_lower"].str.contains("interest|dividend|bonus|transfer")]
    avg_monthly_income = income_credits["amount"].sum() / 3.0

    windfall_txns = txn_df[
        txn_df["desc_lower"].str.contains("|".join(_WINDFALL_KEYWORDS))
        & (txn_df["amount"] > 0)
    ]
    if not windfall_txns.empty:
        evidence = []
        for _, r in windfall_txns.iterrows():
            evidence.append(f"  • {r['date_parsed'][:10]}  {r['description']}  £{r['amount']:,.2f}")
        events.append({
            "event": "Windfall / Inheritance Received",
            "confidence": "High",
            "icon": "💰",
            "evidence": evidence,
            "recommendations": _WINDFALL_RECS,
        })
    elif avg_monthly_income > 0:
        large_credits = credits[
            (credits["amount"] > avg_monthly_income * 4)
            & ~credits["desc_lower"].str.contains("salary|payroll|pension|wage|freelance")
        ]
        if not large_credits.empty:
            evidence = [f"  • {r['date_parsed'][:10]}  {r['description']}  £{r['amount']:,.2f}"
                        for _, r in large_credits.iterrows()]
            events.append({
                "event": "Potential Windfall / Large One-Off Credit",
                "confidence": "Medium",
                "icon": "💰",
                "evidence": evidence,
                "recommendations": _WINDFALL_RECS,
            })

    income_txns = credits[credits["desc_lower"].str.contains("salary|payroll|wage|income")]
    if len(income_txns) >= 2:
        sorted_income = income_txns.sort_values("date_parsed")
        first_half = sorted_income.head(len(sorted_income) // 2)["amount"].mean()
        second_half = sorted_income.tail(len(sorted_income) // 2)["amount"].mean()
        if first_half > 0 and abs(second_half - first_half) / first_half > 0.20:
            direction = "increase" if second_half > first_half else "decrease"
            pct = abs(second_half - first_half) / first_half * 100
            events.append({
                "event": f"Income Change Detected ({direction.title()})",
                "confidence": "Medium",
                "icon": "💼",
                "evidence": [
                    f"  • Average income first half of period: £{first_half:,.2f}/month",
                    f"  • Average income second half of period: £{second_half:,.2f}/month",
                    f"  • Change: {pct:.0f}% {direction}",
                ],
                "recommendations": _JOB_CHANGE_RECS,
            })

    pension_txns = txn_df[
        txn_df["desc_lower"].str.contains("|".join(_RETIREMENT_KEYWORDS))
        & (txn_df["amount"] < 0)
    ]
    if not pension_txns.empty:
        evidence = [f"  • {r['date_parsed'][:10]}  {r['description']}  £{abs(r['amount']):,.2f}"
                    for _, r in pension_txns.head(3).iterrows()]
        events.append({
            "event": "Retirement Planning Activity",
            "confidence": "Medium",
            "icon": "🎯",
            "evidence": evidence,
            "recommendations": _RETIREMENT_RECS,
        })

    return events


@traced_tool
def detect_life_events(customer_id: str) -> str:
    """Scans the last 90 days of transaction data for signals of major life events such as
    a house purchase, new baby, inheritance/windfall, job change, or retirement planning.
    Returns detected events with confidence levels and personalised product/action recommendations.

    Args:
        customer_id: The customer ID (e.g. C001)

    Returns:
        A formatted report of detected life events and recommended next steps.
    """
    try:
        if not PROJECT_ID or not BQ_DATASET:
            return "Error: GOOGLE_CLOUD_PROJECT or BQ_DATASET not configured."

        client = _bq_client()

        cust_sql = f"""
            SELECT name, age
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

        name = str(cust_df.iloc[0]["name"])
        age = int(cust_df.iloc[0]["age"])

        txn_sql = f"""
            SELECT t.description, t.amount, t.category, DATE(t.date) AS date
            FROM `{BQ_DATASET}.transactions` t
            JOIN `{BQ_DATASET}.accounts` a ON t.account_id = a.account_id
            WHERE a.customer_id = @cid
              AND DATE(t.date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
            ORDER BY t.date DESC
        """
        txn_df = client.query(
            txn_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
            ),
        ).to_dataframe()

        events = _detect_signals(txn_df)

        if not events:
            return "\n".join([
                f"Life Event Detection — {name} ({customer_id})",
                f"{'='*55}",
                f"",
                f"No significant life events detected in the last 90 days.",
                f"",
                f"Your transaction patterns appear consistent with recent history.",
                f"Use 'get_customer_profile' for product gap analysis, or",
                f"'calculate_wellbeing_score' for a full financial health check.",
            ])

        lines = [
            f"Life Event Detection — {name} ({customer_id})",
            f"{'='*55}",
            f"Analysed last 90 days  |  {len(events)} event(s) detected",
            f"",
        ]

        for i, event in enumerate(events, 1):
            confidence_icon = "🟢" if event["confidence"] == "High" else "🟡"
            lines += [
                f"{'─'*55}",
                f"{event['icon']}  Event {i}: {event['event']}",
                f"    Confidence: {confidence_icon} {event['confidence']}",
                f"",
                f"    Evidence from your transactions:",
            ]
            lines += event["evidence"]
            lines += [
                f"",
                f"    Recommended actions:",
            ]
            for rec in event["recommendations"]:
                lines.append(f"    → {rec}")
            lines.append("")

        lines += [
            f"{'─'*55}",
            f"These recommendations are based on your recent activity.",
            f"Speak to one of our advisers for personalised guidance.",
        ]
        return "\n".join(lines)

    except Exception as e:
        return f"Life Event Detection Error: {str(e)}"
