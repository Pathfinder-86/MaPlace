#!/usr/bin/env python3
"""
read_placement.py
-----------------
從 DREAMPlace 讀回 placement 結果，轉換成 GradMap 可用的格式。

支援兩種讀取方式：
  A. 從 Python API (placedb)  — 在同一 Python process 中使用
  B. 從 DREAMPlace 輸出的 DEF — 在不同 process 讀回

輸出：
  placement_result.json  → {inst_name: [x_um, y_um], "__hpwl_um__": float}
"""

import re
import os
import sys
import json
import math
from collections import defaultdict
from typing import Dict, Tuple, Optional, List

# DBU per μm（與 verilog_to_def.py 保持一致）
DBU_PER_UM = 1000


# =========================================================
# 方法 A: 從 DREAMPlace placedb Python 物件讀取
# =========================================================
def read_from_placedb(placedb, params, instance_order: List[str]) -> Dict:
    """
    在 DREAMPlace 跑完後，從 placedb 讀回 movable cell 的位置。

    Args:
        placedb        : DREAMPlace PlaceDB 物件
        params         : DREAMPlace Params 物件
        instance_order : DEF COMPONENTS 中 instance 的順序
                         （由 verilog_to_def.py 的 summary.json 取得）

    Returns:
        dict:
            {inst_name: [x_um, y_um]}  ← cell 左下角，real-space μm
            "__hpwl_um__": float        ← 總 HPWL（μm）
            "__num_movable__": int
    """
    import numpy as np

    # node_x / node_y 是 scaled 座標（DBU）
    # placedb 在讀入後會 scale：node_x_scaled = (real - shift) * scale_factor
    # unscale: real = node_x_scaled / scale_factor + shift_factor

    node_x = placedb.node_x  # numpy array, length = num_physical_nodes
    node_y = placedb.node_y
    node_names = placedb.node_names   # list of str, 與 node_x 對齊
    num_movable = placedb.num_movable_nodes

    # scale factor（DREAMPlace 內部的 normalization）
    # 若直接從 placedb 拿，node_x 通常已是 real-space DBU（尚未 normalize）
    # 需要先 unscale_pl 或直接用 placedb.node_x（已是 real-space）
    # 注意：DREAMPlace 在 __call__() 結束後會自動 call unscale_pl
    scale  = getattr(params, 'scale_factor',  1.0)
    shift  = getattr(params, 'shift_factor',  [0.0, 0.0])

    result = {}

    for i in range(num_movable):
        name = node_names[i] if i < len(node_names) else f"unknown_{i}"
        # 轉回 real-space μm
        x_dbu = node_x[i] / scale + shift[0]
        y_dbu = node_y[i] / scale + shift[1]
        x_um  = x_dbu / DBU_PER_UM
        y_um  = y_dbu / DBU_PER_UM
        result[name] = [round(x_um, 6), round(y_um, 6)]

    # 計算 HPWL（用 placedb 的 net 結構）
    hpwl_dbu = _compute_hpwl_from_placedb(placedb, node_x, node_y)
    hpwl_um  = hpwl_dbu / DBU_PER_UM

    result['__hpwl_um__']     = round(hpwl_um, 2)
    result['__num_movable__'] = num_movable

    return result


def _compute_hpwl_from_placedb(placedb, node_x, node_y) -> float:
    """計算所有 net 的 HPWL（half-perimeter wirelength），單位 DBU"""
    import numpy as np

    hpwl = 0.0
    pin_offset_x = placedb.pin_offset_x
    pin_offset_y = placedb.pin_offset_y
    pin2node_map = placedb.pin2node_map
    net2pin_map  = placedb.net2pin_map   # list of list
    net_weights  = placedb.net_weights

    for net_id, pin_ids in enumerate(net2pin_map):
        if len(pin_ids) < 2:
            continue
        xs = []
        ys = []
        for pin_id in pin_ids:
            node_id = pin2node_map[pin_id]
            if node_id < len(node_x):
                xs.append(node_x[node_id] + pin_offset_x[pin_id])
                ys.append(node_y[node_id] + pin_offset_y[pin_id])
        if len(xs) >= 2:
            hpwl += net_weights[net_id] * (
                (max(xs) - min(xs)) + (max(ys) - min(ys))
            )

    return hpwl


