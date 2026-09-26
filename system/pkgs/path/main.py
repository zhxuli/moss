import os
import sys
import ctypes
import winreg
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime
# python -m nuitka --onefile --lto=yes --plugin-enable=tk-inter --windows-disable-console --remove-output --windows-icon-from-ico=icon.ico -o path main.py
# 依赖检查和颜色配置等所有类定义都保持不变
try:
    import windnd
except ImportError:
    messagebox.showerror("依赖缺失", "错误: 缺少 'windnd' 库。\n请在命令行中运行: pip install windnd")
    sys.exit(1)

COLORS = {
    "bg": "#2E3440", "fg": "#ECEFF4", "frame_bg": "#3B4252",
    "list_bg": "#3B4252", "list_select_bg": "#88C0D0", "list_select_fg": "#2E3440",
    "button_bg": "#5E81AC", "button_fg": "#ECEFF4", "success_bg": "#A3BE8C",
    "success_fg": "#2E3440", "status_bg": "#434C5E", "disabled_fg": "#4C566A",
    "tree_heading_bg": "#4C566A", "warning_fg": "#EBCB8B"
}
application_path = os.path.dirname(sys.executable) if 'python' not in os.path.basename(sys.executable).lower() else os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.path.abspath(sys.path[0])
# 宿主 moss 注入的插件专属数据目录 (user_data/<插件目录名>)；独立运行时退回插件目录
DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.environ.get('PA_PLUGIN_DATA_DIR') or application_path
class BackupManager:
    def __init__(self):
        self.backup_dir = Path(DATA_DIR) / ".path_editor" / "path_bak"
        self.backup_prefix = "path_backup_"
        self.time_format = "%Y%m%d_%H%M%S"
    def create_backup(self, paths: list[str]) -> tuple[bool, str]:
        timestamp = datetime.now().strftime(self.time_format)
        backup_file = self.backup_dir / f"{self.backup_prefix}{timestamp}.txt"
        try:
            # 懒加载：只有真正备份时才创建数据目录
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            with open(backup_file, 'w', encoding='utf-8') as f:
                for path in paths:
                    f.write(f"{path}\n")
            return True, f"成功备份到: {backup_file}"
        except IOError as e:
            return False, f"备份失败: {e}"
    def get_paths_from_backup(self, backup_filepath: str) -> list[str]:
        try:
            with open(backup_filepath, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            return []
    def list_backups(self, current_system_paths: list[str]) -> list[dict]:
        backups = []
        current_set = {os.path.normpath(p).lower() for p in current_system_paths}
        for f in self.backup_dir.glob(f"{self.backup_prefix}*.txt"):
            try:
                timestamp_str = f.stem.replace(self.backup_prefix, '')
                backup_time = datetime.strptime(timestamp_str, self.time_format)
                backup_paths = self.get_paths_from_backup(str(f))
                backup_set = {os.path.normpath(p).lower() for p in backup_paths}
                added_count = len(backup_set - current_set)
                removed_count = len(current_set - backup_set)
                backups.append({
                    "path": str(f),
                    "time": backup_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_count": len(backup_paths),
                    "added_count": added_count,
                    "removed_count": removed_count
                })
            except (ValueError, IndexError):
                continue
        return sorted(backups, key=lambda x: x['time'], reverse=True)

class PathManager:
    ENV_REG_KEY = winreg.HKEY_CURRENT_USER
    ENV_REG_SUBKEY = 'Environment'
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    def _broadcast_change(self):
        ctypes.windll.user32.SendNotifyMessageW(
            self.HWND_BROADCAST, self.WM_SETTINGCHANGE, 0,
            ctypes.c_wchar_p('Environment')
        )
    def get_user_path_list(self) -> list[str]:
        try:
            with winreg.OpenKey(self.ENV_REG_KEY, self.ENV_REG_SUBKEY) as key:
                path_str, _ = winreg.QueryValueEx(key, 'Path')
            return [p.strip() for p in path_str.split(';') if p.strip()]
        except FileNotFoundError:
            return []
    def is_path_registered(self, dir_to_check: str) -> bool:
        normalized_dir = os.path.normpath(dir_to_check).lower()
        return any(os.path.normpath(p).lower() == normalized_dir for p in self.get_user_path_list())
    def add_path_and_broadcast(self, dir_to_add: str) -> tuple[bool, str]:
        normalized_dir = os.path.normpath(dir_to_add)
        if self.is_path_registered(normalized_dir):
            return False, f"路径 '{normalized_dir}' 已存在。"
        current_paths = self.get_user_path_list()
        new_paths = list(dict.fromkeys(current_paths))
        new_paths.append(normalized_dir)
        return self.set_new_path_and_broadcast(new_paths, f"成功注册路径: {normalized_dir}")
    def remove_path_and_broadcast(self, dir_to_remove: str) -> tuple[bool, str]:
        normalized_dir_lower = os.path.normpath(dir_to_remove).lower()
        current_paths = self.get_user_path_list()
        new_paths = [p for p in current_paths if os.path.normpath(p).lower() != normalized_dir_lower]
        if len(new_paths) == len(current_paths):
            return False, f"路径 '{os.path.normpath(dir_to_remove)}' 未在PATH中找到。"
        return self.set_new_path_and_broadcast(new_paths, f"成功反注册路径: {os.path.normpath(dir_to_remove)}")
    def set_new_path_and_broadcast(self, new_paths: list[str], success_message: str) -> tuple[bool, str]:
        new_path_str = ';'.join(new_paths)
        try:
            with winreg.OpenKey(self.ENV_REG_KEY, self.ENV_REG_SUBKEY, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, new_path_str)
            self._broadcast_change()
            return True, success_message
        except Exception as e:
            return False, f"修改注册表失败: {e}"

# --- 恢复窗口 (已修改) ---
class RestoreWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.transient(parent)
        self.grab_set()
        self.title("从备份恢复PATH")
        self.geometry("750x600")
        self.configure(bg=COLORS["bg"])
        self._center_window()
        self.selected_backup = None
        self.paths_to_add = []
        self.paths_to_remove = []
        self.full_backup_paths = []
        self._setup_styles()
        self._create_step1_widgets()
        self._create_step2_widgets()
        self.show_step1()
    def _center_window(self):
        self.update_idletasks()
        parent_x, parent_y = self.parent.winfo_x(), self.parent.winfo_y()
        parent_w, parent_h = self.parent.winfo_width(), self.parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = parent_x + (parent_w // 2) - (w // 2)
        y = parent_y + (parent_h // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")
    def _setup_styles(self):
        style = ttk.Style(self); style.configure("Restore.TLabel", background=COLORS["bg"], foreground=COLORS["fg"], padding=5)
        style.configure("Treeview", background=COLORS["list_bg"], foreground=COLORS["fg"], fieldbackground=COLORS["list_bg"], rowheight=25)
        style.map("Treeview", background=[('selected', COLORS["list_select_bg"])], foreground=[('selected', COLORS["list_select_fg"])])
        style.configure("Treeview.Heading", background=COLORS["tree_heading_bg"], foreground=COLORS["fg"], padding=5, font=('Segoe UI', 10, 'bold'))
        style.configure("Custom.TPanedwindow", background=COLORS["bg"]); style.configure("Custom.TPanedwindow.Sash", background=COLORS["frame_bg"], sashthickness=2, relief=tk.FLAT, borderwidth=0)
    def _create_step1_widgets(self):
        self.step1_frame = ttk.Frame(self, padding=10)
        ttk.Label(self.step1_frame, text="步骤 1: 选择一个备份文件", style="Restore.TLabel", font=('Segoe UI', 12, 'bold')).pack(fill=tk.X)
        ttk.Label(self.step1_frame, text="列表显示了每个备份与当前系统PATH对比的变化。", style="Restore.TLabel").pack(fill=tk.X, pady=(0, 10))
        tree_frame = ttk.Frame(self.step1_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("备份时间", "总条数", "将新增", "将移除")
        self.backup_tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols: self.backup_tree.heading(col, text=col)
        self.backup_tree.column("备份时间", width=160, anchor=tk.W); self.backup_tree.column("总条数", width=80, anchor=tk.CENTER); self.backup_tree.column("将新增", width=80, anchor=tk.CENTER); self.backup_tree.column("将移除", width=80, anchor=tk.CENTER)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=scrollbar.set)
        self.backup_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.backup_tree.bind("<<TreeviewSelect>>", self._on_backup_select)
        
        btn_frame = ttk.Frame(self.step1_frame, padding=(0, 10))
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 按钮从右向左放置
        self.btn_next = ttk.Button(btn_frame, text="下一步", state=tk.DISABLED, command=self.go_to_step2)
        self.btn_next.pack(side=tk.RIGHT)
        
        # **新增**: 删除备份按钮
        self.btn_delete = ttk.Button(btn_frame, text="删除所选", state=tk.DISABLED, command=self.delete_selected_backup)
        self.btn_delete.pack(side=tk.RIGHT, padx=5)

        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=5)
    def _create_step2_widgets(self):
        self.step2_frame = ttk.Frame(self, padding=10)
        ttk.Label(self.step2_frame, text="步骤 2: 确认变更内容", style="Restore.TLabel", font=('Segoe UI', 12, 'bold')).pack(fill=tk.X, pady=(0, 10))
        self.paned_window = ttk.PanedWindow(self.step2_frame, orient=tk.HORIZONTAL, style="Custom.TPanedwindow")
        self.paned_window.pack(fill=tk.BOTH, expand=True)
        add_frame = ttk.Frame(self.paned_window, padding=5); ttk.Label(add_frame, text="将新增的路径:", style="Restore.TLabel").pack(anchor='w')
        self.add_listbox = tk.Listbox(add_frame, bg=COLORS["list_bg"], fg=COLORS["fg"], selectbackground=COLORS["list_select_bg"], selectforeground=COLORS["list_select_fg"], borderwidth=0, highlightthickness=0)
        self.add_listbox.pack(fill=tk.BOTH, expand=True); self.paned_window.add(add_frame, weight=1)
        remove_frame = ttk.Frame(self.paned_window, padding=5); ttk.Label(remove_frame, text="将移除的路径:", style="Restore.TLabel").pack(anchor='w')
        self.remove_listbox = tk.Listbox(remove_frame, bg=COLORS["list_bg"], fg=COLORS["fg"], selectbackground=COLORS["list_select_bg"], selectforeground=COLORS["list_select_fg"], borderwidth=0, highlightthickness=0)
        self.remove_listbox.pack(fill=tk.BOTH, expand=True); self.paned_window.add(remove_frame, weight=1)
        btn_frame = ttk.Frame(self.step2_frame, padding=(0, 10)); btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.btn_apply = ttk.Button(btn_frame, text="确认恢复", style="Success.TButton", command=self.apply_restore)
        self.btn_apply.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="返回上一步", command=self.show_step1).pack(side=tk.RIGHT, padx=5)
    def go_to_step2(self):
        backup_paths = self.parent.backup_manager.get_paths_from_backup(self.selected_backup['path']); current_paths = self.parent.path_manager.get_user_path_list(); backup_set = {os.path.normpath(p).lower() for p in backup_paths}; current_set = {os.path.normpath(p).lower() for p in current_paths}
        self.paths_to_add = [p for p in backup_paths if os.path.normpath(p).lower() not in current_set]; self.paths_to_remove = [p for p in current_paths if os.path.normpath(p).lower() not in backup_set]
        self.full_backup_paths = backup_paths; self.add_listbox.delete(0, tk.END); self.remove_listbox.delete(0, tk.END)
        for p in self.paths_to_add: self.add_listbox.insert(tk.END, p)
        for p in self.paths_to_remove: self.remove_listbox.insert(tk.END, p)
        self.step1_frame.pack_forget(); self.step2_frame.pack(fill=tk.BOTH, expand=True); self.update_idletasks()
        try: width = self.paned_window.winfo_width(); self.paned_window.sashpos(0, width // 2)
        except tk.TclError: pass
    def show_step1(self):
        self.step2_frame.pack_forget()
        self.step1_frame.pack(fill=tk.BOTH, expand=True)
        self.load_backup_list()
    def apply_restore(self):
        if messagebox.askyesno("最后确认", "确定要用此备份覆盖当前的系统PATH吗？此操作不可撤销。", icon='warning', parent=self): self.destroy(); self.parent.perform_action(self.parent.path_manager.set_new_path_and_broadcast, self.full_backup_paths, "PATH已成功从备份恢复。", op_desc="正在从备份恢复系统PATH...")
    def load_backup_list(self):
        for item in self.backup_tree.get_children(): self.backup_tree.delete(item)
        current_paths = self.parent.path_manager.get_user_path_list()
        backups = self.parent.backup_manager.list_backups(current_paths)
        if not backups:
            self.backup_tree.insert('', 'end', values=("没有找到任何备份文件。", "", "", ""))
            self.btn_next.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED) # 同时禁用删除按钮
            return
        for backup in backups:
            self.backup_tree.insert('', 'end', values=(backup['time'], backup['total_count'], f"+{backup['added_count']}", f"-{backup['removed_count']}"), iid=backup['path'])
    
    # **新增**: 删除选中备份的逻辑
    def delete_selected_backup(self):
        if not self.selected_backup or not self.selected_backup.get('path'):
            return
        
        backup_path = self.selected_backup['path']
        backup_filename = Path(backup_path).name

        if messagebox.askyesno("确认删除", f"确定要永久删除此备份吗？\n\n文件: {backup_filename}", icon='warning', parent=self):
            try:
                os.remove(backup_path)
                messagebox.showinfo("删除成功", f"备份 '{backup_filename}' 已被删除。", parent=self)
                # 刷新列表
                self.load_backup_list()
            except OSError as e:
                messagebox.showerror("删除失败", f"无法删除文件: {e}", parent=self)

    # **修改**: _on_backup_select 现在也控制删除按钮的状态
    def _on_backup_select(self, event):
        selected_item = self.backup_tree.selection()
        if selected_item:
            path = selected_item[0]
            if Path(path).exists():
                self.selected_backup = {"path": path}
                self.btn_next.config(state=tk.NORMAL)
                self.btn_delete.config(state=tk.NORMAL)
            else:
                self.selected_backup = None
                self.btn_next.config(state=tk.DISABLED)
                self.btn_delete.config(state=tk.DISABLED)
        else:
            self.selected_backup = None
            self.btn_next.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)

