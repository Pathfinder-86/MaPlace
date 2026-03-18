# Documentation Structure Analysis & Optimization Plan

## Current State

### GradMap Documentation (13 files)
```
gradmap_docs/
├── 00_README.md                     # Index
├── 01_overview.md                   # Architecture overview
├── 02_mapping_graph.md              # Match graph structure
├── 03_timing_engine.md              # STA mechanism
├── 04_optimizer.md                  # Gradient descent details
├── 05_known_issues.md               # Bug / limitation tracking
├── 06_wire_cap_load.md              # Wire capacitance calculation
├── 07_cover_ownership_writeback.md  # ✅ ABC cover + write-back
├── 08_selected_cover_conflict_analysis.md  # 🟡 Diagnostic (dated)
├── 09_abc_cover_and_regression.md   # ✅ ABC cover details + regression test
├── DREAMPlace_Integration.md        # ✅ Docker + placement loop
├── maplace_integration_progress_slides.md  # ✅ Status report
└── maplace_ppt_outline.md           # ✅ Presentation outline
```

### MaPlace Work Documentation (4 files)
```
maplace/work/
├── gradmap_warm_start_placement.md  # 🟡 Initial exploration
├── gradmap_position_writeback_strategy_plan.md  # ✅ Core design doc
├── session_20260319_improvements.md # ✅ Latest session (TODAY)
└── src/README_pipeline.md           # ℹ️ Pipeline architecture
```

---

## Analysis: Redundancy & Quality

### Category A: Core Knowledge (KEEP ALL)
✅ **Should remain** — Foundational docs for understanding system

| File | Quality | Priority | Notes |
|------|---------|----------|-------|
| 01_overview.md | ⭐⭐⭐ | CRITICAL | Architecture baseline |
| 02_mapping_graph.md | ⭐⭐⭐ | CRITICAL | Data structure reference |
| 03_timing_engine.md | ⭐⭐⭐ | CRITICAL | STA mechanism (unchanged) |
| 04_optimizer.md | ⭐⭐⭐ | HIGH | Gradient descent algorithm |
| 07_cover_ownership_writeback.md | ⭐⭐⭐ | HIGH | **Updated today** |
| 09_abc_cover_and_regression.md | ⭐⭐⭐ | HIGH | Cover mechanics + tests |

### Category B: Integration Docs (KEEP - ACTIVELY MAINTAINED)
✅ **Should remain but regularly updated**

| File | Quality | Priority | Notes |
|------|---------|----------|-------|
| DREAMPlace_Integration.md | ⭐⭐⭐ | HIGH | Docker + placement loop |
| maplace_integration_progress_slides.md | ⭐⭐ | MEDIUM | **Updated today** — status summary |
| maplace_ppt_outline.md | ⭐⭐ | MEDIUM | **Updated today** — presentation |
| session_20260319_improvements.md | ⭐⭐⭐ | HIGH | **NEW — comprehensive session log** |

### Category C: Provisional / Exploratory (ARCHIVE or CONSOLIDATE)
⚠️ **Can be archived** — useful historical reference

| File | Quality | Recommendation |
|------|---------|-----------------|
| 05_known_issues.md | ⭐ | Archive → GitHub Issues |
| 08_selected_cover_conflict_analysis.md | ⭐⭐ | **CONSOLIDATE** → 09_abc_cover_and_regression.md |
| gradmap_warm_start_placement.md | ⭐⭐ | Archive → historical reference |
| gradmap_position_writeback_strategy_plan.md | ⭐⭐⭐ | **CONSOLIDATE** → modernize, keep as "Design Decisions" |

### Category D: Infrastructure (KEEP)
✅ **Operational references**

| File | Quality | Priority |
|------|---------|----------|
| 00_README.md | ⭐⭐⭐ | HIGH — navigation hub |
| 06_wire_cap_load.md | ⭐⭐⭐ | MEDIUM |
| src/README_pipeline.md | ⭐⭐ | MEDIUM |

---

## Recommended New Structure

### **Tier 1: Quick Start (for next-session context understanding)**

Create **`gradmap_docs/QUICKSTART.md`** — Consolidates essential info in 5 min read:
```markdown
# MaPlace Quick Start for Next Session

## System Overview (2 min read)
- Architecture: GradMap (differentiable mapping) + DREAMPlace (GPU placement)
- Loop: optimize → export → place → read back → repeat

## Key Files to Know
- Config: `config/run_config_docker` (main control)
- Metrics: `validation/torch_metrics.csv` + `placement_metrics.csv`
- Dashboard: `python3 maplace/src/metrics_analyzer.py`

## Current Status (as of 2026-03-19)
- ✅ ABC cover support + write-back strategies (owner_propagation, owner_average)
- ✅ DREAMPlace parameters aligned (num_bins=256, target_density=1.0)
- 🔄 Experimental validation in progress

## Next Steps
1. Run optimization with new DREAMPlace settings
2. Compare write-back strategies via dashboard
3. Validate overflow improvements

## Deep Dives (5+ min)
- [Core Architecture](./01_overview.md)
- [Match Graph Details](./02_mapping_graph.md)
- [Write-Back Strategies](./07_cover_ownership_writeback.md)
- [Latest Session](../maplace/work/session_20260319_improvements.md)
```

### **Tier 2: Technical Details (for deep investigation)**

