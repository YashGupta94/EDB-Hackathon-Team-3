from google.adk.agents import Agent

from .observability import (
    after_model_callback,
    before_model_callback,
    setup_observability,
)
from .prompt import AGENT_INSTRUCTION

# Initialise OpenTelemetry exporters and the metrics store.
setup_observability()

root_agent = Agent(
    name="bank_agent",
    model="gemini-2.5-flash",
    description="A helpful banking assistant.",
    instruction=AGENT_INSTRUCTION,
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
)
