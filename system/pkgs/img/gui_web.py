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

    def attach(self, window):
        self._window = window

    # -- 启动数据 ------------------------------------------------------
    def bootstrap(self):
        cfg, message = core.load_config()
        self._cfg = cfg
        self._history = list(cfg.get('history') or [])
        # 旧版打开就是「当前工作目录」，照抄
        cwd = os.getcwd()
        if os.path.isdir(cwd):
            core.push_history(cfg, cwd)
            self._history = list(cfg['history'])
        scan = core.scan_source(cwd)
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

    def scan(self, source_dir):
        """换目录时前端要重新生成「源文件过滤」那一排，结果由这里给。

        顺便把目录记进历史 —— 照抄旧版 `_handle_folder_selection` 的行为。
        """
        got = core.scan_source(source_dir or '')
        if got.get('ok') and self._cfg is not None:
            core.push_history(self._cfg, source_dir)
            self._history = list(self._cfg['history'])
            got['history'] = self._history
        return got

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
        cfg = core.normalize_config(state or {})
        source_dir = str((state or {}).get('source_dir') or '')
        filters = [e for e, on in (cfg.get('source_filter') or {}).items() if on]
        params = core.build_params(cfg, source_dir, filters)

        bad = core.validate(params)
        if bad:
            return {'ok': False, 'message': bad}

        core.push_history(cfg, source_dir)
        self._history = list(cfg['history'])
        cfg['history'] = self._history
        core.save_config(cfg)
        self._cfg = cfg

        job = core.Job(params)
        with self._lock:
            self._jobs[job.id] = job
        job.start()
        return {'ok': True, 'job': job.id, 'history': self._history,
                'outputDir': _expected_output_dir(params)}

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


def _expected_output_dir(params):
    if params.get('save_mode') in ('source', 'source_delete'):
        return params.get('source_dir') or ''
    return os.path.join(params.get('source_dir') or '', 'compressed_output')


def run_gui():
    """打开窗口。pywebview / WebView2 缺失时抛异常，由 main 决定怎么兜底。"""
    import webview

    api = Api()
    index = os.path.join(HERE, 'ui', 'index.html')
    if not os.path.isfile(index):
        raise RuntimeError('界面文件缺失：%s' % index)

    window = webview.create_window(
        TITLE,
        url=index,
        js_api=api,
        width=760, height=880,
        min_size=(640, 620),
        text_select=False,
    )
    api.attach(window)
    window.events.closing += api._on_closing
    # 强制 edgechromium：不指定的话 pywebview 可能退到 mshtml(IE)，
    # 那份引擎渲染不了这套 CSS，而且不会报错 —— 宁可让它抛异常走 Tk 退路。
    webview.start(gui='edgechromium', debug=bool(os.environ.get('MOSS_IMG_DEBUG')))


if __name__ == '__main__':
    run_gui()
