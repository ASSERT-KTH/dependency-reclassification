import os
import json
import csv
import numpy as np

# Load dataset
with open("data/33087_dataset.txt", "r", encoding="utf-8") as f:
    valid_repos = set(line.strip() for line in f if line.strip())

# Load history map
history_map = {}
with open("data/reports/history_map.txt", "r", encoding="utf-8") as f:
    for line in f:
        if "," in line:
            repo, index = line.strip().split(",")
            history_map[repo] = int(index)

# Define reclassification types
transition_types = [
    "void_core", "void_dev", "void_peer",
    "core_void", "core_dev", "core_peer",
    "dev_void", "dev_core", "dev_peer",
    "peer_void", "peer_core", "peer_dev"
]

results = []

for idx in range(1, 108):
    print("✅ Processing file index: ", idx)
    graph_path = f"splitted_files/{idx}_graph.json"
    analysis_path = f"splitted_files/{idx}_analysis.txt"

    if not os.path.exists(graph_path) or not os.path.exists(analysis_path):
        continue

    # Load graph
    with open(graph_path, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    # Load analysis
    repo_commits = {}
    with open(analysis_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                repo = entry.get("repo")
                if repo in valid_repos:
                    repo_commits.setdefault(repo, []).append(entry)
            except json.JSONDecodeError:
                continue

    # Process each repo
    for repo, deps in graph_data.items():
        print(repo)
        if repo not in valid_repos or repo not in history_map:
            continue

        # Get total commits
        total_commits = 0
        history_index = history_map[repo]
        history_file = f"commit_history/commits_batch_{history_index}.json"
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                try:
                    commit_data = json.load(f)
                    if repo in commit_data:
                        total_commits = len(commit_data[repo]["commits"])
                except:
                    pass

        # Count transitions
        transitions = {k: 0 for k in transition_types}
        for paths in deps.values():
            for path in paths:
                for step in path:
                    t_type = f"{step['from']}_{step['to']}"
                    if t_type in transitions:
                        transitions[t_type] += 1

        # Extract core dep stats
        if repo not in repo_commits:
            continue
        core_counts = [c.get("deps", 0) for c in repo_commits[repo] if "deps" in c]
        if not core_counts:
            continue
        last_core = repo_commits[repo][0]["deps"]
        first_core = repo_commits[repo][-1]["deps"]
        median_core = int(np.median(core_counts))

        row = {
            "repo": repo,
            "first_core_num": first_core,
            "last_core_num": last_core,
            "median_core_num": median_core,
            "total_commits": total_commits
        }
        row.update(transitions)
        results.append(row)

# Write to CSV
output_file = "data/reclassification/reclassification_statistics.csv"
fieldnames = ["repo", "first_core_num", "last_core_num", "median_core_num", "total_commits"] + transition_types

with open(output_file, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

print(f"✅ CSV written to: {output_file}")
