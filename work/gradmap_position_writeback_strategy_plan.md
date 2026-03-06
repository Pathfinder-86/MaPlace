# GradMap Placement Write-Back / Seed Strategy Plan

## 1. Goal
Make iterative placement feedback stable, interpretable, and configurable.

Current behavior mixes together three different concerns:
1. how DREAMPlace results are written back to graph nodes,
2. how uncovered / inactive AIG nodes receive positions,
3. how those positions are reused as the next placement seed.

The main problem is that these three concerns are currently coupled, so when placement quality becomes worse, it is hard to know whether the issue comes from:
- poor placer settings,
- incorrect write-back semantics,
- overly aggressive seed reuse,
- or bad propagation to uncovered nodes.

This plan separates those concerns and introduces **strategy-style configuration**, similar to `circuit.init_weights_strategy`.

---

## 2. What we learned from the latest experiments

### Confirmed
- DREAMPlace legalization **does run**.
- Primary I/O pin warm-start was a real bug; fixing I/O to boundary improved behavior.
- `placement_metrics.csv` now gives enough data to compare runs reliably.

### Still problematic
- Placement often looks fine at step 20 / 40, then degrades from step 60 onward.
- This strongly suggests the later seeds are drifting into a bad basin.
- The current uncovered-node propagation is too heuristic:
  - backward fanout averaging,
  - then forward fanin averaging.

That heuristic is easy to implement, but it has weak semantics. It can smear many internal AIG nodes into averaged locations that do not correspond to any real placed object.

---

## 3. Current root-cause hypothesis

The most likely cause is **bad seed quality**, not only bad placer parameters.

### 3.1 Current write-back issue
Placed DEF only gives coordinates for objects that really exist in the current mapped netlist.
But after read-back, GradMap tries to assign coordinates to many additional graph nodes that were not directly placed.

Current fallback:
- reverse topo: average fanout positions,
- forward topo: average fanin positions.

This causes several risks:
- position smoothing / collapse,
- artificial clustering,
- hidden nodes drifting toward local centroids,
- later seeds no longer representing real ownership.

### 3.2 Why this matters more than noise for now
`seed + small noise` can help escape a bad basin, but if the seed itself is semantically wrong, noise is only a patch.
So the preferred order is:
1. fix write-back semantics,
2. then add optional seed perturbation if needed,
3. then consider partial seed.

---

## 4. Design principle

We should treat placement write-back like weight initialization:
- explicit policy,
- config driven,
- easy to compare experimentally,
- easy to fall back to old behavior.

### Proposed config style
```ini
# --- Placement Write-Back Strategy ---
# 可選值：
#   - "active_only"       : 只回寫目前實際被放置到的節點
#   - "owner_propagation" : active node 直接回寫；covered/uncovered node 只繼承明確 owner 的位置 (推薦)
#   - "neighbor_average"  : 舊行為，使用 fanout/fanin 平均補位置
optimizer.placement_writeback_strategy owner_propagation
```

This mirrors the style of:
- `circuit.init_weights_strategy`
- `circuit.build_inverters_strategy`

---

## 5. Proposed strategy set

## 5.1 `neighbor_average`
### Meaning
Preserve the current behavior.

### Rules
- Read placed node coordinates from CSV.
- Missing nodes are filled by:
  1. backward fanout average,
  2. forward fanin average.

### Pros
- backward compatible,
- easy fallback / baseline.

### Cons
- semantically weak,
- likely source of seed contamination,
- hard to reason about.

### Use case
Only for regression comparison with old results.

---

## 5.2 `active_only`
### Meaning
Only nodes directly present in the placed DEF get updated positions.
All other graph nodes keep their existing coordinates.

### Rules
- If node id appears in placement CSV: overwrite with new `(x, y)`.
- Otherwise: keep previous graph position unchanged.
- No averaging.
- No guessed propagation.

### Pros
- simplest semantics,
- very controlled,
- easy to debug.

### Cons
- uncovered nodes may retain stale positions for many iterations,
- less smooth if graph structure changes a lot.

### Use case
Best first debugging baseline.
If this already stabilizes placement, then propagation was indeed the problem.

---

