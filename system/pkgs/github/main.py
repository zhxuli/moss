# -*- coding: utf-8 -*-
"""GitHub 可视化助手 —— **每个按钮 = 一条 git / gh 命令**。

三种跑法，共用同一份 `ui/`：

    moss :github                          开一个窗口（界面）
    在 moss 界面里点「运行」               内嵌到「界面」选项卡里（宿主给 MOSS_UI_EMBED=1）
    moss :github action=status path=D:\\x  命令行跑一个动作：先打「等价命令」，再打输出

两条设计上的规矩：
  ① **界面不做业务**：仓库 / 磁盘 / 同步状态全在这个文件里算好，前端只负责画。
  ② **每个动作都必须同时给出「等价命令行」** —— 这是这个包存在的意义（用多了自然会敲）。
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, 'ui', 'index.html')
TITLE = 'GitHub 可视化助手'

GIT = shutil.which('git') or 'git'
GH = shutil.which('gh')
TOOLS_DIR = os.path.join(os.environ.get('MOSS_PLUGIN_DATA_DIR') or
                         os.path.join(os.path.expanduser('~'), '.moss-github'), 'tools')
DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.path.join(HERE, '.data')
STORE = os.path.join(DATA_DIR, 'paths.json')

#: 起子进程时不要弹黑框（内嵌模式下特别明显）
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# ★ gh 自己会偷偷去 api.github.com 查"有没有新版本"，网络一卡它就把我们拖住。
#   这几个环境变量让它闭嘴 + 不联网，`gh auth status` 才能秒回。
os.environ.setdefault('GH_NO_UPDATE_NOTIFIER', '1')
os.environ.setdefault('GH_PROMPT_DISABLED', '1')
os.environ.setdefault('GH_PAGER', 'cat')
os.environ.setdefault('GH_NO_COLOR', '1')

#: 缺东西时给人点的网址（都不需要登录就能开）
URL_GIT = 'https://git-scm.com/download/win'
URL_GH = 'https://cli.github.com/'
URL_SIGNUP = 'https://github.com/signup'
URL_LOGIN = 'https://github.com/login'

#: 环境真的搞不定时，把这句话摆在人面前（别让人自己摸）
HELP_AI = ('实在弄不明白？在这个窗口外面跟 moss 的 AI 说一句'
           '「帮我把这台电脑的 Git / GitHub 环境弄好」——它能看到同样的信息，'
           '装什么、点哪儿，它替你弄。')


def refresh_tools():
    """重新找一遍 git / gh（含我们自己装在包里的便携版）。

    ★ 必须每次都重找：`GIT`/`GH` 是模块加载那一刻定下来的，用户刚装完 git 时
      这两个常量还是旧的（GIT 甚至是字符串 'git'），不刷新就永远"没装"。
    ★ 还要找 TOOLS_DIR 里的便携版 —— 那是不需要管理员权限就能装上的那份，
      真机上 winget 半天没动静时靠它（见 install_tool 里的说明）。
    """
    global GIT, GH
    got = shutil.which('git') or local_tool('git')
    if got:
        GIT = got
    got = shutil.which('gh') or local_tool('gh')
    if got:
        GH = got
    return GIT, GH


def local_tool(what):
    """我们替用户装在包自己目录里的便携版（不需要管理员权限那份）在哪儿。"""
    if what == 'gh':
        for rel in (('gh', 'bin', 'gh.exe'), ('gh', 'gh.exe')):
            p = os.path.join(TOOLS_DIR, *rel)
            if os.path.exists(p):
                return p
    else:
        for rel in (('git', 'cmd', 'git.exe'), ('git', 'bin', 'git.exe'),
                    ('git', 'mingw64', 'bin', 'git.exe')):
            p = os.path.join(TOOLS_DIR, *rel)
            if os.path.exists(p):
                return p
    return ''


#: 便携版从哪儿下（GitHub 官方 release 资产，不需要管理员权限）
PORTABLE = {
    'gh': dict(repo='cli/cli', pick=r'windows_amd64\.zip$', label='GitHub CLI'),
    'git': dict(repo='git-for-windows/git', pick=r'MinGit-.*-64-bit\.zip$', label='Git'),
}


def _http_json(url, timeout=20):
    import urllib.request                                            # noqa: PLC0415
    req = urllib.request.Request(url, headers={'User-Agent': 'moss-github',
                                              'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:          # noqa: S310
        return json.loads(r.read().decode('utf-8', 'replace'))


#: 下不动 github.com 时的备用通道（国内常见：直连被断，走加速反而能下）
MIRRORS = ('', 'https://ghproxy.net/', 'https://mirror.ghproxy.com/',
           'https://gh-proxy.com/', 'https://ghfast.top/')

#: 查不到最新版本时退而求其次的固定版本（老一点但一定能下、能用）
FALLBACK_VER = {'gh': ('v2.63.2', 'gh_2.63.2_windows_amd64.zip'),
                'git': ('v2.47.1', 'MinGit-2.47.1-64-bit.zip')}


def install_portable(what):
    """下载官方便携版 zip → 解到 TOOLS_DIR → 记 EXIT_OK。

    ★ 为什么不用 winget 当主力（真机实测）：`winget install` 把输出重定向到文件时
      **一个字都不写**，还可能弹 UAC 半天不出来，人只能干等。便携版则：
      不需要管理员、进度能精确到百分比（边下边写日志）、装完马上就能用。

    ★ 再加一层保险（国内实测）：直连 github.com 经常 SSL 被断
      （`UNEXPECTED_EOF_WHILE_READING`）—— 查版本和下载都会失败。
      所以每条都按 MIRRORS 逐个试，一个通了就往下走；全不通才报失败。
    """
    spec = PORTABLE.get(what)
    js, log = install_paths(what)
    t0 = datetime.now()

    def say(line):
        try:
            with open(log, 'a', encoding='utf-8') as f:
                f.write('%s  %s\n' % (datetime.now().strftime('%H:%M:%S'), line))
        except Exception:                                            # noqa: BLE001
            pass

    try:
        say('开始下载 %s 的官方便携版（不需要管理员权限）' % spec['label'])
        # ① 先问发布页"最新是哪个版本"（直连 / 镜像都试一遍）
        tag, name, size, dl = '', '', 0, ''
        meta_err = ''
        for m in MIRRORS:
            try:
                base = ('https://api.github.com/repos/%s/releases/latest' % spec['repo'])
                rel = _http_json(m + base if m else base)
                tag = rel.get('tag_name') or ''
                for a in (rel.get('assets') or []):
                    if re.search(spec['pick'], a.get('name') or '', re.I):
                        name, size = a['name'], int(a.get('size') or 0)
                        dl = a['browser_download_url']
                        break
                if dl:
                    if m:
                        say('走的是加速通道 %s' % m)
                    break
            except Exception as e:                                   # noqa: BLE001
                meta_err = '%s: %s' % (type(e).__name__, e)
                say('查版本没成（%s）：%s' % (m or '直连', str(e)[:80]))
        if not dl:
            # ② 查不到就用固定版本（老一点，但文件路径是可预测的）
            tag, name = FALLBACK_VER[what]
            say('查不到最新版本（%s），改用固定版本 %s' % (meta_err[:60] or '网络不通', tag))
            dl = 'https://github.com/%s/releases/download/%s/%s' % (spec['repo'], tag, name)
        say('版本 %s，文件 %s（%s）' % (tag, name, human_size(size) if size else '大小未知'))
        os.makedirs(TOOLS_DIR, exist_ok=True)
        zpath = os.path.join(TOOLS_DIR, name)

        import urllib.request                                        # noqa: PLC0415
        # ③ 下载本体：同样一个通道一个通道试（直连 SSL 断掉很常见）
        got = 0
        last_err = ''
        for m in MIRRORS:
            src = (m + dl) if m else dl
            try:
                say('正在连 %s …' % (m or 'github.com 直连'))
                req = urllib.request.Request(src, headers={'User-Agent': 'moss-github'})
                got, last = 0, -10
                with urllib.request.urlopen(req, timeout=60) as r, open(zpath, 'wb') as f:  # noqa: S310
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if size:
                            pct = int(got * 100 / size)
                            if pct >= last + 10:
                                last = pct
                                say('正在下载… %d%%（%s / %s）'
                                    % (pct, human_size(got), human_size(size)))
                        else:
                            if got // (1024 * 1024) > (got - len(chunk)) // (1024 * 1024):
                                say('正在下载… 已收到 %s' % human_size(got))
                if got > 0:
                    if m:
                        say('这个通道通了：%s' % m)
                    break
            except Exception as e:                                   # noqa: BLE001
                last_err = '%s: %s' % (type(e).__name__, e)
                say('这个通道不行（%s）：%s' % (m or '直连', str(e)[:80]))
                got = 0
        if got <= 0:
            raise RuntimeError('所有下载通道都失败了，最后一个错误：%s' % last_err)
        say('下载完成，正在解压…')
        import zipfile                                               # noqa: PLC0415
        dest = os.path.join(TOOLS_DIR, what)
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(dest)
        try:
            os.remove(zpath)
        except OSError:
            pass
        refresh_tools()
        found = local_tool(what) or shutil.which(what)
        if not found:
            say('解压完了，但没找到可执行文件 —— 目录结构可能变了')
            return False, '解压后没找到可执行文件'
        say('装好了：%s（用了 %d 秒）' % (found, int((datetime.now() - t0).total_seconds())))
        say('EXIT_OK')
        mark_install(what, log=log, done=True, code=0)
        return True, found
    except Exception as e:                                           # noqa: BLE001
        say('下载/解压失败：%s: %s' % (type(e).__name__, e))
        say('EXIT_FAIL')
        mark_install(what, log=log, done=True, code=1)
        return False, str(e)


def browse_url(url):
    """用系统默认浏览器打开一个网址。返回 True/False（永远不抛）。"""
    url = str(url or '').strip()
    if not re.match(r'^https?://', url):
        return False
    try:
        import webbrowser                                            # noqa: PLC0415
        return bool(webbrowser.open(url))
    except Exception:                                                # noqa: BLE001
        return False


def open_url(url):
    """同上（给 Core 的方法用，名字短一点）。"""
    ok = browse_url(url)
    print('[github] 打开网址 %s → %s' % (url, 'ok' if ok else '失败'), flush=True)
    return ok


_NET_CACHE = {'at': 0.0, 'ok': False}

#: 环境检查结果缓存（4 秒）—— 界面上连点不会反复跑 git/gh 全套
_ENV_CACHE = {'path': '', 'at': 0.0, 'data': None}


def net_touch(host='github.com', port=443, timeout=3, cache=20):
    """能不能连上 github.com:443 —— 只判断"网通不通"，不下载任何东西。

    ★★ 这里踩过一个真坑（用户："点环境检查就一直卡着，等一分钟也不行"）：
      `socket.create_connection(timeout=3)` 的 timeout **只管 connect，不管 DNS**。
      国内解析 github.com 经常卡十几秒甚至更久，于是整个"环境检查"卡死；
      而界面内嵌模式下后端是**一条线程**在跑，卡住 = 整个界面点不动。
      所以现在：① DNS 放到单独线程里跑，超过 timeout 直接判"连不上"，绝不等；
      ② 结果缓存 20 秒，反复点检查不会反复去试网。
    """
    now = time.time()
    if now - _NET_CACHE['at'] < cache:
        return _NET_CACHE['ok']
    ok = [False]

    def probe():
        import socket                                                # noqa: PLC0415
        try:
            infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
            for fam, typ, proto, _cn, addr in infos[:2]:
                s = socket.socket(fam, typ, proto)
                s.settimeout(timeout)
                try:
                    s.connect(addr)
                    ok[0] = True
                    return
                finally:
                    s.close()
        except Exception:                                            # noqa: BLE001
            ok[0] = False

    import threading                                                 # noqa: PLC0415
    th = threading.Thread(target=probe, daemon=True)
    th.start()
    th.join(timeout + 0.5)          # 等不到就当作"连不上"，绝不拖住界面
    _NET_CACHE.update({'at': time.time(), 'ok': bool(ok[0])})
    return bool(ok[0])


def repo_probe(path):
    """只问三件事的"轻量探针"：这是不是仓库、在哪个根、远端是什么。

    ★ 为什么单独写一个：`repo_info()` 要跑十几个 git 命令（status / log / stash /
      tag / rev-list…）。环境检查只需要"是不是仓库 + 远端类型"，却把 repo_info
      调了两遍 —— 在慢盘 / 网络盘 / 大仓库上就是几十秒，界面直接冻住。
      这里只要 3 个命令、每个 6 秒上限，并且**每步失败就立刻返回**。
    """
    if not os.path.isdir(path):
        return None
    top = git(path, 'rev-parse', '--show-toplevel', timeout=6)
    if not top['ok']:
        return None
    root = (top['out'].splitlines() or [path])[-1].strip()
    if not os.path.isdir(root):
        return None
    br = git(root, 'rev-parse', '--abbrev-ref', 'HEAD', timeout=6)
    url = (git(root, 'remote', 'get-url', 'origin', timeout=6)['out'] or '').strip()
    return {'root': root, 'branch': (br['out'].strip() if br['ok'] else ''),
            'remote': url}


def push_ability(path, info=None):
    """**能不能往 GitHub 推送** —— 只看 git 自己的凭证，跟 gh 登录无关。

    ★ 这里踩过一个真坑（用户原话："之前还能推送呢，现在就提示我没登录"）：
      我一开始把「gh 没登录」当成了「不能推送」。这是错的 ——
      推送走的是 **git 的 credential**（Windows 上一般是 Git Credential Manager，
      第一次推会弹浏览器让你授权一次），跟 GitHub CLI 一点关系都没有。
      gh 只是"替你自动建仓库"用得上。所以两者必须分开判断。

    返回 {'can': 能不能推, 'how': 走的哪条路, 'why': 人话, 'need': 该做什么}
    """
    if info is None:
        info = repo_probe(path)
    if not info:
        return {'can': False, 'how': '', 'need': 'repo',
                'why': '这个文件夹还不是 git 仓库 —— 先「开始记录」'}
    root = info['root']
    url = info.get('remote') or ''          # repo_info 里这个字段叫 remote
    if not url:
        return {'can': False, 'how': 'none', 'need': 'remote',
                'why': '还没连云端仓库 —— 先点「备份到 GitHub」把仓库建上/填上地址'}
    helper = (git(root, 'config', '--get', 'credential.helper')['out'] or '').strip()
    if not helper:
        ghelper = (git(root, 'config', '--global', '--get', 'credential.helper')['out']
                   or '').strip()
        helper = helper or ghelper

    if url.startswith('git@') or url.startswith('ssh://') or url.startswith('ssh:'):
        keys = []
        for d in ('~/.ssh',):
            try:
                base = os.path.expanduser(d)
                keys += [f for f in os.listdir(base) if f.startswith('id_')] \
                    if os.path.isdir(base) else []
            except OSError:
                pass
        if keys:
            return {'can': True, 'how': 'ssh', 'helper': helper,
                    'why': '走 SSH 密钥（%s）—— 跟 gh 登录没关系，能推' % keys[0]}
        return {'can': False, 'how': 'ssh', 'need': 'ssh-key', 'helper': helper,
                'why': '这个仓库用 SSH 地址，但这台电脑没找到 SSH 密钥 —— 要么换成 '
                       'https 地址，要么去 GitHub 加一把公钥'}

    # https：有凭证助手（GCM 之类）就基本能推，第一次会弹浏览器授权
    if helper:
        nice = helper.split()[0] if helper.split() else helper
        return {'can': True, 'how': 'https', 'helper': helper,
                'why': '走 https + %s —— 第一次推送会弹一次浏览器让你登录 GitHub'
                       '（之后它就记住了），**不需要 gh 也不需要在这里专门登录**' % nice}
    return {'can': True, 'how': 'https', 'helper': '',
            'why': '走 https。没配凭证助手的话，第一次推送会直接在终端里问你的用户名和 '
                   'Personal Access Token；Win 上装了 Git 一般自带凭据管理器，会自动弹窗',
            'soft': True}


def git_identity(path=''):
    """读 git 署名（user.name / user.email）。给了仓库就读仓库那份。"""
    base = [GIT] + (['-C', path] if path and os.path.isdir(path) else [])
    nm = run(base + ['config', '--get', 'user.name'], timeout=10)
    em = run(base + ['config', '--get', 'user.email'], timeout=10)
    return {'name': (nm['out'] or '').strip() if nm['ok'] else '',
            'email': (em['out'] or '').strip() if em['ok'] else ''}


def ensure_identity(path, force=False):
    """没有署名就替人填一个。

    ★ 这是"第一次保存版本就失败"的头号原因：新装的 Git 没配 user.name/email，
      `git commit` 直接报 "Author identity unknown ... tell me who you are"。
      普通用户看到这句只会觉得"这软件坏了"。

    只写**这个仓库自己的** `.git/config`（不动全局，也不动别人的仓库）；
      万一这里还不是仓库，就先不写，等 init 之后再填。
    返回一句人能看懂的说明；什么都没动就返回空串。
    """
    refresh_tools()
    argv_git = [GIT] + (['-C', path] if path else [])
    inside = run(argv_git + ['rev-parse', '--git-dir'], timeout=15)['ok']
    cur = git_identity(path if inside else '')
    if cur['name'] and cur['email'] and not force:
        return ''
    who = (os.environ.get('USERNAME') or os.environ.get('USER') or 'moss').strip()
    name = cur['name'] or who or 'moss'
    slug = re.sub(r'[^0-9a-zA-Z._-]', '', name) or 'moss'
    mail = cur['email'] or ('%s@localhost' % slug)
    scope = [] if inside else ['--global']
    a = run(argv_git + ['config'] + scope + ['user.name', name], timeout=10)
    b = run(argv_git + ['config'] + scope + ['user.email', mail], timeout=10)
    if not (a['ok'] and b['ok']):
        return ''
    return ('我替你填好了署名：%s <%s>（只写进%s）。'
            '想换成自己的名字和邮箱，之后在设置里改就行。'
            % (name, mail, '这个仓库' if inside else '全局配置'))


#: 安装任务的状态文件 / 日志文件都在这里
def install_paths(what):
    os.makedirs(DATA_DIR, exist_ok=True)
    return (os.path.join(DATA_DIR, 'install.json'),
            os.path.join(DATA_DIR, 'install-%s.log' % what))


def mark_install(what, log='', done=False, code=None, kind=''):
    """记下安装这件事的状态。

    ★ 这一版是**为了让人看得见进度**才这么写的（V-14x 真机反馈）：
      第一版只 `Popen` 一下就把输出全丢了（DEVNULL），结果界面上既没有进度条
      也没有一行日志，人只能干等、也不知道到底在动还是在卡。
      现在改成：**把 winget 的输出整个写进日志文件**，界面每秒来读一次尾巴。
    """
    js, _ = install_paths(what)
    try:
        with open(js, 'w', encoding='utf-8') as f:
            json.dump({'what': what, 'at': time.time(), 'log': log,
                       'done': bool(done), 'code': code, 'kind': kind or ''}, f)
    except Exception:                                                # noqa: BLE001
        pass


def read_install():
    try:
        with open(os.path.join(DATA_DIR, 'install.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:                                                # noqa: BLE001
        return None


def pending_install():
    """有没有刚起步的安装（最近 15 分钟内还没结束），有就说一句。"""
    d = read_install()
    if not d or d.get('done'):
        return None
    ts = float(d.get('at') or 0)
    if time.time() - ts > 900:
        return None
    return {'what': d.get('what') or '', 'ago': rel_time(ts),
            'secs': int(time.time() - ts)}


def tail_log(path, limit=4000):
    """读日志尾巴（只读最后几 KB，文件再大也不会卡）。"""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size > limit:
                f.seek(size - limit)
            blob = f.read()
    except Exception:                                                # noqa: BLE001
        return ''
    text = blob.decode('utf-8', 'replace')
    if size > limit:
        text = text.split('\n', 1)[-1]        # 砍掉被截断的半行
    # winget 的进度条用 \r 反复覆写同一行 —— 只留最后那一段，不然满屏是碎片
    out = []
    for line in text.replace('\r\n', '\n').split('\n'):
        seg = line.split('\r')[-1].rstrip()
        if seg:
            out.append(seg)
    return '\n'.join(out[-40:])


def install_phase(text, found):
    """从日志里猜"现在到哪一步了"，好给人一句话。

    ★ 猜不准就显示"正在装"，别瞎报百分比。
    ★ 别拿 `found`（机器上有这个程序）当"装完了"—— 那会把"本来就有"
      和"正在下第 30%"混为一谈（真机上进度条会突然跳 100% 骗人）。
      这里只认日志里的 EXIT_OK / EXIT_FAIL。
    """
    low = (text or '').lower()
    if 'fail' in low or 'error' in low or '0x8' in low:
        if 'successfully' not in low and '已成功' not in low:
            return ('fail', '出错了')
    for k, v in (('正在下载', '正在下载'), ('downloading', '正在下载'),
                 ('下载完成', '正在解压'), ('正在解压', '正在解压'),
                 ('正在安装', '正在安装'), ('installing', '正在安装'),
                 ('正在连接', '正在连网'), ('正在连 ', '正在连网'),
                 ('正在启动', '正在准备'), ('starting', '正在准备'),
                 ('正在检查', '正在检查源'), ('searching', '正在检查源'),
                 ('已成功', '快好了'), ('successfully installed', '快好了')):
        if k in low:
            return ('run', v)
    return ('run', '正在装')


def install_percent(text):
    """从输出里抠最后一个百分比（抠不到返回 None，让界面显示"不确定"那种条）。"""
    hits = re.findall(r'(\d{1,3})\s*%', text or '')
    for h in reversed(hits):
        try:
            v = int(h)
        except ValueError:
            continue
        if 0 <= v <= 100:
            return v
    return None


# ------------------------------------------------------------------ 小工具
def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def rel_time(ts):
    d = time.time() - float(ts or 0)
    if d < 60:
        return '刚刚'
    if d < 3600:
        return '%d 分钟前' % (d // 60)
    if d < 86400:
        return '%d 小时前' % (d // 3600)
    return '%d 天前' % (d // 86400)


def human_size(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return ('%.0f %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024.0
    return '%.1f TB' % n


def display(argv):
    """把 argv 拼成**能敲的那一串**（教命令用，所以要像人敲的）。"""
    out = []
    for a in argv:
        if a == '' or re.search(r'[\s"]', a):
            out.append('"%s"' % a.replace('"', '\\"'))
        else:
            out.append(a)
    return ' '.join(out)


def run(argv, cwd=None, timeout=30):
    """跑一条命令。返回 {ok, code, out, ms, cmd}；**永不抛异常**。"""
    t0 = time.time()
    env = dict(os.environ)
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_PAGER': 'cat', 'PAGER': 'cat',
                'LC_ALL': env.get('LC_ALL') or 'C.UTF-8'})
    try:
        p = subprocess.run(argv, cwd=cwd or None, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           text=True, encoding='utf-8', errors='replace',
                           timeout=timeout, env=env, creationflags=NO_WINDOW)
        code, out = p.returncode, (p.stdout or '')
    except FileNotFoundError:
        code, out = 127, '找不到命令：%s —— 装了吗？在 PATH 里吗？' % argv[0]
    except subprocess.TimeoutExpired:
        code, out = 124, '超时：%s 秒还没回来（网络慢 / 要你输密码？）' % timeout
    except Exception as e:                                               # noqa: BLE001
        code, out = 1, '%s: %s' % (type(e).__name__, e)
    got = {'ok': code == 0, 'code': code, 'out': (out or '').strip('\n'),
           'ms': int((time.time() - t0) * 1000), 'cmd': display(argv)}
    # 慢的 / 失败的留一条日志（快而成功的直接跳过，别把日志冲成垃圾）
    log_cmd(argv, cwd, got, timeout)
    return got


# ------------------------------------------------------------------ 同步日志 / 带进度地跑
#: 每条"慢的 / 失败的"命令都在这儿留一条 —— 推送卡住时能回看它到底走到了哪一步。
#: 界面里的「同步日志」和 `moss :github action=gitlog` 读的就是这个文件。
SYNC_LOG = os.path.join(DATA_DIR, 'sync.log')
LOG_KEEP = 300          # 最多留多少条（再多就把最老的挤掉）
LOG_MAX = 512 * 1024

#: 这几条会真的上传 / 下载 —— 要补 `--progress`，还要边跑边打进度
PROGRESS_SUBS = ('push', 'fetch', 'pull', 'clone')


#: 内嵌模式（界面里的 iframe）—— 这时候 stdout 是协议通道，进度不能往里 print。
EMBEDDED = str(os.environ.get('MOSS_UI_EMBED') or '').strip().lower() in ('1', 'true', 'yes')


# ---------------------------------------------------------------- 长任务（后台跑 + 界面看进度）
#: 一次只跑一个长操作（推 / 拉 / 保存…）；界面拿 `id` 来轮询，能看到每一行进度的出处。
_JOB = {'cur': None}
_JOB_LOCK = threading.Lock()
#: 没有任务在跑时说过的话（内嵌模式下没法 print，先攒着）—— 开任务时当前情补在前面
_IDLE = collections.deque(maxlen=40)


def _live(line):
    """把一行进度交给"正在被看的那个任务"；没有任务就先攒着，等下开任务时补在前面。

    ★ 为什么不直接 print：内嵌模式下 stdout 是**协议通道**（一行一个 JSON），
      进度混进去宿主只会当垃圾丢弃 —— 用户那边就是"什么也看不到"。
      所以进度先进任务缓冲，界面 `job_state` 一取就有；命令行跑的时候照样打印。

    ★★ 这里**绝对不能再 print**（`_StdoutToProgress` 会把 print 转回本函数，
       变成自己叫自己 —— 递归到 RecursionError）。内嵌模式下没有任务时，
       攒进 `_IDLE` 就行：下次开任务会把它当作"前情"接在进度最前面。
    """
    text = str(line).rstrip()
    if not text:
        return
    with _JOB_LOCK:
        job = _JOB.get('cur')
    if job is not None:
        with job['lock']:
            job['lines'].append(text)
            job['beat'] = time.time()
            if len(job['lines']) > 600:
                del job['lines'][:200]
    elif EMBEDDED:
        _IDLE.append(text)
        return
    if EMBEDDED:
        # ★ 到这儿就不能再 print 了：内嵌模式下 print 已经被 `_StdoutToProgress`
        #   改回 `_live`，再 print 一次就是自己叫自己 —— 探针里那条
        #   「同一行刷了 80 遍」就是它（不是显示问题，是真的在递归）。
        return
    print(text, flush=True)


def _job_proc(proc):
    """把正在跑的子进程挂到当前任务上 —— 界面点「停一下」时能真的杀掉它。"""
    with _JOB_LOCK:
        job = _JOB.get('cur')
    if job is not None:
        with job['lock']:
            job['proc'] = proc


def _job_cancelled():
    """用户是不是点了「停一下」。

    ★ 探针抓到的：光靠 `p.kill()` 不够 —— 读输出的那条线程可能还阻塞在管道上，
      主循环于是继续一动不动地等（界面看着像"点了停也没停"）。所以主循环**自己**
      查这个标志，一看到就主动收尾，不等管道。
    """
    with _JOB_LOCK:
        job = _JOB.get('cur')
    if job is None:
        return False
    with job['lock']:
        return bool(job.get('cancel'))


def _kill_tree(proc):
    """连子孙一起杀（Windows 上 git 会拉起 git-remote-https 之类的小弟）。"""
    if proc is None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            proc.kill()
    except Exception:                                                    # noqa: BLE001
        try:
            proc.kill()
        except Exception:                                                # noqa: BLE001
            pass


def log_write(text):
    """往 sync.log 追加一段。**永不抛**（记日志不能拖累正事）。"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        old = []
        try:
            with open(SYNC_LOG, encoding='utf-8', errors='replace') as f:
                old = [x for x in f.read().splitlines() if x.strip()]
        except OSError:
            old = []
        # 一条记录以 "[时间]" 开头 —— 照它切条数，别把一条几行的记录拆散
        rows, cur = [], []
        for ln in old:
            if ln.startswith('[') and cur:
                rows.append(cur)
                cur = []
            cur.append(ln)
        if cur:
            rows.append(cur)
        rows.append(str(text).splitlines())
        rows = rows[-LOG_KEEP:]
        data = '\n'.join('\n'.join(r) for r in rows) + '\n'
        while len(data.encode('utf-8')) > LOG_MAX and len(rows) > 40:
            rows = rows[len(rows) // 2:]
            data = '\n'.join('\n'.join(r) for r in rows) + '\n'
        with open(SYNC_LOG, 'w', encoding='utf-8') as f:
            f.write(data)
        return True
    except Exception:                                                    # noqa: BLE001
        return False


def _sub(argv):
    """argv 里的子命令（`git push -u origin main` → `push`）。"""
    for a in list(argv)[1:]:
        if not a.startswith('-'):
            return a
    return ''


def log_cmd(argv, cwd, got, timeout=0, note=''):
    """把一条命令的"耗时 / 退出码 / 输出尾巴"记进 sync.log。

    ★ 只记**慢的（≥3 秒）和失败的**：正常命令一秒能跑几十条，全记会把有用的冲掉，
      真卡住的时候反而翻不到那一条。
    """
    ms = int(got.get('ms') or 0)
    if got.get('ok') and ms < 3000 and not note:
        return
    # 「探路」的命令天天失败（没配 upstream 时 rev-parse @{u} 必然 exit=128），
    # 记下来只会把真正慢的那条挤掉 —— 跳过它。
    joined = ' '.join(str(a) for a in argv)
    if not got.get('ok') and ms < 3000 and ('@{u}' in joined or 'rev-parse' in joined
                                            or 'symbolic-ref' in joined):
        return
    lines = ['[%s] %5.1fs exit=%s 超时上限=%ss'
             % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ms / 1000.0,
                got.get('code'), timeout or '-'),
             '    $ %s' % (got.get('cmd') or display(argv)),
             '    目录 %s' % (cwd or os.getcwd())]
    if note:
        lines.append('    说明 %s' % note)
    for t in [x.rstrip() for x in (got.get('out') or '').splitlines() if x.strip()][-10:]:
        lines.append('    | ' + t[:300])
    log_write('\n'.join(lines))


