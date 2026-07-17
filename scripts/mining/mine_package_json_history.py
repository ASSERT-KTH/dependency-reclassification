import os
import subprocess
import requests
import re
import json
from jsondiff import symbols
from jsondiff import diff
from datetime import datetime

github_token = __import__('os').environ.get('GITHUB_TOKEN', '')
headers = {}
headers['Authorization'] = f'token {github_token}'

CLONE_DIR = "cloned_repos"
os.makedirs(CLONE_DIR, exist_ok=True)
commit_array = []

def clear_file(file_path):
    with open(file_path, 'w'):
        pass # Clear the file

def format_time(time_string):
    time_object = datetime.strptime(time_string, '%a %b %d %H:%M:%S %Y %z')
    
    return time_object.strftime('%Y %b %d %H:%M:%S')

# Set the filenames for the output files
def set_filenames(suffix):
    REPOS_FILE = f"splitted_files/output_part_{suffix}.txt"
    # REPOS_FILE = f"repos_example.txt"
    # DIFF_FILE = f"diff_{suffix}.txt"
    # DIFF_FILE = f"diff_example.txt"
    ANALYSIS_FILE = f"splitted_files/{suffix}_analysis.txt"
    # ANALYSIS_EXTRA_FILE = f"split_files/{suffix}_analysis_extra.txt"
    # ANALYSIS_FILE = f"analysis_example.txt"
    ERROR_FILE = f"logs/error_pkg.log"
    # ANALYSIS_EXTRA_FILE = f"analysis_extra_example.txt"
    # COMMIT_FILE = f"commit_{suffix}.txt"
    return REPOS_FILE, ANALYSIS_FILE, ERROR_FILE


def repo_exists(repo):
    url = f"https://github.com/{repo}"
    response = requests.head(url)
    return response.status_code == 200

