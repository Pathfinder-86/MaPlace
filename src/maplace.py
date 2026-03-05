#!/usr/bin/env python3
"""
maplace.py  —  GradMap ↔ DREAMPlace 整合中央控制器
=====================================================

Flow（目標 A：Placement-Informed Mapping）:

  for t in range(T):
    1. GradMap 跑 K steps → verilog_output/design.v
    2. verilog_to_def  → testcase/design.lef/.def/.json
    3. DREAMPlace 跑 P steps → placed positions
    4. read_placement  → {inst: (x,y)}, HPWL
    5. HPWL + positions → 回傳 GradMap（下一輪）

使用方式:
    python maplace.py --verilog <path/to/design.v>
    python maplace.py --verilog <path/to/design.v> --lef <path/to/asap7.lef>
    python maplace.py --test-conversion-only   # 只測試 Verilog→DEF 轉換
"""

import os
import sys
import json
import logging
import argparse

# ── 路徑設定 ──────────────────────────────────────────
SRC_DIR         = os.path.dirname(os.path.abspath(__file__))   # .../maplace/src
MAPLACE_ROOT    = os.path.dirname(SRC_DIR)                      # .../maplace
PROJECT_ROOT    = os.path.dirname(MAPLACE_ROOT)                 # .../projects
DREAMPLACE_ROOT = os.path.join(MAPLACE_ROOT, 'dreamplace')
INSTALL_PATH    = os.path.join(DREAMPLACE_ROOT, 'install')
TESTCASE_DIR    = os.path.join(MAPLACE_ROOT, 'testcase')

GRADMAP_ROOT    = os.path.join(PROJECT_ROOT, 'gradmap')
GRADMAP_VERILOG = os.path.join(GRADMAP_ROOT, 'verilog_output')
LIBCELL_PATH    = os.path.join(GRADMAP_ROOT, 'libs', 'asap7_libcell_info.txt')

for _p in [INSTALL_PATH, os.path.join(INSTALL_PATH, 'dreamplace'), SRC_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)-7s] MaPlace | %(message)s'
)
log = logging.getLogger('maplace')

# ── 本地模組（需 SRC_DIR 已在 sys.path）───────────────
from verilog_to_def import (
    parse_libcell_info, parse_verilog,
    write_lef, write_def, write_dreamplace_config
)
from read_placement import (
    read_from_placedb, read_from_placed_def,
    save_placement, get_positions_for_gradmap,
    compute_hpwl_from_def_and_placement
)


