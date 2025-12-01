#!/usr/bin/env python3
"""
Test script to verify semantic routing works correctly.

Run with: python test_routing.py

This tests the SemanticRouter directly without needing the full agent.
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.agent.semantic_router import SemanticRouter
from app.services.llm_service import LLMService


def test_routing():
    """Test the semantic router with various queries."""
    
    print("=" * 70)
    print("SEMANTIC ROUTER TEST")
    print("=" * 70)
    
    # Initialize router
    llm_service = LLMService()
    router = SemanticRouter(llm_service)
    
    # Test cases: (query, expected_route)
    test_cases = [
        # KPI queries (should route to "kpi")
        ("Give me a strategic overview of Dallas", "kpi"),
        ("Generate a portfolio analysis for Houston", "kpi"),
        ("What's the portfolio health for Atlanta?", "kpi"),
        ("Show me the critical analysis for Denver", "kpi"),
        ("I need a performance report for San Antonio", "kpi"),
        ("Generate a KPI report for the West region", "kpi"),
        
        # Query database queries (should route to "query")
        ("How many properties are in Dallas?", "query"),
        ("What is the occupancy for Continental Tower?", "query"),
        ("List all properties lost in September 2025", "query"),
        ("What is the average occupancy in Denver?", "query"),
        ("Tell me about the Denver portfolio", "query"),  # This is ambiguous
        ("Show me properties with occupancy below 80%", "query"),
    ]
    
    print("\nRunning routing tests...\n")
    
    passed = 0
    failed = 0
    
    for query, expected in test_cases:
        result = router.route(query)
        actual = result["route"]
        confidence = result["confidence"]
        method = result["method"]
        
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} Query: \"{query[:50]}...\"" if len(query) > 50 else f"{status} Query: \"{query}\"")
        print(f"   Expected: {expected} | Actual: {actual} | Confidence: {confidence:.2f} | Method: {method}")
        
        if result.get("reasoning"):
            print(f"   Reasoning: {result['reasoning']}")
        if result.get("matched_keyword"):
            print(f"   Keyword: {result['matched_keyword']}")
        print()
    
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("=" * 70)
    
    return failed == 0


def test_keyword_only():
    """Test keyword matching without LLM (faster, no API calls)."""
    
    print("\n" + "=" * 70)
    print("KEYWORD-ONLY ROUTING TEST (No LLM calls)")
    print("=" * 70)
    
    # Create router with a mock LLM service
    class MockLLMService:
        def generate_structured(self, *args, **kwargs):
            # Should not be called for keyword matches
            raise Exception("LLM should not be called for keyword matches!")
    
    router = SemanticRouter(MockLLMService())
    
    # These should all match keywords (no LLM needed)
    keyword_test_cases = [
        ("Give me a strategic overview of Dallas", "kpi", "strategic overview"),
        ("portfolio analysis for Houston", "kpi", "portfolio analysis"),
        ("Show me the critical analysis", "kpi", "critical analysis"),
        ("How many properties in Denver?", "query", "how many"),
        ("list all properties", "query", "list all"),
    ]
    
    print("\nTesting keyword matching...\n")
    
    for query, expected_route, expected_keyword in keyword_test_cases:
        result = router.route(query)
        
        assert result["method"] == "keyword", f"Expected keyword method, got {result['method']}"
        assert result["route"] == expected_route, f"Expected {expected_route}, got {result['route']}"
        
        print(f"✅ \"{query}\" → {result['route']} (keyword: {result.get('matched_keyword')})")
    
    print("\n✅ All keyword tests passed!")
    return True


if __name__ == "__main__":
    print("\n🧪 Testing Semantic Router\n")
    
    # First test keyword matching (no API calls)
    try:
        test_keyword_only()
    except AssertionError as e:
        print(f"\n❌ Keyword test failed: {e}")
        sys.exit(1)
    
    # Then test full routing (requires API key)
    if os.getenv("OPEN_ROUTER_KEY"):
        try:
            success = test_routing()
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"\n❌ Routing test failed: {e}")
            sys.exit(1)
    else:
        print("\n⚠️  Skipping LLM routing tests (OPEN_ROUTER_KEY not set)")
        print("   Set OPEN_ROUTER_KEY to test LLM-based classification")

