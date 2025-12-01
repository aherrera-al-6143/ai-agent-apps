"""
Tools for the ReAct agent
"""
from langchain_core.tools import tool
from typing import Dict, Any, List, Optional
import json
import time
import re


def create_query_database_tool(agent_config: Dict[str, Any], use_cache: bool):
    """
    Factory function to create a configured query_database_tool.
    
    Args:
        agent_config: Agent configuration dict
        use_cache: Whether to enable caching
    
    Returns:
        Configured tool with agent_config and use_cache bound
    """
    @tool
    def query_database_tool_configured(query: str, conversation_id: str, user_id: str) -> str:
        """
        Query the property database using natural language.
        
        This tool searches for relevant columns, generates SQL, and executes the query.
        
        Args:
            query: Natural language question about property data
            conversation_id: Conversation identifier for context
            user_id: User identifier
        
        Returns:
            JSON string with query results, SQL, and metadata including columns_queried
        """
        return query_database_tool.invoke({
            "query": query,
            "agent_config": agent_config,
            "use_cache": use_cache,
            "conversation_id": conversation_id,
            "user_id": user_id
        })
    
    return query_database_tool_configured


@tool
def query_database_tool(
    query: str,
    agent_config: Dict[str, Any],
    use_cache: bool,
    conversation_id: str,
    user_id: str
) -> str:
    """
    Query the property database using natural language.
    
    This tool searches for relevant columns, generates SQL, and executes the query.
    
    Args:
        query: Natural language question about property data
        agent_config: Agent configuration (model, temperature, etc)
        use_cache: Whether to use caching
        conversation_id: Conversation identifier for context
        user_id: User identifier
    
    Returns:
        JSON string with query results, SQL, and metadata
    """
    from app.agent.nodes import (
        _multi_faceted_column_search,
        _select_columns_with_llm,
        _format_column_for_sql,
        _sanitize_sql_column_names,
        get_services
    )
    
    start_time = time.time()
    
    # Get services
    vector_service, qdrant_service, domo_service, llm_service, cache_service = get_services()
    
    # Extract model from agent_config
    model = agent_config.get("model") if agent_config else None
    base_limit = 50
    
    # Step 1: Search for relevant columns
    intent = {}  # No longer using intent analysis
    
    # Perform multi-faceted column search
    normalized_results = _multi_faceted_column_search(
        vector_service,
        qdrant_service,
        query,
        intent,
        base_limit=base_limit
    )
    
    if not normalized_results:
        return json.dumps({
            "error": "No relevant columns found for the query",
            "final_response": "I couldn't find any relevant data columns to answer your question.",
            "sql_query": None,
            "data": None
        })
    
    # Group by dataset
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
        return json.dumps({
            "error": "Column search returned no usable payloads",
            "final_response": "I couldn't find any relevant datasets to answer your question.",
            "sql_query": None,
            "data": None
        })
    
    # Sort columns by score
    for entry in dataset_groups.values():
        entry["columns"].sort(key=lambda col: col.get("_score", 0.0), reverse=True)
    
    # Select best dataset
    sorted_datasets = sorted(
        dataset_groups.values(),
        key=lambda ds: sum(col.get("_score", 0.0) for col in ds["columns"]),
        reverse=True
    )
    selected_dataset = sorted_datasets[0]
    selected_dataset_id = selected_dataset["dataset_id"]
    
    # Double-check table_name and extract table-level metadata from Qdrant
    from qdrant_client import models as rest_models
    check_result = qdrant_service.client.scroll(
        collection_name=qdrant_service.collection_name,
        scroll_filter=rest_models.Filter(
            must=[rest_models.FieldCondition(key='dataset_id', match=rest_models.MatchValue(value=selected_dataset_id))]
        ),
        limit=1,
        with_payload=True
    )
    if check_result[0]:
        payload = check_result[0][0].payload
        correct_table_name = payload.get("table_name")
        # OVERRIDE with correct value from Qdrant
        selected_dataset["table_name"] = correct_table_name
        # Extract table-level business rules and common queries
        selected_dataset["business_rules"] = payload.get("business_rules", "")
        selected_dataset["common_queries"] = payload.get("common_queries", "")
    
    # Get all columns for the selected dataset
    from qdrant_client import models as rest_models
    dataset_filter = rest_models.Filter(
        must=[
            rest_models.FieldCondition(
                key="dataset_id",
                match=rest_models.MatchValue(value=selected_dataset_id)
            )
        ]
    )
    
    all_dataset_columns = qdrant_service.client.scroll(
        collection_name=qdrant_service.collection_name,
        scroll_filter=dataset_filter,
        limit=1000,
        with_payload=True,
        with_vectors=False
    )
    
    # Convert to column metadata format
    all_columns = []
    for point in all_dataset_columns[0]:
        payload = point.payload or {}
        column_metadata = dict(payload.get("full_metadata") or {})
        if "name" not in column_metadata and payload.get("column_name"):
            column_metadata["name"] = payload["column_name"]
        if column_metadata.get("name"):
            all_columns.append(column_metadata)
    
    # Use LLM to select columns and map filters
    llm_selection_result = _select_columns_with_llm(
        intent=intent,
        all_columns=all_columns,
        query=query,
        dataset_name=selected_dataset["dataset_name"],
        llm_service=llm_service,
        model=None  # Will use default
    )
    
    # Filter all_columns to only selected ones
    selected_column_names = set(llm_selection_result.get("selected_columns", []))
    selected_columns_list = [
        col for col in all_columns
        if col.get("name") in selected_column_names
    ]
    
    # Store filter mappings for SQL generation
    filter_column_mappings = llm_selection_result.get("filter_mappings", [])
    
    # Step 2: Determine query type and generate SQL
    # Check if this is an aggregation query
    aggregation_keywords = ['average', 'avg', 'count', 'sum', 'total', 'summarize', 'group by', 'maximum', 'minimum', 'max', 'min']
    is_aggregation = any(keyword in query.lower() for keyword in aggregation_keywords)
    
    sql_result = _generate_sql_helper(
        query=query,
        selected_dataset_id=selected_dataset_id,
        table_name=selected_dataset["table_name"],
        columns=selected_columns_list,
        filter_mappings=filter_column_mappings,
        intent=intent,
        llm_service=llm_service,
        cache_service=cache_service,
        use_cache=use_cache,
        model=model,
        use_select_star=not is_aggregation,  # Use SELECT * for non-aggregation queries
        business_rules=selected_dataset.get("business_rules", ""),
        common_queries=selected_dataset.get("common_queries", "")
    )
    
    sql_query = sql_result["sql_query"]
    sql_reasoning = sql_result["sql_reasoning"]
    
    # Extract columns from SQL query for metadata
    columns_queried = []
    if "SELECT *" in sql_query.upper():
        columns_queried = [col.get("name") for col in all_columns if col.get("name")]
        query_type = "raw_data"
    else:
        # Extract column names from SELECT clause
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql_query, re.IGNORECASE | re.DOTALL)
        if select_match:
            select_clause = select_match.group(1)
            # Parse out column names (simplified - handles basic cases)
            for col in all_columns:
                col_name = col.get("name", "")
                if col_name and (col_name in select_clause or f'"{col_name}"' in select_clause):
                    columns_queried.append(col_name)
        query_type = "aggregation"
    
    # Step 3: Execute query
    execution_result = _execute_query_helper(
        dataset_id=selected_dataset_id,
        sql_query=sql_query,
        domo_service=domo_service,
        cache_service=cache_service,
        use_cache=use_cache
    )
    
    data = execution_result.get("data", [])
    rows_returned = execution_result.get("rows_returned", 0)
    
    # Build result payload
    total_duration_ms = int((time.time() - start_time) * 1000)
    
    result_payload = {
        "sql_query": sql_query,
        "sql_reasoning": sql_reasoning,
        "data": data[:100] if data else [],  # Limit to 100 rows
        "rows_returned": rows_returned,
        "columns_queried": columns_queried,
        "query_type": query_type,
        "dataset_name": selected_dataset["dataset_name"],
        "table_name": selected_dataset["table_name"],
        "total_duration_ms": total_duration_ms,
        "steps": [
            {"name": "search_columns", "duration_ms": 0},
            {"name": "generate_sql", "duration_ms": sql_result.get("duration_ms", 0)},
            {"name": "execute_query", "duration_ms": execution_result.get("duration_ms", 0)}
        ]
    }
    
    return json.dumps(result_payload)


