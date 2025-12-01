"""
Domo service for executing SQL queries
"""
import os
from typing import Dict, List, Optional, Any
from pydomo import Domo
from dotenv import load_dotenv

load_dotenv()


class DomoService:
    """Service for executing queries in Domo"""
    
    def __init__(self):
        """Initialize Domo client"""
        client_id = os.getenv("DOMO_CLIENT_ID")
        secret_key = os.getenv("DOMO_SECRET_KEY")
        
        if not client_id or not secret_key:
            raise ValueError("DOMO_CLIENT_ID and DOMO_SECRET_KEY must be set")
        
        self.client = Domo(client_id, secret_key, api_host='api.domo.com')
    
    def execute_query(
        self,
        dataset_id: str,
        sql_query: str
    ) -> Dict[str, Any]:
        """
        Execute SQL query in Domo dataset
        
        Args:
            dataset_id: Domo dataset ID
            sql_query: SQL query to execute
        
        Returns:
            Dictionary with query results
        """
        try:
            # Execute query using Domo Data API
            result = self.client.datasets.query(
                dataset_id=dataset_id,
                query=sql_query
            )
            
            # Format results
            rows = result if isinstance(result, list) else result.get('rows', [])
            
            return {
                "success": True,
                "rows": rows,
                "row_count": len(rows),
                "dataset_id": dataset_id
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "rows": [],
                "row_count": 0,
                "dataset_id": dataset_id
            }
    
    def get_available_datasets(self) -> List[Dict]:
        """
        Get list of available datasets
        
        Returns:
            List of dataset dictionaries
        """
        try:
            datasets = self.client.datasets.list()
            return [
                {
                    "id": ds.get("id"),
                    "name": ds.get("name"),
                    "description": ds.get("description", "")
                }
                for ds in datasets
            ]
        except Exception as e:
            print(f"Error getting datasets: {e}")
            return []
    
    def get_dataset_info(self, dataset_id: str) -> Optional[Dict]:
        """
        Get information about a specific dataset
        
        Args:
            dataset_id: Dataset ID
        
        Returns:
            Dataset information dictionary or None
        """
        try:
            dataset = self.client.datasets.get(dataset_id)
            return {
                "id": dataset.get("id"),
                "name": dataset.get("name"),
                "description": dataset.get("description", ""),
                "schema": dataset.get("schema", {})
            }
        except Exception as e:
            print(f"Error getting dataset info: {e}")
            return None





