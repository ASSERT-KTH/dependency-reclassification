import json
import csv
from glob import glob
from collections import defaultdict, Counter

# Directory containing JSON graph files
graph_files = sorted(glob("splitted_files/*_graph.json"))

# Mapping of path signature to dependency count and set of repos
path_signature_counter = defaultdict(Counter)
path_signature_repos = defaultdict(set)

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
                    if not isinstance(path_list, list):
                        continue
                    signature = tuple(f"{t['from']}->{t['to']}" for t in path_list)
                    path_signature_counter[signature][dep] += 1
                    path_signature_repos[signature].add(repo)
                    if len(path_list) > 10:
                        print("⚠️ Long transition path:", repo, dep)

# Prepare CSV rows
csv_rows = []
for signature, dep_counter in path_signature_counter.items():
    path_id = signature[0].split("->")[0] + "->" + "->".join(t.split("->")[1] for t in signature)
    total_count = sum(dep_counter.values())
    repo_count = len(path_signature_repos[signature])
    if repo_count == 0:
        continue

    row = {
        "path_id": path_id,
        "total_count": total_count,
        "repo_count": repo_count
    }

    # Top 20 by absolute count
    top_deps = dep_counter.most_common(20)
    for i, (dep, count) in enumerate(top_deps, start=1):
        row[f"top{i}_dep"] = dep
        row[f"top{i}_dep_count"] = count

    # Top 20 by ratio (count / repo_count)
    ratio_list = [(dep, count / repo_count) for dep, count in dep_counter.items()]
    ratio_list.sort(key=lambda x: -x[1])
    for i, (dep, ratio) in enumerate(ratio_list[:20], start=1):
        row[f"top{i}_ratio_dep"] = dep
        row[f"top{i}_ratio"] = round(ratio, 3)

    csv_rows.append(row)

# Sort rows by total_count descending
csv_rows.sort(key=lambda x: -x["total_count"])

# Define CSV columns
fieldnames = ["path_id", "total_count", "repo_count"]
for i in range(1, 21):
    fieldnames.append(f"top{i}_dep")
    fieldnames.append(f"top{i}_dep_count")
for i in range(1, 21):
    fieldnames.append(f"top{i}_ratio_dep")
    fieldnames.append(f"top{i}_ratio")

# Write CSV
csv_file = "data/reports/path_summary_with_ratios.csv"
with open(csv_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

print(f"✅ Enhanced path summary saved to '{csv_file}'")
