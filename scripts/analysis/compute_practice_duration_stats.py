import json
import os
import math
from collections import defaultdict

# ================= 配置 (Configuration) =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)
OUTPUT_JSON = 'data/reports/practice_stats_final.json'
# ========================================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def get_trajectory_from_segment(segment):
    """提取状态轨迹，忽略 relocation"""
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return []
    
    first_from = segment[0].get('from')
    if first_from and first_from != 'void':
        trajectory.append({'state': first_from, 'duration': 0})
    
    current_state = first_from if first_from else 'void'
    for event in segment:
        if event.get('is_relocation'): return "IGNORE_RELOCATION"
        to_state = event.get('to')
        if to_state != current_state:
            trajectory.append({'state': to_state, 'duration': float(event.get('duration', 0))})
            current_state = to_state
    return trajectory

def get_percentile(data, p):
    """手动实现百分位数计算"""
    if not data: return 0.0
    s_data = sorted(data)
    idx = (len(s_data) - 1) * p
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high: return s_data[low]
    return s_data[low] * (high - idx) + s_data[high] * (idx - low)

def collect_and_save_stats():
    print(f"🚀 开始分析 {BASE_DIR} 中的数据...")
    raw_storage = {} 
    all_practice_storage = defaultdict(list)

    for i in FILE_RANGE:
        path = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(path)
        if not data: continue
        
        for repo in data.values():
            for segments in repo.values():
                for seg in segments:
                    traj = get_trajectory_from_segment(seg)
                    if traj == "IGNORE_RELOCATION" or not traj: continue
                    
                    born = traj[0]['state']
                    if born == 'void' and len(traj) > 1:
                        born = traj[1]['state']
                        traj = traj[1:]
                    if born not in ['core', 'dev', 'peer']: continue
                    
                    states = [t['state'] for t in traj]
                    durations = [t['duration'] / 86400.0 for t in traj] # 秒转天
                    role_key = born.capitalize()

                    # 提取角色路径
                    active_roles = [s for s in states if s != 'void']
                    unique_seq = [active_roles[0]] if active_roles else []
                    for r in active_roles[1:]:
                        if r != unique_seq[-1]: unique_seq.append(r)

                    def add_entry(practice_name, data_point):
                        raw_storage.setdefault((practice_name, role_key), []).append(data_point)
                        all_practice_storage[practice_name].append(data_point)

                    # --- 分类判定逻辑 ---
                    # 1. Role oscillation
                    if len(unique_seq) >= 3:
                        if len(durations) >= 3:
                            add_entry('Role oscillation', {'s1': durations[1], 'tot': durations[1] + durations[2]})
                    # 2. Removal reversion
                    elif len(states) >= 3 and states[1] == 'void' and states[2] == states[0]:
                        add_entry('Removal reversion', {'s1': durations[1], 'tot': durations[1] + durations[2]})
                    # 3. One-time removal
                    elif len(states) == 2 and states[1] == 'void':
                        add_entry('One-time removal', durations[1])
                    # 4. Multi-step removal
                    elif len(states) >= 3 and states[-1] == 'void' and states[0] != 'void' and states[1] != 'void':
                        add_entry('Multi-step removal', {'s1': durations[1], 'tot': sum(durations[1:])})
                    # 5. Reclassify
                    elif states[-1] in ['core', 'dev', 'peer'] and states[-1] != born:
                        add_entry(f'Reclassify to {states[-1].capitalize()}', sum(durations[1:]))

        print(f"\r处理进度: {i}/107", end="", flush=True)

    # --- 数据汇总处理 ---
    final_output_list = []
    global_all_pool = [] # 存储全量不分类数据的池子

    def process_stats(vals, label_role, label_practice):
        if not vals: return
        is_multi = isinstance(vals[0], dict)
        tots = [v['tot'] for v in vals] if is_multi else vals
        s1s = [v['s1'] for v in vals] if is_multi else vals
        
        # 将数据加入大统一池子
        if label_role != "Total":
            global_all_pool.extend(tots)

        final_output_list.append({
            'Role': label_role, 'Practice': label_practice, 
            'count': len(tots),
            'total_med': round(get_percentile(tots, 0.5), 2),
            'q1_d': round(get_percentile(tots, 0.25), 2),
            'q3_d': round(get_percentile(tots, 0.75), 2),
            '7d_rate': round(len([d for d in tots if d <= 7]) / len(tots) * 100, 2)
        })

    # 生成细分和按类型汇总数据
    for (practice, role), vals in raw_storage.items(): process_stats(vals, role, practice)
    for practice, vals in all_practice_storage.items(): process_stats(vals, "Total", practice)

    # --- 控制台打印与全局总结 ---
    print("\n\n" + "="*85)
    print(f"{'Practice Type (Total Role)':<28} | {'Count':<8} | {'Med (Day)':<10} | {'IQR (Q1-Q3)':<15} | {'<=7d %'}")
    print("-" * 85)
    
    # 只打印 Role == "Total" 的部分到控制台
    summaries = [s for s in final_output_list if s['Role'] == "Total"]
    summaries.sort(key=lambda x: x['count'], reverse=True)
    for s in summaries:
        iqr = f"{s['q1_d']}-{s['q3_d']}"
        print(f"{s['Practice']:<28} | {s['count']:<8} | {s['total_med']:<10} | {iqr:<15} | {s['7d_rate']}%")

    print("-" * 85)
    
    # 打印终极汇总数据 (不分任何类)
    if global_all_pool:
        g_med = round(get_percentile(global_all_pool, 0.5), 2)
        g_q1 = round(get_percentile(global_all_pool, 0.25), 2)
        g_q3 = round(get_percentile(global_all_pool, 0.75), 2)
        g_rate = round(len([d for d in global_all_pool if d <= 7]) / len(global_all_pool) * 100, 2)
        
        print(f"{'OVERALL GLOBAL PRACTICES':<28} | {len(global_all_pool):<8} | {g_med:<10} | {g_q1}-{g_q3:<14} | {g_rate}%")
    
    print("="*85)

    with open(OUTPUT_JSON, 'w') as f:
        json.dump(final_output_list, f, indent=4)
    print(f"\n✅ 详细 JSON 已保存至: {OUTPUT_JSON}")

if __name__ == "__main__":
    collect_and_save_stats()