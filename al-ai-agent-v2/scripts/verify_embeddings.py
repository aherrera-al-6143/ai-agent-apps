#!/usr/bin/env python3
"""
Script to verify that embeddings contain comprehensive column information
from YAML files (examples, category, definitions, etc.)
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import SessionLocal
from app.services.vector_service import VectorService
from app.services.azure_metadata_service import AzureMetadataService
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()


def verify_embeddings():
    """Verify that embeddings contain comprehensive column information"""
    print("=" * 60)
    print("EMBEDDING VERIFICATION")
    print("=" * 60)
    print()
    
    # Initialize services
    vector_service = VectorService()
    azure_service = AzureMetadataService()
    db = SessionLocal()
    
    try:
        # Get dataset IDs
        test_dataset_ids = os.getenv("TEST_DATASET_IDS", "").split(",")
        test_dataset_ids = [d.strip() for d in test_dataset_ids if d.strip()]
        
        if not test_dataset_ids:
            print("❌ ERROR: TEST_DATASET_IDS not set")
            return
        
        print(f"Checking {len(test_dataset_ids)} datasets...")
        print()
        
        for dataset_id in test_dataset_ids:
            print(f"Dataset: {dataset_id}")
            print("-" * 60)
            
            # Get metadata from database
            result = db.execute(
                text("SELECT dataset_id, table_name, columns FROM dataset_metadata WHERE dataset_id = :did"),
                {"did": dataset_id}
            )
            row = result.fetchone()
            
            if not row:
                print(f"  ❌ Dataset not found in database")
                continue
            
            # Get fresh metadata from Azure
            print(f"  Loading fresh metadata from Azure...")
            azure_metadata = azure_service.get_metadata(dataset_id)
            
            if not azure_metadata:
                print(f"  ❌ Metadata not found in Azure")
                continue
            
            # Compare columns
            db_columns = row.columns if isinstance(row.columns, list) else []
            azure_columns = azure_metadata.get('columns', [])
            
            print(f"  Database columns: {len(db_columns)}")
            print(f"  Azure YAML columns: {len(azure_columns)}")
            print()
            
            # Check a specific column (record_state) for comprehensive data
            print("  Checking record_state column for comprehensive metadata:")
            print()
            
            db_state_col = next((c for c in db_columns if c.get('name') == 'record_state'), None)
            azure_state_col = next((c for c in azure_columns if c.get('name') == 'record_state'), None)
            
            if not db_state_col:
                print("    ❌ record_state not found in database columns")
            else:
                print("    Database record_state column has:")
                print(f"      - name: {db_state_col.get('name', 'MISSING')}")
                print(f"      - type: {db_state_col.get('type', 'MISSING')}")
                print(f"      - category: {db_state_col.get('category', 'MISSING')}")
                print(f"      - description: {'✓' if db_state_col.get('description') else '✗'}")
                print(f"      - business_meaning: {'✓' if db_state_col.get('business_meaning') else '✗'}")
                print(f"      - examples: {db_state_col.get('examples', 'MISSING')}")
                print(f"      - definitions: {'✓' if db_state_col.get('definitions') else '✗'}")
                print(f"      - business_rules: {'✓' if db_state_col.get('business_rules') else '✗'}")
                print(f"      - data_quality_notes: {'✓' if db_state_col.get('data_quality_notes') else '✗'}")
            
            print()
            
            if not azure_state_col:
                print("    ❌ record_state not found in Azure YAML")
            else:
                print("    Azure YAML record_state column has:")
                print(f"      - name: {azure_state_col.get('name', 'MISSING')}")
                print(f"      - type: {azure_state_col.get('type', 'MISSING')}")
                print(f"      - category: {azure_state_col.get('category', 'MISSING')}")
                print(f"      - description: {'✓' if azure_state_col.get('description') else '✗'}")
                print(f"      - business_meaning: {'✓' if azure_state_col.get('business_meaning') else '✗'}")
                print(f"      - examples: {azure_state_col.get('examples', 'MISSING')}")
                print(f"      - definitions: {'✓' if azure_state_col.get('definitions') else '✗'}")
                print(f"      - business_rules: {'✓' if azure_state_col.get('business_rules') else '✗'}")
                print(f"      - data_quality_notes: {'✓' if azure_state_col.get('data_quality_notes') else '✗'}")
            
            print()
            
            # Test embedding text generation
            print("  Testing embedding text generation:")
            print()
            
            # Generate embedding text using the current method
            embedding_text = vector_service._build_embedding_text(
                table_name=row.table_name,
                description=azure_metadata.get('description', ''),
                columns=db_columns[:5]  # Just check first 5 columns
            )
            
            # Check if examples are in the embedding text
            if db_state_col and db_state_col.get('examples'):
                examples_str = ', '.join(str(ex) for ex in db_state_col.get('examples', [])[:3])
                if examples_str in embedding_text or any(str(ex) in embedding_text for ex in db_state_col.get('examples', [])[:3]):
                    print(f"    ✓ Examples found in embedding text (checked for: {examples_str})")
                else:
                    print(f"    ✗ Examples NOT found in embedding text")
                    print(f"      Looking for: {examples_str}")
                    print(f"      Embedding text preview (first 500 chars):")
                    print(f"      {embedding_text[:500]}...")
            
            # Check if category is in embedding text
            if db_state_col and db_state_col.get('category'):
                if db_state_col.get('category') in embedding_text:
                    print(f"    ✓ Category found in embedding text: {db_state_col.get('category')}")
                else:
                    print(f"    ✗ Category NOT found in embedding text")
            
            print()
            print("=" * 60)
            print()
    
    except Exception as e:
        print(f"\n✗ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    verify_embeddings()




