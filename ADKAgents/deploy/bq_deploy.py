#!/usr/bin/env python3
"""Create the BigQuery dataset + tables and load seed data from bq_seed/."""

import sys
from pathlib import Path

from google.cloud import bigquery
from google.cloud.exceptions import Conflict
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deploy.tf_run import ENV_PATH, load_env

console = Console()

SEED_DIR = Path(__file__).parent.parent / "bq_seed"

SCHEMAS = {
    "customers": [
        bigquery.SchemaField("customer_id", "STRING"),
        bigquery.SchemaField("name",        "STRING"),
        bigquery.SchemaField("dob",         "STRING"),
        bigquery.SchemaField("postcode",    "STRING"),
        bigquery.SchemaField("address",     "STRING"),
        bigquery.SchemaField("age",         "INTEGER"),
        bigquery.SchemaField("gender",      "STRING"),
        bigquery.SchemaField("phone",       "STRING"),
    ],
    "accounts": [
        bigquery.SchemaField("account_id",   "STRING"),
        bigquery.SchemaField("customer_id",  "STRING"),
        bigquery.SchemaField("product_type", "STRING"),
        bigquery.SchemaField("balance",      "FLOAT"),
    ],
    "transactions": [
        bigquery.SchemaField("account_id",  "STRING"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("amount",      "FLOAT"),
        bigquery.SchemaField("type",        "STRING"),
        bigquery.SchemaField("date",        "STRING"),
    ],
}


def create_dataset(client: bigquery.Client, dataset_id: str, project: str) -> bigquery.Dataset:
    full_id = f"{project}.{dataset_id}"
    dataset = bigquery.Dataset(full_id)
    dataset.location = "US"
    try:
        ds = client.create_dataset(dataset)
        console.print(f"  Created dataset [cyan]{full_id}[/cyan]")
        return ds
    except Conflict:
        console.print(f"  Dataset [cyan]{full_id}[/cyan] already exists — skipping create")
        return client.get_dataset(full_id)


def create_table(client: bigquery.Client, dataset_id: str, project: str, table_name: str) -> None:
    table_ref = f"{project}.{dataset_id}.{table_name}"
    table = bigquery.Table(table_ref, schema=SCHEMAS[table_name])
    try:
        client.create_table(table)
        console.print(f"  Created table   [cyan]{table_name}[/cyan]")
    except Conflict:
        console.print(f"  Table [cyan]{table_name}[/cyan] already exists — skipping create")


def load_table(client: bigquery.Client, dataset_id: str, project: str, table_name: str) -> int:
    seed_file = SEED_DIR / f"{table_name}.json"
    if not seed_file.exists():
        console.print(f"  [yellow]No seed file found for {table_name} — skipping load[/yellow]")
        return 0

    table_ref = f"{project}.{dataset_id}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMAS[table_name],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with seed_file.open("rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=job_config)

    job.result()  # wait for completion
    table = client.get_table(table_ref)
    console.print(f"  Loaded  [cyan]{table_name}[/cyan] — [bold]{table.num_rows}[/bold] rows")
    return table.num_rows


def main() -> None:
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("Bank Agent", "bold bright_green"),
            (" — ", "dim white"),
            ("BigQuery Deploy", "bold white"),
        ),
        border_style="bright_green",
        padding=(0, 2),
    ))

    if not ENV_PATH.exists():
        console.print(f"[red]Error: {ENV_PATH} not found. Run `uv run setup-env` first.[/red]")
        sys.exit(1)

    dot_env = load_env(ENV_PATH)
    project = dot_env.get("GOOGLE_CLOUD_PROJECT", "")
    dataset_id = dot_env.get("BQ_DATASET", "")

    if not project:
        console.print("[red]Error: GOOGLE_CLOUD_PROJECT not set in .env[/red]")
        sys.exit(1)
    if not dataset_id:
        console.print("[red]Error: BQ_DATASET not set in .env[/red]")
        sys.exit(1)

    console.print(f"\n  Project : [cyan]{project}[/cyan]")
    console.print(f"  Dataset : [cyan]{dataset_id}[/cyan]")
    console.print()

    client = bigquery.Client(project=project)

    # Step 1: dataset
    console.print("  [bold]Step 1:[/bold] Dataset")
    create_dataset(client, dataset_id, project)
    console.print()

    # Step 2: tables
    console.print("  [bold]Step 2:[/bold] Tables")
    for table_name in SCHEMAS:
        create_table(client, dataset_id, project, table_name)
    console.print()

    # Step 3: seed data
    console.print("  [bold]Step 3:[/bold] Seed data")
    total_rows = 0
    for table_name in SCHEMAS:
        total_rows += load_table(client, dataset_id, project, table_name)
    console.print()

    console.print(Panel.fit(
        Text.assemble(
            ("Done! ", "bold bright_green"),
            (f"{total_rows} rows loaded into ", "white"),
            (f"{project}.{dataset_id}", "cyan"),
        ),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print()


if __name__ == "__main__":
    main()
