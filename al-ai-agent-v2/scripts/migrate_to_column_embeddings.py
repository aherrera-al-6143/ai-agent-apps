"""
Migration script for converting dataset-level embeddings to column-level Qdrant embeddings.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import SessionLocal, init_db
from app.database.models import DatasetMetadata
from app.services.azure_metadata_service import AzureMetadataService
from app.services.vector_service import VectorService
from app.services.qdrant_service import QdrantService

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migrate existing datasets to column-level embeddings in Qdrant."
    )
    parser.add_argument(
        "--dataset-ids",
        type=str,
        help="Comma-separated list of dataset IDs to migrate. Defaults to all datasets in the database."
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Do not delete existing Qdrant entries before re-indexing."
    )
    return parser.parse_args()


def fetch_dataset_ids(session, cli_ids: Optional[str]) -> List[str]:
    if cli_ids:
        return [dataset_id.strip() for dataset_id in cli_ids.split(",") if dataset_id.strip()]
    
    records = session.query(DatasetMetadata.dataset_id).all()
    return [record[0] for record in records if record[0]]


def main():
    args = parse_args()
    init_db()

    session = SessionLocal()
    vector_service = VectorService()
    azure_service = AzureMetadataService()
    qdrant_service = QdrantService()

    dataset_ids = fetch_dataset_ids(session, args.dataset_ids)
    if not dataset_ids:
        print("No datasets found to migrate.")
        return

    print(f"Found {len(dataset_ids)} datasets to migrate.")

    for dataset_id in dataset_ids:
        print("=" * 80)
        print(f"Processing dataset: {dataset_id}")

        metadata = azure_service.get_metadata(dataset_id)
        if not metadata:
            db_record = session.query(DatasetMetadata).filter(
                DatasetMetadata.dataset_id == dataset_id
            ).first()
            if db_record:
                metadata = {
                    "table_name": db_record.table_name,
                    "description": db_record.description,
                    "columns": db_record.columns or []
                }

        if not metadata:
            print(f"⚠️  No metadata available for {dataset_id}. Skipping.")
            continue

        columns = metadata.get("columns", [])
        if not columns:
            print(f"⚠️  Metadata for {dataset_id} does not contain columns. Skipping.")
            continue

        dataset_name = metadata.get("dataset_name") or metadata.get("table_name") or dataset_id
        table_name = metadata.get("table_name") or dataset_name

        if not args.skip_delete:
            qdrant_service.delete_by_dataset(dataset_id)

        try:
            count = vector_service.store_column_embeddings(
                dataset_id=dataset_id,
                dataset_name=dataset_name,
                table_name=table_name,
                dataset_description=metadata.get("description", ""),
                columns=columns,
                qdrant_service=qdrant_service
            )
            print(f"✓ Indexed {count} columns for dataset {dataset_id}")
        except Exception as exc:
            print(f"✗ Failed to index dataset {dataset_id}: {exc}")

    session.close()


if __name__ == "__main__":
    main()
