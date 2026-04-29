# EDB Hackathon Starter

A starter template for building AI agents with [Google ADK](https://google.github.io/adk-docs/), Vertex AI Search, and Firestore. It includes synthetic data generation, a vector search tool, and a customer database tool — ready for you to wire into your own agent.

## What's Included

```
EDB-Hackathon-Starter/
├── DataGen/                  # Synthetic data pipeline (CSV → Firestore / SQLite)
└── ADKAgents/
    ├── bank_agent/
    │   ├── agent.py          # Your base agent — start here
    │   ├── prompt.py         # Agent instructions
    │   └── tools/
    │       ├── customersearch.py   # Customer lookup (Firestore or SQLite)
    │       └── productsearch.py    # Vertex AI vector search
    ├── deploy/
    │   ├── main.tf           # Terraform — provisions Vertex AI Search data store
    │   ├── tf_deploy.py      # One-shot Terraform deploy
    │   └── tf_run.py         # Terraform wrapper (passes .env as TF vars)
    └── setup_env.py          # Interactive .env setup
```

## Prerequisites

- **Python 3.14+** — [python.org/downloads](https://www.python.org/downloads/)
- **uv** — [docs.astral.sh/uv/getting-started/installation](https://docs.astral.sh/uv/getting-started/installation/)
- **Terraform** — [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install)
- **Google Cloud SDK** — [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
- A Google Cloud project with billing enabled

---

## Setup

### 1. Install dependencies

```bash
cd ADKAgents
uv sync
```

### 2. Authenticate with Google Cloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project {YOUR_PROJECT_ID}
```

### 3. Configure your environment

Run the interactive setup — it will write `bank_agent/.env`:

```bash
uv run setup-env
```

You'll be prompted for:

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key — get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GOOGLE_CLOUD_PROJECT` | Your GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | GCP location (default: `global`) |
| `WEBSITE_DOMAIN` | Domain for Terraform to crawl (e.g. `www.example.com`) |
| `VERTEX_DATA_STORE_ID` | Leave blank for now — populated after Terraform deploy |
| `USE_DATASTORE` | `true` for Firestore, anything else uses local SQLite |

### 4. Deploy the Vertex AI Search data store

```bash
uv run tf-deploy
```

This runs `terraform init` + `terraform apply` and outputs your `VERTEX_DATA_STORE_ID`. Re-run `uv run setup-env` and paste it in.

You can also run individual Terraform commands via the `tf` wrapper:

```bash
uv run tf plan
uv run tf apply
uv run tf output -raw vertex_data_store_id
uv run tf destroy
```

### 5. Generate synthetic data

```bash
cd ../DataGen
uv sync

# Generate CSVs
uv run python dataFakeGen.py

# Merge into per-customer JSON documents
uv run python prepare_for_nosql.py

# Load into local SQLite (for local dev)
uv run python localdb_setup.py

# Or upload to Firestore (set USE_DATASTORE=true in .env)
uv run python upload_to_datestore.py
```

### 6. Run the agent locally

```bash
cd ../ADKAgents
adk web
```

---

## IAM Permissions

IAM roles are provisioned by Terraform alongside the data store. Set `member_email` in your `.tfvars` or pass it via `-var`:

```hcl
# terraform.tfvars
member_email = "user:you@example.com"
# or for a service account:
# member_email = "serviceAccount:sa@your-project.iam.gserviceaccount.com"
```

Terraform grants `roles/discoveryengine.viewer`, `roles/aiplatform.user`, and `roles/datastore.user` to that identity.

---

## Building Your Agent

Open `ADKAgents/bank_agent/agent.py`. You'll find a minimal base agent:

```python
from google.adk.agents import Agent
from .prompt import AGENT_INSTRUCTION

root_agent = Agent(
    name="bank_agent",
    model="gemini-2.5-flash",
    description="A helpful banking assistant.",
    instruction=AGENT_INSTRUCTION,
)
```

The tools in `tools/` are ready to import and attach:

| Tool | Import | Description |
|---|---|---|
| `customer_id_search` | `from .tools.customersearch import customer_id_search` | Look up a customer by ID |
| `customer_database_search` | `from .tools.customersearch import customer_database_search` | Full profile + transaction history |
| `vertex_vector_search` | `from .tools.productsearch import vertex_vector_search` | Semantic search over your website |

Add them to an agent's `tools` list to start using them.

To build multi-agent pipelines, pass other `Agent` instances via `sub_agents=[...]`. Each sub-agent is invoked by name, and any inputs are forwarded as named keyword arguments matching its tool signatures.

---

## Deploy to Cloud Run

### 1. Build the container

```bash
gcloud builds submit --tag us-central1-docker.pkg.dev/{YOUR_PROJECT_ID}/{YOUR_REPO}/agent:latest .
```

### 2. Deploy via Terraform

Set `container_image` and `google_api_key` in your `.tfvars`, then run `uv run tf-deploy`. Terraform provisions the Cloud Run service, wires in all environment variables from the data store output, and grants public invoker access.

```hcl
# terraform.tfvars
container_image = "us-central1-docker.pkg.dev/{YOUR_PROJECT_ID}/{YOUR_REPO}/agent:latest"
google_api_key  = "{YOUR_GOOGLE_API_KEY}"
```

The public URL is printed as the `cloud_run_url` output.
