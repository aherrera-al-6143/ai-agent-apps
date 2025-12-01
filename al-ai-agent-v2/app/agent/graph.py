"""
LangGraph workflow definition for the agent.

Supports two modes:
1. Legacy mode: Single ReAct agent with all tools (original behavior)
2. Routed mode: Semantic router + specialized sub-agents (recommended)
"""
from __future__ import annotations

import os
from typing import Annotated, Sequence, Literal

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver
from typing_extensions import TypedDict

from app.agent.tools import create_query_database_tool, create_generate_kpi_report_tool
from app.agent.prompts import KPI_AGENT_PROMPT, QUERY_AGENT_PROMPT
from app.agent.semantic_router import SemanticRouter
from app.database.connection import DATABASE_URL
from app.services.llm_service import LLMService


# =============================================================================
# CHECKPOINTER MANAGEMENT
# =============================================================================

_checkpointer: PostgresSaver | None = None
_checkpointer_cm = None  # Keep context manager alive


def initialize_checkpointer():
    """Initialize the checkpointer at application startup."""
    global _checkpointer, _checkpointer_cm
    if _checkpointer is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(DATABASE_URL)
        _checkpointer = _checkpointer_cm.__enter__()
        _checkpointer.setup()


def _get_checkpointer() -> PostgresSaver:
    """Get the initialized Postgres-backed LangGraph checkpointer."""
    global _checkpointer
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call initialize_checkpointer() at startup.")
    return _checkpointer


# =============================================================================
# STATE DEFINITIONS
# =============================================================================

class AgentState(TypedDict):
    """State for the ReAct agent (legacy mode)"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


class RoutedAgentState(TypedDict):
    """State for the routed agent with semantic classification"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    route: str  # "kpi" or "query"
    route_confidence: float
    route_method: str  # "keyword" or "llm"
    route_reasoning: str


# =============================================================================
# LLM CONFIGURATION
# =============================================================================