def run_progress(argv, cwd=None, timeout=300, tick=5.0, label=''):
    r"""跑一条会联网的命令：**边跑边把 git 的进度打出来**，每 tick 秒还报一次「还在跑」。

    ★ 由来（真机反馈）：第一次 `git push` 要传 178MB，可输出被 `subprocess.run`
      一口气攒到最后 —— 界面三十秒一个字都没有，人只能当成它死了。所以现在：
      ① 有 `--progress` 就让 git 在非终端下也报百分比；
      ② 逐块读输出、边读边打（git 的 `\r` 原地刷新改成一行一行）；
      ③ 每 tick 秒没新输出就打一行「还在跑…已 N 秒」—— 卡住也看得出是在动还是死了；
      ④ 整条命令记进 sync.log，事后能查。返回值跟 `run()` 完全一样。
    """
    t0 = time.time()
    cmd = list(argv)
    sub = _sub(cmd)
    if sub in PROGRESS_SUBS and '--progress' not in cmd:
        try:
            cmd.insert(cmd.index(sub) + 1, '--progress')
        except ValueError:
            pass
    env = dict(os.environ)
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_PAGER': 'cat', 'PAGER': 'cat',
                'GIT_PROGRESS_DELAY': '0',
                'LC_ALL': env.get('LC_ALL') or 'C.UTF-8'})
    title = label or display(cmd)
    _live('▶ %s（最多等 %d 秒）' % (title, int(timeout)))
    try:
        p = subprocess.Popen(cmd, cwd=cwd or None, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, encoding='utf-8', errors='replace',
                             env=env, creationflags=NO_WINDOW)
        _job_proc(p)                      # 挂上去，「停一下」才杀得掉
    except FileNotFoundError:
        got = {'ok': False, 'code': 127, 'ms': 0, 'cmd': display(cmd),
               'out': '找不到命令：%s —— 装了吗？在 PATH 里吗？' % cmd[0]}
        log_cmd(cmd, cwd, got, timeout)
        return got
    except Exception as e:                                               # noqa: BLE001
        got = {'ok': False, 'code': 1, 'ms': 0, 'cmd': display(cmd),
               'out': '%s: %s' % (type(e).__name__, e)}
        log_cmd(cmd, cwd, got, timeout)
        return got

    lock = threading.Lock()
    chunks, ended = [], [False]

    def _read():
        try:
            while True:
                bit = p.stdout.read(2048)
                if not bit:
                    break
                with lock:
                    chunks.append(bit)
        except Exception:                                                # noqa: BLE001
            pass
        finally:
            ended[0] = True

    threading.Thread(target=_read, daemon=True).start()
    out, last, killed = [], time.time(), False
    while True:
        time.sleep(0.25)
        with lock:
            fresh = ''.join(chunks)
            chunks.clear()
        if fresh:
            out.append(fresh)
            for seg in re.split(r'[\r\n]+', fresh):
                seg = seg.strip()
                if seg:
                    _live('   ' + seg[:200])
            last = time.time()
        if ended[0] and p.poll() is not None:
            break
        if _job_cancelled():
            # 用户点了「停一下」——别等管道，直接收掉
            killed = True
            _kill_tree(p)
            break
        if time.time() - t0 > timeout:
            killed = True
            try:
                p.kill()
            except Exception:                                            # noqa: BLE001
                pass
            break
        if time.time() - last > tick:
            _live('   …还在跑：已 %d 秒，还没有新输出（进程没死，就是慢）'
                  % int(time.time() - t0))
            last = time.time()
    try:
        code = p.wait(timeout=10)
    except Exception:                                                    # noqa: BLE001
        code = -1
    text_out = ''.join(out).strip('\n')
    if killed:
        if _job_cancelled():
            code = 130
            text_out = (text_out + '\n你点了「停一下」，这一步已经中断。'
                        '（已经传上去的部分不会坏，重新点一次会接着来）').strip('\n')
        else:
            code = 124
            text_out = (text_out + '\n超时：%d 秒还没回来（网络慢 / 要你输密码？）'
                        % timeout).strip('\n')
    got = {'ok': code == 0, 'code': code, 'out': text_out,
           'ms': int((time.time() - t0) * 1000), 'cmd': display(cmd)}
    _live('%s %s（%.1f 秒，退出码 %s）'
          % ('✓' if got['ok'] else '✗', title, got['ms'] / 1000.0, code))
    log_cmd(cmd, cwd, got, timeout)
    return got


def _exec(argv, cwd=None, timeout=60, label=''):
    """该看得见进度的走 run_progress（push / fetch / pull / clone），其余走 run。

    `MOSS_GIT_PROGRESS=0` 可以关掉（脚本里想只要最后那段输出时用）。
    """
    if _sub(list(argv)) in PROGRESS_SUBS and \
            str(os.environ.get('MOSS_GIT_PROGRESS', '1')).strip() != '0':
        return run_progress(argv, cwd=cwd, timeout=timeout, label=label)
    return run(argv, cwd=cwd, timeout=timeout)


def git(path, *args, **kw):
    return run([GIT, '-C', path] + list(args), **kw)


# ------------------------------------------------------------------ 路径记忆
def load_store():
    try:
        with open(STORE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:                                                    # noqa: BLE001
        d = {}
    if not isinstance(d, dict):
        d = {}
    recent = [p for p in (d.get('recent') or []) if isinstance(p, str) and p.strip()]
    return {'last': str(d.get('last') or ''), 'recent': recent}


def save_store(d):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STORE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STORE)
    except Exception:                                                    # noqa: BLE001
        pass


def remember(path):
    """把它记成「用过的路径」（最近的在最前，最多 12 条）。"""
    if not path:
        return
    d = load_store()
    key = os.path.normcase(os.path.abspath(path))
    recent = [p for p in d['recent'] if os.path.normcase(os.path.abspath(p)) != key]
    recent.insert(0, os.path.abspath(path))
    d['recent'] = recent[:12]
    d['last'] = os.path.abspath(path)
    save_store(d)


def _cwd_seed():
    """当前工作目录能不能当默认仓库？

    ★ 这里专门照顾「**拖动目录**」这条用法：`drop` 声明里写了 `cwd: true`，
      所以拖一个文件夹进来运行时，宿主会把**那个目录**设成工作目录
      （`MOSS_PKG_PARAMS` 里一个参数都没有 —— 路径是靠 cwd 传来的）。
      排除掉 moss 自己的安装目录，免得在里面跑 moss 时把 moss 当成"当前仓库"。
    """
    cwd = os.getcwd()
    home = os.path.abspath(os.environ.get('MOSS_HOME') or '')
    if home and os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(home):
        return ''
    return cwd if os.path.isdir(os.path.join(cwd, '.git')) else ''


def resolve_path(p):
    """挑一个「当前仓库目录」：显式给的 → 拖进来的（cwd）→ 上次用过的 → 记忆里的 → 家目录。"""
    p = str(p or '').strip().strip('"').strip("'")
    if p and os.path.isdir(p):
        return os.path.abspath(p)
    d = load_store()
    for cand in (_cwd_seed(), d.get('last'), *(d.get('recent') or []), os.getcwd(),
                 os.path.expanduser('~')):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.getcwd()


# ------------------------------------------------------------------ 仓库信息
def parse_status(text):
    """git status --porcelain 的一行行 → 给界面用的结构。"""
    rows, counts = [], {'staged': 0, 'unstaged': 0, 'untracked': 0, 'conflict': 0}
    for line in (text or '').splitlines():
        if len(line) < 3:
            continue
        xy, rest = line[:2], line[3:]
        path = rest.split(' -> ')[-1].strip()
        if xy == '??':
            flag = 'untracked'
        elif 'U' in xy or xy in ('AA', 'DD'):
            flag = 'conflict'
        elif xy[0] != ' ' and xy[1] != ' ':
            flag = 'both'
        elif xy[0] != ' ':
            flag = 'staged'
        else:
            flag = 'unstaged'
        counts[flag if flag in counts else 'unstaged'] += 1
        rows.append({'code': xy.strip() or '?', 'xy': xy, 'path': path,
                     'name': os.path.basename(path) or path, 'flag': flag})
    return rows, counts


