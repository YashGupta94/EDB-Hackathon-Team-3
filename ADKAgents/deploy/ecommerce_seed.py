import os
from google.cloud import bigquery
from google.cloud.exceptions import Conflict

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "adk-starter-kit-1")
DATASET_ID = f"{PROJECT_ID}.ecommerce_data"

client = bigquery.Client(project=PROJECT_ID)

# 1. Create Dataset
dataset = bigquery.Dataset(DATASET_ID)
dataset.location = "US"
try:
    client.create_dataset(dataset, timeout=30)
    print(f"Created dataset {DATASET_ID}")
except Conflict:
    print(f"Dataset {DATASET_ID} already exists")

# 2. Define schemas and create tables
schemas = {
    "users": [
        bigquery.SchemaField("user_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("email", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("signup_date", "DATE", mode="REQUIRED"),
    ],
    "products": [
        bigquery.SchemaField("product_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("category", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("price", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("stock", "INTEGER", mode="REQUIRED"),
    ],
    "orders": [
        bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("user_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("product_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("quantity", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("order_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    ]
}

for table_name, schema in schemas.items():
    table_id = f"{DATASET_ID}.{table_name}"
    table = bigquery.Table(table_id, schema=schema)
    try:
        client.create_table(table)
        print(f"Created table {table_id}")
    except Conflict:
        print(f"Table {table_id} already exists, recreating...")
        client.delete_table(table_id)
        client.create_table(table)
        print(f"Recreated table {table_id}")

# 3. Load Seed Data
users_data = [
    {"user_id": "U001", "name": "Alice Smith", "email": "alice@example.com", "signup_date": "2023-01-15"},
    {"user_id": "U002", "name": "Bob Jones", "email": "bob@example.com", "signup_date": "2023-03-22"},
    {"user_id": "U003", "name": "Charlie Brown", "email": "charlie@example.com", "signup_date": "2023-06-10"},
]

products_data = [
    {"product_id": "P001", "name": "Laptop Pro", "category": "Electronics", "price": 1299.99, "stock": 50},
    {"product_id": "P002", "name": "Wireless Mouse", "category": "Electronics", "price": 49.99, "stock": 200},
    {"product_id": "P003", "name": "Coffee Maker", "category": "Home", "price": 89.50, "stock": 30},
    {"product_id": "P004", "name": "Desk Lamp", "category": "Office", "price": 25.00, "stock": 100},
]

orders_data = [
    {"order_id": "O001", "user_id": "U001", "product_id": "P001", "quantity": 1, "order_date": "2023-07-01", "status": "Delivered"},
    {"order_id": "O002", "user_id": "U001", "product_id": "P002", "quantity": 2, "order_date": "2023-07-05", "status": "Delivered"},
    {"order_id": "O003", "user_id": "U002", "product_id": "P003", "quantity": 1, "order_date": "2023-08-12", "status": "Shipped"},
    {"order_id": "O004", "user_id": "U003", "product_id": "P004", "quantity": 3, "order_date": "2023-09-20", "status": "Processing"},
]

client.insert_rows_json(f"{DATASET_ID}.users", users_data)
print("Inserted rows into users")
client.insert_rows_json(f"{DATASET_ID}.products", products_data)
print("Inserted rows into products")
client.insert_rows_json(f"{DATASET_ID}.orders", orders_data)
print("Inserted rows into orders")

print("E-commerce seed complete!")
