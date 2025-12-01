Perfect! Let me add a comprehensive summary/quick start guide at the top, then continue with the remaining implementation details.

---

# AI Data Agent API - Architecture Plan v3

## 📋 IMPORTANT: How to Use This Document

**This is an architectural guide and template, not a rigid specification.**

- ✅ **Use as a reference:** The overall architecture and patterns should guide your implementation
- ✅ **Adapt as needed:** Modify components, adjust flows, and simplify where appropriate
- ✅ **Test incrementally:** Build and test each layer before moving to the next
- ✅ **Seek confirmation:** Validate each major component works before adding complexity

**DO NOT blindly implement everything at once.** Build iteratively, test frequently, and adjust based on what you learn.

---

## 🚀 Quick Start Guide

### Phase 1: Database & Core Services (Day 1)
**Goal:** Get PostgreSQL running and test basic connections

```bash
# 1. Start PostgreSQL
docker-compose up -d

# 2. Verify database is running
docker ps

# 3. Test connection
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent

# 4. Run init.sql if not auto-loaded
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent -f init.sql
```

**Test checkpoint:** Can you connect to the database and see the tables?

### Phase 2: Vector Setup (Day 1-2)
**Goal:** Index your 2 test datasets into vector database

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Verify .env is configured
cat .env  # Check all keys are present

# 3. Run vector setup script
python scripts/setup_vectors.py
```

**Test checkpoint:** Did both datasets get indexed? Can you query them?

### Phase 3: Basic API (Day 2-3)
**Goal:** Get a minimal API running that can answer ONE query

```bash
# 1. Start API
uvicorn app.main:app --reload --port 8000

# 2. Test health endpoint
curl http://localhost:8000/health

# 3. Test simple query (non-streaming first)
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is in this dataset?", "user_id": "test"}'
```

**Test checkpoint:** Does it return a response? Check each step in the logs.

### Phase 4: Add Conversation History (Day 3-4)
**Goal:** Store conversations and enable follow-up questions

```bash
# 1. Test creating a conversation
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test"}'

# 2. Test querying with conversation_id
# 3. Test retrieving conversation history
```

**Test checkpoint:** Can you have a 2-3 turn conversation where context is maintained?

### Phase 5: Add Streaming (Day 4-5)
**Goal:** Stream responses in real-time

**Test checkpoint:** Do you see step updates streaming in?

### Phase 6: Optimization & Production Prep (Day 5+)
**Goal:** Add caching, improve prompts, prepare for scale

---

## 🏗️ Architecture Overview

### System Flow
```
User Query
    ↓
[1] Vector Search (PostgreSQL) → Top 3 datasets
    ↓
[2] Load Metadata (Azure Blob) → Full YAML for candidates
    ↓
[3] LLM Selection (Claude) → Pick best dataset
    ↓
[4] SQL Generation (Claude) → Create query
    ↓
[5] Execute (Domo PyDomo) → Get results
    ↓
[6] Generate Response (Claude) → Natural language answer
    ↓
Save to Conversation History (PostgreSQL)
```

### Technology Stack
| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | FastAPI | REST endpoints + streaming |
| Orchestration | LangGraph 1.0 | Agent workflow management |
| LLM | Claude Sonnet 4.5 | Reasoning & SQL generation |
| Embeddings | OpenAI text-embedding-3-small | Vector search |
| Database | PostgreSQL + pgvector | Vectors + conversations + cache |
| Data Source | Domo (PyDomo SDK) | Query execution |
| Metadata | Azure Blob Storage | Dataset YAML files |

### Key Files Reference
```
app/
├── main.py                      # START HERE - FastAPI app entry point
├── database/
│   ├── connection.py            # Database setup
│   └── models.py                # SQLAlchemy models
├── services/
│   ├── vector_service.py        # OpenAI embeddings + pgvector search
│   ├── azure_metadata_service.py # Load YAML from Azure
│   ├── domo_service.py          # PyDomo wrapper
│   ├── llm_service.py           # Claude API calls
│   ├── cache_service.py         # Caching layer
│   └── conversation_service.py  # Conversation storage
├── agent/
│   ├── graph.py                 # LangGraph workflow definition
│   └── nodes.py                 # Individual workflow steps
└── api/
    ├── routes.py                # Query endpoints
    └── streaming.py             # SSE streaming

