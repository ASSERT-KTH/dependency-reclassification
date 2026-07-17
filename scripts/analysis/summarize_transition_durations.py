import json
import os
from glob import glob
from collections import defaultdict, Counter
import statistics
import numpy as np

# Directory containing JSON graph files
graph_files = sorted(glob("splitted_files/*_graph.json"))

# Structures to hold data
transition_data = defaultdict(list)
dependency_counter = defaultdict(Counter)
dependency_sets = defaultdict(set)

def add_transition(from_state, to_state, duration, commits, dependency):
    trans_type = f"{from_state}->{to_state}"
    transition_data[trans_type].append((duration, commits))
    dependency_counter[trans_type][dependency] += 1
    dependency_sets[trans_type].add(dependency)

def percentile(data, p):
    if not data:
        return 0
    data = sorted(data)
    k = (len(data) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    return data[f] + (data[c] - data[f]) * (k - f)

def gini(array):
    array = np.array(array, dtype=np.float64)
    if array.size == 0:
        return 0.0
    array = array[array >= 0]
    if array.sum() == 0:
        return 0.0
    array = np.sort(array)
    n = array.size
    index = np.arange(1, n + 1)
    return (np.sum((2 * index - n - 1) * array)) / (n * np.sum(array))

# Parse all graph files
for path in graph_files:
    if path == "splitted_files/0_graph.json":
        continue
    with open(path, "r") as f:
        try:
            graphs = json.load(f)
        except Exception as e:
            print(f"Could not read {path}: {e}")
            continue

        for repo, repo_data in graphs.items():
            for dep, paths in repo_data.items():
                for path_list in paths:
                    for transition in path_list:
                        from_state = transition.get("from")
                        to_state = transition.get("to")
                        duration = transition.get("duration", 0)
                        commits = transition.get("commits", 0)

                        if from_state == to_state:
                            print(f"[WARNING] Skipping same-state transition in {repo} for dependency '{dep}': {from_state} → {to_state}")
                            continue

                        add_transition(from_state, to_state, duration, commits, dep)

# Aggregate statistics
summary = {}
total = 0
for trans, values in transition_data.items():
    durations = [v[0] for v in values if isinstance(v[0], (int, float))]
    commits_list = [v[1] for v in values if isinstance(v[1], (int, float))]
    unique_deps = dependency_sets[trans]
    num_deps = len(unique_deps)
    num_trans = len(values)

    # Distribution of transition counts per dependency (for Gini)
    transition_counts = list(dependency_counter[trans].values())
    gini_coeff = gini(transition_counts)
    total += num_trans

    summary[trans] = {
        "count": num_trans,
        "unique_dependencies": num_deps,
        "transition_density": round(num_trans / num_deps, 2) if num_deps else 0,
        "gini_coefficient": round(gini_coeff, 4),
        "duration_min": min(durations, default=0),
        "duration_max": max(durations, default=0),
        "duration_median": statistics.median(durations) if durations else 0,
        "duration_mean": statistics.mean(durations) if durations else 0,
        "duration_p25": percentile(durations, 25),
        "duration_p75": percentile(durations, 75),
        "commits_min": min(commits_list, default=0),
        "commits_max": max(commits_list, default=0),
        "commits_median": statistics.median(commits_list) if commits_list else 0,
        "commits_mean": statistics.mean(commits_list) if commits_list else 0,
        "commits_p25": percentile(commits_list, 25),
        "commits_p75": percentile(commits_list, 75),
        "top_dependencies": dependency_counter[trans].most_common(30)
    }

# Save results
with open("transition_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"✅ Summary saved to 'transition_summary.json', total: {total}")
