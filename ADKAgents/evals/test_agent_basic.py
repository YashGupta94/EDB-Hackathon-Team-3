import pytest
from bank_agent.agent import root_agent
import os

@pytest.mark.asyncio
async def test_agent_properties():
    """Test that the agent is configured correctly."""
    assert root_agent.name == "bank_agent"
    assert "banking assistant" in root_agent.description.lower()
    # Check if the agent has a model configured
    assert root_agent.model is not None


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"),
    reason="API key not found, skipping live agent evaluation."
)
async def test_live_agent_response():
    """
    Live evaluation of the agent.
    This test actually runs the agent against the LLM if an API key is provided.
    """
    test_message = "Hi, I need help with my bank account."
    
    # Run the agent asynchronously
    response = await root_agent.run_async(test_message)
    
    # The response should typically be a string or a structured output
    # Let's assert it's not empty and contains expected keywords
    assert response is not None
    output_text = str(response).lower()
    
    # We expect the banking assistant to acknowledge the user's account request
    assert any(word in output_text for word in ["how", "help", "account", "assist"])
