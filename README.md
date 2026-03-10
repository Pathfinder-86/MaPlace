# MaPlace: Unified Mapping and Placement

An integrated tool combining **GradMap** (gradient-based technology mapping) with **DREAMPlace** (deep learning-based placement) to enable simultaneous circuit optimization.

**Vision:** Map gates and place cells in one unified gradient descent framework, enabling co-optimization of mapping and placement decisions.

---

## Latest Experiment Snapshot (2026-03-06)

Current reference run:
- placement run id: `run_20260306T043153Z`
- GradMap metrics source: [../gradmap/validation/torch_metrics.csv](../gradmap/validation/torch_metrics.csv)
- placement metrics source: [../gradmap/validation/placement_metrics.csv](../gradmap/validation/placement_metrics.csv)

### GradMap / Torch metrics

| step | loss | area | delay | best_cost |
|---|---:|---:|---:|---:|
| 1 | 2.4715 | 159.636 | 707.027 | 1.6932 |
| 40 | 1.0331 | 174.975 | 552.425 | 1.2025 |
| 60 | 1.0132 | 172.846 | 536.952 | 1.1691 |
| 100 | 1.0175 | 171.694 | 532.756 | 1.1531 |

![GradMap torch metrics](../gradmap/gradmap_docs/assets/maplace_torch_metrics.png)

Interpretation:
- loss decreases substantially
- delay improves from about `707` to `533`
- area rises from about `159.6` to `171.7`
- current optimization is trading some area for better delay

### Placement metrics

| step | final HPWL | final overflow | final max density | converged |
|---|---:|---:|---:|---|
| 20 | 204713.4 | 0.0995 | 1.363 | yes |
| 40 | 199214.8 | 0.0988 | 1.420 | yes |
| 60 | 216320.3 | 0.3169 | 4.237 | no |
| 80 | 208541.5 | 0.3641 | 3.705 | no |
| 100 | 205527.5 | 0.3899 | 3.869 | no |

![Placement metrics](../gradmap/gradmap_docs/assets/maplace_placement_metrics.png)

Interpretation:
- step `20` and `40` converge well
- after step `40`, overflow grows sharply
- the integration is functioning, but later-stage congestion is still unresolved

### Combined summary figure

![Latest experiment snapshot](../gradmap/gradmap_docs/assets/maplace_latest_snapshot.png)

### Layout snapshots

- [iter_20 layout](testcase/gradmap_output/placement_layout_iter_20.png)
- [iter_40 layout](testcase/gradmap_output/placement_layout_iter_40.png)
- [iter_60 layout](testcase/gradmap_output/placement_layout_iter_60.png)
- [iter_80 layout](testcase/gradmap_output/placement_layout_iter_80.png)
- [iter_100 layout](testcase/gradmap_output/placement_layout_iter_100.png)

### One-paragraph takeaway

MaPlace already closes the loop between mapping and placement: GradMap improves delay using placement-aware feedback, and DREAMPlace can be invoked repeatedly with warm-started coordinates. The current limitation is not runtime stability but physical quality at later iterations, where placement overflow rises after step `40` even though GradMap delay continues improving.

---

## PPT-Ready Outline

If you want to generate slides from markdown, use:
- [../gradmap/gradmap_docs/maplace_ppt_outline.md](../gradmap/gradmap_docs/maplace_ppt_outline.md)

Suggested section order:
1. MaPlace Introduction
2. Preliminary
3. Method
4. Experiments
5. Issue

---

## Docker Quick Start

### One-time Host Setup

The NVIDIA container runtime must be the Docker default runtime. Check `/etc/docker/daemon.json`:

```json
{
    "default-runtime": "nvidia",
    "runtimes": {
        "nvidia": {
            "args": [],
            "path": "nvidia-container-runtime"
        }
    }
}
```

If you change the file, restart Docker:

```bash
sudo systemctl restart docker
```

### Saved Image (no pip install needed)

The working environment (DREAMPlace + requirements installed) is saved as a local image:

```bash
sudo docker images | grep dreamplace-maplace
# dreamplace-maplace   ready   ...
```

To start a session:

