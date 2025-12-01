"""
Streaming endpoint with Server-Sent Events (SSE)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import json
import asyncio
import time
import uuid
import os

from langchain_core.messages import HumanMessage, BaseMessage

from app.database.connection import get_db
from app.agent.graph import create_agent_graph
from app.services.conversation_service import ConversationService
from app.api.routes import QueryRequest, AgentConfig, _history_to_llm_messages, _extract_previous_context
from app.auth import require_api_key

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

async def event_generator(state: dict, conversation_id: str, thread_id: str, query: str, agent_graph, requested_model: str):
    """
    Generate Server-Sent Events (SSE) for streaming response
    
    Yields events as the agent progresses through each step
    """
    from langchain_core.messages import AIMessage, ToolMessage
    
    conv_service = ConversationService()
    
    try:
        # Stream agent execution
        final_state = None
        
        config = {"configurable": {"thread_id": thread_id}}
        for step_update in agent_graph.stream(state, config=config):
            # Each iteration is a state update
            final_state = step_update
            
            # Extract messages from state
            messages = final_state.get("messages", [])
            if messages:
                last_msg = messages[-1]
                
                # Send events for tool calls
                if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                    event_data = {
                        "event": "tool_call",
                        "data": {
                            "tool": last_msg.tool_calls[0].get("name") if last_msg.tool_calls else None
                        }
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                    await asyncio.sleep(0)
                
                # Send events for tool results
                elif isinstance(last_msg, ToolMessage):
                    try:
                        tool_result = json.loads(last_msg.content)
                        steps = tool_result.get("steps", [])
                        for step in steps:
                            event_data = {
                                "event": "step_update",
                                "data": {"step": step}
                            }
                            yield f"data: {json.dumps(event_data)}\n\n"
                            await asyncio.sleep(0)
                    except json.JSONDecodeError:
                        pass
        
        if not final_state:
            raise Exception("Agent execution failed")
        
        # Extract results from messages
        messages = final_state.get("messages", [])
        
        # Find final response
        final_response = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                final_response = msg.content
                break
        
        # Find tool result
        sql_query = None
        dataset_id = None
        steps = []
        
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                try:
                    tool_result = json.loads(msg.content)
                    sql_query = tool_result.get("sql_query")
                    dataset_id = tool_result.get("dataset_id")
                    steps = tool_result.get("steps", [])
                    break
                except json.JSONDecodeError:
                    continue
        
        # Save conversation messages
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=query
        )
        
        conv_service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_response,
            sql_query=sql_query,
            datasets_used=[dataset_id] if dataset_id else [],
            steps=steps
        )

        # Send completion event
        completion_event = {
            "event": "complete",
            "data": {
                "conversation_id": conversation_id,
                "final_response": final_response,
                "sql_query": sql_query,
                "selected_dataset": dataset_id,
                "metadata": {
                    "model": requested_model
                }
            }
        }
        yield f"data: {json.dumps(completion_event)}\n\n"
        
    except Exception as e:
        # Send error event
        error_event = {
            "event": "error",
            "data": {
                "error": str(e)
            }
        }
        yield f"data: {json.dumps(error_event)}\n\n"

@router.post("/query/stream")
async def query_stream(request: QueryRequest, db: Session = Depends(get_db), _api_key = auth_dependency):
    """
    Execute query with Server-Sent Events (SSE) streaming
    
    Returns:
        StreamingResponse with events for each agent step
    
    Events emitted:
        - tool_call: Agent calling a tool
        - step_update: Tool completed a step
        - complete: Full response ready
        - error: An error occurred
    """
    
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
        
        return StreamingResponse(
            event_generator(initial_state, conversation_id, thread_id, request.query, agent_graph, requested_model),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