```
gradmap_docs/
├── QUICKSTART.md                            🆕 **READ FIRST**
├── INDEX.md                                 🆕 Navigation hub
│
├── [CORE ARCHITECTURE]
├── 01_overview.md
├── 02_mapping_graph.md
├── 03_timing_engine.md
├── 04_optimizer.md
│
├── [ABC COVER & WRITE-BACK]
├── 07_cover_ownership_writeback.md
├── 09_abc_cover_and_regression.md
│
├── [INTEGRATION]
├── DREAMPlace_Integration.md
├── 06_wire_cap_load.md
│
├── [REFERENCE]
├── 05_known_issues.md
│
└── [ARCHIVED / HISTORICAL]
    ├── 08_selected_cover_conflict_analysis.md (moved to archive/)
    └── gradmap_warm_start_placement.md (moved to archive/)
```

### **Tier 3: Session Logs (Decision Tracking)**

```
maplace/work/
├── README.md                            🆕 Work index
├── session_20260319_improvements.md     Latest (TODAY)
├── gradmap_position_writeback_strategy_plan.md (design reference)
└── archive/
    ├── gradmap_warm_start_placement.md
    └── 08_selected_cover_conflict_analysis.md
```

---

## MEMORY.md Enhancement Plan

### Current MEMORY.md Issues
- ⚠️ Project-specific but **too brief**
- ❌ No configuration reference
- ❌ No setup instructions
- ❌ Next-session context missing

### Proposed MEMORY.md 2.0 (Enhanced)

```markdown
# Project Memory — MaPlace Integration

## 🎯 Project Mission (One sentence)
Simultaneous technology mapping (GradMap) + placement (DREAMPlace) co-optimization via iterative gradient descent.

## 📋 Current Status (Last updated: 2026-03-19)
- ✅ ABC cover support: COMPLETE
- ✅ Ownership write-back: COMPLETE (2 strategies implemented)
- ✅ DREAMPlace integration: STABLE
- 🔄 Placement quality: IMPROVING (new parameters tuned)

## 🔑 Key Insights Learned

### Write-Back Strategies
- `owner_propagation`: Fast (O(n)), first-come-first-served for multi-owner nodes ← DEFAULT
- `owner_average`: Balanced (O(n×k)), averages multi-owner positions ← for redundancy

### DREAMPlace Tuning
- `num_bins=256` (was 64) → Fine granularity prevents artificial clustering
- `target_density=1.0` (was 0.6) → Realistic physical constraint, lower overflow
- `utilization=0.55` (was 0.70) → Larger chip, fewer packing conflicts

### IO Placement
- Current: All PI/PO fixed on boundaries (no movement)
- Status: Acceptable for now, but not co-optimized with mapping
- Future: Consider timing-aware pin placement

## 📁 Essential Files (Quick Reference)

| Purpose | File | Notes |
|---------|------|-------|
| Main config | `config/run_config_docker` | Most critical |
| Metrics tracking | `validation/(torch/placement)_metrics.csv` | Auto-generated |
| Dashboard | `maplace/src/metrics_analyzer.py` | NEW—aggregates both metrics |
| ABC cover | `match/*_cover.txt` | Generated by ABC `&nf -Y` |
| Write-back source | `src/mapping/circuit_graph_torch.cpp` | Strategies implemented here |

## 🔧 How to Run (Next Session)

```bash
cd /home/james/projects/gradmap

# Edit config if needed:
# optimizer.placement_utilization 0.55
# optimizer.placement_target_density 1.0
# optimizer.placement_writeback_strategy owner_propagation

./maplace config/run_config_docker

# After completion:
python3 ../maplace/src/metrics_analyzer.py \
  --torch-csv validation/torch_metrics.csv \
  --place-csv validation/placement_metrics.csv \
  --output-dir /tmp/report
```

## 📚 Documentation Map

| Focus | File | Read Time |
|-------|------|-----------|
| Quick context | `gradmap_docs/QUICKSTART.md` | 5 min |
| Full overview | `gradmap_docs/01_overview.md` | 15 min |
| Write-back design | `gradmap_docs/07_cover_ownership_writeback.md` | 10 min |
| DREAMPlace setup | `gradmap_docs/DREAMPlace_Integration.md` | 15 min |
| Latest session | `maplace/work/session_20260319_improvements.md` | 20 min |

## ⚠️ Known Limitations

1. **IO placement:** Static boundary → not co-optimized with mapping
2. **Later-stage placement:** Still seeing high overflow at step 60+, but improving
3. **Timing closure:** No hard timing constraints enforced

## 🚀 Next Priorities

1. Validate overflow improvements with new DREAMPlace params
2. Experimental comparison: `owner_propagation` vs `owner_average`
3. Consider timing-aware IO placement if current approach plateaus

## 🔗 Related Projects
- GradMap: Core mapping engine (`/home/james/projects/gradmap`)
- MaPlace: Integration layer (`/home/james/projects/maplace`)
- DREAMPlace: External placement (Dockerized)

---

**Last Session:** 2026-03-19 — Ownership write-back, DREAMPlace tuning, metrics dashboard
**Next Review:** After experimental validation with new parameters
```

---

## Action Items for Next Session

### Immediate (Next 30 min)
- [ ] Update `gradmap_docs/QUICKSTART.md` (👈 create)
- [ ] Update `gradmap_docs/INDEX.md` (👈 create)
- [ ] Enhance MEMORY.md with above content

### Short-term (Next 1-2 hours)
- [ ] Archive old files to `gradmap_docs/archive/`
- [ ] Consolidate 08_* into 09_abc_cover_and_regression.md
- [ ] Update 00_README.md as top-level nav

### Medium-term
- [ ] Run validation experiments with new metrics dashboard
- [ ] Compare write-back strategies
- [ ] Document best practices in QUICKSTART.md

---

## Summary

```
Before:  13 + 4 md files, some redundant/outdated
After:   Clear Tier structure, QUICKSTART for rapid context, archived historical docs

Benefit: Next session can get to work in 5 min instead of 30 min of doc hunting
```

**Proceed? Shall I start creating QUICKSTART.md and updating MEMORY.md?**
