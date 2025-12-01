"""
LangGraph workflow definition for the agent
"""
from __future__ import annotations

from typing import Annotated, Sequence
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver

from app.agent.tools import create_query_database_tool, create_generate_kpi_report_tool
from app.database.connection import DATABASE_URL

_checkpointer: PostgresSaver | None = None
_checkpointer_cm = None  # Keep context manager alive


def initialize_checkpointer():
    """Initialize the checkpointer at application startup."""
    global _checkpointer, _checkpointer_cm
    if _checkpointer is None:
        # PostgresSaver.from_conn_string returns a context manager
        # We need to keep the context manager alive to prevent connection closure
        _checkpointer_cm = PostgresSaver.from_conn_string(DATABASE_URL)
        _checkpointer = _checkpointer_cm.__enter__()
        # Setup tables if they don't exist
        _checkpointer.setup()


def _get_checkpointer() -> PostgresSaver:
    """Get the initialized Postgres-backed LangGraph checkpointer."""
    global _checkpointer
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call initialize_checkpointer() at startup.")
    return _checkpointer


# Agent state for create_react_agent
class AgentState(TypedDict):
    """State for the ReAct agent"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


def create_agent_graph(agent_config: dict = None, use_cache: bool = True):
    """
    Create and compile the agent workflow using create_react_agent
    
    Args:
        agent_config: Configuration dict with model, dataset_filter, etc.
        use_cache: Whether to use caching
    
    Returns:
        Compiled LangGraph agent
    """
    if agent_config is None:
        agent_config = {}
    
    # Create the configured query tool
    query_tool = create_query_database_tool(agent_config, use_cache)
    
    # Create the KPI report generation tool
    # URL can be configured via environment variable
    kpi_api_url = os.getenv("KPI_REPORTS_API_URL", "http://localhost:8001")
    kpi_report_tool = create_generate_kpi_report_tool(kpi_api_url)
    
    # System message with instructions
    system_message = """You are a helpful data analyst assistant that answers questions about property data.

When a user asks a question:
1. FIRST check if previous ToolMessage objects in the conversation history contain the data you need
2. Check the 'columns_queried' field in previous tool results to see what columns were fetched
3. If you already have the data AND all needed columns, use it to answer directly WITHOUT calling the tool again
4. If you need columns that are NOT in 'columns_queried' from previous results, you MUST call the tool again
5. ONLY call the query_database_tool when you need NEW data or DIFFERENT columns than what's in previous results

Previous query results are stored in ToolMessage objects in the conversation history. These contain:
- 'sql_query': The SQL query that was executed
- 'data': The complete dataset rows returned
- 'rows_returned': The TOTAL count of rows (use this for counts, NOT len(data))
- 'columns_queried': LIST of column names that were fetched (IMPORTANT: check this!)
- 'query_type': Either "raw_data" (has all columns) or "aggregation" (has specific columns only)
- Other metadata about the query

CRITICAL - Using Query Result Metadata:
- ALWAYS use 'rows_returned' field for the total count (do NOT count items in data array)
- The 'data' field may be a sample (limited for performance)
- For accurate counts and totals, use the metadata values provided

CRITICAL COLUMN CHECKING RULES:
- If query_type is "raw_data" → all columns available, safe to answer follow-ups
- If query_type is "aggregation" → only specific columns available, check 'columns_queried' list
- If user asks about a column NOT in 'columns_queried', you MUST call the tool again with the new query
- Examples:
  * Previous: columns_queried=["property_name", "loss_date"], user asks "summarize by office" → MUST call tool (need "office" column)
  * Previous: query_type="raw_data", user asks "summarize by office" → Can use existing data (has all columns)

Use the query_database_tool to get fresh data from the database when:
- User asks for information requiring columns not in 'columns_queried'
- User wants different filters or date ranges
- This is a new query about different data
- Previous query_type was "aggregation" and user needs different columns

Do NOT call the tool when:
- User asks "are you sure?" or similar clarification questions
- You have query_type="raw_data" and can answer from existing data
- You have the exact columns needed in 'columns_queried' from previous aggregation results
- User is asking follow-up questions answerable with existing data

After getting results, provide clear, accurate answers with specific numbers from the data.

CRITICAL - Reporting Counts:
When reporting how many items were found, you MUST use the 'rows_returned' value from the tool result.
DO NOT manually count items in the 'data' array - always use 'rows_returned' for accuracy.

RESPONSE FORMAT:
- If results have ≤10 items: List all items
- If results have >10 items: Provide the EXACT count, a brief summary, and 3-5 sample items
- IMPORTANT: Use the actual row count from the data. Do NOT use words like "top" or "best" - just say "Here are 5 examples:" or "Sample properties:"

KPI REPORT GENERATION:
When users ask for KPI reports, portfolio analysis, or performance overviews, use the generate_kpi_report tool.
Available report types:
- strategic_overview: High-level portfolio health and performance distribution
- critical_analysis: Focus on worst-performing properties needing attention
- top_performers: Analysis of best-performing properties and success patterns
- operational_focus: Operational issues requiring immediate action

When generating reports:
1. Confirm the office/region with the user if not specified
2. Ask about filters (stabilized properties, exclude lease-up) if relevant
3. Generate the report and share the PDF path
4. The response includes SQL queries used - use these for follow-up questions
5. The stats object can be used to answer detailed questions about the report
"""
    
    # Import LLM model
    from langchain_openai import ChatOpenAI
    import os
    
    # Get model from config or use default
    model_name = agent_config.get("model", os.getenv("DEFAULT_MODEL_VERSION", "google/gemini-2.5-flash"))
    
    # Determine API configuration
    # If using OpenRouter (google/, anthropic/, etc. models), use OPEN_ROUTER_KEY
    # Otherwise use standard OPENAI_API_KEY
    if "google/" in model_name or "anthropic/" in model_name or os.getenv("OPEN_ROUTER_KEY"):
        api_key = os.getenv("OPEN_ROUTER_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
    
    # Configure the LLM
    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        max_tokens=2000,
        api_key=api_key,
        base_url=base_url
    )
    
    # Create the ReAct agent with the tools
    agent = create_react_agent(
        llm,
        tools=[query_tool, kpi_report_tool],
        checkpointer=_get_checkpointer(),
        prompt=system_message
    )
    
    return agent


