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
    """界面能调的方法 —— **内嵌（stdio）和独立窗口（js_api）共用同一份**（`V-225`）。

    ★ 参数约定：**每个方法只收一个 dict**（`params`），字段按名字取。为什么：
      moss 的垫片 `ui/moss-embed.js` 两种环境都只传一个参数（内嵌是把
      `{id, method, params}` 送进后端进程的 stdin）。以前这里是位置参数
      （`scan(dir)` / `thumbs(paths)`），只有"页面直接调 `pywebview.api`"那条路能用，
      一内嵌就走不通。**别改回位置参数** —— 页面那侧 `ui/src/bridge.js` 就是按字段名发的。
    """

    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._jobs = {}
        self._cfg = None
        self._history = []
        self._drop = []          # 拖放进来的路径；由 drop 回调所在的线程写，前端轮询取走
        self._thumbs = {}        # (路径, mtime) -> data URL

    @staticmethod
    def _p(params):
        """把 `params` 归一成一个 dict（没给 / 给错形状都当空）。"""
        return params if isinstance(params, dict) else {}

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

    def bootstrap(self, params=None):
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
            # ★ `V-225`：内嵌时告诉页面"你没有自己的窗口"（页面据此跳过 `set_title`、
            #   拖放改走宿主那条路），也是给探针看的自证
            'embedded': bool(os.environ.get('MOSS_UI_EMBED')),
        }

    # -- 系统交互 ------------------------------------------------------
    def pick_dir(self, params=None):
        """打开系统「选择文件夹」对话框。"""
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
        """打开系统「选择文件」对话框（可多选）。"""
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
        """帮助面板要显示的内容。

        ★ 用法文本**直接从 cli.py 取**，不在这里再抄一份 ——
          命令行那套语法只在 cli.py 里有一份真相，抄一遍早晚对不上
          （这正是本项目的 W 章纪律：重复可以，漂移不行）。
        """
        import cli
        return {
            'ok': True,
            'usage': cli.USAGE,
            'formats': core.FORMATS,
            'description': '带参数＝命令行模式；不带参数＝打开这个界面。',
        }

    def copy(self, params=None):
        """把文本放进剪贴板（帮助面板的「复制用法」）。"""
        text = self._p(params).get('text') or ''
        try:
            import pyperclip
            pyperclip.copy(str(text or ''))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'message': '写入剪贴板失败：%s' % e}

    def check_path(self, params=None):
        """问一下某个路径是文件还是目录 —— 拖放落点要靠它判断怎么处理。

        拖进来的可能是文件夹（直接当输出目录 / 当源目录），
        也可能是文件（那就取它所在的目录）。
        """
        path = self._p(params).get('path') or ''
        p = str(path or '')
        return {'ok': True, 'path': p,
                'isdir': os.path.isdir(p), 'isfile': os.path.isfile(p),
                'parent': os.path.dirname(p)}

    def scan_files(self, params=None):
        """重新核一遍文件清单（「刷新」用）：还在不在、多大。"""
        paths = list(self._p(params).get('paths') or [])
        return {'ok': True, 'files': core.describe_files(paths or [])}

    def thumbs(self, params=None):
        """生成缩略图。前端分批要（一次 20 张），这样界面立刻出来、后面慢慢补齐。

        按 (路径, mtime) 缓存 —— 刷新、切模式、重开窗口都不用重新解码。
        """
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
        """悬停时按需取一个文件的详情（宽高 / 格式 / 大小 / 修改时间）。"""
        path = self._p(params).get('path') or ''
        path = str(path or '')
        if not path:
            return {'ok': False, 'message': '没有路径。'}
        if not os.path.isfile(path):
            return {'ok': True, 'info': {'path': path, 'exists': False,
                                         'name': os.path.basename(path)}}
        return {'ok': True, 'info': core.file_info(path)}

    def report_error(self, params=None):
        """前端把脚本异常报回来，落到 DATA_DIR 下的 ui-error.log。

        为什么要走这一趟：WebView 里没有控制台，界面上一句红字用户看不懂、
        也没法贴给我，窗口一关线索就没了。写进文件就能查。
        """
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
        """把当前目录/状态写进**窗口标题栏** —— 这样顶栏那一行就可以整条去掉。"""
        text = self._p(params).get('title') or ''
        if self._window is None:
            return {'ok': False}
        try:
            self._window.title = str(text or TITLE)
        except Exception as e:
            return {'ok': False, 'message': str(e)}
        return {'ok': True}

    def open_file(self, params=None):
        """双击缩略图 = 用系统默认程序打开它。"""
        path = self._p(params).get('path') or ''
        path = str(path or '')
        if not os.path.isfile(path):
            return {'ok': False, 'message': '文件不在了：%s' % path}
        try:
            os.startfile(path)          # noqa: S606  (Windows 专用，照抄旧项目做法)
        except Exception as e:
            return {'ok': False, 'message': '打不开：%s' % e}
        return {'ok': True}

    def scan(self, params=None):
        """换目录时前端要重新生成「源文件过滤」那一排，结果由这里给。"""
        source_dir = self._p(params).get('dir') or ''
        return self._scan(source_dir)

    def reveal(self, params=None):
        """在资源管理器里打开输出目录。

        ★ 目录**还没生成**时不要报"不存在" —— 往上一层找第一个存在的打开就行。
          最典型：选了「新文件夹」但一次都还没跑过，compressed_output 当然不存在，
          这时候用户真正想看的是**源目录**（用户指出）。
          自定输出目录 D:\\out\\sub 还没建时，打开 D:\\out 也同样是想要的。
        """
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
            os.startfile(probe)          # noqa: S606  (Windows 专用，照抄旧项目做法)
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

    # -- 拖放 ----------------------------------------------------------
    def push_drop(self, params=None):
        """由 drop 回调（跑在 pywebview 的线程里）调用，只往篮子里放，不做别的。"""
        paths = list(self._p(params).get('paths') or [])
        with self._lock:
            self._drop.extend(str(p) for p in (paths or []) if p)
        return True

    def take_drop(self, params=None):
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
    def save_config(self, params=None):
        cfg = self._p(params).get('config') or {}
        cfg = core.normalize_config(cfg or {})
        cfg['history'] = self._history
        ok, message = core.save_config(cfg)
        self._cfg = cfg
        return {'ok': ok, 'message': message}

    # -- 干活 ----------------------------------------------------------
    def start(self, params=None):
        """开始处理。state 是前端的完整界面状态（未规范化）。"""
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
        # 自定义输出目录：只在「保存到单独文件夹」下有意义
        # （另外两种模式是写回源目录 / 各文件自己的目录，跟它没关系）
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
