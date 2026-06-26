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
from bank_agent.tools.ecommerce_tools import lookup_user_orders, sales_reporting_query
from bank_agent.tools.spending_habits import spending_habits_for_user


class VertexGemini(Gemini):
    """Gemini model that uses Vertex AI ADC for this agent."""

    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )


root_agent = Agent(
    name="spending_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description="A dedicated spending habits assistant.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        spending_habits_for_user,
        run_bigquery_query,
    ],
)