# =========================================================
# 方法 B: 從 DREAMPlace 輸出的 placed DEF 讀取
# =========================================================
def read_from_placed_def(def_path: str) -> Dict:
    """
    解析 DREAMPlace 輸出的 placed DEF 檔案，取出每個 instance 的位置。

    DEF COMPONENTS 格式：
      - inst_name CELL_TYPE + PLACED ( x_dbu y_dbu ) N ;

    Returns:
        {inst_name: [x_um, y_um]}   ← cell 左下角，real-space μm
        "__hpwl_um__": None         ← DEF 不含 HPWL，由外部計算
    """
    result = {}

    with open(def_path) as f:
        content = f.read()

    placed_pat = re.compile(
        r'-\s+(\w+)\s+\w+[^;]*\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\w+\s*;'
    )

    for m in placed_pat.finditer(content):
        inst_name = m.group(1)
        x_dbu = int(m.group(2))
        y_dbu = int(m.group(3))
        # DEF UNITS DISTANCE MICRONS 1000 → 1 DBU = 1 nm = 0.001 μm
        x_um = x_dbu / DBU_PER_UM
        y_um = y_dbu / DBU_PER_UM
        result[inst_name] = [round(x_um, 6), round(y_um, 6)]

    result['__hpwl_um__']     = None
    result['__num_movable__'] = len([k for k in result if not k.startswith('__')])

    return result


# =========================================================
# 儲存 / 載入 placement JSON
# =========================================================
def save_placement(placement: Dict, output_path: str):
    """把 placement 結果存成 JSON"""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(placement, f, indent=2)
    hpwl = placement.get('__hpwl_um__')
    n    = placement.get('__num_movable__', 0)
    print(f"[placement] Saved {n} cells → {output_path}")
    if hpwl is not None:
        print(f"[placement] HPWL = {hpwl:.2f} μm")


def load_placement(json_path: str) -> Dict:
    """從 JSON 載入 placement 結果"""
    with open(json_path) as f:
        return json.load(f)


# =========================================================
# GradMap 座標回傳介面
# =========================================================
def get_positions_for_gradmap(placement: Dict,
                               summary_json_path: str
                               ) -> Tuple[list, list, float]:
    """
    把 placement dict 轉成 GradMap 可用的 (x_list, y_list, hpwl_um)。

    回傳的 x_list / y_list 順序與 summary.json 中的 instances 清單一致
    （即 DEF COMPONENTS 的順序，也是 GradMap instances 的順序）。

    不知道位置的 instance 填 None。
    """
    with open(summary_json_path) as f:
        summary = json.load(f)

    x_list = []
    y_list = []
    missing_count = 0

    for entry in summary['instances']:
        inst_name = entry['inst']
        if inst_name in placement:
            x_list.append(placement[inst_name][0])
            y_list.append(placement[inst_name][1])
        else:
            x_list.append(None)
            y_list.append(None)
            missing_count += 1

    if missing_count > 0:
        print(f"[placement] WARNING: {missing_count} instances have no placement")

    hpwl_um = placement.get('__hpwl_um__', None)
    return x_list, y_list, hpwl_um


# =========================================================
# 計算 HPWL（從 DEF 讀入的 connectivity + positions）
# =========================================================
def compute_hpwl_from_def_and_placement(def_path: str, placement: Dict) -> float:
    """
    從原始 DEF（含 NETS 資訊）和 placement dict 計算 HPWL（μm）。
    用於方法 B（read_from_placed_def 後沒有 HPWL 的情況）。
    """
    # 解析 DEF NETS section
    with open(def_path) as f:
        content = f.read()

    # 找 NETS...END NETS 區塊
    nets_match = re.search(r'\bNETS\s+\d+\s*;(.*?)\bEND\s+NETS\b', content, re.DOTALL)
    if not nets_match:
        return 0.0

    nets_content = nets_match.group(1)

    # 每條 net： - net_name ( inst pin ) ( inst pin ) ... ;
    net_pat = re.compile(r'-\s+(\w+)(.*?);', re.DOTALL)
    conn_pat = re.compile(r'\(\s*(\w+)\s+(\w+)\s*\)')

    # 從 placement 拿位置（cell 左下角 μm）
    # 近似：所有 pin 都在 cell 中心，忽略 pin offset
    def get_center(inst_name: str):
        if inst_name in placement:
            return placement[inst_name]
        return None

    hpwl = 0.0
    for nm in net_pat.finditer(nets_content):
        net_name = nm.group(1)
        conns_str = nm.group(2)
        xs, ys = [], []
        for cm in conn_pat.finditer(conns_str):
            inst = cm.group(1)
            if inst == 'PIN':
                continue
            pos = get_center(inst)
            if pos:
                xs.append(pos[0])
                ys.append(pos[1])
        if len(xs) >= 2:
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))

    return round(hpwl, 4)


