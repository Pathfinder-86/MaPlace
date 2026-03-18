#!/usr/bin/env python3
"""
Metrics Analyzer & Dashboard Plotter
-------------------------------------
Aggregate GradMap (torch_metrics.csv) + DREAMPlace (placement_metrics.csv)
and generate QoR dashboard with dual-axis and comparison plots.

Usage (Command Line):
  python3 metrics_analyzer.py \
    --torch-csv /path/to/torch_metrics.csv \
    --place-csv /path/to/placement_metrics.csv \
    --config /path/to/metrics_plot_config.yaml \
    --output-dir /tmp/maplace_report

Usage (From Code):
  from metrics_analyzer import generate_dashboard
  generate_dashboard(
    torch_csv='validation/torch_metrics.csv',
    place_csv='validation/placement_metrics.csv',
    output_dir='validation/metrics_report',
    plot_config='config/metrics_plot_config.yaml'
  )
"""

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import yaml


def read_csv(filepath: str) -> Dict[str, List]:
    """Read CSV and return dict of {column_name: [values]}"""
    data = {}
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key, value in row.items():
                if key not in data:
                    data[key] = []
                try:
                    # Try to parse as number
                    data[key].append(float(value))
                except (ValueError, TypeError):
                    data[key].append(value)
    return data


def aggregate_metrics(torch_data: Dict, place_data: Dict) -> Dict:
    """
    Merge torch_metrics and placement_metrics by step.
    Returns: {step: {metric_name: value, ...}, ...}
    """
    combined = {}

    steps_torch = torch_data.get('step', [])
    steps_place = place_data.get('step', [])

    # Create unified step list
    all_steps = sorted(set(
        [int(s) for s in steps_torch if isinstance(s, (int, float))] +
        [int(s) for s in steps_place if isinstance(s, (int, float))]
    ))

    for step in all_steps:
        combined[step] = {}

        # Add torch metrics
        try:
            idx = int(steps_torch.index(step))
            for key, values in torch_data.items():
                if key != 'step' and idx < len(values):
                    combined[step][f'torch_{key}'] = values[idx]
        except (ValueError, IndexError):
            pass

        # Add placement metrics
        try:
            idx = int(steps_place.index(step))
            for key, values in place_data.items():
                if key != 'step' and idx < len(values):
                    combined[step][f'place_{key}'] = values[idx]
        except (ValueError, IndexError):
            pass

    return combined


def compute_derived_metrics(combined: Dict) -> Dict:
    """Compute QoR cost and other derived metrics"""
    for step_data in combined.values():
        # QoR cost = area + delay (normalized)
        area = step_data.get('torch_area', 0)
        delay = step_data.get('torch_delay', 0)
        if area > 0 and delay > 0:
            step_data['derived_qor_cost'] = area + delay

        # Convergence indicator
        converged = step_data.get('place_converged', None)
        if isinstance(converged, str):
            step_data['derived_converged'] = 1 if converged.lower() in ['true', 'yes', '1'] else 0
        else:
            step_data['derived_converged'] = converged

    return combined


def plot_single_metric(steps: List[int], values: List, metric_name: str,
                       unit: str, color: str, output_path: str,
                       threshold: Optional[float] = None,
                       baseline_value: Optional[float] = None):
    """Plot single metric with optional threshold line"""
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(steps, values, marker='o', linestyle='-', linewidth=2,
            color=color, label=metric_name, markersize=5)

    if threshold is not None:
        ax.axhline(y=threshold, color='red', linestyle='--',
                   linewidth=1.5, label=f'Threshold: {threshold}')

    # Baseline line
    if baseline_value is not None:
        ax.axhline(y=baseline_value, color='gray', linestyle=':', 
                   linewidth=2.0, label=f'ABC Baseline: {baseline_value:.2f}')

    ax.set_xlabel('Optimization Step', fontsize=12)
    ax.set_ylabel(f'{metric_name} ({unit})', fontsize=12, color=color)
    ax.tick_params(axis='y', labelcolor=color)
    ax.grid(True, alpha=0.3)
    ax.set_title(f'{metric_name} Trend', fontsize=14, fontweight='bold')

    if threshold is None:
        ax.legend(loc='best', fontsize=10)
    else:
        ax.legend(loc='best', fontsize=10)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"✅ Saved: {output_path}")


