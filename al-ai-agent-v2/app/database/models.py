"""
SQLAlchemy models for the AI Data Agent API
"""
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from datetime import datetime
from app.database.connection import Base


class DatasetMetadata(Base):
    """
    Stores dataset metadata with vector embeddings for similarity search
    """
    __tablename__ = "dataset_metadata"
    
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(String, unique=True, nullable=False, index=True)
    table_name = Column(String, nullable=False)
    description = Column(Text)
    embedding = Column(Vector(1536))  # OpenAI text-embedding-3-small dimension
    columns = Column(JSONB)  # Store column metadata as JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Conversation(Base):
    """
    Stores conversation sessions
    """
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    message_count = Column(Integer, default=0)
    agent_config = Column(JSONB, default={})
    is_deleted = Column(Boolean, default=False)


class Message(Base):
    """
    Stores individual messages in conversations
    """
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, unique=True, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    sql_query = Column(Text)
    datasets_used = Column(JSON)  # List of dataset IDs
    steps = Column(JSONB)  # Agent execution steps
    tokens_used = Column(Integer)
    execution_time_ms = Column(Integer)


class CacheEntry(Base):
    """
    Multi-level caching for SQL results, dataset selections, and responses
    """
    __tablename__ = "cache_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String, unique=True, nullable=False, index=True)
    cache_type = Column(String, nullable=False, index=True)  # sql_result, dataset_selection, etc.
    value = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))
    last_accessed = Column(DateTime(timezone=True), server_default=func.now())
    hit_count = Column(Integer, default=0)





