# -*- coding: utf-8 -*-

import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image

# 尝试导入windnd库以支持拖放功能
try:
    import windnd
    WINDND_AVAILABLE = True
except ImportError:
    WINDND_AVAILABLE = False

# --- 数据目录 ---
# ★ 迁移说明：旧版是 QuickTools 插件，宿主 pa 注入 PA_PLUGIN_DATA_DIR；
#   新版是 moss 包，宿主注入 MOSS_PLUGIN_DATA_DIR（= user_data/state/<包 id>）。
#   两个都认，脚本被单独跑时退回脚本自身目录。
DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.environ.get('PA_PLUGIN_DATA_DIR')
            or (os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals()
                else os.path.abspath(sys.path[0])))
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
HISTORY_LIMIT = 50

# ★ ico 是【多分辨率容器】：Windows 会按场景挑尺寸
#     （任务栏 32、资源管理器 16/48、属性与预览 256）。
#   旧版只往里写一个尺寸，等于把 ico 当单张图用 —— 这就是本次修的 bug。
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICO_SIZES_DEFAULT = [16, 24, 32, 48, 64, 128, 256]

# ==============================================================================
# 核心处理逻辑
# ==============================================================================

def process_single_image(filepath, output_format, quality, width, output_dir, save_mode, ico_sizes):
    try:
        with Image.open(filepath) as img:
            original_size = os.path.getsize(filepath)
            print(f"\n- 正在处理: {os.path.basename(filepath)} ({img.width}x{img.height})")
            img_copy = img.copy()

        if output_format != 'ico' and width and img_copy.width > width:
            aspect_ratio = img_copy.height / img_copy.width
            new_height = int(width * aspect_ratio)
            print(f"  - 调整尺寸为: {width}x{new_height}")
            img_copy = img_copy.resize((width, new_height), Image.Resampling.LANCZOS)

        base_name, _ = os.path.splitext(os.path.basename(filepath))
        output_filename = f"{base_name}.{output_format}"
        output_path = os.path.join(output_dir, output_filename)
        
        if output_format == 'jpg' and img_copy.mode in ('RGBA', 'P'):
            print("  - 转换透明背景为白色")
            background = Image.new('RGB', img_copy.size, (255, 255, 255))
            if 'A' in img_copy.getbands(): background.paste(img_copy, (0, 0), img_copy.getchannel('A'))
            else: background.paste(img_copy, (0, 0))
            img_copy = background
        elif img_copy.mode != 'RGB' and output_format == 'jpg':
            img_copy = img_copy.convert('RGB')

        save_options = {}
        if output_format in ('jpg', 'jpeg', 'webp'): save_options['quality'] = quality
        elif output_format == 'png': save_options['compress_level'] = int((100 - quality) / 100 * 9); save_options['optimize'] = True
        elif output_format == 'ico':
            sizes = sorted({int(s) for s in (ico_sizes or ICO_SIZES_DEFAULT) if s})
            print("  - ICO 多分辨率: %s" % ", ".join(str(s) for s in sizes))
            save_options['sizes'] = [(s, s) for s in sizes]

        img_copy.save(output_path, **save_options)
        new_size = os.path.getsize(output_path)
        print(f"[已保存] 至: {output_path} ({new_size/1024:.1f} KB)")

        if save_mode == "source_delete" and os.path.abspath(filepath).lower() != os.path.abspath(output_path).lower():
            os.remove(filepath); print(f"  - [已删除] 源文件: {os.path.basename(filepath)}")
    except Exception as e: print(f"[错误] 处理 {os.path.basename(filepath)} 时出错: {e}")

def run_tasks(source_dir, output_format, quality, width, source_filter, save_mode, ico_sizes):
    output_dir = source_dir if save_mode in ["source", "source_delete"] else os.path.join(source_dir, "compressed_output")
    if save_mode == "separate" and not os.path.exists(output_dir): os.makedirs(output_dir)
    files = [f for f in os.listdir(source_dir) if os.path.isfile(os.path.join(source_dir, f)) and os.path.splitext(f)[1].lower() in source_filter]
    if not files: print("\n提示: 未找到符合条件的图片。"); return
    print(f"\n找到 {len(files)} 个文件，开始处理...")
    for i, filename in enumerate(files):
        print(f"--- [进度: {i+1}/{len(files)}] ---")
        process_single_image(os.path.join(source_dir, filename), output_format, quality, width, output_dir, save_mode, ico_sizes)
    print("\n=====================\n所有任务已成功完成。\n=====================")

