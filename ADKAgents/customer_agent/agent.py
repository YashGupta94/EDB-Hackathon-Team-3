import os
from functools import cached_property
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import Client

# Load the shared bank_agent environment explicitly so tools have dataset/project settings.
load_dotenv(
    str(Path(__file__).resolve().parent.parent / "bank_agent" / ".env"),
    override=True,
)

from .prompt import AGENT_INSTRUCTION
from bank_agent.tools.bigquery_tool import run_bigquery_query
from bank_agent.tools.customersearch import customer_database_search, customer_id_search


class VertexGemini(Gemini):
    """Gemini model that unconditionally uses Vertex AI (ADC) instead of an API key."""

    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )


root_agent = Agent(
    name="customer_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description="A helpful customer agent to retrieve customer information.",
    instruction=AGENT_INSTRUCTION,
    #tools=[customer_id_search, customer_database_search, vertex_vector_search, run_bigquery_query, lookup_user_orders, check_product_stock, sales_reporting_query, spending_habits_report],
    tools=[customer_id_search, customer_database_search, run_bigquery_query],
)
