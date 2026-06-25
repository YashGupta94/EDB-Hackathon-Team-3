import os
from functools import cached_property

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import Client

from .observability import (
    after_model_callback,
    before_model_callback,
    setup_observability,
)
from .prompt import AGENT_INSTRUCTION
from .tools.bigquery_tool import run_bigquery_query
from .tools.customersearch import customer_database_search, customer_id_search
from .tools.productsearch import vertex_vector_search
from .tools.ecommerce_tools import lookup_user_orders, check_product_stock, sales_reporting_query
from .tools.spending_habits import spending_habits_report, spending_habits_for_user
from .tools.customer_profile import get_customer_profile
from .tools.product_recommendation import recommend_products
from .tools.financial_wellbeing import calculate_wellbeing_score
from .tools.life_event_detector import detect_life_events

load_dotenv()


class VertexGemini(Gemini):
    """Gemini model that unconditionally uses Vertex AI (ADC) instead of an API key."""

    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )


setup_observability()

root_agent = Agent(
    name="bank_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description="A helpful UK retail banking assistant.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        # Identity & customer data
        customer_id_search,
        customer_database_search,
        # Spending analysis
        spending_habits_report,
        spending_habits_for_user,
        # Financial profiling
        get_customer_profile,
        calculate_wellbeing_score,
        # Product intelligence
        recommend_products,
        # Life event detection (standout feature)
        detect_life_events,
        # Search & discovery
        vertex_vector_search,
        run_bigquery_query,
        # Ecommerce
        lookup_user_orders,
        check_product_stock,
        sales_reporting_query,
    ],
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
)
