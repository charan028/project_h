import chainlit as cl
import pandas as pd

@cl.on_chat_start
async def start():
    data = {"Node ID": ["J12", "J44"], "Max Rate (CFS)": [12.5, 18.25], "Total Volume (10^6 gal)": [0.25, 0.80]}
    df = pd.DataFrame(data)
    
    await cl.Message(
        content="Here is the interactive DataFrame rendering engine in action:",
        elements=[cl.Dataframe(name="Test Table", data=df, display="inline")]
    ).send()
