# -*- coding: utf-8 -*-
"""
exec 插件的核心层：命令存储 + 执行。不含任何界面代码。

数据位置遵循 QuickTools 规范：宿主 pa 注入 PA_PLUGIN_DATA_DIR
（= pa_soft/user_data/exec），独立运行时退回插件自身目录。

执行模型刻意拆成两个正交维度，避免"类型"无限膨胀：
  · runner  —— 怎么执行：python / pythonfile / powershell / shell（都 spawn 进程）
  · builtin —— 宿主自己动手，不 spawn 进程：url / path / html
  · combo   —— 组合：按顺序调用已有命令
"""
import json
import locale
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime

# --- 路径 ---
# 兼容通过 exec() 或 python -c 启动时没有 __file__ 的情况
if '__file__' in globals():
    PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    PLUGIN_DIR = sys.path[0] if sys.path else os.getcwd()

# 宿主 moss 注入的插件专属数据目录 (= user_data/state/exec)；老 pa 的 PA_* 与插件目录作兜底
DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.environ.get('PA_PLUGIN_DATA_DIR') or PLUGIN_DIR
CMDS_DIR = os.path.join(DATA_DIR, 'cmds')
PREVIEW_DIR = os.path.join(DATA_DIR, 'preview')     # HTML 页面落盘处
OUTPUT_DIR = os.path.join(DATA_DIR, 'output')       # "输出存文件"落盘处
TEMP_DIR = os.path.join(DATA_DIR, 'tmp')            # 提权运行时用的临时脚本

ALIAS_RE = re.compile(r'^[a-z0-9_-]{1,64}$')

# 子进程管道的默认编码：中文 Windows 上是 cp936。
# 注意 stdout 被重定向成管道后，python 子进程用的也是它，所以 shell 和 python 一致。
_PREFERRED_ENCODING = locale.getpreferredencoding(False) or 'utf-8'

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


# ---------------------------------------------------------------- 类型表
# kind: proc=要 spawn 进程 / builtin=宿主自己动手 / combo=组合
#
# 这里刻意不再细分"Python 文件"——跑磁盘上的 .py 用命令行类型（python x.py）就够了，
# 多一个类型只是把同一个能力包装两遍。
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

# 界面上的可点选项。macOS 里"按类别看列表"的标准答案是**源列表侧栏**
# （Finder / 邮件 / 备忘录 / 系统设置都是），所以这里是侧栏的导航项，不是筛选标签：
#   · 一个选项可以覆盖多个底层类型（命令行 = CMD / PowerShell）
#   · icon 只是给前端挑图标的键，具体图形在界面里
#   · 冗余的能力合并掉，而不是靠换控件来容纳
PICKER = [
    {'id': 'python',  'label': 'Python', 'types': ['python'], 'icon': 'code'},
    {'id': 'command', 'label': '命令行', 'types': ['shell', 'powershell'], 'icon': 'terminal'},
    {'id': 'url',     'label': '网址',   'types': ['url'], 'icon': 'globe'},
    {'id': 'path',    'label': '路径',   'types': ['path'], 'icon': 'folder'},
    {'id': 'html',    'label': 'HTML',   'types': ['html'], 'icon': 'doc'},
]

# 一个选项下多个类型时，用这个顺序决定默认值；第一个也用于"切回来时的记忆"
PICKER_DEFAULT = {'command': 'shell'}

# 新建命令时让用户挑的一份扁平清单（类型一旦定下就不再允许切换）
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

# 参数占位符：写进代码/网址/路径里，运行时替换
PLACEHOLDERS = [
    {'token': '{args}', 'desc': '本次输入的参数'},
    {'token': '{clipboard}', 'desc': '剪贴板文本'},
    {'token': '{date}', 'desc': '今天，如 2026-09-22'},
    {'token': '{date:%Y%m%d}', 'desc': '自定义格式的日期'},
    {'token': '{time}', 'desc': '当前时间，如 14:30:05'},
]

# 运行后动作
AFTER_ACTIONS = [
    {'id': 'none', 'label': '不处理'},
    {'id': 'clipboard', 'label': '把输出复制到剪贴板'},
    {'id': 'file', 'label': '把输出保存到文件'},
]