# --- PathEditorApp 和其他函数 (无任何修改) ---
class PathEditorApp(tk.Tk):
    def __init__(self, script_dir: str):
        super().__init__(); self.script_dir = script_dir; self.normalized_script_dir = os.path.normpath(self.script_dir).lower()
        self.path_manager = PathManager(); self.backup_manager = BackupManager(); self.controls = []; self.path_count_var = tk.StringVar(); self.reg_status_var = tk.StringVar()
        self.title(f"Path 环境编辑器 - [{self.script_dir}]"); self.geometry("650x800"); self.minsize(600, 500); self.configure(bg=COLORS["bg"])
        self._setup_styles(); self._create_widgets(); self.populate_path_list(); windnd.hook_dropfiles(self, func=self.handle_drop)
    def _setup_styles(self):
        style = ttk.Style(self); style.theme_use('clam'); style.configure("TFrame", background=COLORS["bg"]); style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"], padding=5)
        style.configure("Count.TLabel", background=COLORS["bg"], foreground=COLORS["fg"], padding=(5,0), font=('Segoe UI', 9, 'italic')); style.configure("Status.TLabel", background=COLORS["status_bg"], foreground=COLORS["fg"], padding=5)
        style.configure("RegStatus.TLabel", background=COLORS["bg"], font=('Segoe UI', 10, 'bold'), padding=(5,0)); style.configure("TButton", background=COLORS["button_bg"], foreground=COLORS["button_fg"], padding=6, bordercolor=COLORS["frame_bg"], lightcolor=COLORS["button_bg"], darkcolor=COLORS["button_bg"])
        style.map("TButton", background=[('active', '#81A1C1')], foreground=[('disabled', COLORS["disabled_fg"])]); style.configure("Success.TButton", background=COLORS["success_bg"], foreground=COLORS["success_fg"]); style.map("Success.TButton", background=[('active', '#B4D59F')])
    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10); main_frame.pack(fill=tk.BOTH, expand=True); top_frame = ttk.Frame(main_frame); top_frame.pack(fill=tk.X, pady=(0, 10))
        reg_frame = ttk.Frame(top_frame); reg_frame.pack(side=tk.LEFT, anchor='w'); self.btn_toggle_self = ttk.Button(reg_frame, text="..."); self.btn_toggle_self.pack(side=tk.LEFT, ipady=4); self.controls.append(self.btn_toggle_self)
        self.reg_status_label = ttk.Label(reg_frame, textvariable=self.reg_status_var, style="RegStatus.TLabel"); self.reg_status_label.pack(side=tk.LEFT, padx=10, anchor='w')
        self.path_count_label = ttk.Label(main_frame, textvariable=self.path_count_var, style="Count.TLabel"); self.path_count_label.pack(anchor='w'); list_frame = ttk.Frame(main_frame); list_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.path_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, bg=COLORS["list_bg"], fg=COLORS["fg"], selectbackground=COLORS["list_select_bg"], selectforeground=COLORS["list_select_fg"], borderwidth=0, highlightthickness=1, highlightcolor=COLORS["button_bg"], highlightbackground=COLORS["frame_bg"], font=('Segoe UI', 10))
        self.path_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); self.controls.append(self.path_listbox); scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.path_listbox.yview); scrollbar.pack(side=tk.RIGHT, fill=tk.Y); self.path_listbox.config(yscrollcommand=scrollbar.set)
        bottom_frame = ttk.Frame(main_frame); bottom_frame.pack(fill=tk.X, pady=(10, 0)); left_btn_frame = ttk.Frame(bottom_frame); left_btn_frame.pack(side=tk.LEFT)
        self.btn_add = ttk.Button(left_btn_frame, text="添加目录...", command=self.add_directory); self.btn_add.pack(side=tk.LEFT, padx=(0, 5)); self.controls.append(self.btn_add)
        self.btn_remove = ttk.Button(left_btn_frame, text="移除选中项", command=self.remove_selected); self.btn_remove.pack(side=tk.LEFT); self.controls.append(self.btn_remove)
        right_btn_frame = ttk.Frame(bottom_frame); right_btn_frame.pack(side=tk.RIGHT); self.btn_backup = ttk.Button(right_btn_frame, text="一键备份", command=self.create_backup); self.btn_backup.pack(side=tk.LEFT, padx=(0, 5)); self.controls.append(self.btn_backup)
        self.btn_restore = ttk.Button(right_btn_frame, text="恢复备份...", command=self.open_restore_window); self.btn_restore.pack(side=tk.LEFT); self.controls.append(self.btn_restore)
        self.status_var = tk.StringVar(); self.status_var.set("欢迎使用！将文件或文件夹拖到此处即可添加。"); status_bar = ttk.Label(self, textvariable=self.status_var, style="Status.TLabel", anchor='w'); status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    def populate_path_list(self):
        self.path_listbox.delete(0, tk.END); paths = self.path_manager.get_user_path_list(); self.path_count_var.set(f"当前用户 PATH 环境变量 ({len(paths)} 条):")
        sorted_paths = sorted(paths, key=str.lower)
        for i, path in enumerate(sorted_paths):
            self.path_listbox.insert(tk.END, path)
            if os.path.normpath(path).lower() == self.normalized_script_dir: self.path_listbox.itemconfigure(i, bg=COLORS["success_bg"], fg=COLORS["success_fg"], selectbackground=COLORS["button_bg"], selectforeground=COLORS["fg"])
        self.update_self_reg_status()
    def update_self_reg_status(self):
        is_registered = self.path_manager.is_path_registered(self.script_dir)
        if is_registered: self.btn_toggle_self.configure(text="反注册自身目录", style="TButton", command=self.unregister_self); self.reg_status_var.set("状态: ✔ 已注册"); self.reg_status_label.configure(foreground=COLORS["success_bg"])
        else: self.btn_toggle_self.configure(text="注册自身目录", style="Success.TButton", command=self.register_self); self.reg_status_var.set("状态: ❌ 未注册"); self.reg_status_label.configure(foreground=COLORS["warning_fg"])
    def toggle_controls(self, state=tk.NORMAL):
        for control in self.controls:
            if isinstance(control, tk.Listbox): control.config(state=state)
            else: control.config(state=state)
    def perform_action(self, action_func, *args, op_desc="正在处理...", **kwargs):
        self.toggle_controls(tk.DISABLED); self.status_var.set(op_desc); self.update_idletasks(); success, message = action_func(*args, **kwargs); self.toggle_controls(tk.NORMAL); self.status_var.set(message)
        if success:
            self.populate_path_list()
            if "恢复" not in op_desc: messagebox.showinfo("操作成功", message)
        else: messagebox.showwarning("操作提示", message)
    def register_self(self): self.perform_action(self.path_manager.add_path_and_broadcast, self.script_dir, op_desc=f"正在注册 {self.script_dir} ...")
    def unregister_self(self): self.perform_action(self.path_manager.remove_path_and_broadcast, self.script_dir, op_desc=f"正在反注册 {self.script_dir} ...")
    def add_directory(self):
        dir_path = filedialog.askdirectory(title="请选择要添加到PATH的文件夹", initialdir=self.script_dir)
        if dir_path: self.perform_action(self.path_manager.add_path_and_broadcast, dir_path, op_desc=f"正在添加 {dir_path} ...")
    def remove_selected(self):
        selected_indices = self.path_listbox.curselection()
        if not selected_indices: messagebox.showwarning("提示", "请先在列表中选择要移除的路径。"); return
        paths_to_remove = [self.path_listbox.get(i) for i in selected_indices]
        if messagebox.askyesno("确认移除", f"确定要移除选中的 {len(paths_to_remove)} 个路径吗？", icon='warning'):
            for path in paths_to_remove: self.perform_action(self.path_manager.remove_path_and_broadcast, path, op_desc=f"正在移除 {path} ...")
    def handle_drop(self, files):
        decoded_files = [f.decode(sys.getfilesystemencoding()) for f in files]
        paths_to_add = {str(Path(f).parent if Path(f).is_file() else Path(f).resolve()) for f in decoded_files}
        if not paths_to_add: return
        for path in paths_to_add: self.perform_action(self.path_manager.add_path_and_broadcast, path, op_desc=f"正在添加 {path} ...")
    def create_backup(self):
        self.status_var.set("正在创建备份..."); self.update_idletasks(); current_paths = self.path_manager.get_user_path_list()
        if not current_paths: messagebox.showwarning("备份提示", "当前PATH为空，无需备份。"); self.status_var.set("备份取消，PATH为空。"); return
        success, message = self.backup_manager.create_backup(current_paths); self.status_var.set(message)
        if success: messagebox.showinfo("备份成功", message)
        else: messagebox.showerror("备份失败", message)
    def open_restore_window(self): RestoreWindow(self)