# =========================================================
# GradMap C++ 介面：輸出 node_idx,x_um,y_um CSV
# =========================================================
def write_positions_csv(placement: Dict, csv_path: str):
    """
    把 placement dict 轉成 GradMap C++ load_positions_from_file() 可讀的 CSV。

    inst_name 對應規則：
      g<N>  → node_idx = N   (COMPONENTS 內部 gate)
      n<M>  → node_idx = M   (PINS PI/PO)

    輸出格式：
      node_idx,x_um,y_um
      3,14.048000,2.062000
      ...
    """
    rows = []   # (node_idx, x_um, y_um)
    skipped = 0
    for inst_name, val in placement.items():
        if inst_name.startswith('__'):   # 跳過 metadata key
            continue
        m = re.match(r'g(\d+)$', inst_name)   # 內部 gate
        if not m:
            m = re.match(r'n(\d+)$', inst_name)  # PI/PO pin
        if m:
            rows.append((int(m.group(1)), val[0], val[1]))
        else:
            skipped += 1

    rows.sort(key=lambda r: r[0])
    with open(csv_path, 'w') as f:
        f.write("node_idx,x_um,y_um\n")
        for idx, x, y in rows:
            f.write(f"{idx},{x:.6f},{y:.6f}\n")

    if skipped:
        print(f"[placement] WARNING: {skipped} instances skipped (unexpected name format)")
    print(f"[placement] Written {len(rows)} node positions → {csv_path}")


# =========================================================
# CLI 獨立使用：從 placed DEF 讀取並存 JSON + CSV
# =========================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='從 DREAMPlace 輸出的 placed DEF 讀取座標'
    )
    parser.add_argument('placed_def',    help='DREAMPlace 輸出的 placed DEF 檔案')
    parser.add_argument('summary_json',  help='verilog_to_def.py 產生的 *_summary.json')
    parser.add_argument('output_json',   help='輸出 placement JSON 路徑')
    parser.add_argument('--positions-csv', default=None,
        help='同時輸出 GradMap C++ 用的 positions.csv (node_idx,x_um,y_um)')
    parser.add_argument('--compute-hpwl', action='store_true',
        help='從原始 DEF 重新計算 HPWL')
    parser.add_argument('--original-def', default=None,
        help='原始 DEF（含 NETS，用於計算 HPWL）')
    args = parser.parse_args()

    print(f"[1/3] Reading placement from DEF: {args.placed_def}")
    placement = read_from_placed_def(args.placed_def)
    print(f"      Found {placement['__num_movable__']} placed cells")

    if args.compute_hpwl and args.original_def:
        print(f"[2/3] Computing HPWL from {args.original_def}")
        hpwl = compute_hpwl_from_def_and_placement(args.original_def, placement)
        placement['__hpwl_um__'] = hpwl
        print(f"      HPWL = {hpwl:.2f} μm")
    else:
        print(f"[2/3] Skipping HPWL computation (use --compute-hpwl --original-def to enable)")

    print(f"[3/3] Saving placement JSON: {args.output_json}")
    save_placement(placement, args.output_json)

    # 輸出 GradMap C++ 用的 CSV
    if args.positions_csv:
        write_positions_csv(placement, args.positions_csv)
        print(f"\nGradMap config:")
        print(f"  optimizer.position_file {os.path.abspath(args.positions_csv)}")

    # 顯示對 GradMap 的順序
    x_list, y_list, hpwl_um = get_positions_for_gradmap(placement, args.summary_json)
    valid = sum(1 for x in x_list if x is not None)
    print(f"\n→ GradMap-ready: {valid}/{len(x_list)} cells have positions")
    if hpwl_um:
        print(f"→ HPWL feedback: {hpwl_um:.2f} μm")

    return 0


if __name__ == '__main__':
    sys.exit(main())
