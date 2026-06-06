import sqlite3
import pandas as pd
from google.adk.tools.tool_context import ToolContext
from dotenv import load_dotenv
from google.cloud import firestore
import os
from typing import Any

from ..observability.tool_tracer import traced_tool


load_dotenv()


@traced_tool
def customer_id_search(customer_id: str, tool_context: ToolContext) -> dict[str, str]:
    """Retrieves customer information for a particular customer ID, used for verifying identity.

    Args:
        customer_id (str): The customer ID for the customer who to verify
        tool_context: provides the state of verification

    Returns:
        dict: status and result or error msg.
    """
    try:

        # 1. SECURITY CHECK: Ensure identity is verified
        if tool_context.state.get("identity_verified") and customer_id != tool_context.state.get("verified_customer_id"):
            tool_context.state["verified_customer_id"] = ""
            tool_context.state["identity_verified"] = False
            return {"status": "error","error_message": "Customer identity is not the same as verified. Verify the customer again"}
        elif tool_context.state.get("identity_verified") and customer_id == tool_context.state.get("verified_customer_id"):
            # 2. CONTEXT INJECTION: Pull the ID from the secure state, not the prompt
            verified_id = tool_context.state.get("verified_customer_id")
        else:
            tool_context.state["identity_verified"] = False
            verified_id = customer_id
        print(f"Customer ID searched: {verified_id}")
        # using datastore
        if os.getenv("USE_DATASTORE") == "true":
            print(f"Pulling customer details from Data store")
            db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
            doc_ref = db.collection("customers").document(f"customer_{verified_id}")
            doc = doc_ref.get(field_paths=["customer_id", "name", "dob", "postcode","transactions","accounts"])

            data: dict[str, Any] | None = doc.to_dict()  # ty:ignore[unresolved-attribute]
            if data is None:
                raise ValueError("No data returned for customer")
            result: dict[str, Any] = data

        else:
            # 1. Connect to the database (Using the persistent file we created)
            conn = sqlite3.connect("bank_data.db")

            # 2. Define the SQL Query with a placeholder (?)
            # This prevents SQL Injection by separating the logic from the data.
            query = """
            SELECT customer_id, name, dob, postcode
            FROM customers
            WHERE customer_id = ?
            """

            # 3. Execute using pandas 'params' argument
            result_df = pd.read_sql_query(query, conn, params=[verified_id])

            conn.close()

            if result_df.empty:
                # Return a clear message so the Agent knows the ID doesn't exist
                return {
                    "status": "error",
                    "error_message": "no values returned for customer ID",
                }

            result = result_df.iloc[0].to_dict()

        result["status"] = "success"
        return result

    except Exception as e:
        return {"status": "error", "error_message": f"Database Error: {str(e)}"}


@traced_tool
def customer_database_search(tool_context: ToolContext) -> str:
    """
    Retrieves the currently verified customer's profile and recent financial activity.
    This tool requires no arguments as it uses the ID from the verified session context.
    tool_context: provides the state of verification
    """
    try:
        # 1. SECURITY CHECK: Ensure identity is verified
        if not tool_context.state.get("identity_verified"):
            return "ERROR: Customer identity has not been verified. Please verify the customer before searching records."

        # 2. CONTEXT INJECTION: Pull the ID from the secure state, not the prompt
        verified_id = tool_context.state.get("verified_customer_id")

        if not verified_id:
            return "ERROR: Session error. Identity verified but no Customer ID found in context."
        # Run this ONCE to create the database file
        # conn = sqlite3.connect('bank_data.db')
        # pd.read_csv("../DataGen/customers.csv").to_sql('customers', conn)
        # pd.read_csv("../DataGen/accounts.csv").to_sql('accounts', conn)
        # pd.read_csv("../DataGen/transactions.csv").to_sql('transactions', conn)
        # conn.close()
        # 1. Connect to the database (Using the persistent file we created)
        conn = sqlite3.connect("bank_data.db")

        # 2. Define the SQL Query with a placeholder (?)
        # This prevents SQL Injection by separating the logic from the data.
        query = """SELECT 
        c.address, c.age, c.customer_id, c.dob, c.gender, c.name, c.phone, c.postcode, 
        a.product_type, a.balance, 
        t.description, t.amount, t.type, t.date
        FROM "customers" c
        JOIN "accounts" a ON c.customer_id = a.customer_id
        LEFT JOIN "transactions" t ON a.account_id = t.account_id
        WHERE c.customer_id = ?
        ORDER BY t.date DESC
        LIMIT 200;
        """

        # 3. Execute using pandas 'params' argument
        result_df = pd.read_sql_query(query, conn, params=[verified_id])

        conn.close()

        if result_df.empty:
            # Return a clear message so the Agent knows the ID doesn't exist
            return "ERROR: No record found for this Customer ID."

        # 4. Return as a clean string for the Agent's context
        return result_df.to_string(index=False)

    except Exception as e:
        return f"Database Error: {str(e)}"
