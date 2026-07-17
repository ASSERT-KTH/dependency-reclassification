import json
import os
import statistics
from collections import defaultdict

# ================= 配置区域 =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)  
TARGET_ROLE = 'core'        
MIN_BATCH_SIZE = 2          
OUTPUT_FILE = 'data/core/core_batch_sources_by_size.json'
# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def get_full_trajectory(segments):
    all_events = []
    for seg in segments:
        all_events.extend(seg)
    all_events.sort(key=lambda x: float(x.get('from_time', 0)))
    return all_events

def analyze_lifecycle(dep_name, segments):
    traj = get_full_trajectory(segments)
    if not traj: return None

    first_event = traj[0]
    last_event = traj[-1]
    
    if first_event.get('from') == 'void':
        born_state = first_event.get('to')
        birth_commit = first_event.get('to_commit')
        birth_time = first_event.get('to_time', 0)
    else:
        born_state = first_event.get('from')
        birth_commit = first_event.get('from_commit')
        birth_time = first_event.get('from_time', 0)

    if born_state != TARGET_ROLE: return None
    if last_event.get('to') != 'void' or last_event.get('is_relocation') is True: return None

    void_count = sum(1 for e in traj if e.get('to') == 'void')
    if void_count > 1: return None 

    death_commit = last_event.get('to_commit')
    
    return {
        'dep': dep_name,
        'birth_commit': birth_commit,
        'birth_time': birth_time,
        'death_commit': death_commit
    }

def main():
    print(f"🚀 Starting Batch Source Analysis by Size...")

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
                    batch_map[repo][info['death_commit']].append(info)

        print(f"\rProcessed {files_processed} files...", end="", flush=True)
    print("\n")

    # === 分组统计 ===
    # buckets[size_key] = { 'total': 0, 'multi': 0, 'windows': [] }
    buckets = defaultdict(lambda: {'total': 0, 'multi': 0, 'windows': []})
    
    detailed_results = []

    for repo, commits in batch_map.items():
        for death_commit, dep_list in commits.items():
            size = len(dep_list)
            if size < MIN_BATCH_SIZE: continue
            
            # 定义 Bucket Key: 2, 3, 4, 5+
            size_key = str(size) if size < 5 else "5+"
            
            origins = set(d['birth_commit'] for d in dep_list)
            is_accumulated = len(origins) > 1
            
            buckets[size_key]['total'] += 1
            if is_accumulated:
                buckets[size_key]['multi'] += 1
                times = [d['birth_time'] for d in dep_list if d['birth_time'] > 0]
                if len(times) > 1:
                    window = (max(times) - min(times)) / 86400.0
                    buckets[size_key]['windows'].append(window)

            detailed_results.append({
                'repo': repo,
                'death_commit': death_commit,
                'size': size,
                'is_accumulated': is_accumulated,
                'origin_count': len(origins)
            })

    # === 输出可视化报告 ===
    print("=" * 90)
    print(f"{'Batch Size':<12} | {'Total Ops':<12} | {'Multi-Origin %':<18} | {'Median Window (Days)':<22}")
    print("-" * 90)
    
    sorted_keys = sorted([k for k in buckets.keys() if k != "5+"], key=int) + (["5+"] if "5+" in buckets else [])
    
    for key in sorted_keys:
        data = buckets[key]
        multi_pct = (data['multi'] / data['total'] * 100) if data['total'] > 0 else 0
        med_win = statistics.median(data['windows']) if data['windows'] else 0
        
        print(f"{key:<12} | {data['total']:<12,} | {multi_pct:<17.1f}% | {med_win:<22.1f}")
    
    print("=" * 90)
    print(f"Notes: 'Multi-Origin %' represents batches where dependencies were added in DIFFERENT commits.")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(detailed_results, f, indent=2)
    print(f"\n📁 Detailed grouping saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()