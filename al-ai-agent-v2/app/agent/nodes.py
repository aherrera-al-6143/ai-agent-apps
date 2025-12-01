"""
Individual workflow nodes for the agent.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.state import AgentState
from app.services.vector_service import VectorService
from app.services.qdrant_service import QdrantService
from app.services.domo_service import DomoService
from app.services.llm_service import LLMService
from app.services.cache_service import CacheService


def _format_column_for_sql(col: Dict[str, Any]) -> str:
    """
    Format a single column with all available metadata fields and smart truncation.
    Used for SQL generation prompts.
    """
    col_name = col.get("name", "")
    col_type = col.get("type", "")
    category = col.get("category", "")
    description = col.get("description", "")
    business_meaning = col.get("business_meaning", "")
    examples = col.get("examples", [])
    definitions = col.get("definitions", [])
    business_rules = col.get("business_rules", "")
    data_quality_notes = col.get("data_quality_notes", "")

    parts = [f"{col_name} ({col_type})"]

    if category:
        parts.append(f"category: {category}")
    if description:
        desc_text = description[:147] + "..." if len(description) > 150 else description
        parts.append(f"Description: {desc_text}")
    if business_meaning and business_meaning != description:
        meaning_text = business_meaning[:147] + "..." if len(business_meaning) > 150 else business_meaning
        parts.append(f"Business meaning: {meaning_text}")

    if examples and isinstance(examples, list):
        examples_list = examples[:15]
        examples_str = ", ".join(str(ex) for ex in examples_list)
        if len(examples) > 15:
            examples_str += f" (and {len(examples) - 15} more)"
        parts.append(f"Examples: {examples_str}")

    if definitions and isinstance(definitions, list) and definitions:
        def_parts = []
        for def_item in definitions[:5]:
            if isinstance(def_item, dict):
                value = def_item.get("value", "")
                meaning = def_item.get("meaning", "")
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

    if business_rules and business_rules.strip():
        rules_text = business_rules[:197] + "..." if len(business_rules) > 200 else business_rules
        parts.append(f"Business rules: {rules_text}")

    if data_quality_notes and data_quality_notes.strip():
        parts.append(f"Data quality: {data_quality_notes}")

    return ". ".join(parts)


def _sanitize_sql_column_names(sql_query: str, column_names: List[str], table_name: Optional[str] = None) -> str:
    """
    Wrap column names and table names that contain special characters in double quotes for Domo SQL.
    Domo SQL uses double quotes for identifiers, not backticks.
    """
    if not sql_query:
        return sql_query

    sanitized_query = sql_query
    
    # Sanitize table name if provided
    if table_name and re.search(r"[^A-Za-z0-9_]", table_name):
        escaped_table = re.escape(table_name)
        # Replace backtick-wrapped table names with double quotes
        backtick_table_pattern = re.compile(rf"`({escaped_table})`")
        sanitized_query = backtick_table_pattern.sub(r'"\1"', sanitized_query)
        # Wrap unquoted table names
        unquoted_table_pattern = re.compile(rf"(?<!`)(?<!\")(?<![A-Za-z0-9_])({escaped_table})(?!`)(?!\")")
        sanitized_query = unquoted_table_pattern.sub(r'"\1"', sanitized_query)
    
    # Sanitize column names
    if column_names:
        for column_name in column_names:
            if not column_name:
                continue

            # Only wrap names that include characters beyond alphanumerics/underscore
            if not re.search(r"[^A-Za-z0-9_]", column_name):
                continue

            # Escape special regex characters in column name
            escaped_name = re.escape(column_name)
            
            # First, replace any backtick-wrapped instances with double quotes
            backtick_pattern = re.compile(rf"`({escaped_name})`")
            sanitized_query = backtick_pattern.sub(r'"\1"', sanitized_query)
            
            # Then, wrap any unquoted occurrences (not in backticks or double quotes)
            unquoted_pattern = re.compile(rf"(?<!`)(?<!\")(?<![A-Za-z0-9_])({escaped_name})(?!`)(?!\")")
            sanitized_query = unquoted_pattern.sub(r'"\1"', sanitized_query)

    return sanitized_query


def _messages_to_dict(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    """Convert LangChain messages into dicts compatible with the LLM service."""
    role_map = {
        "human": "user",
        "user": "user",
        "ai": "assistant",
        "assistant": "assistant",
        "system": "system"
    }
    formatted: List[Dict[str, str]] = []
    for message in messages:
        role = role_map.get(message.type, "user")
        formatted.append({"role": role, "content": str(message.content)})
    return formatted


def _format_recent_conversation(messages: List[BaseMessage], limit: int = 4) -> str:
    """Create a readable snippet of recent conversation turns."""
    if not messages:
        return ""
    recent = messages[-limit:]
    lines: List[str] = []
    for msg in recent:
        if isinstance(msg, AIMessage):
            speaker = "Assistant"
        elif isinstance(msg, HumanMessage):
            speaker = "User"
        else:
            speaker = msg.type.title()
        lines.append(f"{speaker}: {msg.content}")
    return "\n".join(lines)


def _is_follow_up(messages: List[BaseMessage]) -> bool:
    """Simple heuristic to detect follow-up questions."""
    if len(messages) < 2:
        return False
    return isinstance(messages[-1], HumanMessage) and isinstance(messages[-2], AIMessage)


def _should_reuse_previous_dataset(query: str, previous_dataset_id: Optional[str]) -> bool:
    """Check if query is asking for more results from the same dataset."""
    if not previous_dataset_id:
        return False
    
    query_lower = query.lower().strip()
    # Patterns that indicate "show me more" type queries
    more_patterns = [
        "show me more",
        "show more",
        "get more",
        "more results",
        "more data",
        "more of those",
        "more from that",
        "more from the same",
        "what else",
        "any more",
        "are there more",
        "give me more"
    ]
    
    return any(pattern in query_lower for pattern in more_patterns)


def _build_final_response(
    llm_service: LLMService,
    state: AgentState,
    query_results: Dict[str, Any]
) -> str:
    """Generate a natural language response using the LLM."""
    rows = query_results.get("rows", [])
    total_rows = query_results.get("total_rows", len(rows))
    
    # For "show more" queries, show more rows
    previous_dataset_id = state.get("previous_dataset_id")
    intent = state.get("query_intent") or {}
    is_show_more = intent.get("is_pagination_request", False)
    
    # Extract requested number from query (e.g., "5 properties")
    import re
    query = state.get("query", "")
    requested_number = None
    if not is_show_more:
        number_match = re.search(r'\b(\d+)\s+(?:properties|results|items|rows|records)', query.lower())
        if number_match:
            requested_number = int(number_match.group(1))
    
    if rows:
        # Send ALL rows to LLM for full context - no truncation
        # This ensures the LLM has complete data to answer questions accurately
        # Modern LLMs can handle large contexts, and accuracy is more important than token cost
        sample_data = "\n".join([str(row) for row in rows])
        
        # Add summary info if there are many rows
        if len(rows) > 100:
            sample_data = f"Total rows: {len(rows)}\n\n" + sample_data
    else:
        sample_data = "No data returned"

    prompt = f"""Based on the SQL query results, provide a clear, natural language answer to the user's question.

