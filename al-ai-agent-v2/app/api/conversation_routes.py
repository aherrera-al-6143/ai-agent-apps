"""
Conversation CRUD endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
import time
import os

from app.database.connection import get_db
from app.services.conversation_service import ConversationService
from app.auth import require_api_key
from fastapi import Depends

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

# Request/Response Models
class CreateConversationRequest(BaseModel):
    user_id: str
    title: Optional[str] = None

class ConversationResponse(BaseModel):
    conversation_id: str
    user_id: str
    title: Optional[str]
    created_at: str
    updated_at: str
    message_count: int

# Get all conversations for a user
@router.get("/conversations/{user_id}")
async def get_user_conversations(user_id: str, _api_key = auth_dependency):
    """Get all conversations for a user"""
    conv_service = ConversationService()
    conversations = conv_service.get_user_conversations(user_id)
    return {"conversations": conversations}

# Get messages in a conversation
@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, _api_key = auth_dependency):
    """Get all messages in a conversation"""
    conv_service = ConversationService()
    messages = conv_service.get_conversation_history(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": messages
    }

# Create new conversation
@router.post("/conversations")
async def create_conversation(request: CreateConversationRequest, _api_key = auth_dependency):
    """Create a new conversation"""
    conv_service = ConversationService()
    conversation_id = conv_service.create_conversation(
        user_id=request.user_id,
        title=request.title
    )
    return {
        "conversation_id": conversation_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

# Delete conversation
@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, _api_key = auth_dependency):
    """Soft delete a conversation"""
    conv_service = ConversationService()
    conv_service.delete_conversation(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}

