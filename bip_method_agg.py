import ast
import os
import json
import re
from collections import defaultdict

BIP_DIR = '.'
PROJ_DIR = './backup/projects/'
TEST_FILE = 'coverage_bugsinpy.txt'
DATA_DIR = './xfl_auth_data/'

def get_changed_info(bug_name):
    project, bug_id = bug_name.split('_')
    with open(f'{BIP_DIR}/projects/{project}/bugs/{bug_id}/bug_patch.txt') as f:
        diff_lines = f.readlines()
    change_locs = dict()
    change_file = None
    change_lines_cache = []
        
    for line in diff_lines:
        if line.startswith('--- a/'):
            if change_file is not None:
                change_locs[change_file] = change_lines_cache
            change_file = line.removeprefix('--- a/').strip()
            change_lines_cache = []
        elif line.startswith('@@ -'):
            change_line = int(line.split(',')[0].removeprefix('@@ -'))+3
            change_lines_cache.append(change_line)
    if change_file is not None:
        change_locs[change_file] = change_lines_cache
        
    return change_locs

def get_susp_info(suspiciousness_file, fix_locs):
    method2susp = dict()
    with open(suspiciousness_file) as f:
        susp_obj = json.load(f) # file -> line -> susps
    
    all_file_names = set(susp_obj.keys())
    for file_name in all_file_names:
        org_file_name = file_name
        if 'ansible' in bug_name:
            file_name = file_name.replace('build/lib/', 'lib/')
        elif 'matplotlib' in bug_name:
            file_name = re.sub(r'matplotlib/env/lib/python3.\d+/site-packages/', 'lib/', file_name)
            file_name = re.sub('env/lib/python3.\d+/site-packages/', 'lib/', file_name)
            #file_name.replace('matplotlib/env/lib/python3.8/site-packages/', 'lib/')
        elif 'youtube' in bug_name:
            file_name = file_name.replace('youtube-dl/youtube_dl/', 'youtube_dl/')
        
        if not os.path.isfile(os.path.join(PROJ_DIR, bug_name, file_name)):
            print(f'{os.path.join(PROJ_DIR, bug_name, file_name)} does not exist!')
            continue
        
        with open(os.path.join(PROJ_DIR, bug_name, file_name)) as f:
            file_code = f.read()
            try:
                root_ast = ast.parse(file_code)
            except:
                print(f"{file_name} could not be parsed!")
                continue
            func_nodes = [e for e in ast.walk(root_ast) if isinstance(e, ast.FunctionDef)]
            class_nodes = [e for e in ast.walk(root_ast) if isinstance(e, ast.ClassDef)]
        
        for covered_line in map(int, susp_obj[org_file_name]):
            encasing_functions = [e for e in func_nodes if e.lineno <= covered_line <= e.end_lineno]
            encasing_classes = [e for e in class_nodes if e.lineno <= covered_line <= e.end_lineno]
            if len(encasing_functions) == 0:
                continue
            innermost_func = list(sorted(encasing_functions, key=lambda x: x.end_lineno - x.lineno))[0]
            if len(encasing_classes) == 0:
                innermost_classname = ""
            else:
                innermost_classname = list(sorted(encasing_classes, key=lambda x: x.end_lineno - x.lineno))[0].name
            
            # detailed_info
            pseudo_classname = file_name.removesuffix('.py').replace('/', '.')
            pseudo_classname += '.'+innermost_classname if len(innermost_classname) > 0 else ''
            method_id = pseudo_classname + '.' + innermost_func.name + '#' + str(innermost_func.lineno)
            func_cont = '\n'.join(file_code.split('\n')[innermost_func.lineno-1:innermost_func.end_lineno])
            is_bug = ((file_name in fix_locs) and 
                      any(innermost_func.lineno <= l <= innermost_func.end_lineno for l in fix_locs[file_name]))
            signature = method_id.split('#')[0]+'('+ast.unparse(innermost_func.args)+')'
            
            if signature in method2susp:
                for key in filter(lambda x: 'pseudo' in x, method2susp[signature].keys()):
                    method2susp[signature][key] = max(
                        method2susp[signature][key],
                        susp_obj[org_file_name][str(covered_line)][key]
                    )
            else:
                method2susp[signature] = susp_obj[org_file_name][str(covered_line)]
    return method2susp

if __name__ == '__main__':
    for bug_name in sorted(os.listdir(PROJ_DIR)):
        print(bug_name)
        fail_test_str = None
        seen_methods = set()
        prod_snippets = []
        test_snippets = []
        fix_locs = get_changed_info(bug_name)

        # get covered method snippets
        bug_dir = os.path.join(PROJ_DIR, bug_name)
        
        auth_susp_fname = f'./authoritative_suspiciousness/{bug_name}_scores.json'
        prod_susp_dict = get_susp_info(auth_susp_fname, fix_locs)

        if len(prod_susp_dict) == 0:
            print(bug_name, 'missing coverage info!')
            continue

        # save gathered information
        save_dir = os.path.join(DATA_DIR, bug_name)
        if not os.path.isfile(os.path.join(save_dir, 'snippet.json')):
            print('WARNING: no snippet file detected for', bug_name)
            continue
        with open(os.path.join(save_dir, 'snippet.json')) as f:
            init_snip_objs = json.load(f)
        new_snip_objs = []
        for snip_dict in init_snip_objs:
            new_snip_dict = snip_dict
            new_snip_dict['susp'] = prod_susp_dict[snip_dict['signature']]
            new_snip_objs.append(new_snip_dict)
        with open(os.path.join(save_dir, 'snippet.json'), 'w') as f:
            json.dump(new_snip_objs, f, indent=4)

    print('a-ok')
