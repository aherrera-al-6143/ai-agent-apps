"""
Azure Blob Storage service for loading dataset metadata YAML files
"""
import os
import yaml
from typing import Dict, Optional
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()


class AzureMetadataService:
    """Service for loading dataset metadata from Azure Blob Storage"""
    
    def __init__(self):
        """Initialize Azure Blob Storage client"""
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT")
        account_key = os.getenv("AZURE_API_KEY")
        container_name = os.getenv("AZURE_STORAGE_CONTAINER")
        
        if not all([account_name, account_key, container_name]):
            raise ValueError(
                "Azure storage configuration missing. "
                "Required: AZURE_STORAGE_ACCOUNT, AZURE_API_KEY, AZURE_STORAGE_CONTAINER"
            )
        
        # Create blob service client
        connection_string = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={account_name};"
            f"AccountKey={account_key};"
            f"EndpointSuffix=core.windows.net"
        )
        
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_name = container_name
    
    def get_metadata(self, dataset_id: str) -> Optional[Dict]:
        """
        Load metadata YAML file for a dataset
        
        Args:
            dataset_id: Dataset identifier (used as blob name)
        
        Returns:
            Dictionary containing metadata, or None if not found
        """
        try:
            # Construct blob name (assuming format: {dataset_id}.yaml)
            blob_name = f"{dataset_id}.yaml"
            
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # Download and parse YAML
            blob_data = blob_client.download_blob()
            yaml_content = blob_data.readall().decode('utf-8')
            metadata = yaml.safe_load(yaml_content)
            
            return metadata
            
        except Exception as e:
            print(f"Failed to load metadata for {dataset_id}: {str(e)}")
            return None
    
    def list_available_datasets(self) -> list:
        """
        List all available dataset metadata files in the container
        
        Returns:
            List of dataset IDs (blob names without .yaml extension)
        """
        try:
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            
            datasets = []
            for blob in container_client.list_blobs(name_starts_with=""):
                if blob.name.endswith('.yaml'):
                    # Extract dataset ID from blob name
                    dataset_id = blob.name.replace('.yaml', '')
                    datasets.append(dataset_id)
            
            return datasets
            
        except Exception as e:
            print(f"Failed to list datasets: {str(e)}")
            return []





