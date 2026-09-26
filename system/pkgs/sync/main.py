# sync_app.py (Final, with Context Menu Restore)

import tkinter as tk
from tkinter import ttk, font, messagebox
import windnd
import os
import fnmatch
import subprocess
import sys
import threading
import queue
import time
from datetime import datetime
from backup_manager import BackupManager
from settings_manager import SettingsManager

# --- Unchanged Helper Class (CreateToolTip) ---
# ... (Omitted for brevity)
class CreateToolTip:
    def __init__(self, widget, text):
        self.widget = widget; self.text = text; self.tooltip_window = None; self.id = None; self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter); self.widget.bind("<Leave>", self.leave); self.widget.bind("<ButtonPress>", self.leave)
    def enter(self, event=None): self.schedule()
    def leave(self, event=None): self.unschedule(); self.hidetip()
    def schedule(self): self.unschedule(); self.id = self.widget.after(500, self.showtip)
    def unschedule(self):
        id = self.id; self.id = None
        if id: self.widget.after_cancel(id)
    def showtip(self):
        if self.tooltip_window: return
        x = self.widget.winfo_pointerx() + 20; y = self.widget.winfo_pointery() + 10
        self.tooltip_window = tk.Toplevel(self.widget); self.tooltip_window.wm_overrideredirect(True); self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip_window, text=self.text, justify='left', background="#ffffe0", relief='solid', borderwidth=1, font=("", "10", "normal"))
        label.pack(ipadx=5, ipady=3)
    def hidetip(self):
        if self.tooltip_window: self.tooltip_window.destroy()
        self.tooltip_window = None

