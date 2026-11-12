import json
import locale
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime

if '__file__' in globals():
    PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    PLUGIN_DIR = sys.path[0] if sys.path else os.getcwd()

DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.environ.get('PA_PLUGIN_DATA_DIR') or os.path.join(os.environ.get("MOSS_HOME") or os.path.expanduser("~"),
             "user_data", "state", "exec")
CMDS_DIR = os.path.join(DATA_DIR, 'cmds')
PREVIEW_DIR = os.path.join(DATA_DIR, 'preview')
OUTPUT_DIR = os.path.join(DATA_DIR, 'output')
TEMP_DIR = os.path.join(DATA_DIR, 'tmp')

ALIAS_RE = re.compile(r'^[a-z0-9_-]{1,64}$')

_PREFERRED_ENCODING = locale.getpreferredencoding(False) or 'utf-8'

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

TYPES = {
    'python': {
        'label': 'Python 片段', 'kind': 'proc', 'lang': 'python',
        'multiline': True, 'payload': 'Python 代码',
        'hint': '在本机 Python 解释器里执行代码片段（等价 python -c）',
    },
    'powershell': {
        'label': 'PowerShell', 'short': 'PowerShell', 'kind': 'proc', 'lang': 'powershell',
        'multiline': True, 'payload': 'PowerShell 代码',
        'hint': '交给 PowerShell 执行（-NoProfile，不受执行策略干扰）',
    },
    'shell': {
        'label': 'CMD 命令', 'short': 'CMD', 'kind': 'proc', 'lang': 'bash',
        'multiline': True, 'payload': '命令',
        'hint': '交给系统 cmd 执行（%VAR% 和 && 是 cmd 语义）',
    },
    'url': {
        'label': '网址', 'kind': 'builtin', 'lang': None,
        'multiline': False, 'payload': '网址模板',
        'hint': '用默认浏览器打开；{args} 会拼进网址（如 .../s?wd={args}）',
    },
    'path': {
        'label': '文件 / 文件夹', 'kind': 'builtin', 'lang': None,
        'multiline': False, 'payload': '路径', 'pick': 'any',
        'hint': '用资源管理器打开；支持 {clipboard} 等占位符',
    },
    'html': {
        'label': 'HTML 页面', 'kind': 'builtin', 'lang': 'xml',
        'multiline': True, 'payload': 'HTML 源码',
        'hint': '把源码写成临时页面并用浏览器打开',
    },
}

PICKER = [
    {'id': 'python',  'label': 'Python', 'types': ['python'], 'icon': 'code'},
    {'id': 'command', 'label': '命令行', 'types': ['shell', 'powershell'], 'icon': 'terminal'},
    {'id': 'url',     'label': '网址',   'types': ['url'], 'icon': 'globe'},
    {'id': 'path',    'label': '路径',   'types': ['path'], 'icon': 'folder'},
    {'id': 'html',    'label': 'HTML',   'types': ['html'], 'icon': 'doc'},
]

PICKER_DEFAULT = {'command': 'shell'}

NEW_TYPES = [
    {'id': 'python',     'label': 'Python 片段',  'icon': 'code',
     'hint': '在本机解释器里跑一段代码'},
    {'id': 'shell',      'label': 'CMD 命令',     'icon': 'terminal',
     'hint': 'cmd 命令，%VAR% 和 && 都是 cmd 语义'},
    {'id': 'powershell', 'label': 'PowerShell',   'icon': 'shell',
     'hint': '对象管道、cmdlet、JSON / REST'},
    {'id': 'url',        'label': '网址',         'icon': 'globe',
     'hint': '浏览器打开，{args} 可拼进网址'},
    {'id': 'path',       'label': '文件 / 文件夹', 'icon': 'folder',
     'hint': '资源管理器打开'},
    {'id': 'html',       'label': 'HTML 页面',    'icon': 'doc',
     'hint': '存一段 HTML，可直接预览'},
]

