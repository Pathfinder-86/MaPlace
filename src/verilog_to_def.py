#!/usr/bin/env python3
"""
verilog_to_def.py
-----------------
把 GradMap 輸出的 gate-level Verilog 轉成 DREAMPlace 可以吃的 LEF + DEF。

用法:
    python verilog_to_def.py <input.v> <output_dir> [options]

選項:
    --libcell <path>      asap7_libcell_info.txt 路徑
    --lef <path>          外部 LEF 檔案（若提供則不生成合成 LEF）
    --utilization <float> 目標使用率 (default: 0.70)
    --design-name <str>   覆蓋設計名稱

輸出:
    <output_dir>/<design>.lef    合成 ASAP7 LEF（若無外部 LEF）
    <output_dir>/<design>.def    帶 COMPONENTS + NETS + PINS 的 DEF
    <output_dir>/<design>.json   DREAMPlace params 設定檔
    <output_dir>/<design>_summary.json  instance 清單（供後續讀回 placement 用）
"""

import re
import os
import sys
import math
import json
import argparse
from collections import defaultdict

# =========================================================
# ASAP7 物理常數（根據 asap7_libcell_info.txt area 反推）
# cell height = 0.270 μm，site width (CPP) = 0.054 μm
# =========================================================
CELL_HEIGHT_UM  = 0.270   # μm  (7.5T standard cell)
SITE_WIDTH_UM   = 0.054   # μm  (CPP: Contacted Poly Pitch)
DBU_PER_UM      = 1000    # 1 DBU = 1 nm，DEF UNITS DISTANCE MICRONS 1000

CELL_HEIGHT_DBU = int(CELL_HEIGHT_UM * DBU_PER_UM)   # 270
SITE_WIDTH_DBU  = int(SITE_WIDTH_UM  * DBU_PER_UM)   # 54

# ASAP7 標準輸出 pin 命名
OUTPUT_PIN_NAMES = {'Y', 'Z', 'ZN', 'CON', 'SN', 'QN', 'Q', 'CO', 'S'}

DEFAULT_AREA_UM2 = 0.10    # 找不到 cell 時的面積 fallback