# --- AppUI Class (Context Menu added) ---
class AppUI(ttk.Frame):
    def __init__(self, master, controller):
        super().__init__(master)
        self.pack(expand=True, fill="both")
        self.controller = controller
        self.font_bold = font.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        self.font_normal = font.Font(family="Microsoft YaHei UI", size=10)
        self.type_checkboxes = []
        self.panes_configured = False
        self._setup_ui()

    def _setup_ui(self):
        self._create_top_path_panel()
        main_paned = ttk.PanedWindow(self, orient="horizontal")
        main_paned.pack(expand=True, fill="both", padx=5, pady=(0, 5))
        self._create_left_panel(main_paned)
        self._create_middle_panel(main_paned)
        self._create_right_filter_panel(main_paned)
        main_paned.bind("<Configure>", self._on_paned_window_configure)
        self._create_status_bar()

    def _on_paned_window_configure(self, event):
        if self.panes_configured or event.width < 100: return
        paned_window = event.widget
        sash1_pos = int(event.width * 0.40); sash2_pos = int(event.width * 0.80)
        try:
            paned_window.sashpos(0, sash1_pos); paned_window.sashpos(1, sash2_pos)
            self.panes_configured = True
        except tk.TclError: pass

    def _create_top_path_panel(self):
        path_frame = ttk.Frame(self, padding=(5, 5, 5, 0)); path_frame.pack(fill="x", side="top")
        ttk.Label(path_frame, text="项目路径:", font=self.font_normal).pack(side="left", padx=(0,5))
        self.path_combobox = ttk.Combobox(path_frame, state="readonly", font=self.font_normal); self.path_combobox.pack(side="left", fill="x", expand=True)
        CreateToolTip(self.path_combobox, "显示所有已备份的项目。\n可拖拽新文件夹到程序窗口以添加新项目。")
        self.scan_button = ttk.Button(path_frame, text="重新扫描", command=self.controller._on_scan_button_click); self.scan_button.pack(side="left", padx=(5,0))

    def _create_status_bar(self):
        status_frame = ttk.Frame(self, style="Status.TFrame"); status_frame.pack(side="bottom", fill="x")
        ttk.Style().configure("Status.TFrame", relief="sunken")
        self.status_label = ttk.Label(status_frame, text="正在啟動...", padding=(5,3)); self.status_label.pack(side="left", fill="x", expand=True)
        open_repo_button = ttk.Button(status_frame, text="打开备份位置", command=self.controller.open_backup_repo, style="Link.TButton"); open_repo_button.pack(side="right", padx=5)
        CreateToolTip(open_repo_button, "在文件浏览器中打开根备份文件夹 (.sync_repo)。")
        s = ttk.Style(); s.configure("Link.TButton", relief="flat", foreground="blue", anchor="center"); s.map("Link.TButton", foreground=[('active', 'red')])
    
    def _create_left_panel(self, parent_paned):
        frame = ttk.Frame(parent_paned, padding=5); parent_paned.add(frame)
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        lframe = ttk.LabelFrame(frame, labelwidget=ttk.Label(frame, text=" 待备份的文件/文件夹 ", font=self.font_bold))
        lframe.grid(row=0, column=0, sticky="nsew"); lframe.rowconfigure(0, weight=1); lframe.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(lframe, show="tree"); self.tree.heading("#0", text="文件/文件夹"); self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(lframe, orient="vertical", command=self.tree.yview); scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.loading_label = ttk.Label(lframe, text="加载中...", font=self.font_bold, background="white", foreground="gray")
        btn_frame = ttk.Frame(lframe); btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5,0))
        ttk.Button(btn_frame, text="全选", command=lambda: self.controller.toggle_all_items(True)).pack(side="left", expand=True, fill="x", padx=(0,2))
        ttk.Button(btn_frame, text="全不选", command=lambda: self.controller.toggle_all_items(False)).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btn_frame, text="反选", command=self.controller.invert_left_tree_selection).pack(side="left", expand=True, fill="x", padx=(2,0))

    def _create_middle_panel(self, parent_paned):
        self.middle_panel_container = ttk.Frame(parent_paned, padding=5); parent_paned.add(self.middle_panel_container)
        self.middle_panel_container.rowconfigure(0, weight=1); self.middle_panel_container.columnconfigure(0, weight=1)
        self._create_actions_panel(); self._create_version_browser_panel()
        self.actions_panel.grid(row=0, column=0, sticky="nsew")

    def _create_actions_panel(self):
        self.actions_panel = ttk.Frame(self.middle_panel_container)
        parent = self.actions_panel; parent.rowconfigure(1, weight=1); parent.columnconfigure(0, weight=1)
        backup_frame = ttk.LabelFrame(parent, text="备份操作", labelwidget=ttk.Label(parent, text=" 备份操作 ", font=self.font_bold)); backup_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        backup_frame.columnconfigure(1, weight=1)
        ttk.Label(backup_frame, text="备份描述:", font=self.font_normal).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.desc_entry = ttk.Entry(backup_frame, font=self.font_normal); self.desc_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        CreateToolTip(self.desc_entry, "为本次备份添加一条易于识别的说明。")
        self.backup_button = ttk.Button(backup_frame, text="执行备份", command=self.controller.execute_backup, state="disabled"); self.backup_button.grid(row=0, column=2, padx=5, pady=5)
        history_frame = ttk.LabelFrame(parent, text="历史记录", labelwidget=ttk.Label(parent, text=" 历史记录 ", font=self.font_bold)); history_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        history_frame.rowconfigure(0, weight=1); history_frame.columnconfigure(0, weight=1)
        cols = ("time", "desc", "count"); self.history_tree = ttk.Treeview(history_frame, columns=cols, show='headings', selectmode='extended'); self.history_tree.grid(row=0, column=0, sticky="nsew")
        hs = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_tree.yview); hs.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=hs.set)
        for col, name in {"time":"备份时间", "desc":"备份描述", "count":"文件数"}.items(): self.history_tree.heading(col, text=name)
        self.history_tree.column("time", width=140, anchor="w", stretch=False); self.history_tree.column("desc", width=150, anchor="w"); self.history_tree.column("count", width=60, anchor="center", stretch=False)
        self.history_empty_label = ttk.Label(history_frame, text="此项目尚无备份记录。", justify="center", style="Placeholder.TLabel"); self.history_empty_label.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Style().configure("Placeholder.TLabel", foreground="gray")
        btn_frame = ttk.Frame(history_frame); btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5,0))
        btn_frame.columnconfigure((0,1,2), weight=1)
        self.browse_button = ttk.Button(btn_frame, text="浏览版本", command=self.controller.browse_selected_version, state="disabled"); self.browse_button.grid(row=0, column=0, sticky="ew", padx=(0,2))
        self.restore_button = ttk.Button(btn_frame, text="完整恢复", command=self.controller.execute_restore, state="disabled"); self.restore_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.delete_button = ttk.Button(btn_frame, text="删除选中", command=self.controller.execute_delete, state="disabled"); self.delete_button.grid(row=0, column=2, sticky="ew", padx=(2,0))

    # <<< CHANGE: Context menu is created here
    def _create_version_browser_panel(self):
        self.browser_panel = ttk.Frame(self.middle_panel_container)
        parent = self.browser_panel; parent.rowconfigure(1, weight=1); parent.columnconfigure(0, weight=1)
        self.browser_title_label = ttk.Label(parent, text="浏览备份版本: ", font=self.font_bold); self.browser_title_label.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 5))
        browser_frame = ttk.LabelFrame(parent, labelwidget=self.browser_title_label)
        browser_frame.grid(row=1, column=0, sticky="nsew", pady=5); browser_frame.rowconfigure(0, weight=1); browser_frame.columnconfigure(0, weight=1)
        self.browser_tree = ttk.Treeview(browser_frame, show="tree"); self.browser_tree.heading("#0", text="备份中的文件/文件夹"); self.browser_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(browser_frame, orient="vertical", command=self.browser_tree.yview); scrollbar.grid(row=0, column=1, sticky="ns")
        self.browser_tree.configure(yscrollcommand=scrollbar.set)
        
        # Create the context menu
        self.browser_context_menu = tk.Menu(self.browser_tree, tearoff=0)
        self.browser_context_menu.add_command(label="恢复此项", command=self.controller.restore_context_item)

        btn_frame = ttk.Frame(browser_frame); btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5,0))
        ttk.Button(btn_frame, text="返回", command=self.controller.show_actions_view).pack(side="left")
        ttk.Label(btn_frame).pack(side="left", expand=True) 
        ttk.Button(btn_frame, text="全选", command=self.controller.select_all_browser_items).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="全不选", command=self.controller.deselect_all_browser_items).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="反选", command=self.controller.invert_browser_selection).pack(side="left", padx=(2,10))
        ttk.Button(btn_frame, text="...", command=self.controller.open_selected_in_browser, width=4).pack(side="left")
        CreateToolTip(btn_frame.winfo_children()[-1], "打开所在文件夹")
        ttk.Button(btn_frame, text="恢复", command=self.controller.restore_selective_items).pack(side="left", padx=5)

    def _create_right_filter_panel(self, parent_paned):
        # ... (unchanged)
        frame = ttk.Frame(parent_paned, padding=5); parent_paned.add(frame)
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(frame); notebook.grid(row=0, column=0, sticky="nsew")
        type_filter_tab = ttk.Frame(notebook, padding=(10, 5)); exclusion_tab = ttk.Frame(notebook, padding=(10, 5))
        notebook.add(type_filter_tab, text=" 按类型过滤 "); notebook.add(exclusion_tab, text=" 排除项过滤 ")
        self._populate_type_filter_tab(type_filter_tab); self._populate_exclusion_tab(exclusion_tab)
        notebook.select(type_filter_tab)
    
    def _populate_exclusion_tab(self, parent):
        # ... (unchanged)
        parent.rowconfigure(0, weight=1); parent.columnconfigure(0, weight=1)
        ex_frame = ttk.LabelFrame(parent, text="全局排除项列表", labelwidget=ttk.Label(parent, text=" 全局排除项列表 ", font=self.font_bold))
        ex_frame.grid(row=0, column=0, sticky="nsew", pady=5); ex_frame.rowconfigure(0, weight=1); ex_frame.columnconfigure(0, weight=1)
        self.exclusion_text = tk.Text(ex_frame, wrap="word", font=self.font_normal, undo=True)
        text_scroll = ttk.Scrollbar(ex_frame, orient="vertical", command=self.exclusion_text.yview)
        self.exclusion_text.config(yscrollcommand=text_scroll.set)
        self.exclusion_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5); text_scroll.grid(row=0, column=1, sticky="ns")
        btn_frame = ttk.Frame(ex_frame); btn_frame.grid(row=1, column=0, columnspan=2, sticky="e", padx=5, pady=5)
        ttk.Button(btn_frame, text="恢复默认", command=self.controller.reset_exclusions).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="保存", command=self.controller.save_exclusions).pack(side="left")
    
    def _populate_type_filter_tab(self, parent):
        # ... (unchanged)
        parent.columnconfigure(0, weight=1); parent.rowconfigure(0, weight=1)
        type_frame = ttk.LabelFrame(parent, text="当前视图类型", labelwidget=ttk.Label(parent, text=" 当前视图类型 ", font=self.font_bold))
        type_frame.grid(row=0, column=0, sticky="nsew", pady=5); type_frame.columnconfigure(0, weight=1); type_frame.rowconfigure(1, weight=1)
        btn_frame = ttk.Frame(type_frame); btn_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        btn_frame.columnconfigure((0,1,2), weight=1)
        ttk.Button(btn_frame, text="全选", command=self.controller.select_all_types).grid(row=0, column=0, sticky="ew", padx=(0,2))
        ttk.Button(btn_frame, text="不选", command=self.controller.deselect_all_types).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(btn_frame, text="反选", command=self.controller.invert_type_selection).grid(row=0, column=2, sticky="ew", padx=(2,0))
        canvas_container = ttk.Frame(type_frame); canvas_container.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        canvas_container.columnconfigure(0, weight=1); canvas_container.rowconfigure(0, weight=1)
        self.types_canvas = tk.Canvas(canvas_container, highlightthickness=0); self.types_canvas.grid(row=0, column=0, sticky="nsew")
        ts = ttk.Scrollbar(canvas_container, orient="vertical", command=self.types_canvas.yview); ts.grid(row=0, column=1, sticky="ns")
        self.types_canvas.configure(yscrollcommand=ts.set)
        self.checkbox_container = ttk.Frame(self.types_canvas); self.types_canvas.create_window((0, 0), window=self.checkbox_container, anchor="nw")
    
    # <<< CHANGE: Right-click event binding added
    def connect_events(self):
        windnd.hook_dropfiles(self, func=self.controller.dragged_files)
        self.path_combobox.bind("<<ComboboxSelected>>", self.controller.on_path_selected_from_dropdown)
        self.tree.bind("<Button-1>", self.controller.on_tree_click)
        self.history_tree.bind("<Double-1>", self.controller.browse_selected_version)
        self.types_canvas.bind("<Configure>", self._reflow_type_checkboxes)
        self.checkbox_container.bind("<Configure>", lambda e: self.types_canvas.configure(scrollregion=self.types_canvas.bbox("all")))
        self.browser_tree.bind("<Button-1>", self.controller.on_browser_tree_click)
        self.browser_tree.bind("<Button-3>", self.controller.on_browser_tree_right_click) # Windows/Linux
        self.browser_tree.bind("<Button-2>", self.controller.on_browser_tree_right_click) # macOS
        self.browser_tree.bind("<Double-1>", self.controller.open_selected_in_browser)
    
    # ... (other AppUI methods are unchanged)
    def show_actions_view(self): self.browser_panel.grid_remove(); self.actions_panel.grid(row=0, column=0, sticky="nsew")
    def show_browser_view(self, version_info):
        self.browser_title_label.config(text=f"浏览备份: {version_info['display_time']}")
        self.browser_tree.delete(*self.browser_tree.get_children())
        self.actions_panel.grid_remove(); self.browser_panel.grid(row=0, column=0, sticky="nsew")
    def show_loading(self, show):
        if show: self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
        else: self.loading_label.place_forget()
    def update_scan_button(self, text, state='normal', command=None):
        self.scan_button.config(text=text, state=state)
        if command: self.scan_button.config(command=command)
    def set_history_buttons_state(self, state):
        for btn in [self.browse_button, self.restore_button, self.delete_button]: btn.config(state=state)
    def update_history_list(self, versions):
        for item in self.history_tree.get_children(): self.history_tree.delete(item)
        if not versions: self.history_empty_label.lift(); self.set_history_buttons_state('disabled')
        else:
            self.history_empty_label.lower()
            for version in versions:
                try:
                    original_ts = version.get("timestamp", "N/A"); dt_object = datetime.strptime(original_ts, "%Y%m%d_%H%M%S"); formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S")
                    self.history_tree.insert("", "end", values=(formatted_time, version.get("description", "无"), version.get("file_count", "N/A"), original_ts))
                except (ValueError, TypeError): self.history_tree.insert("", "end", values=("无效时间", version.get("description", "无"), version.get("file_count", "N/A"), ""))
            self.history_tree["displaycolumns"] = ("time", "desc", "count"); self.set_history_buttons_state('normal')
    def update_exclusion_text(self, patterns): self.exclusion_text.delete('1.0', tk.END); self.exclusion_text.insert('1.0', '\n'.join(patterns)); self.exclusion_text.edit_reset()
    def get_exclusion_text_content(self): return self.exclusion_text.get('1.0', tk.END)
    def update_file_type_filters(self, file_types_dict):
        for widget in self.checkbox_container.winfo_children(): widget.destroy()
        self.type_checkboxes.clear()
        if file_types_dict:
            for ext, var in sorted(file_types_dict.items()):
                cb = ttk.Checkbutton(self.checkbox_container, text=ext, variable=var, command=self.controller.apply_filter); self.type_checkboxes.append(cb)
            self._reflow_type_checkboxes()
    def _reflow_type_checkboxes(self, event=None):
        if not self.type_checkboxes: return
        canvas_width = self.types_canvas.winfo_width();
        if canvas_width < 2: return
        cb_width = self.type_checkboxes[0].winfo_reqwidth() + 10; max_cols = max(1, canvas_width // cb_width) if cb_width > 10 else 3
        for i, cb in enumerate(self.type_checkboxes): cb.grid(row=i // max_cols, column=i % max_cols, sticky="w", padx=2, pady=1)
        self.checkbox_container.update_idletasks(); self.types_canvas.config(scrollregion=self.types_canvas.bbox("all"))

# --- AppController Class (New context menu methods added) ---
class AppController:
    def __init__(self, master):
        self.master = master; self.backup_manager = BackupManager(); self.settings_manager = SettingsManager()
        self.current_path = None; self.file_types = {}; self.tracked_projects_map = {}
        self.is_scanning = False; self.pending_scan_path = None
        self.scan_thread = None; self.scan_queue = queue.Queue(); self.scan_stop_event = threading.Event()
        self.dnd_queue = queue.Queue()
        self.current_browsing_version = None
        # <<< NEW: Variable to store the item ID from a right-click
        self.context_menu_item_id = None
        self.ui = AppUI(master, self)
        self.ui.connect_events()
        self.master.after(10, self.initial_load)
        
    # <<< NEW: Handler for right-clicks on the browser tree
    def on_browser_tree_right_click(self, event):
        item_id = self.ui.browser_tree.identify_row(event.y)
        if item_id:
            # Select the item that was right-clicked
            self.ui.browser_tree.selection_set(item_id)
            # Store it for the menu command
            self.context_menu_item_id = item_id
            # Show the context menu
            self.ui.browser_context_menu.post(event.x_root, event.y_root)

    # <<< NEW: Logic for the context menu's "Restore" command
    def restore_context_item(self):
        item_to_restore = self.context_menu_item_id
        if not item_to_restore or not self.current_browsing_version:
            return

        item_name = os.path.basename(item_to_restore)
        msg = f"确定要将 '{item_name}' 恢复到原始位置吗？\n这将覆盖现有同名文件！"

        if messagebox.askyesno("确认恢复", msg):
            source_path = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
            timestamp = self.current_browsing_version['timestamp']
            
            # We call the same function but with a list containing only the one item
            success, message = self.backup_manager.restore_selective_items(source_path, timestamp, [item_to_restore])
            
            if success:
                messagebox.showinfo("成功", f"'{item_name}' 已成功恢复。")
            else:
                messagebox.showerror("失败", message)

    # ... (The rest of the AppController is unchanged and correct)
    def _invert_recursive(self, tree, item_id):
        current_state = "checked" in tree.item(item_id, "tags")
        self._set_item_checked(tree, item_id, not current_state)
        for child_id in tree.get_children(item_id):
            self._invert_recursive(tree, child_id)
    def invert_left_tree_selection(self):
        for item_id in self.ui.tree.get_children(""): self._invert_recursive(self.ui.tree, item_id)
    def select_all_browser_items(self):
        for item_id in self.ui.browser_tree.get_children(""): self._toggle_recursive(self.ui.browser_tree, item_id, True)
    def deselect_all_browser_items(self):
        for item_id in self.ui.browser_tree.get_children(""): self._toggle_recursive(self.ui.browser_tree, item_id, False)
    def invert_browser_selection(self):
        for item_id in self.ui.browser_tree.get_children(""): self._invert_recursive(self.ui.browser_tree, item_id)
    def _populate_browser_tree(self):
        if not self.current_browsing_version: return
        source_for_repo = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
        timestamp = self.current_browsing_version["timestamp"]
        all_paths = self.backup_manager.get_version_contents(source_for_repo, timestamp)
        if all_paths is None: messagebox.showerror("错误", "无法加载此版本的文件列表。"); return
        tree = self.ui.browser_tree; tree.delete(*tree.get_children())
        for item_path in sorted(list(all_paths), key=lambda p: (p.count('/'), p)):
            parent_path = os.path.dirname(item_path); item_name = os.path.basename(item_path)
            parent_iid = parent_path if parent_path else ""
            if not tree.exists(item_path):
                tree.insert(parent_iid, "end", iid=item_path, text="☐ " + item_name, open=False)
    def _ensure_parent_exists(self, tree, full_path):
        parent_path = os.path.dirname(full_path).replace('\\', '/')
        if not parent_path: return ""
        if tree.exists(parent_path): return parent_path
        else:
            grandparent_iid = self._ensure_parent_exists(tree, parent_path)
            parent_name = os.path.basename(parent_path)
            tree.insert(grandparent_iid, "end", iid=parent_path, text="☐ " + parent_name, open=False)
            return parent_path
    def _scan_worker(self, path, stop_event, q):
        discovered_exts = set()
        try:
            if os.path.isfile(path):
                f = os.path.basename(path)
                if not self._is_excluded(f):
                    q.put(('item', f)); ext = os.path.splitext(f)[1].lower()
                    if ext: discovered_exts.add(ext)
            else:
                for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
                    if stop_event.is_set(): break
                    dirs[:] = [d for d in dirs if not self._is_excluded(d)]
                    rel_root = os.path.relpath(root, path)
                    for name in dirs + files:
                        if self._is_excluded(name): continue
                        rel_path = os.path.join(rel_root, name) if rel_root != '.' else name
                        q.put(('item', rel_path.replace('\\', '/')))
                        if not os.path.isdir(os.path.join(path, rel_path)):
                            ext = os.path.splitext(name)[1].lower()
                            if ext: discovered_exts.add(ext)
            if stop_event.is_set(): q.put(("status", "stopped"))
            else: q.put(("exts", discovered_exts)); q.put(("status", "done"))
        except Exception as e: q.put(("error", str(e)))
    def _process_scan_queue_batch(self):
        if not self.is_scanning or self.scan_stop_event.is_set():
            if self.is_scanning: self._finalize_scan("stopped"); return
        start_time = time.time()
        while time.time() - start_time < 0.05:
            try:
                msg_type, *data = self.scan_queue.get_nowait()
                if msg_type == 'item':
                    full_path = data[0]; parent_iid = self._ensure_parent_exists(self.ui.tree, full_path)
                    item_name = os.path.basename(full_path)
                    if not self.ui.tree.exists(full_path):
                        self.ui.tree.insert(parent_iid, "end", iid=full_path, text="☐ " + item_name, open=False)
                elif msg_type == 'exts': self._update_file_type_filters_ui(data[0])
                elif msg_type == 'status': self._finalize_scan(data[0]); return
                elif msg_type == 'error': self._finalize_scan('error', data[0]); return
            except queue.Empty: break
        if not self.scan_thread.is_alive() and self.scan_queue.empty(): self._finalize_scan("done"); return
        if self.is_scanning: self.master.after(100, self._process_scan_queue_batch)
    def initial_load(self):
        self.ui.status_label.config(text="正在初始化..."); self._load_exclusions_to_ui()
        self.update_tracked_paths_dropdown(); initial_path = os.getcwd()
        if initial_path: self.load_path(initial_path)
        else: self.ui.status_label.config(text="準備就緒。請拖拽文件夾或從下拉列表選擇。")
        self.master.after(100, self._process_dnd_queue)
    def _load_exclusions_to_ui(self): self.ui.update_exclusion_text(self.settings_manager.get_exclusions())
    def save_exclusions(self):
        patterns = [line.strip() for line in self.ui.get_exclusion_text_content().split('\n') if line.strip()]
        self.settings_manager.set_exclusions(patterns)
        self.ui.status_label.config(text="排除项已保存。重新扫描以应用更改。")
        messagebox.showinfo("保存成功", "排除项已保存。\n请在主操作界面点击“重新扫描”来应用新的过滤规则。", parent=self.master)
    def reset_exclusions(self):
        if messagebox.askyesno("确认", "确定要将排除项恢复为默认设置吗？", parent=self.master):
            default_patterns = self.settings_manager.reset_exclusions_to_default()
            self.ui.update_exclusion_text(default_patterns)
            self.ui.status_label.config(text="排除项已恢复为默认值。点击“保存”以确认。")
    def open_selected_in_browser(self, event=None):
        if not self.current_browsing_version: return
        selected = self.ui.browser_tree.selection()
        if not selected: messagebox.showwarning("选择错误", "请选择一个文件或文件夹。"); return
        relative_path = selected[0]
        source = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
        project_repo_path = self.backup_manager._get_project_repo_path(source)
        version_path = os.path.join(project_repo_path, self.current_browsing_version['timestamp'])
        full_path = os.path.join(version_path, relative_path)
        if not os.path.exists(full_path): messagebox.showerror("错误", f"找不到路径: {full_path}"); return
        path_to_open = os.path.dirname(full_path) if not os.path.isdir(full_path) else full_path
        try:
            if sys.platform == "win32": os.startfile(path_to_open)
            elif sys.platform == "darwin": subprocess.Popen(["open", path_to_open])
            else: subprocess.Popen(["xdg-open", path_to_open])
        except Exception as e: messagebox.showerror("打开失败", f"无法打开文件夹：\n{e}")
    def dragged_files(self, files): self.dnd_queue.put(files)
    def _process_dnd_queue(self):
        try:
            dropped_files = self.dnd_queue.get_nowait()
            if dropped_files: self.load_path(os.path.normpath(dropped_files[0].decode('gbk', 'ignore')))
        except queue.Empty: pass
        finally: self.master.after(100, self._process_dnd_queue)
    def load_path(self, path):
        if not os.path.exists(path): self.ui.status_label.config(text=f"错误: 路径不存在: {path}"); return
        if self.is_scanning:
            self.pending_scan_path = path; self.ui.status_label.config(text=f"请求新路径... 等待当前扫描停止。")
            self.current_path = path; self.update_tracked_paths_dropdown(); self.set_combobox_selection(path)
            self._update_history_view(); self._stop_scan(); return
        self.current_path = path
        self.update_tracked_paths_dropdown(); self.set_combobox_selection(path)
        self._update_history_view(); self._start_scan(); self.show_actions_view()
    def _start_scan(self):
        if self.is_scanning: return
        self.is_scanning = True; self.ui.tree.delete(*self.ui.tree.get_children()); self.ui.show_loading(True)
        self.ui.status_label.config(text=f"正在扫描: {self.current_path}...")
        self.ui.update_scan_button("停止", command=self._stop_scan)
        self.ui.backup_button.config(state="disabled")
        self.scan_stop_event.clear();
        while not self.scan_queue.empty(): self.scan_queue.get_nowait()
        self.scan_thread = threading.Thread(target=self._scan_worker, args=(self.current_path, self.scan_stop_event, self.scan_queue), daemon=True)
        self.scan_thread.start(); self.master.after(100, self._process_scan_queue_batch)
    def _on_scan_button_click(self):
        if self.current_path and not self.is_scanning: self._start_scan()
    def _stop_scan(self):
        if not self.is_scanning: return
        self.ui.update_scan_button("停止中...", state="disabled")
        self.ui.status_label.config(text="正在停止扫描..."); self.scan_stop_event.set()
    def _finalize_scan(self, status, error_msg=None):
        if not self.is_scanning and status != "stopped": return
        self.is_scanning = False; self.ui.show_loading(False)
        self.ui.update_scan_button("重新扫描", command=self._on_scan_button_click)
        self.ui.backup_button.config(state="normal")
        if status == 'done': self.ui.status_label.config(text=f"扫描完成。")
        elif status == 'stopped': self.ui.status_label.config(text="扫描已停止。")
        elif status == 'error': self.ui.status_label.config(text=f"扫描出错！"); messagebox.showerror("扫描错误", f"扫描时发生错误：\n{error_msg}")
        if not self.file_types: self._update_file_type_filters_ui(set())
        if self.pending_scan_path:
            path_to_load = self.pending_scan_path; self.pending_scan_path = None
            self.master.after(10, lambda: self.load_path(path_to_load))
    def show_actions_view(self): self.current_browsing_version = None; self.ui.show_actions_view()
    def browse_selected_version(self, event=None):
        selected_items = self.ui.history_tree.selection()
        if not selected_items or len(selected_items) > 1: messagebox.showwarning("选择错误", "请选择一个版本进行浏览。"); return
        values = self.ui.history_tree.item(selected_items[0], "values")
        self.current_browsing_version = {"timestamp": values[3], "display_time": values[0]}
        self.ui.show_browser_view(self.current_browsing_version); self._populate_browser_tree()
    def on_browser_tree_click(self, event):
        item_id = self.ui.browser_tree.identify_row(event.y)
        if not item_id: return
        is_checked = "checked" not in self.ui.browser_tree.item(item_id, 'tags')
        self._set_item_checked(self.ui.browser_tree, item_id, is_checked)
        for child_id in self.ui.browser_tree.get_children(item_id):
            self._toggle_recursive(self.ui.browser_tree, child_id, is_checked)
    def restore_selective_items(self):
        if not self.current_browsing_version: return
        selected_paths = []; tree = self.ui.browser_tree
        def find_top_checked(item_id):
            if 'checked' in tree.item(item_id, 'tags'): selected_paths.append(item_id)
            else:
                for child in tree.get_children(item_id): find_top_checked(child)
        for root_item in tree.get_children(""): find_top_checked(root_item)
        if not selected_paths: messagebox.showwarning("选择错误", "请至少选择一个要恢复的项目。"); return
        msg = f"确定要恢复选中的 {len(selected_paths)} 个项目吗？\n这将覆盖原始位置的同名文件！"
        if messagebox.askyesno("确认恢复", msg):
            source_path = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
            timestamp = self.current_browsing_version['timestamp']
            success, message = self.backup_manager.restore_selective_items(source_path, timestamp, selected_paths)
            if success: messagebox.showinfo("成功", message)
            else: messagebox.showerror("失败", message)
    def _update_history_view(self):
        if not self.current_path: self.ui.update_history_list([]); return
        source = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
        versions = self.backup_manager.list_backups(source)
        self.ui.update_history_list(versions)
    def on_path_selected_from_dropdown(self, event=None):
        selected = self.ui.path_combobox.get()
        path = self.tracked_projects_map.get(selected)
        if path and path != self.current_path: self.load_path(path)
    def open_backup_repo(self):
        repo_path = self.backup_manager.backup_root
        try:
            if sys.platform == "win32": os.startfile(repo_path)
            elif sys.platform == "darwin": subprocess.Popen(["open", repo_path])
            else: subprocess.Popen(["xdg-open", repo_path])
        except Exception as e: messagebox.showerror("打开失败", f"无法打开备份文件夹：\n{e}")
    def execute_backup(self):
        description = self.ui.desc_entry.get().strip()
        if not description: messagebox.showwarning("输入错误", "请输入备份描述。"); return
        selected = self.get_selected_items_for_backup()
        if not selected: messagebox.showwarning("选择错误", "请至少选择一项。"); return
        source = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
        success, message = self.backup_manager.create_backup(source, selected, description)
        if success:
            self.ui.status_label.config(text=message); self.ui.desc_entry.delete(0, 'end')
            self._update_history_view(); self.update_tracked_paths_dropdown()
        else: messagebox.showerror("备份失败", message)
    def execute_restore(self):
        selected = self.ui.history_tree.selection()
        if not selected or len(selected) > 1: messagebox.showwarning("选择错误", "请选择一个版本进行恢复。"); return
        values = self.ui.history_tree.item(selected[0], "values")
        if messagebox.askyesno("确认恢复", f"确定要恢复版本【{values[0]}】吗？\n这将覆盖原始位置的同名文件！"):
            source = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
            success, msg = self.backup_manager.restore_backup(source, values[3])
            if success: self.ui.status_label.config(text=msg)
            else: messagebox.showerror("恢复失败", msg)
    def execute_delete(self):
        selected = self.ui.history_tree.selection()
        if not selected: messagebox.showwarning("选择错误", "请选择要删除的版本。"); return
        if messagebox.askyesno("确认删除", f"确定要永久删除选中的 {len(selected)} 个版本吗？"):
            source = os.path.dirname(self.current_path) if os.path.isfile(self.current_path) else self.current_path
            timestamps = [self.ui.history_tree.item(item, "values")[3] for item in selected]
            success, msg = self.backup_manager.delete_backups(source, timestamps)
            if success: self.ui.status_label.config(text=msg); self._update_history_view(); self.update_tracked_paths_dropdown()
            else: messagebox.showerror("删除失败", msg)
    def apply_filter(self):
        if self.current_path: self.load_path(self.current_path)
    def _is_excluded(self, name):
        patterns = self.settings_manager.get_exclusions()
        if any(fnmatch.fnmatch(name, p) for p in patterns): return True
        ext = os.path.splitext(name)[1].lower()
        if ext in self.file_types and not self.file_types[ext].get(): return True
        return False
    def _update_file_type_filters_ui(self, exts):
        self.file_types.clear()
        if exts:
            for ext in sorted(list(exts)): self.file_types[ext] = tk.BooleanVar(value=True)
        self.ui.update_file_type_filters(self.file_types)
    def select_all_types(self): [v.set(True) for v in self.file_types.values()]; self.apply_filter()
    def deselect_all_types(self): [v.set(False) for v in self.file_types.values()]; self.apply_filter()
    def invert_type_selection(self): [v.set(not v.get()) for v in self.file_types.values()]; self.apply_filter()
    def update_tracked_paths_dropdown(self):
        projects = self.backup_manager.get_all_tracked_projects(); self.tracked_projects_map.clear()
        display_list = [f"{path} ({count}个备份)" for path, count in sorted(projects.items())]
        for item in display_list: self.tracked_projects_map[item] = item.split(" (")[0]
        self.ui.path_combobox['values'] = display_list
        if self.current_path: self.set_combobox_selection(self.current_path)
    def set_combobox_selection(self, path):
        for display, real in self.tracked_projects_map.items():
            if os.path.normpath(real) == os.path.normpath(path): self.ui.path_combobox.set(display); return
        self.ui.path_combobox.set(path)
    def on_tree_click(self, event):
        if self.ui.tree.identify_region(event.x, event.y) != "tree": return
        item_id = self.ui.tree.identify_row(event.y)
        if item_id: self._set_item_checked(self.ui.tree, item_id, "checked" not in self.ui.tree.item(item_id, "tags"))
    def _set_item_checked(self, tree, item_id, check):
        tags = list(tree.item(item_id, "tags")); text = tree.item(item_id, "text").lstrip("☐ ☑ ")
        if check: tags.append("checked"); tree.item(item_id, text="☑ " + text, tags=tags)
        else:
            if "checked" in tags: tags.remove("checked")
            tree.item(item_id, text="☐ " + text, tags=tags)
    def toggle_all_items(self, check=True):
        for item_id in self.ui.tree.get_children(""): self._toggle_recursive(self.ui.tree, item_id, check)
    def _toggle_recursive(self, tree, item_id, check):
        self._set_item_checked(tree, item_id, check)
        for child_id in tree.get_children(item_id): self._toggle_recursive(tree, child_id, check)
    def get_selected_items_for_backup(self):
        selected_paths = []; tree = self.ui.tree
        if not self.current_path: return []
        if os.path.isfile(self.current_path):
            root_items = tree.get_children('');
            if root_items and 'checked' in tree.item(root_items[0], 'tags'): return [os.path.basename(self.current_path)]
            else: return []
        def find_top_checked(item_id):
            if 'checked' in tree.item(item_id, 'tags'): selected_paths.append(item_id)
            else:
                for child_id in tree.get_children(item_id): find_top_checked(child_id)
        for root_item_id in tree.get_children(''): find_top_checked(root_item_id)
        return selected_paths

if __name__ == '__main__':
    try: from ttkthemes import ThemedTk; root = ThemedTk(theme="arc")
    except ImportError: root = tk.Tk()
    root.title("Sync - 本地文件备份工具")
    root.geometry("1200x750")
    app_controller = AppController(master=root)
    root.mainloop()