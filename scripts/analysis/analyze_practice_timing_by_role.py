import json
import os
import math
from collections import Counter, defaultdict

# ================= Configuration =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)  # 1 to 107
REPORT_DAYS_FILE = 'data/reports/report_no_relocation_days.txt'
REPORT_COMMITS_FILE = 'data/reports/report_no_relocation_commits.txt'
JSON_OUTPUT_FILE = 'data/transitions/trajectory_details_no_relocation.json' 
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
        else:
            weight = idx_float - lower
            return data[lower] * (1 - weight) + data[upper] * weight
    return get_val((n-1)/2.0), get_val((n-1)/4.0), get_val((n-1)*0.75)

def get_stats_str(data_list):
    if not data_list: return "0.0 [0.0, 0.0]"
    med, q1, q3 = calculate_quartiles(data_list)
    return f"{med:.1f} [{q1:.1f}, {q3:.1f}]"

def get_percentage_stats(data_list, thresholds):
    total = len(data_list)
    if total == 0:
        return {t: 0.0 for t in thresholds}, 0
    results = {}
    for t in thresholds:
        count = sum(1 for x in data_list if x <= t)
        results[t] = (count / total) * 100.0
    return results, total

def get_trajectory_from_segment(segment):
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return []

    first_event = segment[0]
    first_from = first_event.get('from')
    
    # 捕捉物理起点
    if first_from and first_from != 'void':
        trajectory.append({
            'state': first_from, 
            'duration': 0, 'commits': 0, 'is_artificial': True
        })

    current_state = first_from 

    for event in segment:
        to_state = event.get('to')
        # is_relocation 字段虽然存在，但我们在此逻辑中完全忽略它
        # 只关心状态是否发生了改变
        duration = float(event.get('duration', 0.0))
        commits = int(event.get('commits', 0))
        
        event_info = {
            'state': to_state, 
            'duration': duration, 'commits': commits, 'is_artificial': False
        }

        # ✨ 修改：严格基于状态变化。忽略 Relocation 事件（如 Core->Core）。
        if to_state != current_state:
            trajectory.append(event_info)
            current_state = to_state
            
    return trajectory

def get_born_role_and_sequence(traj):
    if not traj: return None, []
    s0 = traj[0]['state']
    if s0 in ['core', 'dev', 'peer']: return s0, traj
    if s0 == 'void' and len(traj) > 1:
        s1 = traj[1]['state']
        if s1 in ['core', 'dev', 'peer']: return s1, traj[1:] 
    return None, []

def analyze_practice(born_role, seq):
    """
    LOGIC (NO RELOCATION considered):
    1. F (Oscillation with Return)
    2. C (Pure Toggling)
    3. Terminal Check:
       - Void -> B (Aliens) or A (No Aliens)
       - Non-Void -> D/E/G...
    """
    simple_seq = [e['state'] for e in seq]
    if len(simple_seq) < 2: return 'Stable'
    terminal = simple_seq[-1]
    
    non_void_seq = [s for s in simple_seq if s != 'void']
    alien_roles = [s for s in non_void_seq if s != born_role]
    has_aliens = len(alien_roles) > 0

    # 1. F: Role Oscillation
    if has_aliens:
        seen_alien = False
        returned_to_origin = False
        for role in non_void_seq:
            if role != born_role: seen_alien = True
            elif role == born_role and seen_alien:
                returned_to_origin = True
                break
        if returned_to_origin: return 'F'

    # 2. C: Pure Toggling
    if not has_aliens:
        if 'void' in simple_seq[:-1] and simple_seq.count(born_role) >= 2:
            return f"C-{born_role}" if born_role != 'core' else 'C'

    # 3. Branch by Terminal
    if terminal == 'void':
        # ✨ 修改：这里不再区分 A 和 R，统统算作 A 或 B
        if has_aliens: 
            return f"B-{born_role}" if born_role != 'core' else 'B'
        else:
            return f"A-{born_role}" if born_role != 'core' else 'A'

    if terminal != born_role:
        target = terminal
        if born_role == 'core': return 'D' if target == 'dev' else 'E'
        elif born_role == 'dev': return 'G' if target == 'core' else 'H'
        elif born_role == 'peer': return 'I' if target == 'core' else 'J'

    return 'Stable'