# ==============================================================================
# Tkinter GUI 应用
# ==============================================================================

class TextRedirector:
    def __init__(self, w): self.widget = w
    def write(self, s): self.widget.insert(tk.END, s); self.widget.see(tk.END)
    def flush(self): pass

class ImageCompressorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("智能图片压缩工具"); self.geometry("700x780")
        self.columnconfigure(0, weight=1); self.rowconfigure(3, weight=1)
        # --- Variables ---
        self.source_dir = tk.StringVar()
        self.output_format = tk.StringVar(value="jpg")
        self.quality = tk.IntVar(value=80)
        self.width = tk.StringVar()
        self.save_mode = tk.StringVar(value="separate")
        self.ico_size_vars = {s: tk.BooleanVar(value=True) for s in ICO_SIZES}
        self.filter_vars = {}; self.saved_filters_config = {}
        self.history = []
        # --- UI Init ---
        self._create_widgets()
        self._load_config()
        self._enable_drag_and_drop()
        self._update_filter_checkboxes()
        self._on_format_change()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_widgets(self):
        # --- Source Folder with History ---
        source_frame = ttk.Labelframe(self, text="源文件夹", padding="10")
        source_frame.grid(row=0, column=0, padx=10, pady=(10,5), sticky="ew")
        source_frame.columnconfigure(0, weight=1)
        self.history_combobox = ttk.Combobox(source_frame, textvariable=self.source_dir, state="readonly")
        self.history_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.history_combobox.bind("<<ComboboxSelected>>", self._on_history_select)
        ttk.Button(source_frame, text="选择...", command=self._select_folder).grid(row=0, column=1, padx=5, pady=5)

        # --- Options Frame ---
        options_frame = ttk.Labelframe(self, text="压缩与保存选项", padding="10")
        options_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        options_frame.columnconfigure(1, weight=1)
        
        self.output_format.trace_add("write", self._on_format_change)
        ttk.Label(options_frame, text="目标格式:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        format_group = ttk.Frame(options_frame)
        format_group.grid(row=0, column=1, columnspan=3, sticky="w")
        for fmt in ["jpg", "png", "webp", "ico"]: ttk.Radiobutton(format_group, text=fmt.upper(), variable=self.output_format, value=fmt).pack(side="left", padx=5)
        
        ttk.Label(options_frame, text="压缩质量:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        q_frame = ttk.Frame(options_frame); q_frame.grid(row=1, column=1, columnspan=3, sticky="ew")
        q_frame.columnconfigure(0, weight=1)
        ttk.Scale(q_frame, from_=1, to=100, orient="horizontal", variable=self.quality, command=lambda v: self.quality_label.config(text=f"{int(float(v))}%")).grid(row=0, column=0, sticky="ew")
        self.quality_label = ttk.Label(q_frame, text=f"{self.quality.get()}%", width=5); self.quality_label.grid(row=0, column=1, padx=5)

        # --- Dynamic Width Frame ---
        self.width_frame = ttk.Frame(options_frame)
        self.width_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(self.width_frame, text="目标宽度 (选填):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Entry(self.width_frame, textvariable=self.width, width=10).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(self.width_frame, text="px (留空则保持原始尺寸)").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        # --- Dynamic ICO Frame ---
        self.ico_options_frame = ttk.Frame(options_frame)
        self.ico_options_frame.grid(row=2, column=0, columnspan=4, sticky="ew") # Placed in same row as width
        ttk.Label(self.ico_options_frame, text="ICO 尺寸:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ico_size_group = ttk.Frame(self.ico_options_frame)
        ico_size_group.grid(row=0, column=1, sticky="w")
        for size in ICO_SIZES:
            ttk.Checkbutton(ico_size_group, text=str(size),
                            variable=self.ico_size_vars[size]).pack(side="left", padx=4)
        ttk.Label(self.ico_options_frame,
                  text="（可多选；Windows 按场景自动挑：任务栏 32、资源管理器 16/48、预览 256）"
                  ).grid(row=1, column=1, padx=5, sticky="w")

        # --- Save Mode and Other UI ---
        ttk.Label(options_frame, text="保存模式:").grid(row=4, column=0, padx=5, pady=10, sticky="w")
        save_mode_frame = ttk.Frame(options_frame)
        save_mode_frame.grid(row=4, column=1, columnspan=3, sticky="w", pady=5)
        for val, txt in [("separate", "保存到单独文件夹"), ("source", "保存到源文件夹 (覆盖)"), ("source_delete", "转换并删除源文件")]:
            ttk.Radiobutton(save_mode_frame, text=txt, variable=self.save_mode, value=val).pack(anchor="w")

        filter_frame = ttk.Labelframe(self, text="源文件过滤", padding="10"); filter_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        btn_frame = ttk.Frame(filter_frame); btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="全选", command=lambda: self._select_all_filters(True)).pack(side="left")
        ttk.Button(btn_frame, text="全不选", command=lambda: self._select_all_filters(False)).pack(side="left", padx=5)
        self.filter_checkbox_frame = ttk.Frame(filter_frame); self.filter_checkbox_frame.pack(fill="x")
        
        log_frame = ttk.Labelframe(self, text="处理日志", padding="10"); log_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        log_frame.columnconfigure(0, weight=1); log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10); self.log_text.grid(row=0, column=0, sticky="nsew")

        action_frame = ttk.Frame(self, padding="10"); action_frame.grid(row=4, column=0, sticky="e")
        self.start_button = ttk.Button(action_frame, text="开始处理", command=self._start_processing, style="Accent.TButton"); self.start_button.pack()
        style = ttk.Style(); style.theme_use('clam'); style.configure("Accent.TButton", foreground="white", background="#0078D7")

    def _on_format_change(self, *args):
        is_ico = self.output_format.get() == "ico"
        if is_ico:
            self.width_frame.grid_remove()
            self.ico_options_frame.grid()
        else:
            self.width_frame.grid()
            self.ico_options_frame.grid_remove()

    def _load_config(self):
        current_path = os.getcwd() # ### 修改点 1 ###: 总是先获取当前工作目录
        try:
            with open(CONFIG_FILE, 'r') as f: config = json.load(f)
            self.save_mode.set(config.get("save_mode", "separate"))
            self.output_format.set(config.get("output_format", "jpg"))
            self.quality.set(config.get("quality", 80))
            self.width.set(config.get("width", ""))
            saved_sizes = config.get("ico_sizes")
            if isinstance(saved_sizes, list) and saved_sizes:
                for s, var in self.ico_size_vars.items():
                    var.set(s in saved_sizes)
            # 旧配置里的 ico_size（单个整数）**故意忽略** —— 那正是被修掉的 bug
            self.saved_filters_config = config.get("source_filter", {})
            self.history = config.get("history", [])
            print(f"成功加载配置文件。")
        except (FileNotFoundError, json.JSONDecodeError):
            print("未找到配置文件，使用默认设置。")
        
        # ### 修改点 1 (续) ###: 设置当前目录并更新历史记录
        self.source_dir.set(current_path)
        self._update_history(current_path)

    def _save_config(self):
        # ### 修改点 ###: 保存前确保当前目录在历史记录首位
        self._update_history(self.source_dir.get())
        current_filters = {ext: var.get() for ext, var in self.filter_vars.items()}
        self.saved_filters_config.update(current_filters)
        config = {
            "save_mode": self.save_mode.get(), "output_format": self.output_format.get(),
            "quality": self.quality.get(), "width": self.width.get(),
            "ico_sizes": self._checked_ico_sizes(),
            "source_filter": self.saved_filters_config, "history": self.history
        }
        try:
            # 懒加载：只有真正写入配置时才创建数据目录
            if not os.path.isdir(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
        except IOError as e: print(f"错误：无法保存配置文件: {e}")

    def _on_closing(self): self._save_config(); self.destroy()

    def _update_history(self, new_path):
        if new_path in self.history: self.history.remove(new_path)
        self.history.insert(0, new_path)
        self.history = self.history[:HISTORY_LIMIT]
        self.history_combobox['values'] = self.history

    def _handle_folder_selection(self, folder_path):
        self.source_dir.set(folder_path)
        self.log_text.delete('1.0', tk.END)
        print(f"已选择文件夹: {folder_path}")
        self._update_filter_checkboxes()
        self._update_history(folder_path)
        
    def _on_history_select(self, event=None):
        self._handle_folder_selection(self.source_dir.get())

    def _update_filter_checkboxes(self):
        for w in self.filter_checkbox_frame.winfo_children(): w.destroy()
        self.filter_vars.clear()
        source_dir = self.source_dir.get()
        if not os.path.isdir(source_dir):
            ttk.Label(self.filter_checkbox_frame, text="请选择一个有效的文件夹。").pack(); return
        supported = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')
        exts = {os.path.splitext(f)[1].lower() for f in os.listdir(source_dir) if os.path.splitext(f)[1].lower() in supported}
        if not exts:
            ttk.Label(self.filter_checkbox_frame, text="未在该目录中找到支持的图片。").pack(); return
        for ext in sorted(list(exts)):
            var = tk.BooleanVar(value=self.saved_filters_config.get(ext, True))
            self.filter_vars[ext] = var
            ttk.Checkbutton(self.filter_checkbox_frame, text=ext.upper(), variable=var).pack(side="left", padx=5)

    def _select_all_filters(self, state):
        for var in self.filter_vars.values(): var.set(state)

    def _checked_ico_sizes(self):
        """用户勾选的 ico 尺寸（升序）。一个都没勾就退回全部标准尺寸。"""
        picked = [s for s, var in self.ico_size_vars.items() if var.get()]
        return sorted(picked) or list(ICO_SIZES_DEFAULT)

    def _enable_drag_and_drop(self):
        if WINDND_AVAILABLE:
            hook_func = lambda f: self._handle_folder_selection(os.path.dirname(f[0].decode('gbk')) if os.path.isfile(f[0].decode('gbk')) else f[0].decode('gbk'))
            windnd.hook_dropfiles(self, func=hook_func)

    def _select_folder(self):
        folder = filedialog.askdirectory(initialdir=self.source_dir.get())
        if folder: self._handle_folder_selection(folder)

    def _start_processing(self):
        if not os.path.isdir(self.source_dir.get()): messagebox.showerror("错误", "请选择有效的文件夹。"); return
        
        # ### 修改点 2 ###: 移除了危险操作的二次确认
        # if self.save_mode.get() == "source_delete" and not messagebox.askokcancel("危险操作确认", "!!! 警告 !!!\n\n您选择了【转换并删除源文件】模式。\n此操作将永久删除原始图片，无法撤销。\n\n您确定要继续吗？"): return
        
        if not any(v.get() for v in self.filter_vars.values()): messagebox.showwarning("提示", "未选择任何文件类型。"); return
        self.start_button.config(state="disabled", text="正在处理...")
        self.log_text.delete('1.0', tk.END)
        threading.Thread(target=self._process_thread_func, daemon=True).start()

    def _process_thread_func(self):
        fmt = self.output_format.get()
        params = {
            "source_dir": self.source_dir.get(), "output_format": fmt, "quality": self.quality.get(),
            "width": None if fmt == 'ico' else (int(self.width.get()) if self.width.get().isdigit() else None),
            "source_filter": [ext for ext, var in self.filter_vars.items() if var.get()],
            "save_mode": self.save_mode.get(), "ico_sizes": self._checked_ico_sizes()
        }
        original_stdout = sys.stdout; sys.stdout = TextRedirector(self.log_text)
        try:
            run_tasks(**params)
        except Exception as e: print(f"\n[严重错误] 处理中发生意外: {e}")
        finally: sys.stdout = original_stdout; self.start_button.config(state="normal", text="开始处理")

if __name__ == "__main__":
    app = ImageCompressorApp()
    sys.stdout = TextRedirector(app.log_text)
    print("--- 欢迎使用智能图片压缩工具 ---")
    if WINDND_AVAILABLE: print("提示: 您可直接拖动文件夹到此窗口。")
    app.mainloop()