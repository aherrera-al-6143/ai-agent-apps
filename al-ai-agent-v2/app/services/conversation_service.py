"""
Service for managing conversation history
"""
from datetime import datetime
from typing import List, Optional, Dict
import uuid
from sqlalchemy.orm import Session
from app.database.models import Conversation, Message
from app.database.connection import SessionLocal


class ConversationService:
    """Service for managing conversation history"""
    
    def create_conversation(
        self, 
        user_id: str, 
        title: Optional[str] = None,
        agent_config: Optional[Dict] = None
    ) -> str:
        """
        Create new conversation
        
        Args:
            user_id: User identifier
            title: Optional conversation title
            agent_config: Optional agent configuration
        
        Returns:
            conversation_id
        """
        conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
        
        db = SessionLocal()
        try:
            conversation = Conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                agent_config=agent_config or {}
            )
            db.add(conversation)
            db.commit()
            
            return conversation_id
            
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to create conversation: {str(e)}")
        finally:
            db.close()
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sql_query: Optional[str] = None,
        datasets_used: Optional[List[str]] = None,
        steps: Optional[List[Dict]] = None,
        tokens_used: Optional[int] = None,
        execution_time_ms: Optional[int] = None
    ) -> str:
        """
        Add message to conversation
        
        Args:
            conversation_id: Target conversation
            role: 'user' or 'assistant'
            content: Message content
            sql_query: SQL generated (for assistant messages)
            datasets_used: Datasets queried (for assistant messages)
            steps: Agent steps taken (for assistant messages)
            tokens_used: LLM tokens consumed
            execution_time_ms: Total execution time
        
        Returns:
            message_id
        """
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        
        db = SessionLocal()
        try:
            message = Message(
                message_id=message_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                timestamp=datetime.now(),
                sql_query=sql_query,
                datasets_used=datasets_used,
                steps=steps,
                tokens_used=tokens_used,
                execution_time_ms=execution_time_ms
            )
            db.add(message)
            
            # Update conversation
            conversation = db.query(Conversation).filter(
                Conversation.conversation_id == conversation_id
            ).first()
            
            if conversation:
                conversation.message_count += 1
                conversation.updated_at = datetime.now()
                
                # Auto-generate title from first user message
                if not conversation.title and role == "user" and conversation.message_count == 1:
                    conversation.title = self._generate_title(content)
            
            db.commit()
            return message_id
            
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to add message: {str(e)}")
        finally:
            db.close()
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get messages in a conversation
        
        Args:
            conversation_id: Target conversation
            limit: Optional limit on number of messages
        
        Returns:
            List of message dictionaries
        """
        db = SessionLocal()
        try:
            query = db.query(Message).filter(
                Message.conversation_id == conversation_id
            ).order_by(Message.timestamp.asc())
            
            if limit:
                query = query.limit(limit)
            
            messages = query.all()
            
            return [
                {
                    "message_id": msg.message_id,
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "metadata": {
                        "sql_query": msg.sql_query,
                        "datasets_used": msg.datasets_used,
                        "steps": msg.steps,
                        "tokens_used": msg.tokens_used,
                        "execution_time_ms": msg.execution_time_ms
                    } if msg.role == "assistant" else None
                }
                for msg in messages
            ]
            
        finally:
            db.close()
    
    def get_user_conversations(self, user_id: str) -> List[Dict]:
        """
        Get all conversations for a user
        
        Args:
            user_id: User identifier
        
        Returns:
            List of conversation summaries
        """
        db = SessionLocal()
        try:
            conversations = db.query(Conversation).filter(
                Conversation.user_id == user_id,
                Conversation.is_deleted == False
            ).order_by(Conversation.updated_at.desc()).all()
            
            return [
                {
                    "conversation_id": conv.conversation_id,
                    "title": conv.title,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "message_count": conv.message_count
                }
                for conv in conversations
            ]
            
        finally:
            db.close()
    
    def format_history_for_llm(
        self,
        conversation_id: str,
        last_n_messages: int = 10
    ) -> List[Dict]:
        """
        Format conversation history for LLM context
        
        Args:
            conversation_id: Target conversation
            last_n_messages: Number of recent messages to include
        
        Returns:
            List of messages in Claude API format
        """
        history = self.get_conversation_history(conversation_id, limit=last_n_messages)
        
        # Format for Claude API
        return [
            {
                "role": msg["role"],
                "content": msg["content"]
            }
            for msg in history
        ]
    
    def delete_conversation(self, conversation_id: str):
        """Soft delete a conversation"""
        db = SessionLocal()
        try:
            conversation = db.query(Conversation).filter(
                Conversation.conversation_id == conversation_id
            ).first()
            
            if conversation:
                conversation.is_deleted = True
                db.commit()
                
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to delete conversation: {str(e)}")
        finally:
            db.close()
    
    def _generate_title(self, first_query: str) -> str:
        """Generate conversation title from first query"""
        # Simple truncation for v1
        # Could use LLM to generate better titles in production
        max_length = 50
        if len(first_query) <= max_length:
            return first_query
        return first_query[:max_length] + "..."