User Query: {state["query"]}

SQL Query: {state.get("sql_query", "")}

Query Results (ALL {query_results.get('row_count', 0)} rows - full dataset):
{sample_data}

Provide a clear, concise response that directly answers the user's question. Include specific numbers and insights from the data. You have access to the complete dataset, so you can compute accurate counts, averages, summaries, and groupings."""
    if is_show_more:
        prompt += "\n\nNote: The user is asking for MORE results. Show additional examples beyond what was shown previously."

    conversation_messages: List[BaseMessage] = state.get("messages", [])
    history_dicts = _messages_to_dict(conversation_messages[:-1][-5:]) if conversation_messages else []
    prompt_messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": "You are a helpful data analyst assistant. Provide clear, accurate answers based on query results."
        }
    ]
    if history_dicts:
        prompt_messages.extend(history_dicts)

    prompt_messages.append({"role": "user", "content": prompt})

    # Get model from agent config
    model = state.get("agent_config", {}).get("model")

    # High token limit for verbose, comprehensive responses
    return llm_service.generate(prompt_messages, temperature=0.1, max_tokens=10000, model=model)


def _normalize_search_results(results: List[Any]) -> List[Dict[str, Any]]:
    """Convert Qdrant search results into JSON-serializable dictionaries."""
    normalized: List[Dict[str, Any]] = []
    for result in results:
        if isinstance(result, dict):
            payload = result.get("payload", {})
            normalized.append({
                "id": str(result.get("id", "")),
                "score": float(result.get("score", 0.0)),
                "payload": payload or {}
            })
        else:
            payload = getattr(result, "payload", {}) or {}
            normalized.append({
                "id": str(getattr(result, "id", "")),
                "score": float(getattr(result, "score", 0.0)),
                "payload": payload
            })
    return normalized


def _validate_column_coverage(
    intent: Dict[str, Any],
    columns: List[Dict[str, Any]],
    vector_service: VectorService,
    qdrant_service: QdrantService,
    query: str
) -> Dict[str, Any]:
    """
    Validate that we have all necessary column types for the query intent.
    Returns validation result with missing types and expansion attempts.
    """
    validation_result = {
        "complete": True,
        "missing_types": [],
        "found_metrics": [],
        "found_dimensions": [],
        "found_temporal": [],
        "expanded": False
    }
    
    # Extract column names and check what we have
    column_names = [col.get("name", "").lower() for col in columns if col.get("name")]
    column_descriptions = " ".join([
        col.get("description", "").lower() + " " + col.get("name", "").lower()
        for col in columns if col.get("name")
    ])
    
    # Check for metrics
    if intent.get("metrics_needed"):
        has_metric = any(
            any(metric_term in name or metric_term in column_descriptions 
                for metric_term in intent["metrics_needed"])
            for name in column_names
        )
        if not has_metric:
            validation_result["missing_types"].append("metric")
            validation_result["complete"] = False
        else:
            validation_result["found_metrics"] = [
                col.get("name") for col in columns
                if any(metric_term in col.get("name", "").lower() or 
                       metric_term in col.get("description", "").lower()
                       for metric_term in intent["metrics_needed"])
            ]
    
    # Check for dimensions
    if intent.get("dimensions_needed"):
        has_dimension = any(
            any(dim_term in name or dim_term in column_descriptions
                for dim_term in intent["dimensions_needed"])
            for name in column_names
        )
        if not has_dimension:
            validation_result["missing_types"].append("dimension")
            validation_result["complete"] = False
        else:
            validation_result["found_dimensions"] = [
                col.get("name") for col in columns
                if any(dim_term in col.get("name", "").lower() or
                       dim_term in col.get("description", "").lower()
                       for dim_term in intent["dimensions_needed"])
            ]
    
    # Check for temporal
    if intent.get("temporal_needed"):
        temporal_keywords = ["date", "time", "year", "month", "day", "timestamp"]
        has_temporal = any(
            any(keyword in name for keyword in temporal_keywords)
            for name in column_names
        )
        if not has_temporal:
            validation_result["missing_types"].append("temporal")
            validation_result["complete"] = False
        else:
            validation_result["found_temporal"] = [
                col.get("name") for col in columns
                if any(keyword in col.get("name", "").lower() for keyword in temporal_keywords)
            ]
    
    # Try expansion if missing
    if not validation_result["complete"]:
        expanded_results = []
        # Track existing column names to avoid duplicates
        existing_column_names = {col.get("name", "").lower() for col in columns if col.get("name")}
        
        # Expand search for missing types
        if "dimension" in validation_result["missing_types"]:
            dim_query = " ".join(intent.get("dimensions_needed", [])) + " location city market geography"
            dim_embedding = vector_service.create_embedding(dim_query)
            dim_results = qdrant_service.search_columns(
                query_vector=dim_embedding,
                query_text=dim_query,
                limit=20
            )
            for result in _normalize_search_results(dim_results):
                payload = result.get("payload", {})
                col_name = (payload.get("column_name") or payload.get("full_metadata", {}).get("name", "")).lower()
                if col_name and col_name not in existing_column_names:
                    expanded_results.append(result)
                    existing_column_names.add(col_name)
        
        if "metric" in validation_result["missing_types"]:
            metric_query = " ".join(intent.get("metrics_needed", [])) + " percentage rate"
            metric_embedding = vector_service.create_embedding(metric_query)
            metric_results = qdrant_service.search_columns(
                query_vector=metric_embedding,
                query_text=metric_query,
                limit=20
            )
            for result in _normalize_search_results(metric_results):
                payload = result.get("payload", {})
                col_name = (payload.get("column_name") or payload.get("full_metadata", {}).get("name", "")).lower()
                if col_name and col_name not in existing_column_names:
                    expanded_results.append(result)
                    existing_column_names.add(col_name)
        
        if expanded_results:
            validation_result["expanded"] = True
            validation_result["expanded_results"] = expanded_results
    
    return validation_result


