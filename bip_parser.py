import ast
import os
import json
import re

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

def get_test_run_info(bug_name):
    # get failing test information
    with open(os.path.join(PROJ_DIR, bug_name, TEST_FILE)) as f:
        raw_fail_test_info = f.read()
        test_fragments = ['coverage run' + e.split('\nCoverage Report\n')[0]
                          for e in raw_fail_test_info.split('coverage run')[1:]]
        fail_test_str = '\n'.join(test_fragments)
    
    need_to_gather_test_files = []
    for line in fail_test_str.splitlines():
        if 'coverage run' in line:
            if 'pytest' in line:
                file_name = line.split()[-1].split('::')[0]
                need_to_gather_test_files.append(file_name)
            elif 'unittest' in line:
                file_cand_1 = '/'.join(line.split()[-1].split('.')[:-2])+'.py'
                file_cand_2 = '/'.join(line.split()[-1].split('.')[:-1])+'.py'
                need_to_gather_test_files += [file_cand_1, file_cand_2]
    need_to_gather_test_files = filter(lambda x: os.path.isfile(os.path.join(PROJ_DIR, bug_name, x)),
                                       need_to_gather_test_files)
    need_to_gather_test_files = list(need_to_gather_test_files)
    return fail_test_str, need_to_gather_test_files

def get_coverage_info(coverage_file, seen_methods, need_to_gather_test_files):
    test_snippets, prod_snippets = [], []
    with open(coverage_file) as f:
        coverage_obj = json.load(f)
    
    all_file_names = set(coverage_obj['files'].keys()) | set(need_to_gather_test_files)
    for file_name in all_file_names:
        if file_name in coverage_obj['files']:
            exec_lines = coverage_obj['files'][file_name]['executed_lines']
            if coverage_obj['files'][file_name]['summary']['num_statements'] == 0:
                continue
        else:
            exec_lines = range(1000000) # hack to get all test methods of test file

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
        
        for covered_line in exec_lines:
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
            if method_id not in seen_methods:
                seen_methods.add(method_id)
                snippet_obj = {
                    'name': method_id,
                    'src_path': file_name,
                    'class_name': pseudo_classname,
                    'signature': method_id.split('#')[0]+'('+ast.unparse(innermost_func.args)+')',
                    'snippet': func_cont,
                    'begin_line': innermost_func.lineno,
                    'end_line': innermost_func.end_lineno,
                    'comment': '',
                    'is_bug': is_bug,
                }
                if 'test/' in file_name or 'tests/' in file_name:
                    test_snippets.append(snippet_obj)
                else:
                    prod_snippets.append(snippet_obj)
    return prod_snippets, test_snippets, seen_methods

if __name__ == '__main__':
    for bug_name in sorted(os.listdir(PROJ_DIR)):
        print(bug_name)
        fail_test_str = None
        seen_methods = set()
        prod_snippets = []
        test_snippets = []
        fix_locs = get_changed_info(bug_name)

        # TODO
        try:
            fail_test_str, need_to_gather_test_files = get_test_run_info(bug_name)
        except Exception as e:
            print(f'{bug_name} does not have a test run log!')
            continue
        if len(need_to_gather_test_files) == 0:
            print('WARNING: test file to gather test snippets from was not detected.')

        # get covered method snippets
        bug_dir = os.path.join(PROJ_DIR, bug_name)
#         for coverage_fname in filter(lambda x: x.endswith('.json') and x.startswith('coverage_'),
#                                      os.listdir(bug_dir)):
        
        auth_coverage_fname = f'./authoritative_coverage/{bug_name}_coverage.json'
        test_prod_snips, test_test_snips, test_seen_methods = \
            get_coverage_info(auth_coverage_fname, seen_methods, need_to_gather_test_files)
        prod_snippets += test_prod_snips
        test_snippets += test_test_snips
        seen_methods |= test_seen_methods

        if len(seen_methods) == 0:
            print(bug_name, 'missing coverage info!')
            continue

        # save gathered information
        save_dir = os.path.join(DATA_DIR, bug_name)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        with open(os.path.join(save_dir, 'snippet.json'), 'w') as f:
            json.dump(prod_snippets, f, indent=4)
        with open(os.path.join(save_dir, 'field_snippet.json'), 'w') as f:
            json.dump({}, f, indent=4)
        with open(os.path.join(save_dir, 'test_snippet.json'), 'w') as f:
            json.dump(test_snippets, f, indent=4)
        with open(os.path.join(save_dir, 'failing_tests'), 'w') as f:
            f.write(fail_test_str)

    print('a-ok')
