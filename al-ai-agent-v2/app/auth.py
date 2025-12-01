"""
API Key Authentication for FastAPI
"""
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
import os

# API Key header name
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key_from_env():
    """Get API key from environment variable."""
    return os.getenv("AZURE_AGENT_API_KEY") or os.getenv("API_KEY") or os.getenv("API_SECRET_KEY")

def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    """
    Verify the API key from the request header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        str: The API key if valid
        
    Raises:
        HTTPException: If API key is missing or invalid
    """
    # Get expected API key from environment
    expected_api_key = get_api_key_from_env()
    
    # If no API key is configured, allow access (for development)
    if not expected_api_key:
        return api_key or "no-auth-configured"
    
    # If API key is missing from request
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Please provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Verify API key matches
    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    return api_key

def require_api_key():
    """
    Dependency function to require API key authentication.
    Use this in route dependencies.
    
    Example:
        @router.post("/endpoint")
        async def my_endpoint(api_key: str = Depends(require_api_key)):
            ...
    """
    return Security(verify_api_key)

