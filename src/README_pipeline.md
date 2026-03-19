# MaPlace Pipeline: Gate-Level Verilog → DREAMPlace → GradMap

完整說明從 GradMap 輸出的 Verilog，到 DREAMPlace 跑出 placement，再讀回 GradMap 的完整流程。

---

## 整體架構

```
GradMap (C++)
  └─ output.v  (gate-level Verilog)
        │
        ▼
  verilog_to_def.py  (Python)
        │
        ├─ top.def          (DEF: 空白 placement，所有 cell UNPLACED)
        ├─ tech.lef         (LEF: UNITS + SITE，DREAMPlace 需要)
        ├─ cell.lef         (LEF: cell macro 定義，從 ASAP7 複製)
        └─ top.json         (DREAMPlace 設定檔)
              │
              ▼
        DREAMPlace (Docker, GPU)
              │
              └─ top.gp.def  (DEF: 所有 cell 都有 PLACED x,y)
                    │
                    ▼
              read_placement.py  (Python)
                    │
                    └─ positions.csv  (inst_name, x_um, y_um)
                          │
                          ▼
                    GradMap C++ 讀入位置
                    用真實 wire length 計算 delay
```

---

## Step 1：GradMap 輸出 gate-level Verilog

GradMap 對 AIG (And-Inverter Graph) 做 technology mapping，選出每個節點對應的 ASAP7 cell，輸出標準的 gate-level Verilog。

**輸出格式範例：**
```verilog
module top (n2, n4, ..., n6630, ...);
    input n2, n4, ...;
    output n6630, ...;
    wire n3, n5, ...;

    INVxp67_ASAP7_75t_R g3 (.Y(n3), .A(n2));
    NAND2x1_ASAP7_75t_R g5 (.Y(n5), .A(n4), .B(n3));
    ...
endmodule
```

- **Cell 命名規則**：`<CellType>_ASAP7_75t_R`，例如 `INVxp67_ASAP7_75t_R`
- **Instance 命名**：`g<node_id>`，對應 AIG 節點 ID
- **Net 命名**：`n<id>`，對應 AIG edge

---

## Step 2：`verilog_to_def.py` — Verilog → DEF + JSON

### 為什麼需要這個步驟？

DREAMPlace 吃的是 **LEF + DEF** 格式（業界標準 EDA 格式），不認識 Verilog。
這個 script 把 Verilog 的邏輯結構翻譯成 DREAMPlace 可以處理的物理格式。

### 做了什麼？

#### 2.1 解析 Verilog

用 regex 從 Verilog 提取：
- `inputs` / `outputs`：電路的 primary I/O
- `instances`：每個 cell instance（cell type + instance name + 連接的 net）
- `all_nets`：所有 wire

#### 2.2 查詢 cell 面積

讀取 `asap7_libcell_info.txt`，得到每個 cell type 的：
- 面積（μm²）→ 用來計算 die area
- pin 名稱（input/output pins）→ 用來建立 NETS

#### 2.3 計算 die area

```python
total_area = sum(cell_db[cell_type]['area'] for each instance)
die_area = total_area / utilization   # 預設 utilization = 0.70
die_side = sqrt(die_area)             # 正方形 die
```

ASAP7 物理常數：
- Cell height = 0.270 μm（7.5T standard cell）
- Site width (CPP) = 0.054 μm（Contacted Poly Pitch）
- 1 DBU = 1 nm（DEF UNITS DISTANCE MICRONS 1000）

#### 2.4 生成 DEF 檔案

DEF 結構：
```
VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 15930 15930 ) ;   # die 大小

ROW ROW_0 asap7sc7p5t 0 0 N DO 295 BY 1 STEP 54 0 ;   # 放置列
ROW ROW_1 asap7sc7p5t 0 270 FS ...
...

COMPONENTS 2414 ;                    # cell instances（全部 UNPLACED）
  - g3 INVxp67_ASAP7_75t_R ;
  - g5 NAND2x1_ASAP7_75t_R ;
  ...
END COMPONENTS

PINS 385 ;                           # I/O pins
  - n2 + NET n2 + DIRECTION INPUT
    + LAYER M1 ( 0 0 ) ( 54 270 )
    + PLACED ( 54 0 ) N ;
  ...
END PINS

NETS 2670 ;                          # 連線關係
  - n3 ( g3 Y ) ( g5 B ) ;
  ...
END NETS
```