def repo_info(path):
    """是这个仓库就回一份现成的信息；不是就回 None。"""
    if not os.path.isdir(path):
        return None
    top = git(path, 'rev-parse', '--show-toplevel', timeout=15)
    if not top['ok']:
        return None
    root = (top['out'].splitlines() or [path])[-1].strip()
    if not os.path.isdir(root):
        return None

    br = git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
    branch = br['out'].strip() if br['ok'] else ''
    up = git(root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    upstream = up['out'].strip() if up['ok'] else ''
    remote = git(root, 'remote', 'get-url', 'origin')
    rurl = remote['out'].strip() if remote['ok'] else ''
    if not rurl:
        first = git(root, 'remote')
        names = [n.strip() for n in (first['out'].splitlines() if first['ok'] else []) if n.strip()]
        if names:
            r2 = git(root, 'remote', 'get-url', names[0])
            rurl = r2['out'].strip() if r2['ok'] else ''

    ahead = behind = 0
    if upstream:
        ab = git(root, 'rev-list', '--left-right', '--count', 'HEAD...@{u}')
        if ab['ok']:
            parts = re.findall(r'\d+', ab['out'])
            if len(parts) >= 2:
                ahead, behind = int(parts[0]), int(parts[1])

    st = git(root, 'status', '--porcelain')
    changes, counts = parse_status(st['out'] if st['ok'] else '')

    last = {'hash': '', 'author': '', 'when': '', 'subject': ''}
    lg = git(root, 'log', '-1', '--pretty=format:%h\x1f%an\x1f%ar\x1f%s', timeout=20)
    if lg['ok'] and lg['out']:
        bits = (lg['out'].splitlines()[0]).split('\x1f')
        if len(bits) >= 4:
            last = {'hash': bits[0], 'author': bits[1], 'when': bits[2], 'subject': bits[3]}

    stash = git(root, 'stash', 'list')
    tags = git(root, 'tag', '--sort=-creatordate')
    return {
        'root': root, 'name': os.path.basename(root.rstrip('\\/')) or root,
        'branch': branch or '(空仓库)', 'detached': branch == 'HEAD',
        'upstream': upstream, 'remote': rurl, 'host': host_of(rurl),
        'ahead': ahead, 'behind': behind,
        'dirty': bool(changes), 'counts': counts, 'changes': changes[:200],
        'changeCount': len(changes),
        'lastCommit': last,
        'stashCount': len([x for x in (stash['out'].splitlines() if stash['ok'] else []) if x.strip()]),
        'tagCount': len([x for x in (tags['out'].splitlines() if tags['ok'] else []) if x.strip()]),
    }


def host_of(url):
    if not url:
        return ''
    m = re.match(r'^[a-zA-Z+]+://(?:[^@/]+@)?([^/:]+)', url)
    if m:
        return m.group(1)
    m = re.match(r'^(?:[^@]+@)?([^:]+):', url)
    if m:
        return m.group(1)
    return ''


def net_info(path, info, probe=None):
    if not info:
        return {'ok': False, 'why': '这不是一个 git 仓库，看不到远端同步情况'}
    fetch_head = os.path.join(info['root'], '.git', 'FETCH_HEAD')
    ts = None
    try:
        ts = os.path.getmtime(fetch_head)
    except OSError:
        pass
    if info['ahead'] and info['behind']:
        state = '分叉了（本地和远端都有对方的提交）'
    elif info['ahead']:
        state = '本地领先 %d 个提交（该 push）' % info['ahead']
    elif info['behind']:
        state = '本地落后 %d 个提交（该 pull）' % info['behind']
    elif info['upstream']:
        state = '和远端一致'
    else:
        state = '没有设置跟踪的远端分支（push -u origin %s 可以设上）' % (info['branch'] or 'main')
    return {
        'ok': True, 'remote': info['remote'], 'host': info['host'],
        'upstream': info['upstream'], 'ahead': info['ahead'], 'behind': info['behind'],
        'state': state, 'dirty': info['dirty'],
        'lastFetchTs': ts, 'lastFetch': (rel_time(ts) if ts else '没记录（还没 fetch 过）'),
        'probe': probe,
    }


# ------------------------------------------------------------------ 磁盘（含"残存盘符"）
DRIVE_TYPES = {0: '未知', 1: '没有根目录', 2: '可移动磁盘', 3: '本地磁盘',
               4: '网络盘', 5: '光驱', 6: '内存盘'}


def list_disks():
    """所有盘符 + 剩余空间。

    ★ 「残存盘符」= 系统里还留着这个盘符（`GetLogicalDrives` 说它在），
      但**读不出来**（`disk_usage` 失败）—— 拔掉的 U 盘、断掉的网络映射、
      没放盘的读卡器都长这样。这种盘点一下会卡半天，所以这里就把它标出来。
    """
    out = []
    if os.name != 'nt':
        try:
            u = shutil.disk_usage('/')
            out.append({'letter': '/', 'root': '/', 'type': '根目录', 'ready': True,
                        'total': u.total, 'used': u.used, 'free': u.free,
                        'pct': round(u.used * 100.0 / u.total, 1) if u.total else 0,
                        'totalText': human_size(u.total), 'freeText': human_size(u.free),
                        'why': ''})
        except OSError as e:
            out.append({'letter': '/', 'root': '/', 'type': '根目录', 'ready': False,
                        'total': 0, 'used': 0, 'free': 0, 'pct': 0,
                        'totalText': '-', 'freeText': '-', 'why': str(e)})
        return out

    import ctypes                                                     # noqa: PLC0415
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        letter = chr(ord('A') + i)
        root = letter + ':\\'
        try:
            code = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:                                                # noqa: BLE001
            code = 0
        item = {'letter': letter, 'root': root, 'type': DRIVE_TYPES.get(code, '未知')}
        try:
            u = shutil.disk_usage(root)
            item.update({'ready': True, 'total': u.total, 'used': u.used, 'free': u.free,
                         'pct': round(u.used * 100.0 / u.total, 1) if u.total else 0,
                         'totalText': human_size(u.total), 'freeText': human_size(u.free),
                         'why': ''})
        except OSError as e:
            item.update({'ready': False, 'total': 0, 'used': 0, 'free': 0, 'pct': 0,
                         'totalText': '-', 'freeText': '-',
                         'why': '盘符还在、但读不到（%s）—— 多半是拔了的 U 盘 / 断了的网络映射' % e})
        out.append(item)
    return out


# ------------------------------------------------------------------ 动作表（**核心：每个动作都带等价命令**）
def _p(ctx, plain):
    """普通 git 动作：不依赖仓库状态时用这个。"""
    return lambda p, a: plain


def _ctx(ctx):
    return ctx or {}


ACTIONS = {
    # ---- 看
    'status': dict(group='看', label='状态一览', danger=False, needArg=None, timeout=20,
                   cmd='git status --short --branch',
                   desc='改了哪些文件、在哪个分支 —— 一眼看清工作区',
                   argv=lambda p, a: ['git', 'status', '--short', '--branch']),
    'log': dict(group='看', label='最近提交', danger=False, needArg=None, timeout=30,
                cmd='git log --oneline --graph --decorate -n 20',
                desc='最近 20 条提交，带分支图（--oneline 是"一行一条"）',
                argv=lambda p, a: ['git', 'log', '--oneline', '--graph', '--decorate', '-n', '20']),
    'diff': dict(group='看', label='改动统计', danger=False, needArg=None, timeout=30,
                 cmd='git diff --stat',
                 desc='还没 git add 的改动，按文件统计行数',
                 argv=lambda p, a: ['git', 'diff', '--stat']),
    'branches': dict(group='看', label='分支列表', danger=False, needArg=None, timeout=20,
                     cmd='git branch -vv',
                     desc='本地分支 + 每个分支跟踪的远端（-vv 才看得到跟踪关系）',
                     argv=lambda p, a: ['git', 'branch', '-vv']),
    'remotes': dict(group='看', label='远端地址', danger=False, needArg=None, timeout=20,
                    cmd='git remote -v',
                    desc='这个仓库连着哪些远端',
                    argv=lambda p, a: ['git', 'remote', '-v']),
    'tags': dict(group='看', label='标签', danger=False, needArg=None, timeout=20,
                 cmd='git tag --sort=-creatordate',
                 desc='标签（按时间新到旧）',
                 argv=lambda p, a: ['git', 'tag', '--sort=-creatordate']),

    # ---- 同步
    'fetch': dict(group='同步', label='拉取远端信息', danger=False, needArg=None, timeout=120,
                  cmd='git fetch --all --prune',
                  desc='只更新远端的「账本」，不动你的代码（安全的联网动作）',
                  argv=lambda p, a: ['git', 'fetch', '--all', '--prune']),
    'pull': dict(group='同步', label='拉取并合并', danger=False, needArg=None, timeout=180,
                 cmd='git pull --ff-only',
                 desc='把远端新提交合进来；--ff-only ＝ 只能快进，会不会冲突当场就知道',
                 argv=lambda p, a: ['git', 'pull', '--ff-only']),
    'push': dict(group='同步', label='推送', danger=False, needArg=None, timeout=180,
                 cmd='git push',
                 desc='把本地提交推到远端（没设跟踪分支时会自动补 -u origin <分支>）',
                 argv=lambda p, a: (['git', 'push'] if (p or {}).get('upstream')
                                    else ['git', 'push', '-u', 'origin', (p or {}).get('branch') or 'HEAD'])),

    # ---- 改
    'add_all': dict(group='改', label='把改动收进来', danger=False, needArg=None, timeout=30,
                    cmd='git add -A',
                    desc='告诉 git「这些改动我都要」（git 管这一步叫暂存；-A ＝ 新增/修改/删除都算）',
                    argv=lambda p, a: ['git', 'add', '-A']),
    'commit': dict(group='改', label='在本地存一个版本', danger=False, needArg='这次改了啥', timeout=60,
                   cmd='git commit -m "说明"',
                   desc='把已经收进来的改动存成一个版本（信息别偷懒，将来的你会谢你）',
                   argv=lambda p, a: ['git', 'commit', '-m', a]),
    'new_branch': dict(group='改', label='新建分支', danger=False, needArg='新分支名', timeout=30,
                       cmd='git checkout -b <新分支名>',
                       desc='从当前提交处开一条新分支并切过去',
                       argv=lambda p, a: ['git', 'checkout', '-b', a]),
    'switch': dict(group='改', label='切换分支', danger=False, needArg='分支名', timeout=30,
                   cmd='git checkout <分支名>',
                   desc='切到已有分支（工作区有改动时 git 会拦住你）',
                   argv=lambda p, a: ['git', 'checkout', a]),
    'stash': dict(group='改', label='把改动收起来', danger=False, needArg=None, timeout=30,
                  cmd='git stash push -u',
                  desc='暂时不想提交的改动先收进抽屉（-u ＝ 连新文件一起），工作区就干净了',
                  argv=lambda p, a: ['git', 'stash', 'push', '-u']),
    'stash_pop': dict(group='改', label='取出收起的改动', danger=False, needArg=None, timeout=30,
                      cmd='git stash pop',
                      desc='把最近一次 stash 拿回来',
                      argv=lambda p, a: ['git', 'stash', 'pop']),
    'untrack': dict(group='改', label='从版本库里去掉（文件留在磁盘）', danger=True,
                    needArg='要剔除的目录或文件（如 .venv）', timeout=180,
                    cmd='git rm -r --cached -- <路径>',
                    desc='版本库里不该有的东西（虚拟环境、数据、大文件）用这个剔除：'
                         '以后不再跟着提交，磁盘上一个文件都不删',
                    argv=lambda p, a: ['git', 'rm', '-r', '-q', '--cached', '--', a]),
    'amend': dict(group='改', label='并进上一条提交', danger=True, needArg=None, timeout=120,
                  cmd='git commit --amend --no-edit',
                  desc='把现在暂存的东西并进最后那条提交（不新增一版、说明不变）'
                       ' —— 只在最后那条还没推到 GitHub 时用，推过就别动它了',
                  argv=lambda p, a: ['git', 'commit', '--amend', '--no-edit']),
    'init': dict(group='改', label='初始化仓库', danger=False, needArg=None, timeout=30,
                 cmd='git init',
                 desc='把一个普通目录变成 git 仓库（不带 -b，免得老版本 git 不认这个参数）',
                 argv=lambda p, a: ['git', 'init']),
    'clone': dict(group='改', label='克隆仓库', danger=False, needArg='仓库地址', timeout=300,
                  cmd='git clone <仓库地址>',
                  desc='把远端仓库克隆到当前目录下面（地址形如 https://github.com/用户/仓库.git）',
                  argv=lambda p, a: ['git', 'clone', a]),

    # ---- GitHub CLI（gh）
    'gh_auth': dict(group='gh', label='gh 登录状态', danger=False, needArg=None, timeout=30, gh=True,
                    cmd='gh auth status',
                    desc='看看 GitHub CLI 登没登、用的哪个账号',
                    argv=lambda p, a: [GH or 'gh', 'auth', 'status']),
    'gh_pr': dict(group='gh', label='PR 列表', danger=False, needArg=None, timeout=60, gh=True,
                  cmd='gh pr list --limit 10',
                  desc='当前仓库的 Pull Request（要先装 GitHub CLI 并登录）',
                  argv=lambda p, a: [GH or 'gh', 'pr', 'list', '--limit', '10']),
    'gh_issue': dict(group='gh', label='Issue 列表', danger=False, needArg=None, timeout=60, gh=True,
                     cmd='gh issue list --limit 10',
                     desc='当前仓库的 issue 列表',
                     argv=lambda p, a: [GH or 'gh', 'issue', 'list', '--limit', '10']),
    'gh_repo': dict(group='gh', label='仓库概览', danger=False, needArg=None, timeout=60, gh=True,
                    cmd='gh repo view',
                    desc='在 GitHub 上这个仓库长什么样（描述 / star / 默认分支）',
                    argv=lambda p, a: [GH or 'gh', 'repo', 'view']),

    # ---- 本机（不是 git 命令，但也算"看一下"）
    'disks': dict(group='本机', label='磁盘与残存盘符', danger=False, needArg=None, timeout=10,
                  cmd='（本机 API：GetLogicalDrives + disk_usage）', fake='disks',
                  desc='所有盘符的剩余空间；拔掉的 U 盘 / 断了的网络映射会标成「残存盘符」',
                  argv=lambda p, a: []),
    'version': dict(group='本机', label='git 版本', danger=False, needArg=None, timeout=20,
                    cmd='git --version', desc='先确认 git 在不在、什么版本',
                    argv=lambda p, a: ['git', '--version']),
    'bigfiles': dict(group='看', label='仓库体积排行（谁占地方）', danger=False,
                     needArg=None, timeout=20, fake='bigfiles',
                     cmd='（本机统计：git ls-files + 文件大小）',
                     desc='推送慢得离谱时先看这个：哪些文件把仓库撑大了（虚拟环境 / 数据 / 视频）',
                     argv=lambda p, a: []),
    'precheck': dict(group='同步', label='推送前体检（会不会推不上去）', danger=False,
                     needArg=None, timeout=20, fake='precheck',
                     cmd='（本机统计：git ls-tree -r -l HEAD）',
                     desc='推之前先看清楚：这一推多大、有没有 GitHub 装不下的文件（>100MB 一定失败）',
                     argv=lambda p, a: []),
    'shield': dict(group='改', label='屏蔽（不跟着提交）', danger=False,
                   needArg='要屏蔽的目录或文件（如 .venv 或 backend/static/xxx/）', timeout=240,
                   cmd='写入 .gitignore + git rm -r --cached -- <路径>',
                   desc='把"不该进仓库"的东西一步处理干净：记进 .gitignore，已经跟踪的从库里去掉，'
                        '磁盘上的文件一个都不删',
                   argv=lambda p, a: []),
    'ignore': dict(group='看', label='屏蔽清单（.gitignore）', danger=False,
                   needArg=None, timeout=20, fake='ignore',
                   cmd='（读 .gitignore）',
                   desc='看一眼现在屏蔽了什么；哪一条其实还在库里（隐患）也会标出来',
                   argv=lambda p, a: []),
    'gitlog': dict(group='本机', label='同步日志（推送 / 拉取过程）', danger=False,
                   needArg=None, timeout=10, cmd='（读 %s）' % SYNC_LOG,
                   desc='推送卡住 / 失败时先看这个：每条慢命令的耗时、退出码和最后几行输出',
                   argv=lambda p, a: []),
}

#: 这些动作不需要在 git 仓库里跑
NO_REPO_NEEDED = ('disks', 'version', 'clone', 'gh_auth', 'init', 'gitlog')


def actions_payload():
    out = []
    for name, s in ACTIONS.items():
        out.append({'name': name, 'group': s['group'], 'label': s['label'],
                    'desc': s['desc'], 'cmd': s['cmd'], 'danger': bool(s.get('danger')),
                    'needArg': s.get('needArg') or '', 'gh': bool(s.get('gh'))})
    return out


def repo_size_rows(root, limit=20):
    """版本库里**最占体积**的文件（按大小排前 N 个）+ 总共多少、多大。

    ★ 为什么要有：推送"三十秒没反应"最常见的原因就是**仓库里有不该提交的大文件**
      （虚拟环境、数据集、视频、模型权重）—— 首次推送要把它整个传上去。
      以前只能靠猜；这一眼就能看出是哪个文件、多大。
    """
    got = git(root, 'ls-files', '-z', timeout=120)
    names = [x for x in (got.get('out') or '').split('\0') if x.strip()]
    if not got.get('ok') or not names:
        return {'count': 0, 'bytes': 0, 'top': [], 'ok': False,
                'why': (got.get('out') or '').strip()[:200]}
    rows, total = [], 0
    for n in names:
        try:
            sz = os.path.getsize(os.path.join(root, n.replace('/', os.sep)))
        except OSError:
            sz = 0
        total += sz
        rows.append((sz, n))
    rows.sort(reverse=True)
    return {'count': len(names), 'bytes': total, 'ok': True,
            'top': [{'path': n, 'bytes': sz, 'size': human_size(sz)}
                    for sz, n in rows[:limit]]}


def _fake_out(name, path):
    if name == 'precheck':
        info = repo_info(path)
        if not info:
            return '这不是一个 git 仓库：%s' % path
        r = Core(path).push_check({'path': path})
        if not r.get('ok'):
            return '读不出来：%s' % (r.get('why') or '')
        out = ['这一推要传 %d 个文件，一共 %s（%d 个提交）。'
               % (r['files'], r['size'], r['commits'])]
        if not r['big']:
            out.append('没有偏大的文件 —— 可以放心推。')
            return '\n'.join(out)
        out.append('')
        out.append('★ 有 %d 个文件偏大：' % len(r['big']))
        for b in r['big']:
            out.append('  [%s] %s  %s' % ('推不上去' if b['level'] == 'block' else '偏大',
                                          b['size'], b['path']))
        if r['blocked']:
            out.append('')
            out.append('⇒ 这一推会失败（GitHub 单文件上限 %s）。先屏蔽掉那几个目录再推。'
                       % r['limitHard'])
        return '\n'.join(out)
    if name == 'ignore':
        return ''
    if name == 'bigfiles':
        info = repo_info(path)
        if not info:
            return '这不是一个 git 仓库：%s' % path
        r = repo_size_rows(info['root'])
        if not r['ok']:
            return '读不出来：%s' % (r.get('why') or 'git ls-files 没答话')
        out = ['版本库里一共 %d 个文件，%s' % (r['count'], human_size(r['bytes'])),
               '其中最占体积的 %d 个：' % len(r['top'])]
        for i, f in enumerate(r['top'], 1):
            out.append('  %2d. %-10s %s' % (i, f['size'], f['path']))
        if r['bytes'] > 50 * 1024 * 1024:
            out.append('')
            out.append('★ 超过 50MB 了 —— 推送会慢，甚至被 GitHub 拒（单文件上限 100MB）。')
            out.append('  虚拟环境 / 数据 / 视频这类东西该用「从版本库里去掉」剔出去。')
        return '\n'.join(out)
    if name == 'disks':
        # 一行一个盘（不做表格式对齐 —— 中英混排按列对齐一定歪）
        rows = []
        for d in list_disks():
            if d['ready']:
                rows.append('%s  %s  剩余 %s / %s（已用 %s%%）'
                            % (d['root'], d['type'], d['freeText'], d['totalText'], d['pct']))
            else:
                rows.append('%s  %s  ★ 残存盘符：%s' % (d['root'], d['type'], d['why']))
        if not rows:
            rows = ['没读到任何盘符（GetLogicalDrives 返回空？）']
        return '\n'.join(rows)
    return ''


# ------------------------------------------------------------------ 时间线 / 分支 / 标签
UNIT = '\x1f'


def _rows(text, fields):
    """把 `%x1f` 分隔的多行输出切成一条条记录（字段少的补空）。"""
    out = []
    for line in (text or '').splitlines():
        if not line.strip():
            continue
        bits = line.split(UNIT)
        if len(bits) < fields:
            bits += [''] * (fields - len(bits))
        out.append(bits[:fields])
    return out


def _rev_count(root, rev):
    """某个引用上有多少个提交（界面上「V-384」里的那个 384）。读不到就当 0。"""
    got = git(root, 'rev-list', '--count', rev, timeout=25)
    try:
        return int((got['out'] or '0').strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


def _upstream_hashes(root, upstream, cap=4000):
    """远端能看到哪些提交 —— 时间线靠它标「已推送 / 只在本地」。

    ★ 只在本地读 `git rev-list`，**不联网**；上限 `cap` 条，超了就宁可标不准
      （回 capped=True，界面会说明），也不让大仓库把界面卡住。
    """
    if not upstream:
        return set(), False
    got = run([GIT, '-C', root, 'rev-list', '--max-count=%d' % cap, upstream], timeout=30)
    if not got['ok']:
        return set(), False
    lines = [x.strip() for x in got['out'].splitlines() if x.strip()]
    return set(lines), len(lines) >= cap


def git_log_rows(root, limit=40, rev='HEAD'):
    """一条提交一行（用 UNIT 分隔，省得跟提交信息里的空格 / 竖线打架）。"""
    fmt = UNIT.join(['%H', '%h', '%an', '%ae', '%ad', '%ar', '%s', '%D', '%P'])
    got = git(root, 'log', '-n', str(limit), '--date=format:%Y-%m-%d %H:%M',
              '--pretty=format:' + fmt, rev, timeout=35)
    rows = []
    for h, short, an, ae, ad, ar, subj, deco, parents in _rows(got['out'], 9):
        rows.append({'hash': h, 'short': short, 'author': an, 'email': ae,
                     'when': ad, 'rel': ar, 'subject': subj,
                     'refs': [d.strip() for d in deco.split(',') if d.strip()],
                     'parents': [x for x in parents.split() if x],
                     'merge': len(parents.split()) > 1})
    return rows, got


def branch_rows(root):
    """本地分支 + 远端分支，一次 for-each-ref 拿全（比一条条问快得多）。"""
    fmt = UNIT.join(['%(refname:short)', '%(refname)', '%(objectname:short)',
                     '%(upstream:short)', '%(upstream:track,nobracket)',
                     '%(committerdate:relative)', '%(contents:subject)'])
    got = git(root, 'for-each-ref', '--sort=-committerdate', '--format=' + fmt,
              'refs/heads', 'refs/remotes', timeout=25)
    cur = git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
    current = cur['out'].strip() if cur['ok'] else ''
    local, remote = [], []
    for name, full, short, up, track, when, subj in _rows(got['out'], 7):
        if name.endswith('/HEAD'):
            continue
        ahead = behind = 0
        m = re.search(r'ahead (\d+)', track or '')
        if m:
            ahead = int(m.group(1))
        m = re.search(r'behind (\d+)', track or '')
        if m:
            behind = int(m.group(1))
        item = {'name': name, 'short': short, 'upstream': up, 'ahead': ahead,
                'behind': behind, 'when': when, 'subject': subj,
                'gone': 'gone' in (track or ''), 'current': name == current,
                'isRemote': full.startswith('refs/remotes/')}
        (remote if item['isRemote'] else local).append(item)
    return local, remote


def tag_rows(root, limit=40):
    fmt = UNIT.join(['%(refname:short)', '%(objectname:short)',
                     '%(creatordate:relative)', '%(contents:subject)'])
    got = git(root, 'for-each-ref', '--sort=-creatordate', '--format=' + fmt,
              'refs/tags', timeout=25)
    return [{'name': n, 'short': s, 'when': w, 'subject': (subj or '')[:80]}
            for n, s, w, subj in _rows(got['out'], 4)][:limit]


# ------------------------------------------------------------------ 后端（两种跑法共用这一份）
class Core:
    """界面能调的方法都在这儿；每个方法收一份 dict、回一份 dict。"""

    def __init__(self, path=''):
        self.default_path = str(path or '')
        self._gh_cache = (0.0, None)

    # ---- 参数
    def _path(self, params):
        return resolve_path((params or {}).get('path') or self.default_path)

    # ---- 信息
    def boot(self, params=None):
        v = run([GIT, '--version'], timeout=15)
        return {
            'pid': os.getpid(), 'python': sys.version.split()[0], 'cwd': os.getcwd(),
            'embedded': bool(str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes')),
            'home': os.path.expanduser('~'), 'platform': sys.platform,
            'git': {'installed': v['ok'], 'version': (v['out'].splitlines() or [''])[0]},
            'preferred': self._path(params), 'at': now_text(),
        }

    def actions(self, params=None):
        return {'actions': actions_payload(), 'groups': ['看', '同步', '改', 'gh', '本机']}

    def snapshot(self, params=None):
        path = self._path(params)
        info = repo_info(path)
        return {'path': path, 'isRepo': bool(info), 'repo': info,
                'net': net_info(path, info), 'recent': recent_payload(),
                'at': now_text(), 'atTs': time.time()}

    def disks(self, params=None):
        return {'disks': list_disks()}

    def untrack(self, params=None):
        """把某个目录 / 文件从**版本库**里去掉：磁盘上的文件一个都不动。

        ★ 为什么要有：`.venv`、数据目录、模型文件这类东西一旦被提交进去，每次
          push 都要把它们整个再传一遍（真事：一个项目的初版提交里躺着一整个
          虚拟环境，178MB —— 首次推送三十多秒没反应，看着像卡死）。
          这里先数清楚"要剔除多少个文件、多大"，再只从索引里移除；文件留在原处，
          删掉 `.gitignore` 里没写的话以后还会被 `git add` 收进来，所以顺手提醒一句。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': [], 'out': ''}
        root = info['root']
        rel = str(p.get('arg') or p.get('file') or '').strip().replace('\\', '/').strip('/')
        cmd_text = 'git rm -r -q --cached -- %s' % (rel or '<路径>')
        if not rel or rel.startswith('/') or '..' in rel.split('/'):
            return {'ok': False, 'cmd': cmd_text, 'steps': [], 'out': '',
                    'why': '只能填仓库里的相对路径，例如 .venv'}
        ls = git(root, 'ls-files', '-z', '--', rel, timeout=90)
        names = [x for x in (ls.get('out') or '').split('\0') if x.strip()]
        if not names:
            return {'ok': False, 'cmd': 'git ls-files -- ' + rel, 'steps': [], 'out': '',
                    'why': '%s 现在没被版本库跟踪 —— 没东西可剔除。'
                           '想让它以后也别被收进来，把 %s 写进 .gitignore 里'
                           % (rel, rel)}
        total = 0
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n.replace('/', os.sep)))
            except OSError:
                pass
        got = self._step(root, ['git', 'rm', '-r', '-q', '--cached', '--', rel],
                         '把 %s 从版本库去掉（磁盘上的文件留着）' % rel, 180)
        out = self._finish(path, [got])
        out['count'] = len(names)
        out['bytes'] = total
        out['label'] = '从版本库里去掉 %s' % rel
        out['note'] = ('%s 里的 %d 个文件（%s）已从版本库去掉，磁盘上还在。'
                       '记得把 %s 写进 .gitignore，否则下次「把改动收进来」又会收进去'
                       % (rel, len(names), human_size(total), rel))
        return out

    def sync_log(self, params=None):
        """把 sync.log 的尾巴读出来（命令行 `action=gitlog` 和界面都用它）。

        ★ 为什么要有：推送卡住时，界面上只有一行"还在跑"，用户问"到底在干什么" ——
          以前**没有任何记录**（push 的输出攒到最后才返回，进程被杀就全丢了）。
          现在每条慢命令都落在这里，事后能看是谁慢、慢几秒、卡在哪一句。
        """
        p = params or {}
        try:
            n = int(p.get('n') or 80)
        except (TypeError, ValueError):
            n = 80
        n = max(5, min(400, n))
        rows = []
        try:
            with open(SYNC_LOG, encoding='utf-8', errors='replace') as f:
                rows = [x.rstrip() for x in f.read().splitlines() if x.strip()]
        except OSError:
            rows = []
        tail = rows[-n:]
        return {'ok': True, 'path': SYNC_LOG, 'exists': bool(rows),
                'lines': tail, 'total': len(rows),
                'out': '\n'.join(tail) or
                       '还没有日志 —— 先点一次「推送」或「同步」，之后这里就有了'}

    # ---------------------------------------------------------------- 长任务：后台跑，界面看进度
    def job_start(self, params=None):
        """把一次长操作（保存 / 备份 / 同步 / 获取最新版…）**放到后台跑**，立刻返回一个号。

        ★ 为什么要有（这是真机上"30 秒没反应"的根因之一）：
          以前界面是「发一条 RPC，然后等它回来」 —— 而 `moss-embed.js` 里那条 RPC 的
          上限写死 **30 秒**。首次推送 178MB 时，三十秒一到界面就报"后端 30 秒没回话"，
          可 git 其实还在传，用户以为失败了，就又点一次…… 现在改成：
            ① 这里只负责开跑、立刻返回 `id`（这条 RPC 一秒内就回，永远不会超时）；
            ② 界面拿 `id` 去 `job_state` 轮询：进度、耗时、最后几行输出都看得到；
            ③ 想停就 `job_cancel`（真的 kill 掉那个子进程）。
        """
        p = params or {}
        method = str(p.get('method') or '').strip()
        label = str(p.get('label') or method).strip() or method
        args = p.get('params') or {}
        if not isinstance(args, dict):
            args = {}
        args = dict(args)
        args.setdefault('path', self._path(p))
        fn = getattr(self, method, None)
        if not method or method.startswith('_') or not callable(fn) or method in (
                'job_start', 'job_state', 'job_cancel'):
            return {'ok': False, 'why': '不认识的操作：%s' % (method or '(空)')}
        with _JOB_LOCK:
            cur = _JOB.get('cur')
            if cur is not None and cur.get('state') == 'running':
                return {'ok': False, 'why': '已经有一个操作在跑了：%s' % cur['label'],
                        'id': cur['id'], 'running': True}
            job = {'id': '%d' % int(time.time() * 1000), 'label': label, 'state': 'running',
                   # 把"开任务之前说过的几句"接在前面：刚打开界面点一下，也能看到前因
                   'lines': list(_IDLE) + ['▶ %s 开始' % label],
                   'started': time.time(), 'beat': time.time(),
                   'result': None, 'lock': threading.Lock(), 'proc': None, 'cancel': False}
            _JOB['cur'] = job
            _IDLE.clear()
        threading.Thread(target=self._job_run, args=(job, fn, args), daemon=True).start()
        return {'ok': True, 'id': job['id'], 'label': label, 'method': method}

    def _job_run(self, job, fn, args):
        """在后台线程里跑真正的活；异常也收进 result，别让它无声无息地没了。"""
        try:
            res = fn(args)
            if not isinstance(res, dict):
                res = {'ok': True, 'out': str(res)}
        except Exception as e:                                          # noqa: BLE001
            res = {'ok': False, 'why': '%s: %s' % (type(e).__name__, e), 'steps': []}
            _live('✗ 出错了：%s: %s' % (type(e).__name__, e))
        with job['lock']:
            if job.get('cancel'):
                res['ok'] = False
                res['why'] = '你点了「停一下」，这次没做完（已经做完的部分都在，重新点一次会接着来）'
            job['result'] = res
            job['state'] = 'cancelled' if job.get('cancel') else 'done'
            job['ended'] = time.time()
            job['proc'] = None

    def job_state(self, params=None):
        """看一眼那个任务跑到哪了（界面每 0.4 秒问一次）。"""
        p = params or {}
        jid = str(p.get('id') or '')
        with _JOB_LOCK:
            job = _JOB.get('cur')
        if not job or (jid and job['id'] != jid):
            return {'ok': False, 'why': '这个任务不在了（可能已经跑完，或者窗口关过）'}
        try:
            n = int(p.get('n') or 80)
        except (TypeError, ValueError):
            n = 80
        with job['lock']:
            lines = job['lines'][-max(5, min(400, n)):]
            beat = job['beat']
            state = job['state']
            res = job['result']
        return {'ok': True, 'id': job['id'], 'label': job['label'], 'state': state,
                'elapsed': round(time.time() - job['started'], 1),
                # silent = 多少秒没有新动静 —— 界面靠它说"还在跑，只是慢"
                'silent': round(time.time() - beat, 1),
                'lines': lines, 'result': res}

    def job_cancel(self, params=None):
        """停掉正在跑的任务（真的 kill 子进程；已经跑完的返回"没在跑"）。"""
        p = params or {}
        jid = str(p.get('id') or '')
        with _JOB_LOCK:
            job = _JOB.get('cur')
        if not job or (jid and job['id'] != jid):
            return {'ok': False, 'why': '没有正在跑的任务'}
        with job['lock']:
            if job['state'] != 'running':
                return {'ok': True, 'state': job['state'], 'why': '它已经跑完了'}
            job['cancel'] = True
            proc = job['proc']
        _kill_tree(proc)
        _live('■ 你点了「停一下」，正在收尾…')
        return {'ok': True, 'state': 'cancelling',
                'why': '已经让它停下了' if proc is not None else '正在收尾'}

    # ---------------------------------------------------------------- 推之前先看清楚
    def push_check(self, params=None):
        """推送前体检：这一推大概多大、有没有 GitHub 装不下的文件。

        ★ 为什么要有（真事）：一个项目的初版提交里躺着一个 **182MB** 的语音模型文件，
          GitHub 单文件上限 100MB ⇒ 那一推**一定失败**，而且失败前先把 182MB 传一遍，
          界面上三十秒没动静，人只会以为软件坏了。现在点「备份到云端」之前先扫一遍
          版本库里的文件大小，先警告、先问，再决定屏蔽还是照推。
        """
        path = self._path(params or {})
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'big': []}
        root = info['root']
        files, total = [], 0
        got = git(root, 'ls-tree', '-r', '-l', 'HEAD', timeout=120)
        if got.get('ok'):
            for ln in (got.get('out') or '').splitlines():
                m = re.match(r'^\d+ \w+ ([0-9a-f]+)\s+(\d+)\t(.+)$', ln)
                if not m:
                    continue
                sz = int(m.group(2))
                total += sz
                files.append((sz, m.group(3)))
        else:
            r = repo_size_rows(root)
            files = [(f['bytes'], f['path']) for f in r.get('top', [])]
            total = r.get('bytes') or 0
        files.sort(reverse=True)
        LIMIT_HARD, LIMIT_WARN = 100 * 1024 * 1024, 50 * 1024 * 1024
        big = []
        for sz, name in files:
            if sz < LIMIT_WARN:
                break
            big.append({'path': name, 'bytes': sz, 'size': human_size(sz),
                        'level': 'block' if sz >= LIMIT_HARD else 'warn',
                        'why': ('%s —— GitHub 单个文件不能超过 100MB，这个一定推不上去'
                                % human_size(sz)) if sz >= LIMIT_HARD else
                               ('%s —— 偏大，推起来会慢' % human_size(sz)),
                        # 屏蔽的时候整条目录屏蔽更省事（不然一个模型目录里有几十个文件）
                        'pattern': (os.path.dirname(name).replace('\\', '/') + '/')
                                   if os.path.dirname(name) else name})
        ahead = 0
        if info.get('upstream'):
            n = git(root, 'rev-list', '--count', '%s..HEAD' % info['upstream'])
            try:
                ahead = int((n.get('out') or '0').strip() or 0)
            except ValueError:
                ahead = 0
        else:
            n = git(root, 'rev-list', '--count', 'HEAD')
            try:
                ahead = int((n.get('out') or '0').strip() or 0)
            except ValueError:
                ahead = 0
        return {'ok': True, 'path': path, 'files': len(files), 'bytes': total,
                'size': human_size(total), 'big': big,
                'blocked': bool([b for b in big if b['level'] == 'block']),
                'initial': not info.get('upstream'), 'commits': ahead,
                'limitHard': human_size(LIMIT_HARD), 'limitWarn': human_size(LIMIT_WARN),
                'gitignore': os.path.join(root, '.gitignore')}

    # ---------------------------------------------------------------- 屏蔽某个目录 / 文件
    def shield(self, params=None):
        """「屏蔽」一步做完：写进 `.gitignore` + 把已经被跟踪的从版本库去掉（磁盘不动）。

        参数 `patterns`：一条或几条要屏蔽的路径（目录结尾带 `/` 更清楚）。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        raw = p.get('patterns') or p.get('pattern') or []
        if isinstance(raw, str):
            raw = [raw]
        pats = []
        for x in raw:
            s = str(x).strip().replace('\\', '/')
            if not s or s.startswith('/') and '..' in s:
                continue
            s = s.lstrip('/').strip('/')
            if s and s not in pats:
                pats.append(s)
        if not pats:
            return {'ok': False, 'why': '没给要屏蔽的路径', 'steps': []}
        gi = os.path.join(root, '.gitignore')
        old = []
        try:
            with open(gi, encoding='utf-8', errors='replace') as f:
                old = [x for x in f.read().splitlines()]
        except OSError:
            old = []
        have = set(x.strip().strip('/') for x in old)
        add = [x for x in pats if x not in have and (x + '/') not in have]
        if add:
            try:
                os.makedirs(os.path.dirname(gi) or '.', exist_ok=True)
                with open(gi, 'a', encoding='utf-8') as f:
                    if old and old[-1].strip():
                        f.write('\n')
                    f.write('\n# moss：这些不跟着提交\n')
                    f.write('\n'.join(add) + '\n')
            except OSError as e:
                return {'ok': False, 'why': '写不进 .gitignore：%s' % e, 'steps': []}
        step = self._step(root, ['git', 'rm', '-r', '-q', '--cached', '--'] + pats,
                          '把 %s 从版本库里去掉（磁盘上的文件都留着）' % '、'.join(pats), 240)
        out = self._finish(path, [step])
        out['added'] = add
        out['patterns'] = pats
        out['label'] = '屏蔽 %s' % '、'.join(pats)
        return out

    def ignore(self, params=None):
        """`.gitignore` 的「看一眼 / 加一条 / 删一条」—— 界面上那张「屏蔽清单」。

        op = list（默认）/ add（要 pattern）/ remove（要 pattern 或 line）。
        ★ 为什么要有：以前"哪些东西没跟着提交"只写在某个隐藏文件里，普通人根本不知道
          有这回事、更不知道当初屏蔽了什么；出了问题只能找 AI 翻 `.gitignore`。
        """
        p = params or {}
        op = str(p.get('op') or 'list').strip()
        path = self._path(p)
        info = repo_info(path)
        root = (info or {}).get('root') or path
        gi = os.path.join(root, '.gitignore')
        lines = []
        try:
            with open(gi, encoding='utf-8', errors='replace') as f:
                lines = [x.rstrip() for x in f.read().splitlines()]
        except OSError:
            lines = []
        if op in ('add', 'remove'):
            pat = str(p.get('pattern') or '').strip().replace('\\', '/')
            if not pat:
                return {'ok': False, 'why': '没给要处理的规则', 'entries': []}
            if op == 'add':
                if pat.strip('/') in set(x.strip().strip('/') for x in lines if x.strip()):
                    return {'ok': True, 'entries': [], 'kept': True,
                            'why': '%s 已经在清单里了' % pat}
                try:
                    with open(gi, 'a', encoding='utf-8') as f:
                        if lines and lines[-1].strip():
                            f.write('\n')
                        f.write(pat + '\n')
                except OSError as e:
                    return {'ok': False, 'why': '写不进 .gitignore：%s' % e, 'entries': []}
            else:
                keep = [x for x in lines if x.strip() and x.strip() != pat.strip()
                        and x.strip().strip('/') != pat.strip().strip('/')]
                try:
                    with open(gi, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(keep) + ('\n' if keep else ''))
                except OSError as e:
                    return {'ok': False, 'why': '改不了 .gitignore：%s' % e, 'entries': []}
            try:
                with open(gi, encoding='utf-8', errors='replace') as f:
                    lines = [x.rstrip() for x in f.read().splitlines()]
            except OSError:
                lines = []
        return {'ok': True, 'path': path, 'file': gi, 'entries': self._ignore_rows(root, lines)}

    def _ignore_rows(self, root, lines):
        """每条规则现在还盖住哪些"已经被跟踪"的文件（这些才是隐患：屏蔽了但还在库里）。"""
        stats = {}
        tracked = []
        ign = git(root, 'ls-files', '-z', '-ci', '--exclude-standard', timeout=120)
        names = [x for x in (ign.get('out') or '').split('\0') if x.strip()][:300]
        if names:
            chk = git(root, 'check-ignore', '-v', '--', *names, timeout=120)
            for ln in (chk.get('out') or '').splitlines():
                m = re.match(r'^(.*?):(\d+):(.*)\t(.+)$', ln)
                if not m:
                    continue
                no = int(m.group(2))
                cur = stats.setdefault(no, {'count': 0, 'bytes': 0, 'files': []})
                cur['count'] += 1
                try:
                    cur['bytes'] += os.path.getsize(os.path.join(root, m.group(4)))
                except OSError:
                    pass
                if len(cur['files']) < 5:
                    cur['files'].append(m.group(4))
            tracked = names
        rows = []
        for i, ln in enumerate(lines, 1):
            t = ln.strip()
            if not t or t.startswith('#'):
                continue
            s = stats.get(i, {'count': 0, 'bytes': 0, 'files': []})
            rows.append({'line': i, 'pattern': t, 'tracked': s['count'],
                         'bytes': s['bytes'], 'size': human_size(s['bytes']),
                         'files': s['files']})
        return rows

    def bigfiles(self, params=None):
        """版本库里最占体积的文件（界面上「体积排行」用）。"""
        path = self._path(params or {})
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'top': []}
        r = repo_size_rows(info['root'], limit=int((params or {}).get('limit') or 20))
        r.update({'ok': bool(r.get('ok')), 'path': path, 'size': human_size(r.get('bytes') or 0)})
        return r

    def net_probe(self, params=None):
        path = self._path(params)
        info = repo_info(path)
        if not info or not info['remote']:
            return {'ok': False, 'why': '这个目录没有可探测的远端地址', 'cmd': 'git ls-remote --heads origin'}
        got = run([GIT, '-C', info['root'], 'ls-remote', '--heads', 'origin'], timeout=25)
        heads = len([x for x in got['out'].splitlines() if x.strip()])
        return {'ok': got['ok'], 'ms': got['ms'], 'cmd': 'git ls-remote --heads origin',
                'host': info['host'], 'heads': heads, 'code': got['code'],
                'out': '\n'.join(got['out'].splitlines()[:10]),
                'why': '' if got['ok'] else got['out'][:300]}

    def _gh(self):
        global GH
        ts, cached = self._gh_cache
        if cached and time.time() - ts < 60:
            return cached
        # ★ 直接问磁盘（`local_tool` 认便携版 + PATH），**不信**模块级那个 `GH` ——
        #   它是 import 那一刻定下来的，装完之后在新的进程里才准。
        #   这就是"明明装好了、界面还一直劝你装"的另一半原因。
        found = local_tool('gh') or shutil.which('gh')
        if found:
            GH = found
        res = {'installed': bool(found), 'version': '', 'loggedIn': False, 'user': '',
               'why': '', 'path': found or ''}
        if found:
            # ★ 超时收紧（15/20 → 8/10）：这俩以前是"界面卡一分钟"的帮凶。
            #   本地命令正常都是几十毫秒，真要 8 秒还没回来，就是它想联网而网不通。
            v = run([GH, '--version'], timeout=8)
            res['version'] = (v['out'].splitlines() or [''])[0]
            # ★ "装了但跑不起来"（杀软拦、权限、文件坏了）跟"没装"是两件事：
            #   以前统一当没装 ⇒ 界面劝你再装一份，装了还是这样，永远好不了。
            res['broken'] = not v['ok']
            a = run([GH, 'auth', 'status'], timeout=10)
            txt, low = a['out'] or '', (a['out'] or '').lower()
            res['loggedIn'] = bool(a['ok'] and 'logged in' in low)
            m = re.search(r'account\s+(\S+)', txt)
            res['user'] = m.group(1).strip() if m else ''
            if not res['loggedIn']:
                res['why'] = (txt or 'gh 说没登录（gh auth login 登一下）').strip()[:300]
        else:
            res['why'] = '这台机器上没有 gh（GitHub CLI）—— 有它才好管 PR / issue；装好再回来点一下'
        self._gh_cache = (time.time(), res)
        return res

    def gh(self, params=None):
        return self._gh()

    # ---------------------------------------------------------------- 界面报错（`ui/error-guard.js`）
    def ui_error(self, params=None):
        """把界面里没被接住的异常记一条（`ui/error-guard.js` 调过来的）。

        ★ 为什么要有：界面出错时只有 DevTools 控制台看得见 —— **用户看不见、AI 也读
          不到**。安装按钮那次"永远 0 秒"就是 `S.modalActs` 未初始化抛的 `TypeError`，
          三个人围着同一个死现象猜了三轮才找到。现在界面底部会弹一条红条，同时这里
          落一份日志，谁都能回看。

        ★ 两种跑法都到这儿（不用界面自己判断模式）：
          · 内嵌：iframe → `moss.call` → 宿主 → **本进程的 stdin**（`Embedded.loop`）；
          · 独立窗口：`window.pywebview.api.ui_error`（`build_api()` 按 Core 自动转发）。
        """
        p = params or {}
        rec = {
            'at': now_text(),
            'msg': str(p.get('msg') or '')[:500],
            'src': str(p.get('src') or '')[:300],
            'line': int(p.get('line') or 0),
            'col': int(p.get('col') or 0),
            'stack': str(p.get('stack') or '')[:1500],
            'mode': str(p.get('mode') or '')[:20],
            'url': str(p.get('url') or '')[:300],
        }
        path = os.path.join(DATA_DIR, 'ui-errors.log')
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            # 只留最近 40 条 / 64 KB：界面错误可能一秒几十条，不能无限长
            old = []
            try:
                with open(path, encoding='utf-8') as f:
                    old = [ln for ln in f.read().splitlines() if ln.strip()][-39:]
            except OSError:
                old = []
            old.append(json.dumps(rec, ensure_ascii=False))
            data = '\n'.join(old) + '\n'
            if len(data.encode('utf-8')) > 64 * 1024:
                old = old[-20:]
                data = '\n'.join(old) + '\n'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(data)
            print('[github] 界面报错：%s' % rec['msg'][:120], flush=True)
            return {'ok': True, 'path': path, 'kept': len(old)}
        except Exception as e:                                       # noqa: BLE001
            return {'ok': False, 'why': '记不下来：%s' % e}

    # ---- 环境体检：缺什么、能不能我替你补上、补不了给网址 ----
    def env_check(self, params=None):
        """把「这东西现在到底能不能用」一次说清。

        ★ 定这个接口的原因（真机上最常见的三种"用不了"）：
          ① 电脑没装 git —— 界面照样能开，但所有按钮点下去都失败，人不知道为啥；
          ② 装了 git 但没配 user.name/user.email —— 第一次「保存版本」就报
             "Author identity unknown"，这句话普通人看不懂；
          ③ 没装 gh / 装了没登录 —— 「自动建仓库并上传」点不动。
        所以这里把每一条都查出来，能自己补的直接补（见 install_tool / fix_identity /
        gh_login），补不了的给一个**能点的网址**和「装完还要做什么」。
        """
        path = self._path(params or {})
        # ★ 4 秒内重复点「环境检查」直接用上次结果 —— 界面上很容易连点，
        #   每次都把 git/gh 全套跑一遍就是白等。
        fresh = bool((params or {}).get('fresh'))
        c = _ENV_CACHE
        if not fresh and c.get('path') == path and c.get('data') \
                and time.time() - float(c.get('at') or 0) < 4:
            return c['data']
        refresh_tools()
        # 刚装完东西的那几分钟里，gh 的 60 秒缓存必须作废（否则"装好了还说没装"）
        _d = read_install()
        if fresh or (_d and _d.get('done')
                     and time.time() - float(_d.get('at') or 0) < 180):
            self._gh_cache = (0.0, None)
        # ★ 判"有没有 git"要连**便携版**一起看（`local_tool`）。以前这里只查 PATH
        #   （`shutil.which('git')`），于是"我们刚帮你把 git 装进 tools/ 了"这种情形
        #   照样被判成"没装 git" —— 后面整块直接 skip，人看到的就是"装完还说没装"。
        if not (shutil.which('git') or local_tool('git')):
            items = [{
                'key': 'git', 'state': 'bad', 'label': 'Git（记录版本的工具）',
                'detail': '这台电脑上没找到 git —— 没有它，下面所有按钮都用不了',
                'fix': 'install_git', 'fixLabel': '帮我装 Git', 'url': URL_GIT,
                'help': '装的时候一路「下一步」就行。最后一步会问要不要装 '
                        '「Git Credential Manager」——那个勾请**保持勾着**，'
                        '以后往 GitHub 上传就不用反复输密码了。装完回到这里点「再检查一次」。',
            }]
            items.append({
                'key': 'gh', 'state': 'skip', 'label': 'GitHub CLI（自动建仓库用）',
                'detail': '先把 git 装上，再考虑这个', 'fix': '', 'url': URL_GH, 'help': '',
            })
            return {'ok': True, 'path': path, 'items': items, 'ready': False,
                    'cloudReady': False, 'badCount': 1, 'todoCount': 1,
                    'next': '装 Git', 'nextFix': 'install_git',
                    'nextText': '这台电脑上还没有 git，先把它装好，别的都免谈。',
                    'help': HELP_AI, 'at': now_text()}

        gitv = run([GIT, '--version'], timeout=15)
        idn = git_identity(path)
        gh = self._gh()
        items = [{
            'key': 'git', 'state': 'ok', 'label': 'Git（记录版本的工具）',
            'detail': (gitv['out'].splitlines() or ['已安装'])[0].strip(),
        }]

        if idn['name'] and idn['email']:
            items.append({'key': 'id', 'state': 'ok', 'label': '署名（每个版本记在谁名下）',
                          'detail': '%s <%s>' % (idn['name'], idn['email'])})
        else:
            items.append({
                'key': 'id', 'state': 'warn', 'label': '署名（每个版本记在谁名下）',
                'detail': '还没填 —— 不填的话第一次「保存版本」会失败，报错叫 '
                          '"Author identity unknown"',
                'fix': 'identity', 'fixLabel': '帮我填好',
                'help': '我按你电脑的用户名填一个（只写进这个文件夹，不动全局配置）。'
                        '想改成自己的名字/邮箱，之后随时能改。',
            })

        if gh['installed']:
            # 装了但 `--version` 跑不通 ⇒ 说清是"跑不起来"，不是"没装"（别再劝人重装）
            _detail = (gh['version'] or '').strip()
            if not _detail:
                _detail = ('装了但跑不起来（%s）—— 多半被杀软/权限挡住了，'
                           '手动双击那个 exe 试试' % (gh.get('path') or 'gh.exe'))
            items.append({'key': 'gh', 'state': 'ok', 'label': 'GitHub CLI（自动建仓库用）',
                          'detail': _detail})
        else:
            items.append({
                'key': 'gh', 'state': 'warn', 'label': 'GitHub CLI（自动建仓库用）',
                'detail': '没装 —— 装了它，「备份到云端」就能**一键替你建仓库并上传**，'
                          '不用你手动去网站建',
                'fix': 'install_gh', 'fixLabel': '帮我装 gh', 'url': URL_GH,
                'help': '装完还要登录一次：回来点「登录 GitHub」，会弹一个黑色窗口，'
                        '跟着提示走完就行。',
            })

        # ★★ 这里是最关键的一处纠正（真机踩过）：
        #   以前把「gh 没登录」当成「不能推送」，于是用户明明一直能推，升级后突然被告知
        #   "没登录 GitHub"，黑窗口一开还啥都没有。**推送走的是 git 自己的凭证**，
        #   跟 gh 登录毫无关系。所以拆成两项：
        #     · push  = 能不能推送（只看 git：远端地址 + 凭证助手 / SSH 密钥）
        #     · login = 能不能"自动替你建仓库"（只看 gh，是**可选**的便利功能）
        probe_info = repo_probe(path)          # 只跑一次，下面两处都用它
        ability = push_ability(path, probe_info)
        if ability['can']:
            items.append({'key': 'push', 'state': 'ok',
                          'label': '能不能推送到 GitHub',
                          'detail': ability['why']})
        elif ability.get('need') == 'remote':
            items.append({'key': 'push', 'state': 'skip', 'label': '能不能推送到 GitHub',
                          'detail': ability['why'], 'url': ''})
        else:
            items.append({
                'key': 'push', 'state': 'warn', 'label': '能不能推送到 GitHub',
                'detail': ability['why'],
                'fix': '', 'url': URL_LOGIN,
                'help': '推送用的是 git 自己的登录（第一次会自动弹浏览器），'
                        '跟下面的 gh 没关系。',
            })

        if gh['installed'] and gh['loggedIn']:
            items.append({'key': 'login', 'state': 'ok',
                          'label': 'GitHub 自动建仓库（可选）',
                          'detail': 'gh 已登录：%s —— 「备份到云端」可以一键替你建仓库'
                                    % (gh['user'] or '（账号名没读出来）')})
        elif gh['installed']:
            # ★ 这里是 skip（不是 bad / 不是 warn）：它**不影响推送**，只是少一个便利功能。
            #   以前写成 bad + 红色，才会让人误以为"没登录就不能推了"。
            items.append({
                'key': 'login', 'state': 'skip',
                'label': 'GitHub 自动建仓库（可选，不影响推送）',
                'detail': 'gh 装了但没登录。**推送照样能用**（走 git 自己的登录）；'
                          '登录只是让「备份到云端」能替你一键建仓库，不用手动去网站建。',
                'fix': 'gh_login', 'fixLabel': '登录 gh（可选）', 'url': URL_LOGIN,
                'help': '点「登录 gh」会开一个窗口，并在里面一步步写给你看；'
                        '不想弄也完全没关系，用「我已有仓库，填地址」那条路一样能上传。',
            })
        else:
            items.append({'key': 'login', 'state': 'skip',
                          'label': 'GitHub 自动建仓库（可选）',
                          'detail': '没装 gh —— 不影响推送，只是要手动去网站建仓库',
                          'url': URL_SIGNUP, 'fix': '', 'help': ''})

        online = net_touch()
        items.append({
            'key': 'net', 'state': 'ok' if online else 'warn', 'label': '能不能连上 GitHub',
            # ★ 措辞改了（`V-422`）：这只是一次**3 秒的探测**，探不到不等于推不上去
            #   （有的网络只卡 DNS / 只卡 HTTPS 的握手，git 走代理照样通）。
            'detail': '能连上' if online else
                      '这次没探到 github.com（443）—— 只是 3 秒的探测，不代表推不上去',
            'fix': '', 'url': '',
            'help': '' if online else '本地存版本一点不受影响。「备份到云端」是**真去推**，'
                                      '推不推得动以那一步的核对结果为准（不是看这里的探测）；'
                                      '开了代理的话，把系统代理开着再点「再检查一次」。',
        })

        info = probe_info
        items.append({
            'key': 'dir', 'state': 'ok' if info else 'skip',
            'label': '这个文件夹', 'detail': path,
            'extra': ('已经是一个仓库（分支 %s）' % ((info or {}).get('branch') or '(空仓库)'))
                     if info else '还不是仓库 —— 点「开始记录」我就把它变成仓库',
        })

        todo = [i for i in items if i['state'] in ('bad', 'warn')]
        data = {'ok': True, 'path': path, 'items': items, 'ready': True,
                # ★ 能不能上云 = 能推送（git）或能自动建仓库（gh）且网络通。
                #   以前这里只认 gh 登录，导致"本来能推"的人被误判成不能 —— 已修。
                'cloudReady': bool(online and (ability['can'] or
                                               (gh['installed'] and gh['loggedIn']))),
                'pushCan': bool(ability['can']),
                'badCount': len([i for i in items if i['state'] == 'bad']),
                'todoCount': len(todo),
                'next': (todo[0]['label'] if todo else ''),
                'nextFix': (todo[0].get('fix') or '') if todo else '',
                'nextText': (todo[0]['detail'] if todo else '该有的都齐了，可以正常用。'),
                'pendingInstall': pending_install(),
                'help': HELP_AI, 'at': now_text()}
        _ENV_CACHE.update({'path': path, 'at': time.time(), 'data': data})
        return data

    def install_tool(self, params=None):
        """替用户装 git / gh（能装就装）。

        ★ 故意**不等它装完**：winget 要下载几十兆、还可能弹一次 UAC，一条 RPC 卡几分钟
          界面看着就像死了。所以这里只负责"踢一脚"，启动后台安装后立刻返回，
          界面提示「装完点再检查一次」。装不了（没有 winget）就打开官网下载页。
        """
        what = str((params or {}).get('what') or '').strip()
        if what not in ('git', 'gh'):
            return {'ok': False, 'why': '只支持装 git 或 gh：%s' % what}
        pkg = 'Git.Git' if what == 'git' else 'GitHub.cli'
        label = 'Git' if what == 'git' else 'GitHub CLI'
        url = URL_GIT if what == 'git' else URL_GH
        # ★★ 已经装好了就**一份都别再下**（真机踩过：界面上的提示是陈旧的，人一点就重下，
        #    于是"每次打开这个插件都装一次"）。这里以**磁盘上真有那个 exe** 为准，
        #    而不是信界面上那份可能过期的状态；确实想重装就传 force=1。
        found = local_tool(what) or shutil.which(what)
        if found and not str((params or {}).get('force') or ''):
            self._gh_cache = (0.0, None)                  # 让环境检查立刻改口
            return {'ok': True, 'started': False, 'already': True, 'installed': True,
                    'path': found, 'url': url,
                    'why': '%s 已经装好了（%s），不用再装。' % (label, found)}
        # ★ 注意：winget 只有"用系统安装器"那条路才需要。
        #   便携版是直接下 zip 解压，**不需要 winget** ——
        #   以前在函数开头就查 winget、没有就整条失败，等于把最靠谱的那条路也堵死了。
        winget = shutil.which('winget')
        # 已经在装了就别开第二份（人看没动静容易连点）
        # ★ 只有「这次新版本留下、而且日志文件真的在」才算"正在装"。
        #   上一版留下的记录没有 log 字段（那时输出全丢了）—— 它不该挡住新的安装，
        #   否则会出现"点了没反应、也没有进度、也不开始装"的死局（真机就是这么卡的）。
        kind = 'winget' if str((params or {}).get('mode') or '') == 'winget' else 'portable'
        cur = read_install()
        if cur and not cur.get('done') and cur.get('what') == what and cur.get('log') \
                and (cur.get('kind') or 'winget') == kind:
            age = time.time() - float(cur.get('at') or 0)
            # ★ 判断"还在装"最可靠的依据是**日志文件还有没有在长**：
            #   进程被杀 / 下载断了 / 卡死了，日志就不动了 —— 这时候必须允许人重新点，
            #   否则按钮会一直回"已经在装了"，形成死局（真机踩过）。
            try:
                quiet = time.time() - os.path.getmtime(cur['log'])
            except OSError:
                quiet = 9999
            alive = age < 900 and quiet < 25
            if os.path.exists(cur['log']) and alive:
                return {'ok': True, 'started': False, 'already': True, 'url': url,
                        'why': '%s 已经在装了，不用重复点 —— 下面就是它的实时进度。' % label}
        js, log = install_paths(what)
        try:
            open(log, 'w', encoding='utf-8').close()      # 清空，从头记
        except Exception:                                            # noqa: BLE001
            pass
        # ★ 关键改动：**把 winget 的输出写进日志文件**，界面每秒读一次尾巴。
        #   第一版是 DEVNULL，人点了之后既没进度也没日志，只能干等 —— 就是这里改的。
        #   用 cmd /c 里做重定向，就不用在 Python 侧接管道（接管道写满会卡死）。
        # ★ 默认走「便携版」：不需要管理员、进度能到百分比、装完立刻能用。
        #   真想用系统安装器就传 mode='winget'（下面那段还留着，万一 portable 通不了）。
        if str((params or {}).get('mode') or 'portable') != 'winget':
            mark_install(what, log=log, kind='portable')
            # ★ 必须起**独立进程**，不能用线程：实测线程下载到第 1 行日志后，
            #   一旦这个跑包的进程退出（关窗口、命令行跑完），daemon 线程当场被杀，
            #   下载就断在半路 —— 人看到的就是"进度卡住不动"。
            #   独立进程（DETACHED）跟界面活多久无关，关掉窗口它照样下完。
            try:
                detach = 0
                if os.name == 'nt':
                    detach = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP
                # ★★ 环境变量必须"摘干净"，否则子进程会跑错分支（真机上就卡在这）：
                #    `main()` 里只要 MOSS_PKG_PARAMS 存在（哪怕是空串）就不会去读 argv，
                #    空串 json 解析失败 → 参数为空 → 它会以为"没人给我 action" →
                #    **跑去开界面窗口**，于是安装根本没开始，界面上就一直是"正在启动"。
                #    MOSS_UI_EMBED 同理：留着它会进内嵌循环等 stdin（DEVNULL 立刻 EOF），
                #    同样不会去装。所以这两个都从子进程环境里删掉，让它老老实实看 argv。
                child_env = dict(os.environ)
                child_env.pop('MOSS_PKG_PARAMS', None)
                child_env.pop('MOSS_UI_EMBED', None)
                child_env['MOSS_INSTALL_CHILD'] = '1'
                subprocess.Popen(
                    [sys.executable, os.path.abspath(__file__),
                     'action=install_portable',
                     'arg=' + what],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, cwd=HERE, creationflags=detach,
                    env=child_env)
            except Exception as e:                                   # noqa: BLE001
                print('[github] 起安装进程失败：%s' % e, flush=True)
                mark_install(what, log=log, done=True, code=1, kind='portable')
                return {'ok': False, 'started': False, 'url': url,
                        'why': '启动下载进程失败（%s）。已经帮你打开下载页，手动装一样的效果。' % e}
            print('[github] 开始下载便携版 %s → 日志：%s' % (label, log), flush=True)
            return {'ok': True, 'started': True, 'portable': True, 'url': url, 'log': log,
                    'why': '正在下载 %s 的官方便携版（%s 左右，不需要管理员权限）。'
                           '下面会显示真实的下载百分比和日志 —— 直连下不动会自动换加速通道，'
                           '整个过程大概 1~3 分钟；装好我直接告诉你能点「登录 GitHub」了。'
                           % (label,
                              '约 15 MB' if what == 'gh' else '约 45 MB')}
        line = ('("%s" install --id %s -e --accept-source-agreements '
                '--accept-package-agreements) > "%s" 2>&1 && (echo EXIT_OK>>"%s") '
                '|| (echo EXIT_FAIL>>"%s")' % (winget, pkg, log, log, log))
        try:
            subprocess.Popen(['cmd', '/c', line], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW, cwd=DATA_DIR)
        except Exception as e:                                          # noqa: BLE001
            opened = open_url(url)
            return {'ok': False, 'started': False, 'opened': bool(opened), 'url': url,
                    'why': '启动安装失败（%s）—— 已经帮你打开下载页，手动装一下。' % e}
        mark_install(what, log=log)
        print('[github] 开始装 %s → 日志：%s' % (label, log), flush=True)
        return {'ok': True, 'started': True, 'url': url, 'log': log,
                'why': '已经在装了。可能弹一个「是否允许」的窗口，点「是」。'
                       '下面会一直显示进度和日志，装完我会直接告诉你能点「登录 GitHub」了。'}

    def install_status(self, params=None):
        """装到哪一步了 —— 界面每秒来读一次，用来画进度条和日志。

        ★ 这个方法是"别再让人干等"的核心：返回 进度百分比（抠不到就是 None）、
          一句人话（正在下载 / 正在安装 / 装好了 / 出错了）、日志尾巴、已经花了几秒。
        """
        what = str((params or {}).get('what') or '').strip()
        d = read_install()
        if not d or (what and d.get('what') != what):
            # ★ found 也要认包里那份便携版（以前只查 PATH，装好了却说"没装"）
            return {'ok': True, 'running': False, 'phase': 'none', 'text': '没有正在进行的安装',
                    'log': '', 'secs': 0,
                    'found': bool(shutil.which(what or '') or local_tool(what or ''))}
        what = d.get('what') or ''
        log = d.get('log') or ''
        text = tail_log(log)
        refresh_tools()
        found = bool(shutil.which(what) or local_tool(what))
        finished = bool(d.get('done')) or ('EXIT_OK' in text) or ('EXIT_FAIL' in text)
        secs = int(time.time() - float(d.get('at') or 0))
        phase, say = install_phase(text, found)
        pct = install_percent(text)
        # ★ 判"装完"只看**这次安装自己的证据**：日志里有 EXIT_OK 或状态文件说 done。
        #   千万不能拿「机器上有这个程序」当成功依据 —— 那会把"本来就有"和
        #   "正在装第 30%"混为一谈，进度条会提前跳到 100% 然后骗人说装好了（真机踩过）。
        if 'EXIT_FAIL' in text:
            phase, say = 'fail', '出错了'
        elif 'EXIT_OK' in text:
            phase, say, pct = 'done', '装好了', 100
        elif not finished:
            # 没写 EXIT_OK 就**绝不**说"装好了"（以前会把"机器上本来就有"当成装完）
            if phase == 'done':
                phase, say = 'run', say
        # ★ 实测：winget 的输出重定向到文件时**很可能一个字都不写**（真机就是这样）。
        #   那就自己写几行带时间戳的进度，保证"屏幕上一直在动"，人不用靠猜。
        if not (text or '').strip() and not finished:
            t0 = datetime.fromtimestamp(float(d.get('at') or time.time()))
            pkgname = 'Git' if what == 'git' else 'GitHub CLI'
            mine = ['%s  开始安装 %s' % (t0.strftime('%H:%M:%S'), pkgname),
                    '%s  下载官方便携版（不需要管理员权限）' % t0.strftime('%H:%M:%S'),
                    '%s  正在连 github.com …（下不动会自动换加速通道）'
                    % t0.strftime('%H:%M:%S')]
            for n in range(1, max(1, secs // 15) + 1):
                mine.append('%s  还在进行… 已约 %d 秒（没输出是正常的，关掉窗口安装也会继续）'
                            % ((t0 + timedelta(seconds=15 * n)).strftime('%H:%M:%S'),
                               15 * n))
            text = '\n'.join(mine)

        # ★ 一句话兜底：winget 在 Windows 上把输出重定向到文件时经常缓冲很久，
        #   甚至一个字都不吐；还有一种情况是它弹了「是否允许」的系统窗口在等人点。
        #   这两种都表现为"屏幕上什么都没发生" —— 所以过一会儿就明确提醒人去看一眼，
        #   而不是让人对着进度条干等（真机反馈的原话："只能等"）。
        hint = ''
        if not finished and secs >= 25 and not text.strip():
            hint = ('还在连网下载，暂时没有输出。要是你屏幕上弹了「是否允许」的窗口，点「是」。'
                    '再久也别干等 —— 点「打开下载页」手动装，效果完全一样。')
        elif not finished and secs >= 60:
            hint = ('有点久了。可以继续等（装完我会直接说），也可以点「打开下载页」手动装；'
                    '或者点「再检查一次」看看是不是其实已经装好了。')
        return {'ok': True, 'what': what, 'running': not finished, 'found': found,
                'phase': phase, 'text': say, 'percent': pct, 'hint': hint,
                'secs': secs,
                'log': text[-2500:], 'logPath': log,
                'label': 'Git' if what == 'git' else 'GitHub CLI'}

    def fix_identity(self, params=None):
        """替用户填一个 git 署名（只写进这个仓库，或者写全局——见函数注释）。"""
        path = self._path(params or {})
        note = ensure_identity(path, force=True)
        return {'ok': bool(git_identity(path)['name']), 'identity': git_identity(path),
                'note': note or '已经有署名了，没动'}

    def open_url(self, params=None):
        """用系统默认浏览器打开一个网址（注册 / 登录 / 下载页都走它）。"""
        return open_url(str((params or {}).get('url') or ''))

    def gh_login(self, params=None):
        """登录 GitHub —— 开一个**真的**命令行窗口让 `gh auth login` 在里面跑。

        ★ 为什么不在这里直接跑：`gh auth login --web` 要人在终端里按回车、还要等浏览器
          授权完成，藏起来跑（平时我们都是 DEVNULL）它会一直等，最后超时，
          人看到的就是"点了没反应"。
        """
        refresh_tools()
        gh = local_tool('gh') or shutil.which('gh')
        if not gh:
            return {'ok': False, 'why': '还没装 gh —— 先点「帮我装 gh」', 'url': URL_GH}
        # ★ 参数按**这个 gh 支持什么**来给：`--clipboard` / `--skip-ssh-key` 是较新版本
        #   才有的，老版本硬塞会报 "unknown flag"，窗口里就只剩一行红字。
        #   `--clipboard` 把一次性代码直接放剪贴板（人不用在窗口里找那 8 位）；
        #   `--skip-ssh-key` 关掉"要不要生成密钥"那一问（真机反馈说的就是这个"秘钥"）。
        _help = run([gh, 'auth', 'login', '--help'], timeout=10)['out'] or ''
        flags = ['--hostname', 'github.com', '--git-protocol', 'https', '--web']
        has_clip = '--clipboard' in _help
        has_skip = '--skip-ssh-key' in _help
        if has_clip:
            flags.append('--clipboard')
        if has_skip:
            flags.append('--skip-ssh-key')
        flag_text = ' '.join(flags)
        # dry=1：只把要执行的命令吐出来，不真开窗口（自检 / 排查用）
        if (params or {}).get('dry'):
            return {'ok': True, 'dry': True, 'ghPath': gh, 'flags': flags,
                    'clipboard': has_clip, 'skipSshKey': has_skip,
                    'cmd': '"%s" auth login %s' % (gh, flag_text)}

        # ★ 真机踩的两个坑：
        #   ① 便携版 gh 不在 PATH 里，窗口里敲 `gh` 会报「不是内部或外部命令」→ 一闪就没了。
        #      所以这里**用绝对路径**，并且先 cd 到它所在目录。
        #   ② 窗口里只有 gh 自己的英文提示，人不知道要干什么。所以先用 echo 把
        #      "接下来会发生什么、你要做什么"写进窗口里，再执行命令。
        steps = [
            'echo ============================================',
            'echo  登录 GitHub（这一步只是让「自动建仓库」能用）',
            'echo --------------------------------------------',
            'echo  接下来：',
            'echo   1) 屏幕上会出现一个 8 位代码，形如 ABCD-1234',
        ]
        if has_clip:
            steps += [
                'echo      ★ 这个代码我已经**替你复制到剪贴板**了（--clipboard），',
                'echo        直接 Ctrl+V 粘就完事。',
            ]
        steps += [
            'echo   2) 浏览器会自动打开；没打开就手动去 github.com/login/device',
            'echo   3) 粘上代码，点 Authorize（同意）',
            'echo   4) 看到 "Logged in as 你的名字" 就成功了',
            'echo --------------------------------------------',
        ]
        if has_skip:
            steps += [
                'echo  不会再问你要不要生成密钥（--skip-ssh-key 已经关掉那一步）——',
                'echo  推送走的是 https + Git Credential Manager，跟密钥无关。',
            ]
        steps += [
            'echo  卡住不动 / 想放弃：直接关掉这个窗口即可，推送照样能用。',
            'echo ============================================',
            'echo.',
        ]
        line = ('%s && echo. && "%s" auth login %s'
                % (' & '.join(steps), gh, flag_text))
        line += ' && echo. && echo 登录完成（按任意键关掉这个窗口） && pause'
        try:
            if os.name == 'nt':
                # /k 保留窗口，出错了也能看到红字，而不是一闪就没
                subprocess.Popen('start "GitHub 登录（照窗口里的字做）" cmd /k %s' % line,
                                 shell=True)
            else:
                subprocess.Popen(['sh', '-c', 'x-terminal-emulator -e "%s auth login %s" '
                                              '|| gnome-terminal -- "%s auth login %s"'
                                              % (gh, flag_text, gh, flag_text)])
        except Exception as e:                                          # noqa: BLE001
            return {'ok': False, 'why': '打不开命令行窗口：%s' % e, 'url': URL_LOGIN}
        self._gh_cache = (0.0, None)
        return {'ok': True, 'window': True, 'ghPath': gh, 'clipboard': has_clip,
                'help': '窗口里我把步骤写在最上面了：屏幕上给一个 8 位代码'
                        + ('（已经帮你复制到剪贴板）' if has_clip else '') +
                        ' → 浏览器自动打开 → 粘代码点同意 → 看到 "Logged in as 你" 就成了。'
                        '窗口不会一闪就没（出错了会停在窗口里给你看）。'
                        '实在不想弄也没关系：推送不受影响。'}

    # ---- 清掉"我们自己造出来的临时垃圾"
    #: 只认这几个名字（白名单），绝不按通配符删 —— 免得手一抖把仓库里的东西带走
    OWN_JUNK = ('_how.py', '_how.txt', '_probe.py', '_probe.txt', '_tmp_probe.py')

    def tidy(self, params=None):
        """删掉写包时落在包目录里的临时探针文件（`_how.py` 这类）。

        ★ 为什么要这么个东西：我（AI）写包时常常要"看一眼帮助的开头"，
          因为 run_moss 只回末尾，于是生成一个 `_how.py` 去存全文 —— 用完该删，
          但我没有删文件的工具（宿主也不许用脚本删目录）。所以留一个**受限的**
          清理入口：只删白名单里的名字，只删包自己这一层，别的一概不碰。
        """
        p = self._path(params or {})
        here = os.path.dirname(os.path.abspath(__file__))
        gone, kept = [], []
        for name in self.OWN_JUNK:
            full = os.path.join(here, name)
            if not os.path.isfile(full):
                continue
            try:
                os.remove(full)
                gone.append(name)
            except OSError as e:
                kept.append('%s（%s）' % (name, e))
        print('[github] 清理临时文件：删了 %s；没删成 %s'
              % (gone or '无', kept or '无'), flush=True)
        return {'ok': not kept, 'removed': gone, 'failed': kept,
                'dir': here, 'path': p, 'at': now_text()}

    # ---- 路径
    def browse(self, params=None):
        p = self._path(params)
        dirs = []
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if not e.is_dir():
                            continue
                    except OSError:
                        continue
                    dirs.append({'name': e.name, 'path': e.path,
                                 'hidden': e.name.startswith('.'),
                                 'repo': os.path.exists(os.path.join(e.path, '.git'))})
        except OSError as e:
            return {'ok': False, 'path': p, 'why': '这个目录读不了：%s' % e, 'dirs': []}
        dirs.sort(key=lambda d: (d['hidden'], d['name'].lower()))
        parent = os.path.dirname(p.rstrip('\\/')) or p
        roots = []
        if os.name == 'nt':
            for d in list_disks():
                roots.append({'name': d['root'], 'path': d['root'], 'ready': d['ready']})
        else:
            roots.append({'name': '/', 'path': '/', 'ready': True})
        return {'ok': True, 'path': p, 'parent': parent, 'dirs': dirs[:300],
                'roots': roots, 'isRepo': os.path.exists(os.path.join(p, '.git'))}

    def set_path(self, params=None):
        raw = str((params or {}).get('path') or '').strip().strip('"')
        if not raw:
            return {'ok': False, 'why': '没给路径'}
        if not os.path.isdir(raw):
            return {'ok': False, 'why': '这个目录不存在（或者读不到）：%s' % raw}
        p = os.path.abspath(raw)
        remember(p)
        print('[github] 当前仓库目录 → %s' % p, flush=True)
        got = self.snapshot({'path': p})
        got['ok'] = True
        return got

    def forget_path(self, params=None):
        """从「最近用过」里去掉一条；**path 给空 = 清空整个列表**（界面上的「清空」）。

        ★ 只动我们自己记的那份列表（`store.json`），**不碰任何目录里的东西**。
        """
        raw = str((params or {}).get('path') or '')
        if not raw.strip():
            d = load_store()
            d['recent'], d['last'] = [], ''
            save_store(d)
            return {'ok': True, 'cleared': True, 'recent': recent_payload()}
        d = load_store()
        key = os.path.normcase(os.path.abspath(raw))
        d['recent'] = [x for x in d['recent'] if os.path.normcase(os.path.abspath(x)) != key]
        if key and os.path.normcase(os.path.abspath(d.get('last') or '')) == key:
            d['last'] = d['recent'][0] if d['recent'] else ''
        save_store(d)
        return {'ok': True, 'recent': recent_payload()}

    # ---- 干活
    def run_action(self, params=None):
        p = params or {}
        name = str(p.get('name') or '').strip()
        arg = str(p.get('arg') or '')
        spec = ACTIONS.get(name)
        if not spec:
            return {'ok': False, 'why': '没有这个动作：%s' % name, 'cmd': '', 'out': ''}
        path = self._path(p)
        cmd_text = spec['cmd']
        if spec.get('needArg') and not arg.strip():
            return {'ok': False, 'why': '这个动作要填：%s' % spec['needArg'],
                    'cmd': cmd_text, 'out': '', 'needArg': spec['needArg']}
        if name == 'untrack':
            return self.untrack({'path': path, 'arg': arg})
        if name == 'shield':
            pats = [x.strip() for x in re.split(r'[,;]', str(arg or '')) if x.strip()]
            return self.shield({'path': path, 'patterns': pats})
        if name == 'gitlog':
            # 只是读日志文件：跟"是不是仓库"无关，也不用跑任何命令
            got = self.sync_log({'n': 80})
            print('[github] %s（最近 %d 行）' % (SYNC_LOG, len(got['lines'])), flush=True)
            return {'ok': True, 'action': name, 'label': spec['label'], 'cmd': cmd_text,
                    'out': got['out'], 'code': 0, 'ms': 0, 'path': path,
                    'logPath': SYNC_LOG, 'lines': got['lines']}
        if name not in NO_REPO_NEEDED and not repo_info(path):
            return {'ok': False, 'cmd': cmd_text, 'out': '',
                    'why': '%s 不是一个 git 仓库 —— 先在「路径」里选一个仓库目录（或者用它 clone 一个）' % path}
        if spec.get('fake'):
            out = _fake_out(name, path)
            print('[github] %s：%d 行' % (name, len(out.splitlines())), flush=True)
            return {'ok': True, 'action': name, 'label': spec['label'], 'cmd': cmd_text,
                    'out': out, 'code': 0, 'ms': 0, 'path': path}
        ctx = repo_info(path) or {}
        argv = spec['argv'](ctx, arg.strip())
        if not any(argv):
            return {'ok': False, 'why': '缺可执行文件（gh 没装？）', 'cmd': cmd_text, 'out': ''}
        got = _exec(argv, cwd=path, timeout=spec.get('timeout', 60), label=spec['label'])
        got.update({'action': name, 'label': spec['label'], 'path': path,
                    'danger': bool(spec.get('danger'))})
        if not got['ok']:
            got['why'] = (got['out'] or '').strip().splitlines()[:1]
            got['why'] = got['why'][0] if got['why'] else '退出码 %s' % got['code']
        print('[github] %s → %s（%d ms，退出码 %s）'
              % (spec['label'], got['cmd'], got['ms'], got['code']), flush=True)
        return got

    def file_op(self, params=None):
        p = params or {}
        path = self._path(p)
        rel = str(p.get('file') or '').replace('/', os.sep)
        op = str(p.get('op') or '')
        if not rel or os.path.isabs(rel) or '..' in rel.split(os.sep):
            return {'ok': False, 'why': '只能操作仓库里的相对路径：%s' % rel}
        table = {
            'add': ['git', 'add', '--', rel],
            'unstage': ['git', 'restore', '--staged', '--', rel],
            'discard': ['git', 'restore', '--', rel],
            'diff': ['git', 'diff', '--', rel],
        }
        argv = table.get(op)
        if not argv:
            return {'ok': False, 'why': '没有这个操作：%s' % op}
        got = run(argv, cwd=path, timeout=40)
        got.update({'action': 'file_' + op, 'file': rel, 'path': path,
                    'label': {'add': '加入这次保存', 'unstage': '不加入这次保存',
                              'discard': '丢弃改动', 'diff': '看改动'}[op]})
        if not got['ok'] and op == 'unstage' and got['code'] != 0:
            got['why'] = (got['out'] or '').splitlines()[:1]
        print('[github] 文件操作 %s：%s' % (op, got['cmd']), flush=True)
        return got

    # ---- 一串步骤的公共件（界面要看到「每一步的等价命令」）
    def _step(self, cwd, argv, label, timeout=180):
        got = _exec(argv, cwd=cwd, timeout=timeout, label=label)
        got['label'] = label
        print('[github] %s → %s（%d ms，退出码 %s）'
              % (label, got['cmd'], got['ms'], got['code']), flush=True)
        return got

    def _upstream_verified(self, root, upstream=""):
        """本地 HEAD 和上游**是不是同一个提交** —— 直接用 git 的事实回答。

        ★ 2026-10-21 的假失败就是靠这个止住的：`git fetch` 超时 / 被断，
          推送其实**已经成功**（reflog 里一条 `update by push`），可界面照着
          "有一条步骤失败"报了"提交失败，可能是网络问题"。
          现在成败以"两端是不是同一个提交"为准，步骤日志只当过程。
        回 `{same, head, up, msg}`；说不清（没有上游 / 命令失败）时 `same=None`。
        """
        ref = str(upstream or "").strip() or "@{u}"
        h = git(root, "rev-parse", "--short", "HEAD", timeout=10)
        u = git(root, "rev-parse", "--short", ref, timeout=10)
        head = ((h.get("out") or "").strip().splitlines() or [""])[0].strip()
        up = ((u.get("out") or "").strip().splitlines() or [""])[0].strip()
        if not (h.get("ok") and u.get("ok") and head and up):
            return {"same": None, "head": head, "up": up,
                    "msg": "核对不上（可能还没有上游分支）：%s"
                           % ((u.get("out") or h.get("out") or "git 没答话").strip()[:200])}
        same = (head == up)
        return {"same": same, "head": head, "up": up,
                "msg": ("本地和远端是同一个提交 %s —— 推上去了" % head) if same
                       else ("本地 %s，远端 %s —— 还没对齐" % (head, up))}

    def _finish(self, path, steps):
        """把一串步骤汇总成一份给界面看的结果（ok / 失败原因 / 全部等价命令）。

        ★ 标了 `soft: True` 的步骤（现在只有"拉取远端信息"）**不参与判定成功**：
          它只是"问问远端现在什么样"，问不着不代表活没干成（`V-422`）。
        """
        bad = [s for s in steps if not s.get("ok") and not s.get("soft")]
        why = ''
        if bad:
            first = bad[0]
            lines = (first.get('out') or '').splitlines() or ['没跑成']
            why = first.get('why') or lines[0]
        # 整体成了、只是"问远端"那一步没问着 ⇒ 别让界面显示一个吓人的 ✗
        if not bad:
            for s in steps:
                if s.get("soft") and not s.get("ok"):
                    s["softFail"] = True
                    s["ok"] = True
                    s["label"] = s.get("label", "") + "（这次没问着，不影响下面的推送）"
        return {
            'ok': not bad and bool(steps), 'steps': steps, 'path': path,
            'why': why, 'ms': sum(int(s.get('ms') or 0) for s in steps),
            'cmd': '  &&  '.join(s['cmd'] for s in steps
                                 if s.get('cmd') and not s['cmd'].startswith('（')),
            'repo': repo_info(self._path({'path': path})), 'at': now_text(),
        }

    # ---- 时间线 / 提交详情（界面主视图）
    def timeline(self, params=None):
        """提交时间线 + 分支 + 标签，一次给全。"""
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'path': path,
                    'commits': [], 'branches': [], 'remoteBranches': [], 'tags': []}
        root = info['root']
        try:
            limit = int(p.get('limit') or 40)
        except (TypeError, ValueError):
            limit = 40
        limit = max(5, min(300, limit))
        rev = str(p.get('rev') or '').strip() or 'HEAD'
        rows, _ = git_log_rows(root, limit + 1, rev)
        more = len(rows) > limit
        rows = rows[:limit]
        pushed, capped = _upstream_hashes(root, info['upstream'])
        for r in rows:
            r['pushed'] = bool(pushed) and r['hash'] in pushed
        local, remote = branch_rows(root)
        # ★ 「V-384」这种版本号：界面上要一个"每保存一次就 +1"的整数，用真实提交数来当。
        #   本地总共多少个提交 / 云端追得上多少个 —— 两个数一减就是"待备份几个版本"。
        total = _rev_count(root, 'HEAD')
        up_total = _rev_count(root, info['upstream']) if info['upstream'] else 0
        for i, r in enumerate(rows):
            r['ver'] = ('V-%d' % (total - i)) if total else ''
        return {'ok': True, 'path': path, 'root': root, 'head': info['branch'],
                'detached': info['detached'], 'upstream': info['upstream'],
                'ahead': info['ahead'], 'behind': info['behind'],
                'commits': rows, 'more': more, 'branches': local, 'remoteBranches': remote,
                'tags': tag_rows(root), 'pushedKnown': bool(pushed), 'capped': capped,
                'total': total, 'upstreamTotal': up_total,
                'ver': ('V-%d' % total) if total else '',
                'cloudVer': ('V-%d' % up_total) if up_total else '',
                'cmd': 'git log --oneline --graph --decorate -n %d' % limit,
                'at': now_text()}

    def cloud_versions(self, params=None):
        """GitHub 上（远端跟踪分支）有哪些版本 —— 界面上「云端版本列表」靠它。

        ★ 只读本地那份远端跟踪分支的记录，**不联网**（想刷新就调 `sync` 里的 fetch）。
          这样点开列表是瞬间出来的，也不会因为网络慢把界面卡住。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'commits': []}
        root = info['root']
        names = [n.strip() for n in git(root, 'remote')['out'].splitlines() if n.strip()]
        if not names:
            return {'ok': False, 'why': '这个仓库还没连任何远端（先去「备到 GitHub」）',
                    'commits': [], 'path': path}
        # 目标：跟踪分支；没有就猜 remote/当前分支
        target = info['upstream']
        if not target:
            target = '%s/%s' % (names[0], info['branch'])
        if not git(root, 'rev-parse', '--verify', '--quiet', target + '^{commit}')['ok']:
            return {'ok': False, 'path': path, 'commits': [], 'ref': target,
                    'why': '本地还没有 %s 的记录 —— 点「获取最新版」或「扫描变动」拉一次远端信息' % target}
        try:
            limit = int(p.get('limit') or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = max(5, min(200, limit))
        rows, _ = git_log_rows(root, limit + 1, target)
        more = len(rows) > limit
        rows = rows[:limit]
        total = _rev_count(root, target)
        for i, r in enumerate(rows):
            r['ver'] = ('V-%d' % (total - i)) if total else ''
            r['pushed'] = True          # 它本来就在云端
        # 云端有、本地没有的（behind）：标出来，界面上一眼看出"这些还没拿下来"
        local_only = set()
        local_heads = git(root, 'rev-list', 'HEAD', timeout=30)['out'].splitlines()
        local_hashes = set(x.strip() for x in local_heads if x.strip())
        for r in rows:
            r['inLocal'] = r['hash'] in local_hashes
            if not r['inLocal']:
                local_only.add(r['hash'])
        return {'ok': True, 'path': path, 'root': root, 'ref': target,
                'upstream': info['upstream'], 'branch': info['branch'],
                'commits': rows, 'more': more, 'total': total,
                'ver': ('V-%d' % total) if total else '',
                'missing': len(local_only), 'behind': info['behind'],
                'cmd': 'git log --oneline -n %d %s' % (limit, target),
                'at': now_text()}

    def show_commit(self, params=None):
        """一条提交的详情：谁写的、改了哪些文件、补丁正文。"""
        p = params or {}
        ref = str(p.get('hash') or p.get('ref') or '').strip()
        if not ref:
            return {'ok': False, 'why': '没给提交（hash）', 'out': ''}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'out': ''}
        root = info['root']
        fmt = UNIT.join(['%H', '%h', '%an', '%ae', '%ad', '%ar', '%D', '%s'])
        meta = git(root, 'show', '-s', '--date=format:%Y-%m-%d %H:%M',
                   '--pretty=format:' + fmt, ref, timeout=25)
        if not meta['ok']:
            lines = (meta['out'] or '').splitlines() or ['看不到这条提交']
            return {'ok': False, 'why': lines[0], 'cmd': 'git show %s' % ref,
                    'out': meta['out']}
        h, short, an, ae, ad, ar, deco, subj = (_rows(meta['out'], 8) or [[''] * 8])[0]
        body = git(root, 'show', '-s', '--format=%b', ref, timeout=20)
        num = git(root, 'show', '--numstat', '--format=', ref, timeout=40)
        files = []
        for line in num['out'].splitlines():
            bits = line.split('\t')
            if len(bits) >= 3:
                files.append({'add': bits[0], 'del': bits[1], 'path': bits[2]})
        patch = git(root, 'show', '--stat', '--patch', '--format=', ref, timeout=60)
        return {'ok': True, 'hash': h, 'short': short, 'author': an, 'email': ae,
                'when': ad, 'rel': ar, 'subject': subj,
                'refs': [d.strip() for d in deco.split(',') if d.strip()],
                'body': (body['out'] or '').strip()[:2000], 'files': files,
                'fileCount': len(files), 'out': (patch['out'] or '')[:30000],
                'cmd': 'git show %s' % short, 'path': path, 'root': root}

    # ---- 切分支 / 同步 / 提交
    def switch_branch(self, params=None):
        """切分支（可选：先自动把改动收进 stash）。"""
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        name = str(p.get('branch') or '').strip()
        if not name:
            return {'ok': False, 'why': '没给分支名', 'steps': []}
        create, stash = bool(p.get('create')), bool(p.get('stash'))
        base = str(p.get('base') or '').strip()
        if info['dirty'] and not stash:
            return {'ok': False, 'steps': [], 'cmd': 'git checkout %s' % name,
                    'why': '工作区还有 %d 个没提交的改动，git 会拦住这次切换 —— '
                           '先提交，或者勾上「帮我先收起来（stash）」' % info['changeCount']}
        steps = []
        if stash and info['dirty']:
            steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                           'moss 切换分支前自动收起 ' + now_text()],
                                    '把当前改动收进 stash', 60))
        argv = (['git', 'checkout', '-b', name] + ([base] if base else [])) if create \
            else ['git', 'checkout', name]
        steps.append(self._step(root, argv, '切到分支 %s' % name, 90))
        return self._finish(path, steps)

    def sync(self, params=None):
        """一键同步：fetch →（落后就）pull --ff-only →（领先就）push。

        ★ 2026-10-21 修的**假失败**：`fetch` 只是"问问远端现在什么样"，它超时 / 被断
          **不代表推不上去**。以前 fetch 一红，整份结果就报失败（界面上就是
          "提交失败，可能是网络问题"），可实际上紧接着的 `git push` 已经推上去了
          —— 真事：15:13:58 的提交，`origin/main` 的 reflog 里 15:14:39 一条
          `update by push`，界面却说失败。
          现在：① `fetch` 标成 **soft**（失败只当提示，不判定整体失败）；
                ② push / pull 之后**再问 git 一次**：`HEAD` 和上游是不是同一个提交；
                ③ 只要事实对得上，就报成功，并把"没问着"的原话留在步骤里。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        fetch = self._step(root, ['git', 'fetch', '--all', '--prune'], '① 拉取远端信息', 180)
        fetch['soft'] = True
        steps = [fetch]
        info = repo_info(path) or info
        if info['behind'] and info['dirty']:
            steps.append({'ok': False, 'cmd': '(跳过) git pull --ff-only', 'ms': 0,
                          'label': '② 合并远端提交', 'out': '',
                          'why': '本地还有没提交的改动，先提交或收起再拉（免得合到一半冲突）'})
            return self._finish(path, steps)
        if info['behind']:
            steps.append(self._step(root, ['git', 'pull', '--ff-only'],
                                    '② 把远端新提交合进来', 240))
            info = repo_info(path) or info
        if info['ahead'] or not info['upstream']:
            argv = ['git', 'push'] if info['upstream'] else \
                ['git', 'push', '-u', 'origin', info['branch'] or 'HEAD']
            steps.append(self._step(root, argv, '③ 推送到 GitHub', 240))
            # ★ 只信事实：推完之后 `HEAD` 和上游是不是同一个提交
            info = repo_info(path) or info
            ver = self._upstream_verified(root, info.get('upstream') or '')
            steps.append({'ok': bool(ver.get('same') is not False), 'ms': 0,
                          'cmd': '(核对) git rev-parse HEAD @{u}',
                          'label': '④ 核对：远端和本地是不是同一个提交',
                          'out': ver.get('msg') or '',
                          'why': '' if ver.get('same') else (ver.get('msg') or '')})
        if len(steps) == 1 and not fetch['ok']:
            # ★ 探针真跑出来的一条：fetch 报 `Recv failure: Connection was reset`，
            #   本地又没有要推的东西 ⇒ 以前这里照样报 **成功**，理由写"本地和远端已经一致"。
            #   可我们**根本没问到云端**（ahead/behind 是拿旧记录算的），说"一致"是瞎猜。
            #   没问到就说没问到 —— 这也是"黑盒"的一种：报了成功，人下次才发现云端是旧的。
            res = self._finish(path, steps)
            first = (fetch.get('out') or '').splitlines()[:1]
            res['ok'] = False
            res['netFail'] = True
            res['why'] = ('没连上 GitHub：%s　（本地没有要推的东西，但云端现在什么样'
                          '也确认不了 —— 网络好了再点一次）'
                          % (first[0] if first else '拉取远端信息失败'))
            return res
        if len(steps) == 1 and steps[0]['ok'] and not info['ahead'] and not info['behind']:
            steps.append({'ok': True, 'cmd': '（无事可做）', 'ms': 0, 'label': '② / ③',
                          'out': '本地和远端已经一致：没有要拉的，也没有要推的。'})
        return self._finish(path, steps)

    def pull_overwrite(self, params=None):
        """从 GitHub 覆盖本地：fetch →（有改动先 stash 备份）→ reset --hard 上游。

        ★ 这就是界面上「从 GitHub 覆盖下载」那把大按钮。它**故意**会丢掉本地没提交的
          改动，所以动手前先把改动 stash 备份一份（「取出收起的改动」能捞回来）。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        if info['detached']:
            return {'ok': False, 'steps': [],
                    'why': '现在不在任何分支上（游离头），先切回一条分支再「覆盖下载」'}
        steps = [self._step(root, ['git', 'fetch', '--all', '--prune'], '① 拉取远端信息', 180)]
        info = repo_info(path) or info
        target = info['upstream']
        if not target:
            names = [n.strip() for n in git(root, 'remote')['out'].splitlines() if n.strip()]
            if not names:
                steps.append({'ok': False, 'ms': 0, 'out': '', 'cmd': '(没有远端)',
                              'label': '找要覆盖成的目标',
                              'why': '这个仓库没连任何远端 —— 先去「镜像…」里在 GitHub 建一个'})
                return self._finish(path, steps)
            target = '%s/%s' % (names[0], info['branch'])
        if not git(root, 'rev-parse', '--verify', '--quiet', target + '^{commit}')['ok']:
            steps.append({'ok': False, 'ms': 0, 'out': '',
                          'cmd': 'git rev-parse --verify %s^{commit}' % target,
                          'label': '确认远端有这条分支',
                          'why': '远端没有 %s 这条分支，没东西可以覆盖下载' % target})
            return self._finish(path, steps)
        if info['dirty']:
            steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                           'moss 覆盖下载前自动备份 ' + now_text()],
                                    '先把当前 %d 个改动备份到 stash' % info['changeCount'], 60))
        steps.append(self._step(root, ['git', 'reset', '--hard', target],
                                '把本地拉成和 %s 一模一样' % target, 120))
        return self._finish(path, steps)

    def commit_all(self, params=None):
        """把改动打包提交，可选顺手推上去。

        参数：
          message   提交**标题**（必填）—— 就是 GitHub 上那一行标题
          body      **详细说明**（可选，空就不写）—— 标题下面那段
          staged    True = 只提交「已经暂存」的那部分，不动其余改动
          push      True = 提交完顺手推上去
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        msg = str(p.get('message') or p.get('arg') or '').strip()
        if not msg:
            return {'ok': False, 'why': '提交标题不能空着（写一句你能看懂的话）', 'steps': []}
        # ★ 标题 + 说明 = `git commit -m 标题 -m 说明`（git 会把第二段当正文，
        #   GitHub 上就是标题下面那段说明）。
        body = str(p.get('body') or '').strip()
        commit_argv = ['git', 'commit', '-m', msg] + (['-m', body] if body else [])
        # ★ 「这次要保存哪几个文件」：界面上的勾。不传 = 全部。
        #   （这是给"我这次只想存这几个"用的，普通人一把全存就够。）
        only = p.get('files')
        if isinstance(only, str):
            only = [x for x in only.split('|') if x.strip()]
        picks = []
        if isinstance(only, list) and only:
            for raw in only:
                rel = str(raw).replace('/', os.sep)
                if not rel or os.path.isabs(rel) or '..' in rel.split(os.sep):
                    return {'ok': False, 'steps': [],
                            'why': '只能保存仓库里的相对路径：%s' % raw}
                picks.append(rel)
        staged_only = bool(p.get('staged'))
        steps = []
        # ★ 先保证有署名：没有的话 `git commit` 会报 "Author identity unknown"，
        #   人看到这句只会以为软件坏了。这里替它填好，并在步骤里说一声。
        idnote = ensure_identity(root)
        if idnote:
            steps.append({'ok': True, 'ms': 0, 'cmd': 'git config user.name / user.email',
                          'label': '⓪ ' + idnote, 'out': ''})
        if staged_only:
            staged = [c for c in (info.get('changes') or []) if c.get('flag') == 'staged']
            if not staged:
                return {'ok': False, 'steps': [], 'cmd': 'git commit -m "标题"',
                        'why': '还没有文件被「加入这次保存」—— 在「文件改动」页勾上要存的文件，'
                               '或者直接用「保存并上传」（默认全存）'}
            steps.append(self._step(root, commit_argv,
                                    '② 在本地存一个版本（%d 个文件）' % len(staged), 90))
        elif picks:
            steps.append(self._step(root, ['git', 'add', '--'] + picks,
                                    '① 把选中的 %d 个文件收进来' % len(picks), 60))
            # ★ 提交时带上这串路径：**只存这几个**。不然万一暂存区里还躺着别的文件
            #   （比如上一次操作留下的），`git commit` 会把它一起存进去 ——
            #   那就违背了"我只勾了这几个"。
            steps.append(self._step(root, commit_argv + ['--'] + picks,
                                    '② 在本地存一个版本（只存选中的）', 90))
        elif info['dirty']:
            steps.append(self._step(root, ['git', 'add', '-A'], '① 把改动收进来', 60))
            steps.append(self._step(root, commit_argv, '② 在本地存一个版本', 90))
        else:
            steps.append({'ok': True, 'cmd': '（没有新改动，不用提交）', 'ms': 0,
                          'label': '① ②', 'out': '本地已经是最新的了。'})
        if p.get('push') and all(s['ok'] for s in steps):
            info = repo_info(path) or info
            argv = ['git', 'push'] if info['upstream'] else \
                ['git', 'push', '-u', 'origin', info['branch'] or 'HEAD']
            steps.append(self._step(root, argv, '③ 上传到 GitHub', 240))
        return self._finish(path, steps)

    # ---- 从远端 / 历史恢复
    def restore(self, params=None):
        """把某条提交恢复出来。

        mode='branch'   → 检出成一条新分支（**默认，不动主线，安全**）
        mode='worktree' → 直接把工作区拉回那条提交（reset --hard，有改动会先自动 stash 备份）
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        ref = str(p.get('hash') or p.get('ref') or '').strip()
        if not ref:
            return {'ok': False, 'why': '没给要恢复的提交', 'steps': []}
        mode = str(p.get('mode') or 'branch')
        steps = []
        if not git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')['ok']:
            steps.append(self._step(root, ['git', 'fetch', '--all', '--prune'],
                                    '本地没有这条提交 —— 先去远端取一下', 180))
        if not git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')['ok']:
            # ★ 取过之后还是没有 ⇒ 到此为止。别再往下走：`git rev-parse` 失败时
            #   它的输出是 "fatal: Needed a single revision" 这种话，
            #   拿它去拼分支名会把一句报错写进分支名里（探针真跑出来的）。
            steps.append({'ok': False, 'ms': 0, 'out': '',
                          'cmd': 'git rev-parse --verify %s^{commit}' % ref,
                          'label': '确认这条提交在不在',
                          'why': '本地和远端都没有这条提交：%s' % ref})
            return self._finish(path, steps)
        heads = git(root, 'rev-parse', '--short', ref)['out'].splitlines()
        short = re.sub(r'[^0-9a-zA-Z_.-]', '', heads[0].strip() if heads else '') or ref[:7]
        if mode == 'worktree':
            if info['dirty']:
                steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                               'moss 恢复 %s 前自动备份 ' % short + now_text()],
                                        '先把当前 %d 个改动备份到 stash' % info['changeCount'], 60))
            steps.append(self._step(root, ['git', 'reset', '--hard', ref],
                                    '把工作区拉回 %s' % short, 90))
        else:
            # ★ 分支名要保证唯一：同名分支已经存在时 `checkout -b` 会直接失败，
            #   而人可能一分钟里连点几下「恢复」（`V-*` 里没写，这是探针真跑出来的）。
            have = set(git(root, 'branch', '--format=%(refname:short)')['out'].splitlines())
            stamp = datetime.now().strftime('%m%d-%H%M%S')
            name = 'restore-%s-%s' % (short, stamp)
            n = 2
            while name.strip() in have:
                name = 'restore-%s-%s-%d' % (short, stamp, n)
                n += 1
            steps.append(self._step(root, ['git', 'checkout', '-b', name, ref],
                                    '检出成新分支 %s（主线不受影响）' % name, 90))
        return self._finish(path, steps)

    # ---- 让某个版本「消失」
    def delete_commit(self, params=None):
        """让某一条提交消失。两种做法，后果完全不同：

          mode='revert'（默认，安全）
              在历史末尾**追加**一条「撤销某版本」的提交：坏代码立刻不生效，
              两个版本在 GitHub 上仍然看得见（谁都能查到"哪一版被撤销了"）。
          mode='purge'（危险，真·抹掉）
              把这条从历史里**抠掉**，它后面的版本全部重写一遍 ⇒ 版本号全变，
              已经推上云端的必须强推覆盖（`--force-with-lease`）。
              动手前先打一个 `moss-undo-<短哈希>-<时间>` 标签，反悔时能精确回到原样。

        ★ 说明白（界面也会照这句写）：GitHub 上被强推掉的提交不会立刻消失，
          一串哈希还能直接访问，直到它被回收；**如果那一版里泄了密钥/密码，
          真正有效的是「换掉那把密钥」**，删历史只能算补救。

        参数：hash 必填；mode = revert / purge；push = 要不要顺手同步到云端（默认要）。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        ref = str(p.get('hash') or p.get('ref') or '').strip()
        if not ref:
            return {'ok': False, 'why': '没给要删的版本（hash）', 'steps': []}
        got = git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
        if not got['ok']:
            return {'ok': False, 'steps': [], 'cmd': 'git rev-parse %s^{commit}' % ref,
                    'why': '这个仓库里找不到这条版本：%s' % ref}
        sha = ((got['out'] or '').strip().splitlines() or [''])[0].strip()
        short = sha[:7]
        if info['detached']:
            return {'ok': False, 'steps': [],
                    'why': '现在不在任何一条线上（游离状态）—— 先切回一条分支再来删'}
        branch = info['branch'] or ''
        # ★ 只能删「你现在这条线上」的版本：别的分支上的提交在这儿删不掉，
        #   硬删也只会让那条线看起来坏掉（所以直接拦住，让人先换过去）。
        if git(root, 'merge-base', '--is-ancestor', sha, 'HEAD')['code'] != 0:
            return {'ok': False, 'steps': [],
                    'why': '%s 不在当前这条线（%s）上 —— 先换到它所在的分支，或者去「分支」里处理那条线'
                           % (short, branch)}
        upstream = info['upstream']
        was_pushed = bool(upstream) and \
            git(root, 'merge-base', '--is-ancestor', sha, upstream)['code'] == 0
        mode = str(p.get('mode') or 'revert')
        push = p.get('push')
        push = True if push is None else bool(push)
        steps = []
        dirty = info['dirty'] and info['changeCount']

        if mode == 'revert':
            ensure_identity(root)          # revert 也会产生一条提交，同样要先有署名
            # 合并提交必须指定「按哪一条主线撤销」，否则 git 直接拒绝
            par = (git(root, 'rev-list', '--parents', '-n', '1', sha)['out'] or '').split()
            argv = ['git', 'revert', '--no-edit'] + (['-m', '1'] if len(par) > 2 else []) + [sha]
            if dirty:
                steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                               'moss 撤销版本前备份 ' + now_text()],
                                        '先把当前 %d 个改动收起来备份' % info['changeCount'], 60))
            rev = self._step(root, argv, '追加一条「撤销 %s」的版本' % short, 150)
            steps.append(rev)
            if not rev['ok']:
                # ★ 测试跑出来的：`git revert` 会冲突（后面的版本动过同一段代码）。
                #   冲突留着不处理，仓库就停在"有未合并文件"的半截状态 ——
                #   界面上看起来到处都怪，人也不知道怎么退。所以这里立刻中止、退回原样。
                steps.append(self._step(root, ['git', 'revert', '--abort'],
                                        '这次撤销撞上冲突，先退回去恢复原样', 120))
                if dirty:
                    steps.append(self._step(root, ['git', 'stash', 'pop'],
                                            '把刚才备份的改动放回来', 60))
                res = self._finish(path, steps)
                res['note'] = ('这条版本跟后面的版本改到了同一段代码，自动撤销撞上冲突 —— '
                               '已经原样退回（什么都没变）。这种就只剩「彻底抹掉」一条路，'
                               '或者先手动把冲突改好。')
                return res
            if dirty and rev['ok']:
                steps.append(self._step(root, ['git', 'stash', 'pop'],
                                        '把刚才备份的改动放回来', 60))
            if push and upstream and rev['ok']:
                steps.append(self._step(root, ['git', 'push'],
                                        '把这条撤销同步到 GitHub', 240))
            res = self._finish(path, steps)
            res['undoCmd'] = ''
            res['note'] = ('已经追加了一条撤销：坏代码现在不生效了，'
                           '历史里两个版本都还查得到。')
            return res

        if mode != 'purge':
            return {'ok': False, 'steps': [], 'why': '不认识的删除方式（revert / purge）：%s' % mode}

        # 最早那条没得"抠"：它没有上一版可接
        if not git(root, 'rev-parse', '--verify', '--quiet', sha + '^')['ok']:
            return {'ok': False, 'steps': [],
                    'why': '%s 是这个仓库最早的版本，删掉它等于把整段历史抹了 —— '
                           '这种情况另建一个仓库、把要留的文件搬过去更稳' % short}

        # 别的分支上也含着它 ⇒ 删完那些线一样会变，先说明白
        others = []
        for b in branch_rows(root)[0]:
            nm = str(b.get('name') or '')
            if nm and not b.get('current') and \
                    git(root, 'merge-base', '--is-ancestor', sha, nm)['code'] == 0:
                others.append(nm)

        if dirty:
            steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                           'moss 抹掉版本前备份 ' + now_text()],
                                    '先把当前 %d 个改动收起来备份' % info['changeCount'], 60))
        # ① 留一条退路：标签指向**改写前**的样子（标签不占工作区，也不影响别人）
        have = set(git(root, 'tag', '--list')['out'].splitlines())
        stamp = datetime.now().strftime('%m%d-%H%M%S')
        tag = 'moss-undo-%s-%s' % (short, stamp)
        n = 2
        while tag.strip() in have:
            tag = 'moss-undo-%s-%s-%d' % (short, stamp, n)
            n += 1
        steps.append(self._step(root, ['git', 'tag', tag, 'HEAD'],
                                '先记一下现在的样子（标签 %s，反悔用）' % tag, 30))
        head_sha = (git(root, 'rev-parse', 'HEAD')['out'] or '').strip()
        if sha == head_sha:
            drop = self._step(root, ['git', 'reset', '--hard', sha + '^'],
                              '把最新那条拿掉（回到它的上一版）', 120)
        else:
            drop = self._step(root, ['git', 'rebase', '--onto', sha + '^', sha],
                              '把这条从历史里抠掉，后面的版本重新接上', 240)
        steps.append(drop)
        if not drop['ok']:
            # ★ 改写中途撞上冲突时，**必须**中止：否则仓库停在 rebase 中间状态，
            #   界面上看起来"所有版本都怪怪的"，人也不知道怎么退。
            steps.append(self._step(root, ['git', 'rebase', '--abort'],
                                    '这次改写没成，退回去恢复原样', 120))
            res = self._finish(path, steps)
            res['note'] = ('改写没成功，仓库已经退回原样（这条版本还在）。'
                           '多半是后面的版本改到了同一处代码 —— 可以先用「安全撤销」。')
            return res
        if push and was_pushed:
            remote = (upstream.split('/')[0] if '/' in upstream else 'origin')
            steps.append(self._step(root, ['git', 'push', '--force-with-lease', remote, branch],
                                    '强推覆盖云端，让它在 GitHub 上也没了', 300))
        if dirty:
            steps.append(self._step(root, ['git', 'stash', 'pop'],
                                    '把刚才备份的改动放回来', 60))
        res = self._finish(path, steps)
        res['undoTag'] = tag
        res['undoCmd'] = 'git reset --hard %s' % tag
        res['others'] = others
        res['note'] = ('已经从历史里抹掉 %s；上面的版本号会全部重排。'
                       '反悔：%s' % (short, res['undoCmd'])) + \
            ('（另外这些分支也含这条提交，一起变了：%s）' % '、'.join(others) if others else '') + \
            ('　★ GitHub 上旧提交不会立刻消失，一串哈希短期内仍能访问；'
             '如果这一版里泄了密码/密钥，务必先把那把密钥换掉。' if push and was_pushed else '')
        return res

    # ---- 暂存盘（stash）：列出来、删掉某一份
    def stashes(self, params=None):
        """列出「收起来的改动」每一份（界面「找回收起的改动」靠它）。"""
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'items': []}
        root = info['root']
        # ★ 别加 `--date=...`：那会让 %gd 从 stash@{0} 变成 stash@{2026-10-20 13:44}，
        #   序号就丢了（真机上就是这个现象）。要时间就用 %cr（"5 分钟前"）。
        got = git(root, 'stash', 'list', '--pretty=format:%gd%x00%cr%x00%s')
        items = []
        for line in (got['out'] or '').splitlines():
            bits = line.split('\x00')
            if len(bits) < 3:
                continue
            name, when, msg = bits[0].strip(), bits[1].strip(), bits[2].strip()
            m = re.match(r'stash@\{(\d+)\}', name)
            items.append({'index': int(m.group(1)) if m else len(items),
                          'name': name, 'when': when, 'subject': msg})
        return {'ok': True, 'path': path, 'root': root, 'items': items,
                'count': len(items), 'cmd': 'git stash list', 'at': now_text()}

    def drop_stash(self, params=None):
        """删掉某一份收起来的改动（`git stash drop stash@{N}`）。

        ★ 这一步回不去（那串提交还在 .git 里，但找它要手工翻 fsck，普通人等于找不回），
          所以界面上必须先给人看清「要删的是哪一份、里面是哪个版本」。
        """
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        try:
            idx = int(p.get('index'))
        except (TypeError, ValueError):
            return {'ok': False, 'steps': [], 'why': '没说要删第几份（index）'}
        listed = self.stashes({'path': path})
        if not listed.get('ok'):
            return {'ok': False, 'steps': [], 'why': listed.get('why') or '列不出来'}
        hit = [x for x in listed['items'] if x['index'] == idx]
        if not hit:
            return {'ok': False, 'steps': [],
                    'why': '没有 stash@{%d} 这一份（现在一共 %d 份）—— 列表可能已经变了，刷新一下'
                           % (idx, listed['count'])}
        steps = [self._step(root, ['git', 'stash', 'drop', 'stash@{%d}' % idx],
                            '删掉这份收起的改动：%s' % (hit[0]['subject'] or '（没有说明）'), 60)]
        return self._finish(path, steps)

    # ---- 镜像
    def mirror(self, params=None):
        """镜像：① 在 GitHub 建仓库并推上去 ② 本地 --mirror 备份 ③ 加一个镜像远端。"""
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        mode = str(p.get('mode') or '').strip()
        steps = []
        if mode == 'gh_create':
            refresh_tools()
            if not shutil.which('gh'):
                # ★ 别让人自己去找原因：告诉他们缺什么、点哪个按钮就能补上。
                return {'ok': False, 'steps': [], 'need': 'install_gh', 'url': URL_GH,
                        'why': '这台电脑上没有 gh（GitHub CLI），我没法替你建仓库。'
                               '点上面「帮我装 gh」，装完再点「登录 GitHub」，'
                               '然后回来这里就能一键建仓库并上传了。'}
            if not self._gh().get('loggedIn'):
                return {'ok': False, 'steps': [], 'need': 'gh_login', 'url': URL_LOGIN,
                        'why': 'gh 装了、但还没登录 GitHub —— 点「登录 GitHub」走一下，'
                               '回来再点这里。'}
            name = str(p.get('name') or '').strip() or os.path.basename(root.rstrip('\\/'))
            remote = str(p.get('remote') or 'origin').strip() or 'origin'
            steps.append(self._step(root, ['gh', 'repo', 'create', name, '--source', root,
                                           '--remote', remote, '--push',
                                           '--private' if p.get('private') else '--public'],
                                    '在 GitHub 上建 %s 并把本地推上去' % name, 300))
        elif mode == 'local_clone':
            dest = str(p.get('dest') or '').strip() or os.path.join(
                os.path.dirname(root), os.path.basename(root.rstrip('\\/')) + '-mirror.git')
            if os.path.abspath(dest).lower().startswith(os.path.abspath(root).lower()):
                return {'ok': False, 'steps': [],
                        'why': '备份目标不能放在仓库里面（会把自己也镜像进去）：%s' % dest}
            steps.append(self._step(root, ['git', 'clone', '--mirror', root, dest],
                                    '本地镜像到 %s' % dest, 180))
        elif mode == 'add_remote':
            url = str(p.get('url') or '').strip()
            remote = str(p.get('remote') or 'mirror').strip() or 'mirror'
            if not url:
                return {'ok': False, 'steps': [], 'why': '没给镜像远端的地址'}
            have = [n.strip() for n in git(root, 'remote')['out'].splitlines() if n.strip()]
            steps.append(self._step(root, ['git', 'remote', 'set-url', remote, url]
                                    if remote in have else
                                    ['git', 'remote', 'add', remote, url],
                                    '把远端 %s 指向 %s' % (remote, url), 30))
            steps.append(self._step(root, ['git', 'push', remote, '--all'],
                                    '把全部分支推过去', 300))
            steps.append(self._step(root, ['git', 'push', remote, '--tags'],
                                    '把标签也推过去', 120))
        else:
            return {'ok': False, 'steps': [],
                    'why': '没给镜像方式（gh_create / local_clone / add_remote）'}
        res = self._finish(path, steps)
        # ★ 建仓库最常见的两个失败，别把 gh 的英文原文甩给人：
        #   「name already exists」= 名字被占了；「not logged in」= 忘了登录。
        if mode == 'gh_create' and not res.get('ok'):
            blob = ' '.join([(s.get('out') or '') for s in steps] +
                            [str(s.get('why') or '') for s in steps]).lower()
            if 'already exists' in blob or 'name already' in blob:
                res['suggest'] = (str(p.get('name') or '').strip() or
                                  os.path.basename(root.rstrip('\\/'))) + '-2'
                res['note'] = ('GitHub 上已经有叫这个的仓库了。换个名字再点一次（比如 %s），'
                               '或者用「我已有仓库，填地址」把现成的那个接过来。'
                               % res['suggest'])
            elif 'auth' in blob or 'not logged' in blob or 'gh auth' in blob:
                res['need'] = 'gh_login'
                res['note'] = 'gh 还没登录 GitHub —— 点「登录 GitHub」走一下，回来再点这里。'
        return res

    def remote_repo(self, params=None):
        """GitHub 上这个仓库长什么样（gh 拿的，要联网 + 登录）。"""
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path}
        if not GH:
            return {'ok': False,
                    'why': '这台机器上没有 gh（GitHub CLI）—— 装上并 gh auth login 就能看到 GitHub 那边的情况'}
        fields = ('nameWithOwner,description,visibility,stargazerCount,forkCount,'
                  'defaultBranchRef,url,pushedAt,isFork,parent')
        got = run([GH, 'repo', 'view', '--json', fields], cwd=info['root'], timeout=45)
        if not got['ok']:
            lines = (got['out'] or '').strip().splitlines() or ['gh 没读出来']
            return {'ok': False, 'cmd': got['cmd'], 'out': got['out'], 'why': lines[0]}
        try:
            data = json.loads(got['out'] or '{}')
        except ValueError:
            return {'ok': False, 'cmd': got['cmd'], 'out': got['out'],
                    'why': 'gh 回的不是 JSON'}
        db = data.get('defaultBranchRef') or {}
        parent = data.get('parent') or {}
        return {'ok': True, 'cmd': got['cmd'], 'path': path,
                'fullName': data.get('nameWithOwner') or '',
                'desc': data.get('description') or '',
                'visibility': data.get('visibility') or '',
                'stars': data.get('stargazerCount') or 0,
                'forks': data.get('forkCount') or 0,
                'defaultBranch': db.get('name') or '',
                'url': data.get('url') or '',
                'pushedAt': (data.get('pushedAt') or '')[:19].replace('T', ' '),
                'isFork': bool(data.get('isFork')),
                'parentName': parent.get('nameWithOwner') or ''}


