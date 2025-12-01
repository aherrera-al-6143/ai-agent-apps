"""
FastAPI main application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from dotenv import load_dotenv

from app.database.connection import init_db
from app.api.routes import router as query_router
from app.api.streaming import router as streaming_router
from app.api.conversation_routes import router as conversation_router
from app.agent.graph import initialize_checkpointer

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AI Data Agent API",
    description="Intelligent agent for querying Domo datasets using natural language",
    version="1.0.0"
)

# CORS configuration
cors_origins = os.getenv("CORS_ORIGINS", "*")
if cors_origins == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [origin.strip() for origin in cors_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
    
    # Initialize LangGraph checkpointer
    print("\n2. Initializing LangGraph checkpointer...")
    initialize_checkpointer()
    print("✓ Checkpointer initialized")
    
    # Verify environment variables
    print("\n3. Checking environment configuration...")
    required_vars = [
        "OPEN_ROUTER_KEY",  # Required for OpenRouter
        "DOMO_CLIENT_ID",
        "DOMO_SECRET_KEY",
        "AZURE_API_KEY",
        "DATABASE_URL"
    ]
    
    # Check for DEFAULT_MODEL_VERSION
    if not os.getenv("DEFAULT_MODEL_VERSION"):
        print("⚠️  DEFAULT_MODEL_VERSION is not set. Using default: google/gemini-2.5-flash")
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"⚠️  Missing environment variables: {', '.join(missing)}")
        print("   App may not function correctly without these.")
    else:
        print("✓ All required environment variables present")
    
    print("\n4. API ready!")
    print(f"   - Environment: {os.getenv('ENVIRONMENT', 'development')}")
    print(f"   - Test Datasets: {os.getenv('TEST_DATASET_IDS', 'Not configured')}")
    print(f"   - Default Model: {os.getenv('DEFAULT_MODEL_VERSION', 'google/gemini-2.5-flash')}")
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
    # In production, reload should be False
    is_production = os.getenv("ENVIRONMENT", "development") == "production"
    # Azure App Service sets PORT environment variable
    port = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=port,
        reload=not is_production
    )
