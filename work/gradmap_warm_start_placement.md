# GradMap → DREAMPlace Warm-Start Placement Plan

## Goal
Avoid cold-starting DREAMPlace at every placement iteration.

Current flow rebuilds a new gate-level netlist every placement step, but the previous placement result has already been read back into GradMap node coordinates. The next placement run should reuse those coordinates as the initial seed when the corresponding instances still exist in the new hard-mapped netlist.

## Key idea
Do **not** reuse the old DEF file.

Instead:
1. GradMap still exports a fresh hard netlist each placement step.
2. GradMap also exports a `seed_positions.csv` from the current graph coordinates.
3. `verilog_to_def.py` reads that seed file.
4. When a new DEF instance name maps back to an existing GradMap node id, write the instance as `PLACED` using the saved coordinates.
5. Instances with no seed remain `UNPLACED`.

This keeps the DEF structurally consistent with the new netlist while still giving DREAMPlace a warm-start placement.

## What counts as a seedable object
### Components
Gate instances already use the naming scheme:
- `g<node_id>` for internal hard-selected gates

If instance `g137` exists in the new Verilog and `node 137` has a known `(x, y)`, then DEF should write:
- `+ PLACED (x_dbu y_dbu) N`

Otherwise it stays:
- `+ UNPLACED`

### PINS
Primary I/O names already use:
- `n<node_id>`

If `n42` has a saved coordinate, reuse it for DEF `PINS` placement instead of forcing the old left/right default.

## Why this is safe even when the netlist changes
The placement state is stored on GradMap graph nodes, not only on a previous DEF file.

So the next iteration can do:
- new netlist topology
- old node coordinates where node ids still match

This gives a partial warm start:
- nodes that persist across iterations keep their old location
- newly introduced instances start as `UNPLACED`
- removed instances are naturally ignored

## Initial implementation scope
### Included
- Export current graph coordinates to `seed_positions.csv`
- Pass seed file into `run_placer_in_docker.sh`
- Add `--seed-positions` support in `verilog_to_def.py`
- Seed DEF `COMPONENTS` and `PINS`
- Disable `random_center_init_flag` when at least one seed is applied

### Not included yet
- Better covered-node ownership reconstruction
- Better PI/PO spreading policy
- Placement pruning / clustering heuristics
- Tuning `placement_interval`

## Practical behavior
### No seed available
- Keep current behavior
- components are `UNPLACED`
- pins use default left/right placement
- `random_center_init_flag = 1`

### Partial seed available
- matching components become `PLACED`
- matching pins reuse saved pin coordinates
- unmatched objects remain default / `UNPLACED`
- `random_center_init_flag = 0`

## Expected benefit
Compared with restarting from a center-randomized DEF every iteration, this should:
- preserve more placement continuity across iterations
- reduce unnecessary HPWL shocks between adjacent placement steps
- make iterative placement feedback more meaningful
