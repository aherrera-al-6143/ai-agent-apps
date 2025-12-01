#!/usr/bin/env python3
"""
Test KPI Report Tool Routing

This script tests whether the agent correctly routes KPI-related queries
to the generate_kpi_report_tool API.

Usage:
    python test_kpi_query.py                    # Test against local agent
    python test_kpi_query.py --env prod         # Test against production agent
    python test_kpi_query.py --verbose          # Show full response details
"""

import requests
import json
import argparse
import os
import sys
from pathlib import Path

# Try to load .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# API URLs
LOCAL_URL = "http://localhost:8000"
PROD_URL = "https://app-ai-agent-v2.ambitiousdesert-4823611f.centralus.azurecontainerapps.io"


def test_kpi_routing(
    query: str = "provide me a strategic overview of atlanta",
    base_url: str = LOCAL_URL,
    api_key: str = None,
    verbose: bool = False
) -> bool:
    """
    Test if the agent correctly routes a KPI-related query to the KPI reports API.
    
    Args:
        query: Natural language query that should trigger KPI report generation
        base_url: Base URL of the agent API
        api_key: Optional API key for authentication
        verbose: If True, print full response details
    
    Returns:
        True if routing was successful (KPI tool was invoked), False otherwise
    """
    url = f"{base_url}/api/v1/query"
    
    payload = {
        "query": query,
        "user_id": "test_kpi_routing"
    }
    
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    
    print(f"\n{'='*60}")
    print("KPI REPORT ROUTING TEST")
    print(f"{'='*60}")
    print(f"Query: \"{query}\"")
    print(f"Agent URL: {base_url}")
    print(f"{'='*60}\n")
    
    try:
        # Make the request
        print("⏳ Sending query to agent (this may take up to 2 minutes)...")
        response = requests.post(url, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        data = response.json()
        
        if verbose:
            print("\n📋 Full Response:")
            print(json.dumps(data, indent=2)[:2000])  # Truncate for readability
            print("..." if len(json.dumps(data)) > 2000 else "")
        
        # Check for KPI report indicators in the response
        final_response = data.get("final_response", "").lower()
        
        # The KPI tool result would be in the tool messages, but we can also check
        # the final response for indicators that the KPI report was generated
        kpi_indicators = [
            "pdf" in final_response,
            "report" in final_response and ("generated" in final_response or "created" in final_response),
            "strategic overview" in final_response,
            "portfolio" in final_response and "performance" in final_response,
            "properties analyzed" in final_response,
            "health" in final_response and "scorecard" in final_response,
            ".pdf" in final_response,
            "markdown" in final_response,
        ]
        
        # Also check if we got specific data structures from KPI API
        # The data_sample from query_database_tool has row data
        # The KPI tool would not return standard "data_sample" rows
        data_sample = data.get("data_sample", [])
        sql_query = data.get("sql_query")
        
        # If there's no SQL query but there's a response about reports,
        # it likely used the KPI tool
        used_query_tool = sql_query is not None and len(sql_query) > 0
        has_standard_rows = len(data_sample) > 0 and isinstance(data_sample[0], dict)
        
        # Check metadata
        execution_time = data.get("metadata", {}).get("execution_time_ms", 0)
        
        # Determine if KPI routing was successful
        kpi_routing_success = any(kpi_indicators) and not (used_query_tool and has_standard_rows)
        
        # Alternative check: look for KPI-specific phrases in response
        kpi_phrases = [
            "portfolio health",
            "kpi report",
            "performance analysis",
            "top performers",
            "critical analysis",
            "operational focus",
            "strategic overview",
            "properties analyzed",
            "avg score",
            "overall status"
        ]
        phrase_match = any(phrase in final_response for phrase in kpi_phrases)
        
        # Final determination
        is_kpi_routed = kpi_routing_success or phrase_match
        
        print("\n" + "="*60)
        print("ROUTING ANALYSIS")
        print("="*60)
        print(f"✓ KPI-related phrases in response: {phrase_match}")
        print(f"✓ Used query_database_tool: {used_query_tool}")
        print(f"✓ Has standard data rows: {has_standard_rows}")
        print(f"✓ Execution time: {execution_time}ms")
        print(f"\n📝 Response Preview:")
        print(f"   {final_response[:300]}{'...' if len(final_response) > 300 else ''}")
        
        print("\n" + "="*60)
        if is_kpi_routed:
            print("✅ RESULT: TRUE - Agent correctly routed to KPI Reports API")
        else:
            print("❌ RESULT: FALSE - Agent did NOT route to KPI Reports API")
            print("\n   Possible reasons:")
            print("   - Agent used query_database_tool instead")
            print("   - KPI API may not be accessible")
            print("   - Agent's reasoning didn't match KPI report criteria")
        print("="*60)
        
        return is_kpi_routed
        
    except requests.exceptions.ConnectionError:
        print(f"❌ ERROR: Could not connect to agent at {base_url}")
        print("   Is the agent running?")
        return False
    except requests.exceptions.Timeout:
        print("❌ ERROR: Request timed out")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"❌ ERROR: HTTP {e.response.status_code}")
        print(f"   {e.response.text[:500]}")
        return False
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test if agent correctly routes KPI queries to the KPI Reports API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python test_kpi_query.py                         # Test local agent
    python test_kpi_query.py --env prod              # Test production agent
    python test_kpi_query.py -q "kpi report for houston"
    python test_kpi_query.py --verbose               # Show full response
"""
    )
    
    parser.add_argument(
        "--env", "-e",
        choices=["local", "prod", "production"],
        default="local",
        help="Environment to test (default: local)"
    )
    
    parser.add_argument(
        "--url", "-u",
        type=str,
        default=None,
        help="Custom agent URL (overrides --env)"
    )
    
    parser.add_argument(
        "--query", "-q",
        type=str,
        default="provide me a strategic overview of atlanta",
        help="Query to test (default: 'provide me a strategic overview of atlanta')"
    )
    
    parser.add_argument(
        "--api-key", "-k",
        type=str,
        default=None,
        help="API key for authentication"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full response details"
    )
    
    args = parser.parse_args()
    
    # Determine base URL
    if args.url:
        base_url = args.url
    elif args.env in ["prod", "production"]:
        base_url = PROD_URL
    else:
        base_url = LOCAL_URL
    
    # Get API key
    api_key = args.api_key or os.getenv("AZURE_AGENT_API_KEY") or os.getenv("API_KEY")
    
    if args.env in ["prod", "production"] and not api_key:
        print("⚠️  Warning: No API key provided for production environment")
    
    # Run the test
    result = test_kpi_routing(
        query=args.query,
        base_url=base_url,
        api_key=api_key,
        verbose=args.verbose
    )
    
    # Exit with appropriate code
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()

