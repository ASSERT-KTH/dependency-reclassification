import json
import os
import statistics
from collections import defaultdict

# ================= 配置区域 =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)  # 1 to 107
TARGET_ROLE = 'core'        # 关注 Core 依赖 (你可以稍后改为 dev)
MIN_BATCH_SIZE = 2          # 批量阈值
OUTPUT_FILE = 'data/core/core_batch_sources_fixed.json'
# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def get_full_trajectory(segments):
    """
    合并 segments 并按时间排序
    """
    all_events = []
    for seg in segments:
        all_events.extend(seg)
    all_events.sort(key=lambda x: float(x.get('from_time', 0)))
    return all_events

def analyze_lifecycle(dep_name, segments):
    """
    准确提取出生和死亡信息
    """
    traj = get_full_trajectory(segments)
    if not traj:
        return None

    first_event = traj[0]
    last_event = traj[-1]

    # === 1. 确定出生 Commit (Birth Commit) ===
    # 逻辑修正：
    # 情况 A: void -> core (Add)。出生点是 'to_commit'。
    # 情况 B: core -> ... (Inherited)。出生点是 'from_commit' (通常是 init)。
    
    born_state = first_event.get('to')
    birth_commit = None
    birth_time = 0

    if first_event.get('from') == 'void':
        # 它是被添加进来的。无论 from_commit 是 init 还是别的，
        # 真正执行添加操作的是 to_commit
        born_state = first_event.get('to')
        birth_commit = first_event.get('to_commit')
        birth_time = first_event.get('to_time', 0)
    else:
        # 它一开始就是存在的 (继承自 init 或上一个文件片段)
        born_state = first_event.get('from')
        birth_commit = first_event.get('from_commit')
        birth_time = first_event.get('from_time', 0)

    # 过滤：只关注 Born Core
    if born_state != TARGET_ROLE:
        return None

    # === 2. 验证 One-time Removal ===
    # A. 必须死 (to: void)
    if last_event.get('to') != 'void':
        return None
    
    # B. 死因不能是 Relocation
    if last_event.get('is_relocation') is True:
        return None

    # C. 中间不能死 (No Resurrection)
    # 统计有多少次变成了 void
    void_count = sum(1 for e in traj if e.get('to') == 'void')
    if void_count > 1:
        return None # 中间死过，说明是反复横跳，不是单纯的 One-time

    # === 3. 提取死亡 Commit ===
    death_commit = last_event.get('to_commit')
    
    return {
        'dep': dep_name,
        'birth_commit': birth_commit,
        'birth_time': birth_time,
        'death_commit': death_commit
    }

def main():
    print(f"🚀 Starting FIXED Analysis for '{TARGET_ROLE}' Batch Removals...")
    print(f"   Logic Fix: Birth Commit is now correctly identified as 'to_commit' for additions.")

    # batch_map[repo][death_commit] = [ list of dep_info ]
    batch_map = defaultdict(lambda: defaultdict(list))

    files_processed = 0

    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if data is None: continue
        files_processed += 1
        
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                
                info = analyze_lifecycle(dep_name, segments)
                
                if info:
                    repo_name = repo
                    death_commit = info['death_commit']
                    
                    if death_commit:
                        batch_map[repo_name][death_commit].append(info)

        print(f"\rProcessed {files_processed} files...", end="", flush=True)
    print("\n")

    # === 统计分析 ===
    
    total_batches = 0
    multi_origin_batches = 0
    single_origin_batches = 0
    
    accumulation_windows = []
    
    detailed_results = []

    for repo, commits in batch_map.items():
        for death_commit, dep_list in commits.items():
            batch_size = len(dep_list)
            
            if batch_size < MIN_BATCH_SIZE:
                continue
            
            total_batches += 1
            
            # 核心：统计有多少个不同的 Birth Commit
            origins = set(d['birth_commit'] for d in dep_list)
            unique_origins = len(origins)
            
            is_accumulated = unique_origins > 1
            
            if is_accumulated:
                multi_origin_batches += 1
                
                # 计算积累窗口
                times = [d['birth_time'] for d in dep_list if d['birth_time'] > 0]
                if times and len(times) > 1:
                    window = (max(times) - min(times)) / 86400.0
                    accumulation_windows.append(window)
            else:
                single_origin_batches += 1

            # 记录典型案例 (Size >= 5)
            if batch_size >= 5:
                detailed_results.append({
                    'repo': repo,
                    'death_commit': death_commit,
                    'batch_size': batch_size,
                    'is_accumulated': is_accumulated,
                    'unique_origins': unique_origins,
                    'birth_commits_sample': list(origins)[:5],
                    'dependencies_sample': [d['dep'] for d in dep_list[:5]]
                })

    # === 输出报告 ===
    print("=" * 70)
    print(f"📊 Corrected Report: {TARGET_ROLE.upper()} Batch Source Analysis")
    print("=" * 70)
    
    print(f"Total Batches (Size >= {MIN_BATCH_SIZE}): {total_batches:,}")
    print("-" * 70)
    
    if total_batches > 0:
        multi_pct = (multi_origin_batches / total_batches) * 100
        single_pct = (single_origin_batches / total_batches) * 100
        
        print(f"✅ Multi-Origin Batches (Accumulated Debt): {multi_origin_batches:,} ({multi_pct:.1f}%)")
        print(f"   -> Dependencies came from DIFFERENT commits.")
        
        print(f"\n🚫 Single-Origin Batches (Likely Revert):   {single_origin_batches:,} ({single_pct:.1f}%)")
        print(f"   -> Dependencies came from the SAME commit.")
        
        print("-" * 70)
        if accumulation_windows:
            med_win = statistics.median(accumulation_windows)
            max_win = max(accumulation_windows)
            print(f"⏳ Accumulation Window (Multi-Origin):")
            print(f"   Median: {med_win:.1f} days")
            print(f"   Max:    {max_win:.1f} days")
    
    # 保存结果
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(detailed_results, f, indent=2, ensure_ascii=False)
    print(f"\n📁 Saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()