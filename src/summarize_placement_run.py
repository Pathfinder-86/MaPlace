#!/usr/bin/env python3
"""
summarize_placement_run.py
--------------------------
Parse DREAMPlace run logs and export a concise placement quality summary.
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone


ITER_RE = re.compile(
    r"iteration\s+(\d+),.*wHPWL\s+([0-9.E+-]+), Overflow\s+([0-9.E+-]+), MaxDensity\s+([0-9.E+-]+)"
)
BENCH_RE = re.compile(
    r"#nodes\s*=\s*(\d+),\s*#terminals\s*=\s*(\d+),\s*# terminal_NIs\s*=\s*(\d+),\s*#movable\s*=\s*(\d+),\s*#nets\s*=\s*(\d+)"
)
RUNTIME_RE = re.compile(r"placement takes\s+([0-9.]+)\s+seconds")


def parse_dreamplace_log(path):
    with open(path) as f:
        content = f.read()

    bench = BENCH_RE.search(content)
    runtime = RUNTIME_RE.search(content)
    iters = [
        {
            "iteration": int(m.group(1)),
            "hpwl": float(m.group(2)),
            "overflow": float(m.group(3)),
            "max_density": float(m.group(4)),
        }
        for m in ITER_RE.finditer(content)
    ]

    if not iters:
        raise RuntimeError(f"No DREAMPlace iteration lines found in {path}")

    result = {
        "initial": iters[0],
        "final": iters[-1],
        "placement_iterations": iters[-1]["iteration"] + 1,
    }

    if bench:
        result.update({
            "num_nodes": int(bench.group(1)),
            "num_terminals": int(bench.group(2)),
            "num_terminal_nis": int(bench.group(3)),
            "num_movable": int(bench.group(4)),
            "num_nets": int(bench.group(5)),
        })

    if runtime:
        result["placement_runtime_sec"] = float(runtime.group(1))

    return result


def load_json(path):
    with open(path) as f:
        return json.load(f)


def append_csv(path, row, fieldnames):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            existing_fieldnames = reader.fieldnames or []
            existing_rows = list(reader)

        if existing_fieldnames != fieldnames:
            for existing_row in existing_rows:
                for field in fieldnames:
                    existing_row.setdefault(field, "")

            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for existing_row in existing_rows:
                    writer.writerow({field: existing_row.get(field, "") for field in fieldnames})

    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists or os.path.getsize(path) == 0:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Summarize a DREAMPlace placement run")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--dreamplace-log", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--placement-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--append-csv", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    dp = parse_dreamplace_log(args.dreamplace_log)
    top_summary = load_json(args.summary_json)
    placement = load_json(args.placement_json)
    chip_info = top_summary.get("chip_info", {})
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = args.run_id or os.environ.get("PLACEMENT_RUN_ID") or timestamp.replace(":", "").replace("+00:00", "Z")

    result = {
        "run_id": run_id,
        "timestamp": timestamp,
        "step": args.step,
        "num_instances": top_summary.get("num_instances"),
        "num_inputs": top_summary.get("num_inputs"),
        "num_outputs": top_summary.get("num_outputs"),
        "num_movable": dp.get("num_movable", placement.get("__num_movable__")),
        "num_terminal_nis": dp.get("num_terminal_nis", top_summary.get("num_inputs", 0) + top_summary.get("num_outputs", 0)),
        "num_nets": dp.get("num_nets", top_summary.get("num_nets")),
        "seeded_components": chip_info.get("seeded_components", 0),
        "seeded_pins": chip_info.get("seeded_pins", 0),
        "initial_hpwl": dp["initial"]["hpwl"],
        "initial_overflow": dp["initial"]["overflow"],
        "initial_max_density": dp["initial"]["max_density"],
        "final_hpwl": dp["final"]["hpwl"],
        "final_overflow": dp["final"]["overflow"],
        "final_max_density": dp["final"]["max_density"],
        "placement_iterations": dp["placement_iterations"],
        "placement_runtime_sec": dp.get("placement_runtime_sec"),
        "converged": dp["final"]["overflow"] < 0.1,
    }

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(result, f, indent=2)

    if args.append_csv:
        fieldnames = [
            "run_id", "timestamp", "step", "num_instances", "num_inputs", "num_outputs", "num_movable",
            "num_terminal_nis", "num_nets", "seeded_components", "seeded_pins",
            "initial_hpwl", "initial_overflow", "initial_max_density",
            "final_hpwl", "final_overflow", "final_max_density",
            "placement_iterations", "placement_runtime_sec", "converged"
        ]
        append_csv(args.append_csv, result, fieldnames)

    print(f"[PlacementSummary] step={result['step']} movable={result['num_movable']} nets={result['num_nets']}")
    print(
        f"[PlacementSummary] seed comp/pin={result['seeded_components']}/{result['seeded_pins']} | "
        f"HPWL {result['initial_hpwl']:.3E} -> {result['final_hpwl']:.3E}"
    )
    print(
        f"[PlacementSummary] overflow {result['initial_overflow']:.3E} -> {result['final_overflow']:.3E} | "
        f"max_density={result['final_max_density']:.3E} | iters={result['placement_iterations']}"
    )
    if result.get("placement_runtime_sec") is not None:
        print(f"[PlacementSummary] runtime={result['placement_runtime_sec']:.3f}s converged={result['converged']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())