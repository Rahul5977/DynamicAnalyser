

import re
import json
from datetime import datetime
import pandas as pd


# Use your filtering function
def time_stamp(log_file): 
    start_time_str = "06:59am GMT" 
    end_time_str = "07:14am GMT"  # user input format
    log_date = "2025-12-01"
    start_time_obj = datetime.strptime(start_time_str.replace("GMT","").strip(), "%I:%M%p")
    start_time = datetime.strptime(log_date, "%Y-%m-%d").replace(
        hour=start_time_obj.hour, minute=start_time_obj.minute
    )
    end_time_obj = datetime.strptime(end_time_str.replace("GMT","").strip(), "%I:%M%p")
    end_time = datetime.strptime(log_date, "%Y-%m-%d").replace(
        hour=end_time_obj.hour, minute=end_time_obj.minute
    )
    filtered_logs = []
    with open(log_file, "r") as f:
        for line in f:
            if "D:" in line:
                try:
                    ts_str = line.split("D:")[1].strip().split()[0] + " " + line.split("D:")[1].strip().split()[1]
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    if ts >= start_time:
                        if ts<=end_time:
                            filtered_logs.append(line.strip())
                except Exception:
                    continue
            else:
                if filtered_logs:
                    filtered_logs.append(line.strip())
    return filtered_logs

# Extract timestamp and microservice

# Timestamp pattern
ts_pattern = re.compile(r"D:(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")

# Flexible key=value pattern (handles case-insensitive keys like FN/Fn/fn)
# It matches until next key (L:, F:, FN:, TI:, C:, R:) or line end
kv_pattern = re.compile(
    r"(?i)\b(FN?|TI|C|R|L):\s*([^ ]+.*?)(?=\s+[A-Z]{1,2}N?:|$)"
)

# Microservice pattern
microservice_pattern = re.compile(r"com\.radcom\.([a-zA-Z0-9\-]+)")

def parse_log_line(line,file):
    entry = {
        "timestamp": None,
        "microservice": None,
        "L": None,
        "F": None,
        "FN": None,
        "TI": None,
        "C": None,
        "R": None,
        "file": None,
        "raw": line.strip()
    }


    # Timestamp
    m = ts_pattern.search(line)
    if m:
        entry["timestamp"] = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").isoformat()

    # Extract key=value fields (case-insensitive)
    for k, v in kv_pattern.findall(line):
        k = k.upper()  # normalize Fn → FN
        if k in entry:
            entry[k] = v.strip()
    try:
        match = re.search(r"R:(.*)", line)

        try:
            entry['R']  = match.group(1).strip()
        except:
            entry['R']  = entry['raw'].split("R")[-1]
       
    except:
        pass
    # Microservice from F
    if entry["F"]:
        msvc = microservice_pattern.search(entry["F"])
        if msvc:
            entry["microservice"] = msvc.group(1)

    # File name from log path
    msvc_file = re.search(r"/([^/]+)\.log", line)
    entry["file"] =file
    


    return entry

    # Fields
    # f_match = re.search(r"F:([^\s]+)", line)
    # fn_match = re.search(r"FN:([^\s]+)", line)
    # c_match = re.search(r"C:([^\s]+)", line)
    # r_match = re.search(r"R:(.*)", line)
    # if f_match: entry["F"] = f_match.group(1)
    # if fn_match: entry["FN"] = fn_match.group(1)
    # if c_match: entry["C"] = c_match.group(1)
    # if r_match: entry["R"] = r_match.group(1).strip()