def _multi_faceted_column_search(
    vector_service: VectorService,
    qdrant_service: QdrantService,
    query: str,
    intent: Dict[str, Any],
    base_limit: int = 15
) -> List[Dict[str, Any]]:
    """
    Perform multi-faceted column search based on query intent.
    
    Searches separately for metrics, dimensions, and temporal columns,
    then merges and deduplicates results.
    """
    all_results: Dict[str, Dict[str, Any]] = {}  # id -> result (for deduplication)
    
    # Search for metrics if needed
    if intent.get("metrics_needed"):
        metrics_query = " ".join(intent["metrics_needed"]) + " percentage rate measurement"
        metrics_embedding = vector_service.create_embedding(metrics_query)
        metrics_results = qdrant_service.search_columns(
            query_vector=metrics_embedding,
            query_text=metrics_query,
            limit=base_limit
        )
        for result in _normalize_search_results(metrics_results):
            result_id = result["id"]
            if result_id not in all_results or result["score"] > all_results[result_id]["score"]:
                all_results[result_id] = result
    
    # Search for dimensions if needed
    if intent.get("dimensions_needed"):
        dimensions_query = " ".join(intent["dimensions_needed"]) + " category filter group geography location"
        dimensions_embedding = vector_service.create_embedding(dimensions_query)
        dimensions_results = qdrant_service.search_columns(
            query_vector=dimensions_embedding,
            query_text=dimensions_query,
            limit=base_limit
        )
        for result in _normalize_search_results(dimensions_results):
            result_id = result["id"]
            if result_id not in all_results or result["score"] > all_results[result_id]["score"]:
                all_results[result_id] = result
    
    # Search for temporal columns if needed
    if intent.get("temporal_needed"):
        temporal_query = "date time period year month day timestamp"
        temporal_embedding = vector_service.create_embedding(temporal_query)
        temporal_results = qdrant_service.search_columns(
            query_vector=temporal_embedding,
            query_text=temporal_query,
            limit=base_limit // 2  # Fewer temporal columns typically needed
        )
        for result in _normalize_search_results(temporal_results):
            result_id = result["id"]
            if result_id not in all_results or result["score"] > all_results[result_id]["score"]:
                all_results[result_id] = result
    
    # Fallback: if no intent or intent is empty, do a general search
    if not all_results:
        general_embedding = vector_service.create_embedding(query)
        general_results = qdrant_service.search_columns(
            query_vector=general_embedding,
            query_text=query,
            limit=base_limit * 2
        )
        for result in _normalize_search_results(general_results):
            result_id = result["id"]
            if result_id not in all_results:
                all_results[result_id] = result
    
    # Return as list, sorted by score
    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)


