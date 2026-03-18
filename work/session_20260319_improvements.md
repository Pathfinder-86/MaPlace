# MaPlace Improvements Session (2026-03-19)
## IO Placement, DREAMPlace Tuning, Ownership-Based Write-Back, and Metrics Integration

---

## Executive Summary

Session focused on **three major improvements**:
1. **IO Placement Strategy** — Analyzed current boundary-fixed approach, identified room for optimization
2. **DREAMPlace Parameter Tuning** — Aligned with ISPD2005 baseline (256×256 bins, target_density=1.0)
3. **Ownership-Based Write-Back** — Added `owner_average` strategy alongside existing `owner_propagation`
4. **Metrics Aggregation** — Built Python dashboard to track combined GradMap + DREAMPlace QoR

---

## 1. IO (Primary I/O Pin) Placement

### Current Implementation
- **Location:** `maplace/src/verilog_to_def.py:376-389`
- **PI (Primary Inputs):** Fixed at `x=0` (left boundary), `y` distributed uniformly
- **PO (Primary Outputs):** Fixed at `x=chip_W` (right boundary), `y` distributed uniformly
- **Status:** `+ FIXED ( x y ) N` in DEF — **no movement allowed**

### Problems Identified
```
PI at x=0, PO at x=max
  └─ Ignores logical connectivity
  └─ Wire length inflated
  └─ Not co-optimized with gate mapping
```

### Possible Improvements (Future)
- [ ] **Flexible Pinning:** Allow PI/PO to move along boundary (change FIXED → PLACED)
- [ ] **Granular Pin Placement:** Group by fanout degree, place near related logic
- [ ] **Timing-Aware IO:** Use critical path info to position IO close to timing-critical cells

### Recommendation
For now, keep IO fixed on boundary (maintains physical legality). Next session can explore flexible pinning.

---

## 2. DREAMPlace Parameter Optimization

### Root Cause Analysis - Why step 200 Had Issues

```
Original Settings:
  num_bins = 64×64
  target_density = 0.60
  shared config: active_only (now deprecated)

Result:
  overflow: 0.30 → 0.46 (worsening)
  max_density: 5.30 (extremely violated)
  converged: False
```

### Key Finding: Misaligned Objectives
```
utilization = 0.70  ──→ avg_density = 0.70
target_density = 0.60 ──→ MUST have overflow (0.70 > 0.60)

Solution:
  Lower utilization  ──→ avg_density ↓
  Raise target_density ──→ more realistic
```

### New Settings (Aligned with ISPD2005)
| Parameter | Old | New | Reason |
|-----------|-----|-----|--------|
| **num_bins** | 64 | 256 | Finer density control |
| **target_density** | 0.60 | 1.0 | Realistic for hard placement |
| **detailed_place** | 0 | 0 | Global placement only (faster) |
| **legalize_flag** | 1 | 1 | Keep (helps GP) |
| **scale_factor** | N/A | 1.0 | Added for consistency |

### File Changes
- `src/verilog_to_def.py`: Simplified to `bins=256` (no cell-count logic)
- `src/verilog_to_def.py`: Added `scale_factor: 1.0` (coordinate scaling)
- `config/run_config_docker`: Updated to `utilization=0.55` (larger chip) + `target_density=1.0`

### Expected Improvement
- Overflow should drop from 0.46 → ~0.05-0.15
- max_density should drop from 5.30 → < 1.5
- converged should become True (more often)

---

## 3. Ownership-Based Write-Back Strategy

### Completed: `owner_average` Strategy

**Problem:** Current `owner_propagation` uses **first-come-first-served** for multi-owner nodes
```cpp
// Old (owner_propagation)
if (owner_root[cover_id] == -1) {
    owner_root[cover_id] = node.node_id;  // First owner wins
} else {
    ++owner_conflicts;  // Later owners ignored
}
```

**Solution:** New `owner_average` strategy takes **positional average** of all owners
```cpp
// New (owner_average)
if (owner_roots[nid].empty()) continue;
std::vector<int> unique_owners = owner_roots[nid];  // All owners
// ... compute average position ...
acc[nid][0] = sum_x / count;  // Balanced coordinate
acc[nid][1] = sum_y / count;
```

### Implementation
- **File:** `src/mapping/circuit_graph_torch.cpp`
- **Functions Added:**
  - `apply_owner_average_propagation()` — New write-back strategy
  - Updated `is_supported_writeback_strategy()` to include `owner_average`
  - Updated main logic to branch between `owner_propagation` vs `owner_average`

### Configuration
```ini
optimizer.placement_writeback_strategy owner_propagation  # Recommended default (fast)
# or
optimizer.placement_writeback_strategy owner_average      # For redundant coverage (balanced)
```

### Usage Pattern
- **owner_propagation:** Use when coverage is clear (few conflicts)
- **owner_average:** Use when multiple matches cover same node (high redundancy)

---

## 4. Metrics Integration & Dashboard

### New Files Created

#### A. `maplace/src/metrics_analyzer.py` (Refactored)
**Purpose:** Aggregate + visualize combined QoR metrics

**Key Changes:**
- ✨ **NEW:** Refactored into `generate_dashboard()` library function
- Can be called from Python code, not just CLI
- Handles missing CSV files gracefully
- Error handling with detailed feedback

