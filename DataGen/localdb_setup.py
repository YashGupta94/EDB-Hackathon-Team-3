import sqlite3
import pandas as pd
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def generate_database():
    db_name = SCRIPT_DIR.parent / "ADKAgents" / "bank_data.db"

    # Check if DB already exists; remove it to start fresh if needed
    if db_name.exists():
        db_name.unlink()
        print(f"Cleaned up old {db_name}")

    # Connect to (and create) the database file
    conn = sqlite3.connect(db_name)

    try:
        # Load your CSVs into Pandas DataFrames
        customers = pd.read_csv(SCRIPT_DIR / 'customers.csv')
        accounts = pd.read_csv(SCRIPT_DIR / 'accounts.csv')
        transactions = pd.read_csv(SCRIPT_DIR / 'transactions.csv')

        # Write the DataFrames to SQL tables
        customers.to_sql('customers', conn, index=False, if_exists='replace')
        accounts.to_sql('accounts', conn, index=False, if_exists='replace')
        transactions.to_sql('transactions', conn, index=False, if_exists='replace')

        print("Successfully created bank_data.db with 3 tables.")

        # Quick verification: Check how many rows were imported
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM customers")
        print(f"Total customers imported: {cursor.fetchone()[0]}")

    except FileNotFoundError as e:
        print(f"Error: {e}. Make sure your CSV files are in the same folder!")
    finally:
        conn.close()

if __name__ == "__main__":
    generate_database()