```bash
sudo docker run -it --gpus all \
  -v /home/james/projects/maplace:/workspace/maplace \
  -v /home/james/projects/gradmap:/workspace/gradmap \
  dreamplace-maplace:ready bash
```

Important:
- current bridge script expects ASAP7 LEF/techlef under [gradmap/libs/ASAP7](../gradmap/libs/ASAP7)
- after Docker restart, mounting only [maplace](.) and [gradmap](../gradmap) is sufficient
- if a script still points to `/home/james/projects/libs/...` inside the container, update it to `/workspace/gradmap/libs/...`

Inside the container, set PYTHONPATH and run DREAMPlace:

```bash
export PYTHONPATH=/workspace/maplace/dreamplace/install:/workspace/maplace/dreamplace/install/dreamplace
cd /workspace/maplace/dreamplace/install/dreamplace
python3 Placer.py /workspace/maplace/testcase/top/iter_000/top.json
```

### First-time Setup (if image is lost)

If the saved image is gone, rebuild from the base image:

```bash
sudo docker run -it --gpus all \
  -v /home/james/projects/maplace:/workspace/maplace \
  -v /home/james/projects/gradmap:/workspace/gradmap \
  limbo018/dreamplace:cuda bash

# Inside container:
pip install -r /workspace/maplace/dreamplace/requirements.txt

# Test GPU visibility:
nvidia-smi
```

Then save the container as a new image (find CONTAINER_ID with `docker ps`):

```bash
sudo docker commit <CONTAINER_ID> dreamplace-maplace:ready
```

### Re-saving After Changes

After installing new packages or modifying the container environment:

```bash
# Find running container ID
sudo docker ps

# Commit (overwrites the saved image)
sudo docker commit <CONTAINER_ID> dreamplace-maplace:ready
```

---

## Project Overview

Traditional design flow: Mapping → Placement (sequential, disjoint)

**MaPlace flow:** Mapping ∥ Placement (simultaneous, joint optimization)

### Architecture: Joint Optimization Loop

```
Input Netlist & Initial Placement
        ↓
  ┌─────────────────────────────────────┐
  │      Joint Gradient Descent Loop    │
  │                                     │
  │   GradMap         ◄─(x,y, HPWL)─►  DREAMPlace
  │ (Area, Delay)        (feedback)   (Density, WL)
  │   ↑                                  ↑
  │   │ (mapping weights)  (placement)  │
  │   └──────────────────────────────────┘
  │      ∇BackProp ← Combined Loss
  │
  └─────────────────────────────────────┘

Output Verilog + Layout
```

**Key Insight:** GradMap and DREAMPlace exchange information within each gradient step:
- DREAMPlace computes placement (x, y) → wire length (HPWL)
- GradMap uses HPWL to compute wire delay → affects total delay
- Both losses guide next gradient step simultaneously

### Key Idea: Physical Co-Optimization

Traditional flow: Mapping (fixed) → Placement (fixed) → Suboptimal

**MaPlace:** Mapping weights + Placement positions optimized jointly

1. **GradMap**: Chooses gate types + positions simultaneously via soft probabilities
2. **DREAMPlace**: Optimizes placement density and wirelength
3. **Feedback Loop**: Placement determines wire lengths → affects gate delays
4. **Single Gradient Step**: Updates both mapping decisions and cell locations

Example: Choosing a slower gate might be acceptable if placement reduces wire delay

---

## Project Structure

```
maplace/
├── maplace.py                   # Main entry point
├── joint_optimizer.py           # Joint gradient descent loop
├── gradmap_wrapper.py           # Pybind11 wrapper for GradMap C++ library
├── dreamplace_wrapper.py        # Wrapper for DREAMPlace
├── config/
│   └── run_config.yaml          # Unified config (mapping + placement)
├── src/
│   ├── gradmap/                 # GradMap C++ source (compiled → libgradmap.so)
│   │   ├── flow/
│   │   ├── mapping/
│   │   ├── timing/              # Linear delay model (wire_delay aware)
│   │   ├── optimizer/
│   │   └── CMakeLists.txt
│   ├── pybind11_bindings/       # C++ ↔ Python interface
│   │   ├── gradmap_binding.cpp
│   │   └── CMakeLists.txt
│   └── unified/
│       ├── combined_loss.py     # Joint loss (area + delay + WL + density)
│       ├── data_structures.py   # Match with position, wire info
│       └── io/
│           ├── lef_reader.py
│           ├── def_reader.py
│           └── def_writer.py
├── libs/
│   ├── asap7_libcell_info.txt   # Cell properties (R, C, area, delay)
│   ├── tech.lef                 # LEF (technology)
│   └── cells.lef                # LEF (cell layouts)
├── benchmarks/
│   ├── *_match.txt              # Match graphs with position info
│   └── *_init.def               # Initial placements
└── README.md
```

