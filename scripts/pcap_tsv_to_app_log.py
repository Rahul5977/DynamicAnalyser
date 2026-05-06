#!/usr/bin/env python3
"""
Convert tshark -T fields TSV (with optional quotes) into DynamicAnalyzer tshark log lines:

  <label>  elapsed=<delta>s

Uses frame.time_delta (seconds) as duration; label = last segment of frame.protocols
(e.g. eth:...:gtpv2 -> gtpv2). Pipe or pass a .tsv file path.

Example:
  tshark -r capture.pcapng -T fields -e frame.number -e frame.time_relative \\
    -e frame.time_delta -e ip.src -e ip.dst -e frame.protocols \\
    -E header=y -E separator=/t -E quote=n \\
    | python3 scripts/pcap_tsv_to_app_log.py > app_timings.log
"""
from __future__ import annotations

import csv
import re
import sys


def proto_label(protocols: str) -> str:
    p = (protocols or "").strip().strip('"')
    if not p:
        return "frame"
    tail = p.split(":")[-1]
    # safe single token for log lines
    return re.sub(r"[^a-zA-Z0-9_]", "_", tail) or "frame"


def main() -> None:
    inp = open(sys.argv[1], newline="", encoding="utf-8", errors="replace") if len(sys.argv) > 1 else sys.stdin
    out = sys.stdout
    reader = csv.reader(inp, delimiter="\t")
    rows = iter(reader)
    header = next(rows, None)
    if not header:
        return
    # find column indices (flexible header names)
    h = [c.strip().lower() for c in header]
    try:
        i_delta = next(i for i, x in enumerate(h) if "delta" in x and "time" in x)
    except StopIteration:
        i_delta = 2  # frame.number, time_relative, time_delta, ...
    try:
        i_proto = next(i for i, x in enumerate(h) if "protocol" in x)
    except StopIteration:
        i_proto = 5

    out.write("# tshark fields → DynamicAnalyzer tshark format (func elapsed=…s)\n")
    for row in rows:
        if len(row) <= max(i_delta, i_proto):
            continue
        try:
            delta_s = float(row[i_delta].strip().strip('"'))
        except ValueError:
            continue
        label = proto_label(row[i_proto])
        out.write(f"{label}  elapsed={delta_s:.9f}s\n")


if __name__ == "__main__":
    main()