PLACEHOLDERS = [
    {'token': '{args}', 'desc': '本次输入的参数'},
    {'token': '{clipboard}', 'desc': '剪贴板文本'},
    {'token': '{date}', 'desc': '今天，如 2026-09-22'},
    {'token': '{date:%Y%m%d}', 'desc': '自定义格式的日期'},
    {'token': '{time}', 'desc': '当前时间，如 14:30:05'},
]

AFTER_ACTIONS = [
    {'id': 'none', 'label': '不处理'},
    {'id': 'clipboard', 'label': '把输出复制到剪贴板'},
    {'id': 'file', 'label': '把输出保存到文件'},
]

DEFAULT_COMMANDS = [
    {
        "alias": "ip", "type": "python", "description": "查询本机 / 指定 IP 的归属信息",
        "code": ("import sys, urllib.request, json\n\n"
                 "try:\n"
                 "    target = sys.argv[1] if len(sys.argv) > 1 else ''\n"
                 "    print('正在查询 %s ...' % (target or '本机当前网络'))\n"
                 "    req = urllib.request.urlopen('http://ip-api.com/json/%s?lang=zh-CN' % target)\n"
                 "    data = json.loads(req.read())\n"
                 "    if data.get('status') == 'success':\n"
                 "        print('IP地址:', data.get('query'))\n"
                 "        print('位置  :', data.get('country'), data.get('regionName'), data.get('city'))\n"
                 "        print('运营商:', data.get('isp'))\n"
                 "    else:\n"
                 "        print('查询失败。')\n"
                 "except Exception as e:\n"
                 "    print('请求出错:', e)")
    },
    {
        "alias": "uuid", "type": "python", "description": "生成一个 UUID",
        "code": "import uuid\nprint(uuid.uuid4())"
    },
    {
        "alias": "ping", "type": "shell", "description": "ping 指定主机（参数填主机名或 IP）",
        "code": "ping {args}"
    },
    {
        "alias": "ports", "type": "shell", "description": "列出本机正在监听的端口",
        "code": "netstat -ano | findstr LISTENING"
    },
    {
        "alias": "top", "type": "powershell", "description": "占用内存最高的 8 个进程",
        "code": ("Get-Process | Sort-Object WS -Descending | Select-Object -First 8 |\n"
                 "  Format-Table Name, Id, @{n='内存MB';e={[int]($_.WS/1MB)}} -AutoSize")
    },
    {
        "alias": "whoisport", "type": "powershell", "description": "查某个端口被哪个进程占用（参数填端口，默认 8080）",
        "code": ("$p = '{args}'; if (-not $p) { $p = 8080 }\n"
                 "Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |\n"
                 "  ForEach-Object { $_.OwningProcess } | Select-Object -Unique |\n"
                 "  ForEach-Object { Get-Process -Id $_ } | Format-Table Id, Name -AutoSize")
    },
    {
        "alias": "bd", "type": "url", "description": "百度搜索（参数填关键词）",
        "code": "https://www.baidu.com/s?wd={args}"
    },
    {
        "alias": "gh", "type": "url", "description": "GitHub 搜索仓库（参数填关键词）",
        "code": "https://github.com/search?q={args}&type=repositories"
    },
    {
        "alias": "downloads", "type": "path", "description": "打开「下载」文件夹",
        "code": r"%USERPROFILE%\Downloads"
    },
    {
        "alias": "tempdir", "type": "path", "description": "打开系统临时文件夹",
        "code": "%TEMP%"
    },
    {
        "alias": "note", "type": "html",
        "description": "一张极简便签页（示例：HTML 源码直接存成命令）",
        "code": ("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
                 "<title>随手记</title>\n<style>\n"
                 "  body { font: 15px/1.75 system-ui, 'Microsoft YaHei UI', sans-serif;\n"
                 "         max-width: 620px; margin: 48px auto; padding: 0 20px; color: #1d1d1f; }\n"
                 "  h1 { font-size: 22px; letter-spacing: -.02em; }\n"
                 "  li { margin: 5px 0; }\n"
                 "  code { background: #f2f2f7; padding: 1px 5px; border-radius: 4px; }\n"
                 "</style>\n</head>\n<body>\n"
                 "  <h1>随手记</h1>\n"
                 "  <ul>\n"
                 "    <li>HTML 源码可以直接存成一条命令，运行即用浏览器打开</li>\n"
                 "    <li><code>{args}</code> 会被替换成运行时输入的参数</li>\n"
                 "    <li>整段源码不出现在插件目录里，都在 user_data</li>\n"
                 "  </ul>\n</body>\n</html>")
    },
]

