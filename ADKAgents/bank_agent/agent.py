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
from .tools.productsearch import vertex_vector_search
from .tools.ecommerce_tools import lookup_user_orders, check_product_stock, sales_reporting_query
from .tools.spending_habits import spending_habits_report

from customer_agent.agent import root_agent as customer_agent
from enquiry_agent.agent import root_agent as enquiry_agent
from spending_agent.agent import root_agent as spending_agent
from customer_profile_agent.agent import root_agent as customer_profile_agent
from financial_wellbeing_agent.agent import root_agent as financial_wellbeing_agent
from life_event_agent.agent import root_agent as life_event_agent
from product_agent.agent import root_agent as product_agent

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
    description="Central orchestrator for a UK retail banking assistant.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        # Cross-customer aggregate analytics (not customer-specific)
        spending_habits_report,
        # Semantic search on banking policies and FAQs
        # vertex_vector_search,
        # Generic read-only SQL analytics
        # run_bigquery_query,
        # Ecommerce data
        # lookup_user_orders,
        # check_product_stock,
        # sales_reporting_query,
    ],
    sub_agents=[
        customer_agent,
        enquiry_agent,
        spending_agent,
        customer_profile_agent,
        financial_wellbeing_agent,
        life_event_agent,
        product_agent,
    ],
    #tools=[customer_id_search, customer_database_search, vertex_vector_search, run_bigquery_query, lookup_user_orders, check_product_stock, sales_reporting_query, spending_habits_report],
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
)
