import os
import json
import math
from collections import defaultdict, Counter

# === CONFIGURATION ===
GRAPH_DIR = "splitted_files"
EXCLUDE_FILE = "0_graph.json"
DEP_TYPE = "core"  # 可选 "dev", "peer"
# ======================

# 数据结构：Repo -> Commit -> [List of Dicts]
# Dict: {'dep': name, 'duration': seconds, 'commits': count}
commit_removal_map = defaultdict(lambda: defaultdict(list))

def extract_path(transitions):
    raw_path = "->".join([t["from"] for t in transitions] + [transitions[-1]["to"]])
    if raw_path.startswith(f"void->{DEP_TYPE}->"):
        return "(void->)" + raw_path[len("void->"):]
    elif raw_path.startswith(f"{DEP_TYPE}->"):
        return "(void->)" + raw_path
    else:
        return raw_path

def calculate_stats(data_list):
    """
    计算列表的中位数, P25, P75
    """
    if not data_list:
        return 0, 0, 0
    
    n = len(data_list)
    sorted_data = sorted(data_list)
    
    def get_percentile(p):
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    median = get_percentile(0.5)
    p25 = get_percentile(0.25)
    p75 = get_percentile(0.75)
    
    return median, p25, p75

def get_stats_str(data_list, is_float=True):
    med, p25, p75 = calculate_stats(data_list)
    if is_float:
        return f"{med:.1f} [{p25:.1f}, {p75:.1f}]"
    else:
        return f"{med:.1f} [{p25:.1f}, {p75:.1f}]"

def process_file(filepath):
    try:
        with open(filepath, "r", encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return

    for repo, dep_map in data.items():
        for dep, paths in dep_map.items():
            for transitions in paths:
                if not transitions:
                    continue

                path_str = extract_path(transitions)
                # 只关注 One-time removal 模式
                if path_str != f"(void->){DEP_TYPE}->void":
                    continue

                # === 定位移除操作发生的 transition ===
                removal_transition = None
                
                if transitions[0]["from"] == "void" and len(transitions) > 1 and transitions[1]["to"] == "void":
                    # 模式: void -> core -> void (移除发生在第2个节点)
                    removal_transition = transitions[1]
                elif transitions[0]["from"] == DEP_TYPE:
                    # 模式: core -> void (移除发生在第1个节点)
                    removal_transition = transitions[0]
                else:
                    continue

                # 过滤掉 Monorepo Relocation
                if removal_transition.get("is_relocation") is True:
                    continue

                to_commit = removal_transition.get("to_commit")
                
                # 获取 duration 和 commits
                duration = removal_transition.get("duration", 0)
                commits = removal_transition.get("commits", 0)

                if to_commit:
                    commit_removal_map[repo][to_commit].append({
                        "dep": dep,
                        "duration": duration,
                        "commits": commits
                    })

# === 1. 处理文件 ===
print(f"🚀 开始分析 {DEP_TYPE} 依赖的 One-time Removal...")
files_processed = 0
for filename in sorted(os.listdir(GRAPH_DIR)):
    if not filename.endswith("_graph.json") or filename == EXCLUDE_FILE:
        continue
    process_file(os.path.join(GRAPH_DIR, filename))
    files_processed += 1
    print(f"\r已处理文件: {files_processed}", end="", flush=True)
print("\n")

# === 2. 聚合统计数据 ===

# 存储每个 Size 分类的详细数据用于计算 Median/IQR
# Keys: 1, 2, 3, 4, '5+'
stats_buckets = {
    1: {'durations': [], 'commits': []},
    2: {'durations': [], 'commits': []},
    3: {'durations': [], 'commits': []},
    4: {'durations': [], 'commits': []},
    '5+': {'durations': [], 'commits': []}
}

# 存储计数信息
group_counts = Counter()          # 发生次数 (Commits)
group_dep_volume = Counter()      # 涉及依赖总数 (Dependencies)
group_projects = defaultdict(set) # 涉及项目 (Unique Projects)

for repo, commits in commit_removal_map.items():
    for dep_list in commits.values():
        size = len(dep_list)
        
        # 确定统计桶的 Key
        bucket_key = size if size < 5 else '5+'
        
        # 基础计数
        group_counts[bucket_key] += 1
        group_dep_volume[bucket_key] += size
        group_projects[bucket_key].add(repo)
        
        # 收集详细数据
        for item in dep_list:
            # Duration: 秒 -> 天
            days = item['duration'] / 86400.0
            commits_num = item['commits']
            
            stats_buckets[bucket_key]['durations'].append(days)
            stats_buckets[bucket_key]['commits'].append(commits_num)

# === 3. 计算与输出 ===

total_removals = sum(group_dep_volume.values())
total_commits = sum(group_counts.values())
total_projects = len(commit_removal_map)

if total_commits == 0:
    print("⚠️ 未找到任何符合条件的移除操作。")
else:
    print(f"🔢 总计移除依赖 (Dependencies): {total_removals:,}")
    print(f"🔢 总计移除操作 (Commits):      {total_commits:,}")
    print(f"🔢 涉及项目总数 (Projects):      {total_projects:,}\n")

    # 表头格式
    # Size | Freq (Commits) | Vol (Deps) | Projs | Survival Days [Median, IQR] | Activity Commits [Median, IQR]
    row_fmt = "{:<6} | {:<16} | {:<14} | {:<12} | {:<28} | {:<28}"
    
    print("-" * 115)
    print(row_fmt.format(
        "Size", "Commits (Freq)", "Deps (Vol)", "Projs", 
        "Survival Days [P25, P75]", "Activity Commits [P25, P75]"
    ))
    print("-" * 115)

    sorted_keys = [1, 2, 3, 4, '5+']
    
    for key in sorted_keys:
        # 基础数据
        n_commits = group_counts[key]
        n_deps = group_dep_volume[key]
        n_projs = len(group_projects[key])
        
        # 比例
        commit_pct = (n_commits / total_commits) * 100
        
        # 统计数据
        durations = stats_buckets[key]['durations']
        commits_data = stats_buckets[key]['commits']
        
        dur_str = get_stats_str(durations)
        com_str = get_stats_str(commits_data)
        
        # 格式化输出
        col_commit = f"{n_commits:,} ({commit_pct:.1f}%)"
        col_deps = f"{n_deps:,}"
        col_projs = f"{n_projs:,}"
        
        print(row_fmt.format(
            str(key), col_commit, col_deps, col_projs, dur_str, com_str
        ))

    print("-" * 115)
    
    # 简单的文本分析
    single_med_days, _, _ = calculate_stats(stats_buckets[1]['durations'])
    batch_med_days, _, _ = calculate_stats(stats_buckets['5+']['durations'])
    
    print("\n💡 Quick Insight:")
    if batch_med_days < single_med_days:
        print(f"   批量移除 (Size 5+) 的依赖通常存活时间更短 (Median: {batch_med_days:.1f} days) ")
        print(f"   相比于单次移除 (Size 1) 的依赖 (Median: {single_med_days:.1f} days)。")
        print("   这可能暗示批量清理往往针对的是试错性引入或短期项目重构。")
    elif batch_med_days > single_med_days:
        print(f"   批量移除 (Size 5+) 的依赖存活时间更长 (Median: {batch_med_days:.1f} days)。")
        print("   这可能暗示这些是大规模的架构升级，淘汰了积攒已久的旧依赖。")
    else:
        print("   单次移除与批量移除的依赖存活时间差异不明显。")