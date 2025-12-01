#!/usr/bin/env python3
"""
Script to reindex datasets in the production database and Qdrant.
Updates legacy dataset-level embeddings plus the new column-level embeddings.

IMPORTANT: This script connects to the PRODUCTION database/Qdrant cluster.
Make sure your .env file has the production settings configured before running.
"""
import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from app.database.connection import SessionLocal, init_db
from app.services.azure_metadata_service import AzureMetadataService
from app.services.qdrant_service import QdrantService
from app.services.vector_service import VectorService

load_dotenv()


def reindex_production_datasets(auto_confirm: bool = False):
    """
    Reindex datasets in production database with new comprehensive column formatting.
    This will update embeddings to include examples, category, definitions, etc.
    """
    print("=" * 60)
    print("PRODUCTION DATASET REINDEXING")
    print("=" * 60)
    print()
    
    # Warn user about production database
    database_url = os.getenv("DATABASE_URL", "")
    if "localhost" in database_url or "127.0.0.1" in database_url:
        print("⚠️  WARNING: DATABASE_URL appears to point to localhost!")
        print("   This script is for PRODUCTION reindexing.")
        print("   Make sure your .env file has the production DATABASE_URL.")
        if not auto_confirm:
            response = input("   Continue anyway? (yes/no): ")
            if response.lower() != "yes":
                print("   Aborted.")
                return
        else:
            print("   --yes flag provided, continuing despite localhost database URL warning.")
    
    print(f"Database URL: {database_url[:50]}..." if len(database_url) > 50 else f"Database URL: {database_url}")
    print()
    
    # Initialize services
    print("1. Initializing services...")
    vector_service = VectorService()
    azure_service = AzureMetadataService()
    qdrant_service = QdrantService()
    db = SessionLocal()
    
    try:
        # Initialize database (ensures tables exist)
        print("\n2. Initializing database...")
        init_db()
        
        # Get dataset IDs from environment
        test_dataset_ids = os.getenv("TEST_DATASET_IDS", "").split(",")
        test_dataset_ids = [d.strip() for d in test_dataset_ids if d.strip()]
        
        if not test_dataset_ids:
            print("❌ ERROR: TEST_DATASET_IDS not set in environment")
            print("   Please set TEST_DATASET_IDS in your .env file")
            print("   Example: TEST_DATASET_IDS=90339811-aa5c-4e35-835c-714f161ba93e,123783d1-459b-41c8-87ba-6468c8f7edaf")
            return
        
        print(f"\n3. Reindexing {len(test_dataset_ids)} datasets in PRODUCTION...")
        print(f"   Dataset IDs: {test_dataset_ids}")
        print()
        
        # Confirm before proceeding
        print("⚠️  This will UPDATE embeddings in the PRODUCTION database.")
        if not auto_confirm:
            response = input("   Continue? (yes/no): ")
            if response.lower() != "yes":
                print("   Aborted.")
                return
        else:
            print("   --yes flag provided, skipping confirmation prompt.")
        
        print()
        indexed_count = 0
        for dataset_id in test_dataset_ids:
            print(f"\n  Processing: {dataset_id}")
            
            # Load metadata from Azure
            print(f"    Loading metadata from Azure for {dataset_id}...")
            metadata = azure_service.get_metadata(dataset_id)
            
            if not metadata:
                print(f"    ⚠️  No metadata found in Azure for {dataset_id}, skipping...")
                print(f"    Check that the YAML file exists: {dataset_id}.yaml")
                continue
            
            print(f"    ✓ Metadata loaded: {metadata.get('table_name', 'N/A')}")
            
            # Extract information
            dataset_name = metadata.get('dataset_name') or metadata.get('table_name') or dataset_id
            table_name = metadata.get('table_name', dataset_name)
            description = metadata.get('description', '')
            columns = metadata.get('columns', [])
            
            # Store in database with embedding (will use new comprehensive formatting)
            try:
                print(f"    Generating NEW embedding with {len(columns)} columns...")
                print(f"    (Includes: examples, category, definitions, business_rules, etc.)")
                vector_service.store_dataset_embedding(
                    db=db,
                    dataset_id=dataset_id,
                    table_name=table_name,
                    description=description,
                    columns=columns
                )
                print("    ✓ Legacy dataset embedding updated")

                print("    Refreshing column-level embeddings in Qdrant...")
                qdrant_service.delete_by_dataset(dataset_id)
                upserted = vector_service.store_column_embeddings(
                    dataset_id=dataset_id,
                    dataset_name=dataset_name,
                    table_name=table_name,
                    dataset_description=description,
                    columns=columns,
                    qdrant_service=qdrant_service,
                    business_rules=metadata.get('business_rules', ''),
                    common_queries=metadata.get('common_queries', '')
                )
                indexed_count += 1
                print(f"    ✓ Upserted {upserted} columns into Qdrant")
            except Exception as e:
                print(f"    ✗ Error reindexing {dataset_id}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'=' * 60}")
        print(f"✓ Successfully reindexed {indexed_count} out of {len(test_dataset_ids)} datasets")
        print("=" * 60)
        print()
        print("✅ Production embeddings updated with comprehensive column formatting!")
        print("   The API will now use the new embeddings on the next query.")
        print("   No API redeployment needed - changes are in the database.")
        
    except Exception as e:
        print(f"\n✗ Error during reindexing: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reindex production datasets and refresh Qdrant column embeddings.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Automatically answer yes to all prompts (non-interactive)",
    )
    args = parser.parse_args()
    reindex_production_datasets(auto_confirm=args.yes)

