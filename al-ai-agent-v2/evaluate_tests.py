#!/usr/bin/env python3
"""
Simplified test evaluation script for AI Agent.

Runs test use cases and tracks basic metrics:
- Was SQL generated?
- Were rows returned?
- What was the agent response?
"""
import requests
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Try to load .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Configuration (defaults, can be overridden by command-line args)
LOCAL_URL = "http://localhost:8000"
PROD_URL = "https://app-ai-agent-v2.ambitiousdesert-4823611f.centralus.azurecontainerapps.io"
BASE_URL = os.getenv("API_BASE_URL", LOCAL_URL)
API_KEY = os.getenv("AZURE_AGENT_API_KEY") or os.getenv("API_KEY")
USER_ID = "test_evaluation"
TEST_CASES_FILE = "test_use_cases.json"


def load_test_cases() -> Dict[str, List[str]]:
    """Load test cases from JSON file."""
    with open(TEST_CASES_FILE, 'r') as f:
        return json.load(f)


def query_api(question: str, conversation_id: str = None) -> Dict[str, Any]:
    """
    Query the API with a question.
    
    Args:
        question: The question to ask
        conversation_id: Optional conversation ID for follow-up questions
        
    Returns:
        API response as dictionary
    """
    url = f"{BASE_URL}/api/v1/query"
    
    payload = {
        "query": question,
        "user_id": USER_ID
    }
    
    if conversation_id:
        payload["conversation_id"] = conversation_id
    
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error querying API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Status: {e.response.status_code}")
            print(f"   Body: {e.response.text[:200]}")
        return {
            "error": str(e),
            "final_response": "ERROR",
            "sql_query": "",
            "data_sample": []
        }


def evaluate_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate a single response and extract key metrics.
    
    Args:
        response: API response dictionary
        
    Returns:
        Dictionary with evaluation metrics
    """
    has_error = "error" in response
    has_sql = bool(response.get("sql_query", "").strip())
    
    # Extract actual row count - now exposed in top-level API response
    rows_returned = response.get("rows_returned", 0)
    
    # Fallback to data_sample length if not provided
    if rows_returned == 0:
        data_sample = response.get("data_sample", [])
        if data_sample:
            rows_returned = len(data_sample)
    
    agent_response = response.get("final_response", "")
    execution_time = response.get("metadata", {}).get("execution_time_ms", 0)
    conversation_id = response.get("conversation_id", "")
    
    return {
        "has_error": has_error,
        "has_sql": has_sql,
        "rows_returned": rows_returned,
        "agent_response": agent_response[:200] + "..." if len(agent_response) > 200 else agent_response,
        "full_agent_response": agent_response,
        "sql_query": response.get("sql_query", ""),
        "execution_time_ms": execution_time,
        "conversation_id": conversation_id
    }


def run_test_sequence(query_name: str, questions: List[str]) -> List[Dict[str, Any]]:
    """
    Run a sequence of questions in a conversation.
    
    Args:
        query_name: Name of the test query
        questions: List of questions to ask in sequence
        
    Returns:
        List of evaluation results for each question
    """
    print(f"\n{'='*80}")
    print(f"Testing {query_name}: {len(questions)} question(s)")
    print(f"{'='*80}")
    
    results = []
    conversation_id = None
    
    for i, question in enumerate(questions, 1):
        print(f"\n  [{i}/{len(questions)}] {question}")
        
        response = query_api(question, conversation_id)
        evaluation = evaluate_response(response)
        
        # Update conversation ID for next question
        conversation_id = evaluation["conversation_id"]
        
        # Print quick status
        status_icon = "✅" if not evaluation["has_error"] else "❌"
        sql_icon = "📊" if evaluation["has_sql"] else "⚪"
        rows_icon = f"({evaluation['rows_returned']} rows)" if evaluation["has_sql"] else ""
        
        print(f"      {status_icon} {sql_icon} {rows_icon} {evaluation['execution_time_ms']}ms")
        
        results.append({
            "question": question,
            "evaluation": evaluation
        })
    
    return results


def generate_report(all_results: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    Generate a markdown report of all test results.
    
    Args:
        all_results: Dictionary mapping query names to their results
        
    Returns:
        Markdown report as string
    """
    lines = []
    lines.append("# AI Agent Evaluation Report")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n**Total Test Sequences:** {len(all_results)}")
    
    # Summary statistics
    total_queries = sum(len(results) for results in all_results.values())
    total_errors = sum(1 for results in all_results.values() 
                      for r in results if r["evaluation"]["has_error"])
    total_with_sql = sum(1 for results in all_results.values() 
                        for r in results if r["evaluation"]["has_sql"])
    
    lines.append(f"\n**Total Queries:** {total_queries}")
    lines.append(f"**Success Rate:** {((total_queries - total_errors) / total_queries * 100):.1f}%")
    lines.append(f"**SQL Generated:** {total_with_sql}/{total_queries}")
    
    # Detailed results for each test sequence
    for query_name, results in all_results.items():
        lines.append(f"\n\n## {query_name}")
        lines.append(f"\n**Questions:** {len(results)}")
        
        for i, result in enumerate(results, 1):
            question = result["question"]
            eval_data = result["evaluation"]
            
            lines.append(f"\n### Query {i}: {question}")
            
            # Status
            status = "✅ Success" if not eval_data["has_error"] else "❌ Error"
            lines.append(f"\n**Status:** {status}")
            
            # SQL Query
            if eval_data["has_sql"]:
                lines.append(f"\n**SQL Generated:** ✅ Yes")
                lines.append(f"\n**Rows Returned:** {eval_data['rows_returned']}")
                lines.append(f"\n```sql\n{eval_data['sql_query']}\n```")
            else:
                lines.append(f"\n**SQL Generated:** ⚪ No")
            
            # Agent Response
            lines.append(f"\n**Agent Response:**")
            lines.append(f"\n{eval_data['full_agent_response']}")
            
            # Execution Time
            lines.append(f"\n**Execution Time:** {eval_data['execution_time_ms']}ms")
            
            lines.append("\n---")
    
    return "\n".join(lines)


