"""
Query endpoints (non-streaming)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Tuple, Any
from sqlalchemy.orm import Session
import time
import uuid
import os

from app.database.connection import get_db
from app.agent.graph import create_agent_graph
from app.services.conversation_service import ConversationService
from app.services.llm_service import LLMService
from app.auth import require_api_key
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage, SystemMessage

router = APIRouter()

# Create a conditional auth dependency
def get_auth_dependency():
    """Get authentication dependency based on environment."""
    if os.getenv("ENVIRONMENT", "development") == "production":
        api_key = os.getenv("AZURE_AGENT_API_KEY") or os.getenv("API_KEY") or os.getenv("API_SECRET_KEY")
        if api_key:
            return require_api_key()
    # Return a no-op dependency for development
    async def no_auth():
        return None
    return Depends(no_auth)

# Create auth dependency
auth_dependency = get_auth_dependency()

# Conversation utilities
def _history_to_llm_messages(history: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert stored conversation history into LangChain message objects."""
    messages: List[BaseMessage] = []
    for message in history:
        role = message.get("role")
        content = message.get("content", "")
        if not content:
            continue

        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


def _summarize_conversation_if_needed(
    messages: List[BaseMessage],
    existing_summary: Optional[str],
    model: str
) -> Tuple[List[BaseMessage], Optional[str]]:
    """
    Summarize conversation if it exceeds 5 turns (10 messages).
    Returns: (trimmed_messages, new_summary)
    """
    MAX_TURNS = 5
    MAX_MESSAGES = MAX_TURNS * 2  # 5 turns = 10 messages
    
    if len(messages) <= MAX_MESSAGES:
        return messages, existing_summary
    
    # Separate messages into: older (to summarize) and recent (to keep)
    messages_to_summarize = messages[:-MAX_MESSAGES]
    messages_to_keep = messages[-MAX_MESSAGES:]
    
    # Format messages for summarization
    def _format_messages_for_summary(msgs: List[BaseMessage]) -> str:
        lines = []
        for msg in msgs:
            if isinstance(msg, AIMessage):
                speaker = "Assistant"
            elif isinstance(msg, HumanMessage):
                speaker = "User"
            else:
                speaker = msg.type.title()
            lines.append(f"{speaker}: {msg.content}")
        return "\n".join(lines)
    
    # Build summary prompt
    summary_prompt = f"""Summarize the following conversation history. Focus on:
1. Key queries asked by the user
2. Important datasets/tables used
3. Key filters, metrics, or dimensions mentioned
4. Any important context or patterns

Previous summary (if any): {existing_summary or "None"}

Conversation to summarize:
{_format_messages_for_summary(messages_to_summarize)}

Provide a concise summary that captures the essential context for future queries."""

    try:
        llm_service = LLMService()
        summary_messages = [
            {
                "role": "system",
                "content": "You are a conversation summarizer. Create concise summaries that preserve key context for data queries."
            },
            {"role": "user", "content": summary_prompt}
        ]
        
        new_summary = llm_service.generate(summary_messages, temperature=0.1, max_tokens=2000, model=model)
        
        # Return recent messages + summary message
        summary_message = SystemMessage(content=f"[Conversation Summary]: {new_summary}")
        trimmed_messages = [summary_message] + messages_to_keep
        
        return trimmed_messages, new_summary
    except Exception as e:
        print(f"Warning: Conversation summarization failed: {str(e)}")
        # Return original messages if summarization fails
        return messages, existing_summary


def _extract_previous_context(history: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[Dict]]:
    """Extract the most recent SQL query, result summary, dataset_id, and metadata from history."""
    previous_sql: Optional[str] = None
    previous_summary: Optional[str] = None
    previous_dataset_id: Optional[str] = None
    previous_metadata: Optional[Dict] = None

    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        if not metadata:
            continue

        if not previous_sql:
            previous_sql = metadata.get("sql_query")

        if not previous_summary:
            datasets = metadata.get("datasets_used") or []
            steps = metadata.get("steps") or []
            rows_returned = None
            for step in reversed(steps):
                if step.get("step") == "execute_query":
                    rows_returned = step.get("rows_returned")
                    break

            parts: List[str] = []
            if datasets:
                parts.append(f"Datasets: {', '.join(datasets)}")
            if rows_returned is not None:
                parts.append(f"Rows returned: {rows_returned}")

            if parts:
                previous_summary = "; ".join(parts)

        if not previous_dataset_id:
            # Try to get dataset from metadata
            selected_dataset = metadata.get("selected_dataset")
            datasets_used = metadata.get("datasets_used") or []
            if selected_dataset:
                previous_dataset_id = selected_dataset
            elif datasets_used:
                previous_dataset_id = datasets_used[0] if isinstance(datasets_used, list) else datasets_used

        if previous_sql and previous_summary and previous_dataset_id:
            # Store metadata for reuse - try to get columns from steps metadata
            previous_metadata = {
                "dataset_id": previous_dataset_id,
                "dataset_name": metadata.get("selected_dataset_name") or previous_dataset_id,
            }
            
            # Extract selected_metadata from steps if available
            steps = metadata.get("steps") or []
            for step in reversed(steps):
                if isinstance(step, dict) and step.get("_metadata"):
                    step_metadata = step["_metadata"]
                    if step_metadata.get("selected_metadata"):
                        selected_meta = step_metadata["selected_metadata"]
                        previous_metadata["columns"] = selected_meta.get("columns", [])
                        previous_metadata["all_rows"] = selected_meta.get("all_rows", [])
                        previous_metadata["rows_shown"] = selected_meta.get("rows_shown", 0)
                        if step_metadata.get("selected_dataset_name"):
                            previous_metadata["dataset_name"] = step_metadata["selected_dataset_name"]
                        break
            
            break

    return previous_sql, previous_summary, previous_dataset_id, previous_metadata


