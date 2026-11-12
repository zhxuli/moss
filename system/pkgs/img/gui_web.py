import json
import os
import threading

import core

TITLE = '图片工具'
API_VERSION = 1

MAX_SCAN_LIST = 1000

HERE = os.path.dirname(os.path.abspath(__file__))

def appearance():
    raw = os.environ.get('MOSS_APPEARANCE')
    if not raw:
        return {'theme': None, 'accent': {}}
    try:
        got = json.loads(raw)
    except (ValueError, TypeError):
        return {'theme': None, 'accent': {}}
    keys = ('accent', 'accent-fg', 'accent-press', 'ring', 'field-focus')
    return {'theme': got.get('theme'),
            'accent': {k: got[k] for k in keys if got.get(k)}}

class Api:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._jobs = {}
        self._cfg = None
        self._history = []
        self._drop = []
        self._thumbs = {}

    @staticmethod
    def _p(params):
        return params if isinstance(params, dict) else {}

    def attach(self, window):
        self._window = window

    def _scan(self, source_dir):
        got = core.scan_source(source_dir or '')
        if got.get('ok'):
            files = core.describe_files(core.list_images(source_dir, None))
            got['files'] = files[:MAX_SCAN_LIST]
            got['truncated'] = len(files) > MAX_SCAN_LIST
            if self._cfg is not None:
                core.push_history(self._cfg, source_dir)
                self._history = list(self._cfg['history'])
                got['history'] = self._history
        return got

    def bootstrap(self, params=None):
        cfg, message = core.load_config()
        self._cfg = cfg
        self._history = list(cfg.get('history') or [])
        cwd = os.getcwd()
        scan = self._scan(cwd) if os.path.isdir(cwd) else core.scan_source(cwd)
        look = appearance()
        return {
            'apiVersion': API_VERSION,
            'ok': True,
            'config': cfg,
            'history': self._history,
            'sourceDir': cwd,
            'scan': scan,
            'dataDir': core.DATA_DIR,
            'formats': core.FORMATS,
            'saveModes': core.SAVE_MODES,
            'icoSizes': core.ICO_SIZES,
            'supportedExts': list(core.SUPPORTED_EXTS),
            'maxExpand': core.MAX_EXPAND,
            'thumbLimit': core.THUMB_LIMIT,
            'thumbBox': core.THUMB_BOX,
            'historyLimit': core.HISTORY_LIMIT,
            'theme': look['theme'],
            'accent': look['accent'],
            'log': message,
            'embedded': bool(os.environ.get('MOSS_UI_EMBED')),
        }

    def pick_dir(self, params=None):
        initial = str(self._p(params).get('start') or '')
        w = self._window
        if not w:
            return {'ok': False, 'message': '窗口未就绪。'}
        try:
            import webview
            kwargs = {}
            if initial and os.path.isdir(initial):
                kwargs['directory'] = initial
            picked = w.create_file_dialog(webview.FOLDER_DIALOG, **kwargs)
        except Exception as e:
            return {'ok': False, 'message': '打开选择框失败：%s' % e}
        if not picked:
            return {'ok': True, 'path': ''}
        first = picked[0] if isinstance(picked, (list, tuple)) else picked
        return {'ok': True, 'path': str(first)}

    def pick_files(self, params=None):
        initial = str(self._p(params).get('start') or '')
        w = self._window
        if not w:
            return {'ok': False, 'message': '窗口未就绪。'}
        try:
            import webview
            exts = ';'.join('*' + e for e in core.SUPPORTED_EXTS)
            kwargs = {
                'allow_multiple': True,
                'file_types': ('图片 (%s)' % exts, '所有文件 (*.*)'),
            }
            if initial and os.path.isdir(initial):
                kwargs['directory'] = initial
            picked = w.create_file_dialog(webview.OPEN_DIALOG, **kwargs)
        except Exception as e:
            return {'ok': False, 'message': '打开选择框失败：%s' % e}
        if not picked:
            return {'ok': True, 'files': []}
        if isinstance(picked, str):
            picked = [picked]
        files = core.describe_files(picked)
        if files:
            self._remember(files[0]['dir'])
        return {'ok': True, 'files': files}

    def help(self, params=None):
        import cli
        return {
            'ok': True,
            'usage': cli.USAGE,
            'formats': core.FORMATS,
            'description': '带参数＝命令行模式；不带参数＝打开这个界面。',
        }

    def copy(self, params=None):
        text = self._p(params).get('text') or ''
        try:
            import pyperclip
            pyperclip.copy(str(text or ''))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'message': '写入剪贴板失败：%s' % e}

    def check_path(self, params=None):
        path = self._p(params).get('path') or ''
        p = str(path or '')
        return {'ok': True, 'path': p,
                'isdir': os.path.isdir(p), 'isfile': os.path.isfile(p),
                'parent': os.path.dirname(p)}

    def scan_files(self, params=None):
        paths = list(self._p(params).get('paths') or [])
        return {'ok': True, 'files': core.describe_files(paths or [])}

    def thumbs(self, params=None):
        paths = list(self._p(params).get('paths') or [])
        out = []
        with self._lock:
            cache = self._thumbs
        for raw in (paths or []):
            p = str(raw)
            try:
                mtime = int(os.path.getmtime(p))
            except OSError:
                out.append({'path': p, 'data': None})
                continue
            key = (p.lower(), mtime)
            got = cache.get(key, '')
            if got == '':
                got = core.make_thumb(p)
                with self._lock:
                    if len(self._thumbs) > 1500:
                        self._thumbs.clear()
                    self._thumbs[key] = got
            out.append({'path': p, 'data': got})
        return {'ok': True, 'thumbs': out}

    def file_info(self, params=None):
        path = self._p(params).get('path') or ''
        path = str(path or '')
        if not path:
            return {'ok': False, 'message': '没有路径。'}
        if not os.path.isfile(path):
            return {'ok': True, 'info': {'path': path, 'exists': False,
                                         'name': os.path.basename(path)}}
        return {'ok': True, 'info': core.file_info(path)}

    def report_error(self, params=None):
        text = self._p(params).get('text') or ''
        try:
            import time as _time
            if not os.path.isdir(core.DATA_DIR):
                os.makedirs(core.DATA_DIR, exist_ok=True)
            with open(os.path.join(core.DATA_DIR, 'ui-error.log'), 'a', encoding='utf-8') as f:
                f.write('\n=== %s ===\n%s\n' % (
                    _time.strftime('%Y-%m-%d %H:%M:%S'), str(text)[:4000]))
            return {'ok': True, 'file': os.path.join(core.DATA_DIR, 'ui-error.log')}
        except Exception:
            return {'ok': False}

    def set_title(self, params=None):
        text = self._p(params).get('title') or ''
        if self._window is None:
            return {'ok': False}
        try:
            self._window.title = str(text or TITLE)
        except Exception as e:
            return {'ok': False, 'message': str(e)}
        return {'ok': True}

    def open_file(self, params=None):
        path = self._p(params).get('path') or ''
        path = str(path or '')
        if not os.path.isfile(path):
            return {'ok': False, 'message': '文件不在了：%s' % path}
        try:
            os.startfile(path)
        except Exception as e:
            return {'ok': False, 'message': '打不开：%s' % e}
        return {'ok': True}

    def scan(self, params=None):
        source_dir = self._p(params).get('dir') or ''
        return self._scan(source_dir)

    def reveal(self, params=None):
        path = self._p(params).get('target') or ''
        raw = str(path or '')
        if not raw:
            return {'ok': False, 'message': '还不知道输出目录。'}
        target = os.path.abspath(raw)

        probe = target
        for _ in range(40):
            if os.path.isdir(probe):
                break
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not os.path.isdir(probe):
            return {'ok': False, 'message': '路径不存在：%s' % raw}
        try:
            os.startfile(probe)
        except Exception as e:
            return {'ok': False, 'message': '打开失败：%s' % e}
        return {'ok': True, 'opened': probe,
                'fellBack': os.path.normcase(probe) != os.path.normcase(target)}

    def _remember(self, path):
        if self._cfg is None or not path:
            return self._history
        core.push_history(self._cfg, path)
        self._history = list(self._cfg['history'])
        return self._history

    def push_drop(self, params=None):
        paths = list(self._p(params).get('paths') or [])
        with self._lock:
            self._drop.extend(str(p) for p in (paths or []) if p)
        return True

    def take_drop(self, params=None):
        with self._lock:
            got, self._drop = self._drop, []
        if not got:
            return {'ok': True, 'pending': False}
        plan = core.expand_dropped(got, _current_filter(self._cfg))
        if plan['mode'] == 'folder':
            self._remember(plan['folder'])
        elif plan['files']:
            self._remember(os.path.dirname(plan['files'][0]))
        return {
            'ok': True,
            'pending': True,
            'mode': plan['mode'],
            'folder': plan['folder'],
            'files': core.describe_files(plan['files']),
            'note': plan['note'],
            'history': self._history,
        }

    def save_config(self, params=None):
        cfg = self._p(params).get('config') or {}
        cfg = core.normalize_config(cfg or {})
        cfg['history'] = self._history
        ok, message = core.save_config(cfg)
        self._cfg = cfg
        return {'ok': ok, 'message': message}

    def start(self, params=None):
        state = self._p(params).get('payload') or {}
        state = state or {}
        cfg = core.normalize_config(state)
        mode = 'files' if state.get('mode') == 'files' else 'folder'
        fmt = cfg.get('output_format') or 'jpg'
        raw_width = str(cfg.get('width') or '').strip()
        width = None if fmt == 'ico' else (int(raw_width) if raw_width.isdigit() else None)
        common = {
            'mode': mode,
            'output_format': fmt,
            'quality': int(cfg.get('quality') or 80),
            'width': width,
            'save_mode': cfg.get('save_mode') or 'separate',
            'ico_sizes': core.checked_ico_sizes(cfg.get('ico_sizes')),
        }
        custom_out = str(state.get('output_dir') or '').strip()
        if common['save_mode'] != 'separate' or not custom_out:
            custom_out = ''
        elif not os.path.isdir(custom_out):
            return {'ok': False, 'message': '输出目录不存在：%s' % custom_out}

        if mode == 'files':
            files = [f.get('path') for f in (state.get('files') or []) if isinstance(f, dict)]
            files = [p for p in files if p]
            if not files:
                return {'ok': False, 'message': '文件清单是空的，先选几个文件。'}
            missing = [p for p in files if not os.path.isfile(p)]
            if missing:
                return {'ok': False, 'message': '有 %d 个文件已经不在了，先点「刷新」清掉。'
                                                 % len(missing)}
            params = dict(common, source_dir='', source_filter=[], files=files,
                          output_dir=custom_out or core.default_output_dir(files, common['save_mode']))
            out_dir = params['output_dir']
        else:
            source_dir = str(state.get('source_dir') or '')
            filters = [e for e, on in (cfg.get('source_filter') or {}).items() if on]
            params = dict(common, source_dir=source_dir, source_filter=filters, files=[],
                          output_dir=custom_out or None)
            bad = core.validate(params)
            if bad:
                return {'ok': False, 'message': bad}
            out_dir = custom_out or _expected_output_dir(params)
            self._remember(source_dir)

        cfg['history'] = self._history
        core.save_config(cfg)
        self._cfg = cfg

        job = core.Job(params)
        with self._lock:
            self._jobs[job.id] = job
        job.start()
        return {'ok': True, 'job': job.id, 'history': self._history, 'outputDir': out_dir}

    def poll(self, params=None):
        job_id = self._p(params).get('id') or ''
        with self._lock:
            job = self._jobs.get(str(job_id))
        if not job:
            return {'ok': False, 'message': '这个任务已经不存在了。'}
        got = job.poll()
        got['ok'] = True
        return got

    def cancel(self, params=None):
        job_id = self._p(params).get('id') or ''
        with self._lock:
            job = self._jobs.get(str(job_id))
        if not job:
            return {'ok': False, 'message': '这个任务已经不存在了。'}
        job.cancel()
        return {'ok': True}

    def _on_closing(self):
        if self._cfg is None:
            return True
        self._cfg['history'] = self._history
        core.save_config(self._cfg)
        return True