scripts/
└── setup_vectors.py             # One-time vector indexing
```

### Configuration Summary
```bash
# Test Datasets (2 for v1)
TEST_DATASET_IDS=90339811-aa5c-4e35-835c-714f161ba93e,123783d1-459b-41c8-87ba-6468c8f7edaf

# Master table (contains all available datasets)
DOMO_MASTER_DATASET_ID=8f902882-bc03-4388-9706-d954d46e2912

# Azure metadata location
AZURE_STORAGE_ACCOUNT=assetdomometadata
AZURE_STORAGE_CONTAINER=metadatafiles
```

---

## 🔄 Production Migration Checklist

When moving from local development to production:

### Database
- [ ] Migrate to Azure Database for PostgreSQL
- [ ] Update `DATABASE_URL` in `.env`
- [ ] Enable SSL connections
- [ ] Configure backup and retention
- [ ] Set up monitoring and alerts
- [ ] Increase connection pool sizes

### Vector Indexing
- [ ] Convert `scripts/setup_vectors.py` to admin API endpoint
- [ ] Add authentication to admin endpoints
- [ ] Implement idempotency for re-indexing
- [ ] Set up scheduled re-indexing for metadata updates

### API
- [ ] Deploy to Azure App Service / Container Apps
- [ ] Set up load balancing
- [ ] Configure CORS for production domains
- [ ] Add rate limiting
- [ ] Implement comprehensive logging
- [ ] Set up error alerting

### Security
- [ ] Rotate all API keys
- [ ] Use Azure Key Vault for secrets
- [ ] Add admin authentication
- [ ] Implement user authorization
- [ ] Enable audit logging

---

## 📊 Testing Strategy

### Unit Tests
Test individual services in isolation:
```python
# Test vector service
def test_embedding_generation():
    service = VectorService()
    embedding = service.create_embedding("test query")
    assert len(embedding) == 1536

# Test Azure metadata loading
def test_metadata_load():
    service = AzureMetadataService()
    metadata = service.get_metadata("90339811-aa5c-4e35-835c-714f161ba93e")
    assert metadata is not None
    assert 'table_name' in metadata
```

### Integration Tests
Test full query flow:
```python
# Test complete query execution
def test_full_query():
    response = client.post("/api/v1/query", json={
        "query": "What columns are in the dataset?",
        "user_id": "test_user"
    })
    assert response.status_code == 200
    assert "final_response" in response.json()
```

### Manual Testing Checklist
- [ ] Single query returns correct dataset
- [ ] SQL is generated correctly
- [ ] Data is retrieved from Domo
- [ ] Response makes sense
- [ ] Follow-up questions use conversation context
- [ ] Caching works (second query is faster)
- [ ] Streaming shows progress
- [ ] Conversation history is saved
- [ ] Error handling works gracefully

---

Now continuing with the remaining implementation details...

---

## 12. Cache Service Implementation

```python
# app/services/cache_service.py
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.database.models import CacheEntry
from app.database.connection import SessionLocal

