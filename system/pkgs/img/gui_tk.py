# -*- coding: utf-8 -*-
"""图片工具 —— Tkinter 界面（退路）。

WebView2 / pywebview 起不来时走这里（旧机器、精简系统可能没有 WebView2）。
界面与旧版 `QuickTools/bin/soft/img/main.py` 一致，业务全部改调 `core.py`，
所以两条路的处理结果一定相同。

保留它还有一个只有它能做到的原因：**拖放文件夹**。
WebView2 里拿不到拖进来的文件的**真实路径**（Chromium 的 File 对象不给 path，
pywebview 也没开放 AllowExternalDrop），所以 WebView 界面只能用「选择…」按钮。
"""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import core

try:
    import windnd
    WINDND_AVAILABLE = True
except ImportError:
    WINDND_AVAILABLE = False


class ImageCompressorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("智能图片压缩工具")
        self.geometry("700x780")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.config_data, load_msg = core.load_config()
        self.startup_msg = load_msg

        # --- Variables ---
        self.source_dir = tk.StringVar()
        self.output_format = tk.StringVar(value=self.config_data['output_format'])
        self.quality = tk.IntVar(value=self.config_data['quality'])
        self.width = tk.StringVar(value=self.config_data['width'])
        self.save_mode = tk.StringVar(value=self.config_data['save_mode'])
        self.ico_size_vars = {s: tk.BooleanVar(value=s in self.config_data['ico_sizes'])
                              for s in core.ICO_SIZES}
        self.filter_vars = {}
        self.saved_filters_config = dict(self.config_data['source_filter'])
        self.history = list(self.config_data['history'])
        self.current_job = None

        # --- UI Init ---
        self._create_widgets()
        self._load_initial_state()
        self._enable_drag_and_drop()
        self._update_filter_checkboxes()
        self._on_format_change()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ------------------------------------------------------------------ 构建
    def _create_widgets(self):
        # --- Source Folder with History ---
        source_frame = ttk.Labelframe(self, text="源文件夹", padding="10")
        source_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        source_frame.columnconfigure(0, weight=1)
        self.history_combobox = ttk.Combobox(source_frame, textvariable=self.source_dir,
                                             state="readonly", values=self.history)
        self.history_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.history_combobox.bind("<<ComboboxSelected>>", self._on_history_select)
        ttk.Button(source_frame, text="选择...", command=self._select_folder) \
            .grid(row=0, column=1, padx=5, pady=5)

        # --- Options Frame ---
        options_frame = ttk.Labelframe(self, text="压缩与保存选项", padding="10")
        options_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        options_frame.columnconfigure(1, weight=1)

        self.output_format.trace_add("write", self._on_format_change)
        ttk.Label(options_frame, text="目标格式:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        format_group = ttk.Frame(options_frame)
        format_group.grid(row=0, column=1, columnspan=3, sticky="w")
        for fmt in core.FORMATS:
            ttk.Radiobutton(format_group, text=fmt.upper(), variable=self.output_format,
                            value=fmt).pack(side="left", padx=5)

        ttk.Label(options_frame, text="压缩质量:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        q_frame = ttk.Frame(options_frame)
        q_frame.grid(row=1, column=1, columnspan=3, sticky="ew")
        q_frame.columnconfigure(0, weight=1)
        ttk.Scale(q_frame, from_=1, to=100, orient="horizontal", variable=self.quality,
                  command=lambda v: self.quality_label.config(text=f"{int(float(v))}%")) \
            .grid(row=0, column=0, sticky="ew")
        self.quality_label = ttk.Label(q_frame, text=f"{self.quality.get()}%", width=5)
        self.quality_label.grid(row=0, column=1, padx=5)

        # --- Dynamic Width Frame ---
        self.width_frame = ttk.Frame(options_frame)
        self.width_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(self.width_frame, text="目标宽度 (选填):") \
            .grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Entry(self.width_frame, textvariable=self.width, width=10) \
            .grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(self.width_frame, text="px (留空则保持原始尺寸)") \
            .grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # --- Dynamic ICO Frame ---
        self.ico_options_frame = ttk.Frame(options_frame)
        self.ico_options_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(self.ico_options_frame, text="ICO 尺寸:") \
            .grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ico_size_group = ttk.Frame(self.ico_options_frame)
        ico_size_group.grid(row=0, column=1, sticky="w")
        for size in core.ICO_SIZES:
            ttk.Checkbutton(ico_size_group, text=str(size),
                            variable=self.ico_size_vars[size]).pack(side="left", padx=4)
        ttk.Label(self.ico_options_frame,
                  text="（可多选；Windows 按场景自动挑：任务栏 32、资源管理器 16/48、预览 256）") \
            .grid(row=1, column=1, padx=5, sticky="w")

        # --- Save Mode and Other UI ---
        ttk.Label(options_frame, text="保存模式:") \
            .grid(row=4, column=0, padx=5, pady=10, sticky="w")
        save_mode_frame = ttk.Frame(options_frame)
        save_mode_frame.grid(row=4, column=1, columnspan=3, sticky="w", pady=5)
        for val, txt in [("separate", "保存到单独文件夹"),
                         ("source", "保存到源文件夹 (覆盖)"),
                         ("source_delete", "转换并删除源文件")]:
            ttk.Radiobutton(save_mode_frame, text=txt, variable=self.save_mode,
                            value=val).pack(anchor="w")

        filter_frame = ttk.Labelframe(self, text="源文件过滤", padding="10")
        filter_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        btn_frame = ttk.Frame(filter_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="全选",
                   command=lambda: self._select_all_filters(True)).pack(side="left")
        ttk.Button(btn_frame, text="全不选",
                   command=lambda: self._select_all_filters(False)).pack(side="left", padx=5)
        self.filter_checkbox_frame = ttk.Frame(filter_frame)
        self.filter_checkbox_frame.pack(fill="x")

        log_frame = ttk.Labelframe(self, text="处理日志", padding="10")
        log_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        action_frame = ttk.Frame(self, padding="10")
        action_frame.grid(row=4, column=0, sticky="e")
        self.start_button = ttk.Button(action_frame, text="开始处理",
                                       command=self._start_processing, style="Accent.TButton")
        self.start_button.pack()
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Accent.TButton", foreground="white", background="#0078D7")

    # ------------------------------------------------------------------ 状态
    def _load_initial_state(self):
        """旧版：打开就把当前工作目录设成源目录，并写进历史。"""
        current_path = os.getcwd()
        self.source_dir.set(current_path)
        core.push_history(self.config_data, current_path)
        self.history = list(self.config_data['history'])
        self.history_combobox['values'] = self.history
        print(self.startup_msg)

    def _on_format_change(self, *args):
        if self.output_format.get() == "ico":
            self.width_frame.grid_remove()
            self.ico_options_frame.grid()
        else:
            self.width_frame.grid()
            self.ico_options_frame.grid_remove()

    def _collect_config(self):
        cfg = {
            "save_mode": self.save_mode.get(),
            "output_format": self.output_format.get(),
            "quality": self.quality.get(),
            "width": self.width.get(),
            "ico_sizes": self._checked_ico_sizes(),
            "source_filter": dict(self.saved_filters_config),
            "history": list(self.history),
        }
        cfg['source_filter'].update({e: v.get() for e, v in self.filter_vars.items()})
        return core.normalize_config(cfg)

    def _save_config(self):
        self.saved_filters_config.update({e: v.get() for e, v in self.filter_vars.items()})
        core.push_history(self.config_data, self.source_dir.get())
        self.history = list(self.config_data['history'])
        self.history_combobox['values'] = self.history
        ok, msg = core.save_config(self._collect_config())
        if not ok:
            print(msg)

    def _on_closing(self):
        self._save_config()
        self.destroy()

    # ------------------------------------------------------------------ 目录
    def _handle_folder_selection(self, folder_path):
        self.source_dir.set(folder_path)
        self.log_text.delete('1.0', tk.END)
        print(f"已选择文件夹: {folder_path}")
        self._update_filter_checkboxes()
        core.push_history(self.config_data, folder_path)
        self.history = list(self.config_data['history'])
        self.history_combobox['values'] = self.history

    def _on_history_select(self, event=None):
        self._handle_folder_selection(self.source_dir.get())

    def _update_filter_checkboxes(self):
        for w in self.filter_checkbox_frame.winfo_children():
            w.destroy()
        self.filter_vars.clear()
        got = core.scan_source(self.source_dir.get())
        if not got['ok']:
            ttk.Label(self.filter_checkbox_frame, text=got['message']).pack()
            return
        if not got['exts']:
            ttk.Label(self.filter_checkbox_frame, text=got['message']).pack()
            return
        for item in got['exts']:
            ext = item['ext']
            var = tk.BooleanVar(value=self.saved_filters_config.get(ext, True))
            self.filter_vars[ext] = var
            ttk.Checkbutton(self.filter_checkbox_frame, text=ext.upper(),
                            variable=var).pack(side="left", padx=5)

    def _select_all_filters(self, state):
        for var in self.filter_vars.values():
            var.set(state)

    def _checked_ico_sizes(self):
        return core.checked_ico_sizes([s for s, var in self.ico_size_vars.items() if var.get()])

    def _enable_drag_and_drop(self):
        if not WINDND_AVAILABLE:
            return
        def hook(files):
            path = files[0].decode('gbk')
            self._handle_folder_selection(os.path.dirname(path) if os.path.isfile(path) else path)
        windnd.hook_dropfiles(self, func=hook)

    def _select_folder(self):
        folder = filedialog.askdirectory(initialdir=self.source_dir.get())
        if folder:
            self._handle_folder_selection(folder)

    # ------------------------------------------------------------------ 运行
    def _start_processing(self):
        cfg = self._collect_config()
        params = core.build_params(cfg, self.source_dir.get())
        bad = core.validate(params)
        if bad:
            messagebox.showerror("错误", bad)
            return

        # ### 修改点 2 ###: 移除了危险操作的二次确认（照抄旧版，别再"好心"加回来）
        self.start_button.config(state="disabled", text="正在处理...")
        self.log_text.delete('1.0', tk.END)
        self.current_job = core.Job(params)
        self.current_job.start()
        self.after(120, self._drain_job)

    def _drain_job(self):
        """Tk 主线程里轮询作业输出 —— 和 WebView 界面同一套 Job，不用全局 stdout 重定向。"""
        job = self.current_job
        if job is None:
            return
        got = job.poll()
        self.log_text.delete('1.0', tk.END)
        self.log_text.insert(tk.END, got['output'] or '')
        self.log_text.see(tk.END)
        if got['running']:
            self.after(120, self._drain_job)
        else:
            self.start_button.config(state="normal", text="开始处理")
            self._save_config()


def run_gui():
    app = ImageCompressorApp()
    print("--- 欢迎使用智能图片压缩工具 ---")
    if WINDND_AVAILABLE:
        print("提示: 您可直接拖动文件夹到此窗口。")
    app.mainloop()


if __name__ == '__main__':
    run_gui()