**Architecture Notes:**
- **maplace.py**: Python orchestrator (manages everything)
- **gradmap_wrapper.py**: C++ ↔ Python bridge (via Pybind11)
- **DREAMPlace**: Integrated as Python module (from UCLA-DA)
- **joint_optimizer.py**: Unified Adam optimizer for both mapping + placement

---

## Workflow: Unified Gradient Descent

### Step 1: Load & Parse
```
├─ Libraries: LEF (tech + cells), lib_info (area, R, C, delay models)
├─ Circuit: Match graph with position candidates
├─ Initial placement: DEF file
└─ GPU setup: PyTorch device
```

### Step 2: Initialize
```
├─ GradMap: Soft weights from ABC warm-start
├─ DREAMPlace: Cell positions from DEF
└─ Both on GPU as learnable tensors
```

### Step 3: Forward Pass (Joint)
```
GradMap Forward:
  ├─ Select gates via soft probabilities (weights)
  ├─ Compute area = Σ(cell_area[selected] × prob)
  ├─ DREAMPlace returns: placement (x, y) → HPWL
  │
  └─ Compute delay:
      ├─ Base delay from linear regression STA
      ├─ Wire delay = R × C_load
      │   where C_load = input_pin_cap + wire_cap
      │   and HPWL comes from DREAMPlace
      └─ Total delay = Δ_gate + Δ_wire

DREAMPlace Forward:
  ├─ Optimize placement: x, y for each cell
  ├─ Compute wirelength (HPWL) ← feedback to GradMap
  ├─ Compute density violations
  └─ Return placement loss
```

**Physical Interaction:** GradMap's delay computation now includes placement effects via wire length!

### Step 4: Compute Joint Loss
```
Combined Loss = 
  α × log(Area)                    [GradMap: area optimization]
  + β × log(Delay_with_Wire)       [GradMap: timing (including placement)]
  + γ × log(HPWL)                  [DREAMPlace: wirelength]
  + λ × log(Density_Violations)    [DREAMPlace: routability]

Physical meaning:
- α: weight on cell area
- β: weight on gate + wire delay (MAIN CO-OPTIMIZATION SIGNAL)
- γ: weight on routing congestion
- λ: weight on placement density
```

### Step 5: Backward & Update
```
Gradient:
  ├─ ∂Loss / ∂weights  → GradMap learns better gate selections
  ├─ ∂Loss / ∂positions → DREAMPlace learns better placement
  └─ Both updated via shared Adam optimizer

Key: Wire delay gradient flows back to both mapping and placement!
```

### Step 6: Evaluate & Checkpoint
```
Periodic evaluation (every N steps):
  ├─ Convert soft weights → discrete gates (one-hot)
  ├─ Fix placement (one-hot cell positions)
  ├─ Run STA with discrete netlist
  ├─ Record best area/delay/HPWL
  └─ Early stop if no improvement
```