# Request/Response Models
class AgentConfig(BaseModel):
    dataset_filter: Optional[List[str]] = None
    model: Optional[str] = Field(default=None, description="Model ID to use (e.g. google/gemini-2.5-flash)")
    temperature: float = 0
    use_cache: bool = True

class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for context")
    agent_config: Optional[AgentConfig] = Field(default_factory=AgentConfig)

class QueryResponse(BaseModel):
    query_id: str
    conversation_id: str
    timestamp: str
    user_id: str
    steps: List[Dict]
    final_response: str
    sql_query: Optional[str]
    data_sample: Optional[List] = None
    rows_returned: Optional[int] = None
    metadata: Dict

# Main query endpoint (non-streaming)
@router.post("/query", response_model=QueryResponse)
async def query_data(
    request: QueryRequest, 
    db: Session = Depends(get_db),
    _api_key = auth_dependency
):
    """
    Execute a natural language query against Domo datasets
    
    This endpoint:
    1. Uses LLM agent with tool calling
    2. Agent decides when to query database vs use previous results
    3. Returns natural language response
    """
    import json
    from langchain_core.messages import ToolMessage
    
    start_time = time.time()
    query_id = f"query_{uuid.uuid4().hex[:16]}"
    
    # Initialize services
    conv_service = ConversationService()
    
    try:
        # Create or get conversation
        if not request.conversation_id:
            conversation_id = conv_service.create_conversation(
                user_id=request.user_id,
                agent_config=request.agent_config.dict() if request.agent_config else {}
            )
        else:
            conversation_id = request.conversation_id
        
        # Get conversation history
        raw_history = conv_service.get_conversation_history(conversation_id)
        history_messages = _history_to_llm_messages(raw_history)
        thread_id = conversation_id
        
        # Resolve model
        default_model = os.getenv("DEFAULT_MODEL_VERSION", "google/gemini-2.5-flash")
        requested_model = request.agent_config.model if request.agent_config and request.agent_config.model else default_model
        
        # Update agent config
        if request.agent_config and not request.agent_config.model:
            request.agent_config.model = requested_model
        elif not request.agent_config:
            request.agent_config = AgentConfig(model=requested_model)
        
        # Create agent with configuration
        agent_config_dict = request.agent_config.dict() if request.agent_config else {"model": requested_model}
        use_cache = request.agent_config.use_cache if request.agent_config else True
        agent_graph = create_agent_graph(agent_config=agent_config_dict, use_cache=use_cache)
        
        # Build initial state with messages
        initial_messages: List[BaseMessage] = history_messages + [
            HumanMessage(content=request.query)
        ]
        initial_state = {
            "messages": initial_messages
        }
        
        # Run agent
        config = {"configurable": {"thread_id": thread_id}}
        final_state = agent_graph.invoke(initial_state, config=config)
        
        total_time = int((time.time() - start_time) * 1000)
        
        # Extract results from messages
        messages = final_state.get("messages", [])
        
        # Find the last AIMessage (final response)
        final_response = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                final_response = msg.content
                break
        
        # Find the last ToolMessage (query results)
        tool_result = None
        sql_query = None
        dataset_id = None
        dataset_name = None
        rows = []
        rows_returned = 0
        steps = []
        
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                try:
                    tool_result = json.loads(msg.content)
                    sql_query = tool_result.get("sql_query")
                    dataset_id = tool_result.get("dataset_id")
                    dataset_name = tool_result.get("dataset_name")
                    # Tool returns "data" key, not "rows"
                    rows = tool_result.get("data", tool_result.get("rows", []))
                    rows_returned = tool_result.get("rows_returned", len(rows))
                    steps = tool_result.get("steps", [])
                    break
                except json.JSONDecodeError:
                    continue
        
        # Save conversation messages
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=request.query
        )
        
        conv_service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_response,
            sql_query=sql_query,
            datasets_used=[dataset_id] if dataset_id else [],
            steps=steps,
            execution_time_ms=total_time
        )
        
        # Format response
        return QueryResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            user_id=request.user_id,
            steps=steps,
            final_response=final_response,
            sql_query=sql_query,
            data_sample=rows[:100] if rows else [],
            rows_returned=rows_returned,
            metadata={
                "execution_time_ms": total_time,
                "selected_dataset": dataset_id,
                "model": requested_model
            }
        )
        
    except Exception as e:
        import traceback
        print(f"Query error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