def print_cli_help():
    # 命令名：旧代码取 sys.argv[0]（旧宿主下是 "main.py" 或 "-c"），对新宿主
    # 没有意义 —— 在 moss 里这条命令就是 `moss :path`（和 kill/tree/open 的
    # 提示保持一致）。直接 python main.py 调试时显示的也是这条，同样正确。
    script_name = "moss :path"
    help_text = f"""
Path 环境变量编辑器 - 命令行使用说明

以 GUI 模式运行 (默认):
  {script_name}

通过命令行管理 PATH:
  {script_name} <命令> [路径]

可用命令:
  add [路径]        将指定路径添加到用户 PATH 环境变量中。
                    如果省略 [路径]，则添加此脚本/程序所在的目录。
                    (别名: register, reg)

  remove [路径]     从用户 PATH 环境变量中移除指定路径。
                    如果省略 [路径]，则移除此脚本/程序所在的目录。
                    (别名: unregister, del)

  help              显示此帮助信息。
                    (别名: ?, -h, --help)

示例:
  {script_name} add "C:\\Program Files\\MyTool"
  {script_name} add
  {script_name} remove
"""
    print(help_text)

def _split_args(s: str) -> list[str]:
    r"""按空白拆参数，但**不碰反斜杠**（照抄 system/pkgs/tree/main.py 的同名函数）。

    为什么不用 shlex：Windows 路径里的 `\` 会被 shlex 当转义吃掉。
    引号包起来的部分保持成一个参数（带空格的路径用得上）。
    """
    out, cur, quote = [], "", None
    for ch in s:
        if quote:
            if ch == quote: quote = None
            else: cur += ch
        elif ch in "\"'": quote = ch
        elif ch.isspace():
            if cur: out.append(cur); cur = ""
        else: cur += ch
    if cur: out.append(cur)
    return out


