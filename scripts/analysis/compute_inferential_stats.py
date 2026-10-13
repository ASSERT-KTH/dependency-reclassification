#!/usr/bin/env python3
"""Inferential statistics for the role comparisons reported in the paper.

Compares dependency roles (Core / Dev / Peer) with the tests commonly used in
EMSE dependency studies:

  - chi-square with Cramer's V  (practice composition, batch-removal shares)
  - Mann-Whitney U with Cliff's delta  (practice durations)
  - log-rank  (Kaplan-Meier first reclassification / return curves)

Point estimates use the same practice, duration, batch, and survival definitions
as the paper (and the existing analysis scripts). At this corpus size, p-values
are expected to be small; interpret differences via effect sizes (V, Cliff's
delta) and absolute gaps (percentage points / days).

Usage (from the repository root):
    python3 scripts/analysis/compute_inferential_stats.py
Output: data/reports/inferential_stats.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
# Default: original working graphs with is_relocation flags (used for the paper numbers).
# The packaged datasets/ under this repo omit those flags; pass --packaged to use them.
ORIGINAL_GRAPH_DIR = ROOT.parent.parent / "splitted_files"
PACKAGED_GRAPH_DIRS = [ROOT / "datasets" / "splitted_files", ROOT / "datasets" / "splitted_files_2"]
OUT_JSON = ROOT / "data" / "reports" / "inferential_stats.json"
DATASET_LIST = ROOT / "data" / "33087_dataset.txt"

ROLES = ("core", "dev", "peer")
PAIRS = (("core", "dev"), ("core", "peer"), ("dev", "peer"))
DAY = 86400.0
X3Y = 365.0 * 3

# Table 1 categories (classification order mirrors classify_path_patterns.py)
CATS = ("onestep", "multistep", "reversion", "oscillation", "to_core", "to_dev", "to_peer")
CAT_LABEL = {
    "onestep": "One-step removal",
    "multistep": "Multi-step removal",
    "reversion": "Removal reversion",
    "oscillation": "Role oscillation",
    "to_core": "Reclassify to Core",
    "to_dev": "Reclassify to Dev",
    "to_peer": "Reclassify to Peer",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# Per-segment extractors (mirroring existing scripts)
# ----------------------------------------------------------------------------

def table1_category(segment):
    """Practice taxonomy of Section 3.3.4 (reproduces Table 1 exactly).

    Rules are applied in order on the role path (leading Void stripped):
      1. role oscillation: the sequence of non-Void roles (consecutive
         duplicates merged) has >= 3 entries and the initial role reappears
         later in it, i.e. the dependency leaves its role and returns after
         visiting another role;
      2. one-step removal: path == [role, Void];
      3. removal reversion: the path only alternates between the initial
         role and Void (removed and reintroduced to the same role);
      4. multi-step removal: any other path ending in Void;
      5. role reassignment: terminal role differs from the initial role.
    """
    if not segment:
        return None, None
    seg = sorted(segment, key=lambda x: float(x.get("from_time", 0)))
    p = [seg[0]["from"]] + [t["to"] for t in seg]
    if p and p[0] == "void":
        p = p[1:]
    if len(p) < 2 or p[0] not in ROLES:
        return None, None
    born = p[0]
    active = [s for s in p if s != "void"]
    uniq = [active[0]]
    for r in active[1:]:
        if r != uniq[-1]:
            uniq.append(r)
    if len(uniq) >= 3 and born in uniq[1:]:
        return born, "oscillation"
    if len(p) == 2 and p[1] == "void":
        return born, "onestep"
    if all(x in {born, "void"} for x in p):
        return born, "reversion"
    if p[-1] == "void":
        return born, "multistep"
    if p[-1] in ROLES and p[-1] != born:
        return born, f"to_{p[-1]}"
    return None, None


def duration_entry(segment):
    """compute_practice_duration_stats.py logic. Returns (practice, role, s1, tot) or None."""
    if not segment:
        return None
    seg = sorted(segment, key=lambda x: float(x.get("from_time", 0)))
    traj = []
    first_from = seg[0].get("from")
    if first_from and first_from != "void":
        traj.append((first_from, 0.0))
    cur = first_from if first_from else "void"
    for ev in seg:
        if ev.get("is_relocation"):
            return None
        to = ev.get("to")
        if to != cur:
            traj.append((to, float(ev.get("duration", 0))))
            cur = to
    if not traj:
        return None
    born = traj[0][0]
    if born == "void" and len(traj) > 1:
        born = traj[1][0]
        traj = traj[1:]
    if born not in ROLES:
        return None
    states = [t[0] for t in traj]
    durs = [t[1] / DAY for t in traj]
    active = [s for s in states if s != "void"]
    uniq = [active[0]] if active else []
    for r in active[1:]:
        if r != uniq[-1]:
            uniq.append(r)

    if len(uniq) >= 3:
        if len(durs) >= 3:
            return ("Role oscillation", born, durs[1], durs[1] + durs[2])
        return None
    if len(states) >= 3 and states[1] == "void" and states[2] == states[0]:
        return ("Removal reversion", born, durs[1], durs[1] + durs[2])
    if len(states) == 2 and states[1] == "void":
        return ("One-time removal", born, durs[1], durs[1])
    if len(states) >= 3 and states[-1] == "void" and states[0] != "void" and states[1] != "void":
        return ("Multi-step removal", born, durs[1], sum(durs[1:]))
    if states[-1] in ROLES and states[-1] != born:
        tot = sum(durs[1:])
        return (f"Reclassify to {states[-1].capitalize()}", born, tot, tot)
    return None


def onestep_removal_commit(segment):
    """analyze_onetime_removal_by_batch_size.py: returns (role, to_commit) for (void->)role->void."""
    if not segment:
        return None
    raw = [t["from"] for t in segment] + [segment[-1]["to"]]
    if raw[0] == "void":
        raw = raw[1:]
    if len(raw) != 2 or raw[0] not in ROLES or raw[1] != "void":
        return None
    role = raw[0]
    if segment[0]["from"] == "void" and len(segment) > 1 and segment[1]["to"] == "void":
        rem = segment[1]
    elif segment[0]["from"] == role:
        rem = segment[0]
    else:
        return None
    if rem.get("is_relocation") is True:
        return None
    tc = rem.get("to_commit")
    if not tc:
        return None
    return role, tc


def reversion_commits(segment):
    """analyze_selective_batch_reversal.py: role->void->role; returns (role, del_commit, rev_commit, strict)."""
    if not segment:
        return None
    seg = sorted(segment, key=lambda x: float(x.get("from_time", 0)))
    born_from = seg[0].get("from")
    traj = []
    if born_from and born_from != "void":
        traj.append({"state": born_from, "art": True})
    for ev in seg:
        traj.append({"state": ev.get("to"), "tc": ev.get("to_commit"), "rel": ev.get("is_relocation", False), "art": False})
    path, events = [traj[0]["state"]], []
    cur = traj[0]["state"]
    for e in traj:
        if e.get("art") or e.get("rel"):
            continue
        if e["state"] != cur:
            path.append(e["state"])
            events.append(e)
            cur = e["state"]
    if len(path) == 3 and path[1] == "void" and path[0] == path[2] and path[0] in ROLES:
        strict = path[0] == born_from
        return path[0], events[0]["tc"], events[1]["tc"], strict
    return None


def repo_observation_end(deps) -> float:
    end = 0.0
    for segments in deps.values():
        for segment in segments:
            for ev in segment:
                end = max(end, float(ev.get("to_time", 0) or 0), float(ev.get("from_time", 0) or 0))
    return end


def survival_first(segment, repo_end):
    if not segment:
        return None
    seg = sorted(segment, key=lambda x: float(x.get("from_time", 0)))
    first = seg[0]
    frm, to = first.get("from"), first.get("to")
    if frm == "void" and to in ROLES:
        born, birth_t, start = to, float(first.get("to_time", 0)), 1
    elif frm in ROLES:
        born, birth_t, start = frm, float(first.get("from_time", 0)), 0
    else:
        return None
    for ev in seg[start:]:
        if ev.get("from") == born and ev.get("to") != born:
            d = float(ev.get("duration", 0)) / DAY
            return (born, d, 1) if d >= 0 else None
    return born, max(0.0, (repo_end - birth_t) / DAY), 0


def survival_return(segment, repo_end):
    if not segment:
        return None
    seg = sorted(segment, key=lambda x: float(x.get("from_time", 0)))
    first = seg[0]
    frm, to = first.get("from"), first.get("to")
    if frm == "void" and to in ROLES:
        born, start = to, 1
    elif frm in ROLES:
        born, start = frm, 0
    else:
        return None
    leave_i = leave_t = None
    for i, ev in enumerate(seg[start:], start=start):
        if ev.get("from") == born and ev.get("to") != born:
            leave_i, leave_t = i, float(ev.get("to_time", 0))
            break
    if leave_i is None:
        return None
    for ev in seg[leave_i + 1:]:
        if ev.get("to") == born:
            d = (float(ev.get("to_time", 0)) - leave_t) / DAY
            return (born, d, 1) if d >= 0 else None
    return born, max(0.0, (repo_end - leave_t) / DAY), 0


# ----------------------------------------------------------------------------
# Data collection: per-project sufficient statistics
# ----------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.repo_index = {}
        # Table 1: counts per project per role per category; project indicators
        self.t1_counts = {r: defaultdict(lambda: np.zeros(len(CATS), dtype=np.int64)) for r in ROLES}
        # batch removal: per project per role -> dict size counts
        self.batch = {r: defaultdict(lambda: np.zeros(6, dtype=np.int64)) for r in ROLES}
        # [deps_total, deps_in_size>=2, deps_in_size>=5, deps_size1, commits_total, commits_size>=2]
        # partial reversal: per project -> [n_rev_ge2, n_partial_ge2, n_rev_ge3, n_partial_ge3] x {strict, loose}
        self.partial = {"strict": defaultdict(lambda: np.zeros(4, dtype=np.int64)),
                        "loose": defaultdict(lambda: np.zeros(4, dtype=np.int64))}
        # durations: (practice, role) -> lists of (proj, s1, tot)
        self.dur = defaultdict(lambda: {"p": [], "s1": [], "tot": []})
        # survival: panel -> role -> lists of (proj, t, e)
        self.surv = {"first": {r: {"p": [], "t": [], "e": []} for r in ROLES},
                     "return": {r: {"p": [], "t": [], "e": []} for r in ROLES}}
        self.n_reclass_projects = 0
        self.n_projects = 0

    def pid(self, repo):
        if repo not in self.repo_index:
            self.repo_index[repo] = len(self.repo_index)
        return self.repo_index[repo]


def process_repo(store: Store, repo: str, deps: dict):
    pid = store.pid(repo)
    store.n_projects += 1
    end = repo_observation_end(deps)
    reclass = False

    removal_commits = {r: defaultdict(int) for r in ROLES}
    del_batches = {"strict": defaultdict(set), "loose": defaultdict(set)}
    rev_info = {"strict": defaultdict(set), "loose": defaultdict(set)}

    for dep, segments in deps.items():
        for seg in segments:
            if not seg:
                continue
            born, cat = table1_category(seg)
            if cat is not None:
                store.t1_counts[born][pid][CATS.index(cat)] += 1
                reclass = True

            d = duration_entry(seg)
            if d is not None:
                prac, role, s1, tot = d
                g = store.dur[(prac, role)]
                g["p"].append(pid)
                g["s1"].append(s1)
                g["tot"].append(tot)

            oc = onestep_removal_commit(seg)
            if oc is not None:
                removal_commits[oc[0]][oc[1]] += 1

            rv = reversion_commits(seg)
            if rv is not None:
                role, dc, rc, strict = rv
                for mode in ("loose",) + (("strict",) if strict else ()):
                    del_batches[mode][dc].add((dep, role))
                    rev_info[mode][(rc, dc)].add((dep, role))

            if end > 0:
                sf = survival_first(seg, end)
                if sf is not None:
                    s = store.surv["first"][sf[0]]
                    s["p"].append(pid); s["t"].append(sf[1]); s["e"].append(sf[2])
                sr = survival_return(seg, end)
                if sr is not None:
                    s = store.surv["return"][sr[0]]
                    s["p"].append(pid); s["t"].append(sr[1]); s["e"].append(sr[2])

    if reclass:
        store.n_reclass_projects += 1

    for r in ROLES:
        if removal_commits[r]:
            arr = store.batch[r][pid]
            for size in removal_commits[r].values():
                arr[0] += size
                arr[4] += 1
                if size >= 2:
                    arr[1] += size
                    arr[5] += 1
                if size >= 5:
                    arr[2] += size
                if size == 1:
                    arr[3] += 1

    for mode in ("strict", "loose"):
        for (rc, dc), rev_deps in rev_info[mode].items():
            orig = del_batches[mode][dc]
            if len(orig) >= 2:
                arr = store.partial[mode][pid]
                arr[0] += 1
                if len(rev_deps) < len(orig):
                    arr[1] += 1
                if len(orig) >= 3:
                    arr[2] += 1
                    if len(rev_deps) < len(orig):
                        arr[3] += 1


def load_all(graph_dirs, limit: int | None = None, use_curated: bool = True) -> Store:
    store = Store()
    paths = []
    for d in graph_dirs:
        if d.is_dir():
            paths.extend(sorted(p for p in d.glob("*_graph.json") if p.name != "0_graph.json"))
    if limit:
        paths = paths[:limit]
    log(f"Found {len(paths)} graph files in {[str(d) for d in graph_dirs]}")
    valid = None
    if use_curated and DATASET_LIST.is_file():
        with open(DATASET_LIST, encoding="utf-8") as f:
            valid = {line.strip() for line in f if line.strip()}
        log(f"Restricting to {len(valid)} curated projects from {DATASET_LIST.name}")
    seen = set()
    for i, path in enumerate(paths, 1):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for repo, deps in data.items():
            if repo in seen or (valid is not None and repo not in valid):
                continue
            seen.add(repo)
            process_repo(store, repo, deps)
        log(f"Loaded {i}/{len(paths)} files, {store.n_projects} projects")
    return store


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------

def to_matrix(dd, P, k):
    M = np.zeros((P, k), dtype=np.float64)
    for pid, arr in dd.items():
        M[pid] = arr
    return M


def median(vals):
    if len(vals) == 0:
        return float("nan")
    s = np.sort(np.asarray(vals, float))
    mid = (len(s) - 1) / 2.0
    lo, hi = int(np.floor(mid)), int(np.ceil(mid))
    return float(s[lo] if lo == hi else s[lo] * (hi - mid) + s[hi] * (mid - lo))


def kaplan_meier_surv_at(durations, events, t_query):
    """KM survival S(t_query); durations/events already aligned."""
    t = np.asarray(durations, float)
    e = np.asarray(events, int)
    if len(t) == 0:
        return 1.0
    order = np.argsort(t, kind="mergesort")
    t, e = t[order], e[order]
    unique = np.unique(t[e == 1])
    s = 1.0
    n = len(t)
    idx = 0
    for ut in unique:
        while idx < n and t[idx] < ut:
            idx += 1
        at_risk = n - idx
        deaths = 0
        j = idx
        while j < n and t[j] == ut:
            if e[j] == 1:
                deaths += 1
            j += 1
        if at_risk > 0 and deaths > 0 and ut <= t_query:
            s *= 1.0 - deaths / at_risk
        idx = j
        if ut > t_query:
            break
    return float(s)


def cliffs_delta(x, y):
    """Cliff's delta via Mann-Whitney U (positive => x tends to be larger)."""
    u = stats.mannwhitneyu(x, y, alternative="two-sided")
    delta = 2.0 * u.statistic / (len(x) * len(y)) - 1.0
    return float(delta), float(u.pvalue)