## 5.3 `owner_propagation` (recommended long-term direction)
### Meaning
Only propagate positions when there is a meaningful owner relationship.
Do **not** use generic neighborhood averaging.

### Rules
1. Directly placed active nodes get exact placed coordinates.
2. A covered / uncovered node receives a propagated coordinate **only if** we can identify a clear active owner.
3. If no clear owner exists, keep the old coordinate instead of inventing a new one.

### What counts as an owner
This needs to be derived from mapping semantics, not graph smoothing.
Possible owner definitions:
- the hard-selected match root that materialized as gate `g<node_id>`,
- an explicit covered-node relationship already known in the mapping data structure,
- a unique selected representative for a merged logic region.

### Important limitation
`owner_propagation` **alone does not guarantee** that every AIG node receives a fresh new `(x, y)` in every placement iteration.

Why not:
- some nodes are not directly materialized in the current hard-mapped netlist,
- some nodes may not have a unique owner,
- some nodes may not yet have enough mapping metadata to infer ownership safely.

So the correct design is not:
- "owner propagation guarantees full coverage"

but instead:
- "owner propagation updates positions only when the semantic source is trustworthy"
- and a separate fallback layer guarantees that timing / wire-cap evaluation never loses coverage.

### Pros
- semantically grounded,
- avoids artificial collapse,
- keeps continuity where ownership is real.

### Cons
- requires inspection of mapping data structures,
- slightly more implementation work.

### Use case
This should become the long-term default.

---

## 6. Implementation plan

## 6.0 Final write-back hierarchy (recommended runtime behavior)
The runtime logic should follow this order:

1. **direct placed node**
  - if DREAMPlace returns a coordinate for node `n`, use it.
2. **selected match ownership from ABC / mapping**
  - if node `n` is covered by a uniquely identified selected owner, inherit that owner position.
3. **polarity-pair fallback (`idx±1`)**
  - if the complementary polarity node has a trustworthy position, reuse it as a strong hint.
4. **keep old position**
  - if this node already had a prior position, keep it.
5. **global fallback**
  - only for nodes that still have no position at all.

This ordering matters because it separates:
- high-confidence write-back,
- medium-confidence semantic fallback,
- last-resort full-coverage fallback.

The key policy is:
> wrong new positions are more dangerous than old but stable positions.

---

## 6.1 Two independent policy dimensions
To keep the system flexible, the design should explicitly separate:

### A. write-back strategy
How we produce **new** positions from the current placement result.

Example config:
```ini
optimizer.placement_writeback_strategy active_only
```

Possible values:
- `active_only`
- `owner_propagation`
- `neighbor_average`

### B. missing-position fallback strategy
How we ensure **every node still has a usable position** for wire-cap / STA.

Example config:
```ini
optimizer.placement_missing_position_strategy keep_old_then_uniform
```

Possible values:
- `keep_old`
- `keep_old_then_uniform`
- `legacy_neighbor_average`

This split is necessary because wire-cap and STA need robust total coverage, while write-back semantics should remain conservative.

## Phase 0: no behavioral change except configuration scaffolding
Add config parsing and strategy enum/string handling.

### Files likely to change
- `gradmap/src/optimizer/optimizer.h`
- `gradmap/src/flow/flow_manager.cpp`
- `gradmap/src/mapping/circuit_graph_torch.cpp`
- possibly `gradmap/src/mapping/circuit_graph_torch.h`

### New config
```ini
optimizer.placement_writeback_strategy owner_propagation
optimizer.placement_missing_position_strategy keep_old_then_uniform
```

### Behavior in Phase 0
- default may temporarily remain `neighbor_average` for compatibility,
- or we can switch default to `owner_propagation` once implemented and validated.

---

## Phase 1: implement `active_only`
This is the cleanest controlled baseline.

### Behavior
- direct placed nodes updated,
- all others keep old positions,
- if a node has no old position at all, use the configured missing-position fallback.

### Why first
- minimal ambiguity,
- easiest to validate,
- isolates whether propagation itself is causing damage.

### Expected experiment outcome
If `active_only` improves step 60+ overflow behavior, then current propagation is very likely harming seeds.

---

## Phase 2: implement `owner_propagation`
Replace heuristic averaging with mapping-aware propagation.