def _moss_args():
    """从宿主拿参数；拿不到返回 None（调用方退回 sys.argv）。

    宿主 moss 把参数放在 `MOSS_PKG_PARAMS`（JSON，键是 pkg.json 里声明的参数名）
    和 `MOSS_ARGS`（原始字符串）两个环境变量里 —— 老 pa 是拼进 argv 的。
    本包的 `args` 声明成 `rest: true`（包名后面那一整串全归我），所以这里原样拆开，
    再交给下面这套老解析逻辑（写法照抄 system/pkgs/exec/main.py 的 _moss_args）。
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
    raw = _os.environ.get("MOSS_ARGS")
    if raw:
        return _split_args(raw)
    return None


def parse_cli_args() -> tuple[str | None, str | None]:
    # 参数来源：先问宿主（MOSS_PKG_PARAMS / MOSS_ARGS），读不到才退回 argv ——
    # 这样直接 `python main.py add xxx` 调试仍然能用。
    args = _moss_args()
    if args is None:
        args = sys.argv[1:]
    if args and args[0] == '-c':
        args = args[1:]
        if args and (args[0].endswith('.py') or Path(args[0]).is_file()):
             args = args[1:]
    if not args: return None, None
    COMMANDS = {'add': ['add', 'register', 'reg'], 'remove': ['remove', 'unregister', 'del'], 'help': ['help', '?', '-h', '--help']}
    raw_arg1 = args[0].lower()
    if raw_arg1 in COMMANDS['help']: return 'help', None
    for cmd_type, aliases in COMMANDS.items():
        if cmd_type == 'help': continue
        for alias in aliases:
            if raw_arg1.startswith(alias + ' '):
                command = cmd_type
                path = args[0][len(alias) + 1:].strip('"')
                return command, path
        if raw_arg1 in aliases:
            command = cmd_type
            path = " ".join(args[1:]).strip('"') if len(args) > 1 else None
            return command, path
    return raw_arg1, " ".join(args[1:])

def main():
    command, path = parse_cli_args()
    if command is None:
        try:
            if getattr(sys, 'frozen', False):
                try: ctypes.windll.kernel32.FreeConsole()
                except Exception: pass
            script_dir = application_path
            app = PathEditorApp(script_dir)
            app.mainloop()
        except Exception as e:
            messagebox.showerror("严重错误", f"程序遇到未知错误并即将退出。\n\n错误信息: {e}")
            sys.exit(1)
        return
    if command == 'help':
        print_cli_help()
        sys.exit(0)
    try:
        path_manager = PathManager()
        target_path = path or application_path
        if command == 'add':
            success, message = path_manager.add_path_and_broadcast(target_path)
            print(message); sys.exit(0 if success else 1)
        elif command == 'remove':
            success, message = path_manager.remove_path_and_broadcast(target_path)
            print(message); sys.exit(0 if success else 1)
        else:
            print(f"错误: 未知命令 '{command}'\n"); print_cli_help(); sys.exit(1)
    except Exception as e:
        print(f"执行命令时发生严重错误: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()