class CacheService:
    """Multi-level caching for SQL results, dataset selections, and responses"""
    
    def __init__(self):
        self.ttl_config = {
            "sql_result": timedelta(hours=1),       # SQL results expire quickly
            "dataset_selection": timedelta(days=1), # Dataset selection is stable
            "sql_generation": timedelta(hours=6),   # SQL generation cached medium-term
            "metadata": timedelta(hours=12)         # Metadata changes occasionally
        }
    
    def generate_cache_key(self, cache_type: str, **kwargs) -> str:
        """
        Generate deterministic cache key from parameters
        
        Args:
            cache_type: Type of cache entry
            **kwargs: Parameters to include in cache key
        
        Returns:
            32-character hash string
        """
        # Sort keys for consistent hashing
        sorted_params = json.dumps(kwargs, sort_keys=True, default=str)
        hash_input = f"{cache_type}:{sorted_params}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]
    
    def get(self, cache_type: str, **kwargs) -> Optional[Any]:
        """
        Get cached value if exists and not expired
        
        Args:
            cache_type: Type of cache entry
            **kwargs: Parameters that define this cache entry
        
        Returns:
            Cached value or None
        """
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        
        db = SessionLocal()
        try:
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key,
                CacheEntry.cache_type == cache_type
            ).first()
            
            if not entry:
                return None
            
            # Check expiration
            if entry.expires_at and entry.expires_at < datetime.now():
                db.delete(entry)
                db.commit()
                return None
            
            # Update hit count and last accessed
            entry.hit_count += 1
            entry.last_accessed = datetime.now()
            db.commit()
            
            return entry.value
            
        except Exception as e:
            print(f"Cache get error: {str(e)}")
            return None
        finally:
            db.close()
    
    def set(self, cache_type: str, value: Any, **kwargs):
        """
        Store value in cache
        
        Args:
            cache_type: Type of cache entry
            value: Value to cache (must be JSON-serializable)
            **kwargs: Parameters that define this cache entry
        """
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        ttl = self.ttl_config.get(cache_type)
        expires_at = datetime.now() + ttl if ttl else None
        
        db = SessionLocal()
        try:
            # Upsert
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key
            ).first()
            
            if entry:
                entry.value = value
                entry.expires_at = expires_at
                entry.last_accessed = datetime.now()
            else:
                entry = CacheEntry(
                    cache_key=cache_key,
                    cache_type=cache_type,
                    value=value,
                    created_at=datetime.now(),
                    expires_at=expires_at,
                    last_accessed=datetime.now()
                )
                db.add(entry)
            
            db.commit()
            
        except Exception as e:
            db.rollback()
            print(f"Cache set error: {str(e)}")
        finally:
            db.close()
    
    def invalidate(self, cache_type: str, **kwargs):
        """Invalidate specific cache entry"""
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        
        db = SessionLocal()
        try:
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key
            ).first()
            
            if entry:
                db.delete(entry)
                db.commit()
                
        except Exception as e:
            db.rollback()
            print(f"Cache invalidate error: {str(e)}")
        finally:
            db.close()
    
    def clear_expired(self):
        """Remove all expired cache entries"""
        db = SessionLocal()
        try:
            deleted = db.query(CacheEntry).filter(
                CacheEntry.expires_at < datetime.now()
            ).delete()
            
            db.commit()
            return deleted
            
        except Exception as e:
            db.rollback()
            print(f"Cache clear error: {str(e)}")
            return 0
        finally:
            db.close()
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        db = SessionLocal()
        try:
            total_entries = db.query(CacheEntry).count()
            
            # Calculate hit rate (if entries have been accessed)
            entries = db.query(CacheEntry).all()
            total_hits = sum(e.hit_count for e in entries)
            
            # Group by cache type
            type_counts = {}
            for entry in entries:
                type_counts[entry.cache_type] = type_counts.get(entry.cache_type, 0) + 1
            
            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "avg_hit_rate": total_hits / total_entries if total_entries > 0 else 0,
                "by_type": type_counts
            }
            
        finally:
            db.close()
```

---

## 13. Conversation Service Implementation

```python
# app/services/conversation_service.py
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
```

---

## 14. FastAPI Main Application

```python
# app/main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv

