#!/usr/bin/env python3
"""
Script to query the AI Agent API endpoint (local or production)
"""
import requests
import json
import sys
import argparse
import os
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env file from project root
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not available, skip

# Default API URLs
LOCAL_URL = "http://localhost:8000"
PROD_URL = "https://app-ai-agent-v2.ambitiousdesert-4823611f.centralus.azurecontainerapps.io"

# Environment URL mapping
ENV_URLS = {
    "local": LOCAL_URL,
    "prod": PROD_URL,
    "production": PROD_URL,
}

def query_api(question, user_id="test_user", base_url=LOCAL_URL, api_key=None, model=None):
    """
    Query the API endpoint with a question.
    
    Args:
        question: The question to ask
        user_id: User ID for the query
        base_url: Base URL of the API
        api_key: Optional API key for authentication
        model: Optional model to use (e.g., google/gemini-2.5-flash)
        
    Returns:
        Response JSON as a dictionary
    """
    url = f"{base_url}/api/v1/query"
    
    payload = {
        "query": question,
        "user_id": user_id
    }
    
    if model:
        payload["agent_config"] = {"model": model}
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Add API key header if provided
    if api_key:
        headers["X-API-Key"] = api_key
    
    print(f"Querying API: {url}")
    print(f"Question: {question}")
    if model:
        print(f"Model: {model}")
    print("-" * 80)
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}", file=sys.stderr)
            print(f"Response body: {e.response.text}", file=sys.stderr)
        sys.exit(1)

def print_response(data):
    """Pretty print the response data."""
    print("\n" + "=" * 80)
    print("API RESPONSE")
    print("=" * 80)
    print(json.dumps(data, indent=2))
    print("=" * 80)
    
    # Extract and print key information
    if "final_response" in data:
        print("\n" + "-" * 80)
        print("FINAL RESPONSE:")
        print("-" * 80)
        print(data["final_response"])
    
    if "sql_query" in data:
        print("\n" + "-" * 80)
        print("GENERATED SQL:")
        print("-" * 80)
        print(data["sql_query"])
    
    if "steps" in data:
        print("\n" + "-" * 80)
        print("EXECUTION STEPS:")
        print("-" * 80)
        for step in data["steps"]:
            step_name = step.get("step", "unknown")
            status = step.get("status", "unknown")
            duration = step.get("duration_ms", 0)
            print(f"  {step_name}: {status} ({duration}ms)")
    
    if "metadata" in data:
        exec_time = data["metadata"].get("execution_time_ms", 0)
        model_used = data["metadata"].get("model", "unknown")
        print(f"\nTotal execution time: {exec_time}ms")
        print(f"Model used: {model_used}")
    
    # if "data_sample" in data and data["data_sample"]:
    #     print("\n" + "-" * 80)
    #     print("DATA SAMPLE:")
    #     print("-" * 80)
    #     print(json.dumps(data["data_sample"], indent=2))

def test_health_check(base_url):
    """Test the health check endpoint."""
    url = f"{base_url}/health"
    print(f"Testing health endpoint: {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        print("✓ Health check passed")
        print(json.dumps(response.json(), indent=2))
        return True
    except requests.exceptions.RequestException as e:
        print(f"✗ Health check failed: {e}", file=sys.stderr)
        return False

def get_base_url(env=None, custom_url=None):
    """
    Get the base URL based on environment or custom URL.
    
    Args:
        env: Environment name ('local', 'prod', 'production')
        custom_url: Custom URL to use (overrides env)
        
    Returns:
        Base URL string
    """
    if custom_url:
        return custom_url
    
    if env:
        env_lower = env.lower()
        if env_lower in ENV_URLS:
            return ENV_URLS[env_lower]
        else:
            print(f"Warning: Unknown environment '{env}'. Using default local URL.", file=sys.stderr)
            return LOCAL_URL
    
    return LOCAL_URL  # Default to local

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test the AI Agent API (local or production)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test local API with default question
  python3 test_query.py --env local
  
  # Test production API with custom question
  python3 test_query.py --env prod -q "What properties churned?"
  
  # Test with custom URL
  python3 test_query.py --url http://custom-url:8000
  
  # Health check only
  python3 test_query.py --env prod --health-only
  
  # Test with specific model
  python3 test_query.py --model google/gemini-2.5-flash
        """
    )
    
    parser.add_argument(
        "--env",
        "-e",
        type=str,
        choices=["local", "prod", "production"],
        default="local",
        help="Environment to test (local, prod, or production). Default: local"
    )
    
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        default=None,
        help="Custom API base URL (overrides --env)"
    )
    
    parser.add_argument(
        "--question",
        "-q",
        type=str,
        default="What are 5 properties that were lost in September 2025?",
        help="Question to ask the API"
    )
    
    parser.add_argument(
        "--user-id",
        "-i",
        type=str,
        default="test_user",
        help="User ID for the query"
    )
    
    parser.add_argument(
        "--health-only",
        "-H",
        action="store_true",
        help="Only test the health endpoint"
    )
    
    parser.add_argument(
        "--api-key",
        "-k",
        type=str,
        default=None,
        help="API key for authentication (or set API_KEY environment variable)"
    )
    
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=None,
        help="Model ID to use (e.g. google/gemini-2.5-flash)"
    )
    
    args = parser.parse_args()
    
    # Get API key from argument or environment variable
    # Check multiple possible environment variable names
    api_key = args.api_key or os.getenv("AZURE_AGENT_API_KEY") or os.getenv("API_KEY") or os.getenv("API_SECRET_KEY")
    
    # Auto-use API key for production if not explicitly provided
    if not api_key and args.env in ["prod", "production"]:
        print("⚠️  Warning: No API key provided for production environment.", file=sys.stderr)
        print("   Set AZURE_AGENT_API_KEY, API_KEY, or use --api-key flag.", file=sys.stderr)
    
    # Get the base URL
    base_url = get_base_url(args.env, args.url)
    
    # Determine environment name for display
    env_name = args.env
    if args.url:
        env_name = "custom"
    elif args.env == "production":
        env_name = "prod"
    
    print("=" * 80)
    print("AI Agent API Query Test")
    print("=" * 80)
    print(f"Environment: {env_name}")
    print(f"Base URL: {base_url}")
    print()
    
    # Test health check first
    if not test_health_check(base_url):
        if not args.health_only:
            print("\n⚠️  Health check failed. Proceeding anyway...")
    print()
    
    if args.health_only:
        print("Health check complete.")
        sys.exit(0)
    
    # Run the query
    response_data = query_api(args.question, args.user_id, base_url, api_key, args.model)
    print_response(response_data)
