"""
Qdrant service for managing column-level embeddings.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models

load_dotenv()

logger = logging.getLogger(__name__)


class QdrantService:
    """Thin wrapper around QdrantClient with sensible defaults for this project."""

    def __init__(self):
        self.url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.api_key = os.getenv("QDRANT_API_KEY")
        self.collection_name = os.getenv("QDRANT_COLLECTION_NAME", "column_embeddings")
        self.vector_size = int(os.getenv("EMBEDDING_DIMENSION", "1536"))

        if not self.url:
            raise ValueError("QDRANT_URL environment variable is required")

        self.client = QdrantClient(url=self.url, api_key=self.api_key, timeout=30)
        logger.info(f"QdrantService initialized with URL: {self.url}, Collection: {self.collection_name}")
        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """Create the collection if it does not already exist."""
        try:
            if self.client.collection_exists(self.collection_name):
                return

            logger.info("Creating Qdrant collection '%s'", self.collection_name)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=rest_models.VectorParams(
                    size=self.vector_size,
                    distance=rest_models.Distance.COSINE,
                ),
                optimizers_config=rest_models.OptimizersConfigDiff(
                    indexing_threshold=20000
                ),
                sparse_vectors_config=None,
                hnsw_config=rest_models.HnswConfigDiff(m=16, ef_construct=128),
                shard_number=1,
                replication_factor=1,
                write_consistency_factor=1,
            )
        except Exception as exc:
            logger.error("Failed to ensure Qdrant collection: %s", exc)
            raise

    def upsert_columns(
        self,
        dataset_id: str,
        dataset_name: str,
        table_name: str,
        column_embeddings: List[Dict[str, Any]],
        business_rules: str = "",
        common_queries: str = ""
    ):
        """
        Upsert a batch of column embeddings.

        Args:
            dataset_id: Dataset identifier.
            dataset_name: Human-readable dataset name.
            table_name: Table name.
            column_embeddings: List of dicts containing
                {
                    "column_metadata": {...},
                    "embedding": [...],
                    "column_index": int
                }
            business_rules: Table-level business rules
            common_queries: Table-level common query patterns
        """
        points: List[rest_models.PointStruct] = []

        for column in column_embeddings:
            metadata = column.get("column_metadata") or {}
            column_name = metadata.get("name")
            embedding = column.get("embedding")
            column_index = column.get("column_index", 0)

            if not column_name or not embedding:
                logger.warning(
                    "Skipping column upsert for dataset %s due to missing data",
                    dataset_id,
                )
                continue

            payload = {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "table_name": table_name,
                "column_name": column_name,
                "column_type": metadata.get("type"),
                "column_category": metadata.get("category"),
                "column_index": column_index,
                "full_metadata": metadata,
                "business_rules": business_rules,
                "common_queries": common_queries,
            }

            # Generate a UUID-based point ID from dataset_id and column_name
            import uuid
            point_id_str = f"{dataset_id}:{column_name}"
            point_id = uuid.uuid5(uuid.NAMESPACE_DNS, point_id_str)
            points.append(
                rest_models.PointStruct(id=str(point_id), vector=embedding, payload=payload)
            )

        if not points:
            logger.warning(
                "No valid column embeddings provided for dataset %s", dataset_id
            )
            return

        self.client.upsert(collection_name=self.collection_name, points=points)

    def delete_by_dataset(self, dataset_id: str):
        """Remove all points for a dataset."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=rest_models.FilterSelector(
                    filter=rest_models.Filter(
                        must=[
                            rest_models.FieldCondition(
                                key="dataset_id",
                                match=rest_models.MatchValue(value=dataset_id),
                            )
                        ]
                    )
                ),
            )
        except Exception as exc:
            logger.error("Failed to delete dataset %s from Qdrant: %s", dataset_id, exc)
            raise

    def search_columns(
        self,
        query_vector: Optional[List[float]] = None,
        query_embedding: Optional[List[float]] = None,
        limit: int = 20,
        filters: Optional[rest_models.Filter] = None,
        with_vectors: bool = False,
        query_text: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant columns.

        Args:
            query_vector: Embedded query vector.
            query_embedding: Deprecated alias for query_vector (for backward compatibility).
            limit: Number of points to return.
            filters: Optional Qdrant filter.
            with_vectors: Whether to include vectors in the response.
            query_text: Optional raw text (not used, kept for compatibility).

        Returns:
            List of dictionaries with payload and score.
        """
        try:
            vector = query_vector if query_vector is not None else query_embedding
            if vector is None:
                raise ValueError("query_vector (or query_embedding) is required for Qdrant search.")

            # Use query_points API (qdrant-client >= 1.7.0 standard)
            # Try NearestQuery first (most common pattern)
            try:
                from qdrant_client.http.models import NearestQuery
                query = NearestQuery(nearest=vector)
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query,
                    limit=limit,
                    with_payload=True,
                    with_vectors=with_vectors,
                    query_filter=filters,
                )
                # query_points returns QueryResponse with points attribute
                results = response.points if hasattr(response, 'points') else []
            except (AttributeError, ImportError, TypeError, ValueError) as e1:
                # Fallback: try Query with Nearest syntax
                try:
                    from qdrant_client.http.models import Query, Nearest
                    query = Query(nearest=Nearest(vector=vector))
                    response = self.client.query_points(
                        collection_name=self.collection_name,
                        query=query,
                        limit=limit,
                        with_payload=True,
                        with_vectors=with_vectors,
                        query_filter=filters,
                    )
                    results = response.points if hasattr(response, 'points') else []
                except (AttributeError, ImportError, TypeError, ValueError) as e2:
                    # Final fallback: try older search API (for older qdrant-client versions)
                    try:
                        results = self.client.search(
                            collection_name=self.collection_name,
                            query_vector=vector,
                            limit=limit,
                            score_threshold=None,
                            with_payload=True,
                            with_vectors=with_vectors,
                            query_filter=filters,
                        )
                    except AttributeError as e3:
                        logger.error(f"QdrantClient API compatibility issue. URL: {self.url}")
                        logger.error(f"Tried: query_points(NearestQuery)={e1}, query_points(Query/Nearest)={e2}, search={e3}")
                        raise AttributeError(
                            f"QdrantClient API not compatible. Tried query_points and search methods. "
                            f"Please check qdrant-client version (>=1.7.0 required) and Qdrant server version."
                        ) from e3

            formatted_results = []
            for result in results:
                # Handle both ScoredPoint (from search) and QueryResult (from query_points)
                result_id = result.id if hasattr(result, 'id') else getattr(result, 'point_id', None)
                result_score = result.score if hasattr(result, 'score') else getattr(result, 'score', 0.0)
                result_payload = result.payload if hasattr(result, 'payload') else getattr(result, 'payload', {})
                result_vector = None
                if with_vectors:
                    result_vector = result.vector if hasattr(result, 'vector') else getattr(result, 'vector', None)
                
                formatted_results.append(
                    {
                        "id": result_id,
                        "score": result_score,
                        "payload": result_payload or {},
                        "vector": result_vector,
                    }
                )
            return formatted_results
        except Exception as exc:
            logger.error("Qdrant search failed: %s", exc)
            logger.error("Qdrant URL: %s, Collection: %s", self.url, self.collection_name)
            raise


