import os
import sys
import json
import subprocess
import questionary

if '__file__' in globals():
    PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    PLUGIN_DIR = sys.path[0] if sys.path else os.getcwd()

DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.environ.get('PA_PLUGIN_DATA_DIR')
            or os.path.join(os.environ.get("MOSS_HOME") or os.path.expanduser("~"),
              "user_data", "state", "mark"))

DATA_FILE = os.path.join(DATA_DIR, 'directories.json')

def _split_args(s):
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
    raw = _os.environ.get("MOSS_ARGS")
    if raw:
        return _split_args(raw)
    return None

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_data(data):
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def switch_directory(path):
    if not os.path.exists(path):
        print(f"错误: 路径 '{path}' 不存在。")
        return

    try:
        os.chdir(path)
        print(f"\n已切换到目录: {path}")
        print("提示: 正在当前路径启动新的 Shell 会话，输入 'exit' 可返回上一层环境。\n")

        if os.name == 'nt':
            shell = os.environ.get('COMSPEC', 'cmd.exe')
        else:
            shell = os.environ.get('SHELL', 'bash')

        subprocess.call(shell)
    except PermissionError:
        print(f"错误: 权限不足，无法访问 '{path}'。")
    except Exception as e:
        print(f"切换目录时出错: {e}")

def run_gui():
    import tkinter as tk
    from tkinter import messagebox

    data = load_data()

    def on_select(event):
        selection = listbox.curselection()
        if selection:
            idx = selection[0]
            item = data[idx]
            entry_title.delete(0, tk.END)
            entry_title.insert(0, item.get('title', ''))
            entry_path.delete(0, tk.END)
            entry_path.insert(0, item.get('path', ''))

    def save_item():
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先在左侧选择要修改的目录。")
            return

        idx = selection[0]
        new_title = entry_title.get().strip()
        new_path = entry_path.get().strip()

        if not new_title or not new_path:
            messagebox.showwarning("警告", "标题和路径不能为空。")
            return

        data[idx]['title'] = new_title
        data[idx]['path'] = new_path
        save_data(data)
        refresh_list()
        listbox.selection_set(idx)
        messagebox.showinfo("成功", "信息已保存！")

    def delete_item():
        selection = listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if messagebox.askyesno("确认", f"确定要删除书签 '{data[idx]['title']}' 吗？"):
            del data[idx]
            save_data(data)
            entry_title.delete(0, tk.END)
            entry_path.delete(0, tk.END)
            refresh_list()

    def refresh_list():
        listbox.delete(0, tk.END)
        for item in data:
            listbox.insert(tk.END, item.get('title', '未命名'))

    root = tk.Tk()
    root.title("目录书签管理")
    root.geometry("500x300")

    root.eval('tk::PlaceWindow . center')

    frame_left = tk.Frame(root)
    frame_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    listbox = tk.Listbox(frame_left, font=('Microsoft YaHei', 10))
    listbox.pack(fill=tk.BOTH, expand=True)
    listbox.bind('<<ListboxSelect>>', on_select)

    frame_right = tk.Frame(root)
    frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    tk.Label(frame_right, text="标题:").pack(anchor=tk.W)
    entry_title = tk.Entry(frame_right, font=('Microsoft YaHei', 10))
    entry_title.pack(fill=tk.X, pady=(0, 15))

    tk.Label(frame_right, text="路径:").pack(anchor=tk.W)
    entry_path = tk.Entry(frame_right, font=('Microsoft YaHei', 10))
    entry_path.pack(fill=tk.X, pady=(0, 20))

    btn_frame = tk.Frame(frame_right)
    btn_frame.pack(fill=tk.X)

    tk.Button(btn_frame, text="保存修改", command=save_item, bg="#4CAF50", fg="white").pack(side=tk.LEFT, expand=True,
                                                                                            fill=tk.X, padx=(0, 5))
    tk.Button(btn_frame, text="删除选中", command=delete_item, bg="#f44336", fg="white").pack(side=tk.RIGHT,
                                                                                              expand=True, fill=tk.X,
                                                                                              padx=(5, 0))

    refresh_list()
    root.mainloop()

def main():
    data = load_data()

    query_args = _moss_args()
    if query_args is None:
        query_args = [a for a in sys.argv[1:] if a not in ('-c', '')]

    first_arg = query_args[0].lower() if query_args else None

    if first_arg in ['--gui', '-g', 'gui']:
        run_gui()
        return

    if first_arg in ['list', 'ls', 'all']:
        if not data:
            print("当前没有记录任何目录。")
        else:
            print("\n已保存的目录清单:")
            print("-" * 50)
            max_title_len = max([len(item['title']) for item in data] + [4])
            for i, item in enumerate(data, 1):
                print(f" {i:02d}. {item['title']:<{max_title_len}} │ {item['path']}")
            print("-" * 50)
        return

    if not first_arg:
        cwd = os.getcwd()
        print(f"当前路径: {cwd}")

        existing_record = next((item for item in data if item['path'] == cwd), None)

        if existing_record:
            print(f"记录状态: 已记录 (标题: {existing_record['title']})")
            if questionary.confirm("当前目录已被记录，是否要将其从记录中移除？", default=False).ask():
                data = [item for item in data if item['path'] != cwd]
                save_data(data)
                print("已取消记录。")
        else:
            print("记录状态: 未记录")
            default_title = os.path.basename(cwd) or cwd

            answer = questionary.text(
                f"请输入书签标题 (直接回车默认使用 '{default_title}', 按 Ctrl+C 取消):"
            ).ask()

            if answer is None:
                print("已取消操作。")
                return

            title = answer.strip() if answer.strip() else default_title
            data.append({"title": title, "path": cwd})
            save_data(data)
            print(f"记录成功！标题被命名为: {title}")
            print(f"数据已保存至: {DATA_FILE}")
        return

    query = first_arg.strip().lower()

    exact_matches = [item for item in data if query == item['title'].lower() or query == item['path'].lower()]
    if exact_matches:
        switch_directory(exact_matches[0]['path'])
        return

    fuzzy_matches = [
        item for item in data
        if query in item['title'].lower() or query in item['path'].lower()
    ]

    if not fuzzy_matches:
        print(f"未找到与 '{query}' 相关的目录记录。")
        return

    if len(fuzzy_matches) == 1:
        print(f"找到唯一模糊匹配: {fuzzy_matches[0]['title']} -> {fuzzy_matches[0]['path']}")
        switch_directory(fuzzy_matches[0]['path'])
        return

    choices = []
    max_title_len = max([len(item['title']) for item in fuzzy_matches] + [10])

    for item in fuzzy_matches:
        title = item['title']
        path = item['path']
        display_text = f"{title:<{max_title_len}} │ {path}"
        choices.append(questionary.Choice(display_text, value=path))

    choices.extend([
        questionary.Separator("─" * (max_title_len + 40)),
        questionary.Choice("取消操作", value="CANCEL")
    ])

    choice = questionary.select(
        f"找到多个与 '{query}' 相关的目录，请选择:",
        choices=choices,
        instruction="(↑/↓ 移动, Enter 确认)"
    ).ask()

    if not choice or choice == "CANCEL":
        print("已取消。")
        return

    switch_directory(choice)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已强制取消。")