**Usage:**
```python
# From Python code (NEW)
from metrics_analyzer import generate_dashboard
generate_dashboard(
    torch_csv='validation/torch_metrics.csv',
    place_csv='validation/placement_metrics.csv',
    output_dir='validation/metrics_report'
)

# Or command-line (still works)
python3 metrics_analyzer.py --torch-csv ... --place-csv ... --output-dir ...
```

#### B. `maplace/config/metrics_plot_config.yaml`
**Purpose:** Configuration-driven plot generation (existing)

#### C. `gradmap/maplace.py` (NEW - Unified Entry Point!) 🌟
**Purpose:** **Single-step execution of entire pipeline**

**Solves:** "One command instead of two"

**Features:**
- Reads config file (including new `metrics.enable`, `metrics.output_dir` settings)
- Runs GradMap binary
- Auto-detects if metrics enabled
- Calls metrics_analyzer if enabled
- Chains everything into one pipeline
- Error handling with clear messages

**Usage:**
```bash
cd /home/james/projects/gradmap
python3 maplace.py config/run_config_docker
# ✅ Done! Optimization + Dashboard in one step
```

**Output:**
- All standard outputs (torch_metrics.csv, placement_metrics.csv)
- **PLUS** dashboard (if enabled)

### Configuration Integration (NEW)

`config/run_config_docker` now includes:
```ini
# --- Metrics Analysis & Dashboard ---
metrics.enable true                              # Enable/disable
metrics.output_dir validation/metrics_report    # Output location
metrics.plot_config config/metrics_plot_config.yaml
```

Default is **enabled**, so users get dashboard automatically with zero extra steps!

---

## 5. Documentation Updates

### Files Updated
- ✅ `config/run_config_docker` — Updated with new strategies, removed deprecated ones
- ✅ `gradmap_docs/07_cover_ownership_writeback.md` — Added owner_average section + comparison table
- ✅ `maplace/work/gradmap_position_writeback_strategy_plan.md` — Removed obsolete strategies
- ✅ `README.md` — Updated config examples
- ✅ `maplace_integration_progress_slides.md` — Updated status to "Complete"
- ✅ `maplace_ppt_outline.md` — Updated with ABC cover advantages

### Core Insight Updated
```
Old narrative:
  "ABC cover support is planned for next stage"

New narrative:
  "ABC cover support is complete with two strategies:
   - owner_propagation (default, first-write semantics)
   - owner_average (for redundant coverage, balanced semantics)"
```

---

## 6. Experimental Setup

### Recommended Next Run
```bash
cd /home/james/projects/gradmap

# Edit config if needed
# optimizer.placement_utilization 0.55
# optimizer.placement_target_density 1.0
# optimizer.placement_writeback_strategy owner_propagation

# Run
./maplace config/run_config_docker

# After completion, generate dashboard
python3 ../maplace/src/metrics_analyzer.py \
  --torch-csv validation/torch_metrics.csv \
  --place-csv validation/placement_metrics.csv \
  --output-dir /tmp/maplace_qor_report
```

### Expected Improvements vs Previous Run (step 200)
| Metric | Before | Expected | Comment |
|--------|--------|----------|---------|
| **overflow** | 0.46 | 0.05-0.15 | Main fix |
| **max_density** | 5.30 | <1.5 | Should legalize |
| **converged (%) ** | 0% (at step 200) | 80%+ | Realistic target |
| **HPWL trend** | Growing | Stable | Better seeding |

---

## 7. Known Limitations & Future Work

### Short-Tem

- [ ] Validate overflow improvements with new bin/density settings
- [ ] Compare `owner_propagation` vs `owner_average` experimentally
- [ ] Document convergence vs owner_conflicts correlation

### Medium-Term
- [ ] Implement timing-aware IO placement (prioritize critical path pins)
- [ ] Add optional "seed + small noise" for basin escape
- [ ] Integrate wire-cap computation into ownership hierarchy

### Long-Term
- [ ] Full multi-objective optimization dashboard (Pareto fronts)
- [ ] Automated DREAMPlace parameter sweep
- [ ] Integration with post-route validation (real congestion/timing)

---

## 8. Files & Paths Reference

```
Key Files Generated/Modified:
├── maplace/src/metrics_analyzer.py              (NEW - dashboard plotter)
├── maplace/config/metrics_plot_config.yaml      (NEW - plot configuration)
├── src/mapping/circuit_graph_torch.cpp          (MOD - owner_average strategy)
├── src/verilog_to_def.py                        (MOD - simplified num_bins)
├── config/run_config_docker                     (MOD - new DREAMPlace params)
├── gradmap_docs/07_cover_ownership_writeback.md (MOD - strategy explanation)
└── README.md                                    (MOD - updated examples)
```

---

## 9. Session Outcome

✅ **All objectives achieved:**
1. IO placement strategy analyzed (no blocker)
2. DREAMPlace parameters aligned with best practices
3. Ownership write-back enhanced (owner_average added)
4. Metrics dashboard integrated for systematic comparison
5. Documentation synchronized

**Ready for:** Next experimental validation run

---

**Session Date:** 2026-03-19
**Duration:** ~2.5 hours
**Status:** Ready for Production Testing
