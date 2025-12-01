"""
Semantic Router for query classification.

Modern LLM-based routing with tiered approach:
1. Fast keyword matching (no LLM call needed)
2. LLM classification for ambiguous queries

This follows 2025 best practices for agent routing.
"""

import time
from typing import Dict, Any, Literal, List


class SemanticRouter:
    """
    Modern LLM-based semantic router for query classification.
    Uses a tiered approach: fast keywords → LLM classification.
    """
    
    # High-confidence keyword triggers for KPI reports (no LLM call needed)
    KPI_KEYWORDS: List[str] = [
        "strategic overview",
        "portfolio analysis", 
        "portfolio health",
        "kpi report",
        "performance report",
        "generate report",
        "critical analysis",
        "top performers",
        "operational focus",
        "underperforming",
        "portfolio summary",
        "performance overview",
        "property scorecard",
        "regional analysis",
        "office analysis",
    ]
    
    # High-confidence keyword triggers for database queries
    QUERY_KEYWORDS: List[str] = [
        "how many",
        "list all",
        "show me all", 
        "count",
        "what is the",
        "tell me about",
        "properties in",
        "average",
        "total",
        "properties lost",
        "properties gained",
        "specific property",
        "property details",
    ]
    
    def __init__(self, llm_service):
        """
        Initialize the router with an LLM service.
        
        Args:
            llm_service: LLMService instance for classification
        """
        self.llm_service = llm_service
        
    def route(self, query: str) -> Dict[str, Any]:
        """
        Route a query to the appropriate agent.
        
        Uses tiered classification:
        1. Keyword matching (instant, free)
        2. LLM classification (200-500ms, costs tokens)
        
        Args:
            query: User's natural language query
            
        Returns:
            {
                "route": "kpi" | "query",
                "confidence": float (0.0-1.0),
                "method": "keyword" | "llm",
                "matched_keyword": str (if keyword match),
                "reasoning": str (if LLM classification),
                "latency_ms": int
            }
        """
        start = time.time()
        query_lower = query.lower().strip()
        
        # Tier 1: Fast keyword matching for KPI routes (highest priority)
        for kw in self.KPI_KEYWORDS:
            if kw in query_lower:
                return {
                    "route": "kpi",
                    "confidence": 0.95,
                    "method": "keyword",
                    "matched_keyword": kw,
                    "latency_ms": int((time.time() - start) * 1000)
                }
        
        # Tier 1b: Check for strong query indicators
        strong_query_indicators = ["how many", "list all", "count of", "show all", "what is the occupancy", "what is the average"]
        for kw in strong_query_indicators:
            if kw in query_lower:
                return {
                    "route": "query",
                    "confidence": 0.9,
                    "method": "keyword",
                    "matched_keyword": kw,
                    "latency_ms": int((time.time() - start) * 1000)
                }
        
        # Tier 2: LLM classification for ambiguous queries
        return self._llm_classify(query, start)
    
    def _llm_classify(self, query: str, start_time: float) -> Dict[str, Any]:
        """
        Use LLM for semantic classification when keywords don't match.
        
        Args:
            query: User's query
            start_time: Start timestamp for latency calculation
            
        Returns:
            Classification result with route, confidence, reasoning
        """
        
        prompt = f"""Classify this user query into exactly ONE category.

Query: "{query}"

Categories:
- "kpi": User wants a comprehensive report, strategic analysis, portfolio overview, 
  performance summary, or any formatted document/PDF output.
  Examples: 
    - "give me an overview of Dallas"
    - "analyze portfolio health for Houston"
    - "what's the performance summary for Atlanta"
    - "show me underperforming properties"
    - "generate a report for the Denver office"

- "query": User wants specific data points, counts, lists, filters, raw data,
  or answers to specific factual questions.
  Examples:
    - "how many properties are in Denver"
    - "list properties lost in September 2025"
    - "what is the occupancy rate for Continental Tower"
    - "show me all properties in the Dallas office"
    - "what was the loss reason for XYZ property"

Key distinction:
- KPI = comprehensive analysis, trends, insights, formatted reports
- Query = specific data, counts, lists, property details

Respond with JSON only:
{{"route": "kpi" or "query", "confidence": 0.0-1.0, "reasoning": "one sentence explanation"}}"""
        
        try:
            response = self.llm_service.generate_structured(
                [
                    {"role": "system", "content": "You are a query classifier. Respond only with the JSON format requested."},
                    {"role": "user", "content": prompt}
                ],
                response_format={
                    "type": "object",
                    "properties": {
                        "route": {"type": "string", "enum": ["kpi", "query"]},
                        "confidence": {"type": "number"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["route", "confidence", "reasoning"]
                },
                temperature=0
            )
            
            route = response.get("route", "query")
            confidence = response.get("confidence", 0.5)
            reasoning = response.get("reasoning", "")
            
            return {
                "route": route,
                "confidence": confidence,
                "method": "llm",
                "reasoning": reasoning,
                "latency_ms": int((time.time() - start_time) * 1000)
            }
            
        except Exception as e:
            # Fallback to query on error (safer default)
            return {
                "route": "query",
                "confidence": 0.3,
                "method": "llm_error",
                "error": str(e),
                "latency_ms": int((time.time() - start_time) * 1000)
            }
    
    def explain_route(self, result: Dict[str, Any]) -> str:
        """
        Generate a human-readable explanation of the routing decision.
        
        Args:
            result: Output from route() method
            
        Returns:
            Human-readable explanation string
        """
        route = result.get("route", "unknown")
        method = result.get("method", "unknown")
        confidence = result.get("confidence", 0)
        
        if method == "keyword":
            keyword = result.get("matched_keyword", "")
            return f"Routed to {route.upper()} agent (keyword match: '{keyword}', confidence: {confidence:.0%})"
        elif method == "llm":
            reasoning = result.get("reasoning", "")
            return f"Routed to {route.upper()} agent (LLM classification, confidence: {confidence:.0%}): {reasoning}"
        elif method == "llm_error":
            return f"Routed to {route.upper()} agent (fallback due to error: {result.get('error', 'unknown')})"
        else:
            return f"Routed to {route.upper()} agent (method: {method})"