def get_package_json_at_commit(commit_hash):
    try:
        # Get the content of package.json at the specific commit
        result = subprocess.run(
            ["git", "show", f"{commit_hash}:package.json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving package.json for commit {commit_hash}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def process_commits(pkg_log):
    global commit_array
    commit_array = []
    
    # Populate commit_array with commit hashes
    for line in pkg_log.splitlines():
        commit_hash = line.split(' - ')[0]
        commit_array.append(commit_hash)

def count_dependencies_from_content(package_json_content):
    # Parse the JSON content if it's in string form
    if isinstance(package_json_content, str):
        package_data = json.loads(package_json_content)
    else:
        package_data = package_json_content

    # Get the number of dependencies and devDependencies
    dependencies = package_data.get('dependencies', {})
    dependencies_count = len(dependencies) if dependencies is not None else 0
    devDependencies = package_data.get('devDependencies', {})
    devDependencies_count = len(devDependencies) if devDependencies is not None else 0
    peerDependencies = package_data.get('peerDependencies', {})
    peerDependencies_count = len(peerDependencies) if peerDependencies is not None else 0
    # print(f"Dependencies: {dependencies_count}, devDependencies: {devDependencies_count}")

    return dependencies_count, devDependencies_count, peerDependencies_count


def is_package_json_included(repo, default_branch):
    raw_file_url = f'https://raw.githubusercontent.com/{repo}/{default_branch}/package.json'

    # Make the HTTP GET request
    response = requests.get(raw_file_url)
    return response.status_code == 200

def clone_and_analyze(repo, default_branch, ANALYSIS_FILE, ERROR_FILE):
    repo_name = repo.split('/')[-1]
    repo_dir = os.path.join(CLONE_DIR, repo_name)
    no_dep_change_commit = []

    subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo}.git", repo_dir])

    os.chdir(repo_dir)

    commit_count = subprocess.run(["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
    pkg_log = subprocess.run(["git", "log", "--first-parent", default_branch, "--follow", "--pretty=format:%h - %ad : %s", "--", "package.json"], capture_output=True, text=True).stdout

    # with open(f"../../{COMMIT_FILE}", "a") as commit_file:
    #     commit_file.write(pkg_log + "\n" + "-" * 43 + "\n")
    
    process_commits(pkg_log)
    print(f"Number of commits: {len(commit_array)} / {commit_count}")
    print("length of pkg_log:", len(pkg_log.splitlines()))
    # count the number of commits where dependencies change
    dependency_change_count = 0
    devDependencies_change_count = 0
    peerDependencies_change_count = 0
    optionalDependencies_change_count = 0
    bundleDependencies_change_count = 0

    # use jsondiff to get the difference between packages of two commits
    for line in pkg_log.splitlines():
        parts = line.split(' - ')
        if len(parts) > 1 and ':' in parts[1]:
            commit = line.split(' - ')[0]
            commit_time = parts[1].split(' :')[0]
            commit_msg = line.split(' - ')[1].split(' :')[1]
        else:
            continue
                
        print("commit:", commit)
        pkg_output = get_package_json_at_commit(commit)
        # print("pkg_output: ", pkg_output)

        try:
            pkg_output = json.loads(pkg_output) if pkg_output else None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            with open(f"../../{ERROR_FILE}", "a") as error_file:
                error_file.write(f"Error decoding JSON: {e}\n")
            pkg_output = None
        
        # print("pkg_output:", pkg_output)
        # get the json of previous commit
        # subprocess.run(["git", "show", commit, "package.json"], stdout=open("../../" + DIFF_FILE, "a"))
        pkg_output_previous = get_package_json_at_commit(commit_array[commit_array.index(commit) + 1]) if commit_array.index(commit) < len(commit_array) - 1 else None
        
        # print("pkg_output_previous", pkg_output_previous)
        
        try:
            pkg_output_previous = json.loads(pkg_output_previous) if pkg_output_previous else None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            with open(f"../../{ERROR_FILE}", "a") as error_file:
                error_file.write(f"Error decoding JSON: {e}\n")
            pkg_output_previous = None
            
        if pkg_output is None or pkg_output_previous is None:
            continue

        num_deps, num_devDeps, num_peerDeps = count_dependencies_from_content(pkg_output)

        diff_output = diff(pkg_output_previous, pkg_output, syntax='explicit')

        updated_version, de_dependencies, in_dependencies, up_dependencies, de_dev_deps, in_dev_deps, up_dev_deps, de_peerDependencies, in_peerDependencies, up_peerDependencies, de_optionalDependencies, in_optionalDependencies, up_optionalDependencies, de_bundleDependencies, in_bundleDependencies, up_bundleDependencies, remove_all_dependencies, remove_all_devDependencies,remove_all_peerDependencies, remove_all_optionalDependencies, remove_all_bundleDependencies, dependencies_change, devDependencies_change, peerDependencies_change, optionalDependencies_change, bundleDependencies_change, version_change = extract_dependency_actions(diff_output)


        dependencies_diff = {
            "version": updated_version,
            "delete": de_dependencies,
            "insert": in_dependencies,
            "update": up_dependencies,
            "delete_dev": de_dev_deps,
            "insert_dev": in_dev_deps,
            "update_dev": up_dev_deps,
            "delete_peer": de_peerDependencies,
            "insert_peer": in_peerDependencies,
            "update_peer": up_peerDependencies,
            "delete_optional": de_optionalDependencies,
            "insert_optional": in_optionalDependencies,
            "update_optional": up_optionalDependencies,
            "delete_bundle": de_bundleDependencies,
            "insert_bundle": in_bundleDependencies,
            "update_bundle": up_bundleDependencies,
            "remove_all_dep": remove_all_dependencies,
            "remove_all_devDep": remove_all_devDependencies,
            "remove_all_peerDep": remove_all_peerDependencies,
            "remove_all_optionalDep": remove_all_optionalDependencies,
            "remove_all_bundleDep": remove_all_bundleDependencies,
            "dependencies_change": dependencies_change,
            "devDependencies_change": devDependencies_change,
            "peerDependencies_change": peerDependencies_change,
            "optionalDependencies_change": optionalDependencies_change,
            "bundleDependencies_change": bundleDependencies_change,
            "version_change": version_change
        }

        # save the difference to the analysis file
        if dependencies_change or devDependencies_change or peerDependencies_change:
            with open(f"../../{ANALYSIS_FILE}", "a") as analysis_file:
                # generate a json and transform it to string
                json_obj = {"repo": repo, "default": default_branch, "deps": num_deps, "devDeps": num_devDeps, "peerDeps": num_peerDeps, "commit": commit, "time": format_time(commit_time), "msg": commit_msg, "diff": dependencies_diff}
                # print(json_obj)
                try:
                    analysis_file.write(f"{json.dumps(json_obj)}\n")
                except Exception as e:
                    print(f"Error writing to analysis file: {e}")
                    with open(f"../../{ERROR_FILE}", "a") as error_file:
                        error_file.write(f"Error writing to analysis file: {e}\n")

        if dependencies_change:
            dependency_change_count += 1
        if devDependencies_change:
            devDependencies_change_count += 1
        if peerDependencies_change:
            peerDependencies_change_count += 1
        if optionalDependencies_change:
            optionalDependencies_change_count += 1
        if bundleDependencies_change:
            bundleDependencies_change_count += 1

        if not dependencies_change and not devDependencies_change and not peerDependencies_change and not optionalDependencies_change and not bundleDependencies_change:
            no_dep_change_commit.append(commit)
            diff_output = subprocess.run(
                ["git", "show", commit, "package.json"], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',  # Specify UTF-8 encoding explicitly
                errors='ignore'    # Ignore invalid byte sequences
            ).stdout

            # print("diff_output: ", diff_output)

            # change_type = analyze_diff(diff_output, commit)     
            # with open(f"../../{ANALYSIS_EXTRA_FILE}", "a") as analysis_file:
            #     analysis_file.write(f"{repo} --- {commit} --- {commit_time} --- {change_type}\n")
        

    pkg_count = len(commit_array)
    with open("../../total_count_new.txt", "a") as total_count:
        total_count.write(f"{repo}, {default_branch}, {commit_count},{pkg_count},{dependency_change_count},{devDependencies_change_count},{peerDependencies_change_count},{optionalDependencies_change_count},{bundleDependencies_change_count},{len(no_dep_change_commit)}\n")

    # if pkg_count == 0 and dependency_change_count == 0 and devDependencies_change_count == 0 and peerDependencies_change_count == 0 and optionalDependencies_change_count == 0 and bundleDependencies_change_count == 0 and len(no_dep_change_commit) == 0:
    #     with open("../../repo_tobe_fixed.txt", "a") as fix_repo:
    #         fix_repo.write(f"{repo}, {default_branch}\n")

    os.chdir("../../")
    subprocess.run(["rm", "-rf", repo_dir])

def extract_dependency_actions(diff_output):
    # Extract the version changes and dependencies changes that we care about
    # output: dict
#{
#    "insert":{
#       "nodemonConfig":{
#          "events":{
#             "restart":"kill-port 5000",
#             "crash":"kill-port 5000"
#          },
#          "delay":"1500"
#       }
#    },
#    "update":{
#       "version":"1.1.8",
#       "scripts":{
#          "insert":{
#             "build:login":"node scripts/build.js"
#          },
#          "update":{
#             "start:server":"NPM_DEPLOY_TARGET=API_SERVER NPM_BUILD_TARGET=API_SERVER NODE_ENV=development nodemon packages/databyss-api/server.js",
#             "storybook":"start-storybook -h 0.0.0.0 -p 6006 -s ./packages/databyss-ui/public",
#             "storybook:build":"build-storybook -o build -s ./packages/databyss-ui/public && node scripts/sb-publish.js Databyss"
#          }
#       },
#       "dependencies":{
#          "insert":{
#             "kill-port":"^1.5.1"
#          },
#          "update":{
#             "@storybook/addon-options":"^5.1.1",
#             "@storybook/addon-storyshots":"^5.1.1",
#             "@storybook/addons":"^5.1.1",
#             "react-native":"^0.60.4"
#          },
#          "delete":[
#             "@babel/cli",
#             "@babel/node",
#             "@babel/plugin-transform-runtime",
#             "@babel/preset-env",
#             "@bugsnag/js",
#             "expo-app-auth"
#          ]
#       }
#    }
# }
    up_dependencies = []
    in_dependencies = []
    de_dependencies = []
    in_dependencies_symbol = {}
    de_dependencies_symbol = {}
    up_dependencies_symbol = {}

    up_devDependencies = []
    in_devDependencies = []
    de_devDependencies = []
    in_devDependencies_symbol = {}
    de_devDependencies_symbol = {}
    up_devDependencies_symbol = {}

    up_peerDependencies = []
    in_peerDependencies = []
    de_peerDependencies = []
    in_peerDependencies_symbol = {}
    de_peerDependencies_symbol = {}
    up_peerDependencies_symbol = {}

    up_optionalDependencies = []
    in_optionalDependencies = []
    de_optionalDependencies = []
    in_optionalDependencies_symbol = {}
    de_optionalDependencies_symbol = {}
    up_optionalDependencies_symbol = {}

    up_bundleDependencies = []
    in_bundleDependencies = []
    de_bundleDependencies = []
    in_bundleDependencies_symbol = {}
    de_bundleDependencies_symbol = {}
    up_bundleDependencies_symbol = {}

    updated_version = ''
    remove_all_dependencies = False
    remove_all_devDependencies = False
    remove_all_peerDependencies = False
    remove_all_optionalDependencies = False
    remove_all_bundleDependencies = False

    dependencies_change = False
    devDependencies_change = False
    peerDependencies_change = False
    optionalDependencies_change = False
    bundleDependencies_change = False
    version_change = False

    update_data = {}

    if symbols.update in diff_output:
        update_data = diff_output[symbols.update] if symbols.update in diff_output else {}
        for key, value in update_data.items():
            if isinstance(key, symbols.Symbol):
                continue

            if key == "dependencies":
                dependencies_change = True

                # dependency updates
                up_dependencies_symbol = value[symbols.update] if symbols.update in value else {}
                if isinstance(up_devDependencies_symbol, dict) and len(up_dependencies_symbol) > 0:
                    for key, key_value in up_dependencies_symbol.items():
                        try:
                            up_dependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

                # dependency deletions
                de_dependencies_symbol = value[symbols.delete] if symbols.delete in value else []                    
                if isinstance(de_dependencies_symbol, list) and len(de_dependencies_symbol) > 0:
                    de_dependencies.extend(de_dependencies_symbol)

                # dependency insertions
                in_dependencies_symbol = value[symbols.insert] if symbols.insert in value else {}
                if isinstance(in_dependencies_symbol, dict) and len(in_dependencies_symbol) > 0:
                    for key, key_value in in_dependencies_symbol.items():
                        try:
                            in_dependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

            if key == "devDependencies":
                devDependencies_change = True

                # devDependency updates
                up_devDependencies_symbol = value[symbols.update] if symbols.update in value else {}
                if isinstance(up_devDependencies_symbol, dict) and len(up_devDependencies_symbol) > 0:
                    for key, key_value in up_devDependencies_symbol.items():
                        try: 
                            up_devDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")
                        
                # devDependency insertions
                de_devDependencies_symbol = value[symbols.delete] if symbols.delete in value else []
                if isinstance(de_devDependencies_symbol, list) and len(de_devDependencies_symbol) > 0:
                    de_devDependencies.extend(de_devDependencies_symbol)

                # devDependency deletions
                in_devDependencies_symbol = value[symbols.insert] if symbols.insert in value else {}
                if isinstance(in_devDependencies_symbol, dict) and len(in_devDependencies_symbol) > 0:
                    for key, key_value in in_devDependencies_symbol.items():
                        try:
                            in_devDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

            if key == "peerDependencies":
                peerDependencies_change = True

                # peerDependency updates
                up_peerDependencies_symbol = value[symbols.update] if symbols.update in value else {}
                if isinstance(up_peerDependencies_symbol, dict) and len(up_peerDependencies_symbol) > 0:
                    for key, key_value in up_peerDependencies_symbol.items():
                        try:
                            up_peerDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")
                
                # peerDependency insertions
                de_peerDependencies_symbol = value[symbols.delete] if symbols.delete in value else []
                if isinstance(de_peerDependencies_symbol, list) and len(de_peerDependencies_symbol) > 0:
                    de_peerDependencies.extend(de_peerDependencies_symbol)
                
                # peerDependency deletions
                in_peerDependencies_symbol = value[symbols.insert] if symbols.insert in value else {}
                if isinstance(in_peerDependencies_symbol, dict) and len(in_peerDependencies_symbol) > 0:
                    for key, key_value in in_peerDependencies_symbol.items():
                        try:
                            in_peerDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

            if key == "optionalDependencies":
                optionalDependencies_change = True

                # optionalDependency updates
                up_optionalDependencies_symbol = value[symbols.update] if symbols.update in value else {}
                if isinstance(up_optionalDependencies_symbol, dict) and len(up_optionalDependencies_symbol) > 0:
                    for key, key_value in up_optionalDependencies_symbol.items():
                        try:
                            up_optionalDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

                # optionalDependency insertions
                de_optionalDependencies_symbol = value[symbols.delete] if symbols.delete in value else []
                if isinstance(de_optionalDependencies_symbol, list) and len(de_optionalDependencies_symbol) > 0:
                    de_optionalDependencies.extend(de_optionalDependencies_symbol)

                # optionalDependency deletions
                in_optionalDependencies_symbol = value[symbols.insert] if symbols.insert in value else {}
                if isinstance(in_optionalDependencies_symbol, dict) and len(in_optionalDependencies_symbol) > 0:
                    for key, key_value in in_optionalDependencies_symbol.items():
                        try:
                            in_optionalDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")
            
            if key == "bundleDependencies":
                bundleDependencies_change = True
                if isinstance(value, bool):
                    up_bundleDependencies.append({key: value})
                    continue

                # bundleDependency updates
                up_bundleDependencies_symbol = value[symbols.update] if symbols.update in value else {}
                if isinstance(up_bundleDependencies_symbol, dict) and len(up_bundleDependencies_symbol) > 0:
                    for key, key_value in up_bundleDependencies_symbol.items():
                        try:
                            up_bundleDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

                # bundleDependency insertions
                de_bundleDependencies_symbol = value[symbols.delete] if symbols.delete in value else []
                if isinstance(de_bundleDependencies_symbol, list) and len(de_bundleDependencies_symbol) > 0:
                    de_bundleDependencies.extend(de_bundleDependencies_symbol)

                # bundleDependency deletions
                in_bundleDependencies_symbol = value[symbols.insert] if symbols.insert in value else {}
                if isinstance(in_bundleDependencies_symbol, dict) and len(in_bundleDependencies_symbol) > 0:
                    for key, key_value in in_bundleDependencies_symbol.items():
                        try:
                            in_bundleDependencies.append({key: key_value})
                        except:
                            print("TypeError: unhashable type: 'dict'")

            if key == "version":
                version_change = True
                updated_version = value

    if symbols.delete in diff_output:
        deleted_data = diff_output[symbols.delete] if symbols.delete in diff_output else {}
        print("deleted_data: ", deleted_data)
        for key in deleted_data:
            if key == "dependencies":
                dependencies_change = True
                remove_all_dependencies = True
            if key == "devDependencies":
                devDependencies_change = True
                remove_all_devDependencies = True
            if key == "peerDependencies":
                peerDependencies_change = True
                remove_all_peerDependencies = True
            if key == "optionalDependencies":
                optionalDependencies_change = True
                remove_all_optionalDependencies = True
            if key == "bundleDependencies":
                bundleDependencies_change = True
                remove_all_bundleDependencies = True
    
    if symbols.insert in diff_output:
        inserted_data = diff_output[symbols.insert] if symbols.insert in diff_output else {}
        print("inserted_data: ", inserted_data)
        for key in inserted_data:
            if key == "dependencies":
                dependencies_change = True
                in_dependencies.append(inserted_data[key])
                # print("in_dependencies: ", in_dependencies)
            if key == "devDependencies":
                devDependencies_change = True
                in_devDependencies.append(inserted_data[key])
            if key == "peerDependencies":
                peerDependencies_change = True
                in_peerDependencies.append(inserted_data[key])
            if key == "optionalDependencies":
                optionalDependencies_change = True
                in_optionalDependencies.append(inserted_data[key])
            if key == "bundleDependencies":
                bundleDependencies_change = True
                in_bundleDependencies.append(inserted_data[key])


    return updated_version, de_dependencies, in_dependencies, up_dependencies, de_devDependencies, in_devDependencies, up_devDependencies, de_peerDependencies, in_peerDependencies, up_peerDependencies, de_optionalDependencies, in_optionalDependencies, up_optionalDependencies, de_bundleDependencies, in_bundleDependencies, up_bundleDependencies, remove_all_dependencies, remove_all_devDependencies,remove_all_peerDependencies, remove_all_optionalDependencies, remove_all_bundleDependencies, dependencies_change, devDependencies_change, peerDependencies_change, optionalDependencies_change, bundleDependencies_change, version_change

def get_main_branch_och_star(item):
    url = f"https://api.github.com/repos/{item}"
    print("url", url)
    response = requests.get(url, headers=headers)

    # print(response)

    if response.status_code == 200:
        repo_info = response.json()
        return repo_info['default_branch']
    
    if response.status_code == 404 or response.status_code == 403:
        print(f"Repo not found: {item}")
        return ""
    else:
        return None

def main(suffix):
    REPOS_FILE, ANALYSIS_FILE, ERROR_FILE = set_filenames(suffix)
    # clear_file(DIFF_FILE)
    # clear_file(ANALYSIS_FILE)
    # clear_file(ERROR_FILE)
    # clear_file(ANALYSIS_EXTRA_FILE)
    # clear_file(COMMIT_FILE)


    with open(REPOS_FILE, "r") as f:
        repos = f.readlines()

    for repo in repos:
        repo_arr = repo.strip().split(",")
        repo = repo_arr[0]
        default_branch = get_main_branch_och_star(repo)

        if not repo_exists(repo):
            print(f"Repository {repo} does not exist. Skipping...")
            with open(ERROR_FILE, 'a') as ef:
                ef.write(f"{repo} does not exist.\n")
            continue
    
        if not is_package_json_included(repo, default_branch):
            print(f"Repository {repo} does not have a package.json file. Skipping...")
            with open(ERROR_FILE, 'a') as ef:
                ef.write(f"{repo} does not have a package.json file.\n")
            continue

        print(f"Start processing {repo}...")
        with open(ERROR_FILE, "a") as error_file:
            error_file.write(f"Start processing {repo}...\n")
            # commit_file.write(f"Start processing {repo}...\n")

        clone_and_analyze(repo, default_branch, ANALYSIS_FILE, ERROR_FILE)

    subprocess.run(["rm", "-rf", CLONE_DIR])
    print(f"Analysis saved to {ANALYSIS_FILE}")

if __name__ == "__main__":
    import sys
    main(sys.argv[1])