def main():
    """Main evaluation flow."""
    global BASE_URL
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Run AI Agent evaluation tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test against local API
  python evaluate_tests.py
  
  # Test against production
  python evaluate_tests.py --prod
  
  # Test against custom URL
  python evaluate_tests.py --url https://custom-url.com
        """
    )
    
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Run tests against production API"
    )
    
    parser.add_argument(
        "--url",
        type=str,
        help="Custom API base URL (overrides --prod)"
    )
    
    args = parser.parse_args()
    
    # Set BASE_URL based on arguments
    if args.url:
        BASE_URL = args.url
    elif args.prod:
        BASE_URL = PROD_URL
    
    env_name = "PRODUCTION" if BASE_URL == PROD_URL else ("CUSTOM" if args.url else "LOCAL")
    
    print("=" * 80)
    print("AI Agent Evaluation Suite")
    print("=" * 80)
    print(f"Environment: {env_name}")
    print(f"Base URL: {BASE_URL}")
    print(f"Test Cases: {TEST_CASES_FILE}")
    
    # Load test cases
    try:
        test_cases = load_test_cases()
        print(f"Loaded {len(test_cases)} test sequence(s)")
    except FileNotFoundError:
        print(f"❌ Error: {TEST_CASES_FILE} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing {TEST_CASES_FILE}: {e}")
        sys.exit(1)
    
    # Run all test sequences
    all_results = {}
    for query_name, questions in test_cases.items():
        results = run_test_sequence(query_name, questions)
        all_results[query_name] = results
    
    # Generate and save report
    print(f"\n{'='*80}")
    print("Generating Report...")
    print(f"{'='*80}")
    
    report = generate_report(all_results)
    output_file = f"evaluation_results_{env_name.lower()}.md"
    
    with open(output_file, 'w') as f:
        f.write(report)
    
    print(f"\n✅ Report saved to: {output_file}")
    
    # Print summary
    total_queries = sum(len(results) for results in all_results.values())
    total_errors = sum(1 for results in all_results.values() 
                      for r in results if r["evaluation"]["has_error"])
    
    print(f"\n{'='*80}")
    print("EVALUATION COMPLETE")
    print(f"{'='*80}")
    print(f"Environment: {env_name}")
    print(f"Total Queries: {total_queries}")
    print(f"Errors: {total_errors}")
    print(f"Success Rate: {((total_queries - total_errors) / total_queries * 100):.1f}%")
    
    # Exit with error code if any tests failed
    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()

