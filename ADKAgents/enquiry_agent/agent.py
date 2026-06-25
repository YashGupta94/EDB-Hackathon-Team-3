import os
from functools import cached_property
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval
from google.genai import Client

load_dotenv(
    str(Path(__file__).resolve().parent.parent / "bank_agent" / ".env"),
    override=True,
)

from .prompt import AGENT_INSTRUCTION


class VertexGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )


rag_tool = VertexAiRagRetrieval(
    name="bankcorpus_retrieval",
    description=(
        "Retrieve relevant information from the bank's knowledge corpus (bankcorpus) "
        "to answer customer enquiries about products, policies, and services."
    ),
    rag_corpora=[os.getenv("RAG_CORPUS_NAME", "")],
    similarity_top_k=5,
    #vector_distance_threshold=0.5,
)

root_agent = Agent(
    name="enquiry_agent",
    model=VertexGemini(model="gemini-2.5-flash"),
    description=(
        "Answers customer enquiries by performing semantic searches against "
        "the bank's RAG knowledge corpus and returning grounded answers with citations."
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[rag_tool],
)
