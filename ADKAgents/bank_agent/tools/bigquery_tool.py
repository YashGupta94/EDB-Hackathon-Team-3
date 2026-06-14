import os

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
BQ_DATASET = os.getenv("BQ_DATASET", "")


def run_bigquery_query(sql: str) -> str:
    """Executes a read-only SQL query against the bank BigQuery dataset and returns the results.

    Use this tool for analytics or reporting questions that go beyond simple customer
    lookups — for example: aggregating transaction volumes, comparing balances across
    accounts, or spotting spending patterns. The dataset contains three tables:
      - customers (customer_id, name, dob, postcode, address, age, gender, phone)
      - accounts  (account_id, customer_id, product_type, balance)
      - transactions (account_id, description, amount, type, date)

    Always reference tables as `{dataset}.table_name` in your SQL — use the
    BQ_DATASET variable already substituted into your query at call time, or ask
    the agent to substitute it. Queries are parameterised at the caller's
    discretion; this function runs whatever SQL string is passed in.

    Args:
        sql: A valid GoogleSQL SELECT statement targeting the bank dataset.

    Returns:
        A plain-text table of results, or an error message if the query fails.
    """
    if not BQ_DATASET:
        return "ERROR: BQ_DATASET environment variable is not set. Cannot run BigQuery queries."

    if not PROJECT_ID:
        return "ERROR: GOOGLE_CLOUD_PROJECT environment variable is not set."

    # Reject anything that looks like a write operation — this tool is read-only.
    normalised = sql.strip().upper()
    for disallowed in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "MERGE", "CREATE"):
        if normalised.startswith(disallowed):
            return f"ERROR: Write operations are not permitted. Only SELECT queries are allowed."

    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Substitute the dataset placeholder so callers can write portable SQL
        resolved_sql = sql.replace("{dataset}", BQ_DATASET)

        print(f"Running BigQuery query:\n{resolved_sql}")
        result_df = client.query(resolved_sql).to_dataframe()

        if result_df.empty:
            return "Query returned no results."

        return result_df.to_string(index=False)

    except Exception as e:
        return f"BigQuery Error: {str(e)}"