# ── Step 1: Verilog → LEF + DEF ──────────────────────
def convert_verilog_to_def(verilog_path: str,
                            iteration: int,
                            external_lef: str = None,
                            utilization: float = 0.70) -> dict:
    """把 Verilog 轉成 LEF+DEF，存到 testcase/<module>/iter_<n>/，回傳 summary dict。"""
    log.info(f"  [convert] Verilog → DEF  (iter {iteration})")

    cell_db = parse_libcell_info(LIBCELL_PATH)
    module_name, inputs, outputs, instances, all_nets = parse_verilog(verilog_path)

    out_dir = os.path.join(TESTCASE_DIR, module_name, f"iter_{iteration:03d}")
    os.makedirs(out_dir, exist_ok=True)

    cell_types_used = set(ct for ct, _, _ in instances)

    if external_lef:
        lef_files = [os.path.abspath(external_lef)]
        log.info(f"  [convert] Using external LEF: {external_lef}")
    else:
        lef_path = os.path.join(out_dir, f"{module_name}.lef")
        write_lef(lef_path, cell_types_used, cell_db)
        lef_files = [os.path.abspath(lef_path)]
        log.info(f"  [convert] Synthetic LEF → {lef_path}")

    def_path = os.path.join(out_dir, f"{module_name}.def")
    chip_info = write_def(def_path, module_name, inputs, outputs,
                          instances, cell_db, utilization)
    log.info(f"  [convert] DEF → {def_path}")
    log.info(f"  [convert] Die: {chip_info['chip_W_um']:.1f}×"
             f"{chip_info['chip_H_um']:.1f} μm  "
             f"cells: {len(instances)}  nets: {chip_info['num_nets']}")

    config_path = os.path.join(out_dir, f"{module_name}.json")
    result_dir  = os.path.join(out_dir, "results")
    write_dreamplace_config(
        config_path,
        [os.path.abspath(f) for f in lef_files],
        os.path.abspath(def_path),
        os.path.abspath(result_dir),
        len(instances)
    )

    summary = {
        'module_name': module_name,
        'iteration': iteration,
        'lef_files': lef_files,
        'def_file': os.path.abspath(def_path),
        'config_file': os.path.abspath(config_path),
        'result_dir': os.path.abspath(result_dir),
        'num_instances': len(instances),
        'chip_info': chip_info,
        'instances': [
            {'idx': i, 'inst': inst_name, 'cell_type': cell_type}
            for i, (cell_type, inst_name, _) in enumerate(instances)
        ]
    }
    summary_path = os.path.join(out_dir, f"{module_name}_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    summary['summary_file'] = summary_path
    return summary


# ── Step 2: 執行 DREAMPlace ───────────────────────────
def run_dreamplace(config_path: str):
    """執行 DREAMPlace global placement，回傳 (placedb, params, metrics)。"""
    log.info(f"  [dreamplace] Loading config: {config_path}")

    import torch
    try:
        import Params
        import PlaceDB
        from dreamplace.NonLinearPlace import NonLinearPlace
    except ImportError as e:
        log.error(f"DREAMPlace 模組載入失敗: {e}")
        log.error(f"確認 {INSTALL_PATH} 已存在且已編譯")
        raise

    orig_dir = os.getcwd()
    os.chdir(DREAMPLACE_ROOT)
    try:
        params = Params.Params()
        params.load(config_path)
        params.gpu = torch.cuda.is_available()
        log.info(f"  [dreamplace] GPU: {params.gpu}")

        placedb = PlaceDB.PlaceDB()
        placedb(params)
        log.info(f"  [dreamplace] {placedb.num_movable_nodes} movable / "
                 f"{placedb.num_nodes} nodes | {placedb.num_nets} nets")

        placer  = NonLinearPlace(params, placedb, timer=None)
        lr      = params.global_place_stages[0]['learning_rate']
        log.info(f"  [dreamplace] Running placement "
                 f"(iter={params.global_place_stages[0]['iteration']}, lr={lr})...")
        metrics = placer(params, placedb, lr)

        placed_def = os.path.join(params.result_dir, 'placed.def')
        placedb.write(params, placed_def)
        log.info(f"  [dreamplace] Done  →  {placed_def}")
    finally:
        os.chdir(orig_dir)

    return placedb, params, metrics


# ── Step 3: 讀取 placement 結果 ───────────────────────
def extract_placement(placedb, params, summary: dict) -> dict:
    """從 placedb 讀取 placement，存 JSON，回傳 placement dict。"""
    log.info(f"  [extract] Reading placement from placedb...")
    instance_order = [e['inst'] for e in summary['instances']]
    placement = read_from_placedb(placedb, params, instance_order)

    placement_path = os.path.join(
        os.path.dirname(summary['config_file']),
        f"{summary['module_name']}_placement.json"
    )
    save_placement(placement, placement_path)
    summary['placement_file'] = placement_path

    hpwl = placement.get('__hpwl_um__')
    if hpwl:
        log.info(f"  [extract] HPWL = {hpwl:.2f} μm")
    return placement


# ── 主迴圈 ────────────────────────────────────────────
def run_pipeline(verilog_path: str,
                 external_lef: str = None,
                 num_iterations: int = 1,
                 gradmap_steps_per_iter: int = 0):
    """GradMap ↔ DREAMPlace iterative loop。"""
    log.info("=" * 55)
    log.info("  MaPlace  —  GradMap ↔ DREAMPlace Pipeline")
    log.info("=" * 55)
    log.info(f"  Verilog: {verilog_path}")
    log.info(f"  LEF:     {external_lef or '(synthetic)'} | Iters: {num_iterations}")
    log.info("")

    prev_hpwl = None
    prev_placement = None

    for t in range(num_iterations):
        log.info(f"━━━  Iteration {t+1}/{num_iterations}  ━━━")

        # A: GradMap
        if gradmap_steps_per_iter > 0:
            log.info(f"  [A] GradMap: {gradmap_steps_per_iter} steps | "
                     f"HPWL feedback: {prev_hpwl:.2f} μm" if prev_hpwl
                     else f"  [A] GradMap: {gradmap_steps_per_iter} steps (first iter)")
            # TODO: verilog_path = run_gradmap(gradmap_steps_per_iter, prev_hpwl, prev_placement)
        else:
            log.info(f"  [A] Using static Verilog")

        # B: Verilog → DEF
        summary = convert_verilog_to_def(verilog_path, t, external_lef)

        # C: DREAMPlace
        placedb, params, metrics = run_dreamplace(summary['config_file'])

        # D: 讀取 placement
        placement = extract_placement(placedb, params, summary)
        prev_hpwl = placement.get('__hpwl_um__')
        prev_placement = placement

        # E: Feedback
        log.info(f"  [E] HPWL feedback: {prev_hpwl:.2f} μm" if prev_hpwl
                 else "  [E] HPWL: N/A")
        log.info(f"      Placement: {summary.get('placement_file', 'N/A')}")
        log.info("")

    log.info("=" * 55)
    log.info(f"  Pipeline complete! Final HPWL: "
             f"{prev_hpwl:.2f} μm" if prev_hpwl else "  Pipeline complete!")
    log.info("=" * 55)
    return prev_placement


# ── 測試模式：只做轉換 ────────────────────────────────
def test_conversion_only(verilog_path: str, external_lef: str = None):
    """只測試 Verilog→LEF+DEF 轉換，不跑 DREAMPlace。"""
    log.info("=" * 55)
    log.info("  Test: Verilog → DEF conversion only")
    log.info("=" * 55)
    summary = convert_verilog_to_def(verilog_path, 0, external_lef)
    log.info("")
    log.info(f"  Design: {summary['module_name']}")
    log.info(f"  Cells:  {summary['num_instances']}")
    log.info(f"  Nets:   {summary['chip_info']['num_nets']}")
    log.info(f"  Die:    {summary['chip_info']['chip_W_um']:.1f} × "
             f"{summary['chip_info']['chip_H_um']:.1f} μm")
    log.info(f"  DEF:    {summary['def_file']}")
    log.info(f"  JSON:   {summary['config_file']}")
    log.info("")
    log.info("To run DREAMPlace:")
    log.info(f"  cd {DREAMPLACE_ROOT}")
    log.info(f"  python install/dreamplace/Placer.py {summary['config_file']}")
    return summary


# ── main ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='MaPlace: GradMap ↔ DREAMPlace 整合控制器'
    )
    parser.add_argument('--verilog', default=None,
        help='GradMap 輸出的 gate-level Verilog 路徑')
    parser.add_argument('--lef', default=None,
        help='外部 ASAP7 LEF（預設自動生成合成 LEF）')
    parser.add_argument('--iterations', type=int, default=1,
        help='迭代次數 (default: 1)')
    parser.add_argument('--test-conversion-only', action='store_true',
        help='只測試 Verilog→DEF 轉換（不跑 DREAMPlace）')
    args = parser.parse_args()

    if not args.verilog:
        default_v = os.path.join(GRADMAP_VERILOG, 'arbiter_dc_abc_grad.v')
        args.verilog = default_v if os.path.exists(default_v) else None
    if not args.verilog or not os.path.exists(args.verilog):
        log.error("請用 --verilog 指定 Verilog 路徑")
        sys.exit(1)

    if args.test_conversion_only:
        test_conversion_only(args.verilog, args.lef)
    else:
        run_pipeline(args.verilog, args.lef, args.iterations)


if __name__ == '__main__':
    main()