def _select_columns_with_llm(
    intent: Dict[str, Any],
    all_columns: List[Dict[str, Any]],
    query: str,
    dataset_name: str,
    llm_service: LLMService,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Use LLM to select relevant columns and map intent filters to specific columns.
    
    Args:
        intent: Query intent with filters, metrics_needed, dimensions_needed
        all_columns: All columns from the selected dataset
        query: Original user query
        dataset_name: Name of the selected dataset
        llm_service: LLM service instance
        model: Optional model override
        
    Returns:
        Dict with selected_columns (list of column names) and filter_mappings (list of mappings)
    """
    # Format all columns for the prompt with full YAML metadata
    columns_text = "\n".join(
        f"{i+1}. {_format_column_for_sql(col)}"
        for i, col in enumerate(all_columns)
    )
    
    # Format intent filters
    filters_text = ""
    if intent.get("filters"):
        filters_text = "\n".join(
            f"- {f.get('concept', f.get('type', ''))}: {f.get('value', '')}"
            for f in intent["filters"]
        )
    
    metrics_text = ", ".join(intent.get("metrics_needed", [])) if intent.get("metrics_needed") else "None"
    dimensions_text = ", ".join(intent.get("dimensions_needed", [])) if intent.get("dimensions_needed") else "None"
    
    prompt = f"""You are a SQL query assistant. Given a user query and intent, select the relevant columns from the dataset and map filters to specific columns.

User Query: "{query}"

Dataset: {dataset_name}

Query Intent:
- Metrics needed: {metrics_text}
- Dimensions needed: {dimensions_text}
- Filters: {filters_text if filters_text else "None"}

Available Columns (all {len(all_columns)} columns from this dataset):
Each column entry includes:
- Column name and data type
- Category (if available)
- Description and business meaning
- Examples: List of valid values (CRITICAL for validation)
- Definitions: Detailed explanations of example values
- Business rules: Specific rules about how to use this column
- Data quality notes: Information about data completeness

{columns_text}

Your task:
1. ALWAYS select columns needed to answer the query. Even if no explicit metrics or dimensions are requested, you MUST select relevant columns to answer the query.
   - For general "about" queries (e.g., "Tell me about the Denver portfolio"), select descriptive/dimension columns that provide information about the subject
   - For portfolio queries, select portfolio-related columns, property information, and location columns
   - For queries asking "what" or "which", select columns that identify and describe the entities
   - You MUST select at least one column - never return an empty selected_columns list
2. For each filter in the intent, identify the CORRECT column to use by following these steps:
   a. Find candidate columns that semantically match the filter concept
   b. CHECK THE EXAMPLES LIST: If a column has examples listed, the filter value MUST match one of those examples (case-insensitive partial match). If it doesn't match, that column is WRONG.
   c. For temporal queries (e.g., "properties lost in September 2025"), prefer DATE/TIMESTAMP columns over STRING reason/type columns
   d. Consider business_rules, business_meaning, and definitions when making final selection
   e. Pay special attention to:
      - Property name filters should use "record_property_name" (NOT "record_new_property_address")
      - Location/city filters should use appropriate location columns
      - Date filters should use DATE/TIMESTAMP columns, not STRING columns with date-like names
      - For queries about "properties that were lost" or "lost properties", use "record_pending_loss_date" (NOT "record_termination_date")
      - "record_termination_date" is for termination events, "record_pending_loss_date" is for loss events

CRITICAL VALIDATION RULES:
- If a column has examples listed (e.g., Examples: [Other, Sale, Property Operations]), the filter value MUST be in that list (case-insensitive partial match)
- If the filter value is NOT in the examples list, DO NOT use that column - it is the wrong column
- For queries about "when" something happened (e.g., "properties lost in September 2025"), use DATE columns, not STRING reason/type columns
- Example: If a column has examples [Other, Sale, Property Operations] and your filter value is "lost", that column is WRONG because "lost" is not in the examples

Respond with JSON:
{{
    "selected_columns": ["column_name1", "column_name2", ...],
    "filter_mappings": [
        {{"concept": "property_name", "column": "record_property_name", "value": "Continental Tower"}},
        {{"concept": "city", "column": "record_new_property_address__city", "value": "Denver"}}
    ],
    "reasoning": "Brief explanation of column selections and filter mappings, including validation against examples"
}}

IMPORTANT:
- Use the EXACT column names as shown in the list above
- For property name searches, ALWAYS use "record_property_name" (not address columns)
- Include all columns needed for metrics, dimensions, and filters
- VALIDATE: Before mapping a filter to a column, verify the filter value matches the column's examples (if examples are provided)
- For temporal queries, prefer DATE/TIMESTAMP columns over STRING columns
- CRITICAL: You MUST select at least one column. If the query asks "about" something or asks "what/which", select descriptive columns that provide information about that subject
- For portfolio queries, select property-related columns, location columns, and any portfolio identifier columns
- Never return an empty selected_columns list - always select relevant columns to answer the query"""

    messages = [
        {
            "role": "system",
            "content": "You are a SQL expert. Select columns and map filters based on semantic understanding of column purposes, business rules, and examples. Always prefer property name columns over address columns for property name filters."
        },
        {"role": "user", "content": prompt}
    ]
    
    response_format = {
        "type": "object",
        "properties": {
            "selected_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of column names to use in the SQL query"
            },
            "filter_mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string"},
                        "column": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["concept", "column", "value"]
                },
                "description": "Mappings from intent filters to specific columns"
            },
            "reasoning": {"type": "string"}
        },
        "required": ["selected_columns", "filter_mappings", "reasoning"]
    }
    
    result = llm_service.generate_structured(messages, response_format, model=model)
    
    # Filter selected_columns to only include columns that actually exist
    valid_column_names = {col.get("name") for col in all_columns if col.get("name")}
    selected_columns = [col for col in result.get("selected_columns", []) if col in valid_column_names]
    
    # Build filter mappings with validation
    filter_mappings = []
    for mapping in result.get("filter_mappings", []):
        col_name = mapping.get("column")
        if col_name and col_name in valid_column_names:
            filter_mappings.append(mapping)
    
    return {
        "selected_columns": selected_columns,
        "filter_mappings": filter_mappings,
        "reasoning": result.get("reasoning", "")
    }


# Initialize services (singleton pattern)
_vector_service: Optional[VectorService] = None
_qdrant_service: Optional[QdrantService] = None
_domo_service: Optional[DomoService] = None
_llm_service: Optional[LLMService] = None
_cache_service: Optional[CacheService] = None


def get_services():
    """Get or initialize service instances."""
    global _vector_service, _qdrant_service, _domo_service, _llm_service, _cache_service

    if _vector_service is None:
        _vector_service = VectorService()
    if _qdrant_service is None:
        _qdrant_service = QdrantService()
    if _domo_service is None:
        _domo_service = DomoService()
    if _llm_service is None:
        _llm_service = LLMService()
    if _cache_service is None:
        _cache_service = CacheService()

    return _vector_service, _qdrant_service, _domo_service, _llm_service, _cache_service


def analyze_query_intent_node(state: AgentState) -> Dict[str, Any]:
    """Analyze query to extract structured intent (metrics, dimensions, filters, aggregations)."""
    start_time = time.time()
    
    try:
        _, _, _, llm_service, _ = get_services()
        query = state.get("query", "")
        
        if not query:
            raise ValueError("Query is required for intent analysis")
        
        # Get conversation history from LangGraph's built-in message state
        conversation_messages: List[BaseMessage] = state.get("messages", [])
        conversation_summary = state.get("conversation_summary")
        conversation_context = ""
        
        # Use summary if available, otherwise use recent messages
        if conversation_summary:
            conversation_context = f"[Conversation Summary]: {conversation_summary}"
            # Also include last 2-3 recent messages for immediate context
            if len(conversation_messages) > 1:
                recent_messages = conversation_messages[:-1][-2:]  # Last 2 messages before current
                recent_context = _format_recent_conversation(recent_messages)
                if recent_context:
                    conversation_context += f"\n\nRecent Messages:\n{recent_context}"
        elif len(conversation_messages) > 1:
            # Get recent conversation history (excluding current query)
            recent_messages = conversation_messages[:-1][-4:]  # Last 4 messages before current
            conversation_context = _format_recent_conversation(recent_messages)
        
        # Get previous query context if available
        previous_sql = state.get("previous_sql")
        previous_dataset_id = state.get("previous_dataset_id")
        
        context_section = ""
        if conversation_context:
            context_section = f"\n\nConversation History:\n{conversation_context}"
        if previous_sql:
            context_section += f"\n\nPrevious SQL Query:\n{previous_sql}"
        
        prompt = f"""Analyze the following natural language query and extract its structured requirements for SQL generation.

Current Query: "{query}"{context_section}

First, determine if this is a continuation of the previous conversation:
- Is the user asking for MORE results from the same query? (e.g., "show me more", "next page", "more results")
- Is the user refining/modifying the previous query? (e.g., "filter that to Houston", "what about last year?")
- Is this a completely new query?

Then extract:
1. What metric(s) or measurement(s) are needed (e.g., occupancy, revenue, count) - these help identify which columns to select
2. What dimension(s) or categorical columns are needed for filtering/grouping (e.g., location, city, date, property)
3. What specific filter values are mentioned (e.g., "Denver" → location filter, "2024" → date filter)

Note: Do NOT extract aggregation functions. The system will fetch raw data and compute aggregations in the response layer.

Respond with JSON:
{{
    "is_continuation": true/false,
    "is_pagination_request": true/false,
    "continuation_type": "pagination" | "refinement" | "clarification" | "new_query",
    "metrics_needed": ["list of metric concepts like 'occupancy', 'revenue'"],
    "dimensions_needed": ["list of dimension concepts like 'location', 'city', 'date'"],
    "filters": [
        {{"type": "location", "value": "Denver", "concept": "city"}},
        {{"type": "date", "value": "2024", "concept": "year"}}
    ],
    "aggregations": [],
    "temporal_needed": true/false
}}

Important:
- If this is a pagination request (e.g., "show me more"), set is_pagination_request=true and continuation_type="pagination"
- If this is a refinement (e.g., "filter that to Houston"), set is_continuation=true and continuation_type="refinement"
- If this is a new query, set is_continuation=false and continuation_type="new_query"
- Be specific about what types of columns are needed
- Extract actual filter values mentioned in the query
- If no specific values are mentioned, leave filters empty
- ALWAYS set "aggregations" to an empty array [] - aggregations are computed in the response layer, not in SQL"""

        messages = [
            {
                "role": "system",
                "content": "You are a SQL query analyst. Analyze natural language queries to extract structured requirements for column discovery and SQL generation. You understand conversation context and can identify when queries are continuations, pagination requests, or refinements of previous queries."
            },
            {"role": "user", "content": prompt}
        ]
        
        response_format = {
            "type": "object",
            "properties": {
                "is_continuation": {"type": "boolean"},
                "is_pagination_request": {"type": "boolean"},
                "continuation_type": {
                    "type": "string",
                    "enum": ["pagination", "refinement", "clarification", "new_query"]
                },
                "metrics_needed": {"type": "array", "items": {"type": "string"}},
                "dimensions_needed": {"type": "array", "items": {"type": "string"}},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "value": {"type": "string"},
                            "concept": {"type": "string"}
                        }
                    }
                },
                "aggregations": {"type": "array", "items": {"type": "string"}},
                "temporal_needed": {"type": "boolean"}
            },
            "required": ["is_continuation", "is_pagination_request", "continuation_type", "metrics_needed", "dimensions_needed", "filters", "aggregations", "temporal_needed"]
        }
        
        # Get model from agent config
        model = state.get("agent_config", {}).get("model")
        
        result = llm_service.generate_structured(messages, response_format, model=model)
        
        # Ensure aggregations is always empty (computed in response layer, not SQL)
        if result.get("aggregations"):
            result["aggregations"] = []  # Force empty - aggregations computed in response layer
        
        state["steps"].append({
            "step": "analyze_intent",
            "status": "completed",
            "duration_ms": int((time.time() - start_time) * 1000),
            "intent": result
        })
        
        return {"query_intent": result}
        
    except Exception as e:
        state["steps"].append({
            "step": "analyze_intent",
            "status": "error",
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000)
        })
        # Return minimal intent on error to allow fallback
        return {
            "query_intent": {
                "metrics_needed": [],
                "dimensions_needed": [],
                "filters": [],
                "aggregations": [],
                "temporal_needed": False
            }
        }


def search_columns_node(state: AgentState) -> Dict[str, Any]:
    """Search Qdrant for the most relevant columns and select a dataset."""
    start_time = time.time()

    try:
        # Check if we should reuse previous dataset for "show more" type queries
        previous_dataset_id = state.get("previous_dataset_id")
        previous_metadata = state.get("previous_metadata")
        
        vector_service, qdrant_service, _, _, cache_service = get_services()
        use_cache = state.get("use_cache", True)
        
        # If this is a "show more" query and we have previous dataset info, reuse it
        intent = state.get("query_intent") or {}
        is_pagination = intent.get("is_pagination_request", False)
        if is_pagination and previous_metadata:
            # For "show more" queries, skip vector search and fetch all columns for the dataset directly
            # This is much faster than doing a vector search
            print(f"Reusing previous dataset for 'show more' query: {previous_dataset_id}")
            
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            dataset_filter = Filter(
                must=[
                    FieldCondition(
                        key="dataset_id",
                        match=MatchValue(value=previous_dataset_id)
                    )
                ]
            )
            
            # Fetch all columns for this dataset (no vector search needed)
            # Use a dummy vector since we're filtering by dataset_id
            dummy_vector = [0.0] * 1536  # 1536 is the default vector size
            all_columns = qdrant_service.client.scroll(
                collection_name=qdrant_service.collection_name,
                scroll_filter=dataset_filter,
                limit=1000,  # Get all columns for the dataset
                with_payload=True,
                with_vectors=False
            )
            
            # Convert scroll results to normalized format
            normalized_results = []
            for point in all_columns[0]:  # scroll returns (points, next_page_offset)
                normalized_results.append({
                    "id": str(point.id),
                    "score": 1.0,  # All columns get same score since we're not ranking
                    "payload": point.payload or {}
                })
            
            # If we got results, use them; otherwise fall back to regular search
            if not normalized_results:
                print(f"Warning: No columns found for dataset {previous_dataset_id}, falling back to regular search")
                limit = state.get("agent_config", {}).get("column_search_limit", 20)
                query_embedding = vector_service.create_embedding(state["query"])
                search_results = qdrant_service.search_columns(
                    query_vector=query_embedding,
                    query_text=state["query"],
                    limit=limit
                )
                normalized_results = _normalize_search_results(search_results)
        else:
            # Normal flow: check cache or do multi-faceted search
            cached_payload = cache_service.get("column_search", query=state["query"]) if use_cache else None

            if cached_payload:
                state["cache_hits"]["column_search"] = True
                normalized_results = cached_payload.get("results", [])
            else:
                # Get intent from state (from analyze_query_intent_node)
                intent = state.get("query_intent") or {
                    "metrics_needed": [],
                    "dimensions_needed": [],
                    "filters": [],
                    "aggregations": [],
                    "temporal_needed": False
                }
                
                base_limit = state.get("agent_config", {}).get("column_search_limit", 15)
                
                # Perform multi-faceted search based on intent
                normalized_results = _multi_faceted_column_search(
                    vector_service,
                    qdrant_service,
                    state["query"],
                    intent,
                    base_limit=base_limit
                )
                
                if use_cache:
                    cache_service.set("column_search", {"results": normalized_results}, query=state["query"])

        if not normalized_results:
            raise ValueError("No relevant columns found for the query.")

        dataset_groups: Dict[str, Dict[str, Any]] = {}
        for result in normalized_results:
            payload = result.get("payload") or {}
            dataset_id = payload.get("dataset_id")
            if not dataset_id:
                continue

            dataset_entry = dataset_groups.setdefault(
                dataset_id,
                {
                    "dataset_id": dataset_id,
                    "dataset_name": payload.get("dataset_name") or payload.get("table_name") or dataset_id,
                    "table_name": payload.get("table_name") or payload.get("dataset_name") or dataset_id,
                    "dataset_description": payload.get("dataset_description", ""),
                    "columns": []
                }
            )

            column_metadata = dict(payload.get("full_metadata") or {})
            if "name" not in column_metadata and payload.get("column_name"):
                column_metadata["name"] = payload["column_name"]
            column_metadata["_score"] = result.get("score", 0.0)
            column_metadata["_column_index"] = payload.get("column_index")

            dataset_entry["columns"].append(column_metadata)

        if not dataset_groups:
            raise ValueError("Column search returned no usable payloads.")

        for entry in dataset_groups.values():
            entry["columns"].sort(key=lambda col: col.get("_score", 0.0), reverse=True)

        def _rank(entry: Dict[str, Any]) -> Tuple[float, int]:
            total_score = sum(col.get("_score", 0.0) for col in entry["columns"])
            # Boost score if this is the previous dataset for "show more" queries
            intent = state.get("query_intent") or {}
            is_pagination = intent.get("is_pagination_request", False)
            if is_pagination:
                if entry["dataset_id"] == previous_dataset_id:
                    total_score += 1000.0  # Strong boost to ensure previous dataset is selected
            return total_score, len(entry["columns"])

        selected_dataset = max(dataset_groups.values(), key=_rank)
        selected_dataset_id = selected_dataset["dataset_id"]
        
        # For "show more" queries, reuse previous columns instead of re-selecting
        intent = state.get("query_intent") or {}
        is_show_more = intent.get("is_pagination_request", False)
        if is_show_more and previous_metadata and previous_metadata.get("columns"):
            print(f"Reusing previous columns for 'show more' query: {len(previous_metadata['columns'])} columns")
            selected_columns_list = previous_metadata["columns"]
            filter_column_mappings = []  # No new filter mappings needed for show more
        else:
            # Load ALL columns from the selected dataset (not just vector search results)
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            dataset_filter = Filter(
                must=[
                    FieldCondition(
                        key="dataset_id",
                        match=MatchValue(value=selected_dataset_id)
                    )
                ]
            )
            
            all_dataset_columns = qdrant_service.client.scroll(
                collection_name=qdrant_service.collection_name,
                scroll_filter=dataset_filter,
                limit=1000,  # Get all columns for the dataset
                with_payload=True,
                with_vectors=False
            )
            
            # Convert to column metadata format
            all_columns = []
            for point in all_dataset_columns[0]:  # scroll returns (points, next_page_offset)
                payload = point.payload or {}
                column_metadata = dict(payload.get("full_metadata") or {})
                if "name" not in column_metadata and payload.get("column_name"):
                    column_metadata["name"] = payload["column_name"]
                if column_metadata.get("name"):  # Only include columns with names
                    all_columns.append(column_metadata)
            
            # Use LLM to select columns and map filters
            intent = state.get("query_intent") or {
                "metrics_needed": [],
                "dimensions_needed": [],
                "filters": [],
                "aggregations": [],
                "temporal_needed": False
            }
            
            _, _, _, llm_service, _ = get_services()
            model = state.get("agent_config", {}).get("model")
            
            llm_selection_result = _select_columns_with_llm(
                intent=intent,
                all_columns=all_columns,
                query=state["query"],
                dataset_name=selected_dataset["dataset_name"],
                llm_service=llm_service,
                model=model
            )
            
            # Filter all_columns to only selected ones
            selected_column_names = set(llm_selection_result.get("selected_columns", []))
            selected_columns_list = [
                col for col in all_columns
                if col.get("name") in selected_column_names
            ]
            
            # Store filter mappings for SQL generation
            filter_column_mappings = llm_selection_result.get("filter_mappings", [])

        selected_metadata = {
            "dataset_id": selected_dataset_id,
            "dataset_name": selected_dataset["dataset_name"],
            "table_name": selected_dataset["table_name"],
            "description": selected_dataset.get("dataset_description", ""),
            "columns": selected_columns_list
        }
        
        # Add LLM selection reasoning if we did LLM selection (not for show more)
        if not is_show_more and 'llm_selection_result' in locals():
            selected_metadata["llm_selection_reasoning"] = llm_selection_result.get("reasoning", "")

        state["steps"].append({
            "step": "search_columns",
            "status": "completed",
            "results_count": len(normalized_results),
            "selected_dataset": selected_dataset["dataset_id"],
            "duration_ms": int((time.time() - start_time) * 1000)
        })

        return {
            "column_search_results": normalized_results,
            "relevant_columns": selected_columns_list,
            "selected_dataset_id": selected_dataset_id,
            "selected_dataset_name": selected_dataset["dataset_name"],
            "selected_metadata": selected_metadata,
            "filter_column_mappings": filter_column_mappings
        }

    except Exception as e:
        state["steps"].append({
            "step": "search_columns",
            "status": "error",
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000)
        })
        return {"error": f"Column search failed: {str(e)}"}


def generate_sql_node(state: AgentState) -> Dict[str, Any]:
    """Generate SQL query from user query and relevant columns."""
    start_time = time.time()

    try:
        _, _, _, llm_service, cache_service = get_services()
        conversation_messages: List[BaseMessage] = state.get("messages", [])
        conversation_summary = state.get("conversation_summary")
        intent = state.get("query_intent") or {}
        is_follow_up = intent.get("is_continuation", False)
        
        # Build context sections - use summary if available, otherwise recent messages
        context_sections: List[str] = []
        if conversation_summary:
            context_sections.append(f"Conversation Summary:\n{conversation_summary}")
            # Also include last 2-3 recent messages for immediate context
            if conversation_messages:
                recent_messages = conversation_messages[:-1][-2:] if len(conversation_messages) > 1 else conversation_messages[-1:]
                recent_context = _format_recent_conversation(recent_messages)
                if recent_context:
                    context_sections.append(f"Recent Messages:\n{recent_context}")
        else:
            prior_context_snippet = _format_recent_conversation(conversation_messages[:-1]) if conversation_messages else ""
            if prior_context_snippet:
                context_sections.append(f"Recent conversation context:\n{prior_context_snippet}")
        
        if state.get("previous_sql"):
            context_sections.append(f"Previous SQL query:\n{state['previous_sql']}")
        if state.get("previous_results_summary"):
            context_sections.append(f"Previous results summary: {state['previous_results_summary']}")
        context_block = "\n\n".join(section for section in context_sections if section)

        selected_dataset_id = state.get("selected_dataset_id")
        metadata = state.get("selected_metadata", {})
        columns = state.get("relevant_columns", metadata.get("columns", []))

        if not selected_dataset_id or not columns:
            raise ValueError("No dataset or columns available for SQL generation.")

        column_names = [
            col.get("name")
            for col in columns
            if isinstance(col, dict) and col.get("name")
        ]

        cached_sql = cache_service.get(
            "sql_generation",
            query=state["query"],
            dataset_id=selected_dataset_id
        ) if state.get("use_cache", True) else None

        if cached_sql:
            state["cache_hits"]["sql_generation"] = True
            sql_query = cached_sql.get("sql_query")
            sql_reasoning = cached_sql.get("reasoning", "")
            table_name = metadata.get('table_name', selected_dataset_id)
            sql_query = _sanitize_sql_column_names(sql_query, column_names, table_name)
        else:
            columns_text = "\n".join(
                f"- {_format_column_for_sql(col)}"
                for col in columns
            )

            column_examples_lines: List[str] = []
            for col in columns:
                if not isinstance(col, dict):
                    continue
                examples = col.get("examples")
                if not examples or not isinstance(examples, list):
                    continue
                examples_list = examples[:10]
                examples_str = ", ".join(str(ex) for ex in examples_list)
                if len(examples) > 10:
                    examples_str += f" (and {len(examples) - 10} more)"
                label = "ONLY valid values" if col.get("examples_exhaustive") is True else "Examples"
                column_examples_lines.append(
                    f"- {col.get('name')}: {label} → {examples_str}"
                )

            column_examples_section = ""
            if column_examples_lines:
                column_examples_section = "\nColumn Value Examples:\n" + "\n".join(column_examples_lines)

            follow_up_note = ""
            intent = state.get("query_intent") or {}
            is_continuation = intent.get("is_continuation", False)
            is_pagination = intent.get("is_pagination_request", False)
            if is_continuation:
                if is_pagination:
                    follow_up_note = "\nThis is a follow-up question asking for MORE results from the same query. Use the EXACT same SQL query as before (do not modify it). The system will paginate through already-fetched results."
                else:
                    continuation_type = intent.get("continuation_type", "refinement")
                    if continuation_type == "refinement":
                        follow_up_note = "\nThis is a follow-up question refining the previous query. Adapt the previous SQL to incorporate the new requirements."
                    else:
                        follow_up_note = "\nThis is a follow-up question. Reuse or adapt the previous SQL when possible to maintain continuity."
            
            # Never add LIMIT - fetch all results and show requested number in response
            limit_note = "\nCRITICAL: Do NOT add a LIMIT clause to the SQL query, even if the user requests a specific number (e.g., 'show me 5 properties'). Always fetch ALL matching rows. The system will handle showing the requested number in the response, and users can request more results without rerunning the query."
            
            # CRITICAL: Always fetch raw data, not aggregated results
            raw_data_note = """
CRITICAL: ALWAYS FETCH RAW DATA, NOT AGGREGATED RESULTS

- Do NOT use COUNT, SUM, AVG, MAX, MIN, or any aggregation functions in SQL
- Do NOT use GROUP BY clauses
- Fetch ALL matching rows with relevant columns (e.g., SELECT column1, column2, ...)
- The system will compute aggregations, counts, and summaries from the raw data in the response layer
- This enables follow-up questions without rerunning queries
- Example: For "how many properties lost in September", fetch:
  SELECT record_property_name, record_pending_loss_date 
  WHERE record_pending_loss_date >= '2025-09-01' AND record_pending_loss_date < '2025-10-01'
  NOT: SELECT COUNT(*) ... GROUP BY ...
"""

            context_text = context_block if context_block else "No prior context available."
            
            # Get intent and validation info
            intent = state.get("query_intent") or {}
            validation = metadata.get("validation", {})
            
            # Build intent context
            intent_context = ""
            if intent:
                if intent.get("metrics_needed"):
                    intent_context += f"\nRequired Metrics: {', '.join(intent['metrics_needed'])}"
                if intent.get("dimensions_needed"):
                    intent_context += f"\nRequired Dimensions: {', '.join(intent['dimensions_needed'])}"
                if intent.get("filters"):
                    filter_strs = [f"{f.get('concept', f.get('type', ''))} = {f.get('value', '')}" for f in intent["filters"]]
                    if filter_strs:
                        intent_context += f"\nRequired Filters: {', '.join(filter_strs)}"
                # Note: Aggregations are NOT included in intent context - they are computed in response layer

            # Build validation warnings
            validation_warning = ""
            if not validation.get("complete", True):
                missing = validation.get("missing_types", [])
                if missing:
                    validation_warning = f"\n\n⚠️ WARNING: The following column types are missing: {', '.join(missing)}"
                    if validation.get("expanded"):
                        validation_warning += "\nExpanded search was attempted but may not have found all required columns."
                    validation_warning += "\nCRITICAL: Do NOT invent column names. Only use columns from the list above."
                    validation_warning += "\nIf a required column type is missing, explain this in your reasoning."
            
            # Map column types for clarity
            column_type_mapping = ""
            if validation.get("found_metrics"):
                column_type_mapping += f"\nMetric columns found: {', '.join(validation['found_metrics'][:5])}"
            if validation.get("found_dimensions"):
                column_type_mapping += f"\nDimension columns found: {', '.join(validation['found_dimensions'][:5])}"
            if validation.get("found_temporal"):
                column_type_mapping += f"\nTemporal columns found: {', '.join(validation['found_temporal'][:5])}"
            
            # Add filter column mappings if available
            filter_mappings_section = ""
            filter_mappings = state.get("filter_column_mappings", [])
            if filter_mappings:
                mapping_lines = []
                # Build a lookup for column types
                column_type_map = {col.get("name"): col.get("type", "") for col in columns}
                
                for mapping in filter_mappings:
                    concept = mapping.get("concept", "")
                    column = mapping.get("column", "")
                    value = mapping.get("value", "")
                    col_type = column_type_map.get(column, "").upper()
                    
                    # For STRING/TEXT columns, suggest ILIKE for partial matching
                    if col_type in ("STRING", "TEXT", "VARCHAR"):
                        mapping_lines.append(f"  - {concept} → use column '{column}' with value '{value}' (use ILIKE '%{value}%' for case-insensitive partial matching)")
                    else:
                        mapping_lines.append(f"  - {concept} → use column '{column}' with value '{value}'")
                
                filter_mappings_section = "\n\nFilter Column Mappings (USE THESE EXACT MAPPINGS):\n" + "\n".join(mapping_lines)
                filter_mappings_section += "\nCRITICAL: Use the columns specified above for each filter. Do NOT substitute with other columns."
                filter_mappings_section += "\nFor STRING/TEXT column filters, use ILIKE with wildcards for case-insensitive partial matching (e.g., WHERE \"column_name\" ILIKE '%search term%')."

            prompt = f"""Generate a SQL query to answer the user's question.

Context:
{context_text}

User Query: {state["query"]}

Query Intent:{intent_context}

Dataset: {metadata.get('table_name', selected_dataset_id)}
Description: {metadata.get('description', '')}

Available Columns (use EXACT column names as shown):
{columns_text}
{column_examples_section}
{column_type_mapping}
{filter_mappings_section}
{validation_warning}

IMPORTANT:
- Use the EXACT column names from the list above (case-sensitive)
- Do NOT invent or guess column names - if a required column type is missing, explain this in reasoning
- Use metric columns for selecting relevant data columns (e.g., occupancy, revenue) - but fetch the raw values, not aggregated results
- Use dimension columns for filtering (e.g., WHERE clauses)
- If a column name contains underscores or special characters, use it exactly as shown
- Columns with special characters (%, spaces, +, etc.) must be wrapped in DOUBLE QUOTES like "column_name%"
- Domo SQL uses double quotes for identifiers, NOT backticks
- For date filtering, use the appropriate date column and proper date format (YYYY-MM-DD)
- When a column lists \"ONLY valid values\", restrict filters to those exact values or ask for clarification instead of inventing one.
- For TEXT/STRING column filters (especially property names, locations, etc.), ALWAYS use ILIKE with wildcards for case-insensitive partial matching: WHERE "column_name" ILIKE '%search term%'
- Use ILIKE instead of = for text filters unless you're certain the exact value exists in the examples list
{raw_data_note}
{limit_note}
{follow_up_note}
Generate a valid SQL query. Respond with JSON:
{{
    "sql_query": "SELECT ...",
    "reasoning": "explanation of the query"
}}"""

            messages = [
                {
                    "role": "system",
                    "content": "You are a SQL expert. Generate SQL queries that ALWAYS fetch raw data rows, never aggregated results. Aggregations are computed in the response layer, not in SQL. Always use the exact column names provided. Never invent or guess column names. If required columns are missing, explain this clearly in your reasoning rather than inventing column names. IMPORTANT: Domo SQL uses DOUBLE QUOTES for column names with special characters (e.g., \"column_name%\"), NOT backticks. For text/string filters, use ILIKE with wildcards (e.g., WHERE \"column_name\" ILIKE '%search term%') for case-insensitive partial matching, especially for property names, locations, and other text fields."
                },
                {"role": "user", "content": prompt}
            ]

            response_format = {
                "type": "object",
                "properties": {
                    "sql_query": {"type": "string"},
                    "reasoning": {"type": "string"}
                },
                "required": ["sql_query", "reasoning"]
            }

            # Get model from agent config
            model = state.get("agent_config", {}).get("model")
            
            result = llm_service.generate_structured(messages, response_format, model=model)
            sql_query = result.get("sql_query", "")
            sql_reasoning = result.get("reasoning", "")
            table_name = metadata.get('table_name', selected_dataset_id)
            sql_query = _sanitize_sql_column_names(sql_query, column_names, table_name)

            if state.get("use_cache", True):
                cache_service.set(
                    "sql_generation",
                    {"sql_query": sql_query, "reasoning": sql_reasoning},
                    query=state["query"],
                    dataset_id=selected_dataset_id
                )

        state["steps"].append({
            "step": "generate_sql",
            "status": "completed",
            "column_count": len(columns),
            "duration_ms": int((time.time() - start_time) * 1000)
        })

        return {
            "sql_query": sql_query,
            "sql_reasoning": sql_reasoning
        }

    except Exception as e:
        state["steps"].append({
            "step": "generate_sql",
            "status": "error",
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000)
        })
        return {"error": f"SQL generation failed: {str(e)}"}


def execute_query_node(state: AgentState) -> Dict[str, Any]:
    """Execute SQL in Domo and create the final response."""
    start_time = time.time()

    try:
        _, _, domo_service, llm_service, cache_service = get_services()
        dataset_id = state.get("selected_dataset_id", "")
        sql_query = state.get("sql_query", "")
        previous_dataset_id = state.get("previous_dataset_id")
        previous_metadata = state.get("previous_metadata") or {}  # Ensure it's always a dict, not None
        
        # Check if this is a "show more" query and we have previous data
        intent = state.get("query_intent") or {}
        is_show_more = intent.get("is_pagination_request", False)
        previous_rows = previous_metadata.get("all_rows", [])
        previous_rows_shown = previous_metadata.get("rows_shown", 0)
        new_rows_shown = None  # Initialize for later use
        all_fetched_rows = []  # Initialize for storing all rows
        result = None  # Initialize result to ensure it's always defined
        
        if is_show_more and previous_rows and previous_dataset_id == dataset_id:
            # Paginate through already-fetched data instead of rerunning SQL
            print(f"Using paginated data for 'show more' query: showing rows {previous_rows_shown} to {previous_rows_shown + 10}")
            rows_per_page = 10
            start_idx = previous_rows_shown
            end_idx = min(start_idx + rows_per_page, len(previous_rows))
            paginated_rows = previous_rows[start_idx:end_idx]
            
            # Create result structure from paginated data
            result = {
                "success": True,
                "rows": paginated_rows,
                "row_count": len(paginated_rows),
                "total_rows": len(previous_rows),
                "columns": previous_metadata.get("columns", []),
                "from_cache": True,
                "paginated": True
            }
            
            # Update rows_shown for next pagination
            new_rows_shown = end_idx
        else:
            # Normal query execution
            if not dataset_id or not sql_query:
                raise ValueError("Missing dataset or SQL query for execution.")

            cached_result = cache_service.get("sql_result", sql_query=sql_query, dataset_id=dataset_id) \
                if state.get("use_cache", True) else None

            if cached_result:
                state["cache_hits"]["sql_result"] = True
                result = cached_result
            else:
                result = domo_service.execute_query(dataset_id, sql_query)
                if result is None:
                    raise ValueError("Query execution returned no result")
                if not isinstance(result, dict):
                    raise ValueError(f"Query execution returned unexpected type: {type(result)}")
                if result.get("success") and state.get("use_cache", True):
                    cache_service.set("sql_result", result, sql_query=sql_query, dataset_id=dataset_id)
            
            # Verify result is valid before processing (defensive check)
            if result is None:
                raise ValueError("Result is None after query execution")
            if not isinstance(result, dict):
                raise ValueError(f"Result is not a dict: {type(result)}")
            
            # Store all fetched rows - DO NOT limit the actual data
            all_fetched_rows = result.get("rows", [])
            
            # Keep ALL rows in result - we'll only limit what we show in the response
            result["rows"] = all_fetched_rows  # Keep all rows, not just 10
            result["row_count"] = len(all_fetched_rows)  # Actual total rows fetched
            result["total_rows"] = len(all_fetched_rows)  # Store total for pagination

        # Verify result is still valid before building response
        if result is None or not isinstance(result, dict):
            raise ValueError(f"Result is invalid before response building: {type(result)}")
        
        response_start = time.time()
        final_response = _build_final_response(llm_service, state, result)
        response_duration = int((time.time() - response_start) * 1000)

        dataset_name = state.get("selected_dataset_name") or dataset_id
        row_count = result.get("row_count", 0) if result else 0
        total_rows = result.get("total_rows", row_count) if result else row_count  # Total rows available (for pagination)
        column_names = [
            col.get("name")
            for col in state.get("relevant_columns", [])
            if isinstance(col, dict) and col.get("name")
        ]
        summary_parts = [
            f"{row_count} rows returned from {dataset_name}"
        ]
        if column_names:
            summary_parts.append(f"Key columns: {', '.join(column_names[:5])}")
        if not result.get("success"):
            summary_parts.append(f"Error: {result.get('error', 'Unknown error')}")
        results_summary = "; ".join(summary_parts)

        state["steps"].append({
            "step": "execute_query",
            "status": "completed" if result.get("success") else "error",
            "rows_returned": row_count,
            "response_generation_ms": response_duration,
            "duration_ms": int((time.time() - start_time) * 1000)
        })
        
        # Store all rows and pagination state for "show more" queries
        if is_show_more and previous_rows:
            all_rows = previous_rows  # Keep all original rows
            rows_shown = new_rows_shown  # Use the updated pagination index
        else:
            # Use all_fetched_rows that we stored before limiting
            all_rows = all_fetched_rows
            rows_shown = len(result.get("rows", []))  # Number of rows shown
        
        # Update previous_metadata with all rows and pagination state
        updated_metadata = state.get("selected_metadata", {}).copy()
        updated_metadata["all_rows"] = all_rows
        updated_metadata["rows_shown"] = rows_shown
        updated_metadata["columns"] = column_names

        return {
            "retrieved_data": result,
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
            "previous_sql": sql_query,
            "previous_results_summary": results_summary,
            "previous_metadata": updated_metadata  # Store for next "show more"
        }

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Execute query error: {str(e)}")
        print(f"Traceback: {error_trace}")
        state["steps"].append({
            "step": "execute_query",
            "status": "error",
            "error": str(e),
            "traceback": error_trace,
            "duration_ms": int((time.time() - start_time) * 1000)
        })
        return {
            "error": f"Query execution failed: {str(e)}",
            "final_response": "I encountered an error while processing your query. Please try again."
        }

