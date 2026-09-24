# -*- coding: utf-8 -*-
"""图片工具 —— WebView 界面（首选）。

★ 做法照抄旧项目 `bin/soft/exec/gui_web.py`：
    pywebview + WebView2 + 本地 HTML/CSS/JS，外观由设计令牌（CSS 变量）驱动。
    用 `url=<本地文件>` 而不是 `html=<字符串>` —— pywebview 会为本地文件
    起一个内置 http 服务，`./css/...`、`./src/...` 这些相对路径才走得通。

★ 界面不实现业务：所有处理逻辑都在 `core.py`，本文件只做「桥」。
   长任务的输出靠前端**轮询** `poll(job_id)` 拿，不用 evaluate_js
   往页面里推（跨线程推容易出玄学问题，exec 也是轮询）。

★ 外观（深浅模式 + 系统强调色）由**宿主**算好，通过环境变量
   `MOSS_APPEARANCE` 传进来 —— 包跑在自带运行时里，是独立进程，
   不能 import 宿主的 core。单独 `python gui_web.py` 跑时没有这个变量，
   就交给 CSS 里的默认值和前端的 `prefers-color-scheme` 兜底。
"""
import json
import os
import threading

import core

TITLE = '图片工具'
API_VERSION = 1

# 一次最多把多少个文件条目交给前端画网格/列表。
# 超出的部分：界面看不到，但「不选 = 全部处理」走后端扫目录，照样全都处理。
MAX_SCAN_LIST = 1000

HERE = os.path.dirname(os.path.abspath(__file__))


def appearance():
    """读宿主注入的外观；没有就返回空壳（前端用 CSS 默认值）。"""
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


# ---------------------------------------------------------------- JS 桥
class Api:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._jobs = {}
        self._cfg = None
        self._history = []
        self._drop = []          # 拖放进来的路径；由 drop 回调所在的线程写，前端轮询取走
        self._thumbs = {}        # (路径, mtime) -> data URL

    def attach(self, window):
        self._window = window

    # -- 启动数据 ------------------------------------------------------
    def _scan(self, source_dir):
        """扫目录 + 带上**全部**图片条目（前端自己按类型过滤、画缩略图网格）。

        列表有上限：几千个文件名过 JS 桥没有意义 —— 而且「不选 = 全部处理」
        这条路由后端自己扫目录完成，不依赖前端有没有拿到完整名单。
        顺带把目录记进历史（照抄旧版 `_handle_folder_selection`）。
        """
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

    def bootstrap(self):
        cfg, message = core.load_config()
        self._cfg = cfg
        self._history = list(cfg.get('history') or [])
        # 旧版打开就是「当前工作目录」，照抄
        cwd = os.getcwd()
        # ★ 必须走 _scan 而不是 core.scan_source：前者才会带上 files，
        #   不然首屏网格是空的，而类型芯片却显示着数量（踩过）
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
        }

    # -- 系统交互 ------------------------------------------------------
    def pick_dir(self, initial=''):
        """打开系统「选择文件夹」对话框。"""
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

    def pick_files(self, initial=''):
        """打开系统「选择文件」对话框（可多选）。"""
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

    def scan_files(self, paths):
        """重新核一遍文件清单（「刷新」用）：还在不在、多大。"""
        return {'ok': True, 'files': core.describe_files(paths or [])}

    def thumbs(self, paths):
        """生成缩略图。前端分批要（一次 20 张），这样界面立刻出来、后面慢慢补齐。

        按 (路径, mtime) 缓存 —— 刷新、切模式、重开窗口都不用重新解码。
        """
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

    def open_file(self, path):
        """双击缩略图 = 用系统默认程序打开它。"""
        path = str(path or '')
        if not os.path.isfile(path):
            return {'ok': False, 'message': '文件不在了：%s' % path}
        try:
            os.startfile(path)          # noqa: S606  (Windows 专用，照抄旧项目做法)
        except Exception as e:
            return {'ok': False, 'message': '打不开：%s' % e}
        return {'ok': True}

    def scan(self, source_dir):
        """换目录时前端要重新生成「源文件过滤」那一排，结果由这里给。"""
        return self._scan(source_dir)

    def reveal(self, path):
        """在资源管理器里打开输出目录。"""
        path = str(path or '')
        if not path or not os.path.isdir(path):
            return {'ok': False, 'message': '目录不存在：%s' % path}
        try:
            os.startfile(path)          # noqa: S606  (Windows 专用，照抄旧项目做法)
        except Exception as e:
            return {'ok': False, 'message': '打开失败：%s' % e}
        return {'ok': True}

    def _remember(self, path):
        if self._cfg is None or not path:
            return self._history
        core.push_history(self._cfg, path)
        self._history = list(self._cfg['history'])
        return self._history

    # -- 拖放 ----------------------------------------------------------
    def push_drop(self, paths):
        """由 drop 回调（跑在 pywebview 的线程里）调用，只往篮子里放，不做别的。"""
        with self._lock:
            self._drop.extend(str(p) for p in (paths or []) if p)
        return True

    def take_drop(self):
        """前端轮询取走拖放进来的路径。

        ★ 为什么用轮询而不是后端 evaluate_js 推给前端：
          drop 回调在**子线程**里跑，跨线程往页面里推容易出玄学问题；
          前端本来就要响应 drop 事件，让它顺手多问几次最省事。
        """
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

    # -- 配置 ----------------------------------------------------------
    def save_config(self, cfg):
        cfg = core.normalize_config(cfg or {})
        cfg['history'] = self._history
        ok, message = core.save_config(cfg)
        self._cfg = cfg
        return {'ok': ok, 'message': message}

    # -- 干活 ----------------------------------------------------------
    def start(self, state):
        """开始处理。state 是前端的完整界面状态（未规范化）。"""
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
                          output_dir=core.default_output_dir(files, common['save_mode']))
            out_dir = params['output_dir']
        else:
            source_dir = str(state.get('source_dir') or '')
            filters = [e for e, on in (cfg.get('source_filter') or {}).items() if on]
            params = dict(common, source_dir=source_dir, source_filter=filters, files=[],
                          output_dir=None)
            bad = core.validate(params)
            if bad:
                return {'ok': False, 'message': bad}
            out_dir = _expected_output_dir(params)
            self._remember(source_dir)

        cfg['history'] = self._history
        core.save_config(cfg)
        self._cfg = cfg

        job = core.Job(params)
        with self._lock:
            self._jobs[job.id] = job
        job.start()
        return {'ok': True, 'job': job.id, 'history': self._history, 'outputDir': out_dir}

    def poll(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id))
        if not job:
            return {'ok': False, 'message': '这个任务已经不存在了。'}
        got = job.poll()
        got['ok'] = True
        return got

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id))
        if not job:
            return {'ok': False, 'message': '这个任务已经不存在了。'}
        job.cancel()
        return {'ok': True}

    # -- 关闭 ----------------------------------------------------------
    def _on_closing(self):
        """关窗口时存一次配置（照抄旧版 protocol('WM_DELETE_WINDOW', self._on_closing)）。"""
        if self._cfg is None:
            return True
        self._cfg['history'] = self._history
        core.save_config(self._cfg)
        return True


