import os
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

# Import our custom SWMM parsing tool
from swmm_tools import parse_swmm_results

# Define the state for the LangGraph using the proper reducer for messages
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    context: dict  # To hold file paths and UI DataFrames

@tool
def analyze_swmm_report(rpt_path: str, inp_path: str = None) -> str:
    """
    Parses a SWMM .rpt (and optionally .inp) file to find flooding and capacity issues.
    This tool extracts continuity errors, the top flooded nodes, and the most overloaded conduits.
    """
    # Defensive check: ensure files exist
    if not rpt_path or not os.path.exists(rpt_path):
        return f"Error: The provided report file path '{rpt_path}' does not exist on disk."
        
    result_dict = parse_swmm_results(rpt_path, inp_path)
    
    if result_dict.get("status") == "error":
        return f"Failed to parse model: {result_dict.get('message')}"
        
    # Format the data into a readable string for the LLM
    # We need a way to pass the DataFrames back out to the UI.
    # We will do a hack: we inject them into a global dictionary or just let the LLM see the raw lists, 
    # Actually, returning a raw string is safest for LangGraph tools. 
    # To pass the DataFrames to Chainlit, we can just attach them to the current cl.user_session.
    import chainlit as cl
    try:
        # Save DataFrames to session so the UI loop can find them later
        cl.user_session.set("latest_flooded_df", result_dict.get("top_flooded_nodes"))
        cl.user_session.set("latest_surcharged_df", result_dict.get("top_surcharged_conduits"))
    except:
        pass # Not running in Chainlit context
    summary = []
    summary.append(f"**Runoff Continuity Error**: {result_dict.get('continuity_error_runoff_percent')}%")
    summary.append(f"**Routing Continuity Error**: {result_dict.get('continuity_error_routing_percent')}%")
    
    summary.append("\n**Top Flooded Nodes (Max Volume)**:")
    flooded_nodes = result_dict.get("raw_flooded_list")
    if flooded_nodes and len(flooded_nodes) > 0:
        for data in flooded_nodes:
            summary.append(f"- Node {data.get('node')}: {data}")
    else:
        summary.append("- No flooding data found.")
        
    summary.append("\n**Top Surcharged Conduits (Max Q / Full Q Ratio)**:")
    surcharged = result_dict.get("raw_surcharged_list")
    if surcharged and len(surcharged) > 0:
        for data in surcharged:
            summary.append(f"- Link {data.get('link')}: {data}")
    else:
        summary.append("- No capacity data found.")
        
    return "\n".join(summary)


# Initialize tools array
tools = [analyze_swmm_report]
tool_node = ToolNode(tools)

# Initialize the LLM (Upgraded to GPT-4o for maximum engineering reasoning, temp=0 for strict determinism)
model = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(tools)

def should_continue(state: AgentState):
    """Determine whether to continue or end the loop based on if the agent called a tool."""
    messages = state['messages']
    last_message = messages[-1]
    if last_message.tool_calls:
        return "continue"
    return "end"

# System prompt configuration
system_prompt_text = """You are the SWMM Results Intelligence Assistant, an AI expert in Storm Water Management.
Your goal is to parse EPA SWMM model outputs (.rpt files) and provide civil engineers with a structured Executive Summary.

When the user uploads a SWMM `.rpt` file (and optionally an `.inp` file):
1. Immediately use the `analyze_swmm_report` tool on the file paths provided by the user system.
2. Review the continuity errors. (If Routing error > 5%, flag it as a severe model stability issue).
3. Review the flooded nodes and surcharged conduits.
4. Output a clean, structured Executive Summary in Markdown.

Your summary MUST include:
- A brief overview of model health (Continuity Errors).
- A ranked list of the most critical problem areas (flooding nodes).
- Specific engineering recommendations on where the engineer should look next (e.g. "Because Node J12 flooded heavily, check the capacity of the immediate downstream conduit").
"""

def call_model(state: AgentState):
    """Invokes the model to generate the next response or tool call."""
    messages = state['messages']

    # LangGraph best practice for system messages
    if not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt_text)] + list(messages)
    
    response = model.invoke(messages)
    return {"messages": [response]}

# Define the graph
workflow = StateGraph(AgentState)

# Define the nodes
workflow.add_node("agent", call_model)
workflow.add_node("action", tool_node)

# Define edges
workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "continue": "action",
        "end": END
    }
)
workflow.add_edge("action", "agent")

# Compile the graph
app_graph = workflow.compile()
