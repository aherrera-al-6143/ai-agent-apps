"""
Database initialization script
Creates tables and enables pgvector extension
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import init_db, engine
from sqlalchemy import text

def main():
    """Initialize database"""
    print("Initializing database...")
    
    try:
        # Enable pgvector extension
        with engine.connect() as conn:
            result = conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("✓ pgvector extension enabled")
        
        # Create all tables
        init_db()
        print("✓ Database initialization complete!")
        
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()