from app.database.connection import get_db, init_db
from app.api.routes import router as query_router
from app.api.streaming import router as streaming_router
from app.api.conversation_routes import router as conversation_router

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AI Data Agent API",
    description="Intelligent agent for querying Domo datasets using natural language",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔄 PRODUCTION: Restrict to specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and verify connections"""
    print("=" * 60)
    print("AI Data Agent API - Starting Up")
    print("=" * 60)
    
    # Create tables if they don't exist
    print("\n1. Initializing database...")
    init_db()
    print("✓ Database initialized")
    
    # Verify environment variables
    print("\n2. Checking environment configuration...")
    required_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "DOMO_CLIENT_ID",
        "DOMO_SECRET_KEY",
        "AZURE_API_KEY",
        "DATABASE_URL"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"✗ Missing environment variables: {', '.join(missing)}")
    else:
        print("✓ All required environment variables present")
    
    print("\n3. API ready!")
    print(f"   - Environment: {os.getenv('ENVIRONMENT', 'development')}")
    print(f"   - Test Datasets: {os.getenv('TEST_DATASET_IDS', 'Not configured')}")
    print("=" * 60)

# Include routers
app.include_router(query_router, prefix="/api/v1", tags=["query"])
app.include_router(streaming_router, prefix="/api/v1", tags=["streaming"])
app.include_router(conversation_router, prefix="/api/v1", tags=["conversations"])

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "version": "1.0.0"
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AI Data Agent API",
        "docs": "/docs",
        "health": "/health"
    }

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle unexpected exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("ENVIRONMENT") == "development" else "An error occurred"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True
    )
```

---

## 15. API Routes (Query Endpoints)

```python
# app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
import time
import uuid

from app.database.connection import get_db
from app.agent.graph import create_agent_graph
from app.services.conversation_service import ConversationService

router = APIRouter()

# Request/Response Models
class AgentConfig(BaseModel):
    dataset_filter: Optional[List[str]] = None
    model: str = "claude-sonnet-4-5-20250929"
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
    metadata: Dict

# Main query endpoint (non-streaming)
@router.post("/query", response_model=QueryResponse)
async def query_data(request: QueryRequest, db: Session = Depends(get_db)):
    """
    Execute a natural language query against Domo datasets
    
    This endpoint:
    1. Uses vector search to find relevant datasets
    2. Generates SQL using Claude
    3. Executes query in Domo
    4. Returns natural language response
    """
    
    start_time = time.time()
    query_id = f"query_{uuid.uuid4().hex[:16]}"
    
    # Initialize services
    conv_service = ConversationService()
    agent_graph = create_agent_graph()
    
    try:
        # Create or get conversation
        if not request.conversation_id:
            conversation_id = conv_service.create_conversation(
                user_id=request.user_id,
                agent_config=request.agent_config.dict() if request.agent_config else {}
            )
        else:
            conversation_id = request.conversation_id
        
        # Get conversation history for context
        conversation_history = conv_service.format_history_for_llm(conversation_id)
        
        # Build initial state
        initial_state = {
            "query": request.query,
            "user_id": request.user_id,
            "conversation_id": conversation_id,
            "conversation_history": conversation_history,
            "agent_config": request.agent_config.dict() if request.agent_config else {},
            "use_cache": request.agent_config.use_cache if request.agent_config else True,
            "steps": [],
            "cache_hits": {},
            "vector_search_results": [],
            "candidate_metadata": {},
            "selected_dataset_id": "",
            "dataset_selection_reasoning": "",
            "selected_metadata": {},
            "sql_query": "",
            "sql_reasoning": "",
            "retrieved_data": {},
            "final_response": "",
            "error": None,
            "tokens_used": 0,
            "execution_time_ms": 0
        }
        
        # Run agent
        final_state = agent_graph.invoke(initial_state)
        
        total_time = int((time.time() - start_time) * 1000)
        final_state["execution_time_ms"] = total_time
        
        # Save conversation messages
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=request.query
        )
        
        conv_service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_state["final_response"],
            sql_query=final_state.get("sql_query"),
            datasets_used=[final_state.get("selected_dataset_id")],
            steps=final_state.get("steps"),
            execution_time_ms=total_time
        )
        
        # Format response
        return QueryResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            user_id=request.user_id,
            steps=final_state["steps"],
            final_response=final_state["final_response"],
            sql_query=final_state.get("sql_query"),
            data_sample=final_state.get("retrieved_data", {}).get("rows", [])[:10],
            metadata={
                "execution_time_ms": total_time,
                "selected_dataset": final_state.get("selected_dataset_id"),
                "cache_hits": final_state.get("cache_hits", {}),
                "model": request.agent_config.model if request.agent_config else "claude-sonnet-4-5-20250929"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 16. Streaming Endpoint

```python
# app/api/streaming.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
import asyncio
import time
import uuid

from app.database.connection import get_db
from app.agent.graph import create_agent_graph
from app.services.conversation_service import ConversationService
from app.api.routes import QueryRequest

router = APIRouter()

async def event_generator(state: dict, conversation_id: str):
    """
    Generate Server-Sent Events (SSE) for streaming response
    
    Yields events as the agent progresses through each step
    """
    
    conv_service = ConversationService()
    agent_graph = create_agent_graph()
    
    try:
        # Stream agent execution
        final_state = None
        
        for step_update in agent_graph.stream(state):
            # Each iteration is a node completion
            final_state = step_update
            
            # Send step update event
            event_data = {
                "event": "step_update",
                "data": {
                    "step": final_state.get("steps", [])[-1] if final_state.get("steps") else None
                }
            }
            yield f"data: {json.dumps(event_data)}\n\n"
            await asyncio.sleep(0)  # Allow other tasks to run
        
        if not final_state:
            raise Exception("Agent execution failed")
        
        # Save conversation messages
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=state["query"]
        )
        
        conv_service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_state["final_response"],
            sql_query=final_state.get("sql_query"),
            datasets_used=[final_state.get("selected_dataset_id")],
            steps=final_state.get("steps"),
            execution_time_ms=final_state.get("execution_time_ms")
        )
        
        # Send completion event
        completion_event = {
            "event": "complete",
            "data": {
                "conversation_id": conversation_id,
                "final_response": final_state["final_response"],
                "sql_query": final_state.get("sql_query"),
                "selected_dataset": final_state.get("selected_dataset_id"),
                "metadata": {
                    "execution_time_ms": final_state.get("execution_time_ms"),
                    "cache_hits": final_state.get("cache_hits", {})
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
async def query_stream(request: QueryRequest, db: Session = Depends(get_db)):
    """
    Execute query with Server-Sent Events (SSE) streaming
    
    Returns:
        StreamingResponse with events for each agent step
    
    Events emitted:
        - step_update: Agent completed a step
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
        conversation_history = conv_service.format_history_for_llm(conversation_id)
        
        # Build initial state
        initial_state = {
            "query": request.query,
            "user_id": request.user_id,
            "conversation_id": conversation_id,
            "conversation_history": conversation_history,
            "agent_config": request.agent_config.dict() if request.agent_config else {},
            "use_cache": request.agent_config.use_cache if request.agent_config else True,
            "steps": [],
            "cache_hits": {},
            "vector_search_results": [],
            "candidate_metadata": {},
            "selected_dataset_id": "",
            "selected_metadata": {},
            "sql_query": "",
            "retrieved_data": {},
            "final_response": "",
            "execution_time_ms": 0
        }
        
        return StreamingResponse(
            event_generator(initial_state, conversation_id),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 17. Conversation Endpoints

```python
# app/api/conversation_routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.conversation_service import ConversationService

router = APIRouter()

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
async def get_user_conversations(user_id: str):
    """Get all conversations for a user"""
    conv_service = ConversationService()
    conversations = conv_service.get_user_conversations(user_id)
    return {"conversations": conversations}

# Get messages in a conversation
@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    """Get all messages in a conversation"""
    conv_service = ConversationService()
    messages = conv_service.get_conversation_history(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": messages
    }

# Create new conversation
@router.post("/conversations")
async def create_conversation(request: CreateConversationRequest):
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
async def delete_conversation(conversation_id: str):
    """Soft delete a conversation"""
    conv_service = ConversationService()
    conv_service.delete_conversation(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}
```

---

## 18. Testing Examples

```python
# tests/test_services.py
"""
Run tests incrementally as you build each service
"""
import pytest
from app.services.vector_service import VectorService
from app.services.azure_metadata_service import AzureMetadataService
from app.services.domo_service import DomoService
from app.database.connection import SessionLocal

def test_vector_embedding():
    """Test embedding generation"""
    service = VectorService()
    embedding = service.create_embedding("test query about revenue")
    
    assert len(embedding) == 1536
    assert all(isinstance(x, float) for x in embedding)
    print("✓ Embedding generation works")

def test_azure_metadata_load():
    """Test loading metadata from Azure"""
    service = AzureMetadataService()
    metadata = service.get_metadata("90339811-aa5c-4e35-835c-714f161ba93e")
    
    assert metadata is not None
    assert 'table_name' in metadata
    assert 'columns' in metadata
    print(f"✓ Loaded metadata for {metadata.get('table_name')}")

def test_domo_connection():
    """Test Domo connection"""
    service = DomoService()
    datasets = service.get_available_datasets()
    
    assert len(datasets) > 0
    print(f"✓ Connected to Domo, found {len(datasets)} datasets")

def test_vector_search():
    """Test vector search"""
    db = SessionLocal()
    service = VectorService()
    
    results = service.search_datasets(db, "revenue by property", top_k=2)
    
    assert len(results) > 0
    print(f"✓ Vector search returned {len(results)} results")
    for r in results:
        print(f"  - {r['table_name']} (similarity: {r['similarity']:.3f})")
    
    db.close()

if __name__ == "__main__":
    print("\nRunning service tests...\n")
    test_vector_embedding()
    test_azure_metadata_load()
    test_domo_connection()
    test_vector_search()
    print("\n✓ All tests passed!")
```

```bash
# Manual API testing
# Save these in a file like test_api.sh

# 1. Health check
curl http://localhost:8000/health

# 2. Simple query
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What columns are in the dataset?",
    "user_id": "ariel_test"
  }'

# 3. Create conversation
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "ariel_test",
    "title": "Test Conversation"
  }'

# 4. Query with conversation (use conversation_id from step 3)
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me the first 5 rows",
    "user_id": "ariel_test",
    "conversation_id": "conv_abc123"
  }'

# 5. Get conversation history
curl http://localhost:8000/api/v1/conversations/conv_abc123/messages

# 6. Streaming query (requires SSE client)
curl -N -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the total revenue?",
    "user_id": "ariel_test"
  }'
```

---

## 19. Final Checklist & Next Steps

### ✅ Pre-Implementation Checklist
- [ ] PostgreSQL running in Docker
- [ ] All environment variables in `.env`
- [ ] Test dataset IDs confirmed
- [ ] Can connect to Azure Blob Storage
- [ ] Can connect to Domo with PyDomo

### 🏗️ Implementation Order

**Phase 1: Foundation (Day 1)**
1. Set up database (docker-compose up)
2. Test database connection
3. Create vector service
4. Test embedding generation

**Phase 2: Data Loading (Day 1-2)**
5. Create Azure metadata service
6. Create Domo service
7. Run vector setup script
8. Verify 2 datasets are indexed

**TEST CHECKPOINT:** Can you query vectors and get back dataset IDs?

**Phase 3: Basic Agent (Day 2-3)**
9. Create LLM service
10. Create agent nodes (start with just vector search + metadata load)
11. Create LangGraph workflow
12. Test basic flow without SQL execution

**TEST CHECKPOINT:** Does agent select the right dataset?

**Phase 4: SQL Execution (Day 3)**
13. Add SQL generation node
14. Add Domo execution node
15. Add response generation node
16. Test full end-to-end query

**TEST CHECKPOINT:** Can you get a complete answer to a simple query?

**Phase 5: API & Conversation (Day 3-4)**
17. Create FastAPI app
18. Add query endpoint
19. Add conversation service
20. Test with curl/Postman

**TEST CHECKPOINT:** Can you have a 2-turn conversation?

**Phase 6: Streaming & Polish (Day 4-5)**
21. Add streaming endpoint
22. Add cache service
23. Test streaming
24. Optimize prompts

**TEST CHECKPOINT:** Does streaming work? Is caching speeding things up?

---

## 🚨 Common Issues & Troubleshooting

**Database connection fails:**
```bash
# Check if container is running
docker ps

# Check logs
docker logs ai-agent-postgres

# Test connection
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent
```

**Vector setup fails:**
```bash
# Check if pgvector extension is enabled
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent -c "SELECT * FROM pg_extension WHERE extname = 'vector';"

# If not, enable it
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent -c "CREATE EXTENSION vector;"
```

**Azure connection fails:**
- Verify `AZURE_API_KEY` in `.env`
- Test with Azure Storage Explorer
- Check container name is correct

**Domo connection fails:**
- Verify `DOMO_CLIENT_ID` and `DOMO_SECRET_KEY`
- Test with PyDomo directly in Python REPL
- Check API permissions

**LLM calls fail:**
- Verify `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
- Check API quotas/limits
- Test with simple curl to API endpoints

---

This completes the enhanced architecture plan v3! 🎉

**Remember:** Build incrementally, test at each phase, and adjust as you learn. This is a guide, not a strict specification.