# =========================================================
# 1. 解析 asap7_libcell_info.txt
# =========================================================
def parse_libcell_info(path: str) -> dict:
    """
    回傳 {cell_name: {'area': float, 'output_pin': str, 'input_pins': [str], 'all_pins': [str]}}
    """
    cells = {}
    with open(path) as f:
        content = f.read()

    # 以 "libcell:" 為分隔符拆 block
    blocks = re.split(r'\n(?=libcell:)', content)

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines()]
        if not lines or not lines[0].startswith('libcell:'):
            continue

        cell_name = lines[0].split(':', 1)[1].strip()
        info = {
            'area': DEFAULT_AREA_UM2,
            'output_pin': 'Y',
            'input_pins': [],
            'all_pins': []
        }

        in_header = True  # 在 luts 之前是 header
        for line in lines[1:]:
            if not line:
                continue
            if line.startswith('luts_num:'):
                in_header = False
                break
            if line.startswith('area:'):
                try:
                    info['area'] = float(line.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith('output_pin:'):
                info['output_pin'] = line.split(':', 1)[1].strip()
            elif line.startswith('input_pins_num:'):
                pass
            elif in_header and re.match(r'^([A-Za-z]\w*)\s+[\d.]+\s*$', line):
                # pin cap 行，e.g. "A1 0.596102"
                pin_name = line.split()[0]
                info['input_pins'].append(pin_name)

        info['all_pins'] = [info['output_pin']] + info['input_pins']
        cells[cell_name] = info

    return cells


# =========================================================
# 2. 解析 gate-level Verilog
# =========================================================
def parse_verilog(path: str):
    """
    解析 gate-level Verilog netlist。

    回傳:
        module_name : str
        inputs      : list[str]   primary input port names
        outputs     : list[str]   primary output port names
        instances   : list[(cell_type, inst_name, {pin: net})]
        all_nets    : set[str]    全部 wire/net 名稱
    """
    with open(path) as f:
        content = f.read()

    # 移除 comment
    content = re.sub(r'//[^\n]*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    # module 名稱
    mm = re.search(r'\bmodule\s+(\w+)\s*\(', content)
    module_name = mm.group(1) if mm else 'top'

    # primary inputs / outputs
    def extract_ports(keyword):
        ports = []
        for m in re.finditer(rf'\b{keyword}\b\s+(.*?)\s*;', content, re.DOTALL):
            raw = m.group(1)
            raw = re.sub(r'\s+', ' ', raw)
            ports.extend(n.strip() for n in raw.split(',') if n.strip())
        return ports

    inputs  = extract_ports('input')
    outputs = extract_ports('output')

    # gate instantiations
    # 格式: CELL_TYPE inst_name ( .pin(net), .pin(net) ) ;
    inst_pat = re.compile(
        r'([A-Za-z]\w*)\s+([A-Za-z]\w*)\s*\('   # cell_type inst_name (
        r'((?:[^()]*\([^()]*\)[^()]*)*)'         # port connections
        r'\)\s*;',
        re.DOTALL
    )

    skip = {'module', 'input', 'output', 'wire', 'reg', 'inout', 'assign', 'endmodule'}
    instances = []

    for m in inst_pat.finditer(content):
        cell_type = m.group(1)
        inst_name = m.group(2)
        port_str  = m.group(3)

        if cell_type in skip or cell_type == module_name:
            continue

        port_conns = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*(\w+)\s*\)', port_str):
            port_conns[pm.group(1)] = pm.group(2)

        if port_conns:
            instances.append((cell_type, inst_name, port_conns))

    all_nets = set()
    for _, _, pc in instances:
        all_nets.update(pc.values())

    return module_name, inputs, outputs, instances, all_nets


# =========================================================
# 3. 計算 cell 寬度
# =========================================================
def cell_width_dbu(cell_type: str, cell_db: dict) -> int:
    """從 area 計算 cell 寬度 DBU（round up 到最近 site width）"""
    area = cell_db[cell_type]['area'] if cell_type in cell_db else DEFAULT_AREA_UM2
    width_um = area / CELL_HEIGHT_UM
    num_sites = max(1, math.ceil(width_um / SITE_WIDTH_UM))
    return num_sites * SITE_WIDTH_DBU


# =========================================================
# 4. 輸出 LEF
# =========================================================
def write_lef(lef_path: str, cell_types_used: set, cell_db: dict):
    """生成合成 ASAP7 LEF（僅含 DREAMPlace 需要的最小資訊）"""

    with open(lef_path, 'w') as f:
        f.write("VERSION 5.8 ;\n")
        f.write('BUSBITCHARS "[]" ;\n')
        f.write('DIVIDERCHAR "/" ;\n\n')

        f.write("UNITS\n")
        f.write(f"  DATABASE MICRONS {DBU_PER_UM} ;\n")
        f.write("END UNITS\n\n")

        # 最小 layer 定義
        f.write("LAYER M1\n")
        f.write("  TYPE ROUTING ;\n")
        f.write("END M1\n\n")

        # Site 定義
        f.write(f"SITE asap7sc7p5t\n")
        f.write(f"  CLASS CORE ;\n")
        f.write(f"  SYMMETRY Y ;\n")
        f.write(f"  SIZE {SITE_WIDTH_UM:.4f} BY {CELL_HEIGHT_UM:.4f} ;\n")
        f.write(f"END asap7sc7p5t\n\n")

        for cell_type in sorted(cell_types_used):
            info = cell_db.get(cell_type, None)
            area = info['area']       if info else DEFAULT_AREA_UM2
            out_pin  = info['output_pin']  if info else 'Y'
            inp_pins = info['input_pins']  if info else []
            all_pins = info['all_pins']    if info and info['all_pins'] else [out_pin] + inp_pins

            width_um = cell_width_dbu(cell_type, cell_db) / DBU_PER_UM
            half_x = width_um / 2
            half_y = CELL_HEIGHT_UM / 2
            pr = 0.027  # pin rect half-size (μm)

            f.write(f"MACRO {cell_type}\n")
            f.write(f"  CLASS CORE ;\n")
            f.write(f"  ORIGIN 0.0000 0.0000 ;\n")
            f.write(f"  SIZE {width_um:.4f} BY {CELL_HEIGHT_UM:.4f} ;\n")
            f.write(f"  SYMMETRY X Y ;\n")
            f.write(f"  SITE asap7sc7p5t ;\n")

            # 若 all_pins 為空，至少補一個 output pin
            if not all_pins:
                all_pins = ['Y']

            for pin in all_pins:
                direction = "OUTPUT" if (pin in OUTPUT_PIN_NAMES or pin == out_pin) else "INPUT"
                # 輸入 pin 均勻排在左側，輸出 pin 在中央
                if direction == "OUTPUT":
                    px = half_x
                else:
                    px = half_x  # 簡化：所有 pin 放在中央（DREAMPlace 不深度用 pin 位置）
                py = half_y
                f.write(f"  PIN {pin}\n")
                f.write(f"    DIRECTION {direction} ;\n")
                f.write(f"    PORT\n")
                f.write(f"      LAYER M1 ;\n")
                f.write(f"        RECT {px-pr:.4f} {py-pr:.4f} {px+pr:.4f} {py+pr:.4f} ;\n")
                f.write(f"    END\n")
                f.write(f"  END {pin}\n")

            f.write(f"END {cell_type}\n\n")

        f.write("END LIBRARY\n")


# =========================================================
# 5. 輸出 DEF
# =========================================================
def write_def(def_path: str, module_name: str,
              inputs: list, outputs: list, instances: list,
              cell_db: dict, utilization: float = 0.70) -> dict:
    """
    生成 DEF 檔（DIEAREA、ROW、COMPONENTS、PINS、NETS）。
    回傳 chip 尺寸資訊 dict。
    """
    # ---- 計算 die 尺寸 ----
    total_area_um2 = sum(
        (cell_db[ct]['area'] if ct in cell_db else DEFAULT_AREA_UM2)
        for ct, _, _ in instances
    )
    chip_area_um2 = total_area_um2 / utilization
    chip_side_um  = math.sqrt(chip_area_um2)

    num_rows = max(20, math.ceil(chip_side_um / CELL_HEIGHT_UM))
    chip_H_um = num_rows * CELL_HEIGHT_UM

    num_cols = max(20, math.ceil(chip_side_um / SITE_WIDTH_UM))
    chip_W_um = num_cols * SITE_WIDTH_UM

    chip_W_dbu = int(chip_W_um * DBU_PER_UM)
    chip_H_dbu = int(chip_H_um * DBU_PER_UM)

    # ---- 建 net → connections map ----
    net_conns = defaultdict(list)
    for cell_type, inst_name, port_conns in instances:
        for pin_name, net_name in port_conns.items():
            net_conns[net_name].append((inst_name, pin_name))

    all_io_ports = set(inputs) | set(outputs)

    with open(def_path, 'w') as f:
        f.write("VERSION 5.8 ;\n")
        f.write('DIVIDERCHAR "/" ;\n')
        f.write('BUSBITCHARS "[]" ;\n\n')
        f.write(f"DESIGN {module_name} ;\n\n")
        f.write(f"UNITS DISTANCE MICRONS {DBU_PER_UM} ;\n\n")
        f.write(f"DIEAREA ( 0 0 ) ( {chip_W_dbu} {chip_H_dbu} ) ;\n\n")

        # ROW 定義
        for r in range(num_rows):
            y_dbu = r * CELL_HEIGHT_DBU
            orient = "N" if r % 2 == 0 else "FS"
            f.write(f"ROW ROW_{r} asap7sc7p5t 0 {y_dbu} {orient} "
                    f"DO {num_cols} BY 1 STEP {SITE_WIDTH_DBU} 0 ;\n")
        f.write("\n")

        # COMPONENTS
        f.write(f"COMPONENTS {len(instances)} ;\n")
        for cell_type, inst_name, _ in instances:
            f.write(f"   - {inst_name} {cell_type} + UNPLACED ;\n")
        f.write("END COMPONENTS\n\n")

        # PINS（primary I/O）
        all_io = [(p, 'INPUT') for p in inputs] + [(p, 'OUTPUT') for p in outputs]
        f.write(f"PINS {len(all_io)} ;\n")
        chip_border_step = max(CELL_HEIGHT_DBU, chip_H_dbu // max(1, len(all_io) + 1))
        for idx, (port_name, direction) in enumerate(all_io):
            # 輸入放左邊界，輸出放右邊界
            if direction == 'INPUT':
                x_dbu = 0
            else:
                x_dbu = chip_W_dbu - SITE_WIDTH_DBU
            y_dbu = min(chip_border_step * (idx + 1), chip_H_dbu - CELL_HEIGHT_DBU)
            f.write(f"   - {port_name} + NET {port_name} + DIRECTION {direction} + USE SIGNAL\n")
            f.write(f"     + LAYER M1 ( 0 0 ) ( {SITE_WIDTH_DBU} {CELL_HEIGHT_DBU} )\n")
            f.write(f"     + PLACED ( {x_dbu} {y_dbu} ) N ;\n")
        f.write("END PINS\n\n")

        # NETS
        # 加入 I/O port nets（它們可能在 net_conns 裡沒有 entry）
        for p in inputs + outputs:
            _ = net_conns[p]  # 確保 key 存在

        f.write(f"NETS {len(net_conns)} ;\n")
        for net_name, conns in sorted(net_conns.items()):
            f.write(f"   - {net_name}")
            if net_name in all_io_ports:
                f.write(f"\n     ( PIN {net_name} )")
            for inst_name, pin_name in conns:
                f.write(f"\n     ( {inst_name} {pin_name} )")
            f.write("\n     ;\n")
        f.write("END NETS\n\n")
        f.write("END DESIGN\n")

    return {
        'chip_W_um': chip_W_um,
        'chip_H_um': chip_H_um,
        'chip_W_dbu': chip_W_dbu,
        'chip_H_dbu': chip_H_dbu,
        'total_area_um2': total_area_um2,
        'num_cells': len(instances),
        'num_rows': num_rows,
        'num_cols': num_cols,
        'num_nets': len(net_conns),
    }


# =========================================================
# 6. 輸出 DREAMPlace JSON config
# =========================================================
def write_dreamplace_config(config_path: str, lef_files: list,
                            def_file: str, result_dir: str,
                            num_cells: int):
    """
    生成 DREAMPlace params JSON（LEF/DEF 模式）。
    num_bins 根據 cell 數量自動選擇。
    """
    # 根據 cell 數量決定 bin 大小
    if num_cells < 5000:
        bins = 64
    elif num_cells < 50000:
        bins = 128
    else:
        bins = 256

    config = {
        "lef_input": lef_files,
        "def_input": def_file,
        "gpu": 1,
        "global_place_stages": [
            {
                "num_bins_x": bins,
                "num_bins_y": bins,
                "iteration": 1000,
                "learning_rate": 0.01,
                "wirelength": "weighted_average",
                "optimizer": "nesterov"
            }
        ],
        "target_density": 0.70,
        "density_weight": 8e-5,
        "gamma": 4.0,
        "random_seed": 1000,
        "ignore_net_degree": 100,
        "enable_fillers": 1,
        "gp_noise_ratio": 0.025,
        "global_place_flag": 1,
        "legalize_flag": 0,        # 先不做 legalization
        "detailed_place_flag": 0,  # 先不做 detailed placement
        "stop_overflow": 0.10,
        "dtype": "float32",
        "plot_flag": 0,
        "random_center_init_flag": 1,
        "sort_nets_by_degree": 0,
        "num_threads": 8,
        "result_dir": result_dir,
        "sol_file_format": "DEF"
    }

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    # result_dir 可能是 Docker 路徑，不在 host 上建立
    if os.path.isabs(result_dir) and not result_dir.startswith('/workspace'):
        os.makedirs(result_dir, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


# =========================================================
# 7. 主程式
# =========================================================
def main():
    parser = argparse.ArgumentParser(
        description='Convert GradMap gate-level Verilog → LEF + DEF for DREAMPlace'
    )
    parser.add_argument('verilog',      help='輸入 gate-level Verilog 檔案')
    parser.add_argument('output_dir',   help='輸出資料夾')
    parser.add_argument('--libcell',
        default='/home/james/projects/gradmap/libs/asap7_libcell_info.txt',
        help='asap7_libcell_info.txt 路徑')
    parser.add_argument('--lef', default=None,
        help='外部 cell LEF 檔（若提供則跳過合成 LEF）')
    parser.add_argument('--techlef', default=None,
        help='tech LEF 檔（含 UNITS + layer 定義，如 asap7_tech_1x_201209.lef）')
    parser.add_argument('--utilization', type=float, default=0.70,
        help='目標使用率 (default: 0.70)')
    parser.add_argument('--design-name', default=None,
        help='覆蓋設計名稱')
    parser.add_argument('--docker-prefix', default=None,
        help='把 JSON 內的 host 絕對路徑前綴換成 Docker 路徑，例如: '
             '--docker-prefix /home/james/projects:/workspace')
    args = parser.parse_args()

    # 建立路徑轉換函式
    if args.docker_prefix:
        host_prefix, docker_prefix = args.docker_prefix.split(':', 1)
        # 同時支援 symlink 路徑與真實路徑
        real_host_prefix = os.path.realpath(host_prefix)
        def to_json_path(p):
            p = os.path.realpath(p)
            if p.startswith(real_host_prefix):
                return docker_prefix + p[len(real_host_prefix):]
            return p
    else:
        def to_json_path(p):
            return os.path.abspath(p)

    os.makedirs(args.output_dir, exist_ok=True)

    # --- Step 1: 載入 cell library ---
    print(f"[1/5] Loading cell library: {args.libcell}")
    cell_db = parse_libcell_info(args.libcell)
    print(f"      Loaded {len(cell_db)} cell types")

    # --- Step 2: 解析 Verilog ---
    print(f"[2/5] Parsing Verilog: {args.verilog}")
    module_name, inputs, outputs, instances, all_nets = parse_verilog(args.verilog)
    if args.design_name:
        module_name = args.design_name

    cell_types_used = set(ct for ct, _, _ in instances)
    missing = cell_types_used - set(cell_db.keys())

    print(f"      Module:            {module_name}")
    print(f"      Primary inputs:    {len(inputs)}")
    print(f"      Primary outputs:   {len(outputs)}")
    print(f"      Cell instances:    {len(instances)}")
    print(f"      Unique nets:       {len(all_nets)}")
    print(f"      Unique cell types: {len(cell_types_used)}")
    if missing:
        print(f"      WARNING: {len(missing)} cell types not in libcell (using defaults)")
        if len(missing) <= 5:
            print(f"        {missing}")

    # --- Step 3: 產生 LEF ---
    if args.lef:
        import shutil
        lef_dest = os.path.join(args.output_dir, os.path.basename(args.lef))
        if os.path.abspath(args.lef) != os.path.abspath(lef_dest):
            shutil.copy2(args.lef, lef_dest)
        print(f"[3/5] Copied cell LEF to output dir: {lef_dest}")

        if args.techlef:
            tech_dest = os.path.join(args.output_dir, os.path.basename(args.techlef))
            if os.path.abspath(args.techlef) != os.path.abspath(tech_dest):
                shutil.copy2(args.techlef, tech_dest)
            lef_files = [tech_dest, lef_dest]
        else:
            lef_files = [lef_dest]
    else:
        lef_path = os.path.join(args.output_dir, f"{module_name}.lef")
        print(f"[3/5] Generating synthetic ASAP7 LEF: {lef_path}")
        write_lef(lef_path, cell_types_used, cell_db)
        
        if args.techlef:
            import shutil
            tech_dest = os.path.join(args.output_dir, os.path.basename(args.techlef))
            if os.path.abspath(args.techlef) != os.path.abspath(tech_dest):
                shutil.copy2(args.techlef, tech_dest)
            lef_files = [tech_dest, os.path.abspath(lef_path)]
        else:
            lef_files = [os.path.abspath(lef_path)]
            
        print(f"      Written {len(cell_types_used)} MACRO entries")

    # --- Step 4: 產生 DEF ---
    def_path = os.path.join(args.output_dir, f"{module_name}.def")
    print(f"[4/5] Generating DEF: {def_path}")
    chip_info = write_def(def_path, module_name, inputs, outputs,
                          instances, cell_db, args.utilization)
    print(f"      Die area: {chip_info['chip_W_um']:.1f} × {chip_info['chip_H_um']:.1f} μm")
    print(f"               ({chip_info['chip_W_dbu']} × {chip_info['chip_H_dbu']} DBU)")
    print(f"      Total cell area: {chip_info['total_area_um2']:.2f} μm²")
    print(f"      Rows: {chip_info['num_rows']}, Cols: {chip_info['num_cols']}")
    print(f"      Nets: {chip_info['num_nets']}")

    # --- Step 5: 產生 DREAMPlace JSON config ---
    config_path = os.path.join(args.output_dir, f"{module_name}.json")
    result_dir  = os.path.join(args.output_dir, "results")
    print(f"[5/5] Generating DREAMPlace config: {config_path}")
    write_dreamplace_config(
        config_path,
        [to_json_path(f) for f in lef_files],
        to_json_path(def_path),
        to_json_path(result_dir),
        len(instances)
    )

    # --- 儲存 summary（供 read_placement.py 使用）---
    summary = {
        'module_name': module_name,
        'lef_files': lef_files,
        'def_file': os.path.abspath(def_path),
        'config_file': os.path.abspath(config_path),
        'result_dir': os.path.abspath(result_dir),
        'num_instances': len(instances),
        'num_inputs': len(inputs),
        'num_outputs': len(outputs),
        'num_nets': chip_info['num_nets'],
        'chip_info': chip_info,
        # instance 清單：DEF COMPONENTS 的順序 = placedb node 順序
        'instances': [
            {'idx': i, 'inst': inst_name, 'cell_type': cell_type}
            for i, (cell_type, inst_name, _) in enumerate(instances)
        ]
    }
    summary_path = os.path.join(args.output_dir, f"{module_name}_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary: {summary_path}")

    print(f"\n{'='*55}")
    print(f"Done! Run DREAMPlace with:")
    print(f"  cd /home/james/projects/maplace/dreamplace")
    print(f"  python install/dreamplace/Placer.py {config_path}")
    print(f"{'='*55}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
