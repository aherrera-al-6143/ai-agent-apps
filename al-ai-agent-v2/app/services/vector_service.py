"""
Vector service for OpenAI embeddings and pgvector similarity search
"""
import os
import json
import uuid
from typing import Any, Dict, List, Optional, Sequence, Union
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI
from dotenv import load_dotenv
from qdrant_client.http import models as qmodels

from app.database.models import DatasetMetadata
from app.services.qdrant_service import QdrantService

load_dotenv()


class VectorService:
    """Service for generating embeddings and performing vector search"""
    
    def __init__(self):
        """Initialize OpenAI client for embeddings"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-small"
        self.dimension = 1536
        self._qdrant_service: Optional[QdrantService] = None

    def _get_qdrant_service(self) -> QdrantService:
        """Lazy-load Qdrant service."""
        if self._qdrant_service is None:
            self._qdrant_service = QdrantService()
        return self._qdrant_service
    
    def create_embedding(self, text: str) -> List[float]:
        """
        Create embedding for text using OpenAI
        
        Args:
            text: Text to embed
        
        Returns:
            List of floats representing the embedding vector
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"Failed to create embedding: {str(e)}")
    
    def _format_column_comprehensive(self, col: Dict) -> str:
        """
        Format a single column with all available metadata fields and smart truncation.
        
        Args:
            col: Column metadata dictionary
        
        Returns:
            Formatted column text string
        """
        col_name = col.get('name', '')
        col_type = col.get('type', '')
        category = col.get('category', '')
        description = col.get('description', '')
        business_meaning = col.get('business_meaning', '')
        examples = col.get('examples', [])
        definitions = col.get('definitions', [])
        business_rules = col.get('business_rules', '')
        data_quality_notes = col.get('data_quality_notes', '')
        
        # Start with name and type
        parts = [f"{col_name} ({col_type})"]
        
        # Add category if available
        if category:
            parts.append(f"category: {category}")
        
        # Add description (truncate to 150 chars)
        if description:
            desc_text = description[:147] + "..." if len(description) > 150 else description
            parts.append(f"Description: {desc_text}")
        
        # Add business meaning if different from description (truncate to 150 chars)
        if business_meaning and business_meaning != description:
            meaning_text = business_meaning[:147] + "..." if len(business_meaning) > 150 else business_meaning
            parts.append(f"Business meaning: {meaning_text}")
        
        # Add examples (limit to first 15 values)
        if examples and isinstance(examples, list):
            examples_list = examples[:15]
            examples_str = ", ".join(str(ex) for ex in examples_list)
            if len(examples) > 15:
                examples_str += f" (and {len(examples) - 15} more)"
            parts.append(f"Examples: {examples_str}")
        
        # Add definitions (limit to first 5, truncate meaning to 100 chars)
        if definitions and isinstance(definitions, list) and len(definitions) > 0:
            def_parts = []
            for def_item in definitions[:5]:
                if isinstance(def_item, dict):
                    value = def_item.get('value', '')
                    meaning = def_item.get('meaning', '')
                    if meaning:
                        meaning = meaning[:97] + "..." if len(meaning) > 100 else meaning
                        def_parts.append(f"{value}: {meaning}")
                    elif value:
                        def_parts.append(value)
            if def_parts:
                def_text = "; ".join(def_parts)
                if len(definitions) > 5:
                    def_text += f" (and {len(definitions) - 5} more definitions)"
                parts.append(f"Definitions: {def_text}")
        
        # Add business rules if non-empty (truncate to 200 chars)
        if business_rules and business_rules.strip():
            rules_text = business_rules[:197] + "..." if len(business_rules) > 200 else business_rules
            parts.append(f"Business rules: {rules_text}")
        
        # Add data quality notes (usually short, include as-is)
        if data_quality_notes and data_quality_notes.strip():
            parts.append(f"Data quality: {data_quality_notes}")
        
        return ". ".join(parts)
    
    def _build_embedding_text(
        self,
        table_name: str,
        description: str,
        columns: List[Dict]
    ) -> str:
        """
        Build embedding text that includes table name, description, and column information.
        
        Args:
            table_name: Name of the table/dataset
            description: Dataset description
            columns: List of column metadata dictionaries
        
        Returns:
            Formatted text string for embedding
        """
        # Start with table name and description
        parts = [f"{table_name}. {description}"]
        
        # Add column information
        if columns:
            # Prioritize columns: geography columns first, then those with descriptions, date/time columns, then others
            # Limit to 50 columns to stay within reasonable token limits
            prioritized_columns = []
            
            # First pass: geography columns (important for location queries) - search all columns first
            for col in columns:
                col_name = col.get('name', '')
                col_category = col.get('category', '').lower()
                
                if col_category == 'geography' and col_name:
                    prioritized_columns.append(col)
                    # Stop if we have enough (but prioritize geography)
                    if len(prioritized_columns) >= 50:
                        break
            
            # Second pass: columns with descriptions (search first 100 to catch important columns)
            for col in columns[:100]:
                col_name = col.get('name', '')
                col_desc = col.get('description', '') or col.get('business_meaning', '')
                
                if col_desc:
                    # Only add if not already added
                    if not any(c.get('name', '') == col_name for c in prioritized_columns):
                        prioritized_columns.append(col)
                        # Stop if we have enough
                        if len(prioritized_columns) >= 50:
                            break
            
            # Third pass: date/time columns (often important for queries)
            for col in columns[:100]:
                col_name = col.get('name', '')
                col_type = col.get('type', '').upper()
                
                if col_name and col_type in ['DATE', 'DATETIME', 'TIMESTAMP']:
                    # Only add if not already added
                    if not any(c.get('name', '') == col_name for c in prioritized_columns):
                        prioritized_columns.append(col)
                        # Stop if we have enough
                        if len(prioritized_columns) >= 50:
                            break
            
            # Fourth pass: remaining columns up to limit
            for col in columns[:100]:
                col_name = col.get('name', '')
                if col_name and not any(c.get('name', '') == col_name for c in prioritized_columns):
                    prioritized_columns.append(col)
                    # Stop at 50 columns total
                    if len(prioritized_columns) >= 50:
                        break
            
            # Format columns into text using comprehensive formatter
            if prioritized_columns:
                column_parts = []
                for col in prioritized_columns:
                    column_parts.append(self._format_column_comprehensive(col))
                
                parts.append("Columns: " + ", ".join(column_parts))
        
        return ". ".join(parts)
    
    def _build_column_embedding_text(
        self,
        dataset_name: str,
        table_name: str,
        column: Dict,
        column_index: int
    ) -> str:
        """
        Build a descriptive string for a single column embedding.
        
        Args:
            dataset_name: Human-friendly dataset or domain name
            table_name: Table name
            column: Column metadata dictionary
            column_index: Original column order to preserve positional hints
        
        Returns:
            Rich text representation of the column
        """
        col_name = column.get('name', '')
        col_type = column.get('type', '')
        category = column.get('category', '')
        description = column.get('description', '')
        business_meaning = column.get('business_meaning', '')
        examples = column.get('examples', [])
        definitions = column.get('definitions', [])
        business_rules = column.get('business_rules', '')
        data_quality_notes = column.get('data_quality_notes', '')
        
        header = f"{dataset_name}.{table_name}.{col_name}".strip(".")
        parts = [
            header,
            f"type: {col_type}" if col_type else "",
            f"category: {category}" if category else "",
            f"position: {column_index}",
        ]
        
        if description:
            parts.append(f"description: {description}")
        if business_meaning:
            parts.append(f"business_meaning: {business_meaning}")
        if business_rules:
            parts.append(f"business_rules: {business_rules}")
        if data_quality_notes:
            parts.append(f"data_quality: {data_quality_notes}")
        
        if examples and isinstance(examples, list):
            example_values = ", ".join(str(ex) for ex in examples[:10])
            parts.append(f"examples: {example_values}")
        
        if definitions and isinstance(definitions, list):
            definition_pairs = []
            for definition in definitions[:5]:
                if isinstance(definition, dict):
                    value = definition.get('value')
                    meaning = definition.get('meaning')
                    if value and meaning:
                        definition_pairs.append(f"{value}: {meaning}")
                    elif value:
                        definition_pairs.append(value)
            if definition_pairs:
                parts.append(f"definitions: {'; '.join(definition_pairs)}")
        
        return ". ".join([part for part in parts if part])
    
    def _build_column_payload(
        self,
        dataset_id: str,
        dataset_name: str,
        table_name: str,
        dataset_description: str,
        column: Dict,
        column_index: int,
        column_text: str
    ) -> Dict[str, Any]:
        """Build payload structure saved to Qdrant."""
        return {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "table_name": table_name,
            "dataset_description": dataset_description,
            "column_name": column.get("name"),
            "column_type": column.get("type"),
            "column_category": column.get("category"),
            "column_index": column_index,
            "column_text": column_text,
            "full_metadata": column
        }

    @staticmethod
    def _build_point_id(dataset_id: str, column_name: str, column_index: int) -> str:
        """Create deterministic Qdrant point identifiers for easy upserts."""
        raw_value = f"{dataset_id}:{column_name}:{column_index}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw_value))
    
    def build_column_points(
        self,
        dataset_id: str,
        dataset_name: str,
        table_name: str,
        dataset_description: str,
        columns: Sequence[Dict[str, Any]]
    ) -> List[qmodels.PointStruct]:
        """
        Generate Qdrant points for every column in a dataset.
        """
        if not columns:
            return []
        
        dataset_label = dataset_name or table_name or dataset_id
        table_label = table_name or dataset_label
        description = dataset_description or ""
        
        points: List[qmodels.PointStruct] = []
        for index, column in enumerate(columns):
            if not isinstance(column, dict):
                continue
            
            column_name = column.get('name')
            if not column_name:
                continue
            
            text = self._build_column_embedding_text(
                dataset_label,
                table_label,
                column,
                index
            )
            embedding = self.create_embedding(text)
            payload = self._build_column_payload(
                dataset_id=dataset_id,
                dataset_name=dataset_label,
                table_name=table_label,
                dataset_description=description,
                column=column,
                column_index=index,
                column_text=text
            )
            # Generate UUID-based point ID (Qdrant requires UUID or integer)
            import uuid
            point_id_str = self._build_point_id(dataset_id, column_name, index)
            point_id = uuid.uuid5(uuid.NAMESPACE_DNS, point_id_str)
            points.append(
                qmodels.PointStruct(
                    id=str(point_id),
                    vector=embedding,
                    payload=payload
                )
            )
        
        return points
    
    def store_column_embeddings(
        self,
        dataset_id: str,
        dataset_name: str,
        table_name: str,
        dataset_description: str,
        columns: Sequence[Dict[str, Any]],
        qdrant_service: Optional[QdrantService] = None,
        business_rules: str = "",
        common_queries: str = ""
    ) -> int:
        """Generate column embeddings and persist them to Qdrant."""
        points = self.build_column_points(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            table_name=table_name,
            dataset_description=dataset_description,
            columns=columns
        )
        
        if not points:
            return 0
        
        service = qdrant_service or self._get_qdrant_service()
        # Use the points directly - upsert_columns will handle them
        # But we need to convert PointStruct to the dict format expected
        column_embeddings = []
        for point in points:
            payload = point.payload or {}
            full_metadata = payload.get("full_metadata", {})
            # Ensure we have the column name in metadata
            if "name" not in full_metadata:
                full_metadata["name"] = payload.get("column_name", "")
            column_embeddings.append({
                "column_metadata": full_metadata,
                "embedding": point.vector,
                "column_index": payload.get("column_index", 0)
            })
        
        service.upsert_columns(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            table_name=table_name,
            column_embeddings=column_embeddings,
            business_rules=business_rules,
            common_queries=common_queries
        )
        return len(points)
    
    def search_datasets(
        self,
        db: Session,
        query: str,
        top_k: int = 3
    ) -> List[Dict]:
        """
        Search for similar datasets using vector similarity
        
        Args:
            db: Database session
            query: Search query text
            top_k: Number of results to return
        
        Returns:
            List of dictionaries with dataset info and similarity scores
        """
        # Generate query embedding
        query_embedding = self.create_embedding(query)
        
        # Convert embedding to string format for pgvector
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
        
        # Perform vector similarity search using cosine distance
        # pgvector uses 1 - cosine_similarity, so we order by distance ASC
        # Use CAST to properly convert the string to vector type
        sql = text("""
            SELECT 
                dataset_id,
                table_name,
                description,
                columns,
                1 - (embedding <=> CAST(:embedding AS vector)) as similarity
            FROM dataset_metadata
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)
        
        result = db.execute(
            sql,
            {"embedding": embedding_str, "top_k": top_k}
        )
        
        results = []
        for row in result:
            results.append({
                "dataset_id": row.dataset_id,
                "table_name": row.table_name,
                "description": row.description,
                "columns": row.columns,
                "similarity": float(row.similarity)
            })
        
        return results
    
    def store_dataset_embedding(
        self,
        db: Session,
        dataset_id: str,
        table_name: str,
        description: str,
        columns: Union[List[Dict], Dict],
        embedding: Optional[List[float]] = None
    ):
        """
        Store dataset metadata with embedding (legacy dataset-level path).
        Prefer `store_column_embeddings` for new ingestion.
        
        Args:
            db: Database session
            dataset_id: Unique dataset identifier
            table_name: Name of the table/dataset
            description: Dataset description
            columns: Column metadata as dictionary (can be list or dict)
            embedding: Optional pre-computed embedding, otherwise generated from table name, description, and columns
        """
        if embedding is None:
            # Convert columns to list if it's a dict
            columns_list = columns if isinstance(columns, list) else (columns.get('columns', []) if isinstance(columns, dict) else [])
            
            # Build embedding text that includes column information
            embedding_text = self._build_embedding_text(
                table_name=table_name,
                description=description or "",
                columns=columns_list
            )
            
            # Generate embedding from the comprehensive text
            embedding = self.create_embedding(embedding_text)
        
        # Convert to string format for pgvector
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"
        
        # Check if dataset already exists
        existing = db.query(DatasetMetadata).filter(
            DatasetMetadata.dataset_id == dataset_id
        ).first()
        
        from sqlalchemy import text
        from sqlalchemy.dialects.postgresql import JSONB
        
        # Convert columns to JSON string
        columns_json = json.dumps(columns)
        
        if existing:
            # Update existing - use text() with proper casting
            db.execute(
                text("UPDATE dataset_metadata SET table_name=:tn, description=:desc, columns=CAST(:cols AS jsonb), embedding=CAST(:emb AS vector) WHERE dataset_id=:did"),
                {
                    "tn": table_name,
                    "desc": description,
                    "cols": columns_json,
                    "emb": embedding_str,
                    "did": dataset_id
                }
            )
        else:
            # Create new - use text() with proper casting
            db.execute(
                text("INSERT INTO dataset_metadata (dataset_id, table_name, description, columns, embedding) VALUES (:did, :tn, :desc, CAST(:cols AS jsonb), CAST(:emb AS vector))"),
                {
                    "did": dataset_id,
                    "tn": table_name,
                    "desc": description,
                    "cols": columns_json,
                    "emb": embedding_str
                }
            )
        
        db.commit()

