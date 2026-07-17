import json
import os
from collections import defaultdict, Counter

# ================= Configuration =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)  # 1 to 107
TARGET_ROLE = 'dev'        # Core 依赖
MIN_BATCH_SIZE = 3          # 保持：至少3个依赖
OUTPUT_FILE = 'data/reclassification/dev_family_merged_analysis.json'
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

def is_valid_onetime_removal(segments):
    traj = get_full_trajectory(segments)
    if not traj: return False, None
    last_event = traj[-1]
    
    # 1. Born Core
    first_event = traj[0]
    if first_event.get('from') == 'void':
        born_role = first_event.get('to')
    else:
        born_role = first_event.get('from') 
    if born_role != TARGET_ROLE: return False, None

    # 2. To Void
    if last_event.get('to') != 'void': return False, None
    # 3. No Relocation
    if last_event.get('is_relocation') is True: return False, None
    # 4. No Resurrection
    void_count = sum(1 for e in traj if e.get('to') == 'void')
    if void_count > 1: return False, None

    return True, last_event.get('to_commit')

def identify_families(dep_list):
    if not dep_list: return None, 0.0, []
    n = len(dep_list)
    
    # 1. Scope
    scopes = [d.split('/')[0] for d in dep_list if d.startswith('@')]
    if scopes:
        top_scope, count = Counter(scopes).most_common(1)[0]
        if count > 1:
            members = [d for d in dep_list if d.startswith(top_scope)]
            return top_scope, count / n, members

    # 2. Prefix
    prefixes = []
    for d in dep_list:
        if '-' in d:
            parts = d.split('-')
            if len(parts[0]) >= 3: prefixes.append(parts[0] + '-')
    if prefixes:
        top_prefix, count = Counter(prefixes).most_common(1)[0]
        if count > 1:
            members = [d for d in dep_list if d.startswith(top_prefix)]
            return top_prefix, count / n, members

    # 3. Inclusion
    sorted_deps = sorted(dep_list, key=len)
    potential_root = sorted_deps[0]
    if len(potential_root) >= 3:
        matches = [d for d in dep_list if d.startswith(potential_root)]
        if len(matches) > 1:
             return potential_root, len(matches) / n, matches

    return "Mixed", 0.0, []

def main():
    print(f"🚀 Starting [Merged] Family Analysis for '{TARGET_ROLE.upper()}'...")
    print(f"   Criteria: A batch is 'Family-Style' if Cohesion >= 50%.")

    batch_map = defaultdict(lambda: defaultdict(list))
    files_processed = 0

    # 1. 扫描
    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if data is None: continue
        files_processed += 1
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                is_valid, death_commit = is_valid_onetime_removal(segments)
                if is_valid and death_commit:
                    batch_map[repo][death_commit].append(dep_name)
        print(f"\rProcessed {files_processed} files...", end="", flush=True)
    print("\n")

    # 2. 分析
    results = []
    total_batches = 0
    
    # === 修改点：只分两类 ===
    patterned_batches = 0 # Cohesion >= 0.5
    random_batches = 0    # Cohesion < 0.5
    
    family_distribution = Counter() 

    for repo, commits in batch_map.items():
        for commit, deps in commits.items():
            if len(deps) < MIN_BATCH_SIZE:
                continue
            
            total_batches += 1
            family_name, coverage, members = identify_families(deps)
            
            results.append({
                'repo': repo,
                'commit': commit,
                'batch_size': len(deps),
                'dominant_family': family_name,
                'cohesion_score': round(coverage, 2),
                'all_deps': deps
            })
            
            # === 合并统计逻辑 ===
            if coverage >= 0.5:
                patterned_batches += 1
                if family_name != "Mixed":
                    family_distribution[family_name] += 1
            else:
                random_batches += 1

    # 3. 输出报告
    print("=" * 60)
    print(f"📊 [CORE] Merged Family Analysis Report")
    print("=" * 60)
    print(f"Total Batches (Size >= {MIN_BATCH_SIZE}): {total_batches:,}")
    
    pat_pct = (patterned_batches / total_batches) * 100 if total_batches else 0
    rand_pct = (random_batches / total_batches) * 100 if total_batches else 0
    
    print(f"\n✅ Family-Dominated Batches (Cohesion >= 50%): {patterned_batches:,} ({pat_pct:.1f}%)")
    print(f"   -> Interpretation: The removal was targeted at a specific framework/library set.")
    
    print(f"\n🚫 Random/Mixed Batches (Cohesion < 50%):      {random_batches:,} ({rand_pct:.1f}%)")
    print(f"   -> Interpretation: General cleanup without a dominant theme.")
    
    print("-" * 60)
    print("🏆 Top 10 Removed Core Families:")
    for fam, count in family_distribution.most_common(10):
        print(f"   - {fam:<15}: {count} batches")

    # 打印例子
    print("-" * 60)
    print("🔥 Examples of Family-Dominated Removals:")
    sorted_results = sorted(results, key=lambda x: x['batch_size'], reverse=True)
    
    count = 0
    for res in sorted_results:
        # 只要 >= 0.5 且有一定规模
        if res['cohesion_score'] >= 0.5 and res['batch_size'] >= 5:
            print(f"\n[Repo]: {res['repo']}")
            print(f"  Family: {res['dominant_family']} (Score: {res['cohesion_score']})")
            print(f"  Size: {res['batch_size']}")
            print(f"  Deps: {', '.join(res['all_deps'][:6])}...")
            count += 1
            if count >= 5: break

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n📁 Saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()