def Parse_Logs(log_files: list)-> str:

    microservice_pattern = re.compile(r"com\.radcom\.([a-zA-Z0-9\-]+)")
    
    # Remove  Later
    # log_files = [
    # "datams-0_1Dec_3.log",
    # "datamsmanager-5b5f96cd4d-8jqjx_1Dec_3.log",
    # "packet-trace-analyzer-0_1Dec_3.log",
    # "packet-trace-executor-0_1Dec_3.log",
    # "packet-trace-manager-74664bbb49-4trd6_1Dec_3.log",
    # "preferencesms-fdd447676-5z4gl_1Dec_3.log",
    # "provisioningms-54d468db77-4fhrn_1Dec_3.log",
    # "storagems-69b7c7d95d-52mpc_1Dec_3.log",
    # "tracesms-58f8bd896-gf7zw_1Dec_3.log"
    #     ]
    
    all_logs = []
    for path in log_files:
        for line in time_stamp(path):
            parsed = parse_log_line(line,path)
            if parsed["timestamp"]:  # Only keep valid ones
                if "metrics" in parsed['C'].lower():
                    continue
                if parsed["C"] == "System":
                    continue
                all_logs.append(parsed)

    # Sort by timestamp
    all_logs.sort(key=lambda x: x["timestamp"])

    last_ts = None
    i = 1
    for entry in all_logs:
        ts = datetime.fromisoformat(entry["timestamp"])
        # if last_ts is not None:
        #     entry["delta_time"] = (ts - last_ts).total_seconds()
        # else:
        #     entry["delta_time"] = None
        last_ts = ts
        entry["Index"] =i
        i+=1



    unique_microservice = []

    for x in all_logs: 
        if x['microservice'] not in unique_microservice:
            if x['microservice'] != None:
                unique_microservice.append(x['microservice'])


    microservice_map = {m:(idx+1) for idx,m in enumerate(unique_microservice)}


    reverse_map = {j:i for i,j in microservice_map.items()}

    microservice_sequence = []

    for x in all_logs: 
        if x['microservice'] != None:
            try:
                microservice_sequence.append([ microservice_map[x['microservice']],x['timestamp'],x["FN"],x["R"],x["L"]])
            except:
                continue



    events = [(svc, ts,fn,r,c) for svc, ts, fn,r,c in microservice_sequence]


    fn_set ={}

    for x in events:
        if reverse_map[x[0]] == 'dataMs':
            if x[2] not in fn_set:
                fn_set[x[2]] = 0
            fn_set[x[2]]+=1


    documents = [f"{reverse_map[svc]} || T : {ts} || FN : {fn} || R : {r} || C : {c} " for svc, ts,fn, r,c in microservice_sequence]




    types = set()


    def extract_fields(log_line: str):
        patterns = {
            "traceId": r"traceId:\s*([a-fA-F0-9]+)",
            "user": r"user:\s*([^\s]+)",
            "numberOfPackets": r"numberOfPackets:\s*(\d+)"
        }

        result = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, log_line)
            result[key] = match.group(1) if match else None

        return result


    dataset = {}


    Parsed_logs_out = ''

    for i, log in enumerate(documents):
        # Clean up commas/dots
        log = log.replace(",", "").replace(".", "")

        # Find ALL /data occurrences, take the last one
        matches = re.findall(r"(/data[^\s]*)", log)
        if not matches:
            if 'FN : getProgressAndStatistics || R : Succeed to get progress and statistics traceId' in log :
                out = extract_fields(log)
                dataset[out['traceId']] = out

            # print("[No match]", log)
            continue
        path = matches[-1]  # take the last /data path

        # Classify types with descriptive labels
        if re.match(r"^/data/packets/[^/]+/([^/]+)", path):
            function = re.match(r"^/data/packets/[^/]+/([^/]+)", path).group(1)
            req_type = "packet-related"
        elif re.match(r"^/data/[^/]+/([^/]+)", path):
            function = re.match(r"^/data/[^/]+/([^/]+)", path).group(1)
            req_type = "console-function"
        elif re.match(r"^/data/([^/]+)$", path):
            function = re.match(r"^/data/([^/]+)$", path).group(1)
            req_type = "no-trace"
        else:
            function, req_type = None, None

        types.add(f"[{req_type} || {function}]")
        Parsed_logs_out+= f"[{req_type} || {function}] {log} \n"

    final_trace_data = {'Trace_ID': [],
    'user': [],
    'numberOfPackets': [],
    }

    for x in dataset:
        data = dataset[x]
        final_trace_data['Trace_ID'].append(data['traceId'])
        final_trace_data['user'].append(data['user'])
        final_trace_data['numberOfPackets'].append(data['numberOfPackets'])

    final_trace_data = pd.DataFrame(final_trace_data)

    return Parsed_logs_out,final_trace_data




        









