# Architecture Audit: al-ai-agent-v2

**Date:** December 1, 2025  
**Purpose:** Comprehensive review of agent architecture with focus on tool selection issues for structured (KPI) vs unstructured (database query) questions

---

## Executive Summary

The agent is built on LangGraph's `create_react_agent` pattern with two tools: `query_database_tool` for unstructured database queries and `generate_kpi_report_tool` for structured KPI reports. **The core issue is that the agent defaults to the query tool even when KPI reports are requested** because:

1. No explicit routing logic exists—tool selection relies entirely on LLM reasoning
2. Tool descriptions don't provide clear differentiation signals
3. The system prompt buries KPI instructions at the end
4. Both tools can technically answer similar questions, creating ambiguity

---

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER QUERY                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    create_react_agent                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   System Prompt                          │    │
│  │  (Contains instructions for BOTH tools)                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    LLM (Gemini/GPT)                      │    │
│  │         Decides: Which tool to call?                     │    │
│  │    ❌ No explicit routing logic                          │    │
│  │    ❌ Relies solely on LLM reasoning                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                  │
│  ┌────────────────────┐         ┌────────────────────────────┐ │
│  │ query_database_tool│         │ generate_kpi_report_tool   │ │
│  │ (DEFAULT FALLBACK) │         │ (UNDERUSED)                │ │
│  │                    │         │                            │ │
│  │ • Vector search    │         │ • Calls KPI API            │ │
│  │ • SQL generation   │         │ • Returns PDF/Markdown     │ │
│  │ • Domo execution   │         │ • Returns stats            │ │
│  └────────────────────┘         └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed Analysis

### 1. Tool Selection Problem (Critical Issue)

**Root Cause:** The system prompt treats tool selection as an afterthought rather than a primary decision point.

**Current System Prompt Structure:**
```
Lines 1-120: Detailed instructions for query_database_tool
Lines 121-137: Brief mention of KPI tool at the END
```

**Problem Evidence:**
```python
# From graph.py - KPI instructions are minimal and buried
"""
KPI REPORT GENERATION:
When users ask for KPI reports, portfolio analysis, or performance overviews, use the generate_kpi_report tool.
Available report types:
- strategic_overview: High-level portfolio health and performance distribution
...
"""
```

**Why the Query Tool Wins:**
1. It appears first and has detailed instructions
2. It can technically answer "strategic overview" questions via SQL
3. No keyword triggers to force KPI tool selection
4. The LLM sees "query property data" which matches "strategic overview of Dallas"

---

### 2. Ambiguous Tool Descriptions

| Aspect | query_database_tool | generate_kpi_report_tool |
|--------|---------------------|--------------------------|
| **Purpose** | "Query the property database using natural language" | "Generate a portfolio KPI report" |
| **Overlap** | Can answer "what is occupancy for Dallas?" | Can answer "strategic overview for Dallas" |
| **Trigger Words** | None specified | "KPI reports, portfolio analysis, performance overviews" |
| **Clear Boundaries** | ❌ No | ❌ No |

**The Problem:** A user asking "Give me a strategic overview of Dallas" could reasonably be handled by either tool. Without explicit routing, the LLM defaults to the more detailed query tool.

---

### 3. Single ReAct Loop Limitations

The `create_react_agent` pattern is excellent for simple use cases but has limitations:

| Strength | Weakness |
|----------|----------|
| Simple to implement | No pre-classification step |
| Built-in tool calling | Tool selection is per-turn (no planning) |
| Conversation history via checkpointer | Can't enforce tool routing rules |
| Works well for single tool scenarios | Ambiguous with multiple specialized tools |

---

### 4. Code Structure Issues

**graph.py Issues:**
```python
# Line 66-67: KPI API URL hardcoded to localhost - will fail in production!
kpi_api_url = os.getenv("KPI_REPORTS_API_URL", "http://localhost:8001")
kpi_report_tool = create_generate_kpi_report_tool(kpi_api_url)
```

**tools.py Issues:**
```python
# KPI tool doesn't return structured data that the agent can use for follow-ups
# It returns a file path - hard to integrate into conversation
return json.dumps({
    "status": "success",
    "pdf_path": "/tmp/...",  # File path isn't useful in chat
    ...
})
```

---

### 5. Scalability Concerns

| Current State | Future Risk |
|---------------|-------------|
| 2 tools | Adding more tools will worsen selection accuracy |
| 2 datasets | More datasets = more vector search complexity |
| Single agent | No specialization for different query types |
| Flat routing | No hierarchy for complex workflows |

---

## Pain Points Summary

