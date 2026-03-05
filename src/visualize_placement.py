#!/usr/bin/env python3
"""
Visualize DREAMPlace placement output (.gp.def)

Usage:
    python3 visualize_placement.py <path/to/top.gp.def> [output.png]
"""

import sys
import re
import os
import argparse
from collections import defaultdict

def parse_gp_def(def_path):
    """Parse PLACED cell positions from a DEF file."""
    instances = []  # (inst_name, cell_type, x_dbu, y_dbu, orient)
    pins = []       # (pin_name, x_dbu, y_dbu)
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
                    pm = re.search(r'\+\s+PLACED\s+\(\s*(\d+)\s+(\d+)\s*\)\s+(\S+)', line)
                    if pm:
                        x, y = int(pm.group(1)), int(pm.group(2))
                        orient = pm.group(3).rstrip(';')
                        instances.append((current_inst, current_type,
                                          x / dbu_per_um, y / dbu_per_um, orient))
                        current_inst = None
                    continue

                # Continuation line with PLACED
                if current_inst:
                    pm = re.search(r'\+\s+PLACED\s+\(\s*(\d+)\s+(\d+)\s*\)\s+(\S+)', line)
                    if pm:
                        x, y = int(pm.group(1)), int(pm.group(2))
                        orient = pm.group(3).rstrip(';')
                        instances.append((current_inst, current_type,
                                          x / dbu_per_um, y / dbu_per_um, orient))
                        current_inst = None

            if in_pins:
                # "- pinname + NET ..."
                m = re.match(r'-\s+(\S+)', line)
                if m:
                    current_pin = m.group(1)
                pm2 = re.search(r'\+\s+PLACED\s+\(\s*(\d+)\s+(\d+)\s*\)', line)
                if pm2:
                    x, y = int(pm2.group(1)), int(pm2.group(2))
                    pins.append((current_pin, x / dbu_per_um, y / dbu_per_um))

    return instances, pins, die, dbu_per_um


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


def main():
    ap = argparse.ArgumentParser(description='Visualize DREAMPlace .gp.def placement')
    ap.add_argument('def_file', help='Path to .gp.def file')
    ap.add_argument('output', nargs='?', default=None,
                    help='Output image path (default: same dir as def_file, placement.png)')
    ap.add_argument('--no-show', action='store_true',
                    help='Do not open interactive window, just save')
    args = ap.parse_args()

    print(f"Parsing {args.def_file} ...")
    instances, pins, die, dbu_per_um = parse_gp_def(args.def_file)

    print(f"  Cells:    {len(instances)}")
    print(f"  IO pins:  {len(pins)}")
    print(f"  Die:      {die[2]:.3f} × {die[3]:.3f}  μm" if die else "  Die:      unknown")

    # Count by family
    family_counts = defaultdict(int)
    for _, ct, *_ in instances:
        family_counts[cell_family(ct)] += 1
    print("\nCell family breakdown:")
    for fam, cnt in sorted(family_counts.items(), key=lambda x: -x[1]):
        print(f"  {fam:<12} {cnt:>5}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    try:
        import matplotlib
        if args.no_show:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
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

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # --- Left: scatter by cell family ---
    ax = axes[0]
    family_xy = defaultdict(lambda: ([], []))
    for _, ct, x, y, _ in instances:
        fam = cell_family(ct)
        family_xy[fam][0].append(x)
        family_xy[fam][1].append(y)

    for fam, (xs, ys) in sorted(family_xy.items()):
        color = FAMILY_COLORS.get(fam, '#a9a9a9')
        ax.scatter(xs, ys, s=0.8, c=color, label=f'{fam} ({len(xs)})', alpha=0.7, linewidths=0)

    if pins:
        px = [p[1] for p in pins]
        py = [p[2] for p in pins]
        ax.scatter(px, py, s=8, c='black', marker='^', label=f'IO pins ({len(pins)})', zorder=5)

    if die:
        rect = mpatches.Rectangle((die[0], die[1]), die[2]-die[0], die[3]-die[1],
                                   linewidth=1.5, edgecolor='black', facecolor='none')
        ax.add_patch(rect)
        ax.set_xlim(die[0] - 0.5, die[2] + 0.5)
        ax.set_ylim(die[1] - 0.5, die[3] + 0.5)

    ax.set_xlabel('X (μm)')
    ax.set_ylabel('Y (μm)')
    ax.set_title(f'Cell Placement by Type  ({len(instances)} cells)')
    ax.legend(markerscale=5, fontsize=7, loc='upper right', ncol=2)
    ax.set_aspect('equal', adjustable='box')
    ax.grid(True, linewidth=0.3, alpha=0.5)

    # --- Right: 2D density heatmap ---
    ax2 = axes[1]
    xs_all = [inst[2] for inst in instances]
    ys_all = [inst[3] for inst in instances]

    h = ax2.hist2d(xs_all, ys_all, bins=40,
                   range=[[die[0], die[2]], [die[1], die[3]]] if die else None,
                   cmap='YlOrRd')
    plt.colorbar(h[3], ax=ax2, label='Cell count per bin')

    if die:
        ax2.set_xlim(die[0] - 0.5, die[2] + 0.5)
        ax2.set_ylim(die[1] - 0.5, die[3] + 0.5)

    ax2.set_xlabel('X (μm)')
    ax2.set_ylabel('Y (μm)')
    ax2.set_title('Cell Density Heatmap')
    ax2.set_aspect('equal', adjustable='box')

    plt.suptitle(
        os.path.basename(args.def_file) +
        (f'   Die: {die[2]:.2f}×{die[3]:.2f} μm' if die else ''),
        fontsize=11, y=1.01
    )
    plt.tight_layout()

    # Save
    out_path = args.output or os.path.join(os.path.dirname(args.def_file), 'placement.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"\nSaved → {out_path}")

    if not args.no_show:
        plt.show()


if __name__ == '__main__':
    main()