def cramers_v(table):
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    n = table.sum()
    k = min(table.shape) - 1
    return float(chi2), float(p), int(dof), float(np.sqrt(chi2 / (n * k))) if k > 0 else float("nan")


def pct_point(numer, denom):
    return float(100.0 * numer / denom) if denom > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only load the first N graph files (smoke test)")
    ap.add_argument("--out", type=Path, default=OUT_JSON)
    ap.add_argument("--packaged", action="store_true",
                    help="use packaged datasets/ (no is_relocation); default uses original splitted_files/")
    ap.add_argument("--graph-dir", type=Path, default=None, action="append",
                    help="override graph directory (repeatable)")
    ap.add_argument("--no-curated", action="store_true", help="do not restrict to 33087_dataset.txt")
    args = ap.parse_args()

    if args.graph_dir:
        graph_dirs = args.graph_dir
    elif args.packaged:
        graph_dirs = PACKAGED_GRAPH_DIRS
    else:
        graph_dirs = [ORIGINAL_GRAPH_DIR]
        if not ORIGINAL_GRAPH_DIR.is_dir():
            log(f"Original graph dir missing ({ORIGINAL_GRAPH_DIR}); falling back to packaged datasets/")
            graph_dirs = PACKAGED_GRAPH_DIRS

    t0 = time.time()
    store = load_all(graph_dirs, args.limit, use_curated=not args.no_curated)
    P = len(store.repo_index)
    log(f"Projects: {P}, reclassifying: {store.n_reclass_projects}; load took {time.time()-t0:.0f}s")

    T1 = {r: to_matrix(store.t1_counts[r], P, len(CATS)) for r in ROLES}
    T1_ind = {r: (T1[r] > 0).astype(float) for r in ROLES}
    T1_has = {r: (T1[r].sum(axis=1) > 0).astype(float) for r in ROLES}
    BT = {r: to_matrix(store.batch[r], P, 6) for r in ROLES}
    PR = {m: to_matrix(store.partial[m], P, 4) for m in ("strict", "loose")}

    DUR = {}
    for key, g in store.dur.items():
        for which in ("s1", "tot"):
            DUR[(key[0], key[1], which)] = np.asarray(g[which], float)
    pool_tot = []
    for key, g in store.dur.items():
        pool_tot.extend(g["tot"])
    pool_tot = np.asarray(pool_tot, float)

    surv = store.surv
    store.surv = None

    k, n = store.n_reclass_projects, P
    out = {
        "meta": {
            "projects": P,
            "reclassifying_projects": k,
            "methods": [
                "chi-square with Cramer's V",
                "Mann-Whitney U with Cliff's delta",
                "log-rank on Kaplan-Meier curves",
            ],
            "note": "At this corpus size, interpret differences via effect sizes and absolute gaps.",
        },
        "overall_prevalence": {"share_pct": pct_point(k, n)},
    }

    # ---------- Table 1 ----------
    out["table1"] = {"dependency_level": {}, "project_level": {}, "N_deps": {}, "N_projs": {}}
    for r in ROLES:
        out["table1"]["N_deps"][r] = int(T1[r].sum())
        out["table1"]["N_projs"][r] = int(T1_has[r].sum())
        dep_tot = T1[r].sum()
        proj_n = T1_has[r].sum()
        for i, c in enumerate(CATS):
            label = CAT_LABEL[c]
            out["table1"]["dependency_level"].setdefault(label, {})[r] = pct_point(T1[r][:, i].sum(), dep_tot)
            out["table1"]["project_level"].setdefault(label, {})[r] = pct_point(T1_ind[r][:, i].sum(), proj_n)

    def comp5(r):
        c = T1[r].sum(axis=0)
        return np.array([c[0], c[1], c[2], c[3], c[4] + c[5] + c[6]])

    tab = np.array([comp5(r) for r in ROLES])
    chi2, p, dof, V = cramers_v(tab)
    out["table1"]["chi2_composition"] = {
        "chi2": chi2, "dof": dof, "p": p, "cramers_v": V,
        "categories": ["onestep", "multistep", "reversion", "oscillation", "reassignment"],
    }
    out["table1"]["chi2_pairwise_composition"] = {}
    for a, c in PAIRS:
        sub = np.array([comp5(a), comp5(c)])
        sub = sub[:, sub.sum(axis=0) > 0]
        chi2, p, dof, V = cramers_v(sub)
        out["table1"]["chi2_pairwise_composition"][f"{a}-{c}"] = {
            "chi2": chi2, "dof": dof, "p": p, "cramers_v": V,
        }

    # ---------- Batch removal ----------
    out["batch_removal"] = {
        "batch_dep_ge2": {"label": "share of one-step removals in commits deleting >=2 deps (dependency-weighted)", "by_role": {}},
        "batch_dep_ge5": {"label": "share of one-step removals in commits deleting >=5 deps (dependency-weighted)", "by_role": {}},
        "batch_commit_size1": {"label": "share of one-step removal commits deleting exactly 1 dep", "by_role": {}},
        "batch_commit_ge2": {"label": "share of one-step removal commits deleting >=2 deps", "by_role": {}},
        "chi2_pairwise_dep_ge2": {},
    }
    for r in ROLES:
        b = BT[r].sum(axis=0)
        out["batch_removal"]["batch_dep_ge2"]["by_role"][r] = pct_point(b[1], b[0])
        out["batch_removal"]["batch_dep_ge5"]["by_role"][r] = pct_point(b[2], b[0])
        out["batch_removal"]["batch_commit_size1"]["by_role"][r] = pct_point(b[3], b[4])
        out["batch_removal"]["batch_commit_ge2"]["by_role"][r] = pct_point(b[5], b[4])
    for a, c in PAIRS:
        ba, bc = BT[a].sum(axis=0), BT[c].sum(axis=0)
        sub = np.array([[ba[1], ba[0] - ba[1]], [bc[1], bc[0] - bc[1]]])
        chi2, p, dof, phi = cramers_v(sub)
        out["batch_removal"]["chi2_pairwise_dep_ge2"][f"{a}-{c}"] = {"chi2": chi2, "p": p, "phi": phi}

    # ---------- Partial reversal (point estimates only) ----------
    out["partial_reversal"] = {}
    for m in ("strict", "loose"):
        q = PR[m].sum(axis=0)
        out["partial_reversal"][m] = {
            "n_batch_reversions_ge2": int(q[0]),
            "partial_ge2_pct": pct_point(q[1], q[0]),
            "n_batch_reversions_ge3": int(q[2]),
            "partial_ge3_pct": pct_point(q[3], q[2]),
        }

    # ---------- Durations ----------
    out["durations"] = {
        "overall_median_days": median(pool_tot),
        "by_practice": {},
        "core_to_dev_vs_dev_to_core": {},
    }
    pracs = sorted({k[0] for k in store.dur})
    for prac in pracs:
        for which in ("s1", "tot"):
            if prac == "One-time removal" and which == "s1":
                continue
            if prac.startswith("Reclassify") and which == "s1":
                continue
            roles_present = [r for r in ROLES if (prac, r, which) in DUR and len(DUR[(prac, r, which)])]
            if not roles_present:
                continue
            entry = {
                "median_days": {r: median(DUR[(prac, r, which)]) for r in roles_present},
                "n": {r: int(len(DUR[(prac, r, which)])) for r in roles_present},
                "mannwhitney_cliffs": {},
            }
            for a, c in PAIRS:
                if a in roles_present and c in roles_present:
                    dlt, pv = cliffs_delta(DUR[(prac, a, which)], DUR[(prac, c, which)])
                    entry["mannwhitney_cliffs"][f"{a}-{c}"] = {"cliffs_delta": dlt, "p": pv}
            out["durations"]["by_practice"][f"{prac} [{which}]"] = entry

    ka, kc = ("Reclassify to Dev", "core", "tot"), ("Reclassify to Core", "dev", "tot")
    if ka in DUR and kc in DUR:
        dlt, pv = cliffs_delta(DUR[ka], DUR[kc])
        out["durations"]["core_to_dev_vs_dev_to_core"] = {
            "median_core_to_dev": median(DUR[ka]),
            "median_dev_to_core": median(DUR[kc]),
            "diff_days": median(DUR[ka]) - median(DUR[kc]),
            "cliffs_delta": dlt,
            "mannwhitney_p": pv,
        }

    # ---------- Survival ----------
    out["survival"] = {}
    for panel in ("first", "return"):
        out["survival"][panel] = {"n": {}, "S_3y_pct": {}, "cumulative_incidence_3y_pct": {}, "logrank_pairwise": {}}
        for r in ROLES:
            t = np.asarray(surv[panel][r]["t"], float)
            e = np.asarray(surv[panel][r]["e"], int)
            s3 = kaplan_meier_surv_at(t, e, X3Y)
            out["survival"][panel]["n"][r] = {"n": int(len(t)), "events": int(e.sum())}
            out["survival"][panel]["S_3y_pct"][r] = 100.0 * s3
            out["survival"][panel]["cumulative_incidence_3y_pct"][r] = 100.0 * (1.0 - s3)
        if hasattr(stats, "logrank"):
            for a, c in PAIRS:
                ta = np.asarray(surv[panel][a]["t"], float)
                ea = np.asarray(surv[panel][a]["e"], int)
                tc = np.asarray(surv[panel][c]["t"], float)
                ec = np.asarray(surv[panel][c]["e"], int)
                xa = stats.CensoredData.right_censored(ta, ea == 0)
                xc = stats.CensoredData.right_censored(tc, ec == 0)
                res = stats.logrank(xa, xc)
                out["survival"][panel]["logrank_pairwise"][f"{a}-{c}"] = {
                    "statistic": float(res.statistic),
                    "p": float(res.pvalue),
                }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=float)
    log(f"Wrote {args.out} ({time.time()-t0:.0f}s total)")

    print("\n=== Inferential statistics ===")
    print(f"Reclassifying projects: {k}/{n} = {100*k/n:.1f}%")
    print("Table 1 N deps:", out["table1"]["N_deps"])
    print("Table 1 N projs:", out["table1"]["N_projs"])
    for c in CATS:
        label = CAT_LABEL[c]
        pts = " / ".join(f"{out['table1']['dependency_level'][label][r]:.1f}" for r in ROLES)
        print(f"  dep  {label:<20} {pts}")
    cc = out["table1"]["chi2_composition"]
    print(f"Composition chi2={cc['chi2']:.0f} dof={cc['dof']} p={cc['p']:.3g} V={cc['cramers_v']:.3f}")
    for a, c in PAIRS:
        v = out["table1"]["chi2_pairwise_composition"][f"{a}-{c}"]
        print(f"  {a}-{c}: V={v['cramers_v']:.3f} p={v['p']:.3g}")
    for s in ("batch_dep_ge2", "batch_dep_ge5", "batch_commit_size1"):
        pts = " / ".join(f"{out['batch_removal'][s]['by_role'][r]:.1f}" for r in ROLES)
        print(f"Batch {s:<20} {pts}")
    for a, c in PAIRS:
        v = out["batch_removal"]["chi2_pairwise_dep_ge2"][f"{a}-{c}"]
        print(f"  batch ge2 {a}-{c}: phi={v['phi']:.3f} p={v['p']:.3g}")
    print(f"Overall median duration {out['durations']['overall_median_days']:.0f} days")
    for name, e in out["durations"]["by_practice"].items():
        pts = " / ".join(f"{e['median_days'][r]:.0f}" for r in ROLES if r in e["median_days"])
        mw = "; ".join(f"{k} δ={v['cliffs_delta']:+.2f} p={v['p']:.3g}" for k, v in e["mannwhitney_cliffs"].items())
        print(f"  {name:<32} {pts:<20} | {mw}")
    x = out["durations"]["core_to_dev_vs_dev_to_core"]
    if x:
        print(f"Core->Dev {x['median_core_to_dev']:.0f} vs Dev->Core {x['median_dev_to_core']:.0f}: "
              f"δ={x['cliffs_delta']:+.3f} MW p={x['mannwhitney_p']:.3g}")
    for panel in ("first", "return"):
        e = out["survival"][panel]
        pts = " / ".join(f"{e['cumulative_incidence_3y_pct'][r]:.1f}" for r in ROLES)
        print(f"Survival {panel} 3y incidence {pts}")
        for k2, v in e["logrank_pairwise"].items():
            print(f"  logrank {k2}: p={v['p']:.3g}")


if __name__ == "__main__":
    sys.exit(main())
