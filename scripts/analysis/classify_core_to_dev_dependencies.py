import json
import os
from collections import Counter, defaultdict

# ================= Configuration =================
BASE_DIR = 'splitted_files'
FILE_RANGE = range(1, 108)  # 1 to 107
OUTPUT_FILE = 'data/core/core_to_dev_refined_taxonomy.json'
TOP_K_FAMILIES = 8  # 展示更多家族以检查归类准确性

# === 1. Family Aliases (别名合并) ===
FAMILY_ALIASES = {
    '@babel': 'babel',
    'ts': 'typescript',
    'node-sass': 'sass',
    'uglify-js': 'uglify',
    'history': 'history', # react-router dependency
}

# === 2. Category Definitions (Taxonomy V3) ===
CATEGORY_DEFINITIONS = {
    # --- 1. Client-Side / Frontend ---
    'Frontend UI, DOM & Widgets': {
        # Core Frameworks
        'react', 'vue', 'angular', 'svelte', 'preact', 'backbone', 'ember', 
        'jquery', 'zepto', # jQuery 属于这里
        # UI Helpers
        'classnames', 'prop-types', 'styled-components', 'emotion',
        # UI Widgets/Libs
        'bootstrap', 'd3', 'chart.js', 'leaflet', 'font-awesome', 'animate.css'
    },
    
    'State Management & App Architecture': {
        'redux', 'mobx', 'vuex', 'flux', 'reselect', 'rxjs', 'history',
        'react-router', 'vue-router'
    },
    
    'Meta-Frameworks & Platforms': {
        'electron', 'nw', 'next', 'nuxt', 'gatsby', 'ionic', 'react-native'
    },

    # --- 2. Server-Side / Backend ---
    'Server-side Frameworks & Middleware': {
        # Frameworks
        'express', 'koa', 'hapi', 'fastify', 'restify', 'connect',
        # Middleware
        'body-parser', 'cookie-parser', 'cors', 'morgan', 'helmet', 'serve-static',
        'compression', 'passport', 'multer', 'socket.io', 'ws'
    },

    # --- 3. Development & Build Chain ---
    'Build Tools, Bundlers & Task Runners': {
        'webpack', 'gulp', 'grunt', 'rollup', 'parcel', 'browserify', 'bower', 
        'vite', 'esbuild', 'rimraf', 'clean', 'mkdirp', 'ncp', 'copy', 
        'serve', 'http-server', 'livereload', 'nodemon', 'concurrently', 'cross-env'
    },
    
    'Transpilers & Compilers': {
        'babel', 'typescript', 'coffee', 'ts', 'less', 'sass', 'stylus', 'postcss', 'autoprefixer'
    },
    
    'Loaders & Plugins (Build-related)': {
        # 这一类主要靠后缀匹配，这里放一些名字里没 loader/plugin 但属于此类的
        'css-loader', 'style-loader', 'file-loader', 'html-webpack-plugin'
    },
    
    'CLI & Terminal UX': {
        # 这些库常用于编写构建脚本或CLI工具，不应在前端Production里
        'chalk', 'commander', 'yargs', 'minimist', 'inquirer', 'ora', 'debug', 
        'colors', 'progress', 'shelljs', 'meow', 'yosay', 'prompts'
    },

    # --- 4. Quality Assurance ---
    'Testing Frameworks & Libs': {
        'jest', 'mocha', 'chai', 'jasmine', 'karma', 'ava', 'supertest', 
        'phantomjs', 'selenium', 'puppeteer', 'cypress', 'sinon', 'coveralls', 
        'istanbul', 'nyc', 'enzyme', 'qunit', 'should', 'expect', 'tap', 'nock'
    },
    
    'Linting, Formatting & Quality': {
        'eslint', 'tslint', 'jshint', 'jscs', 'prettier', 'stylelint', 
        'husky', 'lint-staged', 'standard', 'commitlint'
    },

    # --- 5. Utilities ---
    'General Utilities (Data/Math/Time)': {
        'lodash', 'underscore', 'ramda', 'moment', 'date-fns', 'dayjs', 'luxon',
        'uuid', 'validator', 'deepmerge', 'qs', 'semver', 'camelcase'
    },
    
    'Polyfills & Shims': {
        'core-js', 'babel-polyfill', 'regenerator-runtime', 'whatwg-fetch', 'es6-promise'
    },
    
    'Network & HTTP Clients': {
        'axios', 'request', 'fetch', 'isomorphic-fetch', 'superagent', 'got'
    },
    
    'Type Definitions': {
        '@types'
    }
}

# Build reverse mapping
FAMILY_TO_CATEGORY = {}
for cat, fams in CATEGORY_DEFINITIONS.items():
    for fam in fams:
        FAMILY_TO_CATEGORY[fam] = cat

# ===========================================

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def get_trajectory_from_segment(segment):
    segment.sort(key=lambda x: float(x.get('from_time', 0)))
    trajectory = []
    if not segment: return []

    first_event = segment[0]
    first_from = first_event.get('from')
    
    if first_from and first_from != 'void':
        trajectory.append({'state': first_from})
    
    current_state = first_from 
    for event in segment:
        to_state = event.get('to')
        trajectory.append({'state': to_state})
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
    # Strict Practice D Logic
    simple_seq = [e['state'] for e in seq]
    if len(simple_seq) < 2: return 'Stable'
    
    terminal = simple_seq[-1]
    non_void_seq = [s for s in simple_seq if s != 'void']
    alien_roles = [s for s in non_void_seq if s != born_role]
    has_aliens = len(alien_roles) > 0

    if has_aliens:
        # Check Oscillation
        seen_alien = False
        returned_to_origin = False
        for role in non_void_seq:
            if role != born_role: seen_alien = True
            elif role == born_role and seen_alien:
                returned_to_origin = True
                break
        if returned_to_origin: return 'F'

    if not has_aliens:
        if simple_seq.count(born_role) >= 2 and 'void' in simple_seq:
             return f"C-{born_role}" if born_role != 'core' else 'C'

    if terminal == 'void':
        return 'B' if has_aliens else 'A'

    if terminal != born_role:
        target = terminal
        if born_role == 'core':
            return 'D' if target == 'dev' else 'E'
        elif born_role == 'dev':
            return 'G' if target == 'core' else 'H'
        elif born_role == 'peer':
            return 'I' if target == 'core' else 'J'

    return 'Stable'