def main():
    print(f"Starting Analysis (NO RELOCATION LOGIC)...")
    
    roles = ['core', 'dev', 'peer']
    
    # ✨ 修改：移除了 'R'
    practice_keys = {
        'core': ['A', 'B', 'C', 'D', 'E', 'F', 'Stable'],
        'dev':  ['A-dev', 'B-dev', 'C-dev', 'G', 'H', 'F', 'Stable'],
        'peer': ['A-peer', 'B-peer', 'C-peer', 'I', 'J', 'F', 'Stable']
    }
    
    stats = {
        r: {
            k: {
                'cases': 0, 'projects': set(),
                'durations': [], 'commits': [],
                'paths': Counter(),
                'path_details': defaultdict(lambda: {'count': 0, 'deps': Counter(), 'projects': set()})
            } for k in practice_keys[r]
        } for r in roles
    }
    
    totals = { r: {'cases': 0, 'projects': set(), 'changed_cases': 0, 'changed_projects': set()} for r in roles }

    files_processed = 0

    # === Step 1: Process Files ===
    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if data is None: continue
        files_processed += 1
        
        for repo, deps in data.items():
            repo_roles_found = set() 
            repo_roles_changed = set() 
            
            for dep_name, segments in deps.items():
                for segment in segments:
                    traj = get_trajectory_from_segment(segment)
                    born_role, seq = get_born_role_and_sequence(traj)
                    
                    if born_role:
                        totals[born_role]['cases'] += 1
                        repo_roles_found.add(born_role)
                        code = analyze_practice(born_role, seq)
                        
                        if code in stats[born_role]:
                            target_stat = stats[born_role][code]
                            target_stat['cases'] += 1
                            target_stat['projects'].add(repo)
                            
                            for item in seq:
                                if not item.get('is_artificial', False):
                                    days = item['duration'] / 86400.0
                                    commits = item['commits']
                                    target_stat['durations'].append(days)
                                    target_stat['commits'].append(commits)
                            
                            path_states = [e['state'] for e in seq]
                            path_str = " -> ".join(path_states)
                            
                            target_stat['paths'][path_str] += 1
                            detail_entry = target_stat['path_details'][path_str]
                            detail_entry['count'] += 1
                            detail_entry['deps'][dep_name] += 1
                            detail_entry['projects'].add(repo)
                        
                        if code != 'Stable':
                            totals[born_role]['changed_cases'] += 1
                            repo_roles_changed.add(born_role)
            
            for r in repo_roles_found: totals[r]['projects'].add(repo)
            for r in repo_roles_changed: totals[r]['changed_projects'].add(repo)

        print(f"\rProcessed {files_processed} files...", end="", flush=True)

    print("\n\nAnalysis Complete. Generating Reports...")

    descriptions = {
        'A': 'One-step removal', 
        'B': 'Multi-step removal', 
        'C': 'Removal reversion',
        'D': 'Reclass to DEV', 'E': 'Reclass to PEER', 
        'F': 'Role Oscillation',
        'Stable': 'Stable',
        
        'A-dev': 'One-step removal', 'B-dev': 'Multi-step removal', 'C-dev': 'Removal reversion',
        'G': 'Reclass to CORE', 'H': 'Reclass to PEER',
        
        'A-peer': 'One-step removal', 'B-peer': 'Multi-step removal', 'C-peer': 'Removal reversion',
        'I': 'Reclass to CORE', 'J': 'Reclass to DEV'
    }

    # === Step 2: Generate Text Reports ===
    with open(REPORT_DAYS_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{'ROLE':<6} | {'CODE':<8} | {'DESCRIPTION':<40} | {'EDGES #':<10} | {'% <= 7 Days':<15} | {'% <= 30 Days':<15}\n")
        f.write("-" * 110 + "\n")
        for role in roles:
            for code in practice_keys[role]:
                desc = descriptions.get(code, code)
                data_list = stats[role][code]['durations']
                res, total = get_percentage_stats(data_list, [7, 30])
                f.write(f"{role.upper():<6} | {code:<8} | {desc:<40} | {total:<10} | {res[7]:>13.2f}% | {res[30]:>13.2f}%\n")
            f.write("-" * 110 + "\n")
    print(f"✅ Full Days Report saved to: {REPORT_DAYS_FILE}")

    with open(REPORT_COMMITS_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{'ROLE':<6} | {'CODE':<8} | {'DESCRIPTION':<40} | {'EDGES #':<10} | {'% <= 5 Commits':<15} | {'% <= 20 Commits':<15}\n")
        f.write("-" * 110 + "\n")
        for role in roles:
            for code in practice_keys[role]:
                desc = descriptions.get(code, code)
                data_list = stats[role][code]['commits']
                res, total = get_percentage_stats(data_list, [5, 20])
                f.write(f"{role.upper():<6} | {code:<8} | {desc:<40} | {total:<10} | {res[5]:>13.2f}% | {res[20]:>13.2f}%\n")
            f.write("-" * 110 + "\n")
    print(f"✅ Full Commits Report saved to: {REPORT_COMMITS_FILE}")
    print("\n")

    # === Step 3: Print Overview Table ===
    row_fmt = "{:<8} | {:<40} | {:<8} | {:<8} | {:<8} | {:<8} | {:<20} | {:<20}"

    for role in roles:
        print("#" * 160)
        print(f"  ROLE ANALYSIS: {role.upper()}")
        print("#" * 160)
        
        d_proj_chg = len(totals[role]['changed_projects']) if len(totals[role]['changed_projects']) > 0 else 1
        d_case_chg = totals[role]['changed_cases'] if totals[role]['changed_cases'] > 0 else 1

        print(f"\n[TABLE] PRACTICE DISTRIBUTION (Excluding Stable, No Relocations)")
        print(f"       Base: {d_case_chg} changed cases across {d_proj_chg} projects")
        print("-" * 160)
        print(row_fmt.format("CODE", "DESC", "PROJ #", "PROJ %", "CASE #", "CASE %", "Med Days", "Med Com"))
        print("-" * 160)
        
        changed_keys = [k for k in practice_keys[role] if k != 'Stable']
        
        for code in changed_keys:
            data = stats[role][code]
            p_pct = (len(data['projects']) / d_proj_chg) * 100
            c_pct = (data['cases'] / d_case_chg) * 100
            desc = descriptions.get(code, code)
            days_s = get_stats_str(data['durations'])
            commits_s = get_stats_str(data['commits'])
            print(row_fmt.format(code, desc, len(data['projects']), f"{p_pct:.1f}%", data['cases'], f"{c_pct:.1f}%", days_s, commits_s))
        
        print("-" * 160)
        
        print(f"\n[TOP 5 FREQUENT TRAJECTORIES]")
        print("-" * 100)
        
        for code in changed_keys:
            path_counter = stats[role][code]['paths']
            if not path_counter: continue
            desc = descriptions.get(code, code)
            total_cases_for_code = stats[role][code]['cases']
            total_projects_for_code = len(stats[role][code]['projects'])
            
            print(f"► Code {code} ({desc}) - Total Cases: {total_cases_for_code} | Total Projects: {total_projects_for_code}")
            
            top_5 = path_counter.most_common(5)
            for rank, (path, count) in enumerate(top_5, 1):
                path_data = stats[role][code]['path_details'][path]
                case_pct = (count / total_cases_for_code) * 100
                proj_count = len(path_data['projects'])
                proj_pct = (proj_count / total_projects_for_code * 100) if total_projects_for_code else 0
                
                print(f"    {rank}. [Cases: {count:<5} | {case_pct:>5.1f}%]  [Projs: {proj_count:<4} | {proj_pct:>5.1f}%]  {path}")
            print("")
        print("\n")

    # === Step 4: Generate JSON ===
    print(f"Generating {JSON_OUTPUT_FILE} ...")
    
    json_export_data = {}

    for role in roles:
        json_export_data[role] = {}
        changed_keys = [k for k in practice_keys[role] if k != 'Stable']
        
        for code in changed_keys:
            path_details = stats[role][code]['path_details']
            if not path_details: continue
            
            paths_list = []
            for path_str, detail in path_details.items():
                top_5_deps = detail['deps'].most_common(5)
                paths_list.append({
                    "path": path_str,
                    "count": detail['count'],
                    "project_count": len(detail['projects']),
                    "top_5_dependencies": top_5_deps
                })
            
            paths_list.sort(key=lambda x: x['count'], reverse=True)
            json_export_data[role][code] = paths_list

    with open(JSON_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_export_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ JSON Data saved to: {JSON_OUTPUT_FILE}")

if __name__ == "__main__":
    main()