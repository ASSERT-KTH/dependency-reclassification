import json
import os
from collections import defaultdict, Counter

# ================= 配置区域 =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)
TARGET_PATH_ARRAY = ['core', 'void', 'core'] 
# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return None

def get_trajectory(segment):
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return [], None
    
    born_role = segment[0].get('from')
    if born_role and born_role != 'void':
        trajectory.append({'state': born_role, 'is_artificial': True})
    
    for event in segment:
        trajectory.append({
            'state': event.get('to'),
            'to_commit': event.get('to_commit'),
            'is_relocation': event.get('is_relocation', False),
            'is_artificial': False
        })
    return trajectory, born_role

def extract_steps(traj):
    path, events = [traj[0]['state']], []
    curr = traj[0]['state']
    for e in traj:
        if e.get('is_artificial') or e.get('is_relocation'): continue
        if e['state'] != curr:
            path.append(e['state'])
            events.append(e)
            curr = e['state']
    return path, events

def main():
    delete_batches = defaultdict(set)
    reversal_info = defaultdict(set)

    print("🚀 开始深度扫描：正在修复角色匹配逻辑...")

    for i in FILE_RANGE:
        data = load_json(os.path.join(BASE_DIR, f"{i}_graph.json"))
        if not data: continue
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                for seg in segments:
                    traj, born_role = get_trajectory(seg)
                    path, events = extract_steps(traj)
                    
                    # ✨ 修改点：动态构建匹配目标
                    # 只有当路径符合 [角色, void, 角色] 且前后角色一致时才计入
                    if len(path) == 3 and path[1] == 'void' and path[0] == path[2] and path[0] == born_role:
                        del_commit = events[0]['to_commit']
                        rev_commit = events[1]['to_commit']
                        
                        delete_batches[(repo, del_commit)].add((dep_name, born_role))
                        reversal_info[(repo, rev_commit, del_commit)].add((dep_name, born_role))
        print(f"\r处理进度: {i}", end="", flush=True)

    # ... 后续统计逻辑保持不变 ...

    # 专门针对 Selective Reversal 的深度分析
    recovered_roles = Counter()   # 被救回的角色
    abandoned_roles = Counter()   # 被永远抛弃的角色 (在 Selective 事件中)

    for (repo, rev_commit, del_commit), rev_deps in reversal_info.items():
        original_deps = delete_batches[(repo, del_commit)]
        
        # 判定为 Selective Reversal
        if len(rev_deps) < len(original_deps):
            # 1. 统计救回了谁
            for _, role in rev_deps:
                recovered_roles[role] += 1
            
            # 2. 统计抛弃了谁 (原始集合 - 恢复集合)
            rev_names = {name for name, _ in rev_deps}
            for name, role in original_deps:
                if name not in rev_names:
                    abandoned_roles[role] += 1

    # === 输出对比报告 ===
    print("\n\n" + "="*70)
    print("  SELECTIVE REVERSAL: RECOVERY VS. ABANDONMENT")
    print("-" * 70)
    print(f"{'Role Type':<15} | {'Recovered #':<15} | {'Abandoned #':<15} | {'Rescue Rate'}")
    print("-" * 70)

    for role in ['core', 'dev', 'peer']:
        rec = recovered_roles[role]
        aba = abandoned_roles[role]
        total = rec + aba
        rate = (rec / total * 100) if total > 0 else 0
        print(f"{role.upper():<15} | {rec:<15} | {aba:<15} | {rate:>10.1f}%")
    
    print("="*70)
    print("💡 解释: Rescue Rate 越高，说明该角色在误删后被『捞回来』的优先级越高。")

if __name__ == "__main__":
    main()