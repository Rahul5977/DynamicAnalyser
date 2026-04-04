
import os  
import shutil


# from __future__ import annotations
from typing import Iterable
import gradio as gr
from gradio.themes.base import Base
from gradio.themes.utils import colors, fonts, sizes
import time

from parse_logs import *
from extract_load_times import *
from predict_load_time import *
from extract_timeto_first_packet import *
from extract_io_graph_time import *

folder_path = "/Users/teesharamchandani/Desktop/RADCOM/Code - Load Trace/All_logs.zip"  
  
# Check if the folder exists  
if os.path.exists(folder_path):  
    # List all files in the folder  
    files = os.listdir(folder_path)  
      
    # Check if there are any files in the folder  
    if files:  
        # Iterate over each file and delete it  
        for file in files:  
            file_path = os.path.join(folder_path, file)  
            try:  
                if os.path.isfile(file_path) or os.path.islink(file_path):  
                    os.unlink(file_path)  # Remove the file or link  
                elif os.path.isdir(file_path):  
                    shutil.rmtree(file_path)  # Remove the directory and its contents  
                print(f"Deleted: {file_path}")  
            except Exception as e:  
                print(f"Failed to delete {file_path}. Reason: {e}")  
        print("All files deleted successfully.")  
    else:  
        print("No files found in the folder.")  
else:  
    print("The specified folder does not exist.") 

import subprocess
import re
from collections import defaultdict



import os
import zipfile

def extract_zip_in_directory(directory_path: str) -> None:
    """
    Finds the first ZIP file in the given directory and
    extracts its contents into the same directory.
    """

    # List all files in directory
    for file_name in os.listdir(directory_path):
        if file_name.lower().endswith(".zip"):
            zip_path = os.path.join(directory_path, file_name)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(directory_path)

            return  # Exit after extracting first zip

    # Optional: raise error if no zip found
    raise FileNotFoundError("No zip file found in the directory.")


def upload_file(file):
    #path of folder to upload the pcap file 
    upload_folder = "/Users/teesharamchandani/Desktop/RADCOM/Code - Load Trace/All_logs.zip"
    if not os.path.exists(upload_folder):
        os.mkdir(upload_folder)
    shutil.copy(file,upload_folder )

    extract_zip_in_directory(upload_folder)


    gr.Info("Zip File Uploaded Successfully!") 



def get_file_path():
    """
    Recursively find all .log files in the given directory
    and its subdirectories.

    Returns a list of full file paths.
    """

    folder_path = "/Users/teesharamchandani/Desktop/RADCOM/Code - Load Trace/All_logs"

    log_files = []

    if os.path.exists(folder_path):
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(".log"):
                    log_files.append(os.path.join(root, file))

    return log_files
import gradio as gr
import pandas as pd
import os
import shutil

def end_2_end(sensitivity_value):
    log_file_paths = get_file_path()

    # Parse Log Files 
    parsed_logs_out, trace_data = Parse_Logs(log_file_paths)
    print('parsed ')

    # Extract LOAD TIMES
    # time_to_frist_packet = extract_time_first_packet(parsed_logs_out) 
    io_out = extract_io_graph(parsed_logs_out)
    print(io_out)

    


    Final_dataset = extract_trace_load_time(parsed_logs_out)

    print('all extracted ')

    # Final_dataset = Final_dataset.merge(
    #     io_out,
    #     on="Trace_ID",
    #     how="right"
    # )
    


    # Merge With Observed Trace Data
    Final_dataset = Final_dataset.merge(
        trace_data,
        on="Trace_ID",
        how="left"
    )

    # Predict Latency - pass sensitivity value
    Final_dataset = predict_latency(Final_dataset, sensitivity_value)

    io_df = io_out.merge(
    Final_dataset[["Trace_ID", "numberOfPackets"]],
    on="Trace_ID",
    how="left"
    )

    io_df["Flow_ID"] = None
    io_df["user"] ='admin'
    io_df["Predicted_Execution_Time_sec"] = None
    io_df["Is_Anomaly"] = None

    io_df = io_df[Final_dataset.columns]

    Final_dataset = pd.concat([Final_dataset, io_df], ignore_index=True)










    return Final_dataset 

def process_and_analyze(file, sensitivity_value):
    """Handle file upload and run analysis"""
    if file is None:
        return None, None, "Please upload a file first"
    
    try:
        # Upload the file
        upload_file(file)
        
        # Run analysis with sensitivity value
        result_df = end_2_end(sensitivity_value)
        
        # Save to CSV for download
        csv_path = "analysis_results.csv"
        result_df.to_csv(csv_path, index=False)
        
        return result_df, csv_path, f"Analysis complete with sensitivity: {sensitivity_value}"
    except Exception as e:
        return None, None, f"Error: {str(e)}"

def clear_files():
    """Delete all files from the working directory and reset UI"""
    folder_path = "/Users/teesharamchandani/Desktop/RADCOM/Code - Load Trace/All_logs"
    
    # Check if the folder exists
    if os.path.exists(folder_path):
        # List all files in the folder
        files = os.listdir(folder_path)
        
        # Check if there are any files in the folder
        if files:
            # Iterate over each file and delete it
            for file in files:
                file_path = os.path.join(folder_path, file)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)  # Remove the file or link
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Remove the directory and its contents
                except Exception as e:
                    return None, None, f"Failed to delete {file_path}. Reason: {e}"
            
            return None, None, "All files deleted successfully. Ready for new upload."
        else:
            return None, None, "No files found in the folder."
    else:
        return None, None, "The specified folder does not exist."

with gr.Blocks() as demo:
    gr.Markdown("# PAM LOG ANALYSIS")
    
    with gr.Row():
        
        batch = gr.Number(
        value=2, 
        minimum=2, 
        maximum=3, 
        step=0.5,
        label="Sensitivity (σ multiplier)",
        info="standard deviations"
    )
    
    with gr.Row():
        upload_button = gr.File(label="Upload Zip File", file_types=[".zip"])
    
    with gr.Row():
        analyze_button = gr.Button("Analyze", variant="primary")
        clear_button = gr.Button("Clear Files", variant="stop")
    
    with gr.Row():
        status_text = gr.Textbox(label="Status", interactive=False)
    
    with gr.Row():
        output_dataframe = gr.Dataframe(label="Analysis Results")
    
    with gr.Row():
        download_button = gr.File(label="Download Results as CSV")
    
    # Connect the analyze button
    analyze_button.click(
        fn=process_and_analyze,
        inputs=[upload_button, batch],
        outputs=[output_dataframe, download_button, status_text]
    )
    
    # Connect the clear button
    clear_button.click(
        fn=clear_files,
        inputs=[],
        outputs=[output_dataframe, download_button, status_text]
    )

demo.launch()