| # | Pain Point | Impact | Severity |
|---|-----------|--------|----------|
| 1 | No explicit tool routing | KPI tool underused | 🔴 Critical |
| 2 | System prompt structure | Query tool favored | 🔴 Critical |
| 3 | Ambiguous tool descriptions | Wrong tool selection | 🟡 High |
| 4 | KPI tool returns file paths | Poor UX in chat | 🟡 High |
| 5 | Single ReAct loop | Limited control over flow | 🟡 Medium |
| 6 | Hardcoded KPI API URL | Production failure risk | 🟡 Medium |
| 7 | No intent classification | Inefficient processing | 🟢 Low |

---

## Opportunities

1. **Pre-Classification Router**: Add a lightweight LLM call to classify query intent before tool execution
2. **Keyword-Based Fast Path**: Detect KPI keywords ("strategic overview", "portfolio analysis") for instant routing
3. **Improved Tool Descriptions**: Make tools mutually exclusive with clear boundaries
4. **Supervisor Pattern**: Use LangGraph's supervisor for multi-agent orchestration
5. **Semantic Tool Selection**: Use embeddings to match queries to tool descriptions

---

## Three Architecture Options

### Option 1: Enhanced Prompting (Quick Fix)
**Effort: 1-2 days | Risk: Low | Scalability: Limited**

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER QUERY                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              ENHANCED create_react_agent                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │            RESTRUCTURED System Prompt                    │    │
│  │                                                          │    │
│  │  FIRST: Tool Selection Rules (explicit decision tree)    │    │
│  │  ────────────────────────────────────────────────────    │    │
│  │  IF query contains: "strategic overview", "portfolio     │    │
│  │     analysis", "KPI report", "performance report"        │    │
│  │  THEN: Use generate_kpi_report_tool                      │    │
│  │                                                          │    │
│  │  IF query contains: specific metrics, counts, filters,   │    │
│  │     raw data questions, specific property lookups        │    │
│  │  THEN: Use query_database_tool                           │    │
│  │                                                          │    │
│  │  SECOND: Tool-specific instructions                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                  │
│  ┌────────────────────┐         ┌────────────────────────────┐ │
│  │ query_database_tool│         │ generate_kpi_report_tool   │ │
│  └────────────────────┘         └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**

```python
# graph.py - New system prompt structure
system_message = """You are a helpful data analyst assistant.

═══════════════════════════════════════════════════════════════════
CRITICAL: TOOL SELECTION RULES (MUST FOLLOW)
═══════════════════════════════════════════════════════════════════

STEP 1: Identify query type BEFORE selecting a tool.

🎯 USE generate_kpi_report_tool WHEN user asks for:
- "strategic overview" of any office/region
- "portfolio analysis" or "portfolio health"
- "performance report" or "KPI report"
- "critical analysis" or "underperforming properties"
- "top performers" analysis
- "operational issues" summary
- Any request that implies a PDF/report output

📊 USE query_database_tool WHEN user asks for:
- Specific counts ("how many properties...")
- Raw data retrieval ("list all properties in...")
- Specific metrics ("what is the occupancy of...")
- Filtering questions ("properties lost in September...")
- Aggregations ("average occupancy by office...")
- Property-specific lookups ("tell me about Continental Tower")

⚠️ WHEN IN DOUBT:
- If user mentions "report", "overview", "analysis" → KPI tool
- If user mentions specific numbers, lists, filters → Query tool

═══════════════════════════════════════════════════════════════════

[Rest of tool-specific instructions below...]
"""
```

**Pros:**
- ✅ Fastest to implement
- ✅ No architectural changes
- ✅ Low risk of breaking existing functionality
- ✅ Can be tested immediately

**Cons:**
- ❌ Still relies on LLM following instructions (can drift)
- ❌ Doesn't scale well with more tools
- ❌ No guaranteed routing
- ❌ Edge cases may still fail

**When to Choose:** 
- Need a quick fix before a demo
- Want to test if better prompts alone solve the problem
- Limited engineering resources available

---

### Option 2: Router Node Pattern (Recommended)
**Effort: 3-5 days | Risk: Medium | Scalability: Good**

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER QUERY                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INTENT CLASSIFIER (New!)                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Fast LLM call or keyword matching                       │    │
│  │  Returns: "structured" | "unstructured"                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                  │
│     query_type == "structured"      query_type == "unstructured"│
│              │                               │                  │
│              ▼                               ▼                  │
│  ┌────────────────────┐         ┌────────────────────────────┐ │
│  │   KPI Agent        │         │    Query Agent             │ │
│  │  (Only KPI tool)   │         │  (Only query tool)         │ │
│  └────────────────────┘         └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**

