import pandas as pd
from faker import Faker
import random
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

fake = Faker('en_GB')
Faker.seed(42) # For reproducibility

# 1. Generate Customers
customers = []
for i in range(100):
    cust_id = f"LYD_{1000 + i}"
    dob = fake.date_of_birth(minimum_age=18, maximum_age=75)
    customers.append({
        "customer_id": cust_id,
        "name": fake.name(),
        "address": fake.address().replace("\n", ", "),
        "postcode": fake.postcode(),
        "phone": fake.phone_number(),
        "age": (datetime.now().date() - dob).days // 365,
        "dob": dob.strftime("%Y-%m-%d"),
        "gender": random.choice(["Male", "Female", "Non-binary"])
    })

df_customers = pd.DataFrame(customers)

# 2. Generate Products/Accounts
products_list = ["PCA", "SAV", "CRD"]
accounts = []
for cust in customers:
    accounts.append({
        "account_id": f"{fake.unique.random_number(digits=8)}",
        "customer_id": cust["customer_id"],
        "product_type": "PCA",
        "balance": round(random.uniform(100, 15000), 2)
    })
    # Each customer gets 1-3 random products
    num_prods = random.randint(1, 3)
    for _ in range(num_prods):
        prod_type = random.choice(products_list)
        accounts.append({
            "account_id": f"{fake.unique.random_number(digits=5)}",
            "customer_id": cust["customer_id"],
            "product_type": prod_type,
            "balance": round(random.uniform(100, 15000), 2)
        })

df_accounts = pd.DataFrame(accounts)

def generate_bank_transactions(account_id, product_type, months=6):
    txns = []
    # Start date 6 months ago
    base_date = datetime.now() - timedelta(days=months * 30)

    if product_type == "PCA": # Personal Current Account
        # --- 1. Monthly Salary (Predictable Credits) ---
        for i in range(months):
            # Paid roughly every 30 days
            salary_date = base_date + timedelta(days=i * 30 + 28)
            txns.append({
                "transaction_id": f"TXN_SAL_{fake.unique.random_number(digits=6)}",
                "account_id": account_id,
                "date": salary_date.strftime("%Y-%m-%d"),
                "amount": round(random.uniform(2500, 4500), 2),
                "description": "EMPLOYER PAYROLL",
                "type": "Credit"
            })

        # --- 2. Random Spending (Debits) ---
        # Generating ~20 random spends across the 6 month window
        for _ in range(20):
            days_offset = random.randint(0, months * 30)
            txn_date = base_date + timedelta(days=days_offset)

            txns.append({
                "transaction_id": f"TXN_EXP_{fake.unique.random_number(digits=6)}",
                "account_id": account_id,
                "date": txn_date.strftime("%Y-%m-%d"),
                "amount": round(random.uniform(-100, -5), 2),
                "description": random.choice(["Tesco", "Sainsburys", "Netflix", "Gym Membership", "Trainline"]),
                "type": "Debit"
            })

    return txns

all_transactions = []

for acc in accounts:
    # This returns a LIST of transactions for one account
    account_txns = generate_bank_transactions(acc["account_id"], acc["product_type"])

    # Use extend to add the items, not the list itself
    all_transactions.extend(account_txns)

# Now this creates a clean, flat table
df_transactions = pd.DataFrame(all_transactions)


# Save to CSV for your Vertex AI Search / Vector DB
df_customers.to_csv(SCRIPT_DIR / "customers.csv", index=False)
df_accounts.to_csv(SCRIPT_DIR / "accounts.csv", index=False)
df_transactions.to_csv(SCRIPT_DIR / "transactions.csv", index=False)