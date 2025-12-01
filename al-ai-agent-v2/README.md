# AI Data Agent API v2

FastAPI-based intelligent agent for querying Domo datasets using natural language.

## Features

- **Vector Search**: Column-level retrieval using Qdrant (legacy pgvector support)
- **LLM-Powered**: Unified OpenRouter integration for access to top models (Gemini, Claude, GPT-4)
- **Model Switching**: Per-request model selection with default fallback
- **Conversation History**: Maintain context across multiple queries
- **Caching**: Multi-level caching for improved performance
- **Streaming**: Real-time response streaming via Server-Sent Events (SSE)
- **Domo Integration**: Execute SQL queries directly in Domo datasets

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- Python 3.9+
- Environment variables configured (see `.env.example`)

### 2. Start Infrastructure

```bash
# Start PostgreSQL with pgvector and Qdrant
docker-compose up -d

# Verify services are running
docker ps

# Optional: Check Qdrant health
curl http://localhost:6333/healthz
```

### 3. Install Dependencies

```bash
# Create virtual environment (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
# Edit .env with your actual keys
```

Required environment variables:
- `DATABASE_URL`: PostgreSQL connection string
- `OPEN_ROUTER_KEY`: OpenRouter API key
- `DEFAULT_MODEL_VERSION`: Default model ID (e.g., `google/gemini-2.5-flash`)
- `OPEN_ROUTER_BASE_URL`: Optional custom base URL (default `https://openrouter.ai/api/v1`)
- `DOMO_CLIENT_ID` and `DOMO_SECRET_KEY`: Domo credentials
- `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONTAINER`, `AZURE_API_KEY`: Azure Blob Storage
- `QDRANT_URL`: Qdrant endpoint (default `http://localhost:6333`)
- `QDRANT_API_KEY`: Required when using Qdrant Cloud (omit for local Docker)
- `QDRANT_COLLECTION_NAME`: Target collection for column embeddings (default `column_embeddings`)
- `QDRANT_USE_GRPC`: Set to `true` to use the gRPC endpoint (optional)
- `TEST_DATASET_IDS`: Comma-separated test dataset IDs
- `DOMO_MASTER_DATASET_ID`: Master dataset ID for indexing

### 5. Initialize Database

```bash
# Create tables and enable pgvector extension
python scripts/init_db.py
```

### 6. Index Datasets

```bash
# Index test datasets into vector database
python scripts/setup_vectors.py

# (New) Generate column-level embeddings in Qdrant
python scripts/migrate_to_column_embeddings.py
```

### 7. Start API

```bash
# Start the FastAPI server
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

## API Usage

### Query Endpoint (Non-Streaming)

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What columns are in the dataset?",
    "user_id": "test_user"
  }'
```

### Streaming Query

```bash
curl -N -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the total revenue?",
    "user_id": "test_user"
  }'
```

### Conversation Management

```bash
# Create conversation
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user", "title": "My Conversation"}'

# Get conversation history
curl http://localhost:8000/api/v1/conversations/{conversation_id}/messages

# Get all user conversations
curl http://localhost:8000/api/v1/conversations/{user_id}
```

## Project Structure

```
al-ai-agent-v2/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── database/               # Database models and connection
│   ├── services/               # Business logic services
│   ├── agent/                 # LangGraph workflow
│   └── api/                   # API routes
├── scripts/                    # Utility scripts
├── tests/                      # Test files
├── docker-compose.yml          # PostgreSQL setup
└── requirements.txt            # Dependencies
```

## Architecture

The agent workflow:

1. **Column Search**: Use Qdrant to retrieve the most relevant columns across datasets
2. **Generate SQL**: LLM generates SQL using only the returned column metadata
3. **Execute & Respond**: Run SQL in Domo, summarize the results, and return the final response

## Testing

```bash
# Run service tests
python tests/test_services.py

# Run API tests
python tests/test_api.py
```

## Troubleshooting

### Database Connection Issues

```bash
# Check if container is running
docker ps

# Check logs
docker logs ai-agent-postgres

# Test connection
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent
```

### Vector Extension Not Enabled

```bash
# Enable pgvector extension manually
psql postgresql://aiagent:dev_password_123@localhost:5432/ai_agent -c "CREATE EXTENSION vector;"
```

## License

Internal use only.
