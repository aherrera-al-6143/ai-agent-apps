"""
Database connection and session management
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://aiagent:dev_password_123@localhost:5432/ai_agent")

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database: create tables and enable pgvector extension
    """
    # Enable pgvector extension
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")





