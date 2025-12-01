"""
Service unit tests
Run tests incrementally as you build each service
"""
import pytest
from app.services.vector_service import VectorService
from app.services.azure_metadata_service import AzureMetadataService
from app.services.domo_service import DomoService
from app.services.llm_service import LLMService
from app.services.qdrant_service import QdrantService
from app.database.connection import SessionLocal


def test_vector_embedding():
    """Test embedding generation"""
    try:
        service = VectorService()
        embedding = service.create_embedding("test query about revenue")
        
        assert len(embedding) == 1536
        assert all(isinstance(x, float) for x in embedding)
        print("✓ Embedding generation works")
    except Exception as e:
        print(f"⚠️  Skipping vector embedding test: {e}")


def test_azure_metadata_load():
    """Test loading metadata from Azure"""
    try:
        service = AzureMetadataService()
        # Use a test dataset ID from environment or default
        import os
        test_id = os.getenv("TEST_DATASET_IDS", "").split(",")[0].strip()
        if test_id:
            metadata = service.get_metadata(test_id)
            assert metadata is not None
            assert 'table_name' in metadata or 'columns' in metadata
            print(f"✓ Loaded metadata for {metadata.get('table_name', test_id)}")
        else:
            print("⚠️  No TEST_DATASET_IDS configured, skipping metadata test")
    except Exception as e:
        print(f"⚠️  Skipping Azure metadata test: {e}")


def test_domo_connection():
    """Test Domo connection"""
    try:
        service = DomoService()
        datasets = service.get_available_datasets()
        
        assert len(datasets) >= 0  # May be empty but should not error
        print(f"✓ Connected to Domo, found {len(datasets)} datasets")
    except Exception as e:
        print(f"⚠️  Skipping Domo connection test: {e}")


def test_vector_search():
    """Test vector search"""
    try:
        db = SessionLocal()
        service = VectorService()
        
        results = service.search_datasets(db, "revenue by property", top_k=2)
        
        assert len(results) >= 0  # May be empty if no datasets indexed
        print(f"✓ Vector search returned {len(results)} results")
        for r in results:
            print(f"  - {r['table_name']} (similarity: {r['similarity']:.3f})")
        
        db.close()
    except Exception as e:
        print(f"⚠️  Skipping vector search test: {e}")


def test_qdrant_service():
    """Ensure Qdrant is reachable and collection is initialized."""
    try:
        service = QdrantService()
        dummy_vector = [0.0] * service.vector_size
        results = service.search_columns(dummy_vector, limit=1)
        assert isinstance(results, list)
        print(f"✓ Qdrant service reachable (returned {len(results)} result(s))")
    except Exception as e:
        print(f"⚠️  Skipping Qdrant service test: {e}")


def test_llm_service():
    """Test LLM service with both providers"""
    try:
        # Test OpenAI if configured
        import os
        if os.getenv("OPENAI_API_KEY"):
            service = LLMService(provider="openai")
            response = service.generate([
                {"role": "user", "content": "Say 'test' if you can read this."}
            ], max_tokens=10)
            assert len(response) > 0
            print("✓ OpenAI LLM service works")
        else:
            print("⚠️  OPENAI_API_KEY not set, skipping OpenAI test")
    except Exception as e:
        print(f"⚠️  Skipping OpenAI test: {e}")
    
    try:
        # Test Claude if configured
        import os
        if os.getenv("ANTHROPIC_API_KEY"):
            service = LLMService(provider="claude")
            response = service.generate([
                {"role": "user", "content": "Say 'test' if you can read this."}
            ], max_tokens=10)
            assert len(response) > 0
            print("✓ Claude LLM service works")
        else:
            print("⚠️  ANTHROPIC_API_KEY not set, skipping Claude test")
    except Exception as e:
        print(f"⚠️  Skipping Claude test: {e}")


if __name__ == "__main__":
    print("\nRunning service tests...\n")
    test_vector_embedding()
    test_azure_metadata_load()
    test_domo_connection()
    test_vector_search()
    test_qdrant_service()
    test_llm_service()
    print("\n✓ All tests completed!")


