import os
import tempfile
import chainlit as cl
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from supabase import create_client, Client
import plotly.express as px

# Initialize Supabase Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase connected successfully.")
    except Exception as e:
        print(f"Warning: Supabase keys invalid. {e}")
else:
    print("Warning: Supabase keys not found. Cloud logging is disabled.")

# Import our custom LangGraph agent
from agent_workflow import app_graph

@cl.on_chat_start
async def on_chat_start():
    # Set the initial state for this user/session
    cl.user_session.set("agent_state", {"messages": [], "context": {}})

    await cl.Message(
        content="**Welcome to the Project H.Y.D.R.O.!**\n\n"
                "I am your AI Civil Engineering Co-Pilot. I can automatically parse EPA SWMM models to find continuity errors, map out flooded nodes, and flag capacity issues.\n\n"
                "To get started, please **upload a `.rpt` report file** (and optionally the `.inp` model file) using the attachment icon below, and ask me to summarize the performance."
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    # Retrieve the state history
    state = cl.user_session.get("agent_state")
    
    # Process uploaded files 
    rpt_path = None
    inp_path = None
    
    # Only try to handle elements if there are any
    if message.elements:
        for element in message.elements:
            if element.name.endswith(".rpt"):
                rpt_path = element.path
            elif element.name.endswith(".inp"):
                inp_path = element.path
                
        # Inject the file paths into the User's message context so the LLM knows about them.
        # CRITICAL: We pass the PATH, not the text, because .rpt files can be 500MB+ and would crash the LLM context window.
        if rpt_path:
            file_context = f"\n[System: The user has uploaded a SWMM report file at disk path: {rpt_path}]"
            if inp_path:
                file_context += f"\n[System: The user has also uploaded a SWMM input file at disk path: {inp_path}]"
            
            message.content += file_context
    
    # Append the user's new message to the history
    state["messages"].append(HumanMessage(content=message.content))
    
    # 1. Log the User's Message to Supabase
    if supabase:
        try:
            supabase.table("chat_logs").insert({
                "session_id": cl.user_session.get("id"),
                "role": "user",
                "content": message.content
            }).execute()
        except:
            pass
            
    # We will stream the response from the agent
    res = await cl.Message(content="").send()
    
    final_state = None
    
    # Track steps by run_id
    tool_steps = {}
    
    # Run the graph
    try:
        # Stream the events from the graph to give real-time feedback
        async for event in app_graph.astream_events(state, version="v2"):
            kind = event["event"]
            
            # Streaming LLM tokens
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    await res.stream_token(content)
                    
            # Tool Start
            elif kind == "on_tool_start":
                tool_name = event["name"]
                run_id = event["run_id"]
                step = cl.Step(name=f"Parsing with: {tool_name}")
                step.input = "Uploaded model files"
                await step.send()
                tool_steps[run_id] = step
                
            # Tool End
            elif kind == "on_tool_end":
                run_id = event["run_id"]
                step = tool_steps.pop(run_id, None)
                if step:
                    # Provide a simple checkmark so it stops spinning in the UI
                    step.output = "Parsing complete."
                    await step.update()
                    
            # Capture the final resulting state from the root graph
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                output = event.get("data", {}).get("output")
                if output and isinstance(output, dict) and "messages" in output:
                    final_state = output
                    
    except Exception as e:
        print(f"Error in astream_events: {e}")
        await cl.Message(content=f"Error executing graph: {e}").send()
        return

    # Update state with the final messages from the graph run without executing it twice
    if final_state:
        cl.user_session.set("agent_state", final_state)
        # Crucial step: finalize the streamed message so the UI knows it is done.
        if not res.content and final_state.get("messages"):
            res.content = final_state["messages"][-1].content
    
    await res.update()
    
    # Render DataFrames if the parser found any
    flooded_df = cl.user_session.get("latest_flooded_df")
    surcharged_df = cl.user_session.get("latest_surcharged_df")
    
    if flooded_df is not None and not flooded_df.empty:
        fig = px.bar(
            flooded_df, 
            x="Node ID", 
            y="Total Volume (10^6 gal)", 
            title="Max Flooding Volume per Node",
            color="Total Volume (10^6 gal)",
            color_continuous_scale="Reds"
        )
        
        await cl.Message(
            content="**Flooded Nodes Analysis:**",
            elements=[
                cl.Plotly(name="Flooding Graph", figure=fig, display="inline"),
                cl.Dataframe(name="Flooded Nodes", data=flooded_df, display="inline")
            ]
        ).send()
        
    if surcharged_df is not None and not surcharged_df.empty:
        await cl.Message(
            content="**Surcharged Conduits Table:**",
            elements=[cl.Dataframe(name="Surcharged Conduits", data=surcharged_df, display="inline")]
        ).send()
        
    # Clear session dataframes so they don't print on the next generic message
    cl.user_session.set("latest_flooded_df", None)
    cl.user_session.set("latest_surcharged_df", None)
    
    # 2. Log the Assistant's Response & Search Metrics to Supabase
    if supabase:
        # Save Chat Response
        try:
            supabase.table("chat_logs").insert({
                "session_id": cl.user_session.get("id"),
                "role": "assistant",
                "content": res.content
            }).execute()
        except Exception as e:
            print(f"Supabase AI log error: {e}")
            
        # Save Search Metrics if a file was parsed
        if rpt_path:
            try:
                num_flooded = len(flooded_df) if flooded_df is not None and not flooded_df.empty else 0
                num_surcharged = len(surcharged_df) if surcharged_df is not None and not surcharged_df.empty else 0
                
                supabase.table("search_logs").insert({
                    "session_id": cl.user_session.get("id"),
                    "files_analyzed": os.path.basename(rpt_path),
                    "flooded_nodes_count": num_flooded,
                    "surcharged_conduits_count": num_surcharged
                }).execute()
            except Exception as e:
                print(f"Supabase search log error: {e}")
    
    print("Graph execution fully completed and res updated.")
