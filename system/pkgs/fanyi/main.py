import sys
import os
import time
import threading
import queue
import tkinter as tk
from tkinter import scrolledtext, font, messagebox

# --- 依赖库检查 ---
try:
    import pyperclip
    from pynput.keyboard import Key, Controller, Listener
    from googletrans import Translator
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "缺少依赖库",
        f"程序无法启动，因为缺少必要的库: {e.name}\n\n"
        "请打开终端或CMD，运行以下命令来安装:\n"
        "pip install pyperclip pynput googletrans==4.0.0rc1"
    )
    sys.exit(1)

# --- 路径获取 ---
application_path = os.path.dirname(sys.executable) if 'python' not in os.path.basename(sys.executable).lower() else os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.path.abspath(sys.path[0])
# 宿主 moss 注入的插件专属数据目录 (= user_data/state/fanyi)；老 pa 的 PA_* 与插件目录作兜底
DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.environ.get('PA_PLUGIN_DATA_DIR') or os.path.join(os.environ.get("MOSS_HOME") or os.path.expanduser("~"),
              "user_data", "state", "fanyi")
CACHE_FILE_PATH = os.path.join(DATA_DIR, 'translation_cache.txt')

# --- 全局变量和配置 ---
keyboard = Controller()
translator = Translator()

DOUBLE_CLICK_INTERVAL = 0.3
COOLDOWN_SECONDS = 1

log_queue = queue.Queue()

listener_thread = None
listener_object = None
is_action_running = False
last_ctrl_press_time = 0

# --- 缓存相关 ---
translation_cache = {}

def log(message):
    log_queue.put(message)

