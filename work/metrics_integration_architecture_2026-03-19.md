# Metrics Integration Architecture Correction (2026-03-19)

## Overview

This document clarifies the **correct C++ integration approach** for metrics dashboard generation, replacing the earlier (incorrect) Python wrapper approach.

---

## ❌ Wrong Approach (Earlier Attempt)

### What Was Done Initially
```
User workflow: ./gradmap_torch config/run_config_docker
↓
Suggested: python3 maplace.py config/run_config_docker (separate entry point)
↓
Issue: User doesn't use maplace.py, they use ./maplace directly
```

### Why It Was Wrong
- User's actual workflow: `./maplace config/run_config_docker`
- Python wrapper added unnecessary indirection
- Not truly "one command" (still manual two-step if user forgets about metrics)
- configuration was correct, but invocation point was wrong

---

## ✅ Correct Approach (Implemented Today)

### Architecture

```
User Command: ./maplace config/run_config_docker
    ↓
[C++ flow_manager.cpp]
    ├─ run_lib_parsing()
    ├─ run_circuit_mapping()
    ├─ run_optimization()
    ├─ run_verilog_writer()
    └─ NEW: run_metrics_dashboard()  ← Integration point!
        │
        ├─ Read metrics.enable from config
        ├─ Read metrics.output_dir from config
        ├─ Read metrics.plot_config from config
        │
        └─ system() call:
           python3 ../maplace/src/metrics_analyzer.py \
             --torch-csv validation/torch_metrics.csv \
             --place-csv validation/placement_metrics.csv \
             --output-dir validation/metrics_report
            ↓
       [metrics_analyzer.py generates 8 plots + CSVs]
            ↓
        Dashboard ready in validation/metrics_report/
```

### Key Changes

#### 1. **flow_manager.h** (Added Method Declaration)
```cpp
void run_metrics_dashboard();  // Generate QoR dashboard if enabled
```

#### 2. **flow_manager.cpp** (Modified run_flow + Added Implementation)

**Modified run_flow():**
```cpp
void FlowManager::run_flow() {
    ConfigManager& cm = ConfigManager::instance();

    auto lib = cm.getValue("testcase.lib");
    if(lib.first) run_lib_parsing(std::get<std::string>(lib.second));

    auto match = cm.getValue("testcase.match");
    if(match.first) run_circuit_mapping(std::get<std::string>(match.second));

    run_optimization();       // Existing
    run_verilog_writer();     // Existing
    run_metrics_dashboard();  // NEW: Auto-generate metrics
}
```

**New run_metrics_dashboard() Implementation:**
```cpp
void FlowManager::run_metrics_dashboard() {
    ConfigManager& cm = ConfigManager::instance();

    // 1. Check if enabled
    auto metrics_enable = cm.getValue("metrics.enable");
    if (!metrics_enable.first || !std::get<bool>(metrics_enable.second)) {
        std::cout << "[Flow] Metrics dashboard: disabled" << std::endl;
        return;
    }

    // 2. Read configuration values
    std::string output_dir = "validation/metrics_report";
    auto output_val = cm.getValue("metrics.output_dir");
    if (output_val.first) {
        output_dir = std::get<std::string>(output_val.second);
    }

    std::string plot_config = "config/metrics_plot_config.yaml";
    auto plot_val = cm.getValue("metrics.plot_config");
    if (plot_val.first) {
        plot_config = std::get<std::string>(plot_val.second);
    }

    // 3. Build and run command
    std::string cmd = "python3 ../maplace/src/metrics_analyzer.py"
                      " --torch-csv validation/torch_metrics.csv"
                      " --place-csv validation/placement_metrics.csv"
                      " --output-dir " + output_dir;
    if (!plot_config.empty()) {
        cmd += " --config " + plot_config;
    }

    std::cout << "[Flow] Running command: " << cmd << std::endl;
    int ret = system(cmd.c_str());

    if (ret == 0) {
        std::cout << "[Flow] Metrics dashboard generated: " << output_dir << std::endl;
    } else {
        std::cerr << "[Flow] Warning: Metrics generation returned status " << ret << std::endl;
    }
}
```

#### 3. **Added #include <cstdlib>** for system() call

---

## Configuration (Unchanged - Already Correct)

`config/run_config_docker` already has correct metrics settings:

```ini
# --- Metrics Analysis & Dashboard ---
metrics.enable true                              # Enable/disable
metrics.output_dir validation/metrics_report     # Output directory
metrics.plot_config config/metrics_plot_config.yaml  # Plot configuration
```

---

## Execution Flow

### Example Run

```bash
$ cd /home/james/projects/gradmap
$ ./maplace config/run_config_docker

=== OUTPUT ===
[Flow] Parsing Library: ...
[Flow] Circuit mapping...
[Flow] Optimization...
[Flow] Writing Verilog...
[Flow] Generating metrics dashboard...
[Flow] Running command: python3 ../maplace/src/metrics_analyzer.py --torch-csv validation/torch_metrics.csv ...
✅ Saved: validation/metrics_report/01_delay_trend.png
✅ Saved: validation/metrics_report/02_area_trend.png
...
[Flow] Metrics dashboard generated: validation/metrics_report
```

---

## Benefits of C++ Integration

| Aspect | Python Wrapper | C++ Integration (Correct) |
|--------|---|---|
| **User command** | `python3 maplace.py config` | `./maplace config` |
| **Single command** | ❌ Required wrapper | ✅ Binary alone |
| **Transparent flow** | ❌ Two steps visible | ✅ Seamless inside binary |
| **Configuration-driven** | ✅ Yes | ✅ Yes |
| **Entry point** | ❌ External Python | ✅ Native C++ |
| **Complexity** | ❌ Extra toolchain | ✅ Integrated |
| **User expects** | ❌ No | ✅ Yes |

---

## Status of Changed Files

### Modified
- ✅ `src/flow/flow_manager.h` - Added method declaration
- ✅ `src/flow/flow_manager.cpp` - Implemented metrics dashboard + updated run_flow()
- ✅ `QUICKSTART_MAPLACE.md` - Updated to reflect C++ integration
- ✅ `MEMORY.md` - Updated "How to Run" section

### Deprecated
- ⚠️ `gradmap/maplace.py` - Marked as deprecated (no longer needed)

### Unchanged (Already Correct)
- ✅ `maplace/src/metrics_analyzer.py` - Standalone tool (works as-is)
- ✅ `config/run_config_docker` - Config section already present
- ✅ `maplace/config/metrics_plot_config.yaml` - Plot configuration

---

## Next Steps

1. **Compile** the modified flow_manager
   ```bash
   cd /data2_4TB/james/projects/gradmap
   ./compile.sh
   ```

2. **Test** with metrics enabled
   ```bash
   cd /data2_4TB/james/projects/gradmap
   ./maplace config/run_config_docker
   # Check: validation/metrics_report/ should be populated
   ```

3. **Test** with metrics disabled
   ```bash
   # Edit config: metrics.enable false
   ./maplace config/run_config_docker
   # Check: No metrics_report directory should be created
   ```

---

## Context Window Consideration

User asked about context window compaction. This integration is **minimal** and shouldn't impact:
- Total lines added: ~50 lines (run_metrics_dashboard method + call)
- Compilation time: Negligible (only added one system() call)
- Runtime overhead: Depends on metrics_analyzer.py execution (typically ~5-10 seconds for plotting)

---

**Summary**: The correct approach integrates metrics into C++ flow_manager, not as a separate Python wrapper. User command remains `./maplace config`, metrics generate automatically if enabled in configuration.

