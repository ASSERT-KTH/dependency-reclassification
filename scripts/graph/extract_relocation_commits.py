import json
import os
import glob

def extract_relocations(input_dir, output_file):
    found_records = set()
    
    # 获取所有 graph.json 文件
    search_path = os.path.join(input_dir, "*_graph.json")
    json_files = glob.glob(search_path)
    
    total_files = len(json_files)
    print(f"找到 {total_files} 个 JSON 文件，开始扫描...")

    for idx, file_path in enumerate(json_files, 1):
        filename = os.path.basename(file_path)
        
        # 实时进度打印
        if idx % 10 == 0 or idx == total_files:
            print(f"[{idx}/{total_files}] 正在扫描: {filename}...")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 第一层：遍历 Repo
                for repo_name, dependencies in data.items():
                    if not isinstance(dependencies, dict): continue
                    
                    # 第二层：遍历 Dependency (如 "prettier")
                    for dep_name, outer_list in dependencies.items():
                        if not isinstance(outer_list, list): continue
                        
                        # 第三层：遍历外层列表 (你的 JSON 里这里是一个包含列表的列表)
                        for inner_list in outer_list:
                            # 兼容性处理：如果 inner_list 直接就是字典，或者它是列表
                            if isinstance(inner_list, list):
                                # 第四层：遍历内层列表，获取真正的字典记录
                                for record in inner_list:
                                    if isinstance(record, dict):
                                        if record.get("is_relocation") is True:
                                            commit = record.get("to_commit")
                                            if repo_name and commit:
                                                found_records.add((repo_name, commit))
                            
                            elif isinstance(inner_list, dict):
                                # 如果某些文件结构没那么深，直接在这里处理
                                if inner_list.get("is_relocation") is True:
                                    commit = inner_list.get("to_commit")
                                    if repo_name and commit:
                                        found_records.add((repo_name, commit))
                                            
        except Exception as e:
            print(f"\n[!] 文件 {filename} 解析异常: {e}")

    # 写入 TXT 文件
    with open(output_file, 'w', encoding='utf-8') as out_f:
        # 排序：先按 repo 排，再按 commit 排
        sorted_records = sorted(list(found_records))
        for repo, commit in sorted_records:
            out_f.write(f"{repo}, {commit}\n")

    print(f"\n" + "="*30)
    print(f"提取完成！")
    print(f"有效记录总数: {len(found_records)}")
    print(f"结果已写入: {output_file}")
    print("="*30)

if __name__ == "__main__":
    # 请确保 splitted_files 文件夹与脚本在同一目录下
    extract_relocations('splitted_files', 'data/reclassification/relocation_commits.txt')