# Helper functions for SQL generation
def _generate_sql_helper(
    query: str,
    selected_dataset_id: str,
    table_name: str,
    columns: List[Dict[str, Any]],
    filter_mappings: List[Dict[str, Any]],
    intent: Dict[str, Any],
    llm_service: Any,
    cache_service: Any,
    use_cache: bool = True,
    model: Optional[str] = None,
    use_select_star: bool = False,
    business_rules: str = "",
    common_queries: str = ""
) -> Dict[str, Any]:
    """
    Generate SQL query from user query and relevant columns.
    
    Args:
        use_select_star: If True, use SELECT * for raw data queries
        business_rules: Table-level business rules from metadata
        common_queries: Common query patterns from metadata
    
    Returns:
        Dict with sql_query, sql_reasoning, duration_ms
    """
    from app.agent.nodes import _format_column_for_sql, _sanitize_sql_column_names
    
    start_time = time.time()
    
    column_names = [
        col.get("name")
        for col in columns
        if isinstance(col, dict) and col.get("name")
    ]
    
    # Check cache (v2 = component-based SQL generation)
    cache_key_suffix = f"_v2_select_star_{use_select_star}"
    cached_result = cache_service.get(
        "sql_generation",
        query=query + cache_key_suffix,
        dataset_id=selected_dataset_id
    ) if use_cache else None
    
    if cached_result:
        # Cached result should have the final SQL already built
        sql_query = cached_result.get("sql_query")
        sql_reasoning = cached_result.get("reasoning", "")
    else:
        # Format columns for prompt
        columns_text = "\n".join(
            f"- {_format_column_for_sql(col)}"
            for col in columns
        )
        
        # Column examples
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
            col_name = col.get("name", "")
            # Add "ONLY valid values" label for exhaustive examples
            label = "ONLY valid values" if col.get("examples_exhaustive") is True else "Examples"
            column_examples_lines.append(f"  - {col_name}: {label} → {examples_str}")
        
        column_examples_section = ""
        if column_examples_lines:
            column_examples_section = "\n\nColumn Value Examples:\n" + "\n".join(column_examples_lines)
            column_examples_section += "\n  (Note: 'ONLY valid values' means this is the COMPLETE list - no other values exist in the data)"
        
        # Filter mappings section
        filter_mappings_section = ""
        if filter_mappings:
            mapping_lines = []
            column_type_map = {col.get("name"): col.get("type", "") for col in columns}
            
            for mapping in filter_mappings:
                concept = mapping.get("concept", "")
                column = mapping.get("column", "")
                value = mapping.get("value", "")
                col_type = column_type_map.get(column, "").upper()
                
                if col_type in ("STRING", "TEXT", "VARCHAR"):
                    mapping_lines.append(f"  - {concept} → use column '{column}' with value '{value}' (use ILIKE '%{value}%' for case-insensitive partial matching)")
                else:
                    mapping_lines.append(f"  - {concept} → use column '{column}' with value '{value}'")
            
            filter_mappings_section = "\n\nSuggested Filter Column Mappings (for WHERE clauses only):\n" + "\n".join(mapping_lines)
            filter_mappings_section += "\n\nCRITICAL: These mappings are ONLY suggestions for WHERE filters."
            filter_mappings_section += "\n- If the query says 'BY [dimension]' or 'group BY [dimension]', that is a GROUP BY column, NOT a WHERE filter."
            filter_mappings_section += "\n- IGNORE any filter mapping that matches a GROUP BY dimension."
            filter_mappings_section += "\n- Example: 'summarize BY corporate office' → GROUP BY record_corporate_operating_office (NOT WHERE...ILIKE '%corporate office%')"
        
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
        
        # Aggregation guidance
        if use_select_star:
            aggregation_guidance = """
QUERY TYPE: RAW DATA RETRIEVAL

You should return ["*"] for select_columns to fetch all columns. This allows for comprehensive data exploration and follow-up questions.

Examples:
- "List properties lost in September":
  {{"select_columns": ["*"], "where_conditions": ["record_pending_loss_date BETWEEN '2025-09-01' AND '2025-09-30'"], ...}}
- "Tell me about Continental Tower":
  {{"select_columns": ["*"], "where_conditions": ["record_property_name ILIKE '%Continental Tower%'"], ...}}
"""
        else:
            aggregation_guidance = """
QUERY TYPE: AGGREGATION/METRICS

Return specific columns with aggregation functions. Use group_by for dimensions:

- User asks for "average", "mean", "avg" → Use AVG() in select_columns
- User asks for "total", "sum" → Use SUM() in select_columns
- User asks for "count", "how many" → Use COUNT() in select_columns
- User asks to "summarize by X", "group by X", "break down by X" → Include X in both select_columns AND group_by
- User asks for "maximum", "minimum", "highest", "lowest" → Use MAX()/MIN() in select_columns

Pattern Examples:
- "What is the average [metric] in [location]?":
  {{"select_columns": ["AVG(metric_column)"], "where_conditions": ["location_column ILIKE '%value%'"], "group_by": [], ...}}
- "Summarize [items] BY [dimension]":
  {{"select_columns": ["dimension_column", "COUNT(*)"], "where_conditions": [...], "group_by": ["dimension_column"], ...}}
  KEY: "BY dimension" means GROUP BY that column, NOT filter WHERE it contains that text value
"""
        
        limit_note = "\nIMPORTANT: Only add LIMIT if user specifically requests a limited number (e.g., 'top 10', 'first 5'). Otherwise fetch all matching rows."
        
        # Add business rules and common queries sections
        business_rules_section = ""
        if business_rules and business_rules.strip():
            business_rules_section = f"\n\n{'='*80}\nCRITICAL - TABLE BUSINESS RULES (MUST FOLLOW):\n{'='*80}\n{business_rules.strip()}\n{'='*80}"
        
        common_queries_section = ""
        if common_queries and common_queries.strip():
            common_queries_section = f"\n\nCommon Query Patterns (Reference Examples):\n{common_queries.strip()}"
        
        prompt = f"""Generate SQL query components to answer the user's question.

User Query: {query}

Query Intent:{intent_context}

Dataset: {table_name}
(Note: You do NOT need to include the table name in your response - I will add it)

Available Columns:
{columns_text}
{column_examples_section}
{filter_mappings_section}
{business_rules_section}
{common_queries_section}

IMPORTANT: The Table Business Rules above OVERRIDE any generic patterns or examples below.

CRITICAL - Table Name Placeholder:
In the Business Rules and Common Query Patterns above, the word "table" is a PLACEHOLDER.
When you generate SQL components, replace "table" with the actual table name shown above.
Example from rules: "SELECT MAX(meas_mo) FROM table" 
Your SQL should use: "SELECT MAX(meas_mo) FROM {table_name}"
DO NOT literally write "FROM table" - always use the actual table name: {table_name}

OTHER CRITICAL INSTRUCTIONS:
- Use EXACT column names as shown (case-sensitive)
- Columns with special characters must also be wrapped in DOUBLE QUOTES
- For TEXT/STRING filters, use ILIKE with wildcards for partial matching (e.g., ILIKE '%value%')
- For date filtering, use appropriate date columns and format (YYYY-MM-DD)
{aggregation_guidance}
{limit_note}

Generate SQL query COMPONENTS (not a full query). I will assemble them into the final SQL. Respond with JSON:
{{
    "select_columns": ["*"] or ["column1", "AVG(column2) as avg_col2"],
    "where_conditions": ["column1 ILIKE '%value%'", "date_col BETWEEN '2025-01-01' AND '2025-12-31'"],
    "group_by": ["column1"] or [],
    "having_conditions": [] or ["COUNT(*) > 5"],
    "order_by": [] or ["column1 ASC"],
    "limit": null or 10,
    "reasoning": "explanation"
}}

IMPORTANT:
- Do NOT include table name anywhere - I will add it
- Do NOT include keywords (SELECT, FROM, WHERE, GROUP BY, etc) - just the values
- For select_columns: use ["*"] for all columns, or list specific columns/expressions
- Column names with special characters should be wrapped in DOUBLE QUOTES
- Use ILIKE with wildcards for text matching"""
        
        messages = [
            {
                "role": "system",
                "content": "You are a SQL expert. Generate SQL query COMPONENTS (not full queries). Return structured JSON with select_columns, where_conditions, group_by, etc. Do NOT include the table name or SQL keywords (SELECT, FROM, WHERE, etc) - just the values for each component. Column names with special characters should be wrapped in DOUBLE QUOTES. Use ILIKE with wildcards for text filtering."
            },
            {"role": "user", "content": prompt}
        ]
        
        response_format = {
            "type": "object",
            "properties": {
                "select_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of columns or expressions to SELECT (e.g., ['*'] or ['column1', 'AVG(column2)'])"
                },
                "where_conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of WHERE conditions (without WHERE keyword)"
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of columns to GROUP BY (empty array if none)"
                },
                "having_conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of HAVING conditions (empty array if none)"
                },
                "order_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ORDER BY expressions (e.g., ['column1 ASC', 'column2 DESC'])"
                },
                "limit": {
                    "type": ["integer", "null"],
                    "description": "LIMIT value if specified, otherwise null"
                },
                "reasoning": {
                    "type": "string",
                    "description": "Explanation of the query components"
                }
            },
            "required": ["select_columns", "where_conditions", "group_by", "having_conditions", "order_by", "limit", "reasoning"]
        }
        
        result = llm_service.generate_structured(messages, response_format, model=model)
        
        # Extract components
        select_columns = result.get("select_columns", ["*"])
        where_conditions = result.get("where_conditions", [])
        group_by = result.get("group_by", [])
        having_conditions = result.get("having_conditions", [])
        order_by = result.get("order_by", [])
        limit = result.get("limit")
        sql_reasoning = result.get("reasoning", "")
        
        # Build SQL query programmatically with correct table name
        select_clause = ", ".join(select_columns) if select_columns else "*"
        sql_query = f'SELECT {select_clause} FROM "{table_name}"'
        
        if where_conditions:
            where_clause = " AND ".join(f"({cond})" for cond in where_conditions)
            sql_query += f" WHERE {where_clause}"
        
        if group_by:
            group_by_clause = ", ".join(group_by)
            sql_query += f" GROUP BY {group_by_clause}"
        
        if having_conditions:
            having_clause = " AND ".join(f"({cond})" for cond in having_conditions)
            sql_query += f" HAVING {having_clause}"
        
        if order_by:
            order_by_clause = ", ".join(order_by)
            sql_query += f" ORDER BY {order_by_clause}"
        
        if limit:
            sql_query += f" LIMIT {limit}"
        
        # Sanitize column names and table names (wrap special characters/spaces in double quotes)
        sql_query = _sanitize_sql_column_names(sql_query, column_names, table_name)
        
        if use_cache:
            cache_service.set(
                "sql_generation",
                {"sql_query": sql_query, "reasoning": sql_reasoning},
                query=query + cache_key_suffix,
                dataset_id=selected_dataset_id
            )
    
    duration_ms = int((time.time() - start_time) * 1000)
    
    return {
        "sql_query": sql_query,
        "sql_reasoning": sql_reasoning,
        "duration_ms": duration_ms
    }


