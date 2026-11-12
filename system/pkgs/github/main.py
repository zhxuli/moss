import collections
import json
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
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

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

os.environ.setdefault('GH_NO_UPDATE_NOTIFIER', '1')
os.environ.setdefault('GH_PROMPT_DISABLED', '1')
os.environ.setdefault('GH_PAGER', 'cat')
os.environ.setdefault('GH_NO_COLOR', '1')

URL_GIT = 'https://git-scm.com/download/win'
URL_GH = 'https://cli.github.com/'
URL_SIGNUP = 'https://github.com/signup'
URL_LOGIN = 'https://github.com/login'

HELP_AI = ('实在弄不明白？在这个窗口外面跟 moss 的 AI 说一句'
           '「帮我把这台电脑的 Git / GitHub 环境弄好」——它能看到同样的信息，'
           '装什么、点哪儿，它替你弄。')

def refresh_tools():
    global GIT, GH
    got = shutil.which('git') or local_tool('git')
    if got:
        GIT = got
    got = shutil.which('gh') or local_tool('gh')
    if got:
        GH = got
    return GIT, GH

def local_tool(what):
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

PORTABLE = {
    'gh': dict(repo='cli/cli', pick=r'windows_amd64\.zip$', label='GitHub CLI'),
    'git': dict(repo='git-for-windows/git', pick=r'MinGit-.*-64-bit\.zip$', label='Git'),
}

