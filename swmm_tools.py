import os
import re
import pandas as pd

def parse_swmm_results(rpt_path: str, inp_path: str = None) -> dict:
    """
    Parses a SWMM .rpt file to extract critical engineering performance metrics.
    Designed to process 3GB+ files line-by-line to prevent Out-Of-Memory errors.

    Returns a structured dictionary containing:
    - Continuity Errors
    - Top Flooded Nodes
    - Surcharged Conduits
    """
    if not os.path.exists(rpt_path):
        return {"error": f"Report file not found at {rpt_path}"}

    continuity_error_runoff = None
    continuity_error_routing = None
    
    # We will use variables to track when we are inside specific tables
    in_flooding_table = False
    in_surcharge_table = False
    
    flooded_nodes = []
    surcharged_links = []
    
    # Regexes for the continuity errors
    runoff_re = re.compile(r"Runoff Quantity Continuity.*Continuity Error \(%\) \.+\s+([-\d\.]+)", re.DOTALL)

    try:
        # Stream the file line-by-line. Never use f.read() on a 3GB file.
        with open(rpt_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # 1. Catch Continuity Errors
                # The line format is: "  Continuity Error (%) .....      -0.029"
                # Since both Runoff and Routing have this exact line, we rely on the order
                # or just capture them sequentially. We'll grab any line that matches and assign it.
                if "Continuity Error (%)" in line:
                    parts = line.split()
                    val = float(parts[-1])
                    if continuity_error_runoff is None:
                        continuity_error_runoff = val
                    elif continuity_error_routing is None:
                        continuity_error_routing = val
                
                # 2. State Machine for Node Flooding Table
                if "Node Flooding Summary" in line:
                    in_flooding_table = True
                    continue
                    
                if in_flooding_table:
                    # If we hit an empty line, we exit the table (the table ends with blank lines before the next header)
                    if not line.strip() and len(flooded_nodes) > 0:
                        in_flooding_table = False
                        continue
                    
                    parts = line.split()
                    # A valid data line will have at least 6 parts and the 2nd part is usually a number (Hours)
                    if len(parts) >= 6 and parts[1].replace('.','',1).isdigit() and parts[0] != "Node":
                        try:
                            node_id = parts[0]
                            max_rate = float(parts[2])
                            total_vol = float(parts[5])
                            flooded_nodes.append({"node": node_id, "MaxFloodingRate": max_rate, "TotalFloodVol": total_vol})
                        except ValueError:
                            pass # skip header lines
                
                # 3. State Machine for Conduit Surcharge Table
                if "Conduit Surcharge Summary" in line:
                    in_surcharge_table = True
                    in_flooding_table = False # Just in case
                    continue
                    
                if in_surcharge_table:
                    if not line.strip() and len(surcharged_links) > 0:
                        in_surcharge_table = False
                        continue
                        
                    parts = line.split()
                    # A valid data line will have 5 parts and the 2nd part is a number (Hours Surcharged)
                    if len(parts) >= 5 and parts[1].replace('.','',1).isdigit() and parts[0] != "Conduit":
                        try:
                            link_id = parts[0]
                            hours_surcharged = float(parts[1])
                            hours_full_normal = float(parts[3])
                            surcharged_links.append({"link": link_id, "HoursSurcharged": hours_surcharged, "HoursAboveFullNormal": hours_full_normal})
                        except ValueError:
                            pass # skip headers

        # Post-process the extracted arrays into top 5 DataFrames
        top_flooded_df = None
        if flooded_nodes:
            flooded_nodes.sort(key=lambda x: x["TotalFloodVol"], reverse=True)
            top_flooded_df = pd.DataFrame(flooded_nodes[:5])
            # Rename columns for clarity in the UI
            top_flooded_df.rename(columns={"node": "Node ID", "MaxFloodingRate": "Max Rate (CFS)", "TotalFloodVol": "Total Volume (10^6 gal)"}, inplace=True)
            
        top_surcharged_df = None
        if surcharged_links:
            surcharged_links.sort(key=lambda x: x["HoursSurcharged"], reverse=True)
            top_surcharged_df = pd.DataFrame(surcharged_links[:5])
            # Rename columns
            top_surcharged_df.rename(columns={"link": "Conduit ID", "HoursSurcharged": "Hours Surcharged", "HoursAboveFullNormal": "Hours Above Normal"}, inplace=True)

        return {
            "status": "success",
            "continuity_error_runoff_percent": continuity_error_runoff,
            "continuity_error_routing_percent": continuity_error_routing,
            "top_flooded_nodes": top_flooded_df,
            "top_surcharged_conduits": top_surcharged_df,
            "raw_flooded_list": flooded_nodes[:5], # Keep raw lists for the LLM thought process
            "raw_surcharged_list": surcharged_links[:5]
        }

    except Exception as e:
        return {"status": "error", "message": f"Error during large file stream: {str(e)}"}

# Quick local test if run directly
if __name__ == "__main__":
    test_res = parse_swmm_results("sample_data/test_swmm.rpt")
    import pprint
    pprint.pprint(test_res)