def command_path(alias):
    return os.path.join(CMDS_DIR, '%s.json' % alias)

def ensure_cmds_dir():
    if not os.path.isdir(CMDS_DIR):
        os.makedirs(CMDS_DIR, exist_ok=True)

def init_cmds_dir():
    if os.path.isdir(CMDS_DIR):
        return
    ensure_cmds_dir()
    for item in DEFAULT_COMMANDS:
        _write(item)

def _spec(type_id):
    return TYPES.get(type_id) or TYPES['python']

def normalize(item):
    type_id = item.get('type')
    code = str(item.get('code') or '')

    if type_id == 'pythonfile':
        type_id = 'shell'
        if code.strip() and not code.strip().lower().startswith('python'):
            code = 'python "%s"' % code.strip()

    if type_id not in TYPES:
        type_id = 'python'

    codes = {}
    raw_codes = item.get('codes')
    if isinstance(raw_codes, dict):
        for key, value in raw_codes.items():
            if key in TYPES:
                codes[key] = str(value or '')
    if 'code' in item:
        codes[type_id] = code
    elif type_id not in codes:
        codes[type_id] = ''
    codes = {k: v for k, v in codes.items() if v.strip() or k == type_id}
    code = codes.get(type_id, '')

    return {
        "alias": str(item.get('alias') or '').strip().lower(),
        "type": type_id,
        "description": str(item.get('description') or '').strip(),
        "code": code,
        "codes": codes,
        "cwd": str(item.get('cwd') or '').strip(),
        "env": str(item.get('env') or ''),
        "elevated": bool(item.get('elevated')),
        "after": item.get('after') if item.get('after') in ('none', 'clipboard', 'file') else 'none',
    }

def validate(item):
    item = normalize(item)
    if not item['alias']:
        return "激活命令不能为空。"
    if not ALIAS_RE.match(item['alias']):
        return "激活命令只能包含小写字母、数字、下划线或连字符。"
    if not item['code'].strip():
        return "%s 不能为空。" % (_spec(item['type'])['payload'] or '内容')
    return None