def plot_dual_axis(steps: List[int], left_values: List, right_values: List,
                   left_metric: str, right_metric: str,
                   left_unit: str, right_unit: str,
                   left_color: str, right_color: str,
                   output_path: str):
    """Plot two metrics on dual axes"""
    fig, ax1 = plt.subplots(figsize=(12, 6))

    # Left axis
    ax1.plot(steps, left_values, marker='o', linestyle='-', linewidth=2.5,
             color=left_color, label=f'{left_metric} ({left_unit})', markersize=6)
    ax1.set_xlabel('Optimization Step', fontsize=12)
    ax1.set_ylabel(f'{left_metric} ({left_unit})', fontsize=12, color=left_color)
    ax1.tick_params(axis='y', labelcolor=left_color)
    ax1.grid(True, alpha=0.3)

    # Right axis
    ax2 = ax1.twinx()
    ax2.plot(steps, right_values, marker='s', linestyle='--', linewidth=2.5,
             color=right_color, label=f'{right_metric} ({right_unit})', markersize=6)
    ax2.set_ylabel(f'{right_metric} ({right_unit})', fontsize=12, color=right_color)
    ax2.tick_params(axis='y', labelcolor=right_color)

    # Title and legend
    fig.suptitle(f'{left_metric} vs {right_metric}', fontsize=14, fontweight='bold')
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"✅ Saved: {output_path}")


def plot_convergence_heatmap(combined: Dict, place_steps: List[int], output_path: str):
    """Plot placement convergence and owner_conflicts status (placement_steps only)"""
    if not place_steps:
        return

    converged_status = []
    owner_conflicts = []

    for step in place_steps:
        conv = combined[step].get('derived_converged', None)
        conflicts = combined[step].get('place_owner_conflicts', 0)

        converged_status.append(1 if conv == 1 else 0)
        owner_conflicts.append(int(conflicts) if conflicts else 0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 6), sharex=True)

    # Convergence heatmap
    colors_conv = ['🔴 Not Converged' if c == 0 else '🟢 Converged' for c in converged_status]
    ax1.bar(place_steps, [1]*len(place_steps), color=['red' if c == 0 else 'green' for c in converged_status],
            alpha=0.7, edgecolor='black')
    ax1.set_ylabel('Convergence Status', fontsize=11)
    ax1.set_ylim([0, 1.5])
    ax1.set_yticks([])
    ax1.grid(True, alpha=0.3, axis='x')
    ax1.set_title('Placement Convergence Status', fontsize=12, fontweight='bold')

    # Owner conflicts
    ax2.bar(place_steps, owner_conflicts, color='orange', alpha=0.7, edgecolor='black')
    ax2.set_xlabel('Optimization Step', fontsize=12)
    ax2.set_ylabel('Owner Conflicts', fontsize=11)
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.set_title('Match Ownership Conflicts', fontsize=12, fontweight='bold')

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"✅ Saved: {output_path}")


