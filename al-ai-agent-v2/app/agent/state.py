"""
Agent state definition for LangGraph workflow
"""
from __future__ import annotations

from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """
    Simplified state for ReAct agent.
    
    The agent uses messages for communication and tool results.
    All query results are stored in ToolMessage objects in the messages list.
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]


# Legacy state kept for backward compatibility with existing nodes
# Can be removed once full migration is complete
class LegacyAgentState(TypedDict, total=False):
    """Legacy state structure - kept for backward compatibility during migration"""
    # User input
    query: str
    user_id: str
    conversation_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Agent configuration
    agent_config: dict
    use_cache: bool
    
    # Workflow tracking
    steps: list[dict]
    cache_hits: dict
    
    # Results
    sql_query: str
    retrieved_data: dict
    final_response: str
    error: str | None


