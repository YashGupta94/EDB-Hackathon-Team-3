# Agent Evaluations

This directory contains evaluation scripts for your agents, tools, and MCP servers. 
Evaluations are crucial to ensure your agent responds reliably and behaves as expected when prompts or tools change.

## Setup

1. Install the development dependencies:
   ```bash
   uv pip install -e ".[dev]"
   ```

2. (Optional) Set any necessary environment variables for your tests (e.g., API keys if you are running live tests, although mocking is recommended).

## Running Evals

To run the evaluations, simply use pytest:

```bash
pytest evals/
```

## Structure

- `test_agent_basic.py`: A sample test to show how to evaluate an agent's response or state.
- `conftest.py`: Put your pytest fixtures here (like mocking API keys or creating dummy context).

## Tips for Hackathon Participants

- **Mock External Calls**: Use `unittest.mock` or `pytest-mock` to avoid making real API calls during evals, saving time and credits.
- **Eval Frameworks**: If you want more advanced metric-based evaluations (like LLM-as-a-judge), consider looking into frameworks like `promptfoo` or `langchain` evaluators. This template uses `pytest` for simple assertion-based evals.
