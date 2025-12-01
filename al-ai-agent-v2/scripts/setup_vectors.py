"""
One-time script to index test datasets into the vector systems.
Loads datasets from Domo master table, generates embeddings, stores legacy dataset
embeddings in PostgreSQL, and upserts column-level embeddings into Qdrant.
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import SessionLocal, init_db
from app.services.vector_service import VectorService
from app.services.azure_metadata_service import AzureMetadataService
from app.services.qdrant_service import QdrantService
from pydomo import Domo
from dotenv import load_dotenv

load_dotenv()


def get_domo_client():
    """Initialize Domo client"""
    client_id = os.getenv("DOMO_CLIENT_ID")
    secret_key = os.getenv("DOMO_SECRET_KEY")
    
    if not client_id or not secret_key:
        raise ValueError("DOMO_CLIENT_ID and DOMO_SECRET_KEY must be set")
    
    return Domo(client_id, secret_key, api_host='api.domo.com')


def load_datasets_from_domo(domo_client, master_dataset_id: str):
    """
    Load dataset information from Domo master table
    
    Args:
        domo_client: PyDomo client instance
        master_dataset_id: ID of the master dataset containing all datasets
    
    Returns:
        List of dataset dictionaries
    """
    try:
        # Query master dataset
        dataset = domo_client.datasets.get(master_dataset_id)
        data = domo_client.datasets.data(master_dataset_id)
        
        datasets = []
        for row in data:
            datasets.append({
                'dataset_id': row.get('dataset_id') or row.get('id'),
                'name': row.get('name') or row.get('dataset_name'),
                'description': row.get('description') or ''
            })
        
        return datasets
        
    except Exception as e:
        print(f"Error loading datasets from Domo: {e}")
        return []


def index_datasets():
    """Main function to index datasets"""
    print("=" * 60)
    print("Vector Indexing Script")
    print("=" * 60)
    
    # Initialize services
    print("\n1. Initializing services...")
    vector_service = VectorService()
    azure_service = AzureMetadataService()
    qdrant_service = QdrantService()
    db = SessionLocal()
    
    try:
        # Initialize database
        print("\n2. Initializing database...")
        init_db()
        
        # Get test dataset IDs from environment
        test_dataset_ids = os.getenv("TEST_DATASET_IDS", "").split(",")
        test_dataset_ids = [d.strip() for d in test_dataset_ids if d.strip()]
        
        if not test_dataset_ids:
            print("No TEST_DATASET_IDS configured. Loading from Domo master table...")
            master_dataset_id = os.getenv("DOMO_MASTER_DATASET_ID")
            if not master_dataset_id:
                raise ValueError("Either TEST_DATASET_IDS or DOMO_MASTER_DATASET_ID must be set")
            
            domo_client = get_domo_client()
            datasets = load_datasets_from_domo(domo_client, master_dataset_id)
        else:
            # Use test dataset IDs directly
            print(f"Using TEST_DATASET_IDS from environment: {test_dataset_ids}")
            datasets = [{'dataset_id': did, 'name': '', 'description': ''} for did in test_dataset_ids]
        
        print(f"\n3. Indexing {len(datasets)} datasets...")
        if len(datasets) == 0:
            print("⚠️  WARNING: No datasets to index!")
            print("   Make sure TEST_DATASET_IDS is set in your .env file")
            print("   Example: TEST_DATASET_IDS=6008b950-3ac3-4f4a-bbc6-66f4bd2625a5,90339811-aa5c-4e35-835c-714f161ba93e")
        
        indexed_count = 0
        for dataset_info in datasets:
            dataset_id = dataset_info['dataset_id']
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
            dataset_name = metadata.get('dataset_name') or metadata.get('table_name') or dataset_info.get('name', dataset_id)
            table_name = metadata.get('table_name', dataset_name)
            description = metadata.get('description', dataset_info.get('description', ''))
            columns = metadata.get('columns', [])
            
            # Store in database and Qdrant
            try:
                print(f"    Generating legacy dataset embedding with {len(columns)} columns...")
                vector_service.store_dataset_embedding(
                    db=db,
                    dataset_id=dataset_id,
                    table_name=table_name,
                    description=description,
                    columns=columns
                )
                print("    ✓ Legacy dataset embedding updated")

                print("    Generating column-level embeddings for Qdrant...")
                upserted = vector_service.store_column_embeddings(
                    dataset_id=dataset_id,
                    dataset_name=dataset_name,
                    table_name=table_name,
                    dataset_description=description,
                    columns=columns,
                    qdrant_service=qdrant_service
                )
                print(f"    ✓ Upserted {upserted} columns into Qdrant")
                indexed_count += 1
                print(f"    ✓ Indexed: {table_name}")
            except Exception as e:
                print(f"    ✗ Error indexing {dataset_id}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'=' * 60}")
        print(f"✓ Successfully indexed {indexed_count} out of {len(datasets)} datasets")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Error during indexing: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    index_datasets()


