# MaPlace: Unified Mapping and Placement

An integrated tool combining **GradMap** (gradient-based technology mapping) with **DREAMPlace** (deep learning-based placement) to enable simultaneous circuit optimization.

**Vision:** Map gates and place cells in one unified gradient descent framework, enabling co-optimization of mapping and placement decisions.

---

## Project Overview

Traditional design flow: Mapping → Placement (sequential, disjoint)

**MaPlace flow:** Mapping ∥ Placement (simultaneous, joint optimization)

### Architecture

```
Input Netlist
      ↓
  GradMap      (Optimize gate selections via gradient descent)
      ↓
  DREAMPlace   (Optimize cell placements via gradient descent)
      ↓
Output Verilog + Layout
```

### Key Idea

- GradMap differentiable optimization: mapping weights → area/delay
- DREAMPlace differentiable optimization: placement → congestion/wirelength
- Combined loss: `α×L_mapping + β×L_placement`
- Single gradient step updates both mapping and placement

---

## Project Structure

```
maplace/
├── src/
│   ├── main.cpp
│   ├── gradmap/                 # GradMap integration (symlink or copy)
│   │   ├── flow/
│   │   ├── mapping/
│   │   ├── optimizer/
│   │   ├── timing/
│   │   └── ...
│   ├── dreamplace/              # DREAMPlace integration
│   │   ├── placer.h/cpp
│   │   ├── placement_loss.h/cpp
│   │   └── ...
│   ├── unified/                 # New modules for joint optimization
│   │   ├── combined_loss.h/cpp   # Joint loss function
│   │   ├── unified_optimizer.h/cpp  # Joint optimizer
│   │   └── io/
│   │       ├── lef_reader.h/cpp     # Read cell shapes
│   │       ├── def_reader.h/cpp     # Read placement
│   │       └── def_writer.h/cpp     # Write placement
│   └── ...
├── config/
│   ├── run_config               # Combined mapping + placement config
│   ├── mapping_config           # GradMap-specific
│   └── placement_config         # DREAMPlace-specific
├── libs/
│   ├── asap7_libcell_info.txt   # Cell properties
│   ├── tech.lef                 # LEF (technology)
│   └── cells.lef                # LEF (cell layouts)
├── benchmarks/
│   └── *_map.txt                # Match graphs
│   └── *_init.def               # Initial placements
└── README.md                    # This file
```

---

## Workflow (High-Level)

```
Step 1: Load Libraries & Benchmarks
  ├─ Parse LEF (tech + cells)
  ├─ Parse DEF (initial placement)
  └─ Parse match graph for mapping

Step 2: Initialize
  ├─ GradMap: Initialize weights (from ABC warm-start)
  ├─ DREAMPlace: Initialize positions (from DEF)
  └─ GPU: Load both to GPU tensors

Step 3: Joint Loss & Gradient
  ├─ Forward GradMap: area(mapping) + delay(mapping)
  ├─ Forward DREAMPlace: wirelength(placement) + congestion(placement)
  ├─ Combined loss: α×L_map + β×L_place
  └─ Backward: Update both mapping weights + placement positions

Step 4: Evaluate
  ├─ Discrete mapping (one-hot)
  ├─ Discrete placement (cell grid)
  ├─ Compute final area/delay/wirelength
  └─ Record best checkpoint

Step 5: Output
  ├─ VerilogWriter: mapped netlist
  ├─ DEFWriter: placement result
  └─ Save to verilog_output/ + placement_output/
```

---

## Configuration

### `config/run_config`

```plaintext
# ===== Unified MaPlace Config =====

# Flow Control
flow true
mapping_enabled true
placement_enabled true
joint_optimization true

# ===== MAPPING (GradMap) =====

testcase.lib libs/asap7_libcell_info.txt
testcase.match match/example_map.txt

optimizer.area_factor 1.0          # Area weight
optimizer.delay_factor 0.5         # Delay weight

# ===== PLACEMENT (DREAMPlace) =====

testcase.lef_tech libs/tech.lef
testcase.lef_cell libs/cells.lef
testcase.def_init benchmarks/example_init.def

placement.wirelength_factor 1.0    # Wirelength weight
placement.congestion_factor 0.5    # Congestion weight
placement.density_weight 1.0       # Cell density

# ===== JOINT OPTIMIZATION =====

optimizer.learning_rate 0.9
optimizer.method torch
optimizer.eval_backend gpu

# Loss balance
optimizer.mapping_weight 0.7       # Favor mapping (area/delay)
optimizer.placement_weight 0.3     # Favor placement (wirelength)

# Training
optimizer.total_steps 500
optimizer.eval_interval 5
optimizer.early_stop_enable true

# ===== OUTPUT =====

output.verilog verilog_output/output.v
output.def placement_output/output.def
```

### Key Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| `area_factor` | 0.0 - 2.0 | GradMap area optimization strength |
| `delay_factor` | 0.0 - 2.0 | GradMap delay optimization strength |
| `wirelength_factor` | 0.0 - 2.0 | DREAMPlace wirelength optimization |
| `congestion_factor` | 0.0 - 1.0 | DREAMPlace congestion control |
| `mapping_weight` | 0.0 - 1.0 | Fraction of loss from mapping |
| `placement_weight` | 0.0 - 1.0 | Fraction of loss from placement |

---

## Building

```bash
cd /home/james/projects/maplace
bash build.sh
```

### Dependencies

- PyTorch + LibTorch (C++)
- CUDA (for GPU)
- GradMap source
- DREAMPlace source (or pre-built library)

---

## Running

```bash
./maplace config/run_config
```

Output:
- `verilog_output/output.v` - Mapped netlist
- `placement_output/output.def` - Final placement
- Metrics logged to terminal

---

## Evaluation

### Mapping Quality
```bash
abc -c "read_lib libs/ASAP7.lib; read_verilog verilog_output/output.v; topo; stime"
```

### Placement Quality
```bash
# Use standard placement metrics: HPWL, congestion, density
# (Can use OpenROAD or custom tools)
```

---

## Key Design Decisions

1. **Shared GPU Memory**: Both mapping and placement tensors on same GPU
2. **Loss Weighting**: Tune `mapping_weight` to balance objectives
3. **Evaluation Mode**: Switch to discrete (hard) selections during eval
4. **LEF/DEF**: Standard formats for technology & placement interchange

---

## Current Status

- **Phase 1:** Framework setup (config, I/O)
- **Phase 2:** GradMap integration (in progress)
- **Phase 3:** DREAMPlace integration (planned)
- **Phase 4:** Joint loss & optimizer (planned)
- **Phase 5:** Evaluation & benchmarking (planned)

---

## References

- **GradMap Paper:** `../gradmap/technology_mapping_gradient_descent.pdf`
- **GradMap Docs:** `../gradmap/README.md`
- **DREAMPlace:** https://github.com/UCLA-DA/DREAMPlace
- **LEF/DEF Format:** https://www.ispd.cc/benchmarks/

---

## Future Extensions

1. **Power Optimization**: Add leakage + dynamic power to loss
2. **Timing Closure**: Incorporate timing constraints
3. **Multi-Objective**: Pareto frontier for area/delay/power/wirelength
4. **Hierarchical**: Handle hierarchical designs
5. **Adaptive Weighting**: Dynamically adjust loss weights during training
