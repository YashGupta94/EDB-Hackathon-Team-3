import pytest
import os

# Add any common mock configurations or fixtures here
@pytest.fixture(autouse=True)
def setup_environment(monkeypatch):
    """Set up environment variables for testing."""
    # Example: monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    pass
