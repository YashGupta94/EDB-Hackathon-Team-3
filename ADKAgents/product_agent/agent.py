import os
from functools import cached_property
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import Client

load_dotenv(
    str(Path(__file__).resolve().parent.parent / "bank_agent" / ".env"),
    override=True,
)

from .prompt import AGENT_INSTRUCTION
from bank_agent.tools.product_recommendation import recommend_products
from bank_agent.tools.bigquery_tool import run_bigquery_query


class VertexGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )


root_agent = Agent(
    name="product_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description=(
        "A UK banking product specialist that recommends the most relevant savings, ISA, "
        "mortgage, and current account products based on a customer's financial profile and life stage."
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[recommend_products, run_bigquery_query],
)