def _execute_query_helper(
    dataset_id: str,
    sql_query: str,
    domo_service: Any,
    cache_service: Any,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Execute SQL query in Domo.
    
    Returns:
        Dict with data, rows_returned, duration_ms
    """
    start_time = time.time()
    
    # Check cache
    cached_result = cache_service.get(
        "sql_result",
        query=sql_query,
        dataset_id=dataset_id
    ) if use_cache else None
    
    if cached_result:
        data = cached_result.get("data", [])
        rows_returned = cached_result.get("rows_returned", len(data))
    else:
        # Execute query
        result = domo_service.execute_query(dataset_id, sql_query)
        data = result.get("rows", []) if isinstance(result, dict) else result
        rows_returned = len(data) if data else 0
        
        if use_cache and data is not None:
            cache_service.set(
                "sql_result",
                {"data": data, "rows_returned": rows_returned},
                query=sql_query,
                dataset_id=dataset_id
            )
    
    duration_ms = int((time.time() - start_time) * 1000)
    
    return {
        "data": data,
        "rows_returned": rows_returned,
        "duration_ms": duration_ms
    }


# ============================================================
# KPI REPORT GENERATION TOOL
# ============================================================

def create_generate_kpi_report_tool(kpi_api_url: str = "http://localhost:8001"):
    """
    Factory function to create a configured generate_kpi_report tool.
    
    Args:
        kpi_api_url: Base URL for the KPI Reports API
    
    Returns:
        Configured tool with kpi_api_url bound
    """
    @tool
    def generate_kpi_report_tool_configured(
        office: str,
        report_type: str = "strategic_overview",
        stabilized: bool = False,
        exclude_leaseup: bool = False,
    ) -> str:
        """
        Generate a portfolio KPI report for a specific office/region.
        
        This tool generates comprehensive KPI reports including:
        - PDF report with visualizations and insights
        - Markdown report for text-based viewing
        - Statistics and metrics data
        - SQL queries used (for follow-up analysis)
        
        Available report types:
        - strategic_overview: High-level portfolio health assessment
        - critical_analysis: Focus on worst-performing properties
        - top_performers: Analysis of best-performing properties
        - operational_focus: Operational issues requiring immediate attention
        
        Args:
            office: Corporate operating office/region (e.g., "Dallas", "Houston", "Atlanta 3", "All Offices")
            report_type: Type of report (strategic_overview, critical_analysis, top_performers, operational_focus)
            stabilized: If True, only include stabilized properties (yoy_same_store = 'y')
            exclude_leaseup: If True, exclude lease-up/new development properties
        
        Returns:
            JSON string with:
            - status: "success" or "error"
            - pdf_path: Path to generated PDF file
            - markdown_path: Path to generated Markdown file  
            - metadata: Report metadata (properties count, avg score, etc.)
            - sql_queries: SQL queries used to generate the data
            - stats: Full statistics for follow-up analysis
        """
        return generate_kpi_report_tool.invoke({
            "office": office,
            "report_type": report_type,
            "stabilized": stabilized,
            "exclude_leaseup": exclude_leaseup,
            "kpi_api_url": kpi_api_url,
        })
    
    return generate_kpi_report_tool_configured


@tool
def generate_kpi_report_tool(
    office: str,
    report_type: str,
    stabilized: bool,
    exclude_leaseup: bool,
    kpi_api_url: str,
) -> str:
    """
    Generate a portfolio KPI report by calling the KPI Reports API.
    
    Args:
        office: Corporate operating office/region
        report_type: Type of report to generate
        stabilized: Only include stabilized properties
        exclude_leaseup: Exclude lease-up properties
        kpi_api_url: Base URL for the KPI Reports API
    
    Returns:
        JSON string with report results
    """
    import requests
    
    start_time = time.time()
    
    try:
        # Call the KPI Reports API
        response = requests.post(
            f"{kpi_api_url}/api/v1/reports/generate",
            json={
                "office": office,
                "report_type": report_type,
                "stabilized": stabilized,
                "exclude_leaseup": exclude_leaseup,
            },
            timeout=120,  # Report generation can take time
        )
        response.raise_for_status()
        
        result = response.json()
        
        # Add timing info
        result["generation_time_ms"] = int((time.time() - start_time) * 1000)
        
        return json.dumps(result)
        
    except requests.exceptions.ConnectionError:
        return json.dumps({
            "status": "error",
            "error": f"Could not connect to KPI Reports API at {kpi_api_url}. Is the service running?",
        })
    except requests.exceptions.Timeout:
        return json.dumps({
            "status": "error",
            "error": "KPI report generation timed out. Try again or use a smaller scope.",
        })
    except requests.exceptions.HTTPError as e:
        return json.dumps({
            "status": "error",
            "error": f"KPI Reports API returned error: {e.response.text}",
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to generate KPI report: {str(e)}",
        })


@tool
def list_available_offices_tool(kpi_api_url: str = "http://localhost:8001") -> str:
    """
    List available corporate operating offices for KPI report generation.
    
    Use this tool to discover which offices/regions are available for generating reports.
    
    Args:
        kpi_api_url: Base URL for the KPI Reports API
    
    Returns:
        JSON string with list of available offices and total property count
    """
    import requests
    
    try:
        response = requests.get(
            f"{kpi_api_url}/api/v1/reports/offices",
            timeout=30,
        )
        response.raise_for_status()
        return json.dumps(response.json())
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to list offices: {str(e)}",
        })