def _current_filter(cfg):
    if not cfg:
        return None
    picked = [e for e, on in (cfg.get('source_filter') or {}).items() if on]
    return picked or None

def _expected_output_dir(params):
    if params.get('mode') == 'files':
        return params.get('output_dir') or ''
    if params.get('save_mode') in ('source', 'source_delete'):
        return params.get('source_dir') or ''
    return os.path.join(params.get('source_dir') or '', 'compressed_output')

def _wire_drop(window, api):
    from webview.dom import DOMEventHandler, _dnd_state

    def on_drop(event):
        files = ((event or {}).get('dataTransfer') or {}).get('files') or []
        paths = []
        for item in files:
            got = item.get('pywebviewFullPath')
            if got:
                paths.append(got)
        if paths:
            api.push_drop(paths)

    window.dom.body.on('drop', DOMEventHandler(on_drop, prevent_default=True))

    if _dnd_state['num_listeners'] <= 0:
        raise RuntimeError('drop 监听没挂上（num_listeners 仍为 0）')
    return True

def _window_size():
    w, h = 940, 1010
    if os.name != 'nt':
        return w, h
    try:
        import ctypes
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        if screen_h:
            h = max(620, min(h, screen_h - 150))
    except Exception:
        pass
    return w, h

def run_gui():
    import webview

    api = Api()
    index = os.path.join(HERE, 'ui', 'index.html')
    if not os.path.isfile(index):
        raise RuntimeError('界面文件缺失：%s' % index)

    width, height = _window_size()
    window = webview.create_window(
        TITLE,
        url=index,
        js_api=api,
        width=width, height=height,
        min_size=(720, 560),
        text_select=False,
    )
    api.attach(window)
    window.events.closing += api._on_closing

    def on_loaded():
        try:
            _wire_drop(window, api)
            print('[提示] 拖放已接上：文件夹或图片都可以直接拖进窗口。')
        except Exception as e:
            import traceback
            print('[提示] 拖放没接上（不影响其它功能）：%s' % e)
            traceback.print_exc()

    window.events.loaded += on_loaded

    webview.start(gui='edgechromium', debug=bool(os.environ.get('MOSS_IMG_DEBUG')))

if __name__ == '__main__':
    run_gui()