### Step 7: Output
```
Best checkpoint:
  ├─ VerilogWriter: mapped netlist
  ├─ DEFWriter: optimized placement
  └─ Metrics: final area/delay/HPWL/density
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

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `area_alpha` | float | 1.0 | Weight on cell area optimization (higher → more area savings) |
| `delay_beta` | float | **3.0** | **Weight on timing-aware optimization (PLACEMENT FEEDBACK HERE)** |
| `wirelength_gamma` | float | 0.5 | Weight on wirelength reduction (DREAMPlace objective) |
| `density_lambda` | float | 1.0 | Weight on placement density constraints |
| `learning_rate` | float | 0.01 | Adam optimizer learning rate |
| `lr_decay_patience` | int | 20 | Steps before LRScheduler reduces LR on plateau |
| `num_epochs` | int | 200 | Total training iterations |
| `eval_interval` | int | 10 | Steps between discrete evaluations |
| `wirelength_model` | str | "hpwl" | Wirelength metric (hpwl or ttwl) |
| `placement_method` | str | "dreamplace" | Placement optimizer (dreamplace or analytical) |

### Tuning Strategy

**For area-focused optimization:**
```
area_alpha = 2.0    # increase weight on cell area
delay_beta = 1.0    # reduce timing constraints
wirelength_gamma = 0.1  # minimal routing cost
```

**For timing-focused optimization:**
```
area_alpha = 0.5    # relax area constraint
delay_beta = 5.0    # strong focus on delay (INCLUDING PLACEMENT EFFECTS)
wirelength_gamma = 1.0  # allow longer wires for better timing
```

**Key Insight:** `delay_beta` is the critical knob for co-optimization because it couples GradMap's gate selection with DREAMPlace's placement decisions. Higher `delay_beta` forces placement to reduce wirelength → lower wire delay → better timing.

---

## Building

### Prerequisites
```bash
# System packages
sudo apt-get install build-essential cmake libboost-all-dev

# Python + dependencies
pip install torch dreamplace pyyaml

# ABC for warm-start initialization
git clone https://github.com/berkeley-abc/abc
cd abc && make -j8
```

### Build Process

```bash
cd /home/james/projects/maplace

# Step 1: Compile GradMap library (C++)
cd src/gradmap
mkdir -p build && cd build
cmake .. -DCUDA_ARCH=75  # adjust for your GPU
make -j8
cp libgradmap.so ../../..

# Step 2: Build Pybind11 bindings
cd ../../pybind11_bindings
python setup.py build_ext --inplace

# Step 3: Verify Python can import
python -c "import _gradmap; print('GradMap bindings OK')"
python -c "import dreamplace; print('DREAMPlace OK')"
```

### Dependencies

- PyTorch + LibTorch (C++)
- CUDA (for GPU)
- GradMap source
- DREAMPlace source (or pre-built library)

---

## Running

### Basic Run
```bash
cd /home/james/projects/maplace

# Run with default config
python maplace.py config/run_config.yaml

# Run with custom parameters (override config file)
python maplace.py config/run_config.yaml \
  --delay_beta 4.0 \
  --num_epochs 300 \
  --learning_rate 0.001
```

### Output
```
maplace_output/
├── checkpoints/
│   ├── best_model.pth          # Best weights + positions
│   └── training_log.csv        # Loss curves per epoch
├── results/
│   ├── output.v                # Mapped netlist (Verilog)
│   ├── output.def              # Final placement (DEF)
│   └── metrics.json            # Final area/delay/HPWL
└── plots/
    ├── loss_curves.png         # Training convergence
    └── area_delay_tradeoff.png # QoR frontier
```

### Example Config (config/run_config.yaml)
```yaml
# Input files
library_lef: libs/tech.lef
library_def: libs/cells.lef
circuit_verilog: benchmarks/c17.v
initial_placement: benchmarks/c17.def

# Optimization weights
area_alpha: 1.0
delay_beta: 3.0          # Higher = more timing focus
wirelength_gamma: 0.5
density_lambda: 1.0

# Training
num_epochs: 200
learning_rate: 0.01
eval_interval: 10

# Hardware
device: cuda:0
batch_size: 1
```

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

### 1. Python Orchestration
```
├─ Why: Coordination between GradMap (C++ CUDA) + DREAMPlace (PyTorch)
├─ Method: Pybind11 bindings expose libgradmap.so to Python
└─ Benefit: Cleaner data flow, easier debugging, flexible workflow
```

### 2. Unified Optimizer (Adam)
```
├─ Why: Both mapping weights AND placement positions are learnable
├─ Implementation: Single optimizer.step() updates both gradients
├─ Benefit: Placement changes → affect wire delay → guide mapping selection
└─ Key: Gradient flow is now coupled (not separate)
```

### 3. Position-Aware Matching
```
Original GradMap:
  ├─ Each AIG node: match_set = [(cell_type_1, prob_1), (cell_type_2, prob_2), ...]
  └─ Matching is FIXED regardless of placement