def _write(item):
    ensure_cmds_dir()
    payload = normalize(item)
    payload.pop('_new', None)
    with open(command_path(payload['alias']), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    return payload

def load_all_commands():
    commands = []
    if not os.path.isdir(CMDS_DIR):
        return commands
    for filename in os.listdir(CMDS_DIR):
        if not filename.endswith('.json'):
            continue
        try:
            with open(os.path.join(CMDS_DIR, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if not data.get('alias'):
            data['alias'] = os.path.splitext(filename)[0]
        commands.append(normalize(data))
    commands.sort(key=lambda x: x['alias'])
    return commands

def load_command(alias):
    path = command_path(alias)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return normalize(json.load(f))
    except Exception:
        return None

def save_command(item, original_alias=None):
    err = validate(item)
    if err:
        return False, err
    clean = normalize(item)
    alias = clean['alias']
    original_alias = str(original_alias or '').strip().lower() or None

    try:
        if original_alias is None:
            if os.path.exists(command_path(alias)):
                return False, "别名 '%s' 已经存在了，换一个吧。" % alias
        elif original_alias != alias:
            if os.path.exists(command_path(alias)):
                return False, "别名 '%s' 已经存在了。" % alias
            old = command_path(original_alias)
            if os.path.exists(old):
                os.remove(old)
        _write(clean)
    except OSError as e:
        return False, "保存失败：%s" % e
    return True, alias

def delete_command(alias):
    path = command_path(alias)
    if not os.path.exists(path):
        return False, "命令 '%s' 不存在。" % alias
    try:
        os.remove(path)
    except OSError as e:
        return False, "删除失败：%s" % e
    return True, alias

def _clip_types():
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [ctypes.c_void_p]
    u.OpenClipboard.restype = ctypes.c_bool
    u.CloseClipboard.restype = ctypes.c_bool
    u.EmptyClipboard.restype = ctypes.c_bool
    u.GetClipboardData.argtypes = [ctypes.c_uint]
    u.GetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.restype = ctypes.c_bool
    k.GlobalFree.argtypes = [ctypes.c_void_p]
    return ctypes, u, k

def _clipboard_get():
    if sys.platform != 'win32':
        return ''
    try:
        ctypes, u, k = _clip_types()
        CF_UNICODETEXT = 13
        if not u.OpenClipboard(None):
            return ''
        try:
            handle = u.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ''
            ptr = k.GlobalLock(handle)
            if not ptr:
                return ''
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k.GlobalUnlock(handle)
        finally:
            u.CloseClipboard()
    except Exception:
        return ''

def clipboard_set(text):
    if sys.platform != 'win32':
        return False
    try:
        ctypes, u, k = _clip_types()
        CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
        data = (text + "\x00").encode('utf-16-le')
        if not u.OpenClipboard(None):
            return False
        handle = None
        try:
            u.EmptyClipboard()
            handle = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            ptr = k.GlobalLock(handle)
            if not ptr:
                k.GlobalFree(handle)
                return False
            try:
                ctypes.memmove(ptr, data, len(data))
            finally:
                k.GlobalUnlock(handle)
            if not u.SetClipboardData(CF_UNICODETEXT, handle):
                k.GlobalFree(handle)
                return False
            handle = None
        finally:
            u.CloseClipboard()
        return True
    except Exception:
        return False

_DATE_FMT_RE = re.compile(r'\{date(?::([^}]*))?\}')

def expand(text, args=''):
    if not text:
        return text
    out = str(text)
    if '{clipboard}' in out:
        out = out.replace('{clipboard}', _clipboard_get())
    if '{args}' in out:
        out = out.replace('{args}', args or '')
    if '{time}' in out:
        out = out.replace('{time}', datetime.now().strftime('%H:%M:%S'))

    def _date(m):
        fmt = m.group(1) or '%Y-%m-%d'
        try:
            return datetime.now().strftime(fmt)
        except Exception:
            return datetime.now().strftime('%Y-%m-%d')

    return _DATE_FMT_RE.sub(_date, out)

def _parse_env(text):
    env = {}
    for line in str(text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        if key:
            env[key] = value.strip()
    return env

def split_args(text):
    if not text:
        return []
    if not isinstance(text, str):
        return list(text)
    s = text.strip()
    if not s:
        return []
    out, buf, quote = [], [], None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in ('"', "'"):
            quote = ch
        elif ch.isspace():
            if buf:
                out.append(''.join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append(''.join(buf))
    return out

_split_args = split_args

def build_command(item, args=None):
    item = normalize(item)
    raw_args = args if isinstance(args, str) else ' '.join(args or [])
    extra = _split_args(raw_args)
    code = expand(item['code'], raw_args)
    substituted = '{args}' in item['code']
    tail = [] if substituted else extra
    type_id = item['type']

    if type_id == 'python':
        return [sys.executable, '-c', code] + tail, False, tail
    if type_id == 'powershell':
        return (['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', code]
                + tail), False, tail
    full = code
    if tail:
        full += ' ' + ' '.join('"%s"' % a if ' ' in a else a for a in tail)
    return full, True, tail

def run_cwd(item):
    cwd = expand(normalize(item)['cwd'])
    if cwd and os.path.isdir(cwd):
        return cwd
    return None

def make_env(item, extra=None):
    env = os.environ.copy()
    for k, v in _parse_env(normalize(item)['env']).items():
        env[k] = expand(v)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env

def _open_url(url):
    import webbrowser
    url = (url or '').strip()
    if not url:
        return False, '没有填网址。'
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', url):
        url = 'https://' + url
    try:
        webbrowser.open(url)
    except Exception as e:
        return False, '无法打开网址：%s' % e
    return True, '已用默认浏览器打开：%s' % url

def _open_path(path):
    path = (path or '').strip().strip('"')
    if not path:
        return False, '没有填路径。'
    path = os.path.expandvars(os.path.expanduser(path))
    if not path.lower().startswith(('shell:', '::{', 'explorer.exe ')) and not os.path.exists(path):
        return False, '路径不存在：%s' % path
    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception as e:
        return False, '无法打开：%s' % e
    return True, '已打开：%s' % path

def _open_html(alias, source):
    import webbrowser
    if not (source or '').strip():
        return False, '没有填 HTML 源码。'
    try:
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        page = os.path.join(PREVIEW_DIR, '%s.html' % alias)
        with open(page, 'w', encoding='utf-8') as f:
            f.write(source)
    except OSError as e:
        return False, '写入页面失败：%s' % e
    try:
        webbrowser.open(page)
    except Exception as e:
        return False, '无法打开页面：%s' % e
    return True, '已生成并打开：%s' % page

def _shell_execute(exe, params, cwd=None):
    if sys.platform != 'win32':
        return False, '只有 Windows 支持提权运行。'
    try:
        import ctypes
        SW_SHOWNORMAL = 1
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', exe, params, cwd or None, SW_SHOWNORMAL)
        if int(rc) <= 32:
            return False, '提权运行失败（错误码 %s）。可能你取消了 UAC。' % rc
    except Exception as e:
        return False, '提权运行失败：%s' % e
    return True, '已请求管理员权限运行（提权进程的输出无法被捕获）。'

def _elevated_launch(item, args=None):
    item = normalize(item)
    raw_args = args if isinstance(args, str) else ' '.join(args or [])
    code = expand(item['code'], raw_args)
    type_id = item['type']
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
    except OSError as e:
        return False, '无法创建临时目录：%s' % e

    stamp = datetime.now().strftime('%H%M%S')
    cwd = run_cwd(item)
    if type_id == 'python':
        path = os.path.join(TEMP_DIR, '%s_%s.py' % (item['alias'], stamp))
        open(path, 'w', encoding='utf-8').write(code)
        return _shell_execute(sys.executable, '"%s"' % path, cwd)
    if type_id == 'powershell':
        path = os.path.join(TEMP_DIR, '%s_%s.ps1' % (item['alias'], stamp))
        open(path, 'w', encoding='utf-8-sig').write(code)
        return _shell_execute('powershell.exe',
                              '-NoProfile -ExecutionPolicy Bypass -File "%s"' % path, cwd)
    path = os.path.join(TEMP_DIR, '%s_%s.bat' % (item['alias'], stamp))
    open(path, 'w', encoding='mbcs', errors='replace').write(code)
    return _shell_execute('cmd.exe', '/c "%s"' % path, cwd)

def run_in_console(item, args=None):
    item = normalize(item)
    kind = _spec(item['type'])['kind']
    raw_args = args if isinstance(args, str) else ' '.join(args or [])

    if kind == 'builtin':
        code = expand(item['code'], raw_args)
        if item['type'] == 'url':
            ok, msg = _open_url(code)
        elif item['type'] == 'path':
            ok, msg = _open_path(code)
        else:
            ok, msg = _open_html(item['alias'], code)
        print(('[完成] ' if ok else '[错误] ') + msg)
        return 0 if ok else 1

    if item['elevated']:
        ok, msg = _elevated_launch(item, raw_args)
        print(('[完成] ' if ok else '[错误] ') + msg)
        return 0 if ok else 1

    argv, use_shell, _ = build_command(item, raw_args)
    try:
        subprocess.run(argv, shell=use_shell, cwd=run_cwd(item),
                       env=make_env(item, {'PA_EXEC_ARGS': raw_args or '',
                                           'PA_PLUGIN_ALIAS': item['alias']}))
    except Exception as e:
        print("[错误] 执行期间发生异常: %s" % e)
        return 1
    return 0

def _decode(raw):
    if not raw:
        return ''
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode(_PREFERRED_ENCODING)
    except (UnicodeDecodeError, LookupError):
        return raw.decode('utf-8', 'replace')

class _BaseSession:
    MAX_OUTPUT = 200 * 1024

    def __init__(self):
        self.id = uuid.uuid4().hex[:8]
        self.returncode = None
        self.truncated = False
        self._buf = b''
        self._lock = threading.Lock()
        self.finished = threading.Event()

    def _append(self, text):
        chunk = text.encode('utf-8', 'replace') if isinstance(text, str) else text
        with self._lock:
            if len(self._buf) < self.MAX_OUTPUT:
                self._buf += chunk
            else:
                self.truncated = True

    @property
    def running(self):
        return not self.finished.is_set()

    def poll(self):
        with self._lock:
            raw, truncated = self._buf, self.truncated
        out = _decode(raw)
        if truncated:
            out += '\n… 输出过长，已截断 …\n'
        return {'id': self.id, 'output': out, 'running': self.running,
                'returncode': self.returncode}

    def stop(self):
        raise NotImplementedError

class RunSession(_BaseSession):
    def __init__(self, item, args=None):
        super().__init__()
        self.item = normalize(item)
        self._proc = None
        self._after_done = False
        raw_args = args if isinstance(args, str) else ' '.join(args or [])
        kind = _spec(self.item['type'])['kind']

        if kind == 'builtin':
            self._run_builtin(raw_args)
            return

        if self.item['elevated']:
            ok, msg = _elevated_launch(self.item, raw_args)
            self._append(('[完成] ' if ok else '[错误] ') + msg + '\n')
            self.returncode = 0 if ok else 1
            self.finished.set()
            return

        argv, use_shell, _ = build_command(self.item, raw_args)
        self._proc = subprocess.Popen(
            argv, shell=use_shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=run_cwd(self.item),
            env=self._env(raw_args),
            creationflags=_NO_WINDOW,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _env(self, raw_args):
        return make_env(self.item, {
            'PA_EXEC_ARGS': raw_args or '',
            'PA_PLUGIN_ALIAS': self.item['alias'],
        })

    def _run_builtin(self, raw_args):
        code = expand(self.item['code'], raw_args)
        if self.item['type'] == 'url':
            ok, msg = _open_url(code)
        elif self.item['type'] == 'path':
            ok, msg = _open_path(code)
        else:
            ok, msg = _open_html(self.item['alias'], code)
        self._append(('[完成] ' if ok else '[错误] ') + msg + '\n')
        self.returncode = 0 if ok else 1
        self.finished.set()

    def _pump(self):
        stream = self._proc.stdout
        try:
            read1 = getattr(stream, 'read1', None) or stream.read
            while True:
                chunk = read1(4096)
                if not chunk:
                    break
                self._append(chunk)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass
            self._proc.wait()
            self.returncode = self._proc.returncode
            self._apply_after()
            self.finished.set()

    def _apply_after(self):
        action = self.item.get('after') or 'none'
        if action == 'none' or self._after_done:
            return
        self._after_done = True
        with self._lock:
            text = _decode(self._buf)
        if action == 'clipboard':
            ok = clipboard_set(text)
            self._append('\n[完成] 输出已复制到剪贴板。\n' if ok else '\n[错误] 写入剪贴板失败。\n')
        elif action == 'file':
            try:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                name = '%s_%s.txt' % (self.item['alias'], datetime.now().strftime('%Y%m%d_%H%M%S'))
                path = os.path.join(OUTPUT_DIR, name)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self._append('\n[完成] 输出已保存到：%s\n' % path)
            except OSError as e:
                self._append('\n[错误] 保存输出失败：%s\n' % e)

    def stop(self):
        if self._proc is not None and self._proc.poll() is None:
            self._kill_tree(self._proc.pid)
        self.finished.set()

    @staticmethod
    def _kill_tree(pid):
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
        except Exception:
            pass

def open_in_new_console(alias, args=None):
    main_py = os.path.join(PLUGIN_DIR, 'main.py')
    cmd = [sys.executable, main_py, '--run', alias] + _split_args(args)
    flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
    try:
        subprocess.Popen(cmd, creationflags=flags)
    except Exception as e:
        return False, "无法打开控制台窗口：%s" % e
    return True, alias

def session_for(item, args=None):
    return RunSession(normalize(item), args)
