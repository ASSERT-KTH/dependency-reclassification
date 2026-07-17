import json
import os
import math
from collections import defaultdict

# ================= 配置区域 =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)

# 🎯 设置分析角色 (core/dev/peer)
ROLE = 'core'

# 🎯 阈值设置：三个月（90天）
THRESHOLD_DAYS = 90

# 🎯 目标路径：必须包含从 role 到 void 再回到 role 的循环
TARGET_PATHS = [
    [ROLE, 'void', ROLE],
    [ROLE, 'void', ROLE, 'void'],
    [ROLE, 'void', ROLE, 'void', ROLE]
]
# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def calculate_quartiles(data):
    if not data: return 0, 0, 0
    data.sort()
    n = len(data)
    def get_val(idx_float):
        lower = int(math.floor(idx_float))
        upper = int(math.ceil(idx_float))
        if lower == upper: return data[lower]
        return data[lower] * (1 - (idx_float - lower)) + data[upper] * (idx_float - lower)
    return get_val((n - 1) * 0.5), get_val((n - 1) * 0.25), get_val((n - 1) * 0.75)

def get_stats_str(data_list):
    if not data_list: return "N/A"
    med, q1, q3 = calculate_quartiles(data_list)
    return f"{med:.2f} [{q1:.2f}, {q3:.2f}]"

def get_trajectory_from_segment(segment):
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return []
    first_from = segment[0].get('from')
    if first_from and first_from != 'void':
        trajectory.append({'state': first_from, 'duration': 0, 'commits': 0, 'is_artificial': True})
    for event in segment:
        trajectory.append({
            'state': event.get('to'), 
            'duration': float(event.get('duration', 0.0)),
            'commits': int(event.get('commits', 0)),
            'is_artificial': False,
            'is_relocation': event.get('is_relocation', False)
        })
    return trajectory

def extract_clean_path_and_events(traj):
    if not traj: return [], []
    path = [traj[0]['state']]
    step_events = []
    current_role = traj[0]['state']
    for event in traj:
        if event.get('is_artificial') or event.get('is_relocation'): continue
        if event['state'] != current_role:
            path.append(event['state'])
            step_events.append(event)
            current_role = event['state']
    return path, step_events

def main():
    print(f"🚀 Analyzing Pairwise Reversion: [ {ROLE.upper()} -> VOID ] vs [ VOID -> {ROLE.upper()} ]")
    
    pair_data = {
        'removal_days': [],    
        'reversion_days': [],   
        'removal_commits': [],
        'reversion_commits': []
    }
    
    total_matches = 0
    long_term_count = 0  # 统计超过 3 个月的修复数量

    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if data is None: continue
        
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                for segment in segments:
                    traj = get_trajectory_from_segment(segment)
                    actual_path, events = extract_clean_path_and_events(traj)
                    
                    if actual_path in TARGET_PATHS:
                        total_matches += 1
                        for idx in range(len(actual_path) - 1):
                            if actual_path[idx] == 'void' and actual_path[idx+1] == ROLE:
                                rev_event = events[idx]
                                
                                if idx > 0 and actual_path[idx-1] == ROLE:
                                    rem_event = events[idx-1]
                                    
                                    rem_days = rem_event['duration'] / 86400.0
                                    rev_days = rev_event['duration'] / 86400.0
                                    
                                    pair_data['removal_days'].append(rem_days)
                                    pair_data['reversion_days'].append(rev_days)
                                    pair_data['removal_commits'].append(rem_event['commits'])
                                    pair_data['reversion_commits'].append(rev_event['commits'])
                                    
                                    # 检查是否超过三个月
                                    if rev_days > THRESHOLD_DAYS:
                                        long_term_count += 1

        print(f"\rProcessed {i}/107 files...", end="", flush=True)

    print("\n\n" + "="*95)
    print(f"📊 PAIRWISE ANALYSIS REPORT ({ROLE.upper()})")
    print("="*95)
    num_pairs = len(pair_data['removal_days'])
    print(f"Total Matched Paths: {total_matches}")
    print(f"Total Valid Pairs Found: {num_pairs}")
    print("-" * 95)
    
    if num_pairs > 0:
        print(f"{'METRIC':<20} | {'REMOVAL (Prior Life)':<32} | {'REVERSION (Absence)':<32}")
        print("-" * 95)
        print(f"{'Time (Days)':<20} | {get_stats_str(pair_data['removal_days']):<32} | {get_stats_str(pair_data['reversion_days']):<32}")
        print(f"{'Commits':<20} | {get_stats_str(pair_data['removal_commits']):<32} | {get_stats_str(pair_data['reversion_commits']):<32}")
        
        print("-" * 95)
        # 核心统计：> 3个月的修复比例
        long_term_pct = (long_term_count / num_pairs) * 100
        print(f"🚩 Reversions after > {THRESHOLD_DAYS} days: {long_term_count} ({long_term_pct:.2f}% of all reversions)")
        
        avg_rem = sum(pair_data['removal_days']) / num_pairs
        avg_rev = sum(pair_data['reversion_days']) / num_pairs
        print(f"💡 On average, dependencies were 'absent' for {avg_rev/avg_rem:.2%} of their prior lifespan.")
    else:
        print("⚠️ No valid pairs found for comparison.")
    print("="*95)

if __name__ == "__main__":
    main()