DEFAULT_COMMANDS = [
    # ---------------- Python ----------------
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
    # ---------------- CMD ----------------
    {
        "alias": "ping", "type": "shell", "description": "ping 指定主机（参数填主机名或 IP）",
        "code": "ping {args}"
    },
    {
        "alias": "ports", "type": "shell", "description": "列出本机正在监听的端口",
        "code": "netstat -ano | findstr LISTENING"
    },
    # ---------------- PowerShell ----------------
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
    # ---------------- 网址 ----------------
    {
        "alias": "bd", "type": "url", "description": "百度搜索（参数填关键词）",
        "code": "https://www.baidu.com/s?wd={args}"
    },
    {
        "alias": "gh", "type": "url", "description": "GitHub 搜索仓库（参数填关键词）",
        "code": "https://github.com/search?q={args}&type=repositories"
    },
    # ---------------- 路径 ----------------
    {
        "alias": "downloads", "type": "path", "description": "打开「下载」文件夹",
        "code": r"%USERPROFILE%\Downloads"
    },
    {
        "alias": "tempdir", "type": "path", "description": "打开系统临时文件夹",
        "code": "%TEMP%"
    },
    # ---------------- HTML ----------------
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


# ---------------------------------------------------------------- 存储
def command_path(alias):
    return os.path.join(CMDS_DIR, '%s.json' % alias)


def ensure_cmds_dir():
    """懒加载：只有真正写入数据时才创建数据目录。"""
    if not os.path.isdir(CMDS_DIR):
        os.makedirs(CMDS_DIR, exist_ok=True)


def init_cmds_dir():
    """首次运行（数据目录还不存在）时播种内置示例命令。

    只在目录不存在时播种，这样用户把示例删光之后不会被"复活"。
    """
    if os.path.isdir(CMDS_DIR):
        return
    ensure_cmds_dir()
    for item in DEFAULT_COMMANDS:
        _write(item)


def _spec(type_id):
    return TYPES.get(type_id) or TYPES['python']


def normalize(item):
    """把任意输入规整成完整的一条命令（缺字段补默认值，向后兼容旧数据）。"""
    type_id = item.get('type')
    code = str(item.get('code') or '')

    # 迁移已下线的类型：pythonfile 的语义等价于"用命令行跑 python <路径>"
    if type_id == 'pythonfile':
        type_id = 'shell'
        if code.strip() and not code.strip().lower().startswith('python'):
            code = 'python "%s"' % code.strip()

    if type_id not in TYPES:
        type_id = 'python'

    # 内容按执行方式分开存：codes[类型] = 该类型自己的内容。
    # 这样切换执行方式时不会把网址当成 cmd 命令显示 —— 切过去是空的，切回来还在。
    codes = {}
    raw_codes = item.get('codes')
    if isinstance(raw_codes, dict):
        for key, value in raw_codes.items():
            if key in TYPES:
                codes[key] = str(value or '')
    # 顶层 code 是"当前类型内容"的镜像：显式给了就以它为准（手改 JSON 不会被人忽略，清空也算数）
    if 'code' in item:
        codes[type_id] = code
    elif type_id not in codes:
        codes[type_id] = ''
    # 顺手清掉空条目（切过但没填的类型），别在 JSON 里留噪音
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
    """返回错误信息；None 表示合法。"""
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
    """保存命令。支持改名（original_alias != alias 时迁移文件）。

    返回 (ok, payload)：ok=True 时 payload 是新别名；否则 payload 是错误信息。
    """
    err = validate(item)
    if err:
        return False, err
    clean = normalize(item)
    alias = clean['alias']
    # 别名一律小写；original_alias 也要归一，否则大小写不同会被误判成"改名撞车"
    original_alias = str(original_alias or '').strip().lower() or None

    try:
        if original_alias is None:
            # 新建：绝不允许覆盖已有命令，否则是静默的数据丢失
            if os.path.exists(command_path(alias)):
                return False, "别名 '%s' 已经存在了，换一个吧。" % alias
        elif original_alias != alias:
            # 改名：目标不能撞车，成功后再删旧文件
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


# ---------------------------------------------------------------- 剪贴板
# ⚠ ctypes 的默认返回值是 32 位 int，而 Windows 的 HANDLE 是 64 位。
#   不显式声明 restype，句柄会被高位截断 —— 剪贴板会"无声地"读写失败。
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
            # SetClipboardData 成功后所有权归系统，不能再 GlobalFree
            if not u.SetClipboardData(CF_UNICODETEXT, handle):
                k.GlobalFree(handle)
                return False
            handle = None
        finally:
            u.CloseClipboard()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 占位符
_DATE_FMT_RE = re.compile(r'\{date(?::([^}]*))?\}')


def expand(text, args=''):
    """把 {args} / {clipboard} / {date} / {time} 替换掉。"""
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
    """把参数串拆成列表。

    ⚠ 不能用 shlex.split：它的 posix 模式把反斜杠当转义符，
      D:\\downloads\\setup.zip 会被拆成 D:downloadssetup.zip ——
      Windows 上只要"参数填文件路径"就全废。这里按空白拆、双引号可分组、反斜杠原样保留。
    """
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


# 内部旧名，保持兼容
_split_args = split_args


# ---------------------------------------------------------------- 命令构造
def build_command(item, args=None):
    """返回 (argv, use_shell, extra_argv)。

    规则：代码里写了 {args} 就只做文本替换，不再额外追加命令行参数；
    没写就沿用老行为，把参数追加到命令后面。
    """
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
    """命令自己的 cwd；留空则继承调用者的当前目录。"""
    cwd = expand(normalize(item)['cwd'])
    if cwd and os.path.isdir(cwd):
        return cwd
    return None


def make_env(item, extra=None):
    """命令的运行环境：进程环境 + 命令自带的环境变量 + 宿主补充的少量变量。"""
    env = os.environ.copy()
    for k, v in _parse_env(normalize(item)['env']).items():
        env[k] = expand(v)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


# ---------------------------------------------------------------- 内置动作
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
    # shell: 是 Windows 引用特殊文件夹的标准方式（shell:startup / shell:RecycleBinFolder），
    # 这种路径 os.path.exists 判断不了，直接交给系统
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


# ---------------------------------------------------------------- 提权运行
def _shell_execute(exe, params, cwd=None):
    """ShellExecuteW runas：会弹 UAC。返回 (ok, message)。"""
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
    """提权运行：把代码落到临时文件再执行，避免引号地狱。"""
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


# ---------------------------------------------------------------- 控制台执行
def run_in_console(item, args=None):
    """在前台控制台里执行（保持 pa :exec <别名> 的原语义）。"""
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


# ---------------------------------------------------------------- 会话
def _decode(raw):
    """输出编码嗅探：先按 UTF-8 严格解，失败再按本地代码页（中文 Windows = cp936）。"""
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
    """界面轮询用的会话基类。输出按原始字节累积，轮询时才解码，"""
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
    """单条命令：进程类 spawn 进程并抓输出，内置动作直接做完。"""

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
        """给子进程的环境：额外塞两个宿主变量。

        PA_EXEC_ARGS —— 用户原样输入的参数串。argv 里的引号在拆参数时就被吃掉了，
                        插件想判断"用户是不是加了引号"只能靠这个。
        PA_PLUGIN_ALIAS —— 当前命令的别名。
        """
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
                chunk = read1(4096)          # 按块读，有数据就返回
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
    """新开一个独立控制台窗口执行命令（给交互式命令用，比如 ping）。"""
    main_py = os.path.join(PLUGIN_DIR, 'main.py')
    cmd = [sys.executable, main_py, '--run', alias] + _split_args(args)
    flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
    try:
        subprocess.Popen(cmd, creationflags=flags)
    except Exception as e:
        return False, "无法打开控制台窗口：%s" % e
    return True, alias


def session_for(item, args=None):
    """按命令类型返回合适的会话对象。"""
    return RunSession(normalize(item), args)
