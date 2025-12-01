#!/usr/bin/env python3
"""
Diagnostic script to check vector indexing setup
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from app.database.connection import SessionLocal
from app.services.azure_metadata_service import AzureMetadataService
from sqlalchemy import text

load_dotenv()

def check_environment():
    """Check if required environment variables are set"""
    print("=" * 60)
    print("Environment Check")
    print("=" * 60)
    
    test_dataset_ids = os.getenv("TEST_DATASET_IDS", "")
    if test_dataset_ids:
        ids = [d.strip() for d in test_dataset_ids.split(",") if d.strip()]
        print(f"✓ TEST_DATASET_IDS is set: {ids}")
    else:
        print("✗ TEST_DATASET_IDS is NOT set")
        print("  Add to .env: TEST_DATASET_IDS=6008b950-3ac3-4f4a-bbc6-66f4bd2625a5,90339811-aa5c-4e35-835c-714f161ba93e")
    
    required_vars = [
        "AZURE_STORAGE_ACCOUNT",
        "AZURE_API_KEY", 
        "AZURE_STORAGE_CONTAINER",
        "OPENAI_API_KEY"
    ]
    
    for var in required_vars:
        if os.getenv(var):
            print(f"✓ {var} is set")
        else:
            print(f"✗ {var} is NOT set")
    
    print()

def check_azure_metadata():
    """Check if metadata files exist in Azure"""
    print("=" * 60)
    print("Azure Metadata Check")
    print("=" * 60)
    
    test_dataset_ids = os.getenv("TEST_DATASET_IDS", "")
    if not test_dataset_ids:
        print("⚠️  TEST_DATASET_IDS not set, skipping Azure check")
        return
    
    ids = [d.strip() for d in test_dataset_ids.split(",") if d.strip()]
    
    try:
        azure_service = AzureMetadataService()
        
        for dataset_id in ids:
            print(f"\nChecking {dataset_id}...")
            metadata = azure_service.get_metadata(dataset_id)
            if metadata:
                table_name = metadata.get('table_name', 'N/A')
                column_count = len(metadata.get('columns', []))
                print(f"  ✓ Found: {table_name} ({column_count} columns)")
            else:
                print(f"  ✗ Not found in Azure")
    except Exception as e:
        print(f"  ✗ Error checking Azure: {e}")
    
    print()

def check_database():
    """Check what's in the database"""
    print("=" * 60)
    print("Database Check")
    print("=" * 60)
    
    test_dataset_ids = os.getenv("TEST_DATASET_IDS", "")
    if not test_dataset_ids:
        print("⚠️  TEST_DATASET_IDS not set, checking all datasets")
        ids = None
    else:
        ids = [d.strip() for d in test_dataset_ids.split(",") if d.strip()]
    
    try:
        db = SessionLocal()
        
        if ids:
            # Check specific datasets
            placeholders = ",".join([f"'{id}'" for id in ids])
            sql = text(f"""
                SELECT dataset_id, table_name, 
                       LEFT(description, 50) as desc_preview,
                       CASE WHEN embedding IS NOT NULL THEN 'Yes' ELSE 'No' END as has_embedding
                FROM dataset_metadata 
                WHERE dataset_id IN ({placeholders})
            """)
        else:
            # Check all datasets
            sql = text("""
                SELECT dataset_id, table_name, 
                       LEFT(description, 50) as desc_preview,
                       CASE WHEN embedding IS NOT NULL THEN 'Yes' ELSE 'No' END as has_embedding
                FROM dataset_metadata
                ORDER BY created_at DESC
                LIMIT 10
            """)
        
        result = db.execute(sql)
        rows = result.fetchall()
        
        if rows:
            print(f"Found {len(rows)} dataset(s):")
            for row in rows:
                print(f"  - {row.dataset_id}: {row.table_name}")
                print(f"    Description: {row.desc_preview}...")
                print(f"    Has embedding: {row.has_embedding}")
        else:
            print("✗ No datasets found in database")
            if ids:
                print(f"  Expected datasets: {ids}")
                print("  Run: python scripts/setup_vectors.py")
        
        db.close()
    except Exception as e:
        print(f"✗ Error checking database: {e}")
        import traceback
        traceback.print_exc()
    
    print()

if __name__ == "__main__":
    check_environment()
    check_azure_metadata()
    check_database()
    
    print("=" * 60)
    print("Diagnostic Complete")
    print("=" * 60)




