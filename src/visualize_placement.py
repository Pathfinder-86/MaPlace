#!/usr/bin/env python3
"""
Visualize DREAMPlace placement output (.gp.def).

Usage:
    python3 visualize_placement.py <path/to/top.gp.def> [output.png]
    python3 visualize_placement.py <def1> <def2> ... --compare --output compare.png
"""

import sys
import re
import os
import json
import argparse
from collections import defaultdict


def parse_lef_macro_sizes(lef_path):
    """Parse macro sizes from a LEF file."""
    sizes = {}
    current_macro = None

    try:
        with open(lef_path) as f:
            for raw_line in f:
                line = raw_line.strip()
                m = re.match(r'MACRO\s+(\S+)', line)
                if m:
                    current_macro = m.group(1)
                    continue
                if current_macro:
                    sm = re.match(r'SIZE\s+([\d\.]+)\s+BY\s+([\d\.]+)\s*;', line)
                    if sm:
                        sizes[current_macro] = (float(sm.group(1)), float(sm.group(2)))
                        continue
                    if line == f'END {current_macro}':
                        current_macro = None
    except OSError:
        return {}

    return sizes


def load_macro_sizes_for_def(def_path):
    """Load macro sizes from sibling LEF files near a generated DEF."""
    search_dirs = [
        os.path.dirname(def_path),
        os.path.dirname(os.path.dirname(def_path)),
        os.path.dirname(os.path.dirname(os.path.dirname(def_path))),
    ]
    sizes = {}
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith('.lef'):
                continue
            sizes.update(parse_lef_macro_sizes(os.path.join(directory, name)))
    return sizes


def oriented_size(width, height, orient):
    """Return width/height adjusted for DEF orientation."""
    if orient in {'W', 'E', 'FW', 'FE'}:
        return height, width
    return width, height

def parse_gp_def(def_path):
    """Parse placed/fixed cell positions from a DEF file."""
    instances = []  # (inst_name, cell_type, x_dbu, y_dbu, orient)
    pins = []       # (pin_name, x_dbu, y_dbu, status)
    dbu_per_um = 1000
    die = None

    in_components = False
    in_pins = False
    current_inst = None
    current_type = None

    with open(def_path) as f:
        for line in f:
            line = line.strip()

            # UNITS
            m = re.match(r'UNITS DISTANCE MICRONS (\d+)', line)
            if m:
                dbu_per_um = int(m.group(1))
                continue

            # DIEAREA
            m = re.match(r'DIEAREA\s+\(\s*(\d+)\s+(\d+)\s*\)\s+\(\s*(\d+)\s+(\d+)\s*\)', line)
            if m:
                die = tuple(int(x) / dbu_per_um for x in m.groups())
                continue

            # COMPONENTS section
            if re.match(r'COMPONENTS\s+\d+', line):
                in_components = True
                in_pins = False
                continue
            if line == 'END COMPONENTS':
                in_components = False
                current_inst = None
                continue

            # PINS section
            if re.match(r'PINS\s+\d+', line):
                in_pins = True
                in_components = False
                continue
            if line == 'END PINS':
                in_pins = False
                continue

            if in_components:
                # New instance line: "- instname celltype ;"
                m = re.match(r'-\s+(\S+)\s+(\S+)', line)
                if m:
                    current_inst = m.group(1)
                    current_type = m.group(2)
                    # Check if PLACED is on same line
                    pm = re.search(r'\+\s+(PLACED|FIXED)\s+\(\s*(\d+)\s+(\d+)\s*\)\s+(\S+)', line)
                    if pm:
                        x, y = int(pm.group(2)), int(pm.group(3))
                        orient = pm.group(4).rstrip(';')
                        instances.append((current_inst, current_type,
                                          x / dbu_per_um, y / dbu_per_um, orient))
                        current_inst = None
                    continue

                # Continuation line with PLACED
                if current_inst:
                    pm = re.search(r'\+\s+(PLACED|FIXED)\s+\(\s*(\d+)\s+(\d+)\s*\)\s+(\S+)', line)
                    if pm:
                        x, y = int(pm.group(2)), int(pm.group(3))
                        orient = pm.group(4).rstrip(';')
                        instances.append((current_inst, current_type,
                                          x / dbu_per_um, y / dbu_per_um, orient))
                        current_inst = None

            if in_pins:
                # "- pinname + NET ..."
                m = re.match(r'-\s+(\S+)', line)
                if m:
                    current_pin = m.group(1)
                pm2 = re.search(r'\+\s+(PLACED|FIXED)\s+\(\s*(\d+)\s+(\d+)\s*\)', line)
                if pm2:
                    x, y = int(pm2.group(2)), int(pm2.group(3))
                    pins.append((current_pin, x / dbu_per_um, y / dbu_per_um, pm2.group(1)))

    return instances, pins, die, dbu_per_um


