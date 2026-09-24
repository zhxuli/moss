# -*- coding: utf-8 -*-
"""图片工具 —— 业务逻辑（与界面无关，唯一实现处）。

界面有两个，都只调用这里，**不许各自再实现一遍业务**：
    gui_web.py   WebView 界面（首选，照抄 exec 的做法）
    gui_tk.py    Tkinter 界面（WebView 起不来时的退路）

★ 迁移说明：本文件是旧版 `QuickTools/bin/soft/img/main.py` 里
  「核心处理逻辑」那一段的搬家，**行为与提示文案逐字保持一致**；
  界面代码从业务里剥出去，是为了让两套界面共用同一份实现。

★ 旧版用 `sys.stdout = TextRedirector(...)` 把日志抓进控件 ——
  那是**全局替换**，两套界面并存会互相打架。这里改成把 `log` 回调
  显式传进来，不动 `sys.stdout`。
"""
import json
import os
import sys
import threading
import time
import uuid

from PIL import Image

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

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')
FORMATS = ['jpg', 'png', 'webp', 'ico']
SAVE_MODES = ['separate', 'source', 'source_delete']

DEFAULT_CONFIG = {
    'save_mode': 'separate',
    'output_format': 'jpg',
    'quality': 80,
    'width': '',
    'ico_sizes': list(ICO_SIZES_DEFAULT),
    'source_filter': {},
    'history': [],
}


def _noop(text):
    pass


# ==============================================================================
# 配置读写（旧版这些是 Tk 变量，现在改成纯 dict —— 两套界面都用得上）
# ==============================================================================

def normalize_config(cfg):
    """把任意来源的配置补齐成一份可用的配置。

    旧配置里的 `ico_size`（单个整数）**故意忽略** —— 那正是被修掉的 bug。
    """
    out = dict(DEFAULT_CONFIG)
    if not isinstance(cfg, dict):
        return out
    if cfg.get('save_mode') in SAVE_MODES:
        out['save_mode'] = cfg['save_mode']
    if cfg.get('output_format') in FORMATS:
        out['output_format'] = cfg['output_format']
    try:
        out['quality'] = max(1, min(100, int(cfg.get('quality', 80))))
    except (TypeError, ValueError):
        pass
    out['width'] = str(cfg.get('width') or '')
    sizes = cfg.get('ico_sizes')
    if isinstance(sizes, list) and sizes:
        picked = []
        for s in sizes:
            try:
                s = int(s)
            except (TypeError, ValueError):
                continue
            if s in ICO_SIZES and s not in picked:
                picked.append(s)
        if picked:
            out['ico_sizes'] = sorted(picked)
    sf = cfg.get('source_filter')
    if isinstance(sf, dict):
        out['source_filter'] = {str(k): bool(v) for k, v in sf.items()}
    hist = cfg.get('history')
    if isinstance(hist, list):
        out['history'] = [str(p) for p in hist if p][:HISTORY_LIMIT]
    return out