```python
# app/agent/router.py (NEW FILE)
from langchain_core.messages import HumanMessage
from typing import Literal

def classify_query_intent(query: str, llm_service) -> Literal["structured", "unstructured"]:
    """
    Classify user query to route to appropriate tool.
    Uses fast LLM call with structured output.
    """
    # Fast path: keyword matching for common cases
    structured_keywords = [
        "strategic overview", "portfolio analysis", "kpi report",
        "performance report", "critical analysis", "top performers",
        "operational focus", "portfolio health", "generate report"
    ]
    
    query_lower = query.lower()
    for keyword in structured_keywords:
        if keyword in query_lower:
            return "structured"
    
    # LLM classification for ambiguous cases
    classification_prompt = f"""Classify this user query into ONE category:

Query: "{query}"

Categories:
- "structured": User wants a comprehensive KPI report, strategic overview, portfolio analysis, or any PDF/report output
- "unstructured": User wants specific data, counts, filters, raw data, or answers to specific questions

Respond with ONLY the category name: "structured" or "unstructured"
"""
    
    response = llm_service.generate([
        {"role": "system", "content": "You are a query classifier. Respond with only one word."},
        {"role": "user", "content": classification_prompt}
    ], temperature=0, max_tokens=20)
    
    result = response.strip().lower().strip('"')
    return "structured" if "structured" in result else "unstructured"


# app/agent/graph.py (MODIFIED)
from langgraph.graph import StateGraph, END
from app.agent.router import classify_query_intent

def create_agent_graph(agent_config: dict = None, use_cache: bool = True):
    """Create agent with router pattern."""
    
    # Create separate agents for each query type
    kpi_agent = create_react_agent(
        llm,
        tools=[kpi_report_tool],
        checkpointer=_get_checkpointer(),
        prompt=KPI_SYSTEM_PROMPT
    )
    
    query_agent = create_react_agent(
        llm,
        tools=[query_tool],
        checkpointer=_get_checkpointer(),
        prompt=QUERY_SYSTEM_PROMPT
    )
    
    # Router function
    def route_query(state):
        messages = state["messages"]
        last_message = messages[-1]
        
        if isinstance(last_message, HumanMessage):
            intent = classify_query_intent(last_message.content, llm_service)
            return intent
        return "unstructured"  # default
    
    # Build graph with conditional routing
    workflow = StateGraph(AgentState)
    
    workflow.add_node("router", route_query)
    workflow.add_node("kpi_agent", kpi_agent)
    workflow.add_node("query_agent", query_agent)
    
    workflow.set_entry_point("router")
    
    workflow.add_conditional_edges(
        "router",
        lambda x: x,  # Route based on classification result
        {
            "structured": "kpi_agent",
            "unstructured": "query_agent"
        }
    )
    
    workflow.add_edge("kpi_agent", END)
    workflow.add_edge("query_agent", END)
    
    return workflow.compile(checkpointer=_get_checkpointer())
```

**Pros:**
- ✅ Explicit routing logic (not relying on LLM to pick tools)
- ✅ Each agent is specialized for its domain
- ✅ Fast keyword matching for common cases
- ✅ LLM fallback for edge cases
- ✅ Easy to debug and test routing
- ✅ Scales better with more query types

**Cons:**
- ❌ Additional LLM call for classification (adds ~200-500ms)
- ❌ Need to maintain separate system prompts
- ❌ Router needs to handle multi-turn conversations correctly
- ❌ More code to maintain

**When to Choose:**
- This is the **recommended option** for your use case
- Good balance of reliability and complexity
- You need the KPI tool to work reliably
- You plan to add more structured report types

---

### Option 3: Multi-Agent Supervisor Pattern (Future-Proof)
**Effort: 1-2 weeks | Risk: Higher | Scalability: Excellent**

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER QUERY                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SUPERVISOR AGENT                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  • Understands all available sub-agents                  │    │
│  │  • Routes to appropriate specialist                      │    │
│  │  • Can orchestrate multi-step workflows                  │    │
│  │  • Handles hand-offs between agents                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│       ┌──────────────────────┼──────────────────────┐           │
│       ▼                      ▼                      ▼           │
│  ┌──────────┐         ┌──────────┐         ┌──────────────┐    │
│  │   KPI    │         │  Query   │         │   Future     │    │
│  │  Agent   │         │  Agent   │         │   Agent      │    │
│  │          │         │          │         │   (e.g.,     │    │
│  │ • KPI    │         │ • SQL    │         │   Forecasting│    │
│  │   reports│         │   queries│         │   Agent)     │    │
│  │ • PDF    │         │ • Domo   │         │              │    │
│  │   output │         │   data   │         │              │    │
│  └──────────┘         └──────────┘         └──────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation (using LangGraph Supervisor pattern):**