def _http_json(url, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'moss-github',
                                              'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

MIRRORS = ('', 'https://ghproxy.net/', 'https://mirror.ghproxy.com/',
           'https://gh-proxy.com/', 'https://ghfast.top/')

FALLBACK_VER = {'gh': ('v2.63.2', 'gh_2.63.2_windows_amd64.zip'),
                'git': ('v2.47.1', 'MinGit-2.47.1-64-bit.zip')}

def install_portable(what):
    spec = PORTABLE.get(what)
    js, log = install_paths(what)
    t0 = datetime.now()

    def say(line):
        try:
            with open(log, 'a', encoding='utf-8') as f:
                f.write('%s  %s\n' % (datetime.now().strftime('%H:%M:%S'), line))
        except Exception:
            pass

    try:
        say('开始下载 %s 的官方便携版（不需要管理员权限）' % spec['label'])
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
            except Exception as e:
                meta_err = '%s: %s' % (type(e).__name__, e)
                say('查版本没成（%s）：%s' % (m or '直连', str(e)[:80]))
        if not dl:
            tag, name = FALLBACK_VER[what]
            say('查不到最新版本（%s），改用固定版本 %s' % (meta_err[:60] or '网络不通', tag))
            dl = 'https://github.com/%s/releases/download/%s/%s' % (spec['repo'], tag, name)
        say('版本 %s，文件 %s（%s）' % (tag, name, human_size(size) if size else '大小未知'))
        os.makedirs(TOOLS_DIR, exist_ok=True)
        zpath = os.path.join(TOOLS_DIR, name)

        import urllib.request
        got = 0
        last_err = ''
        for m in MIRRORS:
            src = (m + dl) if m else dl
            try:
                say('正在连 %s …' % (m or 'github.com 直连'))
                req = urllib.request.Request(src, headers={'User-Agent': 'moss-github'})
                got, last = 0, -10
                with urllib.request.urlopen(req, timeout=60) as r, open(zpath, 'wb') as f:
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
            except Exception as e:
                last_err = '%s: %s' % (type(e).__name__, e)
                say('这个通道不行（%s）：%s' % (m or '直连', str(e)[:80]))
                got = 0
        if got <= 0:
            raise RuntimeError('所有下载通道都失败了，最后一个错误：%s' % last_err)
        say('下载完成，正在解压…')
        import zipfile
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
    except Exception as e:
        say('下载/解压失败：%s: %s' % (type(e).__name__, e))
        say('EXIT_FAIL')
        mark_install(what, log=log, done=True, code=1)
        return False, str(e)

def browse_url(url):
    url = str(url or '').strip()
    if not re.match(r'^https?://', url):
        return False
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False

def open_url(url):
    ok = browse_url(url)
    print('[github] 打开网址 %s → %s' % (url, 'ok' if ok else '失败'), flush=True)
    return ok

_NET_CACHE = {'at': 0.0, 'ok': False}

_ENV_CACHE = {'path': '', 'at': 0.0, 'data': None}

def net_touch(host='github.com', port=443, timeout=3, cache=20):
    now = time.time()
    if now - _NET_CACHE['at'] < cache:
        return _NET_CACHE['ok']
    ok = [False]

    def probe():
        import socket
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
        except Exception:
            ok[0] = False

    import threading
    th = threading.Thread(target=probe, daemon=True)
    th.start()
    th.join(timeout + 0.5)
    _NET_CACHE.update({'at': time.time(), 'ok': bool(ok[0])})
    return bool(ok[0])

def repo_probe(path):
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
    if info is None:
        info = repo_probe(path)
    if not info:
        return {'can': False, 'how': '', 'need': 'repo',
                'why': '这个文件夹还不是 git 仓库 —— 先「开始记录」'}
    root = info['root']
    url = info.get('remote') or ''
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
    base = [GIT] + (['-C', path] if path and os.path.isdir(path) else [])
    nm = run(base + ['config', '--get', 'user.name'], timeout=10)
    em = run(base + ['config', '--get', 'user.email'], timeout=10)
    return {'name': (nm['out'] or '').strip() if nm['ok'] else '',
            'email': (em['out'] or '').strip() if em['ok'] else ''}

def ensure_identity(path, force=False):
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

def install_paths(what):
    os.makedirs(DATA_DIR, exist_ok=True)
    return (os.path.join(DATA_DIR, 'install.json'),
            os.path.join(DATA_DIR, 'install-%s.log' % what))

def mark_install(what, log='', done=False, code=None, kind=''):
    js, _ = install_paths(what)
    try:
        with open(js, 'w', encoding='utf-8') as f:
            json.dump({'what': what, 'at': time.time(), 'log': log,
                       'done': bool(done), 'code': code, 'kind': kind or ''}, f)
    except Exception:
        pass

def read_install():
    try:
        with open(os.path.join(DATA_DIR, 'install.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def pending_install():
    d = read_install()
    if not d or d.get('done'):
        return None
    ts = float(d.get('at') or 0)
    if time.time() - ts > 900:
        return None
    return {'what': d.get('what') or '', 'ago': rel_time(ts),
            'secs': int(time.time() - ts)}

def tail_log(path, limit=4000):
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size > limit:
                f.seek(size - limit)
            blob = f.read()
    except Exception:
        return ''
    text = blob.decode('utf-8', 'replace')
    if size > limit:
        text = text.split('\n', 1)[-1]
    out = []
    for line in text.replace('\r\n', '\n').split('\n'):
        seg = line.split('\r')[-1].rstrip()
        if seg:
            out.append(seg)
    return '\n'.join(out[-40:])

def install_phase(text, found):
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
    hits = re.findall(r'(\d{1,3})\s*%', text or '')
    for h in reversed(hits):
        try:
            v = int(h)
        except ValueError:
            continue
        if 0 <= v <= 100:
            return v
    return None

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
    out = []
    for a in argv:
        if a == '' or re.search(r'[\s"]', a):
            out.append('"%s"' % a.replace('"', '\\"'))
        else:
            out.append(a)
    return ' '.join(out)

def run(argv, cwd=None, timeout=30):
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
    except Exception as e:
        code, out = 1, '%s: %s' % (type(e).__name__, e)
    got = {'ok': code == 0, 'code': code, 'out': (out or '').strip('\n'),
           'ms': int((time.time() - t0) * 1000), 'cmd': display(argv)}
    log_cmd(argv, cwd, got, timeout)
    return got

SYNC_LOG = os.path.join(DATA_DIR, 'sync.log')
LOG_KEEP = 300
LOG_MAX = 512 * 1024

PROGRESS_SUBS = ('push', 'fetch', 'pull', 'clone')

EMBEDDED = str(os.environ.get('MOSS_UI_EMBED') or '').strip().lower() in ('1', 'true', 'yes')

_JOB = {'cur': None}
_JOB_LOCK = threading.Lock()
_IDLE = collections.deque(maxlen=40)

def _live(line):
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
        return
    print(text, flush=True)

def _job_proc(proc):
    with _JOB_LOCK:
        job = _JOB.get('cur')
    if job is not None:
        with job['lock']:
            job['proc'] = proc

def _job_cancelled():
    with _JOB_LOCK:
        job = _JOB.get('cur')
    if job is None:
        return False
    with job['lock']:
        return bool(job.get('cancel'))

def _kill_tree(proc):
    if proc is None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def log_write(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        old = []
        try:
            with open(SYNC_LOG, encoding='utf-8', errors='replace') as f:
                old = [x for x in f.read().splitlines() if x.strip()]
        except OSError:
            old = []
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
    except Exception:
        return False

def _sub(argv):
    rest = list(argv)[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ('-c', '--config', '-C', '--git-dir', '--work-tree', '--exec-path'):
            i += 2
            continue
        if a.startswith('-'):
            i += 1
            continue
        return a
    return ''

def log_cmd(argv, cwd, got, timeout=0, note=''):
    ms = int(got.get('ms') or 0)
    if got.get('ok') and ms < 3000 and not note:
        return
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
        _job_proc(p)
    except FileNotFoundError:
        got = {'ok': False, 'code': 127, 'ms': 0, 'cmd': display(cmd),
               'out': '找不到命令：%s —— 装了吗？在 PATH 里吗？' % cmd[0]}
        log_cmd(cmd, cwd, got, timeout)
        return got
    except Exception as e:
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
        except Exception:
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
            killed = True
            _kill_tree(p)
            break
        if time.time() - t0 > timeout:
            killed = True
            try:
                p.kill()
            except Exception:
                pass
            break
        if time.time() - last > tick:
            _live('   …还在跑：已 %d 秒，还没有新输出（进程没死，就是慢）'
                  % int(time.time() - t0))
            last = time.time()
    try:
        code = p.wait(timeout=10)
    except Exception:
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

def _exec_once(argv, cwd=None, timeout=60, label=''):
    if _sub(list(argv)) in PROGRESS_SUBS and \
            str(os.environ.get('MOSS_GIT_PROGRESS', '1')).strip() != '0':
        return run_progress(argv, cwd=cwd, timeout=timeout, label=label)
    return run(argv, cwd=cwd, timeout=timeout)

NET_SUBS = frozenset(('push', 'fetch', 'pull', 'clone', 'ls-remote'))

NET_FLAKY = re.compile(
    r'schannel|ssl/tls connection failed|unexpected eof|connection was reset'
    r'|connection reset by peer|recv failure|gnutls_handshake|ssl_error_syscall'
    r'|tls packet was malformed|rpc failed|remote end hung up|early eof'
    r'|could not resolve host|failed to connect|operation timed out|timed out'
    r'|http 50[234]|proxy', re.I)

NET_FINAL = re.compile(
    r'authentication failed|permission denied|permission to .* denied'
    r'|could not read username|repository not found|access denied|403 forbidden'
    r'|does not exist|non-fast-forward|\[rejected\]|merge conflict'
    r'|not a git repository|invalid username or password', re.I)

NET_ATTEMPTS = 3

NET_PREF = os.path.join(DATA_DIR, 'net.json')

def _net_score():
    try:
        with open(NET_PREF, encoding='utf-8') as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    lose = d.get('lose') if isinstance(d.get('lose'), dict) else {}
    return {k: max(0, int(lose.get(k) or 0)) for k in ('default', 'openssl')}

def net_pref():
    s = _net_score()
    return 'openssl' if s['openssl'] + 2 <= s['default'] else ''

def net_pref_learn(backend, ok):
    key = 'openssl' if backend == 'openssl' else 'default'
    s = _net_score()
    before = dict(s)
    s[key] = max(0, s[key] + (-1 if ok else 1))
    if s == before:
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = NET_PREF + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'lose': s, 'at': now_text()}, f, ensure_ascii=False)
        os.replace(tmp, NET_PREF)
    except Exception:
        pass

def _mask_proxy(v):
    return re.sub(r'//[^/@]+@', '//***@', str(v or ''))

def git_proxy(url='https://github.com'):
    try:
        got = run([GIT, 'config', '--get-urlmatch', 'http.proxy', url], timeout=10)
    except Exception:
        return ''
    v = (got['out'].splitlines() or [''])[0].strip() if got['ok'] else ''
    return _mask_proxy(v)

def system_proxy():
    for k in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
        v = str(os.environ.get(k) or '').strip()
        if v:
            return _mask_proxy(v), k
    if os.name != 'nt':
        return '', ''
    try:
        import winreg
        path = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                on, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            except OSError:
                on = 0
            if not on:
                return '', ''
            try:
                srv, _ = winreg.QueryValueEx(key, 'ProxyServer')
            except OSError:
                srv = ''
    except Exception:
        return '', ''
    srv = str(srv or '').strip()
    if not srv:
        return '', ''
    if '=' in srv:
        pick = ''
        for part in srv.split(';'):
            k, _, v = part.partition('=')
            if k.strip().lower() in ('https', 'http'):
                pick = v.strip()
                if k.strip().lower() == 'https':
                    break
        srv = pick or ''
    return _mask_proxy(srv), 'Windows 系统代理'

def proxy_alive(proxy, timeout=0.6):
    m2 = re.match(r'^(?:[a-zA-Z0-9+]+://)?(?:[^@/]*@)?([^:/]+):(\d+)', str(proxy or ''))
    if not m2:
        return None
    host, port = m2.group(1), int(m2.group(2))
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _first_line(text, n=90):
    lines = [x.strip() for x in str(text or '').splitlines() if x.strip()]
    return lines[0][:n] if lines else ''

def net_hint(out):
    low = str(out or '').lower()
    if not low:
        return ''
    if 'schannel' in low or 'ssl/tls connection failed' in low:
        return ('Windows 自带的 TLS（schannel）和代理握手没过 —— 默认后端和 openssl 后端都试过了，'
                '这次都不行：看一眼代理软件开着没有（git 配置里那个 proxy 端口对不对）。'
                '凭据在 Windows 凭据管理器里，跟这个没关系，不用重新登录。')
    if 'could not resolve host' in low or 'failed to connect' in low:
        return '连不上 github.com：网络或代理断了（端口变了也会这样）。网络好了再点一次就行。'
    if ('unexpected eof' in low or 'remote end hung up' in low
            or 'connection was reset' in low or 'recv failure' in low or 'early eof' in low):
        return ('连接被掐断（代理偶发的 EOF / reset），已经自动重试过；还不行就再点一次 —— '
                '推成功与否以"两端是不是同一个提交"为准，不会重复上传。')
    if ('authentication failed' in low or 'permission denied' in low
            or 'could not read username' in low):
        return '这是账号 / 凭据的问题，不是网络 —— 去「检查环境」看一眼 GitHub 登录。'
    return ''

def _exec(argv, cwd=None, timeout=60, label=''):
    base = list(argv)
    if _sub(base) not in NET_SUBS:
        return _exec_once(base, cwd=cwd, timeout=timeout, label=label)
    is_git = os.path.basename(str(base[0])).lower() in ('git', 'git.exe')
    can_switch = is_git and os.name == 'nt'
    order = (['openssl', 'default', 'openssl'] if (can_switch and net_pref() == 'openssl')
             else ['default', 'openssl', 'default'])
    got, tries = None, 0
    first_backend = order[0] if can_switch else 'default'
    first_ok, first_out = None, ''
    for i in range(NET_ATTEMPTS):
        backend = order[i] if can_switch else 'default'
        cur, why_try = list(base), ''
        if backend == 'openssl':
            cur = [cur[0], '-c', 'http.sslBackend=openssl'] + cur[1:]
        if i:
            why_try = '，换成 openssl 后端' if backend == 'openssl' else '，换回默认后端'
            time.sleep(0.6 * i)
            _live('⚠ 网络抖了一下（%s），自动重试第 %d 次%s…'
                  % (_first_line((got or {}).get('out'), 60), i + 1, why_try))
        got = _exec_once(cur, cwd=cwd, timeout=timeout,
                         label=label if not i else '%s（重试 %d）' % (label, i + 1))
        tries = i + 1
        got['retried'] = i
        got['cmd'] = display(cur)
        got['backend'] = backend
        if i == 0:
            first_ok, first_out = bool(got.get('ok')), got.get('out') or ''
        if got.get('ok'):
            if first_ok is not None:
                net_pref_learn(first_backend, first_ok)
            if i:
                got['out'] = ((got.get('out') or '')
                              + '\n（网络抖了一下，自动重试 %d 次，第 %d 次才通%s）'
                              % (i, i + 1, why_try)).strip('\n')
                log_cmd(cur, cwd, got, timeout,
                        note='自动重试第 %d 次才成功%s' % (i + 1, why_try))
            return got
        if got.get('code') in (124, 130):
            break
        blob = got.get('out') or ''
        if not NET_FLAKY.search(blob) or NET_FINAL.search(blob):
            break
    if first_ok is False and NET_FLAKY.search(first_out or '') \
            and not NET_FINAL.search(first_out or ''):
        net_pref_learn(first_backend, False)
    if got is not None:
        hint = net_hint(got.get('out') or '')
        if hint:
            got['why'] = '%s%s' % (hint, ('（自动试了 %d 次）' % tries) if tries > 1 else '')
            first = _first_line(got.get('out'))
            if first:
                got['why'] += '　原始报错：' + first
    return got

def git(path, *args, **kw):
    return run([GIT, '-C', path] + list(args), **kw)

def load_store():
    try:
        with open(STORE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
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
    except Exception:
        pass

def remember(path):
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
    cwd = os.getcwd()
    home = os.path.abspath(os.environ.get('MOSS_HOME') or '')
    if home and os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(home):
        return ''
    return cwd if os.path.isdir(os.path.join(cwd, '.git')) else ''

def resolve_path(p):
    p = str(p or '').strip().strip('"').strip("'")
    if p and os.path.isdir(p):
        return os.path.abspath(p)
    d = load_store()
    for cand in (_cwd_seed(), d.get('last'), *(d.get('recent') or []), os.getcwd(),
                 os.path.expanduser('~')):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.getcwd()

def parse_status(text):
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

def repo_info(path, ttl=None):
    ttl = _REPO_TTL if ttl is None else ttl
    key = os.path.abspath(path).lower()
    if ttl > 0:
        hit = _REPO_CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        got = repo_info_raw(path)
        _REPO_CACHE[key] = (time.time(), got)
        return got
    return repo_info_raw(path)

def gits_parallel(path, specs, timeout=25, workers=8):
    out = {}
    if not specs:
        return out
    real = min(len(specs), max(1, workers))
    with ThreadPoolExecutor(max_workers=real) as pool:
        futs = {pool.submit(git, path, *argv, timeout=timeout): name
                for name, argv in specs}
        for f, name in list(futs.items()):
            try:
                out[name] = f.result()
            except Exception as e:
                out[name] = {'ok': False, 'code': -1, 'out': '%s: %s' % (type(e).__name__, e),
                             'ms': 0, 'cmd': 'git ' + ' '.join(specs[name][0])}
    return out

def repo_info_raw(path):
    if not os.path.isdir(path):
        return None
    first = gits_parallel(path, [
        ('top', ['rev-parse', '--show-toplevel']),
        ('br', ['rev-parse', '--abbrev-ref', 'HEAD']),
        ('up', ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']),
        ('url', ['remote', 'get-url', 'origin']),
        ('status', ['status', '--porcelain']),
        ('log', ['log', '-1', '--pretty=format:%h\x1f%an\x1f%ar\x1f%s']),
        ('stash', ['stash', 'list']),
        ('tags', ['tag', '--sort=-creatordate']),
    ])
    top = first['top']
    if not top['ok']:
        return None
    root = (top['out'].splitlines() or [path])[-1].strip()
    if not os.path.isdir(root):
        return None

    br = first['br']
    branch = br['out'].strip() if br['ok'] else ''
    up = first['up']
    upstream = up['out'].strip() if up['ok'] else ''
    remote = first['url']
    rurl = remote['out'].strip() if remote['ok'] else ''
    if not rurl:
        first2 = gits_parallel(root, [
            ('names', ['remote']),
        ])
        names = [n.strip() for n in (first2['names']['out'].splitlines()
                                     if first2['names']['ok'] else []) if n.strip()]
        if names:
            r2 = git(root, 'remote', 'get-url', names[0])
            rurl = r2['out'].strip() if r2['ok'] else ''

    track = upstream
    if not upstream and branch and branch != 'HEAD':
        nm = gits_parallel(root, [('names', ['remote'])])['names']
        names = [n.strip() for n in (nm['out'].splitlines() if nm['ok'] else []) if n.strip()]
        order = (['origin'] if 'origin' in names else []) + [n for n in names if n != 'origin']
        for n in order:
            cand = '%s/%s' % (n, branch)
            if git(root, 'rev-parse', '--verify', '--quiet', cand + '^{commit}')['ok']:
                track = cand
                break
    ahead = behind = 0
    if track:
        ab = git(root, 'rev-list', '--left-right', '--count', 'HEAD...' + track)
        if ab['ok']:
            parts = re.findall(r'\d+', ab['out'])
            if len(parts) >= 2:
                ahead, behind = int(parts[0]), int(parts[1])
    elif rurl and branch and branch != 'HEAD':
        cnt = git(root, 'rev-list', '--count', 'HEAD')
        got = re.findall(r'\d+', cnt['out']) if cnt['ok'] else []
        ahead = int(got[0]) if got else 0

    st = first['status']
    changes, counts = parse_status(st['out'] if st['ok'] else '')

    last = {'hash': '', 'author': '', 'when': '', 'subject': ''}
    lg = first['log']
    if lg['ok'] and lg['out']:
        bits = (lg['out'].splitlines()[0]).split('\x1f')
        if len(bits) >= 4:
            last = {'hash': bits[0], 'author': bits[1], 'when': bits[2], 'subject': bits[3]}

    stash = first['stash']
    tags = first['tags']
    return {
        'root': root, 'name': os.path.basename(root.rstrip('\\/')) or root,
        'branch': branch or '(空仓库)', 'detached': branch == 'HEAD',
        'upstream': upstream, 'track': track,
        'remote': rurl, 'host': host_of(rurl),
        'ahead': ahead, 'behind': behind,
        'dirty': bool(changes), 'counts': counts, 'changes': changes[:200],
        'changeCount': len(changes),
        'lastCommit': last,
        'stashCount': len([x for x in (stash['out'].splitlines() if stash['ok'] else []) if x.strip()]),
        'tagCount': len([x for x in (tags['out'].splitlines() if tags['ok'] else []) if x.strip()]),
    }

_REPO_CACHE = {}
_REPO_TTL = 15.0

def repo_cache_clear(path=None):
    if not path:
        _REPO_CACHE.clear()
        return
    key = os.path.abspath(path).lower()
    for k in list(_REPO_CACHE):
        if k == key or key.startswith(k + os.sep) or k.startswith(key + os.sep):
            _REPO_CACHE.pop(k, None)

def repo_info_fast(path, ttl=None):
    return repo_info(path, ttl=ttl)

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
    elif info.get('track'):
        state = '和 %s 一致（这条分支还没和云端建立跟踪关系，下次上传会自动设上）' % info['track']
    else:
        state = '没有设置跟踪的远端分支（push -u origin %s 可以设上）' % (info['branch'] or 'main')
    return {
        'ok': True, 'remote': info['remote'], 'host': info['host'],
        'upstream': info['upstream'], 'track': info.get('track') or '',
        'ahead': info['ahead'], 'behind': info['behind'],
        'state': state, 'dirty': info['dirty'],
        'lastFetchTs': ts, 'lastFetch': (rel_time(ts) if ts else '没记录（还没 fetch 过）'),
        'probe': probe,
    }

DRIVE_TYPES = {0: '未知', 1: '没有根目录', 2: '可移动磁盘', 3: '本地磁盘',
               4: '网络盘', 5: '光驱', 6: '内存盘'}

def list_disks():
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

    import ctypes
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        letter = chr(ord('A') + i)
        root = letter + ':\\'
        try:
            code = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:
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

def _p(ctx, plain):
    return lambda p, a: plain

def _ctx(ctx):
    return ctx or {}

ACTIONS = {
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
    'loc': dict(group='看', label='代码行数（有多少行代码）', danger=False,
                needArg=None, timeout=180, fake='loc',
                cmd='（本机统计：按扩展名数行数，空行注释都算）',
                desc='数 .py / .html / .js / .css / .vue 这些代码文件有多少行；'
                     '配置文件（json / ini / txt / md）不算。'
                     '同时给两份：只算 git 跟踪的、和磁盘上所有的',
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

NO_REPO_NEEDED = ('disks', 'version', 'clone', 'gh_auth', 'init', 'gitlog')

def actions_payload():
    out = []
    for name, s in ACTIONS.items():
        out.append({'name': name, 'group': s['group'], 'label': s['label'],
                    'desc': s['desc'], 'cmd': s['cmd'], 'danger': bool(s.get('danger')),
                    'needArg': s.get('needArg') or '', 'gh': bool(s.get('gh'))})
    return out

LOC_LANG = {
    'py': 'Python', 'pyw': 'Python',
    'html': 'HTML', 'htm': 'HTML',
    'js': 'JavaScript', 'mjs': 'JavaScript', 'cjs': 'JavaScript',
    'jsx': 'JSX', 'ts': 'TypeScript', 'tsx': 'TSX',
    'css': 'CSS', 'scss': 'SCSS', 'sass': 'Sass', 'less': 'Less',
    'vue': 'Vue', 'svelte': 'Svelte',
    'java': 'Java', 'kt': 'Kotlin', 'swift': 'Swift', 'dart': 'Dart',
    'c': 'C', 'h': 'C/C++ 头', 'cpp': 'C++', 'cc': 'C++', 'cxx': 'C++',
    'hpp': 'C++ 头', 'cs': 'C#', 'go': 'Go', 'rs': 'Rust',
    'rb': 'Ruby', 'php': 'PHP', 'lua': 'Lua', 'sql': 'SQL',
    'sh': 'Shell', 'bash': 'Shell', 'ps1': 'PowerShell', 'bat': 'Batch',
}
LOC_SKIP_DIRS = {
    '.git', '.hg', '.svn', '.venv', 'venv', 'env', '.env', 'node_modules',
    '__pycache__', '.mypy_cache', '.pytest_cache', '.ruff_cache', '.tox',
    '.next', '.nuxt', 'dist', 'build', 'target', 'out', 'coverage',
    'site-packages', '.idea', '.vscode', '.cache', 'bower_components',
    'media', 'uploads', 'upload', 'apps_data', 'dataset', 'datasets', 'data',
    'staticfiles', 'logs', 'tmp', 'temp',
}

def count_lines(fp):
    n, last = 0, b'\n'
    try:
        with open(fp, 'rb') as f:
            while True:
                bit = f.read(262144)
                if not bit:
                    break
                n += bit.count(b'\n')
                last = bit[-1:]
        if last not in (b'\n',):
            n += 1
        return n
    except OSError:
        return -1

def loc_scan(root, names=None, limit=12, budget=8.0, keep_libs=False,
             prune=4000, max_dirs=5000):
    by_lang, top = {}, []
    files, total, skipped = 0, 0, 0
    root = os.path.abspath(root)
    t0 = time.time()
    jumped, cut = [], False

    def one(rel, fp):
        nonlocal files, total, skipped
        ext = os.path.splitext(fp)[1].lower().lstrip('.')
        lang = LOC_LANG.get(ext)
        if not lang:
            skipped += 1
            return
        if not keep_libs and '.min.' in os.path.basename(fp).lower():
            skipped += 1
            return
        n = count_lines(fp)
        if n < 0:
            skipped += 1
            return
        files += 1
        total += n
        cur = by_lang.setdefault(lang, {'lang': lang, 'files': 0, 'lines': 0})
        cur['files'] += 1
        cur['lines'] += n
        top.append({'path': rel.replace('\\', '/'), 'lines': n, 'lang': lang})

    if names is not None:
        for rel in names:
            fp = os.path.join(root, rel.replace('/', os.sep))
            if os.path.isfile(fp):
                one(rel, fp)
    else:
        stack = [root]
        dirs_done = 0
        while stack:
            if time.time() - t0 > budget:
                cut = True
                break
            if dirs_done >= max_dirs:
                cut = True
                jumped.append({'path': '（目录太多，走到 %d 个就先停了）' % max_dirs,
                               'entries': 0})
                break
            cur_dir = stack.pop()
            dirs_done += 1
            try:
                with os.scandir(cur_dir) as it:
                    entries = list(it)
            except OSError:
                continue
            if len(entries) > prune:
                jumped.append({'path': (os.path.relpath(cur_dir, root) or '.').replace('\\', '/'),
                               'entries': len(entries)})
                continue
            for e in entries:
                try:
                    if e.is_dir():
                        if e.name.lower() not in LOC_SKIP_DIRS:
                            stack.append(e.path)
                    elif e.is_file():
                        one(os.path.relpath(e.path, root), e.path)
                except OSError:
                    continue
    top.sort(key=lambda x: -x['lines'])
    return {'files': files, 'lines': total, 'skipped': skipped,
            'byLang': sorted(by_lang.values(), key=lambda x: -x['lines']),
            'top': top[:limit], 'jumped': jumped[:8], 'cut': cut,
            'secs': round(time.time() - t0, 1), 'keepLibs': bool(keep_libs)}

def repo_size_rows(root, limit=20):
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

def _loc_text(r, which):
    d = (r or {}).get(which) or {}
    head = ('%-6s %s%8s 行   %5s 个文件' %
            ('git 跟踪的' if which == 'tracked' else '磁盘上全部',
             '≥' if d.get('cut') else ' ',
             '{:,}'.format(d.get('lines') or 0), d.get('files') or 0))
    out = [head]
    for x in (d.get('byLang') or [])[:8]:
        out.append('        %-12s %8s 行  %5d 个文件'
                   % (x['lang'], '{:,}'.format(x['lines']), x['files']))
    return '\n'.join(out)

def _fake_out(name, path):
    if name == 'loc':
        r = Core(path).loc({'path': path})
        if not r.get('ok'):
            return r.get('why') or '数不出来'
        out = ['按「一个文件多少行就算多少行」数的（空行、注释都算），配置文件不算。', '']
        out.append(_loc_text(r, 'tracked'))
        out.append('')
        out.append(_loc_text(r, 'all'))
        top = ((r.get('all') or {}).get('top') or [])[:8]
        if top:
            out.append('')
            out.append('行数最多的几个文件：')
            for i, f in enumerate(top, 1):
                out.append('  %2d. %-9s %6s 行  %s'
                           % (i, '{:,}'.format(f['lines']), f['lang'], f['path']))
        alld = r.get('all') or {}
        if alld.get('cut'):
            out.append('')
            out.append('★ 「磁盘上全部」这一份**没走完**（%s 秒 / 目录太多就先停了）：'
                       '这个项目里有海量素材目录（音频 / 图标 / 上传件），'
                       '那些地方不是代码。要一个确定的数字，看上面「git 跟踪的」那一份。'
                       % alld.get('secs'))
        out.append('')
        out.append('（跳过 .venv / node_modules / __pycache__ / dist / media 这些目录；'
                   '压缩过的 *.min.js 也不算）')
        return '\n'.join(out)
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

UNIT = '\x1f'

def _rows(text, fields):
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
    got = git(root, 'rev-list', '--count', rev, timeout=25)
    try:
        return int((got['out'] or '0').strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0

def _upstream_hashes(root, upstream, cap=4000):
    if not upstream:
        return set(), False
    got = run([GIT, '-C', root, 'rev-list', '--max-count=%d' % cap, upstream], timeout=30)
    if not got['ok']:
        return set(), False
    lines = [x.strip() for x in got['out'].splitlines() if x.strip()]
    return set(lines), len(lines) >= cap

def git_log_rows(root, limit=40, rev='HEAD'):
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

class Core:
    def __init__(self, path=''):
        self.default_path = str(path or '')
        self._gh_cache = (0.0, None)

    def _path(self, params):
        return resolve_path((params or {}).get('path') or self.default_path)

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
        info = repo_info_fast(path, ttl=0 if (params or {}).get('fresh') else None)
        return {'path': path, 'isRepo': bool(info), 'repo': info,
                'net': net_info(path, info), 'recent': recent_payload(),
                'at': now_text(), 'atTs': time.time()}

    def disks(self, params=None):
        return {'disks': list_disks()}

    def untrack(self, params=None):
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

    def job_start(self, params=None):
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
                   'lines': list(_IDLE) + ['▶ %s 开始' % label],
                   'started': time.time(), 'beat': time.time(),
                   'result': None, 'lock': threading.Lock(), 'proc': None, 'cancel': False}
            _JOB['cur'] = job
            _IDLE.clear()
        threading.Thread(target=self._job_run, args=(job, fn, args), daemon=True).start()
        return {'ok': True, 'id': job['id'], 'label': label, 'method': method}

    def _job_run(self, job, fn, args):
        try:
            res = fn(args)
            if not isinstance(res, dict):
                res = {'ok': True, 'out': str(res)}
        except Exception as e:
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
                'silent': round(time.time() - beat, 1),
                'lines': lines, 'result': res}

    def job_cancel(self, params=None):
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

    def push_check(self, params=None):
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

    def shield(self, params=None):
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
        path = self._path(params or {})
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'top': []}
        r = repo_size_rows(info['root'], limit=int((params or {}).get('limit') or 20))
        r.update({'ok': bool(r.get('ok')), 'path': path, 'size': human_size(r.get('bytes') or 0)})
        return r

    def loc(self, params=None):
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        repo_root = (info or {}).get('root') or path
        root = os.path.abspath(path)
        if not os.path.isdir(root):
            return {'ok': False, 'why': '这个目录不在了：%s' % root, 'tracked': None, 'all': None}

        keep_libs = bool(p.get('libs'))
        names = []
        if info and os.path.isdir(repo_root):
            got = git(repo_root, 'ls-files', '-z', timeout=180)
            allnames = [x for x in (got.get('out') or '').split('\0') if x.strip()]
            rel = os.path.relpath(root, repo_root).replace('\\', '/')
            if rel in ('.', ''):
                names = allnames
            else:
                names = [x for x in allnames if x == rel or x.startswith(rel + '/')]
        scan_root = repo_root if names else root
        tracked = loc_scan(scan_root, names, keep_libs=keep_libs) if names else {
            'files': 0, 'lines': 0, 'byLang': [], 'top': [], 'skipped': 0,
            'jumped': [], 'cut': False, 'secs': 0}
        everything = None if p.get('fast') else loc_scan(root, None, keep_libs=keep_libs)
        return {'ok': True, 'path': path, 'root': root, 'repoRoot': repo_root,
                'isRepo': bool(info),
                'tracked': tracked, 'all': everything, 'libs': keep_libs,
                'exts': sorted(LOC_LANG.keys()),
                'skipDirs': sorted(LOC_SKIP_DIRS),
                'note': '按"一个文件多少行就算多少行"数的：不去空行、不剔注释。'
                        '只数代码，配置文件（json / ini / txt / md / yml）不算。'}

    def net_probe(self, params=None):
        path = self._path(params)
        info = repo_info(path)
        if not info or not info['remote']:
            return {'ok': False, 'why': '这个目录没有可探测的远端地址', 'cmd': 'git ls-remote --heads origin'}
        got = _exec([GIT, '-C', info['root'], 'ls-remote', '--heads', 'origin'],
                    timeout=25, label='问一下远端有哪些分支')
        heads = len([x for x in got['out'].splitlines() if x.strip()])
        return {'ok': got['ok'], 'ms': got['ms'], 'cmd': 'git ls-remote --heads origin',
                'host': info['host'], 'heads': heads, 'code': got['code'],
                'retried': got.get('retried') or 0, 'backend': got.get('backend') or '',
                'out': '\n'.join(got['out'].splitlines()[:10]),
                'why': '' if got['ok'] else (got.get('why') or got['out'][:300])}

    def _gh(self):
        global GH
        ts, cached = self._gh_cache
        if cached and time.time() - ts < 60:
            return cached
        found = local_tool('gh') or shutil.which('gh')
        if found:
            GH = found
        res = {'installed': bool(found), 'version': '', 'loggedIn': False, 'user': '',
               'why': '', 'path': found or ''}
        if found:
            v = run([GH, '--version'], timeout=8)
            res['version'] = (v['out'].splitlines() or [''])[0]
            res['broken'] = not v['ok']
            a = run([GH, 'auth', 'status'], timeout=10)
            txt, low = a['out'] or '', (a['out'] or '').lower()
            res['loggedIn'] = bool(a['ok'] and 'logged in' in low)
            m = re.search(r'account\s+(\S+)', txt)
            res['user'] = m.group(1).strip() if m else ''
            if not res['loggedIn']:
                _why = (txt or 'gh 说没登录（gh auth login 登一下）').strip()[:300]
                _hint = net_hint(txt)
                if _hint:
                    _why = '%s　→ %s（这一条拿不准，别急着重新登录 —— 推送用的是 git 自己的凭据）' \
                           % (_why, _hint)
                res['why'] = _why
        else:
            res['why'] = '这台机器上没有 gh（GitHub CLI）—— 有它才好管 PR / issue；装好再回来点一下'
        self._gh_cache = (time.time(), res)
        return res

    def gh(self, params=None):
        return self._gh()

    def ui_error(self, params=None):
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
        except Exception as e:
            return {'ok': False, 'why': '记不下来：%s' % e}

    def env_check(self, params=None):
        path = self._path(params or {})
        fresh = bool((params or {}).get('fresh'))
        c = _ENV_CACHE
        if not fresh and c.get('path') == path and c.get('data') \
                and time.time() - float(c.get('at') or 0) < 60:
            return c['data']
        refresh_tools()
        _d = read_install()
        if fresh or (_d and _d.get('done')
                     and time.time() - float(_d.get('at') or 0) < 180):
            self._gh_cache = (0.0, None)
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

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_gitv = pool.submit(run, [GIT, '--version'], timeout=15)
            f_idn = pool.submit(git_identity, path)
            f_gh = pool.submit(self._gh)
            f_probe = pool.submit(repo_probe, path)
            gitv = f_gitv.result()
            idn = f_idn.result()
            gh = f_gh.result()
            probe_info = f_probe.result()
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
        _px = git_proxy()
        _px_alive = proxy_alive(_px) if _px else None
        _sys_alive = None
        _px_txt = ''
        if _px:
            _px_txt = '｜走代理 %s（git 自己配的）' % _px
            if _px_alive is False:
                _px_txt += '，但这个端口连不上 —— 多半是代理软件没开（或者换了端口）'
        else:
            _sys_px, _sys_src = system_proxy()
            if _sys_px:
                _px_txt = ('｜%s设了 %s，但 git 不认它（git 只认自己的配置）'
                           '—— 要让 git 走代理得执行一次 git config --global http.proxy %s'
                           % (_sys_src, _sys_px, _sys_px))
                _sys_alive = proxy_alive(_sys_px)
                if _sys_alive is False:
                    _px_txt += '；而且这个端口现在也连不上'
        _pref = net_pref()
        items.append({
            'key': 'net',
            'state': 'warn' if (not online or _px_alive is False or _sys_alive is False) else 'ok',
            'label': '能不能连上 GitHub',
            'detail': ('能连上' if online else
                       '这次没探到 github.com（443）—— 只是 3 秒的探测，不代表推不上去')
                      + _px_txt
                      + ('｜回回都用 openssl 后端连（自动，不用你管）' if _pref else ''),
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
        what = str((params or {}).get('what') or '').strip()
        if what not in ('git', 'gh'):
            return {'ok': False, 'why': '只支持装 git 或 gh：%s' % what}
        pkg = 'Git.Git' if what == 'git' else 'GitHub.cli'
        label = 'Git' if what == 'git' else 'GitHub CLI'
        url = URL_GIT if what == 'git' else URL_GH
        found = local_tool(what) or shutil.which(what)
        if found and not str((params or {}).get('force') or ''):
            self._gh_cache = (0.0, None)
            return {'ok': True, 'started': False, 'already': True, 'installed': True,
                    'path': found, 'url': url,
                    'why': '%s 已经装好了（%s），不用再装。' % (label, found)}
        winget = shutil.which('winget')
        kind = 'winget' if str((params or {}).get('mode') or '') == 'winget' else 'portable'
        cur = read_install()
        if cur and not cur.get('done') and cur.get('what') == what and cur.get('log') \
                and (cur.get('kind') or 'winget') == kind:
            age = time.time() - float(cur.get('at') or 0)
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
            open(log, 'w', encoding='utf-8').close()
        except Exception:
            pass
        if str((params or {}).get('mode') or 'portable') != 'winget':
            mark_install(what, log=log, kind='portable')
            try:
                detach = 0
                if os.name == 'nt':
                    detach = 0x00000008 | 0x00000200
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
            except Exception as e:
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
        except Exception as e:
            opened = open_url(url)
            return {'ok': False, 'started': False, 'opened': bool(opened), 'url': url,
                    'why': '启动安装失败（%s）—— 已经帮你打开下载页，手动装一下。' % e}
        mark_install(what, log=log)
        print('[github] 开始装 %s → 日志：%s' % (label, log), flush=True)
        return {'ok': True, 'started': True, 'url': url, 'log': log,
                'why': '已经在装了。可能弹一个「是否允许」的窗口，点「是」。'
                       '下面会一直显示进度和日志，装完我会直接告诉你能点「登录 GitHub」了。'}

    def install_status(self, params=None):
        what = str((params or {}).get('what') or '').strip()
        d = read_install()
        if not d or (what and d.get('what') != what):
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
        if 'EXIT_FAIL' in text:
            phase, say = 'fail', '出错了'
        elif 'EXIT_OK' in text:
            phase, say, pct = 'done', '装好了', 100
        elif not finished:
            if phase == 'done':
                phase, say = 'run', say
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
        path = self._path(params or {})
        note = ensure_identity(path, force=True)
        return {'ok': bool(git_identity(path)['name']), 'identity': git_identity(path),
                'note': note or '已经有署名了，没动'}

    def open_url(self, params=None):
        return open_url(str((params or {}).get('url') or ''))

    def gh_login(self, params=None):
        refresh_tools()
        gh = local_tool('gh') or shutil.which('gh')
        if not gh:
            return {'ok': False, 'why': '还没装 gh —— 先点「帮我装 gh」', 'url': URL_GH}
        _help = run([gh, 'auth', 'login', '--help'], timeout=10)['out'] or ''
        flags = ['--hostname', 'github.com', '--git-protocol', 'https', '--web']
        has_clip = '--clipboard' in _help
        has_skip = '--skip-ssh-key' in _help
        if has_clip:
            flags.append('--clipboard')
        if has_skip:
            flags.append('--skip-ssh-key')
        flag_text = ' '.join(flags)
        if (params or {}).get('dry'):
            return {'ok': True, 'dry': True, 'ghPath': gh, 'flags': flags,
                    'clipboard': has_clip, 'skipSshKey': has_skip,
                    'cmd': '"%s" auth login %s' % (gh, flag_text)}

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
                subprocess.Popen('start "GitHub 登录（照窗口里的字做）" cmd /k %s' % line,
                                 shell=True)
            else:
                subprocess.Popen(['sh', '-c', 'x-terminal-emulator -e "%s auth login %s" '
                                              '|| gnome-terminal -- "%s auth login %s"'
                                              % (gh, flag_text, gh, flag_text)])
        except Exception as e:
            return {'ok': False, 'why': '打不开命令行窗口：%s' % e, 'url': URL_LOGIN}
        self._gh_cache = (0.0, None)
        return {'ok': True, 'window': True, 'ghPath': gh, 'clipboard': has_clip,
                'help': '窗口里我把步骤写在最上面了：屏幕上给一个 8 位代码'
                        + ('（已经帮你复制到剪贴板）' if has_clip else '') +
                        ' → 浏览器自动打开 → 粘代码点同意 → 看到 "Logged in as 你" 就成了。'
                        '窗口不会一闪就没（出错了会停在窗口里给你看）。'
                        '实在不想弄也没关系：推送不受影响。'}

    OWN_JUNK = ('_how.py', '_how.txt', '_probe.py', '_probe.txt', '_tmp_probe.py')

    def tidy(self, params=None):
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
            if not got.get('why'):
                got['why'] = (got['out'] or '').strip().splitlines()[:1]
                got['why'] = got['why'][0] if got['why'] else '退出码 %s' % got['code']
                hint = net_hint(got.get('out') or '')
                if hint:
                    got['why'] = '%s　原始报错：%s' % (hint, got['why'])
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

    def _step(self, cwd, argv, label, timeout=180):
        got = _exec(argv, cwd=cwd, timeout=timeout, label=label)
        got['label'] = label
        if got.get('retried'):
            got['label'] = '%s（网络抖了一下，自动重试 %d 次才通，用的是%s后端）' % (
                label, got['retried'],
                'openssl' if got.get('backend') == 'openssl' else '默认')
        repo_cache_clear(cwd)
        print('[github] %s → %s（%d ms，退出码 %s）'
              % (label, got['cmd'], got['ms'], got['code']), flush=True)
        return got

    def _upstream_verified(self, root, upstream=""):
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
        bad = [s for s in steps if not s.get("ok") and not s.get("soft")]
        why = ''
        if bad:
            first = bad[0]
            lines = (first.get('out') or '').splitlines() or ['没跑成']
            why = first.get('why') or lines[0]
            if not first.get('why'):
                hint = net_hint(first.get('out') or '')
                if hint:
                    why = '%s　→ %s' % (why, hint)
            if 'push' in (first.get('cmd') or '') and why:
                why = ('%s　（这次保存的版本已经在本地了，网络好了再点一次「备份到云端」就行，'
                       '不会重复上传）' % why)
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

    def timeline(self, params=None):
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
        track = info.get('track') or info['upstream']
        with ThreadPoolExecutor(max_workers=6) as pool:
            f_rows = pool.submit(git_log_rows, root, limit + 1, rev)
            f_pushed = pool.submit(_upstream_hashes, root, track)
            f_branch = pool.submit(branch_rows, root)
            f_total = pool.submit(_rev_count, root, 'HEAD')
            f_uptotal = (pool.submit(_rev_count, root, track) if track else None)
            f_tags = pool.submit(tag_rows, root)
            rows, _ = f_rows.result()
            pushed, capped = f_pushed.result()
            local, remote = f_branch.result()
            total = f_total.result()
            up_total = f_uptotal.result() if f_uptotal else 0
            tags = f_tags.result()
        more = len(rows) > limit
        rows = rows[:limit]
        for r in rows:
            r['pushed'] = bool(pushed) and r['hash'] in pushed
        for i, r in enumerate(rows):
            r['ver'] = ('V-%d' % (total - i)) if total else ''
        return {'ok': True, 'path': path, 'root': root, 'head': info['branch'],
                'detached': info['detached'], 'upstream': info['upstream'],
                'track': track,
                'ahead': info['ahead'], 'behind': info['behind'],
                'commits': rows, 'more': more, 'branches': local, 'remoteBranches': remote,
                'tags': tags, 'pushedKnown': bool(pushed), 'capped': capped,
                'total': total, 'upstreamTotal': up_total,
                'ver': ('V-%d' % total) if total else '',
                'cloudVer': ('V-%d' % up_total) if up_total else '',
                'cmd': 'git log --oneline --graph --decorate -n %d' % limit,
                'at': now_text()}

    def cloud_versions(self, params=None):
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
        target = info.get('track') or info['upstream']
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
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_rows = pool.submit(git_log_rows, root, limit + 1, target)
            f_total = pool.submit(_rev_count, root, target)
            f_local = pool.submit(git, root, 'rev-list', 'HEAD', timeout=30)
            rows, _ = f_rows.result()
            total = f_total.result()
            local_heads = (f_local.result() or {}).get('out', '').splitlines()
        more = len(rows) > limit
        rows = rows[:limit]
        for i, r in enumerate(rows):
            r['ver'] = ('V-%d' % (total - i)) if total else ''
            r['pushed'] = True
        local_only = set()
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

    def switch_branch(self, params=None):
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
            info = repo_info(path) or info
            ver = self._upstream_verified(root, info.get('upstream') or '')
            steps.append({'ok': bool(ver.get('same') is not False), 'ms': 0,
                          'cmd': '(核对) git rev-parse HEAD @{u}',
                          'label': '④ 核对：远端和本地是不是同一个提交',
                          'out': ver.get('msg') or '',
                          'why': '' if ver.get('same') else (ver.get('msg') or '')})
        if len(steps) == 1 and not fetch['ok']:
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
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'steps': []}
        root = info['root']
        msg = str(p.get('message') or p.get('arg') or '').strip()
        if not msg:
            return {'ok': False, 'why': '提交标题不能空着（写一句你能看懂的话）', 'steps': []}
        body = str(p.get('body') or '').strip()
        commit_argv = ['git', 'commit', '-m', msg] + (['-m', body] if body else [])
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

    def restore(self, params=None):
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

    def delete_commit(self, params=None):
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
            ensure_identity(root)
            par = (git(root, 'rev-list', '--parents', '-n', '1', sha)['out'] or '').split()
            argv = ['git', 'revert', '--no-edit'] + (['-m', '1'] if len(par) > 2 else []) + [sha]
            if dirty:
                steps.append(self._step(root, ['git', 'stash', 'push', '-u', '-m',
                                               'moss 撤销版本前备份 ' + now_text()],
                                        '先把当前 %d 个改动收起来备份' % info['changeCount'], 60))
            rev = self._step(root, argv, '追加一条「撤销 %s」的版本' % short, 150)
            steps.append(rev)
            if not rev['ok']:
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

        if not git(root, 'rev-parse', '--verify', '--quiet', sha + '^')['ok']:
            return {'ok': False, 'steps': [],
                    'why': '%s 是这个仓库最早的版本，删掉它等于把整段历史抹了 —— '
                           '这种情况另建一个仓库、把要留的文件搬过去更稳' % short}

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

    def stashes(self, params=None):
        p = params or {}
        path = self._path(p)
        info = repo_info(path)
        if not info:
            return {'ok': False, 'why': '这不是一个 git 仓库：%s' % path, 'items': []}
        root = info['root']
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

    def mirror(self, params=None):
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
            repo_cache_clear(root)
            after = repo_info(path, ttl=0) or {}
            br = after.get('branch') or ''
            if (remote == 'origin' and not after.get('upstream') and br
                    and not after.get('detached')
                    and git(root, 'rev-parse', '--verify', '--quiet',
                            'origin/%s^{commit}' % br)['ok']):
                steps.append(self._step(
                    root, ['git', 'branch', '--set-upstream-to=origin/' + br, br],
                    '把 %s 和 origin/%s 关联起来（以后"待上传"才数得准）' % (br, br), 30))
        else:
            return {'ok': False, 'steps': [],
                    'why': '没给镜像方式（gh_create / local_clone / add_remote）'}
        res = self._finish(path, steps)
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

PARALLEL_METHODS = frozenset((
    'boot', 'actions', 'snapshot', 'timeline', 'cloud_versions', 'show_commit',
    'gh', 'disks', 'net_probe', 'remote_repo', 'stashes', 'env_check',
    'install_status', 'push_check', 'bigfiles', 'loc', 'ignore', 'sync_log',
    'recent', 'settings', 'job_state',
))

class _StdoutToProgress(object):
    def __init__(self, real):
        self._real = real

    def write(self, s):
        text = str(s or '')
        for ln in text.splitlines():
            if ln.strip():
                try:
                    _live(ln)
                except Exception:
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
    def __init__(self):
        self.core = Core()
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._out = sys.stdout
        sys.stdout = _StdoutToProgress(self._out)

    def send(self, obj):
        with self._send_lock:
            self._out.write(json.dumps(obj, ensure_ascii=False) + '\n')
            self._out.flush()

    def _answer(self, mid, fn, params):
        try:
            result = fn(params)
            self.send({'id': mid, 'ok': True, 'result': result})
            return result
        except Exception as e:
            self.send({'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
            return None

    def loop(self):
        pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix='moss-gh')
        try:
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
                if method in PARALLEL_METHODS:
                    pool.submit(self._answer, mid, fn, msg.get('params'))
                else:
                    with self._lock:
                        self._answer(mid, fn, msg.get('params'))
        finally:
            pool.shutdown(wait=False)

def run_window(path=''):
    import webview

    core = Core(path)

    api = build_api(core)()
    webview.create_window(TITLE, url=UI, js_api=api,
                          width=1180, height=800, min_size=(900, 620))
    webview.start()
    return 0

def build_api(core):
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
    try:
        api = build_api(core)()
    except Exception:
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
    except Exception:
        pass

def cli(action, path, arg='', extra=None):
    core = Core()
    if action == 'tidy':
        got = core.tidy({'path': resolve_path(path)})
        print('[github] 删了：%s' % ('、'.join(got['removed']) or '（没有要删的）'))
        if got['failed']:
            print('[github] 没删成：%s' % '、'.join(got['failed']))
        write_result(got)
        return 0 if got['ok'] else 1
    if action == 'list_methods':
        names = sorted([n for n in dir(core)
                        if not n.startswith('_') and callable(getattr(core, n, None))])
        print('[github] Core 上可调用的方法（%d 个）：' % len(names))
        print('  ' + ' '.join(names))
        need = ['boot', 'actions', 'snapshot', 'timeline', 'cloud_versions', 'show_commit',
                'run_action', 'file_op', 'gh', 'set_path', 'forget_path', 'browse', 'disks',
                'net_probe', 'remote_repo', 'mirror', 'stashes', 'drop_stash',
                'delete_commit', 'env_check', 'install_tool', 'install_status',
                'fix_identity', 'open_url', 'gh_login',
                'job_start', 'job_state', 'job_cancel',
                'push_check', 'bigfiles', 'shield', 'ignore', 'sync_log']
        missing = [m for m in need if not callable(getattr(core, m, None))]
        print('[github] 界面用到但缺失的：%s' % (' '.join(missing) if missing else '（一个都不缺）'))
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