def recent_payload():
    d = load_store()
    out = []
    for p in d['recent']:
        out.append({'path': p, 'exists': os.path.isdir(p),
                    'name': os.path.basename(p.rstrip('\\/')) or p,
                    'repo': os.path.exists(os.path.join(p, '.git'))})
    return out


# ------------------------------------------------------------------ 内嵌模式（stdio）
class _StdoutToProgress(object):
    """内嵌模式下挡在 `sys.stdout` 前面：**print 出来的东西一律变成"进度"**。

    ★ 为什么要有（探针真抓到的）：内嵌模式下 stdout 是**协议通道**（一行一个 JSON），
      而这个文件里到处是 `print('…')`（每一步干了什么）。这些行一进通道，宿主只当
      坏消息丢掉 —— 于是用户在界面上什么也看不见，只能问"它到底在干什么"。
      以前是靠一条条改 print 解决，永远改不完；这里一次性全部改道：
      走 `_live()` → 进当前任务的进度缓冲 → 界面的进度窗口能看见，协议也不会脏。
    """

    def __init__(self, real):
        self._real = real

    def write(self, s):
        text = str(s or '')
        for ln in text.splitlines():
            if ln.strip():
                try:
                    _live(ln)
                except Exception:                                        # noqa: BLE001
                    pass
        return len(text)

    def flush(self):
        return None

    def isatty(self):
        return False

    @property
    def encoding(self):
        return 'utf-8'

    def fileno(self):
        raise OSError('内嵌模式下 stdout 已经改道（不再是协议通道）')