def load_summary_for_def(def_path):
    summary_path = os.path.join(os.path.dirname(os.path.dirname(def_path)), 'placement_summary.json')
    if not os.path.exists(summary_path):
        return None
    try:
        with open(summary_path) as f:
            return json.load(f)
    except Exception:
        return None


def cell_family(cell_type):
    """Return a coarse cell family for coloring."""
    ct = cell_type.lower()
    if 'inv' in ct:    return 'INV'
    if 'buf' in ct:    return 'BUF'
    if 'nand' in ct:   return 'NAND'
    if 'nor' in ct:    return 'NOR'
    if 'and' in ct:    return 'AND'
    if 'or' in ct:     return 'OR'
    if 'xor' in ct:    return 'XOR'
    if 'xnor' in ct:   return 'XNOR'
    if 'mux' in ct:    return 'MUX'
    if 'dff' in ct or 'ff' in ct: return 'FF'
    if 'ao' in ct or 'oa' in ct:  return 'AOI/OAI'
    return 'OTHER'


def plot_single_layout(ax, ax2, def_file, instances, pins, die, summary, family_colors,
                       show_heatmap=True, render_style='boxes'):
    import matplotlib.patches as mpatches
    from matplotlib.collections import PatchCollection

    macro_sizes = load_macro_sizes_for_def(def_file)

    if render_style == 'points':
        family_xy = defaultdict(lambda: ([], []))
        for _, ct, x, y, _ in instances:
            fam = cell_family(ct)
            family_xy[fam][0].append(x)
            family_xy[fam][1].append(y)

        for fam, (xs, ys) in sorted(family_xy.items()):
            color = family_colors.get(fam, '#a9a9a9')
            ax.scatter(xs, ys, s=1.0, c=color, label=f'{fam} ({len(xs)})', alpha=0.7, linewidths=0)
    else:
        patches = []
        edgecolors = []
        missing_size_xy = ([], [])
        for _, ct, x, y, orient in instances:
            size = macro_sizes.get(ct)
            if not size:
                missing_size_xy[0].append(x)
                missing_size_xy[1].append(y)
                continue
            w, h = oriented_size(size[0], size[1], orient)
            patches.append(mpatches.Rectangle((x, y), w, h))
            edgecolors.append(family_colors.get(cell_family(ct), '#4e79a7'))

        if patches:
            pc = PatchCollection(
                patches,
                facecolor='#d9e2f3',
                edgecolor=edgecolors,
                linewidth=0.35,
                alpha=0.85,
                match_original=False,
                rasterized=True,
            )
            ax.add_collection(pc)

        if missing_size_xy[0]:
            ax.scatter(missing_size_xy[0], missing_size_xy[1], s=1.2, c='#7f7f7f', alpha=0.6,
                       linewidths=0, label=f'unknown-size cells ({len(missing_size_xy[0])})')

    if pins:
        px = [p[1] for p in pins]
        py = [p[2] for p in pins]
        ax.scatter(px, py, s=16, c='#c00000', marker='s', label=f'IO pins ({len(pins)})', zorder=6,
                   edgecolors='white', linewidths=0.3)

    if die:
        rect = mpatches.Rectangle((die[0], die[1]), die[2]-die[0], die[3]-die[1],
                                   linewidth=1.5, edgecolor='black', facecolor='none')
        ax.add_patch(rect)
        ax.set_xlim(die[0] - 0.5, die[2] + 0.5)
        ax.set_ylim(die[1] - 0.5, die[3] + 0.5)

    title = os.path.basename(def_file)
    if summary:
        title += f"\nstep={summary.get('step')}  ovf {summary.get('initial_overflow', 0):.3f}->{summary.get('final_overflow', 0):.3f}"
        title += f"  hpwl {summary.get('initial_hpwl', 0):.0f}->{summary.get('final_hpwl', 0):.0f}"
    ax.set_xlabel('X (μm)')
    ax.set_ylabel('Y (μm)')
    ax.set_title(title)
    ax.set_aspect('equal', adjustable='box')
    ax.set_facecolor('#f7f7f7')
    ax.grid(False)

    if not show_heatmap or ax2 is None:
        return None

    xs_all = [inst[2] for inst in instances]
    ys_all = [inst[3] for inst in instances]
    h = ax2.hist2d(xs_all, ys_all, bins=40,
                   range=[[die[0], die[2]], [die[1], die[3]]] if die else None,
                   cmap='YlOrRd')
    if die:
        ax2.set_xlim(die[0] - 0.5, die[2] + 0.5)
        ax2.set_ylim(die[1] - 0.5, die[3] + 0.5)
    ax2.set_xlabel('X (μm)')
    ax2.set_ylabel('Y (μm)')
    ax2.set_title('Density Heatmap')
    ax2.set_aspect('equal', adjustable='box')
    return h


