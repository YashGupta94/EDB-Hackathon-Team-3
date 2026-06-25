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
from bank_agent.tools.life_event_detector import detect_life_events
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
    name="life_event_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description=(
        "Proactively detects major life events (house purchase, new baby, inheritance/windfall, "
        "job change, retirement planning) from transaction patterns and provides timely, "
        "empathetic product and action recommendations."
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[detect_life_events, recommend_products, run_bigquery_query],
)