# === Enhanced Classifier ===
def identify_family(dep_name):
    family_name = dep_name
    if dep_name.startswith('@'):
        family_name = dep_name.split('/')[0]
    elif '-' in dep_name:
        parts = dep_name.split('-')
        prefix = parts[0]
        # 排除常用非家族前缀
        ignored_prefixes = {'js', 'is', 'to', 'get', 'has', 'lib', 'node', 'gulp', 'grunt'}
        if len(prefix) >= 3 and prefix not in ignored_prefixes:
            family_name = prefix
    return FAMILY_ALIASES.get(family_name, family_name)

def classify_category(family_name, dep_name):
    # 1. Direct Table Lookup
    if family_name in FAMILY_TO_CATEGORY:
        return FAMILY_TO_CATEGORY[family_name]
    
    # 2. Heuristic Matching (Suffix/Keyword)
    lower_dep = dep_name.lower()
    
    # Build Related
    if 'loader' in lower_dep or 'plugin' in lower_dep or 'preset' in lower_dep:
        return 'Loaders & Plugins (Build-related)'
    
    # Testing
    if 'test' in lower_dep or 'spec' in lower_dep or 'mock' in lower_dep or 'coverage' in lower_dep:
        return 'Testing Frameworks & Libs'
    
    # Linting
    if 'lint' in lower_dep:
        return 'Linting, Formatting & Quality'
        
    # CLI
    if 'cli' in lower_dep or 'bin' in lower_dep or 'argv' in lower_dep:
        return 'CLI & Terminal UX'
        
    # React/UI Related (Catch-all for react-*)
    if 'react' in lower_dep or 'vue' in lower_dep or 'angular' in lower_dep or 'ui' in lower_dep:
        return 'Frontend UI, DOM & Widgets'

    # Middleware
    if 'middleware' in lower_dep:
        return 'Server-side Frameworks & Middleware'

    return 'Other / Unclassified Libraries'

def main():
    print(f"🚀 Starting STRICT Analysis: Practice D (Core -> Dev)")
    print(f"   Taxonomy V3: Detailed breakdown of Server vs Client vs CLI vs Utils.")
    
    files_processed = 0
    total_d_cases = 0
    
    category_stats = defaultdict(lambda: {'count': 0, 'families': Counter(), 'projects': set()})
    family_examples = defaultdict(set)

    for i in FILE_RANGE:
        filename = os.path.join(BASE_DIR, f"{i}_graph.json")
        data = load_json(filename)
        if data is None: continue
        files_processed += 1
        
        for repo, deps in data.items():
            for dep_name, segments in deps.items():
                for segment in segments:
                    traj = get_trajectory_from_segment(segment)
                    born_role, seq = get_born_role_and_sequence(traj)
                    
                    if born_role == 'core':
                        code = analyze_practice(born_role, seq)
                        if code == 'D':
                            total_d_cases += 1
                            fam = identify_family(dep_name)
                            cat = classify_category(fam, dep_name)
                            
                            category_stats[cat]['count'] += 1
                            category_stats[cat]['families'][fam] += 1
                            category_stats[cat]['projects'].add(repo)
                            family_examples[fam].add(dep_name)
        
        print(f"\rProcessed {files_processed} files...", end="", flush=True)

    print("\n\n" + "="*100)
    print(f"✅ Analysis Complete.")
    print(f"Total Strictly Classified 'Practice D' Cases: {total_d_cases}")
    print("="*100)

    if total_d_cases == 0: return

    # Sort categories by count
    sorted_categories = sorted(category_stats.items(), key=lambda x: x[1]['count'], reverse=True)
    json_export = []
    
    print(f"\n🏆 Top Categories in Practice D (Core -> Dev):\n")
    
    for rank, (cat_name, stats) in enumerate(sorted_categories, 1):
        count = stats['count']
        share = (count / total_d_cases) * 100
        proj_count = len(stats['projects'])
        
        print(f"{rank}. [{cat_name}]")
        print(f"   Cases: {count} ({share:.1f}%) | Projects: {proj_count}")
        
        # Show breakdown of 'Other' to help debug
        k_val = 15 if cat_name.startswith('Other') else TOP_K_FAMILIES
        
        top_families = stats['families'].most_common(k_val)
        family_details = []
        
        for f_rank, (fam, f_count) in enumerate(top_families, 1):
            f_share = (f_count / count) * 100
            examples = list(family_examples[fam])
            examples.sort(key=len)
            ex_str = ", ".join(examples[:3])
            
            print(f"     {f_rank}. {fam:<20} : {f_count:>4} ({f_share:>4.1f}%) -> e.g. {ex_str}")
            
            family_details.append({
                'family': fam,
                'count': f_count,
                'examples': examples[:10]
            })
            
        print("-" * 80)
        
        json_export.append({
            'category': cat_name,
            'total_count': count,
            'share_percent': share,
            'top_families': family_details
        })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_export, f, indent=2)
    print(f"\n📁 Results saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()