def main():
    ap = argparse.ArgumentParser(description='Visualize DREAMPlace .gp.def placement')
    ap.add_argument('def_files', nargs='+', help='One or more .gp.def files')
    ap.add_argument('--output', default=None,
                    help='Output image path (default: same dir as def file(s), placement.png or placement_compare.png)')
    ap.add_argument('--no-show', action='store_true',
                    help='Do not open interactive window, just save')
    ap.add_argument('--compare', action='store_true',
                    help='Render multiple DEFs into a single comparison figure')
    ap.add_argument('--layout-only', action='store_true',
                    help='Render only the placement layout without the density heatmap')
    ap.add_argument('--style', choices=['boxes', 'points'], default='boxes',
                    help='Layout rendering style (default: boxes)')
    args = ap.parse_args()

    if len(args.def_files) > 1:
        args.compare = True

    parsed = []
    for def_file in args.def_files:
        print(f"Parsing {def_file} ...")
        instances, pins, die, dbu_per_um = parse_gp_def(def_file)
        summary = load_summary_for_def(def_file)
        print(f"  Cells:    {len(instances)}")
        print(f"  IO pins:  {len(pins)}")
        print(f"  Die:      {die[2]:.3f} × {die[3]:.3f}  μm" if die else "  Die:      unknown")
        if summary:
            print(f"  Summary:  HPWL {summary.get('initial_hpwl', 0):.0f}->{summary.get('final_hpwl', 0):.0f}, "
                  f"overflow {summary.get('initial_overflow', 0):.3f}->{summary.get('final_overflow', 0):.3f}, "
                  f"converged={summary.get('converged')}")

        family_counts = defaultdict(int)
        for _, ct, *_ in instances:
            family_counts[cell_family(ct)] += 1
        print("\nCell family breakdown:")
        for fam, cnt in sorted(family_counts.items(), key=lambda x: -x[1]):
            print(f"  {fam:<12} {cnt:>5}")
        print()
        parsed.append((def_file, instances, pins, die, summary))

    # ── Plot ──────────────────────────────────────────────────────────────────
    try:
        import matplotlib
        if args.no_show:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed. Run: pip install matplotlib")
        sys.exit(1)

    FAMILY_COLORS = {
        'INV':     '#4e79a7',
        'BUF':     '#76b7b2',
        'NAND':    '#f28e2b',
        'NOR':     '#e15759',
        'AND':     '#59a14f',
        'OR':      '#edc948',
        'XOR':     '#b07aa1',
        'XNOR':    '#ff9da7',
        'MUX':     '#9c755f',
        'FF':      '#bab0ac',
        'AOI/OAI': '#d37295',
        'OTHER':   '#a9a9a9',
    }

    cols = len(parsed) if args.compare else 1
    rows = 1 if args.layout_only else 2
    fig_height = 7 if args.layout_only else (12 if args.compare else 7)
    fig, axes = plt.subplots(rows, cols, figsize=(7 * cols, fig_height), squeeze=False)
    heatmaps = []
    for idx, (def_file, instances, pins, die, summary) in enumerate(parsed[:cols]):
        ax2 = None if args.layout_only else axes[1][idx]
        h = plot_single_layout(axes[0][idx], ax2, def_file, instances, pins, die, summary, FAMILY_COLORS,
                               show_heatmap=not args.layout_only, render_style=args.style)
        heatmaps.append(h)
        if idx == cols - 1:
            handles = [
                plt.Line2D([0], [0], color='#4e79a7', lw=1.2, label='standard cells'),
                plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#c00000',
                           markeredgecolor='white', markersize=7, label='IO pins'),
            ]
            axes[0][idx].legend(handles=handles, fontsize=8, loc='upper right')
    if not args.layout_only:
        for idx, h in enumerate(heatmaps):
            plt.colorbar(h[3], ax=axes[1][idx], label='Cell count per bin')

    title = 'Placement Comparison' if args.compare else os.path.basename(parsed[0][0])
    plt.suptitle(title, fontsize=12, y=0.995)
    plt.tight_layout()

    # Save
    if args.output:
        out_path = args.output
    else:
        if args.compare:
            common_dir = os.path.commonpath([os.path.dirname(p[0]) for p in parsed])
            out_path = os.path.join(common_dir, 'placement_compare.png')
        else:
            out_path = os.path.join(os.path.dirname(parsed[0][0]), 'placement.png')
    plt.savefig(out_path, dpi=180, bbox_inches='tight')
    print(f"\nSaved → {out_path}")

    if not args.no_show:
        plt.show()


if __name__ == '__main__':
    main()