MaPlace Enhancement:
  ├─ Each AIG node: match_set = [(cell_type_1, x_1, y_1, prob_1), ...]
  ├─ Soft weights now include spatial information
  └─ SAME cell_type at different (x, y) = different match candidates
  
Physical meaning:
  - Cell choices depend on location → influences HPWL → affects wire delay
  - Placement feedback directly affects mapping decisions
```

### 4. Wire-Aware STA Model
```
Traditional mapping:
  ├─ Delay = cell_delay[selected_gate]
  └─ Ignores physical placement

MaPlace model:
  ├─ Delay = cell_delay[gate] + wire_delay[wire_length]
  ├─ Wire_delay = R × C_load   (load = pin_cap + wirecap(HPWL))
  └─ HPWL comes from DREAMPlace forward pass
```

### 5. Discrete Evaluation Loop
```
During training (forward/backward):
  ├─ Use soft probabilities: L = Σ(prob_i × loss_i)
  ├─ Enable gradient flow
  └─ Fast (no routing or detailed placement)

During evaluation (every N steps):
  ├─ Convert to one-hot: select highest prob option
  ├─ Fix placement: snap to placement grid
  ├─ Run ABC STA on discrete netlist
  ├─ Record best area/delay/HPWL
  └─ Slow (one-hot evaluation) but reliable
```

---

## Technical Innovation: The Co-Optimization Loop

### Why Sequential Doesn't Work
```
Traditional flow (sequential):
Step 1: Map circuit (gates fixed)
Step 2: Place circuit (mapping fixed)
Problem: Placement has no influence on mapping decisions
Result: Suboptimal because placement opportunities missed during mapping

MaPlace solution (co-optimized):
├─ Both gates AND placement positions are trainable
├─ Update both in same backward pass
├─ Placement shapes wire delay → influences gate selection
└─ Gate selection shapes HPWL → influences placement optimization
```

### The Physical Feedback Loop
```
Iteration N:
  1. GradMap soft selects gates (probabilities)
  2. DREAMPlace positions cells to minimize HPWL
  3. Wire delay calculated: Δ_wire = R × C[HPWL]
  4. Total loss includes delay (area + gate_delay + wire_delay + HPWL)
  5. Backward propagates through BOTH networks
  6. Adam updates mapping weights AND positions simultaneously

Result: Placement becomes aware of timing criticality
        Mapping becomes aware of physical placement
```

### Match Data Structure
```
Match set example for one AIG node:

Original GradMap:
  match_set = [
    ("NAND2", prob=0.7),
    ("AOI21", prob=0.2),
    ("OAI21", prob=0.1)
  ]
  Area = 0.7 × A(NAND2) + 0.2 × A(AOI21) + 0.1 × A(OAI21)

MaPlace enhancement:
  match_set_with_positions = [
    ("NAND2", {
      "positions": [(10.5, 20.0), (25.0, 30.5), (40.0, 20.0)],
      "probabilities": [0.4, 0.2, 0.1]
    }),
    ("AOI21", {
      "positions": [(15.0, 25.0), (35.0, 35.0)],
      "probabilities": [0.15, 0.05]
    })
  ]
  
Soft area = 0.4×A(NAND2@10.5,20.0) + 0.2×A(NAND2@25.0,30.5) + ...
Soft HPWL = depends on selected positions through DREAMPlace
Wire delay = R × C_load[HPWL for selected position]
```

---

## Current Status

**Implementation Progress:**
- ✅ **Phase 1:** Python orchestrator (maplace.py)
- ✅ **Phase 2:** GradMap C++ integration (Pybind11 bindings)
- ✅ **Phase 3:** DREAMPlace PyTorch integration
- ✅ **Phase 4:** Joint loss function (area + delay + HPWL + density)
- ✅ **Phase 5:** Unified Adam optimizer
- 🟡 **Phase 6:** Position-aware matching (in development)
- 🟡 **Phase 7:** Evaluation & benchmarking (initial results)

**Known Limitations:**
- Position candidates currently from grid only (can extend to continuous)
- Wire delay model uses R×C approximation (not full parasitic RLC)
- Density constraints simplified (can add layer-aware constraints)



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
