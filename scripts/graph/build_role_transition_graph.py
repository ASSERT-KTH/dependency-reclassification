import sys
import json
from datetime import datetime, timezone
from collections import defaultdict

def parse_time(time_str):
    formats = ["%Y-%m-%d %H:%M:%S %z", "%Y %b %d %H:%M:%S"]
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Time format not recognized: {time_str}")

def load_commit_history(repo_name, history_map_path="data/reports/history_map.txt", history_folder="commit_history"):
    with open(history_map_path, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 2 and parts[0] == repo_name:
                index = parts[1]
                break
        else:
            raise ValueError(f"No history index found for repo: {repo_name}")

    history_path = f"{history_folder}/commits_batch_{index}.json"
    with open(history_path, 'r') as f:
        batch = json.load(f)

    repo_data = batch.get(repo_name)
    if not repo_data:
        raise ValueError(f"Repo {repo_name} not found in commits_batch_{index}.json")

    commit_times = {}
    for commit in repo_data['commits']:
        sha_short = commit['sha'][:7]
        commit_times[sha_short] = parse_time(commit['time'])

    seen_times = set()
    filtered_commits = []
    for sha, t in commit_times.items():
        ts = t.timestamp()
        if ts not in seen_times:
            seen_times.add(ts)
            filtered_commits.append((sha, t))

    sorted_commits = sorted(filtered_commits, key=lambda item: item[1])
    ordered_shas = [sha for sha, _ in sorted_commits]
    filtered_commit_times = dict(sorted_commits)
    return repo_data['init_time'], filtered_commit_times, ordered_shas

def extract_dep_names(dep_list):
    deps = []
    for item in dep_list:
        if isinstance(item, dict):
            deps.extend(item.keys())
        elif isinstance(item, list):
            # Flatten nested lists
            deps.extend(extract_dep_names(item))
        else:
            deps.append(item)
    return deps


def format_duration(delta):
    total_seconds = int(delta.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    total_days, hours = divmod(hours, 24)
    years, days = divmod(total_days, 365)

    parts = []
    if years: parts.append(f"{years} years")
    if days: parts.append(f"{days} days")
    if hours: parts.append(f"{hours} hours")
    if minutes: parts.append(f"{minutes} minutes")
    if seconds: parts.append(f"{seconds} seconds")
    return ", ".join(parts) if parts else "0 seconds"


def generate_dependency_paths(diff_txt_path, history_map_path):
    all_paths = {}

    with open(diff_txt_path, 'r') as f:
        lines = [json.loads(line.strip()) for line in f]

    grouped = defaultdict(list)
    for entry in lines:
        grouped[entry['repo']].append(entry)

    commit_history_cache = {}

    for repo_name, commits in grouped.items():
        try:
            if repo_name not in commit_history_cache:
                commit_history_cache[repo_name] = load_commit_history(repo_name, history_map_path)
        except ValueError as e:
            print(f"Skipping {repo_name}: {e}")
            continue

        init_time_str, commit_times, ordered_shas = commit_history_cache[repo_name]
        init_time = parse_time(init_time_str).astimezone(timezone.utc)

        commits = sorted(commits, key=lambda c: ordered_shas.index(c['commit'][:7]) if c['commit'][:7] in ordered_shas else float('inf'))

        paths = defaultdict(list)

        for commit in commits:
            sha_short = commit['commit'][:7]
            if sha_short not in commit_times:
                continue
            time = commit_times[sha_short].astimezone(timezone.utc)
            diff = commit['diff']

            changes = {
                "core": {
                    "delete": set(diff.get("delete", [])),
                    "insert": set(extract_dep_names(diff.get("insert", [])))
                },
                "dev": {
                    "delete": set(diff.get("delete_dev", [])),
                    "insert": set(extract_dep_names(diff.get("insert_dev", [])))
                },
                "peer": {
                    "delete": set(diff.get("delete_peer", [])),
                    "insert": set(extract_dep_names(diff.get("insert_peer", [])))
                }
            }

            transitions = []
            handled = set()
            categories = ["core", "dev", "peer"]

            for from_cat in categories:
                for to_cat in categories:
                    if from_cat == to_cat:
                        continue
                    moved = changes[from_cat]["delete"].intersection(changes[to_cat]["insert"])
                    for dep in moved:
                        transitions.append((dep, from_cat, to_cat))
                        handled.add(dep)

            inserted_all = set().union(*(changes[cat]["insert"] for cat in categories))

            # if sha_short == "c6a1b2f":
            #     print(transitions)
            for cat in categories:
                for dep in changes[cat]["delete"]:
                    if dep not in handled and dep not in inserted_all:
                        transitions.append((dep, cat, "void"))
                        handled.add(dep)

                for dep in changes[cat]["insert"]:
                    if dep not in handled:
                        transitions.append((dep, "void", cat))
                        handled.add(dep)

            for dep, from_state, to_state in transitions:
                matched = False
                for path in paths[dep]:
                    if path and path[-1]['to'] == from_state:
                        last_time = datetime.fromtimestamp(path[-1]['to_time'], tz=timezone.utc)
                        duration = (time - last_time).total_seconds()
                        commit_count = ordered_shas.index(sha_short) - ordered_shas.index(path[-1]['to_commit'])
                        path.append({
                            "from": from_state,
                            "to": to_state,
                            "from_time": path[-1]['to_time'],
                            "to_time": time.timestamp(),
                            "duration": duration,
                            "duration_str": format_duration(time - last_time),
                            "commits": commit_count,
                            "from_commit": path[-1]['to_commit'],
                            "to_commit": sha_short,
                            "from_time_str": datetime.fromtimestamp(path[-1]['to_time'], tz=timezone.utc).strftime("%Y %b %d %H:%M:%S"),
                            "to_time_str": time.strftime("%Y %b %d %H:%M:%S")
                        })
                        matched = True
                        break

                if not matched:
                    duration = (time - init_time).total_seconds()
                    commit_count = ordered_shas.index(sha_short) + 1
                    paths[dep].append([
                        {
                            "from": from_state,
                            "to": to_state,
                            "from_time": init_time.timestamp(),
                            "to_time": time.timestamp(),
                            "duration": duration,
                            "duration_str": format_duration(time - init_time),
                            "commits": commit_count,
                            "from_commit": "init",
                            "to_commit": sha_short,
                            "from_time_str": init_time.strftime("%Y %b %d %H:%M:%S"),
                            "to_time_str": time.strftime("%Y %b %d %H:%M:%S")
                        }
                    ])

        all_paths[repo_name] = paths

    return all_paths

if __name__ == "__main__":
    index = sys.argv[1]
    diff_txt_path = f"splitted_files/{index}_analysis.txt"
    print(f"processing {diff_txt_path}")
    history_map_path = "data/reports/history_map.txt"
    dependency_graph = generate_dependency_paths(diff_txt_path, history_map_path)

    with open(f"splitted_files/{index}_graph.json", "w") as f:
        json.dump(dependency_graph, f, indent=2)