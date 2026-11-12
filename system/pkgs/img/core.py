import json
import os
import sys
import threading
import time
import uuid

from PIL import Image

DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.environ.get('PA_PLUGIN_DATA_DIR')
            or os.path.join(os.environ.get("MOSS_HOME") or os.path.expanduser("~"),
                            "user_data", "state", "img"))
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
HISTORY_LIMIT = 50

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICO_SIZES_DEFAULT = [16, 24, 32, 48, 64, 128, 256]

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')
FORMATS = ['jpg', 'png', 'webp', 'ico']
SAVE_FORMATS = ('jpg', 'jpeg', 'png', 'webp', 'ico', 'bmp', 'gif', 'tiff')
SAVE_MODES = ['separate', 'source', 'source_delete']

DEFAULT_CONFIG = {
    'save_mode': 'separate',
    'output_format': 'jpg',
    'quality': 80,
    'width': '',
    'ico_sizes': list(ICO_SIZES_DEFAULT),
    'source_filter': {},
    'history': [],
    'output_dir': '',
}

def _noop(text):
    pass

def normalize_config(cfg):
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
    out['output_dir'] = str(cfg.get('output_dir') or '').strip()
    return out

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return normalize_config(json.load(f)), '成功加载配置文件。'
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG), '未找到配置文件，使用默认设置。'
    except (json.JSONDecodeError, OSError) as e:
        return dict(DEFAULT_CONFIG), '配置文件读取失败（%s），使用默认设置。' % e

def save_config(cfg):
    cfg = normalize_config(cfg)
    try:
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True, '配置已保存。'
    except OSError as e:
        return False, '错误：无法保存配置文件: %s' % e

def push_history(cfg, path):
    path = str(path or '')
    if not path:
        return cfg
    hist = [p for p in cfg.get('history', []) if p != path]
    hist.insert(0, path)
    cfg['history'] = hist[:HISTORY_LIMIT]
    return cfg

def checked_ico_sizes(picked):
    got = []
    for s in (picked or []):
        try:
            s = int(s)
        except (TypeError, ValueError):
            continue
        if s in ICO_SIZES and s not in got:
            got.append(s)
    return sorted(got) or list(ICO_SIZES_DEFAULT)

def scan_source(source_dir):
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

def resolve_format(filepath, output_format):
    fmt = str(output_format or '').strip().lower()
    if fmt and fmt not in ('same', '原样'):
        return 'jpg' if fmt == 'jpeg' else fmt
    ext = os.path.splitext(str(filepath))[1].lstrip('.').lower()
    ext = 'jpg' if ext == 'jpeg' else ext
    return ext if ext in SAVE_FORMATS else 'png'

def process_single_image(filepath, output_format, quality, width, output_dir, save_mode,
                         ico_sizes, log=_noop):
    name = os.path.basename(filepath)
    fmt = resolve_format(filepath, output_format)
    try:
        with Image.open(filepath) as img:
            log(f"\n- 正在处理: {name} ({img.width}x{img.height})\n")
            img_copy = img.copy()

        if fmt != 'ico' and width and img_copy.width > width:
            aspect_ratio = img_copy.height / img_copy.width
            new_height = int(width * aspect_ratio)
            log(f"  - 调整尺寸为: {width}x{new_height}\n")
            img_copy = img_copy.resize((width, new_height), Image.Resampling.LANCZOS)

        base_name, _ = os.path.splitext(name)
        output_filename = f"{base_name}.{fmt}"
        output_path = os.path.join(output_dir, output_filename)

        if fmt in ('jpg', 'bmp') and img_copy.mode in ('RGBA', 'P', 'LA'):
            log("  - 转换透明背景为白色\n")
            img_copy = img_copy.convert('RGBA') if img_copy.mode != 'RGBA' else img_copy
            background = Image.new('RGB', img_copy.size, (255, 255, 255))
            if 'A' in img_copy.getbands():
                background.paste(img_copy, (0, 0), img_copy.getchannel('A'))
            else:
                background.paste(img_copy, (0, 0))
            img_copy = background
        elif fmt in ('jpg', 'bmp') and img_copy.mode != 'RGB':
            img_copy = img_copy.convert('RGB')

        save_options = {}
        if fmt in ('jpg', 'jpeg', 'webp'):
            save_options['quality'] = quality
        elif fmt == 'png':
            save_options['compress_level'] = int((100 - quality) / 100 * 9)
            save_options['optimize'] = True
        elif fmt == 'ico':
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
              log=_noop, cancel=None, output_dir=None):
    if output_dir:
        target = output_dir
    elif save_mode in ["source", "source_delete"]:
        target = source_dir
    else:
        target = os.path.join(source_dir, "compressed_output")
    if not os.path.isdir(target):
        os.makedirs(target, exist_ok=True)

    return run_files(list_images(source_dir, source_filter), output_format, quality, width,
                     target, save_mode, ico_sizes, log=log, cancel=cancel)

MAX_EXPAND = 2000

def file_entry(path):
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

def file_info(path):
    info = dict(file_entry(path))
    info.pop('data', None)
    if not info['exists']:
        return info
    try:
        with Image.open(info['path']) as im:
            info['width'] = im.width
            info['height'] = im.height
            info['format'] = im.format or ''
            info['mode'] = im.mode
    except Exception:
        info['width'] = info['height'] = None
        info['format'] = ''
        info['mode'] = ''
    try:
        info['mtime_text'] = time.strftime('%Y-%m-%d %H:%M:%S',
                                           time.localtime(info['mtime']))
    except Exception:
        info['mtime_text'] = ''
    return info

def default_output_dir(files, save_mode):
    if not files:
        return ''
    base = os.path.dirname(os.path.abspath(str(files[0])))
    if save_mode in ('source', 'source_delete'):
        return base
    return os.path.join(base, 'compressed_output')

THUMB_BOX = 240
THUMB_QUALITY = 72
THUMB_LIMIT = 100

def make_thumb(path, box=THUMB_BOX, quality=THUMB_QUALITY):
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

def has_wildcard(text):
    return any(c in str(text) for c in '*?[')

def expand_patterns(patterns, base_dir=None):
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
                files = [str(x) for x in (p.get('files') or [])]
                per_file = common['save_mode'] in ('source', 'source_delete')
                out_dir = p.get('output_dir') or default_output_dir(files, common['save_mode'])
                self.summary = run_files(
                    files, output_dir=out_dir,
                    output_dir_per_file=per_file, **common)
            else:
                self.summary = run_tasks(
                    source_dir=p.get('source_dir') or '',
                    source_filter=p.get('source_filter') or [],
                    output_dir=p.get('output_dir') or None,
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

def build_params(cfg, source_dir, source_filter=None):
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
    if not os.path.isdir(params.get('source_dir') or ''):
        return '请选择有效的文件夹。'
    if not params.get('source_filter'):
        return '未选择任何文件类型。'
    return None