class Embedded:
    """被嵌进 moss 的时候：**不开窗**，在 stdin/stdout 上一行一个 JSON 说话。"""

    def __init__(self):
        self.core = Core()
        self._lock = threading.Lock()
        # 协议通道单独留一份；剩下的 print 全部改道成进度（见 _StdoutToProgress）
        self._out = sys.stdout
        sys.stdout = _StdoutToProgress(self._out)

    def send(self, obj):
        self._out.write(json.dumps(obj, ensure_ascii=False) + '\n')
        self._out.flush()

    def loop(self):
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({'event': 'error', 'data': {'why': '这不是 JSON：%s' % line[:80]}})
                continue
            mid, method = msg.get('id'), str(msg.get('method') or '')
            if method == 'ping':
                self.send({'id': mid, 'ok': True, 'result': {'pong': True, 'at': now_text()}})
                continue
            fn = getattr(self.core, method, None)
            if not callable(fn) or method.startswith('_'):
                self.send({'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method})
                continue
            try:
                with self._lock:
                    result = fn(msg.get('params'))
                self.send({'id': mid, 'ok': True, 'result': result})
            except Exception as e:                                       # noqa: BLE001
                self.send({'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})


# ------------------------------------------------------------------ 独立窗口
def run_window(path=''):
    import webview                                                     # noqa: PLC0415

    core = Core(path)

    # ★★ 别再一个一个手写转发（这个坑真机上炸过）：
    #    独立窗口走 `window.pywebview.api.<方法>`，它只认 Api 类上**真实存在**的方法。
    #    以前这里是手写白名单，新加的方法忘登记就报「后端没有这个方法」——
    #    最惨的是打开窗口第一步就调 timeline，于是"一开就报错、什么都点不动"。
    #    现在 build_api() 按 Core 自动转发：Core 有什么，窗口就能调什么，不会再漏。
    #    （两个老坑仍要注意：每个方法都要收得下那一个 params；别把 window 挂成属性。）
    api = build_api(core)()
    webview.create_window(TITLE, url=UI, js_api=api,
                          width=1180, height=800, min_size=(900, 620))
    webview.start()
    return 0


# ------------------------------------------------------------------ 命令行
def build_api(core):
    """造**独立窗口**那层桥的类（run_window 和自检共用同一份逻辑）。

    ★ 这段必须只有一份：以前 Api 是手写白名单，新方法忘登记就报
      「后端没有这个方法」—— 真机上整个窗口一开就废。现在按 Core 自动转发。
    """
    class Api(object):
        def __init__(self):
            self._stop = False

        def ping(self, params=None):
            return {'pong': True, 'at': now_text()}

        def stop(self, params=None):
            self._stop = True
            return {'ok': True}

    for name in dir(core):
        if name.startswith('_') or not callable(getattr(core, name, None)):
            continue
        if hasattr(Api, name):
            continue

        def _make(nm):
            def _fwd(self, params=None):
                return getattr(core, nm)(params)
            _fwd.__name__ = nm
            return _fwd

        setattr(Api, name, _make(name))
    return Api


def bridge_check(core, need):
    """照 run_window 的做法把桥建起来，看界面要的方法是不是都挂上了。"""
    try:
        api = build_api(core)()
    except Exception:                                                # noqa: BLE001
        return None
    gone = [m for m in need if not callable(getattr(api, m, None))]
    return (len([n for n in dir(api) if not n.startswith('_')]), gone)


def write_result(payload):
    rf = os.environ.get('MOSS_RESULT_FILE')
    if not rf:
        return
    try:
        with open(rf, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:                                                    # noqa: BLE001
        pass


def cli(action, path, arg='', extra=None):
    core = Core()
    # ★ 这三个是"分好几步"的动作（先打标签、再改写、再强推…），一条 git 命令表达不了，
    #   所以不进 ACTIONS 表；命令行照样能用，方便脚本和排查：
    #     moss :github action=stashes       path=D:/code/x
    #     moss :github action=del_commit    path=D:/code/x arg=<版本哈希>     ← 追加一条撤销（安全）
    #     moss :github action=purge_commit  path=D:/code/x arg=<版本哈希>     ← 从历史里抹掉（危险）
    #     moss :github action=drop_stash    path=D:/code/x arg=<第几份>
    # ★ 环境体检也做成命令行能查的：装完 git / gh 之后，人（和 AI）都能一条命令
    #   看清"现在齐了没、下一步该点什么"。
    # 装到哪了（界面靠它画进度条；命令行也能查，排查"点了没动静"时特别好用）
    # 真正干活那一步：install_tool 起一个**独立进程**跑它（关窗口也不中断）
    # 清掉写包时留下的临时探针文件（_how.py / _how.txt 这类，白名单）
    if action == 'tidy':
        got = core.tidy({'path': resolve_path(path)})
        print('[github] 删了：%s' % ('、'.join(got['removed']) or '（没有要删的）'))
        if got['failed']:
            print('[github] 没删成：%s' % '、'.join(got['failed']))
        write_result(got)
        return 0 if got['ok'] else 1
    # 界面能调到哪些方法（排查"后端没有这个方法"用）
    if action == 'list_methods':
        names = sorted([n for n in dir(core)
                        if not n.startswith('_') and callable(getattr(core, n, None))])
        print('[github] Core 上可调用的方法（%d 个）：' % len(names))
        print('  ' + ' '.join(names))
        # 顺手核对界面会用到的那几个
        need = ['boot', 'actions', 'snapshot', 'timeline', 'cloud_versions', 'show_commit',
                'run_action', 'file_op', 'gh', 'set_path', 'forget_path', 'browse', 'disks',
                'net_probe', 'remote_repo', 'mirror', 'stashes', 'drop_stash',
                'delete_commit', 'env_check', 'install_tool', 'install_status',
                'fix_identity', 'open_url', 'gh_login',
                # 长任务 + 把黑盒打开的那几个（界面全靠它们：进度、日志、体检、屏蔽）
                'job_start', 'job_state', 'job_cancel',
                'push_check', 'bigfiles', 'shield', 'ignore', 'sync_log']
        missing = [m for m in need if not callable(getattr(core, m, None))]
        print('[github] 界面用到但缺失的：%s' % (' '.join(missing) if missing else '（一个都不缺）'))
        # ★ 真正要验的是**独立窗口那层桥**（真机报的"后端没有这个方法"就出在那儿）：
        #   pywebview 只认 Api 类上真实存在的方法，手写白名单漏一个就报错。
        #   这里把 run_window 里那段自动转发的逻辑照跑一遍，确认界面要的方法都挂上了。
        bridged = bridge_check(core, need)
        if bridged is None:
            print('[github] 桥检查跳过（这台机器没法建窗口）')
        else:
            print('[github] 独立窗口桥：%d 个方法可调；缺的：%s'
                  % (bridged[0], '、'.join(bridged[1]) if bridged[1] else '（一个都不缺）'))
            if bridged[1]:
                write_result({'methods': names, 'missing': missing, 'bridgeMissing': bridged[1]})
                return 1
        write_result({'methods': names, 'missing': missing,
                      'bridge': bridged[0] if bridged else None})
        return 0 if not missing else 1
    # 登录 gh：arg=dry 只打印命令不弹窗（验证用），否则真开窗口
    if action == 'gh_login':
        got = core.gh_login({'dry': bool((arg or '').strip() == 'dry')})
        print('[github] %s' % (got.get('cmd') or got.get('why') or got.get('help') or ''))
        write_result(got)
        return 0 if got.get('ok') else 1
    if action == 'install_portable':
        what = arg or 'gh'
        ok, got = install_portable(what)
        print('[github] 便携版 %s：%s' % (what, got if ok else ('失败 ' + str(got))), flush=True)
        return 0 if ok else 1
    # 命令行也能踢一脚安装（排查用；正常人是点界面上的按钮）
    if action == 'install_tool':
        got = core.install_tool({'what': arg or 'gh'})
        print('[github] %s' % (got.get('why') or ''))
        write_result(got)
        return 0 if got.get('ok') else 1
    if action == 'install_status':
        got = core.install_status({'what': arg or (extra or {}).get('what') or ''})
        print('[github] 状态：%s（%s）　已 %d 秒　装上了没：%s'
              % (got.get('text'), got.get('phase'), got.get('secs') or 0,
                 '是' if got.get('found') else '还没有'))
        if got.get('log'):
            print('---- 日志尾巴 ----')
            print(got['log'])
            print('-----------------')
        else:
            print('[github] 还没有日志输出')
        write_result(got)
        return 0 if got.get('ok') else 1
    if action in ('env_check', 'doctor'):
        p = resolve_path(path)
        got = core.env_check({'path': p})
        print('[github] 目录：%s' % p)
        mark = {'ok': '✓', 'warn': '!', 'bad': '✗', 'skip': '·'}
        for it in got.get('items') or []:
            print('  %s %-28s %s' % (mark.get(it['state'], '?'), it['label'],
                                     it.get('detail') or ''))
            if it.get('extra'):
                print('      %s' % it['extra'])
            if it.get('help') and it['state'] in ('bad', 'warn'):
                print('      → %s' % it['help'])
        if got.get('next'):
            print('[github] 下一步：%s —— %s' % (got['next'], got.get('nextText') or ''))
        else:
            print('[github] 该有的都齐了，可以正常用。')
        if got.get('pendingInstall'):
            print('[github] 刚起步的安装：%s（%s）—— 装完点「再检查一次」'
                  % (got['pendingInstall']['what'], got['pendingInstall']['ago']))
        print('[github] %s' % got.get('help'))
        write_result({'ok': True, 'path': p, 'ready': got.get('ready'),
                      'cloudReady': got.get('cloudReady'), 'todo': got.get('todoCount'),
                      'items': [{'key': i['key'], 'state': i['state'], 'detail': i.get('detail')}
                                for i in (got.get('items') or [])]})
        return 0
    if action in ('stashes', 'del_commit', 'purge_commit', 'drop_stash'):
        asked = action
        action = {'del_commit': 'delete_commit', 'purge_commit': 'delete_commit'}.get(action, action)

        p = resolve_path(path)
        if not os.path.isdir(p):
            print('[github] 目录不存在：%s' % (path or p))
            return 3
        # ★ 宿主只把 action / path / arg 三个字段传进来（界面上声明的参数），
        #   所以「用哪种删法」走**动作名**，不走 k=v —— 命令行同样一条命令能表达。
        params = {'path': p}
        if asked in ('del_commit', 'purge_commit'):
            params['hash'] = arg
            params['mode'] = 'purge' if asked == 'purge_commit' else 'revert'
            params['push'] = True
        if action == 'drop_stash' and arg.strip():
            params.setdefault('index', arg)
        got = getattr(core, action)(params)
        print('[github] 目录：%s' % p)
        if action == 'stashes':
            for it in got.get('items') or []:
                print('  %-14s %s  %s' % (it['name'], it['when'], it['subject']))
            if not (got.get('items') or []):
                print('  （一份都没有）')
        for s in got.get('steps') or []:
            print('[%s] %s' % ('✓' if s.get('ok') else '✗', s.get('label') or s.get('cmd') or ''))
            out = (s.get('out') or '').strip()
            if out and not s.get('ok'):
                print('    ' + out.replace('\n', '\n    ')[:800])
        if got.get('note'):
            print('[github] %s' % got['note'])
        if got.get('undoCmd'):
            print('[github] 反悔：%s' % got['undoCmd'])
        if not got.get('ok'):
            print('[github] 没跑成：%s' % (got.get('why') or '见上面哪一步红了'))
        write_result({'ok': bool(got.get('ok')), 'action': action, 'path': p,
                      'steps': [{'ok': s.get('ok'), 'label': s.get('label') or s.get('cmd')}
                                for s in (got.get('steps') or [])],
                      'note': got.get('note') or ''})
        return 0 if got.get('ok') else 1
    if action in ('untrack', 'gitlog', 'shield', 'ignore'):
        p = resolve_path(path)
        _fn = {'gitlog': 'sync_log', 'untrack': 'untrack',
               'shield': 'shield', 'ignore': 'ignore'}[action]
        _kw = {'path': p}
        if action in ('untrack', 'shield'):
            _kw['arg'] = arg
            _kw['patterns'] = [x for x in arg.replace(';', ',').split(',') if x.strip()]
        if action == 'ignore':
            _kw['pattern'] = arg
            _kw['op'] = 'add' if arg else 'list'
        got = getattr(core, _fn)(_kw)
        if action == 'gitlog':
            print('[github] 日志文件：%s' % got.get('path'))
            print(got.get('out') or '')
        elif action == 'ignore':
            print('[github] 清单文件：%s' % got.get('file'))
            for e in got.get('entries') or []:
                mark = ('（还在库里 %d 个文件 / %s）' % (e['tracked'], e['size'])) if e.get('tracked') else ''
                print('  %3d. %s %s' % (e.get('line'), e.get('pattern'), mark))
            if not (got.get('entries') or []):
                print('  （清单是空的 —— 什么过滤规则都还没写）')
            if got.get('why'):
                print('[github] %s' % got['why'])
        else:
            print('[github] 目录：%s' % p)
            print('[github] 等价命令：%s' % got.get('cmd', ''))
            for s in got.get('steps') or []:
                print('[%s] %s' % ('✓' if s.get('ok') else '✗', s.get('label') or s.get('cmd') or ''))
                out = (s.get('out') or '').strip()
                if out and not s.get('ok'):
                    print('    ' + out.replace('\n', '\n    ')[:800])
            if got.get('note'):
                print('[github] %s' % got['note'])
            if not got.get('ok'):
                print('[github] 没跑成：%s' % (got.get('why') or '见上面哪一步红了'))
        write_result({'ok': bool(got.get('ok')), 'action': action, 'path': p,
                      'cmd': got.get('cmd', ''), 'out': got.get('out', '')[:4000],
                      'count': got.get('count'), 'note': got.get('note') or ''})
        return 0 if got.get('ok') else 1
    if action not in ACTIONS:
        names = '、'.join(ACTIONS.keys())
        print('[github] 不认识的 action：%s' % action)
        print('[github] 可以用的有：%s、del_commit、purge_commit、stashes、drop_stash' % names)
        print('[github] 例：moss :github action=status path=D:/code/my-repo')
        print('[github] 撤销某版：moss :github action=del_commit path=<目录> arg=<哈希>')
        print('[github] 抹掉某版：moss :github action=purge_commit path=<目录> arg=<哈希>')
        return 2
    p = resolve_path(path)
    if not os.path.isdir(p):
        print('[github] 目录不存在：%s' % (path or p))
        return 3
    got = core.run_action({'name': action, 'path': p, 'arg': arg})
    print('[github] 目录：%s' % p)
    print('[github] 等价命令：%s' % got.get('cmd', ''))
    if got.get('out'):
        print(got['out'])
    if not got.get('ok'):
        print('[github] 没跑成：%s' % (got.get('why') or '退出码 %s' % got.get('code')))
    if got.get('ok') and action == 'status':
        got2 = core.snapshot({'path': p})
        info = got2.get('repo')
        if info:
            print('[github] 分支 %s · 改动 %d 个文件 · 领先 %d / 落后 %d · %s'
                  % (info['branch'], info['changeCount'], info['ahead'], info['behind'],
                     got2['net'].get('state', '')))
    write_result({'ok': bool(got.get('ok')), 'action': action, 'path': p,
                  'cmd': got.get('cmd', ''), 'out': got.get('out', ''),
                  'code': got.get('code'), 'ms': got.get('ms')})
    return 0 if got.get('ok') else 1


def argv_params():
    """命令行上直接给的 k=v（`moss <包路径> action=status` 这种跑法也能用）。

    ★ 正常跑包时参数由宿主放进 `MOSS_PKG_PARAMS`；这里顺手把 argv 里的 `k=v` 也吃进来，
      于是"用文件路径直接跑"（调试、脚本、AI 验收）也走同一条路，不用另写一份。
    """
    out = {}
    for i, a in enumerate(sys.argv[1:]):
        if '=' in a and not a.startswith('-'):
            k, v = a.split('=', 1)
            out[k.strip()] = v
        elif i == 0 and a and not a.startswith('-'):
            out.setdefault('action', a)
    return out


def main():
    raw = os.environ.get('MOSS_PKG_PARAMS')
    if raw is None:
        # 宿主没注入（直接用 python / 文件路径跑）→ 从 argv 里读 k=v
        params = argv_params()
    else:
        try:
            params = json.loads(raw or '{}')
        except ValueError:
            params = {}
    action = str(params.get('action') or '').strip()
    path = str(params.get('path') or '').strip()
    arg = str(params.get('arg') or '').strip()
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        Embedded().loop()
        return 0
    if action:
        return cli(action, path, arg, params)
    return run_window(path)


if __name__ == '__main__':
    sys.exit(main())