**關鍵點**：COMPONENTS 裡全部是 `UNPLACED`（沒有座標），DREAMPlace 會負責決定位置。

#### 2.5 複製 LEF 到 output 目錄

原因：ASAP7 library 是透過 symlink (`gradmap/libs/ASAP7 → ../../../libs/ASAP7/`)，Docker 裡 symlink target 不存在，所以直接複製到 output 目錄，避免路徑問題。

複製兩個 LEF：
1. `tech.lef`（從 `asap7_tech_1x_201209.lef`）：包含 `UNITS DATABASE MICRONS 1000`，讓 DREAMPlace 正確換算 DBU → μm
2. `cell.lef`（從 `asap7sc7p5t_28_R_1x_220121a.lef`）：包含所有 MACRO（cell 的物理尺寸 + pin 位置）

**為什麼需要 tech.lef？**

ASAP7 cell LEF 本身沒有 `UNITS` 定義。DREAMPlace 讀到 SITE SIZE `0.054` 沒有換算單位，直接取整數 = 0，造成 `ZeroDivisionError: float division by zero`。tech.lef 提供 `DATABASE MICRONS 1000`，讓 DREAMPlace 知道 54 DBU = 0.054 μm。

#### 2.6 生成 DREAMPlace JSON config

```json
{
  "lef_input": ["tech.lef", "cell.lef"],
  "def_input": "top.def",
  "gpu": 1,
  "global_place_stages": [{
    "num_bins_x": 64, "num_bins_y": 64,
    "iteration": 1000,
    "learning_rate": 0.01,
    "wirelength": "weighted_average",
    "optimizer": "nesterov"
  }],
  "target_density": 0.70,
  "result_dir": ".../results"
}
```

### 使用方式

```bash
cd /home/james/projects
python3 maplace/src/verilog_to_def.py \
  gradmap/verilog_output/output.v \
  maplace/testcase/gradmap_output/iter_000 \
  --libcell  gradmap/libs/asap7_libcell_info.txt \
  --techlef  gradmap/libs/ASAP7/techlef/asap7_tech_1x_201209.lef \
  --lef      gradmap/libs/ASAP7/LEF/asap7sc7p5t_28_R_1x_220121a.lef \
  --design-name top \
  --docker-prefix /home/james/projects:/workspace
```

`--docker-prefix`：因為 `/home/james/projects` 是指向 `/data2_4TB/james/projects` 的 symlink，JSON 裡用 `os.path.realpath()` 取得真實路徑，再換成 Docker 的 `/workspace/...`。

### 輸出檔案

```
maplace/testcase/gradmap_output/iter_000/
├── top.def                              # DEF (UNPLACED components)
├── tech.lef                             # tech LEF (UNITS + SITE)
├── asap7sc7p5t_28_R_1x_220121a.lef     # cell LEF (MACRO definitions)
├── top.json                             # DREAMPlace config
└── top_summary.json                     # instance 清單 (供 read_placement.py 用)
```

---

## Step 3：DREAMPlace 跑 Placement（Docker）

### 環境

- Docker image：`dreamplace-maplace:ready`
- 掛載：`-v /home/james/projects/maplace:/workspace/maplace -v /home/james/projects/gradmap:/workspace/gradmap`
- PYTHONPATH：`/workspace/maplace/dreamplace/install:/workspace/maplace/dreamplace/install/dreamplace`

### 啟動

```bash
sudo docker run -it --gpus all \
  -v /home/james/projects/maplace:/workspace/maplace \
  -v /home/james/projects/gradmap:/workspace/gradmap \
  dreamplace-maplace:ready bash

# 在 Docker 裡
export PYTHONPATH=/workspace/maplace/dreamplace/install:/workspace/maplace/dreamplace/install/dreamplace
cd /workspace/maplace/dreamplace/install/dreamplace
python3 Placer.py /workspace/maplace/testcase/gradmap_output/iter_000/top.json
```