def _get_llm(agent_config: dict = None):
    """Get configured LLM instance."""
    if agent_config is None:
        agent_config = {}
    
    model_name = agent_config.get("model", os.getenv("DEFAULT_MODEL_VERSION", "google/gemini-2.5-flash"))
    
    # Determine API configuration
    if "google/" in model_name or "anthropic/" in model_name or os.getenv("OPEN_ROUTER_KEY"):
        api_key = os.getenv("OPEN_ROUTER_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
    
    return ChatOpenAI(
        model=model_name,
        temperature=0,
        max_tokens=2000,
        api_key=api_key,
        base_url=base_url
    )


# =============================================================================
# LEGACY MODE (Original single-agent approach)
# =============================================================================

def create_legacy_agent_graph(agent_config: dict = None, use_cache: bool = True):
    """
    Create the LEGACY agent (single ReAct agent with all tools).
    
    This is the original architecture - kept for backward compatibility.
    Use create_routed_agent_graph for better tool selection.
    
    Args:
        agent_config: Configuration dict with model, dataset_filter, etc.
        use_cache: Whether to use caching
    
    Returns:
        Compiled LangGraph agent
    """
    if agent_config is None:
        agent_config = {}
    
    # Create tools
    query_tool = create_query_database_tool(agent_config, use_cache)
    kpi_api_url = os.getenv("KPI_REPORTS_API_URL", "http://localhost:8001")
    kpi_report_tool = create_generate_kpi_report_tool(kpi_api_url)
    
    # Legacy system prompt (combined instructions for both tools)
    system_message = """You are a helpful data analyst assistant that answers questions about property data.

When a user asks a question:
1. FIRST check if previous ToolMessage objects contain the data you need
2. Check 'columns_queried' field to see what columns were fetched
3. Use 'rows_returned' for counts (NOT len(data))

TOOL SELECTION (CRITICAL):
═══════════════════════════════════════════════════════════════════

🎯 USE generate_kpi_report_tool WHEN user asks for:
- "strategic overview" of any office/region
- "portfolio analysis" or "portfolio health"
- "performance report" or "KPI report"
- "critical analysis" or "underperforming properties"
- "top performers" analysis
- Any request implying a PDF/report output

📊 USE query_database_tool WHEN user asks for:
- Specific counts ("how many properties...")
- Raw data retrieval ("list all properties in...")
- Specific metrics ("what is the occupancy of...")
- Filtering questions ("properties lost in September...")
- Property-specific lookups ("tell me about Continental Tower")

═══════════════════════════════════════════════════════════════════

After getting results, provide clear, accurate answers with specific numbers.
"""
    
    llm = _get_llm(agent_config)
    
    agent = create_react_agent(
        llm,
        tools=[query_tool, kpi_report_tool],
        checkpointer=_get_checkpointer(),
        prompt=system_message
    )
    
    return agent


# =============================================================================
# ROUTED MODE (New semantic routing approach - RECOMMENDED)
# =============================================================================

def create_routed_agent_graph(agent_config: dict = None, use_cache: bool = True):
    """
    Create the ROUTED agent with semantic classification.
    
    Architecture:
    1. Semantic Router classifies query intent (keyword matching → LLM fallback)
    2. Routes to specialized sub-agent (KPI or Query)
    3. Each sub-agent has focused prompts and single tool
    
    Args:
        agent_config: Configuration dict with model, dataset_filter, etc.
        use_cache: Whether to use caching
    
    Returns:
        Compiled LangGraph StateGraph with routing
    """
    if agent_config is None:
        agent_config = {}
    
    # Initialize services
    llm = _get_llm(agent_config)
    llm_service = LLMService()
    router = SemanticRouter(llm_service)
    
    # Create specialized tools
    query_tool = create_query_database_tool(agent_config, use_cache)
    kpi_api_url = os.getenv("KPI_REPORTS_API_URL", "http://localhost:8001")
    kpi_report_tool = create_generate_kpi_report_tool(kpi_api_url)
    
    # Create specialized sub-agents
    kpi_agent = create_react_agent(
        llm,
        tools=[kpi_report_tool],
        prompt=KPI_AGENT_PROMPT
    )
    
    query_agent = create_react_agent(
        llm,
        tools=[query_tool],
        prompt=QUERY_AGENT_PROMPT
    )
    
    # =================================================================
    # GRAPH NODES
    # =================================================================
    
    def route_query(state: RoutedAgentState) -> dict:
        """
        Classify the incoming query and determine routing.
        Uses SemanticRouter for tiered classification.
        """
        messages = state.get("messages", [])
        
        # Find the last human message
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        
        if not last_human_message:
            # Default to query for safety
            return {
                "route": "query",
                "route_confidence": 0.5,
                "route_method": "default",
                "route_reasoning": "No human message found"
            }
        
        # Classify the query
        result = router.route(last_human_message.content)
        
        # Log the routing decision
        explanation = router.explain_route(result)
        print(f"[ROUTER] {explanation}")
        
        return {
            "route": result["route"],
            "route_confidence": result["confidence"],
            "route_method": result["method"],
            "route_reasoning": result.get("reasoning", result.get("matched_keyword", ""))
        }
    
    def validate_route(state: RoutedAgentState) -> dict:
        """
        Guardrail node to validate and log routing decisions.
        Can be extended with additional validation logic.
        """
        route = state.get("route", "query")
        confidence = state.get("route_confidence", 0)
        method = state.get("route_method", "unknown")
        reasoning = state.get("route_reasoning", "")
        
        # Log for monitoring/debugging
        print(f"[VALIDATE] Route: {route} | Confidence: {confidence:.2f} | Method: {method}")
        if reasoning:
            print(f"[VALIDATE] Reasoning: {reasoning}")
        
        # Future: Add more guardrails here
        # - Low confidence handling
        # - Route override rules
        # - Audit logging
        
        return {}  # No state changes needed
    
    def call_kpi_agent(state: RoutedAgentState) -> dict:
        """Execute the KPI agent."""
        # Extract just the messages for the sub-agent
        result = kpi_agent.invoke({"messages": state["messages"]})
        return {"messages": result["messages"]}
    
    def call_query_agent(state: RoutedAgentState) -> dict:
        """Execute the Query agent."""
        result = query_agent.invoke({"messages": state["messages"]})
        return {"messages": result["messages"]}
    
    def get_route(state: RoutedAgentState) -> Literal["kpi", "query"]:
        """Get the route from state for conditional edge."""
        return state.get("route", "query")
    
    # =================================================================
    # BUILD GRAPH
    # =================================================================
    
    workflow = StateGraph(RoutedAgentState)
    
    # Add nodes
    workflow.add_node("route", route_query)
    workflow.add_node("validate", validate_route)
    workflow.add_node("kpi_agent", call_kpi_agent)
    workflow.add_node("query_agent", call_query_agent)
    
    # Define edges
    workflow.set_entry_point("route")
    workflow.add_edge("route", "validate")
    
    # Conditional routing after validation
    workflow.add_conditional_edges(
        "validate",
        get_route,
        {
            "kpi": "kpi_agent",
            "query": "query_agent"
        }
    )
    
    # Terminal edges
    workflow.add_edge("kpi_agent", END)
    workflow.add_edge("query_agent", END)
    
    # Compile with checkpointer
    return workflow.compile(checkpointer=_get_checkpointer())


# =============================================================================
# FACTORY FUNCTION (Main Entry Point)
# =============================================================================

def create_agent_graph(agent_config: dict = None, use_cache: bool = True, use_routing: bool = True):
    """
    Create the agent graph.
    
    This is the main entry point. By default, uses the new routed architecture.
    Set use_routing=False for legacy single-agent behavior.
    
    Args:
        agent_config: Configuration dict with model, dataset_filter, etc.
        use_cache: Whether to use caching
        use_routing: If True (default), use semantic routing. If False, use legacy mode.
    
    Returns:
        Compiled LangGraph agent
    """
    # Check environment variable override
    env_routing = os.getenv("USE_SEMANTIC_ROUTING", "true").lower()
    if env_routing == "false":
        use_routing = False
    
    if use_routing:
        print("[AGENT] Using ROUTED agent architecture (semantic routing enabled)")
        return create_routed_agent_graph(agent_config, use_cache)
    else:
        print("[AGENT] Using LEGACY agent architecture (single ReAct agent)")
        return create_legacy_agent_graph(agent_config, use_cache)
