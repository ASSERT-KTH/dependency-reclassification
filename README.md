# Replication Package: Dependency Reclassification in JavaScript Projects

This repository accompanies the paper:

> **A Longitudinal Study of Dependency Reclassifications in JavaScript Projects**  
> Yuxin Liu, Cristian Bogdan, Benoit Baudry  
> Empirical Software Engineering (EMSE)

It provides the curated project list, per-project dependency-manifest histories, reclassification graphs, and the scripts used to mine and analyze dependency role changes in `package.json`.

**Repository:** https://github.com/ASSERT-KTH/dependency-reclassification

---

## Repository structure

```text
dependency-reclassification/
├── README.md
├── data/
│   ├── 33087_dataset.txt          # Curated project list (one owner/repo per line)
│   └── examples/
│       ├── example_analysis.txt
│       └── example_graph.json
├── datasets/
│   ├── splitted_files/            # Main corpus: *_analysis.txt and *_graph.json
│   └── splitted_files_2/          # Additional shards
└── scripts/
    ├── mining/                    # Clone repos and extract package.json diffs
    ├── graph/                     # Build dependency role-transition graphs
    └── analysis/                  # Practice taxonomy and RQ statistics
```

### What each data artifact is

| Path | Description |
|------|-------------|
| `data/33087_dataset.txt` | Curated set of 33,087 projects used in the paper. |
| `datasets/splitted_files/{i}_analysis.txt` | JSON-lines file. Each line is one commit that modifies declared dependencies in the root `package.json` on the default branch. |
| `datasets/splitted_files/{i}_graph.json` | Per-repository dependency graphs. For each dependency name, the file stores ordered role-transition segments (Core / Dev / Peer / Void). |
| `data/examples/` | Small examples for format inspection without browsing the full corpus. |

---

## Data schemas

### `*_analysis.txt` (JSON Lines)

Each line is a JSON object with fields such as:

| Field | Meaning |
|-------|---------|
| `repo` | GitHub repository (`owner/name`) |
| `default` | Default branch name |
| `commit` | Short commit SHA |
| `time` | Commit timestamp |
| `msg` | Commit message |
| `deps` / `devDeps` / `peerDeps` | Declared dependency counts after the commit |
| `diff` | Structural diff of `dependencies`, `devDependencies`, and `peerDependencies` (`insert` / `delete` / `update`, and the corresponding `*_dev` / `*_peer` fields) |

Version-only updates appear under `update*` and do **not** constitute role transitions in our analysis (dependencies are tracked by name).

### `*_graph.json`

Top-level object keyed by repository. Each repository maps dependency names to lists of transition segments. A transition event typically includes:

| Field | Meaning |
|-------|---------|
| `from` / `to` | Roles: `core`, `dev`, `peer`, or `void` |
| `from_commit` / `to_commit` | Commits bounding the transition |
| `from_time` / `to_time` | Timestamps (Unix) |
| `duration` | Seconds between the two commits |
| `commits` | Number of commits spanned |
| `is_relocation` | Whether the change is excluded as a cross-file relocation (when applicable) |

---

## Environment

- Python 3.9+
- Packages used by the scripts: `jsondiff`, `numpy`, `requests`, `scipy`
- Git (required only if re-running mining from GitHub)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install jsondiff numpy requests scipy
```

For mining against GitHub at scale, set a token via environment variable (do **not** hard-code tokens in scripts):

```bash
export GITHUB_TOKEN=ghp_xxx
```

---

## Reproduction overview

The study pipeline has four stages, matching Section 3 of the paper:

1. **Project selection** — curated list in `data/33087_dataset.txt`.
2. **Manifest history construction** — consecutive root `package.json` snapshots that change declared dependencies (`*_analysis.txt`).
3. **Reclassification event / sequence extraction** — field-level inserts/deletes → role transitions → per-dependency graphs (`*_graph.json`).
4. **Practice taxonomy and RQ analyses** — classify sequences into practices and compute prevalence, structure, and timing statistics.

### Minimal reproduction (recommended)

Most quantitative results can be recomputed from the released `*_graph.json` / `*_analysis.txt` files **without** re-cloning all repositories:

```bash
# Example: summarize transition counts
python scripts/analysis/generate_reclassification_statistics.py