def _current_filter(cfg):
    """当前勾着的扩展名过滤（给"拖进来的文件夹"展开用）。没勾过就 None（=全都要）。"""
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
    """把 WebView2 的文件拖放接上。

    ★ 为什么这样能拿到**真路径**（pywebview 6 + WebView2 才有）：
        js/api.js:90-101   drop 事件上 `chrome.webview.postMessageWithAdditionalObjects(
                           'FilesDropped', e.dataTransfer.files)` 把真实的 file 对象送给 .NET
        platforms/edgechromium.py:185-198   从 `CoreWebView2File.Path` 取完整路径
        util.py:282-290   把路径以 `pywebviewFullPath` 挂回事件对象

    ⚠️ 两个前提，缺一个就什么都收不到：
      1. 页面里**必须挂一个 drop 监听** —— 后端看到 `_dnd_state['num_listeners'] == 0`
         会直接 return（edgechromium.py:186），路径根本不会被收集。
      2. 必须是 edgechromium 后端（run_gui 里已经强制指定）。

    ⚠️ pywebview 是用**文件名**去配对路径的（util.py:285），一次拖两个同名文件
      （不同目录）会串。拦不住，但也不是日常场景。
    """
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

    # prevent_default 很重要：不然 WebView2 会拿拖进来的文件去导航，把界面顶掉
    window.dom.body.on('drop', DOMEventHandler(on_drop, prevent_default=True))

    # ★ 挂没挂上必须**当场验**，不能靠"没报错"就当成了。
    #   实测过一次：element.on() 内部把 JavascriptException 吞掉只记 logger，
    #   外面看起来一切正常，而 num_listeners 还是 0 —— 真拖文件进来毫无反应。
    if _dnd_state['num_listeners'] <= 0:
        raise RuntimeError('drop 监听没挂上（num_listeners 仍为 0）')
    return True


def _window_size():
    """按屏幕高度自适应：小屏笔记本上别顶出屏幕，大屏上给足缩略图的地方。"""
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
    """打开窗口。pywebview / WebView2 缺失时抛异常，由 main 决定怎么兜底。"""
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
        """页面加载完才能挂 DOM 事件（元素还不存在时挂不上）。"""
        try:
            _wire_drop(window, api)
            print('[提示] 拖放已接上：文件夹或图片都可以直接拖进窗口。')
        except Exception as e:
            import traceback
            print('[提示] 拖放没接上（不影响其它功能）：%s' % e)
            traceback.print_exc()

    window.events.loaded += on_loaded

    # 强制 edgechromium：不指定的话 pywebview 可能退到 mshtml(IE)，
    # 那份引擎渲染不了这套 CSS，而且不会报错 —— 宁可让它抛异常走 Tk 退路。
    # 另外 WebView2 才支持"拖进来的文件给真路径"。
    webview.start(gui='edgechromium', debug=bool(os.environ.get('MOSS_IMG_DEBUG')))


if __name__ == '__main__':
    run_gui()