```python
# app/agent/supervisor.py (NEW FILE)
from langgraph.graph import StateGraph, END
from langgraph_supervisor import create_supervisor

def create_supervisor_agent():
    """Create multi-agent system with supervisor."""
    
    # Define sub-agents
    kpi_agent = create_kpi_agent()  # Specialized for KPI reports
    query_agent = create_query_agent()  # Specialized for SQL queries
    
    # Supervisor configuration
    supervisor_config = {
        "agents": {
            "kpi_specialist": {
                "agent": kpi_agent,
                "description": """KPI Report Specialist: Use for generating comprehensive
                portfolio reports, strategic overviews, performance analysis, and any
                request that requires PDF/report output. Best for questions like:
                - "Give me a strategic overview of Dallas"
                - "Generate a KPI report for Houston"
                - "What's the portfolio health analysis?"
                """,
            },
            "data_analyst": {
                "agent": query_agent,
                "description": """Data Analyst: Use for specific data queries, counts,
                filters, and raw data retrieval. Best for questions like:
                - "How many properties were lost in September?"
                - "What is the occupancy for Continental Tower?"
                - "List all properties in Denver"
                """,
            }
        },
        "llm": ChatOpenAI(model="google/gemini-2.5-flash", temperature=0),
        "supervisor_prompt": """You are a supervisor managing specialized agents.
        Route user queries to the most appropriate specialist.
        
        IMPORTANT: Only select ONE agent per turn. Do not call multiple agents.
        
        For reports, overviews, portfolio analysis → kpi_specialist
        For specific data, counts, filters → data_analyst
        """
    }
    
    return create_supervisor(**supervisor_config)
```

**Pros:**
- ✅ Most scalable architecture
- ✅ Easy to add new specialized agents
- ✅ Supervisor can orchestrate complex multi-step workflows
- ✅ Each agent can have its own state and context
- ✅ Best for complex enterprise use cases
- ✅ Supports agent-to-agent handoffs

**Cons:**
- ❌ Most complex to implement
- ❌ Higher latency (supervisor + sub-agent calls)
- ❌ More points of failure
- ❌ Overkill for current 2-tool scenario
- ❌ Requires more testing and debugging

**When to Choose:**
- You plan to add 3+ specialized agents
- You need complex multi-step workflows
- You have dedicated engineering time
- You're building a platform, not just a feature

---

## Recommendation Matrix

| Factor | Option 1: Prompting | Option 2: Router (⭐) | Option 3: Supervisor |
|--------|--------------------|-----------------------|---------------------|
| **Implementation Time** | 1-2 days | 3-5 days | 1-2 weeks |
| **Reliability** | Medium | High | Highest |
| **Latency Impact** | None | +200-500ms | +500-1000ms |
| **Scalability** | Limited | Good | Excellent |
| **Maintenance** | Easy | Medium | Complex |
| **Current Need Fit** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **Future Proof** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## Immediate Action Items

### If You Choose Option 1 (Quick Fix):
1. [ ] Restructure system prompt with tool selection rules at TOP
2. [ ] Add explicit keyword triggers for KPI tool
3. [ ] Test with 10+ KPI-related queries
4. [ ] Monitor tool selection accuracy

### If You Choose Option 2 (Recommended):
1. [ ] Create `app/agent/router.py` with intent classifier
2. [ ] Split system prompt into two specialized prompts
3. [ ] Modify `graph.py` to use StateGraph with routing
4. [ ] Add unit tests for router accuracy
5. [ ] Test both paths thoroughly

### Regardless of Choice:
1. [ ] Fix KPI API URL to use environment variable properly
2. [ ] Improve KPI tool response format (include summary text, not just file path)
3. [ ] Add evaluation tests specifically for KPI tool selection
4. [ ] Consider adding `list_available_offices_tool` to the agent

---

## Testing Strategy

Add these test cases to `test_use_cases.json`:

```json
{
    "kpi_tests": [
        "Give me a strategic overview of Dallas",
        "Generate a KPI report for Houston",
        "What's the portfolio health for Atlanta?",
        "Show me the critical analysis for Denver",
        "I need a performance report for San Antonio"
    ],
    "should_NOT_use_kpi": [
        "How many properties are in Dallas?",
        "What is the occupancy for Continental Tower?",
        "List properties lost in September 2025"
    ]
}
```

---

## Conclusion

**The recommended path forward is Option 2 (Router Node Pattern)** because:

1. It directly solves the tool selection problem
2. It's a reasonable implementation effort (3-5 days)
3. It scales well for your near-term needs (adding more report types)
4. It provides explicit, testable routing logic
5. It can be incrementally improved without major rewrites

Start with Option 1 if you need an immediate fix, then migrate to Option 2 for production reliability.

---

*Generated by Architecture Audit Tool*