# Example: classify reclassification practices
python scripts/analysis/classify_path_patterns.py
python scripts/analysis/compute_practice_duration_stats.py

# Example: batch-removal / timing / Core-to-Dev family analyses
python scripts/analysis/analyze_batch_removal_source_batchsize.py
python scripts/analysis/analyze_practice_timing_by_role.py
python scripts/analysis/analyze_core_to_dev_families.py

# Inferential tests and effect sizes reported in Section 4
python scripts/analysis/compute_inferential_stats.py
# writes data/reports/inferential_stats.json
```

Exact output paths are configured at the top of each script. Adjust `BASE_DIR` if needed so shards resolve under `datasets/splitted_files/`.
For `compute_inferential_stats.py`, pass `--packaged` to read graphs from `datasets/splitted_files/` when the original working-tree path is unavailable.

### Full re-mining (optional, expensive)

```bash
# 1) Mine manifest diffs for a shard of repositories
python scripts/mining/mine_package_json_history.py <shard_id>

# 2) Build role-transition graphs from an analysis shard
python scripts/graph/build_role_transition_graph.py <shard_id>
```

---

## Scripts

| Directory | Script | Role |
|-----------|--------|------|
| `scripts/mining/` | `mine_package_json_history.py` | Miner: clone repo, walk commits that touch `package.json`, emit `*_analysis.txt` |
| `scripts/graph/` | `build_role_transition_graph.py` | Build `*_graph.json` from `*_analysis.txt` |
| `scripts/graph/` | `extract_relocation_commits.py` | List relocation commits from tagged graphs (exclusion utility) |
| `scripts/analysis/` | `classify_path_patterns.py`, `compute_practice_duration_stats.py` | Practice taxonomy (§3.3.3–3.3.4) |
| `scripts/analysis/` | `generate_reclassification_statistics.py`, `summarize_transition_paths.py`, `summarize_transition_durations.py` | RQ1 transition / path prevalence |
| `scripts/analysis/` | `analyze_onetime_removal_by_batch_size.py`, `analyze_batch_removal_origins.py`, `analyze_batch_removal_source_batchsize.py`, `analyze_batch_removal_family_cohesion.py`, `analyze_selective_batch_reversal.py`, `analyze_removal_reversion_timing.py` | RQ2 removal / reversion |
| `scripts/analysis/` | `analyze_core_to_dev_families.py`, `classify_core_to_dev_dependencies.py` | RQ3 reassignment / family concentration |
| `scripts/analysis/` | `analyze_practice_timing_by_role.py` | RQ4 practice timing tables |
| `scripts/analysis/` | `compute_inferential_stats.py` | Statistical tests and effect sizes in §4 (chi-squared + Cramér's *V*, Mann–Whitney + Cliff's *δ*, log-rank) |
| `scripts/analysis/` | `compute_dataset_descriptive_stats.py` | Dataset descriptive statistics |

Path names in scripts may still refer to the original working-tree layout (`splitted_files/`). When in doubt, open the configuration block at the top of the script.

---

## Mapping to the paper

| Paper section | Primary artifacts |
|---------------|-------------------|
| §3.2 Project Selection | `data/33087_dataset.txt` |
| §3.3.1 Manifest histories | `*_analysis.txt`; mining scripts |
| §3.3.2 Reclassification events | `*_analysis.txt` → `*_graph.json` |
| §3.3.3–3.3.4 Sequences & practice taxonomy | `classify_path_patterns.py`, `compute_practice_duration_stats.py` |
| §4 Results (RQ1–RQ4) | scripts under `scripts/analysis/` |
| §4 statistical tests / effect sizes | `scripts/analysis/compute_inferential_stats.py`; `data/reports/inferential_stats.json` |

---

## Limitations of reuse

- Mining depends on public GitHub availability at collection time; some repositories may no longer be accessible.
- We analyze the **default branch** root `package.json` only.
- Released graphs already apply the study’s exclusion rules (initial introductions, relocations, version-only non-transitions). Re-mining without the same filters will not match the paper’s counts exactly.
- Scripts are research prototypes: expect hardcoded paths and shard ranges (`range(1, 108)`). They are provided for transparency and reuse, not as a polished CLI product.

---

## Citation

Please cite the EMSE paper when using this package. A BibTeX entry will be added upon publication.

---

## Contact

For questions about the replication package, contact the corresponding author listed in the paper.