### DREAMPlace 做了什麼？

1. 讀入 LEF（cell 尺寸）+ DEF（netlist + 空白 placement）
2. 用 GPU-accelerated gradient descent 最佳化 cell 位置
3. 目標：最小化 HPWL（Half-Perimeter Wire Length）+ 密度懲罰
4. 收斂條件：Overflow < 0.1（cell 重疊率 < 10%）

### 輸出

```
results/top/top.gp.def    # Global Placement 結果
```

格式：原本 UNPLACED 的 cell 全部變成 `PLACED ( x y ) orient`：
```
- g3 INVxp67_ASAP7_75t_R
  + PLACED ( 14048 2062 ) FS ;
- g5 NAND2x1_ASAP7_75t_R
  + PLACED ( 13814 1592 ) N ;
```

### 結果確認

```
Cells placed:  2799  (2414 cells + 385 IO pins)
X range:       0 ~ 15876 DBU  (0.00 ~ 15.88 μm)
Y range:       0 ~ 15660 DBU  (0.00 ~ 15.66 μm)
Die:           15930 × 15930 DBU (15.93 × 15.93 μm)
Overflow:      9.9%  (< 10%, 收斂)
wHPWL:         2.06 × 10⁵
Runtime:       2.42 秒 (GPU)
```

---

## Step 4：`read_placement.py` — DEF → positions.csv（待實作）

### 目標

從 `top.gp.def` 提取每個 instance 的 (x, y) 座標，轉換成 GradMap C++ 可以讀入的格式。

### 輸出格式（positions.csv）

```csv
inst_name,x_um,y_um
g3,14.048,2.062
g5,13.814,1.592
...
```

換算：`x_um = x_dbu / 1000.0`（DEF UNITS DISTANCE MICRONS 1000）

---

## Step 5：GradMap 讀入位置（待實作）

### 目標

GradMap `optimizer_torch.cpp` 目前的位置初始化：
```cpp
// 現在：均勻分布（假位置）
torch_graph.set_uniform_positions(chip_w, chip_h, &graph);
```

需要新增：
```cpp
// 目標：從 DREAMPlace 結果讀入真實位置
torch_graph.load_positions_from_file(config.position_file, &graph);
```

在 config 裡加：
```
optimizer.position_file maplace/testcase/gradmap_output/iter_000/positions.csv
```

**物理意義**：用真實 placement 的 wire length 計算 delay，梯度就能同時優化 mapping 和 placement 的 co-optimization。

---

## 已知問題 / 踩過的坑

| 問題 | 原因 | 解法 |
|------|------|------|
| `Could not open LEF file` | `/home/james/projects` 是 symlink，realpath 是 `/data2_4TB/...`，Docker 不認識 | 把 LEF 複製到 output 目錄；`--docker-prefix` 用 `os.path.realpath()` 處理 |
| `ZeroDivisionError: site_width = 0` | ASAP7 cell LEF 沒有 UNITS，DREAMPlace 把 0.054 當整數 = 0 | 加上 tech.lef 提供 `DATABASE MICRONS 1000` |
| `Site name asap7_site not found` | DEF ROW 用了自訂 site name，LEF 裡不存在 | 改成 LEF 裡真實定義的 `asap7sc7p5t` |
| Docker 裡 symlink 斷掉 | `gradmap/libs/ASAP7 → /home/james/projects/libs/ASAP7`，Docker 沒掛 `libs/` | 把需要的 LEF 直接 copy 到 output 目錄 |
| GradMap binary 無法在 Docker 跑 | 在 Ubuntu 22.04 (glibc 2.34) 編譯，Docker 是 Ubuntu 18.04 (glibc 2.27) | 在 Docker 裡重新編譯：`./compile_docker.sh` |
| PyTorch API 不相容 | Docker 用 PyTorch 1.7.1，`index_reduce_` / `get_lr()` 是後來才加的 API | 改用 `global_max` 穩定 softmax；cast 到 `AdamOptions&` 用 `.lr()` |