def load_config():
    """读配置。返回 (config, message)；读不到/坏了就给默认值，并带出原因。"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return normalize_config(json.load(f)), '成功加载配置文件。'
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG), '未找到配置文件，使用默认设置。'
    except (json.JSONDecodeError, OSError) as e:
        return dict(DEFAULT_CONFIG), '配置文件读取失败（%s），使用默认设置。' % e


def save_config(cfg):
    """写配置。返回 (ok, message)。"""
    cfg = normalize_config(cfg)
    try:
        # 懒加载：只有真正写入配置时才创建数据目录
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True, '配置已保存。'
    except OSError as e:
        return False, '错误：无法保存配置文件: %s' % e


def push_history(cfg, path):
    """把 path 提到历史最前面（就地改 cfg，返回 cfg）。"""
    path = str(path or '')
    if not path:
        return cfg
    hist = [p for p in cfg.get('history', []) if p != path]
    hist.insert(0, path)
    cfg['history'] = hist[:HISTORY_LIMIT]
    return cfg


def checked_ico_sizes(picked):
    """用户勾选的 ico 尺寸（升序）。一个都没勾就退回全部标准尺寸。"""
    got = []
    for s in (picked or []):
        try:
            s = int(s)
        except (TypeError, ValueError):
            continue
        if s in ICO_SIZES and s not in got:
            got.append(s)
    return sorted(got) or list(ICO_SIZES_DEFAULT)


# ==============================================================================
# 目录扫描
# ==============================================================================

def scan_source(source_dir):
    """扫一遍源目录：有哪些受支持的扩展名、各多少个文件。

    旧版 Tk 界面就是拿这个结果去动态生成过滤勾选框的，行为照旧。
    """
    if not source_dir or not os.path.isdir(source_dir):
        return {'ok': False, 'message': '请选择一个有效的文件夹。', 'exts': [], 'count': 0}

    counts = {}
    for name in os.listdir(source_dir):
        if not os.path.isfile(os.path.join(source_dir, name)):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in SUPPORTED_EXTS:
            counts[ext] = counts.get(ext, 0) + 1
    exts = [{'ext': e, 'count': counts[e]} for e in sorted(counts)]
    message = '' if exts else '未在该目录中找到支持的图片。'
    return {'ok': True, 'exts': exts, 'count': sum(counts.values()), 'message': message}


# ==============================================================================
# 核心处理逻辑（照抄旧版，只把 print 换成注入的 log）
# ==============================================================================

def process_single_image(filepath, output_format, quality, width, output_dir, save_mode,
                         ico_sizes, log=_noop):
    """处理一张图。返回 True/False（旧版只打印不返回，这里补一个给统计用）。"""
    name = os.path.basename(filepath)
    try:
        with Image.open(filepath) as img:
            log(f"\n- 正在处理: {name} ({img.width}x{img.height})\n")
            img_copy = img.copy()

        if output_format != 'ico' and width and img_copy.width > width:
            aspect_ratio = img_copy.height / img_copy.width
            new_height = int(width * aspect_ratio)
            log(f"  - 调整尺寸为: {width}x{new_height}\n")
            img_copy = img_copy.resize((width, new_height), Image.Resampling.LANCZOS)

        base_name, _ = os.path.splitext(name)
        output_filename = f"{base_name}.{output_format}"
        output_path = os.path.join(output_dir, output_filename)

        if output_format == 'jpg' and img_copy.mode in ('RGBA', 'P'):
            log("  - 转换透明背景为白色\n")
            background = Image.new('RGB', img_copy.size, (255, 255, 255))
            if 'A' in img_copy.getbands():
                background.paste(img_copy, (0, 0), img_copy.getchannel('A'))
            else:
                background.paste(img_copy, (0, 0))
            img_copy = background
        elif img_copy.mode != 'RGB' and output_format == 'jpg':
            img_copy = img_copy.convert('RGB')

        save_options = {}
        if output_format in ('jpg', 'jpeg', 'webp'):
            save_options['quality'] = quality
        elif output_format == 'png':
            save_options['compress_level'] = int((100 - quality) / 100 * 9)
            save_options['optimize'] = True
        elif output_format == 'ico':
            sizes = sorted({int(s) for s in (ico_sizes or ICO_SIZES_DEFAULT) if s})
            log("  - ICO 多分辨率: %s\n" % ", ".join(str(s) for s in sizes))
            save_options['sizes'] = [(s, s) for s in sizes]

        img_copy.save(output_path, **save_options)
        new_size = os.path.getsize(output_path)
        log(f"[已保存] 至: {output_path} ({new_size/1024:.1f} KB)\n")

        if save_mode == "source_delete" and \
                os.path.abspath(filepath).lower() != os.path.abspath(output_path).lower():
            os.remove(filepath)
            log(f"  - [已删除] 源文件: {name}\n")
        return True
    except Exception as e:
        log(f"[错误] 处理 {name} 时出错: {e}\n")
        return False


def run_files(files, output_format, quality, width, output_dir, save_mode, ico_sizes,
              log=_noop, cancel=None, total=None, output_dir_per_file=False):
    """对一份**已确定**的文件清单干活。

    界面模式（给一个目录 + 扩展名过滤）和命令行模式（给通配符）
    最后都归到这里 —— 处理逻辑只能有一份。

    `output_dir_per_file=True`：每个文件写回**它自己所在的目录**。
    ★ 文件清单里的文件可能来自不同目录（拖进来的、多选的），
      这时"保存到源目录"必须按文件各自算，不能全塞进一个目录。
    """
    started = time.time()
    files = [str(f) for f in files]
    if not files:
        log("\n提示: 未找到符合条件的图片。\n")
        return {'total': 0, 'done': 0, 'failed': 0, 'output_dir': output_dir,
                'elapsed': time.time() - started, 'cancelled': False}

    log(f"\n找到 {len(files)} 个文件，开始处理...\n")
    done = failed = 0
    stopped = False
    for i, path in enumerate(files):
        if cancel is not None and cancel.is_set():
            log("\n[已取消] 用户中止了处理。\n")
            stopped = True
            break
        log(f"--- [进度: {i+1}/{len(files)}] ---\n")
        target = os.path.dirname(path) if output_dir_per_file else output_dir
        if target and not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        if process_single_image(path, output_format, quality, width, target,
                                save_mode, ico_sizes, log=log):
            done += 1
        else:
            failed += 1

    if not stopped:
        log("\n=====================\n所有任务已成功完成。\n=====================\n")

    return {'total': total if total is not None else len(files), 'done': done, 'failed': failed,
            'output_dir': output_dir, 'elapsed': time.time() - started, 'cancelled': stopped}


def list_images(source_dir, source_filter=None):
    """列出目录下符合扩展名过滤的图片（绝对路径，按名字排序）。"""
    picked = set(normalize_exts(source_filter) or SUPPORTED_EXTS)
    try:
        names = os.listdir(source_dir)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        full = os.path.join(source_dir, name)
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in picked:
            out.append(full)
    return out


def run_tasks(source_dir, output_format, quality, width, source_filter, save_mode, ico_sizes,
              log=_noop, cancel=None):
    """界面「文件夹模式」的入口：扫一个目录，按扩展名过滤，然后交给 run_files。"""
    output_dir = source_dir if save_mode in ["source", "source_delete"] \
        else os.path.join(source_dir, "compressed_output")
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    return run_files(list_images(source_dir, source_filter), output_format, quality, width,
                     output_dir, save_mode, ico_sizes, log=log, cancel=cancel)


# ==============================================================================
# 文件清单模式（多选文件 / 拖放）
# ==============================================================================

# 拖进来的文件夹展开成清单时最多收这么多个文件，防止手一抖拖进整个磁盘
MAX_EXPAND = 2000


def file_entry(path):
    """文件清单里的一行。拿不到 stat 就是"文件不在了"（界面画红）。"""
    full = os.path.abspath(str(path))
    try:
        st = os.stat(full)
        size, mtime, exists = st.st_size, st.st_mtime, True
    except OSError:
        size, mtime, exists = None, None, False
    return {'path': full, 'name': os.path.basename(full), 'dir': os.path.dirname(full),
            'ext': os.path.splitext(full)[1].lower(),
            'size': size, 'mtime': mtime, 'exists': exists}


def describe_files(paths):
    """把一串路径整理成文件清单（去重、补属性、标出已消失的）。"""
    out, seen = [], set()
    for p in (paths or []):
        full = os.path.abspath(str(p))
        key = full.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(file_entry(full))
    return out


def expand_dropped(paths, source_filter=None):
    """拖进来的东西 → 该用什么模式、处理哪些文件。

    规则（2026-09-25 商定）：
      · **只有一个文件夹** → 文件夹模式，源 = 那个文件夹
      · **文件 / 多个文件夹 / 混合** → 文件清单模式：
        散着的文件直接进清单；文件夹按当前扩展名过滤展开后一起并进去

    返回 {'mode', 'folder', 'files', 'note'}。
    """
    dirs, files = [], []
    for p in (paths or []):
        full = os.path.abspath(str(p))
        if os.path.isdir(full):
            dirs.append(full)
        elif os.path.isfile(full):
            files.append(full)

    if len(dirs) == 1 and not files:
        return {'mode': 'folder', 'folder': dirs[0], 'files': [], 'note': ''}

    out, truncated = list(files), False
    for d in dirs:
        for f in list_images(d, source_filter):
            out.append(f)
            if len(out) >= MAX_EXPAND:
                truncated = True
                break
        if truncated:
            break

    note = ''
    if truncated:
        note = '文件夹展开超过 %d 个文件，只取了前 %d 个。' % (MAX_EXPAND, MAX_EXPAND)
    return {'mode': 'files', 'folder': None, 'files': out, 'note': note}


def default_output_dir(files, save_mode):
    """文件清单模式的默认输出目录：以**第一个文件所在目录**为基准。"""
    if not files:
        return ''
    base = os.path.dirname(os.path.abspath(str(files[0])))
    if save_mode in ('source', 'source_delete'):
        return base
    return os.path.join(base, 'compressed_output')


# ==============================================================================
# 缩略图（界面用；生成一次缓存住，别每次重画都重解码）
# ==============================================================================

THUMB_BOX = 240          # 最长边像素。界面按 ~104px 显示，多余的是给高分屏留的
THUMB_QUALITY = 72
# 图片数 ≤ 这个值就画缩略图网格；超了改画紧凑列表。
# 为什么要有这条线：几千张图生成缩略图要几十秒、还要几十 MB 内存，
# 而"挑几张来转"这个动作本来就不需要看几千张缩略图。
THUMB_LIMIT = 100


def make_thumb(path, box=THUMB_BOX, quality=THUMB_QUALITY):
    """把一张图变成 JPEG 的 data URL（直接塞进 <img src>）。

    几个大小上的取舍：
      · `draft()` 是 JPEG 专用的快速降采样 —— 一张 6000×4000 的照片
        能在解码阶段就降到 1/8，不然光解码就要几百毫秒
      · 透明的 PNG 合成到**白底**：缩略图格子小，白底最干净
      · 失败一律返回 None（界面画个占位方块），绝不让一张坏图把整个网格卡住
    """
    import base64
    import io

    try:
        with Image.open(path) as im:
            try:
                im.draft('RGB', (box, box))
            except Exception:
                pass
            if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
                im = im.convert('RGBA')
                flat = Image.new('RGB', im.size, (255, 255, 255))
                flat.paste(im, (0, 0), im)
                im = flat
            else:
                im = im.convert('RGB')
            im.thumbnail((box, box), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=quality, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return None




# ==============================================================================
# 通配符展开（命令行模式用）
# ==============================================================================

def has_wildcard(text):
    return any(c in str(text) for c in '*?[')


def expand_patterns(patterns, base_dir=None):
    """把 `*.png` / `D:\\图\\*.jpg` / `**/*.webp` 展开成绝对路径清单。

    ★ 相对模式按 `base_dir`（命令行里给了源目录就用它，否则当前目录）解析 ——
      这样 `moss :img webp D:\\图 *.png` 里那个 `*.png` 指的是 D:\\图\\*.png，
      不用把目录写两遍。

    返回 (files, 没匹配上的模式列表)。
    """
    import glob as _glob

    base = base_dir or os.getcwd()
    files, missed = [], []
    seen = set()
    for raw in patterns:
        pat = os.path.expandvars(os.path.expanduser(str(raw)))
        if not os.path.isabs(pat):
            pat = os.path.join(base, pat)
        recursive = '**' in pat
        hits = [p for p in _glob.glob(pat, recursive=recursive) if os.path.isfile(p)]
        if not hits:
            missed.append(raw)
            continue
        for h in sorted(hits):
            full = os.path.abspath(h)
            key = full.lower()
            if key not in seen:
                seen.add(key)
                files.append(full)
    return files, missed


def split_ext_filter(text):
    """老写法 `jpg;png` → ['.jpg', '.png']；不是这种形态就返回 None。"""
    text = str(text or '').strip()
    if not text or ';' not in text:
        return None
    parts = []
    for chunk in text.split(';'):
        chunk = chunk.strip().lstrip('.').lower()
        if not chunk:
            continue
        parts.append('.' + chunk)
    return parts or None


def normalize_exts(exts):
    """把 ['.png', 'png', 'PNG'] 统一成 ['.png']，只留受支持的。"""
    out = []
    for e in exts or []:
        e = str(e).strip().lower()
        if not e:
            continue
        if not e.startswith('.'):
            e = '.' + e
        if e in SUPPORTED_EXTS and e not in out:
            out.append(e)
    return out



# ==============================================================================
# 后台作业：界面轮询它拿输出（照抄 exec core.py 的 RunSession.poll 做法）
# ==============================================================================

class Job:
    MAX_OUTPUT = 400 * 1024

    def __init__(self, params):
        self.id = uuid.uuid4().hex[:8]
        self.params = params
        self.returncode = None
        self.summary = None
        self._buf = ''
        self._truncated = False
        self._lock = threading.Lock()
        self.finished = threading.Event()
        self.cancel_event = threading.Event()
        self._thread = threading.Thread(target=self._work, daemon=True)

    def log(self, text):
        if not text:
            return
        with self._lock:
            if len(self._buf) < self.MAX_OUTPUT:
                self._buf += text
            else:
                self._truncated = True

    @property
    def running(self):
        return not self.finished.is_set()

    def poll(self):
        with self._lock:
            out, truncated = self._buf, self._truncated
        if truncated:
            out += '\n… 输出过长，已截断 …\n'
        return {'id': self.id, 'output': out, 'running': self.running,
                'returncode': self.returncode, 'summary': self.summary}

    def cancel(self):
        self.cancel_event.set()

    def start(self):
        self._thread.start()
        return self

    def _work(self):
        p = self.params
        try:
            common = dict(
                output_format=p.get('output_format') or 'jpg',
                quality=int(p.get('quality') or 80),
                width=p.get('width'),
                save_mode=p.get('save_mode') or 'separate',
                ico_sizes=p.get('ico_sizes') or ICO_SIZES_DEFAULT,
                log=self.log,
                cancel=self.cancel_event,
            )
            if p.get('mode') == 'files':
                # 文件清单模式：文件可能来自不同目录
                files = [str(x) for x in (p.get('files') or [])]
                per_file = common['save_mode'] in ('source', 'source_delete')
                self.summary = run_files(
                    files, output_dir=p.get('output_dir') or default_output_dir(files, common['save_mode']),
                    output_dir_per_file=per_file, **common)
            else:
                self.summary = run_tasks(
                    source_dir=p.get('source_dir') or '',
                    source_filter=p.get('source_filter') or [],
                    **common)
            if self.cancel_event.is_set():
                self.returncode = 130
            elif self.summary.get('failed'):
                self.returncode = 1
            else:
                self.returncode = 0
        except Exception as e:
            self.log('\n[严重错误] 处理中发生意外: %s\n' % e)
            self.returncode = 1
        finally:
            self.finished.set()


# ==============================================================================
# 开工前整理参数 / 校验（旧版散在 Tk 回调里，这里抽出来给两套界面共用）
# ==============================================================================

def build_params(cfg, source_dir, source_filter=None):
    """把界面状态整理成 run_tasks 要的参数。ico 模式下忽略目标宽度（照抄旧版）。"""
    fmt = cfg.get('output_format') or 'jpg'
    raw_width = str(cfg.get('width') or '').strip()
    width = None
    if fmt != 'ico' and raw_width.isdigit():
        width = int(raw_width)
    if source_filter is None:
        source_filter = [e for e, on in (cfg.get('source_filter') or {}).items() if on]
    return {
        'source_dir': source_dir,
        'output_format': fmt,
        'quality': int(cfg.get('quality') or 80),
        'width': width,
        'source_filter': list(source_filter),
        'save_mode': cfg.get('save_mode') or 'separate',
        'ico_sizes': checked_ico_sizes(cfg.get('ico_sizes')),
    }


def validate(params):
    """开工前的检查，返回错误文本或 None。照抄旧版的两种提示。"""
    if not os.path.isdir(params.get('source_dir') or ''):
        return '请选择有效的文件夹。'
    if not params.get('source_filter'):
        return '未选择任何文件类型。'
    return None