def generate_summary_report(combined: Dict, output_path: str):
    """Generate text summary report"""
    steps = sorted(combined.keys())

    with open(output_path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write("MaPlace QoR Summary Report\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Total optimization steps: {len(steps)}\n")
        f.write(f"Step range: {steps[0]} → {steps[-1]}\n\n")

        # Metrics at key checkpoints
        for checkpoint_step in [steps[0], steps[len(steps)//2], steps[-1]]:
            data = combined[checkpoint_step]
            f.write(f"--- Step {checkpoint_step} ---\n")

            if 'torch_delay' in data:
                f.write(f"  Delay:    {data['torch_delay']:.2f} ps\n")
            if 'torch_area' in data:
                f.write(f"  Area:     {data['torch_area']:.2f} μm²\n")
            if 'place_final_hpwl' in data or 'place_HPWL' in data:
                hpwl = data.get('place_final_hpwl', data.get('place_HPWL', 0))
                f.write(f"  HPWL:     {hpwl:.1f} μm\n")
            if 'place_final_overflow' in data or 'place_overflow' in data:
                overflow = data.get('place_final_overflow', data.get('place_overflow', 0))
                f.write(f"  Overflow: {overflow:.4f}\n")
            if 'derived_converged' in data:
                conv_str = "✓ Yes" if data['derived_converged'] == 1 else "✗ No"
                f.write(f"  Converged: {conv_str}\n")

            f.write("\n")

        f.write("=" * 70 + "\n")
        f.write("Improvements Summary\n")
        f.write("=" * 70 + "\n")

        first = combined[steps[0]]
        last = combined[steps[-1]]

        if 'torch_delay' in first and 'torch_delay' in last:
            delay_improve = ((first['torch_delay'] - last['torch_delay']) / first['torch_delay']) * 100
            f.write(f"Delay improvement: {delay_improve:.1f}% ({first['torch_delay']:.1f} → {last['torch_delay']:.1f} ps)\n")

        if 'place_final_overflow' in first and 'place_final_overflow' in last:
            overflow_first = first.get('place_final_overflow', 0)
            overflow_last = last.get('place_final_overflow', 0)
            f.write(f"Overflow trend: {overflow_first:.4f} → {overflow_last:.4f}\n")

        f.write("\n")


def generate_dashboard(torch_csv: str, place_csv: str, output_dir: str,
                       plot_config: Optional[str] = None) -> bool:
    """
    Generate QoR dashboard from metrics CSVs.

    Handles different sampling rates:
    - torch_metrics: eval_interval (typically 20)
    - placement_metrics: placement_interval (typically 50)

    Args:
        torch_csv: Path to torch_metrics.csv (GradMap)
        place_csv: Path to placement_metrics.csv (DREAMPlace)
        output_dir: Output directory for plots and reports
        plot_config: Optional path to YAML config (for future extensibility)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        print(f"📖 Reading torch_metrics from: {torch_csv}")
        if not os.path.exists(torch_csv):
            print(f"⚠️ Warning: torch_metrics.csv not found: {torch_csv}")
            torch_data = {}
        else:
            torch_data = read_csv(torch_csv)

        print(f"📖 Reading placement_metrics from: {place_csv}")
        if not os.path.exists(place_csv):
            print(f"⚠️ Warning: placement_metrics.csv not found: {place_csv}")
            place_data = {}
        else:
            place_data = read_csv(place_csv)

        if not torch_data and not place_data:
            print("❌ Error: No metrics data found!")
            return False

        # Aggregate
        print("🔗 Aggregating metrics...")
        combined = aggregate_metrics(torch_data, place_data)
        combined = compute_derived_metrics(combined)

        # Write combined CSV
        combined_csv = os.path.join(output_dir, 'combined_metrics.csv')
        print(f"💾 Writing combined metrics to: {combined_csv}")
        if combined:
            steps = sorted(combined.keys())
            all_keys = set()
            for data in combined.values():
                all_keys.update(data.keys())

            with open(combined_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['step'] + sorted(all_keys))
                for step in steps:
                    row = [step]
                    for key in sorted(all_keys):
                        row.append(combined[step].get(key, ''))
                    writer.writerow(row)

        # Generate plots
        steps = sorted(combined.keys())

        # Separate torch steps (eval_interval) and placement steps (placement_interval)
        torch_steps = [s for s in steps if 'torch_delay' in combined[s]]
        place_steps = [s for s in steps if 'place_final_overflow' in combined[s]]

        print("\n📊 Generating plots...\n")

        # 1. Delay curve (torch_steps only)
        if torch_steps:
            delays = [combined[s].get('torch_delay', 0) for s in torch_steps]
            if all(d > 0 for d in delays):
                plot_single_metric(torch_steps, delays, 'Delay', 'ps', 'red',
                                  os.path.join(output_dir, '01_delay_trend.png'))

        # 2. Area curve (torch_steps only)
        if torch_steps:
            areas = [combined[s].get('torch_area', 0) for s in torch_steps]
            if all(a > 0 for a in areas):
                plot_single_metric(torch_steps, areas, 'Area', 'μm²', 'blue',
                                  os.path.join(output_dir, '02_area_trend.png'))

        # 3. Overflow curve (placement_steps only)
        if place_steps:
            overflows = [combined[s].get('place_final_overflow', 0) for s in place_steps]
            if any(o > 0 for o in overflows):
                plot_single_metric(place_steps, overflows, 'Overflow', '%', 'orange',
                                  os.path.join(output_dir, '03_overflow_trend.png'),
                                  threshold=0.1)

        # 4. HPWL curve (placement_steps only)
        if place_steps:
            hpwls = [combined[s].get('place_final_hpwl', 0) for s in place_steps]
            if any(h > 0 for h in hpwls):
                plot_single_metric(place_steps, hpwls, 'HPWL', 'μm', 'green',
                                  os.path.join(output_dir, '04_hpwl_trend.png'))

        # 5. Max density curve (placement_steps only)
        if place_steps:
            densities = [combined[s].get('place_final_max_density', 0) for s in place_steps]
            if any(d > 0 for d in densities):
                plot_single_metric(place_steps, densities, 'Max Density', 'ratio', 'purple',
                                  os.path.join(output_dir, '05_max_density_trend.png'),
                                  threshold=1.0)

        # 6. Dual-axis: Delay vs HPWL (aligned steps)
        if torch_steps and place_steps:
            # Find common steps (torch_steps that overlap with place_steps)
            common_steps = sorted(set(torch_steps) & set(place_steps))
            if common_steps:
                delays = [combined[s].get('torch_delay', 0) for s in common_steps]
                hpwls = [combined[s].get('place_final_hpwl', 0) for s in common_steps]
                if all(d > 0 for d in delays) and any(h > 0 for h in hpwls):
                    plot_dual_axis(common_steps, delays, hpwls, 'Delay', 'HPWL', 'ps', 'μm',
                                  'red', 'green', os.path.join(output_dir, '06_delay_vs_hpwl.png'))

        # 7. Dual-axis: Area vs Overflow (aligned steps)
        if torch_steps and place_steps:
            common_steps = sorted(set(torch_steps) & set(place_steps))
            if common_steps:
                areas = [combined[s].get('torch_area', 0) for s in common_steps]
                overflows = [combined[s].get('place_final_overflow', 0) for s in common_steps]
                if all(a > 0 for a in areas) and any(o > 0 for o in overflows):
                    plot_dual_axis(common_steps, areas, overflows, 'Area', 'Overflow', 'μm²', '%',
                                  'blue', 'orange', os.path.join(output_dir, '07_area_vs_overflow.png'))

        # 8. Convergence heatmap (placement_steps only)
        if place_steps and any('derived_converged' in combined[s] for s in place_steps):
            plot_convergence_heatmap(combined, place_steps, os.path.join(output_dir, '08_convergence_heatmap.png'))

        # Generate summary report (use all steps)
        print("\n📝 Generating summary report...\n")
        generate_summary_report(combined, os.path.join(output_dir, 'summary_report.txt'))

        print(f"\n✅ Dashboard generated! Output directory: {output_dir}\n")
        print("Files generated:")
        for f in sorted(os.listdir(output_dir)):
            print(f"  - {f}")

        return True

    except Exception as e:
        print(f"❌ Error generating dashboard: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description='MaPlace Metrics Analyzer & Dashboard Plotter')
    parser.add_argument('--torch-csv', required=True, help='Path to torch_metrics.csv')
    parser.add_argument('--place-csv', required=True, help='Path to placement_metrics.csv')
    parser.add_argument('--config', default=None, help='Path to metrics_plot_config.yaml (optional)')
    parser.add_argument('--output-dir', default='/tmp/maplace_report', help='Output directory')

    args = parser.parse_args()

    success = generate_dashboard(
        torch_csv=args.torch_csv,
        place_csv=args.place_csv,
        output_dir=args.output_dir,
        plot_config=args.config
    )

    exit(0 if success else 1)


if __name__ == '__main__':
    main()
