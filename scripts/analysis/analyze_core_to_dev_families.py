import json
import os
from collections import Counter, defaultdict

# ================= Configuration =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)
OUTPUT_FILE = 'data/core/core_to_dev_family_concentration.json'
# ✨ 我们现在不再只取 Top K，而是分析整个长尾分布
CUMULATIVE_THRESHOLD = 90.0  # 关注前 90% 的家族

FAMILY_ALIASES = {
    # === 编译器与语言 (Compilers & Languages) ===
    '@babel': 'babel',
    'babel': 'babel',
    'ts': 'typescript',
    'typescript': 'typescript',
    'coffee': 'coffeescript',
    
    # === 类型定义 (Type Definitions) ===
    '@types': '@types',  # 保持统一前缀
    
    # === 测试框架生态 (Testing Ecosystem) ===
    '@jest': 'jest',
    'jest': 'jest',
    'mocha': 'mocha',
    'chai': 'chai',
    'karma': 'karma',
    'jasmine': 'jasmine',
    'cypress': 'cypress',
    '@testing-library': 'testing-library',
    
    # === 代码规范与格式化 (Linting & Formatting) ===
    '@eslint': 'eslint',
    'eslint': 'eslint',
    'prettier': 'prettier',
    'stylelint': 'stylelint',
    'jshint': 'jshint',
    
    # === 构建工具与插件 (Build Tools) ===
    'webpack': 'webpack',
    '@webpack': 'webpack',
    'rollup': 'rollup',
    'gulp': 'gulp',
    'grunt': 'grunt',
    'vite': 'vite',
    'parcel': 'parcel',
    'esbuild': 'esbuild',
    
    # === 样式处理 (Styles) ===
    'sass': 'sass',
    'node-sass': 'sass',
    'less': 'less',
    'postcss': 'postcss',
    
    # === 框架相关工具 (Framework Tooling) ===
    '@vue': 'vue',
    'vue': 'vue',
    '@angular': 'angular',
    'react': 'react',      # 比如 react-dom, react-router 统归 react
    
    # === 常用实用库前缀 (Utilities) ===
    'lodash': 'lodash'
}
# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception: return None

def get_trajectory_from_segment(segment):
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return []
    first_from = segment[0].get('from')
    if first_from and first_from != 'void':
        trajectory.append({ 'state': first_from })
    current_state = first_from
    for event in segment:
        to_state = event.get('to')
        if to_state != current_state:
            trajectory.append({ 'state': to_state })
            current_state = to_state
    return trajectory

def identify_family(dep_name):
    family_name = dep_name
    if dep_name.startswith('@'):
        family_name = dep_name.split('/')[0]
    elif '-' in dep_name:
        parts = dep_name.split('-')
        prefix = parts[0]
        ignored_prefixes = {'js', 'is', 'to', 'get', 'has', 'lib', 'node'}
        if len(prefix) >= 3 and prefix not in ignored_prefixes:
            family_name = prefix
    return FAMILY_ALIASES.get(family_name, family_name)

def main():
    print(f"🚀 分析 Dependency Family 集中度 (目标累积占比: {CUMULATIVE_THRESHOLD}%)")
    
    family_counter = Counter()
    family_members = defaultdict(set)
    total_cases = 0
    files_processed = 0

    # === Step 1: 数据采集 ===
    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if not data: continue
        files_processed += 1
        
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                for segment in segments:
                    traj = get_trajectory_from_segment(segment)
                    path = [t['state'] for t in traj]
                    
                    # 检查 Core -> Dev 变迁
                    if any(path[j] == 'core' and path[j+1] == 'dev' for j in range(len(path)-1)):
                        total_cases += 1
                        fam = identify_family(dep_name)
                        family_counter[fam] += 1
                        family_members[fam].add(dep_name)
        
        print(f"\r已处理 {files_processed} 个文件...", end="", flush=True)

    if total_cases == 0:
        print("\n未找到任何变迁案例。")
        return

    # === Step 2: 累积占比计算与排名 ===
    # 按出现频率从高到低排序
    sorted_families = family_counter.most_common()
    
    print("\n\n" + "="*120)
    header = "{:<4} | {:<20} | {:<8} | {:<8} | {:<12} | {:<30}".format(
        "RANK", "FAMILY", "CASES", "SHARE%", "CUMULATIVE%", "MEMBERS"
    )
    print(header)
    print("-" * 120)

    cumulative_count = 0
    threshold_reached = False
    families_within_threshold = 0
    export_data = []

    for rank, (fam, count) in enumerate(sorted_families, 1):
        share = (count / total_cases) * 100
        cumulative_count += count
        cumulative_percent = (cumulative_count / total_cases) * 100
        
        members = sorted(list(family_members[fam]), key=len)
        members_str = ", ".join(members[:3]) + ("..." if len(members) > 3 else "")
        
        # 打印信息
        row = "{:<4} | {:<20} | {:<8} | {:<7.1f}% | {:<11.1f}% | {:<30}".format(
            rank, fam, count, share, cumulative_percent, members_str
        )
        
        # 标记出超过阈值的分割线
        if not threshold_reached:
            families_within_threshold += 1
            print(row)
            if cumulative_percent >= CUMULATIVE_THRESHOLD:
                print("-" * 120)
                print(f"⚠️  以上 {families_within_threshold} 个家族已占据 {cumulative_percent:.1f}% 的案例总数")
                print("-" * 120)
                threshold_reached = True
        elif rank <= families_within_threshold + 5: # 阈值外多显几个作为参考
            print(f"   {row}")

        export_data.append({
            'rank': rank, 'family': fam, 'count': count, 
            'cumulative_percent': round(cumulative_percent, 2)
        })

    # === Step 3: 集中度分析摘要 ===
    total_distinct_families = len(sorted_families)
    concentration_ratio = (families_within_threshold / total_distinct_families) * 100
    
    print(f"\n💡 集中度洞察:")
    print(f"   1. 总变迁案例: {total_cases}")
    print(f"   2. 涉及的不同家族总数: {total_distinct_families}")
    print(f"   3. 头部效应: 仅 {families_within_threshold} 个家族 (占总数的 {concentration_ratio:.1f}%) "
          f"就贡献了 {CUMULATIVE_THRESHOLD}% 的变迁行为。")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2)

if __name__ == "__main__":
    main()