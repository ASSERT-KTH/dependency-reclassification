import os
import json
import csv
from collections import defaultdict

# === CONFIGURATION ===
GRAPH_DIR = "splitted_files"
EXCLUDE_FILE = "0_graph.json"
OUTPUT_CSV = "data/reports/pattern_summary.csv"
# ======================

# Define pattern rules
patterns = {
    "A-A": lambda p: p[0] == "core" and p[-1] == "void" and len(p) == 2,
    "A-B": lambda p: p[0] == "dev" and p[-1] == "void" and len(p) == 2,
    "A-C": lambda p: p[0] == "peer" and p[-1] == "void" and len(p) == 2,
    "B-A": lambda p: p[0] == "core" and p[-1] == "void" and len(p) > 2,
    "B-B": lambda p: p[0] == "dev" and p[-1] == "void" and len(p) > 2,
    "B-C": lambda p: p[0] == "peer" and p[-1] == "void" and len(p) > 2,
    "C-A": lambda p: (
        len(p) >= 3 and
        p[0] == "core" and
        p[-1] == "core" and
        all(x in {"core", "void"} for x in p) and
        all(p[i] != p[i+1] for i in range(len(p) - 1))  # alternating
    ),
    "C-B": lambda p: (
        len(p) >= 3 and
        p[0] == "dev" and
        p[-1] == "dev" and
        all(x in {"dev", "void"} for x in p) and
        all(p[i] != p[i+1] for i in range(len(p) - 1))  # alternating
    ),
    "C-C": lambda p: (
        len(p) >= 3 and
        p[0] == "peer" and
        p[-1] == "peer" and
        all(x in {"peer", "void"} for x in p) and
        all(p[i] != p[i+1] for i in range(len(p) - 1))  # alternating
    ),

    "D-A": lambda p: p[0] == "core" and p[-1] == "core" and any(x in {"dev", "peer"} for x in p[1:-1]),
    "D-B": lambda p: p[0] == "dev" and p[-1] == "dev" and any(x in {"core", "peer"} for x in p[1:-1]),
    "D-C": lambda p: p[0] == "peer" and p[-1] == "peer" and any(x in {"core", "dev"} for x in p[1:-1]),
    "E":   lambda p: p[0] == "core" and p[-1] == "dev",
    "F":   lambda p: p[0] == "core" and p[-1] == "peer",
    "G":   lambda p: p[0] == "dev" and p[-1] == "core",
    "H":   lambda p: p[0] == "dev" and p[-1] == "peer",
    "I":   lambda p: p[0] == "peer" and p[-1] == "core",
    "J":   lambda p: p[0] == "peer" and p[-1] == "dev",
}

pattern_stats = {k: {"count": 0, "repos": set()} for k in patterns}

def extract_path(transitions):
    if not transitions:
        return []
    return [t["from"] for t in transitions] + [transitions[-1]["to"]]

def classify_path(path):
    for pattern_name, rule in patterns.items():
        if rule(path):
            return pattern_name
    return None

def process_file(filepath):
    with open(filepath, "r") as f:
        data = json.load(f)

    for repo, deps in data.items():
        for dep, transition_groups in deps.items():
            for transitions in transition_groups:
                path = extract_path(transitions)
                if path and path[0] == "void":
                    path = path[1:]  # Normalize (void->)

                if not path:
                    continue

                pattern = classify_path(path)
                if pattern:
                    pattern_stats[pattern]["count"] += 1
                    pattern_stats[pattern]["repos"].add(repo)

def write_csv():
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pattern", "cases", "involved_repos"])
        writer.writeheader()
        for pattern, stats in sorted(pattern_stats.items()):
            writer.writerow({
                "pattern": pattern,
                "cases": stats["count"],
                "involved_repos": len(stats["repos"])
            })

def main():
    for fname in sorted(os.listdir(GRAPH_DIR)):
        if not fname.endswith("_graph.json") or fname == EXCLUDE_FILE:
            continue
        process_file(os.path.join(GRAPH_DIR, fname))

    write_csv()
    print(f"✅ Pattern summary saved to: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
