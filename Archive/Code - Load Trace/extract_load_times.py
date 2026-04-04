
import re
import csv
import re
import pandas as pd

from datetime import datetime



# Helper function
def find_next(pattern, start, end=None,lines=""):
    end = end or len(lines)
    for j in range(start, min(end, len(lines))):
        if pattern.search(lines[j]):
            return j
    return -1




def extract_trace_load_time(Parsed_logs):


    lines = Parsed_logs.split("\n")


    # Define patterns
    pat_loadTrace = re.compile(r"\[console-function \|\| loadTrace\]")
    pat_progress = re.compile(r"\[console-function \|\| progressAndStatistics\]")
    pat_packet_list = re.compile(r"\[packet-related \|\| list\]")
    pat_calc_ladder = re.compile(r"\[console-function \|\| calculateLadderDiagram\]")
    pat_calc_counts = re.compile(r"\[console-function \|\| calculatePacketsCounts\]")
    pat_time_ref = re.compile(r"\[console-function \|\| timeRefNumber\]")


    # Invalid patterns - invalidate the flow if found between
    pat_invalid = re.compile(
        r"\[console-function \|\| (iograph|closeTrace)\]|\[no-trace \|\| validateFilter\]"
    )


    flows = []
    i = 0

    while i < len(lines):
        if pat_loadTrace.search(lines[i]):
            start_idx = i

            # Expected sequence
            seq_order = [
                pat_progress,
                pat_packet_list,
                pat_calc_ladder,
                pat_progress,
                pat_calc_counts,
                pat_progress,
                pat_time_ref,
                pat_calc_counts
            ]

            current_idx = i + 1
            valid = True

            for p in seq_order:
                nxt = find_next(p, current_idx,lines=lines)
                if nxt == -1:
                    valid = False
                    break
                # Check for invalid patterns in between
                for mid in range(current_idx, nxt):
                    if pat_invalid.search(lines[mid]):
                        valid = False
                        break
                if not valid:
                    break
                current_idx = nxt + 1

            if not valid:
                next_load = find_next(pat_loadTrace, i + 1,lines=lines)
                i = next_load if next_load != -1 else len(lines)
                continue

            # Extend the final calculatePacketsCounts cluster
            end_idx = current_idx - 1
            while end_idx + 1 < len(lines):
                nxt_line = lines[end_idx + 1]
                if (pat_calc_counts.search(nxt_line) or
                    re.search(r'\[No match\] datamsmanager', nxt_line)):
                    end_idx += 1
                else:
                    break

            # Capture full flow
            flow_block = lines[start_idx:end_idx + 1]
            flows.append(flow_block)
            i = end_idx + 1
        else:
            i += 1

    print(f" Parsed {len(flows)} valid loadTrace flows")

    parsed_flow = {"Flow_ID":[],'Log_Line':[]}



    for flow_id, flow in enumerate(flows, 1):
        for line in flow:
            parsed_flow['Flow_ID'].append(flow_id)
            parsed_flow['Log_Line'].append(line.strip())

        
    #dataFrame Initialization 
    df = pd.DataFrame(parsed_flow)

    # Regex patterns
    time_pattern = re.compile(r"T\s*:\s*\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2})(\d{6,7})")
    trace_pattern = re.compile(r"traceId[:=]\s*([a-zA-Z0-9]+)")
    completed_with_packets_pattern = re.compile(
        r"Return progress:\s*isCompleted:\s*true.*?numberOfPackets:\s*(\d+)",
        re.IGNORECASE
    )

    def extract_full_time(line):
        """Extract full datetime object from the log line"""
        m = time_pattern.search(str(line))
        if not m:
            return None
        hh, mm, ss, micros = m.groups()
        micros = micros[:6]
        try:
            return datetime.strptime(f"{hh}:{mm}:{ss}.{micros}", "%H:%M:%S.%f")
        except ValueError:
            return None

    def extract_trace_id(group):
        """Find first traceId from [console-function || loadTrace]"""
        for line in group["Log_Line"]:
            if "[console-function || loadTrace]" in line:
                m = trace_pattern.search(line)
                if m:
                    return m.group(1)
        return None

    def extract_packets_if_completed(group):
        """Extract numberOfPackets only when isCompleted:true"""
        for line in group["Log_Line"]:
            m = completed_with_packets_pattern.search(str(line))
            if m:
                return int(m.group(1))
        return None

    execution_info = []
    for flow_id, group in df.groupby("Flow_ID"):
        times = group["Log_Line"].apply(extract_full_time).dropna()
        trace_id = extract_trace_id(group)
        # number_of_packets = extract_packets_if_completed(group)

        if not times.empty:
            start_time = times.iloc[0]
            end_time = times.iloc[-1]
            delta = (end_time - start_time).total_seconds()
            if delta < 0:
                delta += 24 * 3600

            execution_info.append({
                "Flow_ID": flow_id,
                "Trace_ID": trace_id,
                "Start_Time": start_time.strftime("%H:%M:%S.%f"),
                "End_Time": end_time.strftime("%H:%M:%S.%f"),
                "Execution_Time_sec": round(delta, 6),
                # "Number_Of_Packets": number_of_packets
            })
        else:
            execution_info.append({
                "Flow_ID": flow_id,
                "Trace_ID": trace_id,
                "Start_Time": None,
                "End_Time": None,
                "Execution_Time_sec": None,
                # "Number_Of_Packets": number_of_packets
            })

    time_df = pd.DataFrame(execution_info)
    print(time_df)

    cols = list(time_df.columns)
    cols.insert(cols.index("Execution_Time_sec") + 1, "Task")

    time_df["Task"] = "Load Trace"
    time_df = time_df[cols]
    
    return time_df
        

    




        