### Work items
1. Inspect available mapping metadata for covered/uncovered ownership.
2. Identify which node should inherit from which active mapped node.
3. Propagate only through explicit ownership.
4. If multiple owners or ambiguous ownership exist:
   - do not average,
   - keep previous coordinate.
5. If ownership is unavailable, optionally try polarity-pair fallback before using global fallback.

### Important policy
**Ambiguity should preserve old state, not synthesize new state.**

This is the key philosophy change.

---

## Phase 3: retain `neighbor_average` as legacy fallback
Do not delete the old behavior immediately.
Keep it as an experiment mode.

This helps:
- regression comparison,
- ablation studies,
- emergency fallback.

---

## 6.2 Why polarity-pair fallback is useful
GradMap already encodes a strong relationship between positive and negative AIG nodes:
- negative node ids are paired with positive node ids by `idx±1`,
- these pairs differ logically by inversion.

This does **not** mean they are always physically identical.
However, it is still a much stronger signal than generic graph-neighbor averaging.

So polarity-pair fallback should be treated as:
- a strong semantic hint,
- weaker than direct placement,
- weaker than explicit owner mapping,
- but stronger than global heuristic smoothing.

This is especially useful before the richer ABC ownership reconstruction is fully implemented.

---

## 6.3 ABC ownership reconstruction (future research direction)
The strongest long-term approach is to recover, from ABC or the mapping layer, exactly which AIG nodes are covered by each selected match.

That would allow:
- accurate owner propagation,
- cleaner hidden-node write-back,
- less reliance on heuristics,
- stronger explainability of placement seeds.

This direction is intentionally deferred because it requires additional research and code archaeology.
The near-term implementation should therefore use the hierarchy above and leave explicit room for plugging in richer ABC ownership data later.

---

## 7. Optional future knobs (not first step)
These are useful later, but not needed before fixing write-back semantics.

### 7.1 Seed perturbation
```ini
optimizer.placement_seed_noise_um 0.0
```
Meaning:
- after generating component seeds, add bounded random perturbation.

Use only after write-back semantics are fixed.

### 7.2 Partial seed
```ini
optimizer.placement_seed_strategy full
# full | active_only | sampled | thresholded
```
Use only after we know whether full seed is truly the issue.

### 7.3 IO placement policy
Already improved by fixing PIs/POs to boundary.
Later we can make this configurable:
```ini
optimizer.placement_io_strategy boundary_lr
# boundary_lr | boundary_4side | clustered
```
But this is lower priority now.

---

## 8. Concrete recommendation

### Recommended immediate implementation order
1. add `placement_writeback_strategy` config,
2. add `placement_missing_position_strategy` config,
3. implement `active_only`,
4. run experiment,
5. implement `owner_propagation`,
6. add polarity-pair fallback,
7. compare against legacy `neighbor_average`,
8. only then consider `seed + small noise`.

### Recommended default direction
Long-term preferred default:
```ini
optimizer.placement_writeback_strategy owner_propagation
```

Short-term safest first experiment:
```ini
optimizer.placement_writeback_strategy active_only
optimizer.placement_missing_position_strategy keep_old_then_uniform
```

---

## 9. Validation plan
For each strategy, compare in `placement_metrics.csv`:
- step 20 / 40 / 60 / 80 / 100,
- final overflow,
- final max density,
- whether step 40 and step 60 still converge,
- whether later initial overflow starts lower or higher.

### Success criteria
A new strategy is better if it does **not** just improve step 20, but also:
- keeps step 40 convergent,
- reduces step 60+ overflow,
- prevents monotonic congestion growth across later steps.

---

## 10. Final decision proposal

### What we should implement next
**Implement configurable write-back strategies now.**

### Why
Because this addresses the likely semantic bug directly and keeps future experiments flexible, instead of hard-coding another heuristic.

### First implementation target
- add `optimizer.placement_writeback_strategy`
- add `optimizer.placement_missing_position_strategy`
- implement:
  - `active_only`
  - `neighbor_average` (current logic preserved)
- add hierarchy support for:
  - polarity-pair fallback
  - keep-old fallback
- leave room for:
  - `owner_propagation`
  - ABC ownership reconstruction

This gives a clean framework first, then we can plug in better propagation logic safely.