def load_cache():
    """从 translation_cache.txt 加载缓存到内存"""
    global translation_cache
    try:
        with open(CACHE_FILE_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        count = 0
        for line in lines:
            parts = line.strip().split('|')
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                if key and value:
                    translation_cache[key] = value
                    translation_cache[value] = key
                    count += 1
        log(f"[SYSTEM] 成功从 {CACHE_FILE_PATH} 加载 {count} 条双向缓存。")
    except FileNotFoundError:
        log(f"[SYSTEM] 缓存文件不存在，将在首次翻译后自动创建。")
    except Exception as e:
        log(f"[ERROR] 加载缓存文件失败: {e}")

def update_cache(original_text, translated_text):
    """更新内存缓存并追加到文件"""
    global translation_cache
    translation_cache[original_text] = translated_text
    translation_cache[translated_text] = original_text
    log(f"[CACHE] 缓存已更新: {original_text} <=> {translated_text}")
    
    try:
        # 懒加载：只有真正写入缓存时才创建数据目录
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{original_text} | {translated_text}\n")
    except Exception as e:
        log(f"[ERROR] 写入缓存文件失败: {e}")

# --- 核心翻译逻辑 ---
def perform_translation_action():
    global keyboard, translator

    log("\n[INFO] 检测到双击Ctrl，开始执行翻译流程...")

    try:
        original_clipboard_content = pyperclip.paste()
    except Exception:
        original_clipboard_content = ""

    log("[STEP 1] 模拟 Ctrl+A+X (全选并剪切)...")
    with keyboard.pressed(Key.ctrl):
        keyboard.press('a')
        keyboard.release('a')
    time.sleep(0.15)
    with keyboard.pressed(Key.ctrl):
        keyboard.press('x')
        keyboard.release('x')
    time.sleep(0.15)

    try:
        text_to_translate = pyperclip.paste().strip()
    except Exception:
        text_to_translate = ""
    
    translated_text = None
    
    # <<< --- 关键改动：移除了 "!= original_clipboard_content" 的判断 --- >>>
    if text_to_translate and text_to_translate.strip():
        log(f"[STEP 2] 获取到文本: '{text_to_translate[:50]}...'")

        if text_to_translate in translation_cache:
            translated_text = translation_cache[text_to_translate]
            log(f"[CACHE] 命中缓存 -> '{translated_text[:50]}...'")
        else:
            try:
                log("[NETWORK] 缓存未命中，正在进行网络翻译...")
                detected_lang = translator.detect(text_to_translate).lang
                target_lang = 'en' if detected_lang.lower().startswith('zh') else 'zh-cn'
                log(f"       - 语言: {detected_lang} -> {target_lang}")

                result = translator.translate(text_to_translate, dest=target_lang)
                translated_text = result.text
                log(f"[NETWORK] 翻译完成 -> '{translated_text[:50]}...'")
                
                update_cache(text_to_translate, translated_text)

            except Exception as e:
                log(f"[ERROR] 网络翻译失败: {e}")
                pyperclip.copy(text_to_translate)

        if translated_text:
            pyperclip.copy(translated_text)
            log("[STEP 3] 模拟 Ctrl+V (粘贴)...")
            with keyboard.pressed(Key.ctrl):
                keyboard.press('v')
                keyboard.release('v')
            log("[SUCCESS] 任务完成！")
        else:
            log("[FAIL] 翻译失败，将原文粘贴回去。")
            with keyboard.pressed(Key.ctrl):
                keyboard.press('v')
                keyboard.release('v')
            time.sleep(0.1)
            pyperclip.copy(original_clipboard_content)
    else:
        log("[FAIL] 未获取到文本，操作中断。")
        pyperclip.copy(original_clipboard_content)

    log(f"[INFO] 进入 {COOLDOWN_SECONDS} 秒冷却时间...")
    time.sleep(COOLDOWN_SECONDS)

# (以下代码与上一版相同，无需修改)
def action_thread_wrapper():
    global is_action_running
    try:
        perform_translation_action()
    finally:
        is_action_running = False
        log("[INFO] 任务流程结束，可以再次触发。")

def on_press(key):
    global last_ctrl_press_time, is_action_running
    if is_action_running:
        return
    if key in (Key.ctrl_l, Key.ctrl_r):
        current_time = time.time()
        if current_time - last_ctrl_press_time < DOUBLE_CLICK_INTERVAL:
            last_ctrl_press_time = 0
            is_action_running = True
            worker_thread = threading.Thread(target=action_thread_wrapper, daemon=True)
            worker_thread.start()
        else:
            last_ctrl_press_time = current_time

def run_listener():
    global listener_object
    log("[SYSTEM] 键盘监听器已启动。")
    listener_object = Listener(on_press=on_press)
    listener_object.run()
    log("[SYSTEM] 键盘监听器已停止。")

class TranslatorApp:
    def __init__(self, master):
        self.master = master
        master.title("快捷翻译工具 (带缓存)")
        master.geometry("450x380")
        master.attributes('-topmost', True)
        self.default_font = font.Font(family="Microsoft YaHei", size=10)
        self.status_font = font.Font(family="Microsoft YaHei", size=12, weight="bold")
        control_frame = tk.Frame(master)
        control_frame.pack(fill=tk.X, padx=10, pady=10)
        status_label = tk.Label(control_frame, text="工作状态:", font=self.default_font)
        status_label.pack(side=tk.LEFT, padx=(0, 5))
        self.status_var = tk.StringVar(value="已停止")
        self.status_display = tk.Label(control_frame, textvariable=self.status_var, font=self.status_font, fg="darkred")
        self.status_display.pack(side=tk.LEFT, padx=5)
        self.start_button = tk.Button(control_frame, text="启动", command=self.start_listener, font=self.default_font)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = tk.Button(control_frame, text="停止", command=self.stop_listener, state=tk.DISABLED, font=self.default_font)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        tip_label = tk.Label(master, text="▲ 触发方式: 双击 Ctrl   (选中文字 → 翻译 → 自动粘贴)", font=self.default_font, fg="#24365C", anchor="w")
        tip_label.pack(fill=tk.X, padx=10, pady=(0, 4))
        log_frame = tk.Frame(master)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_widget = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Courier New", 9), state=tk.DISABLED)
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        self.process_log_queue()

    def update_log(self, message):
        self.log_widget.config(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + '\n')
        self.log_widget.see(tk.END)
        self.log_widget.config(state=tk.DISABLED)

    def process_log_queue(self):
        try:
            while True:
                message = log_queue.get_nowait()
                self.update_log(message)
        except queue.Empty:
            pass
        self.master.after(100, self.process_log_queue)

    def start_listener(self):
        global listener_thread
        if listener_thread and listener_thread.is_alive():
            log("[WARNING] 监听器已在运行中。")
            return
        listener_thread = threading.Thread(target=run_listener, daemon=True)
        listener_thread.start()
        self.status_var.set("正在运行")
        self.status_display.config(fg="darkgreen")
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

    def stop_listener(self):
        global listener_object
        if listener_object:
            listener_object.stop()
            listener_object = None
        self.status_var.set("已停止")
        self.status_display.config(fg="darkred")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

if __name__ == "__main__":
    load_cache()

    root = tk.Tk()
    app = TranslatorApp(root)
    
    log_queue.put("欢迎使用快捷翻译工具！")
    log_queue.put("触发方式: 双击 Ctrl 键 (选中文字 → 翻译 → 自动粘贴)")
    log_queue.put("请点击“启动”按钮开始监听。")
    
    root.mainloop()