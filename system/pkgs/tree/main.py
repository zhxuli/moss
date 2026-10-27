#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""目录树 —— 把一个目录按规则画成树，并印出来。

    moss :tree              当前目录
    moss :tree docs         只看 docs 子目录
    moss :tree docs 2       只看两层
    moss :tree -a           连隐藏文件一起显示
    moss :tree -venv,dist   额外忽略 venv 和 dist（内置已忽略 venv/.git/__pycache__ 等）

"""
import os
import sys
import fnmatch

# --- 配置区 ---
CONNECTORS = {
    'Tee': '├──',
    'Corner': '└──',
    'Line': '│ ',
    'Blank': ' '
}

# 默认忽略列表
DEFAULT_IGNORE_SET = {'venv', '.venv', '__pycache__', '.git', '.vscode', '.idea', 'node_modules', '.ds_store'}

# 单个目录最大显示条目数
MAX_FILES_PER_DIR = 100

def find_gitignore(start_path):
    current_path = os.path.abspath(start_path)
    while True:
        gitignore_path = os.path.join(current_path, '.gitignore')
        if os.path.isfile(gitignore_path):
            return gitignore_path
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return None

def parse_gitignore(file_path):
    rules = []
    if not file_path or not os.path.exists(file_path):
        return rules
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('!'):
                    continue
                
                is_root_only = line.startswith('/')
                if is_root_only:
                    line = line[1:]
                
                is_dir_only = line.endswith('/')
                if is_dir_only:
                    line = line[:-1]
                
                if line:
                    rules.append({
                        'pattern': line,
                        'is_dir_only': is_dir_only,
                        'is_root_only': is_root_only
                    })
    except Exception as e:
        pass 
    return rules

def should_ignore(name, path, gitignore_rules, custom_ignore_set, root_path, target_dir_name=None):
    name_lower = name.lower()
    
    # 核心保护：如果是目标目录，绝不忽略
    if target_dir_name and name_lower == target_dir_name.lower():
        return False

    if name_lower in DEFAULT_IGNORE_SET:
        return True
        
    if name_lower in custom_ignore_set:
        return True
        
    try:
        rel_path = os.path.relpath(path, root_path)
    except ValueError:
        rel_path = name
    is_root_item = (rel_path == name)

    for rule in gitignore_rules:
        pattern = rule['pattern']
        if rule['is_root_only'] and not is_root_item:
            continue
        matches = fnmatch.fnmatch(name_lower, pattern.lower())
        if rule['is_dir_only'] and os.path.isfile(path):
            continue
        if matches:
            return True
    return False

def build_tree(target_path, max_depth=-1, show_all=False, custom_ignore_set=None, target_dir_name=None):
    if custom_ignore_set is None:
        custom_ignore_set = set()

    gitignore_file = find_gitignore(target_path)
    gitignore_rules = parse_gitignore(gitignore_file)
    root_path = os.path.abspath(target_path)

    root_name = os.path.basename(root_path)
    print(f"{root_name}{os.sep}")
    
    _walk_directory(
        path=target_path,
        prefix="",
        max_depth=max_depth,
        show_all=show_all,
        level=0,
        custom_ignore_set=custom_ignore_set,
        gitignore_rules=gitignore_rules,
        root_path=root_path,
        target_dir_name=target_dir_name
    )

def _walk_directory(path, prefix, max_depth, show_all, level, custom_ignore_set, gitignore_rules, root_path, target_dir_name):
    if max_depth != -1 and level >= max_depth:
        return

    dir_name = os.path.basename(path)
    
    if level > 0:
        if should_ignore(dir_name, path, gitignore_rules, custom_ignore_set, root_path, target_dir_name):
            return

    hide_file_path = os.path.join(path, '.hide')
    has_hide_marker = os.path.isfile(hide_file_path)

    if has_hide_marker or 'hide' in dir_name.lower():
        return

    try:
        entries = os.listdir(path)
    except (PermissionError, OSError):
        return

    filtered_entries = []
    for entry in entries:
        entry_path = os.path.join(path, entry)
        
        if should_ignore(entry, entry_path, gitignore_rules, custom_ignore_set, root_path, target_dir_name):
            continue
            
        if not show_all and _is_hidden(entry_path):
            continue
            
        filtered_entries.append(entry)

    filtered_entries.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))

    if len(filtered_entries) > MAX_FILES_PER_DIR:
        print(f"{prefix}{CONNECTORS['Tee']} ... (Skipped large directory: {len(filtered_entries)} items)")
        return

    entry_count = len(filtered_entries)
    for i, entry in enumerate(filtered_entries):
        connector = CONNECTORS['Tee'] if i < entry_count - 1 else CONNECTORS['Corner']
        entry_path = os.path.join(path, entry)
        
        print(f"{prefix}{connector} {entry}")
        
        if os.path.isdir(entry_path):
            extension = CONNECTORS['Line'] if i < entry_count - 1 else CONNECTORS['Blank']
            _walk_directory(
                path=entry_path,
                prefix=prefix + extension,
                max_depth=max_depth,
                show_all=show_all,
                level=level + 1,
                custom_ignore_set=custom_ignore_set,
                gitignore_rules=gitignore_rules,
                root_path=root_path,
                target_dir_name=target_dir_name
            )

def _is_hidden(filepath):
    name = os.path.basename(filepath)
    if name.startswith('.'):
        return True
    if sys.platform == "win32":
        try:
            import stat
            return name.startswith('$') or name.endswith('~')
        except:
            return False
    return False

def _split_args(s):
    r"""按空白拆参数，但**不碰反斜杠**。

    为什么不直接用 shlex：Windows 路径里的 `\` 会被 shlex 当转义吃掉
    （旧项目 core.py 里就为此专门写过自己的 split_args，见 `E-06`）。
    引号包起来的部分保持成一个参数（带空格的路径用得上）。
    """
    out, cur, quote = [], "", None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "\"'":
            quote = ch
        elif ch.isspace():
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _moss_args():
    """从宿主拿参数；拿不到返回 None（调用方退回 sys.argv）。

    宿主把参数放在 `MOSS_PKG_PARAMS`（JSON，键是 pkg.json 里声明的参数名）。
    本包的 `args` 声明成
    `rest: true`，意思是"包名后面的词全归我、我自己解析" —— 所以这里原样拆开
    再走下面那套老的解析逻辑（数字=深度、-a=显示隐藏、-xxx=额外忽略、其它=目标目录）。
    """
    import json as _json
    import os as _os

    raw = _os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            p = _json.loads(raw) or {}
            if p.get("args"):
                return _split_args(str(p["args"]))
        except Exception:
            pass
    return None


def main():
    # --- 参数解析逻辑 (已修复) ---
    max_depth = -1
    show_all = False
    custom_ignore_set = set()
    target_subdir = None

    # 获取所有参数；宿主没给就退回 sys.argv，直接调试仍可用。
    args = _moss_args()
    if args is None:
        args = sys.argv[1:]
    
    # --- 调试信息 ---
    # print(f"[DEBUG] 接收到的参数: {args}")<websource>source_group_web_1</websource> 

    for arg in args:
        # 处理深度参数
        if arg.isdigit():
            max_depth = int(arg)
            continue
        
        # 处理显示隐藏文件
        if arg in ['-a', '--all']:
            show_all = True
            continue
        
        # 判断是“目标”还是“过滤”
        if arg.startswith('-'):
            items = arg[1:]
            if items:
                custom_ignore_set.update(item.strip().lower() for item in items.split(',') if item.strip())
        else:
            # 不带 '-' 的参数，视为目标子目录
            target_subdir = arg

    # 确定最终路径
    base_path = os.getcwd()
    
    if target_subdir:
        final_path = os.path.join(base_path, target_subdir)
        if not os.path.isdir(final_path):
            print(f"[错误] 找不到指定的目录: {final_path}", file=sys.stderr)
            return
    else:
        final_path = base_path

    build_tree(final_path, max_depth, show_all, custom_ignore_set, target_subdir)

if __name__ == "__main__":
    if sys.platform == "win32":
        os.system("chcp 65001 > nul")
    main()