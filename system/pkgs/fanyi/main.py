# -*- coding: utf-8 -*-
"""快捷翻译 —— 一份界面两种跑法（照 `system/pkgs/skill/` 的样板写）。

    moss :fanyi                不带参数 → 自己开一个窗口（不依赖 moss 的界面）
    在 moss 界面里点「运行」     → 内嵌到 moss 的「界面」选项卡里跑

界面是网页（`ui/index.html` + Vue 3），靠 `ui/moss-embed.js` 垫片自动分流。翻译、缓存、
剪贴板这些活儿**全在 Python 这边**，前端只负责显示。

和从老项目移植来的那一版相比，这一版有两点根本改动（详见 AGENT.md）：
  1. **只用标准库**：宿主自带运行时是隔离的，装不了第三方库 —— 原来的 `googletrans` /
     `pyperclip` / `pynput` 换成 `urllib`（Google 免费接口）/ `ctypes`（Windows 剪贴板）。
     代价是**全局「双击 Ctrl」热键没了**（那要键盘钩子=第三方库）；改用界面上的
     读剪贴板 / 复制译文，内嵌到 moss 后同样顺手。
  2. **界面从 Tk 换成网页**（契约 §4.2：「要界面就把界面写成网页，别用 Tk 写新包」）。

内嵌模式约定（`V-51`）：宿主给 `MOSS_UI_EMBED=1`，这时**别开窗口**，改成在 stdin/stdout
上说话，一行一个 JSON **对象**；收到 `{"id":1,"method":"translate","params":{...}}`
就回 `{"id":1,"ok":true,"result":{...}}`。宿主自己的横幅是 `[执行] / [目录]` 那种
**数组样子的行**，界面那侧只认 `{` 开头的行，两边不会串。
"""
import ctypes
import html
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, 'ui', 'index.html')
TITLE = '快捷翻译'

# 宿主注入的插件专属数据目录（= user_data/state/fanyi）；没注入时兜底到 MOSS_HOME 下
DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.path.join(os.environ.get('MOSS_HOME') or os.path.expanduser('~'),
                            'user_data', 'state', 'fanyi'))
CACHE_DIR = os.environ.get('MOSS_PLUGIN_CACHE_DIR') or os.path.join(DATA_DIR, 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'translation_cache.jsonl')
HISTORY_LIMIT = 200

# 「保留历史记录」开关（界面右上角那个开关）：持久化在 SETTINGS_FILE。
#   开 = 照旧：翻译完写缓存、历史里能看到，下次同样的句子直接命中缓存；
#   关 = 新翻译**不落盘**（连缓存也不写），每次重新联网翻；已有的历史还在，可手动删。
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
_keep_history = True

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) moss:fanyi'

#: 界面下拉里能选的目标语言（值 = Google 用的代码）
TARGETS = [
    {'value': 'auto', 'label': '自动（中↔英）'},
    {'value': 'zh-CN', 'label': '中文（简体）'},
    {'value': 'zh-TW', 'label': '中文（繁体）'},
    {'value': 'en', 'label': 'English'},
    {'value': 'ja', 'label': '日本語'},
    {'value': 'ko', 'label': '한국어'},
    {'value': 'fr', 'label': 'Français'},
    {'value': 'de', 'label': 'Deutsch'},
    {'value': 'es', 'label': 'Español'},
    {'value': 'ru', 'label': 'Русский'},
]


def _who():
    return 'Python（pid %d）' % os.getpid()


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------- 本地缓存（JSON 行）
_cache = {}        # key -> record（含 original / target / translated / source / at）
_history = []      # 最近记录，新的在前（给界面看）


def _key(text, target):
    return text + '\x1f' + target


def _guess_lang(text):
    """粗判语种：优先假名（日语）、谚文（韩语）、西里尔（俄语），最后才认汉字。

    ★ 现在它也用于 `auto` 目标（中文→英文 / 其他→中文），所以必须**扫完再下结论**：
      日语文本常夹大量汉字，按首字符判会把「日本語」当成中文。
    """
    has_kana = has_hangul = has_cjk = has_cyrillic = False
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF:
            has_kana = True
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            has_hangul = True
        elif 0x4E00 <= o <= 0x9FFF:
            has_cjk = True
        elif 0x0400 <= o <= 0x04FF:
            has_cyrillic = True
    if has_kana:
        return 'ja'
    if has_hangul:
        return 'ko'
    if has_cyrillic:
        return 'ru'
    if has_cjk:
        return 'zh-CN'
    return 'en'


def cache_load():
    """从磁盘读缓存（一行一条 JSON）。返回加载条数。"""
    global _cache, _history
    _cache, _history = {}, []
    if not os.path.isfile(CACHE_FILE):
        return 0
    n = 0
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                src, tgt, dst = rec.get('original'), rec.get('target'), rec.get('translated')
                if not (src and tgt and dst):
                    continue
                rec.setdefault('source', '')
                rec.setdefault('at', '')
                _cache[_key(src, tgt)] = rec
                _history.append({'src': src, 'dst': dst, 'target': tgt,
                                 'at': rec.get('at', '')})
                n += 1
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 读缓存失败：%s' % e, flush=True)
        return 0
    _history = _history[-HISTORY_LIMIT:][::-1]     # 文件是追加序 → 反转成新在前
    return n


def cache_store(original, target, translated, source):
    rec = {'original': original, 'target': target, 'translated': translated,
           'source': source or '', 'at': _now()}
    if not _keep_history:
        return rec            # 不保留历史：这次结果照用，但不落盘、也不进历史
    _cache[_key(original, target)] = rec
    _history.insert(0, {'src': original, 'dst': translated, 'target': target,
                        'at': rec['at']})
    del _history[HISTORY_LIMIT:]
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)               # 懒建：真写才建目录
        with open(CACHE_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 写缓存失败：%s' % e, flush=True)
    return rec


def cache_clear():
    global _cache, _history
    n = len(_cache)
    _cache, _history = {}, []
    try:
        if os.path.isfile(CACHE_FILE):
            os.remove(CACHE_FILE)
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 删缓存失败：%s' % e, flush=True)
    return n


def cache_save():
    """把内存里的缓存整体写回文件（删单条 / 清空之后用）。返回写了几条。

    ★ 为什么不"从文件里删那一行"：文件是 JSON 行追加出来的，同一个 key 可能有多行，
    按行删容易漏；整篇重写最稳（数据量本来就小）。
    """
    global _cache
    recs = list(_cache.values())
    try:
        if not recs:
            if os.path.isfile(CACHE_FILE):
                os.remove(CACHE_FILE)
            return 0
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        os.replace(tmp, CACHE_FILE)
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 写缓存失败：%s' % e, flush=True)
    return len(recs)


def history_remove(src, target=''):
    """删掉一条历史记录（连带删掉它的缓存，重启不会回来）。返回删了几条。

    按 (原文, 目标语言) 定位 —— 和缓存的 key 一致，所以删历史 = 真把缓存删了。
    """
    global _history
    src = (src or '').strip()
    target = (target or '').strip()
    if not src:
        return 0
    if target:
        keys = [_key(src, target)]
    else:
        keys = [k for k in list(_cache) if k.startswith(src + '\x1f')]
    n = 0
    for k in keys:
        if _cache.pop(k, None) is not None:
            n += 1
    _history = [h for h in _history
                if not ((h.get('src') or '') == src
                        and (not target or (h.get('target') or '') == target))]
    if n:
        cache_save()
    return n


# ---------------------------------------------------------------- 设置（保留历史开关）
def _settings_load():
    """读设置（现在只有「保留历史」）。文件不在 / 读坏 → 默认开。"""
    global _keep_history
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _keep_history = bool(data.get('keep_history', True))
    except Exception:                                                   # noqa: BLE001
        _keep_history = True


def _settings_save():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'keep_history': _keep_history, 'updated': _now()}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 记设置失败：%s' % e, flush=True)


def set_keep_history(on):
    """切换「保留历史记录」并落盘。返回切换后的状态。"""
    global _keep_history
    _keep_history = bool(on)
    _settings_save()
    print('[fanyi] 保留历史记录：%s' % ('开' if _keep_history else '关'), flush=True)
    return _keep_history


# ---------------------------------------------------------------- 剪贴板（ctypes / Windows）
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _clipboard_ready():
    if os.name != 'nt':
        return False
    try:
        import ctypes                                                   # noqa: F401
        return True
    except Exception:                                                   # noqa: BLE001
        return False


def clipboard_get():
    """读剪贴板纯文本。返回 (text, err)。"""
    if not _clipboard_ready():
        return '', '这个平台没有 Windows 剪贴板'
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    for _ in range(5):                       # 剪贴板偶尔被别的程序占着，重试几次
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return '', '剪贴板被占用，读不到'
    try:
        h = u.GetClipboardData(_CF_UNICODETEXT)
        if not h:
            return '', '剪贴板里没有文本'
        p = k.GlobalLock(h)
        if not p:
            return '', '剪贴板数据锁定失败'
        try:
            return ctypes.wstring_at(p), None
        finally:
            k.GlobalUnlock(h)
    except Exception as e:                                              # noqa: BLE001
        return '', '%s' % e
    finally:
        u.CloseClipboard()


def clipboard_set(text):
    """把文本写进剪贴板。返回 (ok, err)。"""
    if not _clipboard_ready():
        return False, '这个平台没有 Windows 剪贴板'
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    text = str(text)
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    h = k.GlobalAlloc(_GMEM_MOVEABLE, size)
    if not h:
        return False, '分配剪贴板内存失败'
    p = k.GlobalLock(h)
    if not p:
        k.GlobalFree(h)
        return False, '锁剪贴板内存失败'
    ctypes.memmove(p, buf, size)
    k.GlobalUnlock(h)
    for _ in range(5):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        k.GlobalFree(h)
        return False, '剪贴板被占用，写不进去'
    try:
        u.EmptyClipboard()
        if not u.SetClipboardData(_CF_UNICODETEXT, h):
            return False, '写入剪贴板失败'
        return True, None
    except Exception as e:                                              # noqa: BLE001
        return False, '%s' % e
    finally:
        u.CloseClipboard()


# ---------------------------------------------------------------- 翻译（多免费接口 + 自动切换）
# Google 公共免费接口 `translate.googleapis.com/translate_a/single` 现在对同一出口 IP
# 限流很严，经常直接 429。以前只有这一条通道，429 就等于整个快捷翻译不可用。
# 现在：一条不行换下一条；并把**最后一次成功的通道**写盘，下次优先用它。
#   google      : 质量最好，默认优先
#   google_c5   : Google 老入口 clients5.google.com，和主接口不是同一个域名
#   youdao      : 有道免密 Demo 接口，适合中文/英文方向兜底
#   mymemory    : MyMemory 免费接口，无 key，支持语言较多，放最后兜底
# 公共接口都有速率限制，不能保证 100%；但多个一起上，偶发 429 不会直接瘫痪。
GT_URL = 'https://translate.googleapis.com/translate_a/single'
GT_C5_URL = 'https://clients5.google.com/translate_a/t'
YDL_URL = 'https://aidemo.youdao.com/trans'
MYM_URL = 'https://api.mymemory.translated.net/get'

#: 有道语言代码和常用代码的映射
YD_LANG = {
    'zh': 'zh-CHS', 'zh-CN': 'zh-CHS', 'zh-TW': 'zh-CHT',
    'en': 'en', 'ja': 'ja', 'ko': 'ko', 'fr': 'fr', 'de': 'de',
    'es': 'es', 'ru': 'ru',
}

PROVIDER_ORDER = ('google', 'google_c5', 'youdao', 'mymemory')
PROVIDERS = {
    'google': {'name': 'Google', 'fn': None},
    'google_c5': {'name': 'Google 备用', 'fn': None},
    'youdao': {'name': '有道翻译', 'fn': None},
    'mymemory': {'name': 'MyMemory', 'fn': None},
}
PROVIDER_FILE = os.path.join(DATA_DIR, 'provider.json')
_PROVIDER = {'loaded': False, 'preferred': ''}


def _fetch_json(url, params=None, payload=None, timeout=15):
    """请求并解析一个 JSON 接口；标准库 urllib 就够。"""
    if params:
        sep = '&' if '?' in url else '?'
        url = url + sep + urllib.parse.urlencode(params)
    headers = {'User-Agent': UA}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode('utf-8', 'replace'))


def _err_text(exc):
    """异常压成一句话，别把一整页 HTML 塞进日志。"""
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP %s %s' % (exc.code, exc.reason)
    return (str(exc) or exc.__class__.__name__).replace('\n', ' ')[:160]


def _provider_load():
    """读上次成功的通道；文件不在/读坏/通道已删都退回第一顺位。"""
    if _PROVIDER['loaded']:
        return
    _PROVIDER['loaded'] = True
    try:
        with open(PROVIDER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        key = str(data.get('preferred') or '')
        if key in PROVIDERS:
            _PROVIDER['preferred'] = key
    except Exception:                                                   # noqa: BLE001
        pass


def _provider_save(key):
    """记住最后一次成功的通道。只在真变了的时候写盘。"""
    if not key or key not in PROVIDERS or _PROVIDER.get('preferred') == key:
        return
    _PROVIDER['preferred'] = key
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = PROVIDER_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'preferred': key, 'updated': _now()}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, PROVIDER_FILE)
    except Exception as e:                                              # noqa: BLE001
        print('[fanyi] 记翻译通道失败：%s' % e, flush=True)


def _provider_keys():
    """尝试顺序：上次成功的排第一，其余按固定顺序补在后面。"""
    _provider_load()
    pref = _PROVIDER.get('preferred') or PROVIDER_ORDER[0]
    if pref not in PROVIDERS:
        pref = PROVIDER_ORDER[0]
    return [pref] + [k for k in PROVIDER_ORDER if k != pref]


def _gt_extract(data):
    segs = (data[0] if isinstance(data, list) and data else None) or []
    translated = ''.join(s[0] for s in segs if s and s[0])
    detected = data[2] if isinstance(data, list) and len(data) > 2 and isinstance(data[2], str) else ''
    return translated, detected


def _c5_extract(data):
    """Google `clients5` 的返回格式有两种：
        · 明确 source：`["Hello"]`
        · source=auto：`[["你好","en"]]`
    """
    if isinstance(data, str):
        return data, ''
    if isinstance(data, list):
        if data and isinstance(data[0], str):
            return ''.join(str(x) for x in data if isinstance(x, str)), ''
        parts, detected = [], ''
        for item in data:
            if not isinstance(item, (list, tuple)) or not item:
                continue
            if isinstance(item[0], str):
                parts.append(item[0])
            if len(item) > 1 and isinstance(item[1], str) and not detected:
                detected = item[1]
        return ''.join(parts), detected
    if isinstance(data, dict):
        for key in ('translation', 'translatedText', 'text'):
            if isinstance(data.get(key), str):
                return data[key], ''
    return '', ''


def _prov_google(text, source, target):
    data = _fetch_json(GT_URL, params={
        'client': 'gtx', 'sl': source or 'auto', 'tl': target,
        'dt': 't', 'q': text})
    return _gt_extract(data)


def _prov_google_c5(text, source, target):
    data = _fetch_json(GT_C5_URL, params={
        'client': 'dict-chrome-ex', 'sl': source or 'auto',
        'tl': target, 'q': text})
    return _c5_extract(data)


def _prov_youdao(text, source, target):
    """有道免密 Demo 接口。不支持的方向会回 errorCode，外层继续换通道。"""
    data = _fetch_json(YDL_URL, params={
        'q': text,
        'from': 'auto' if (not source or source == 'auto') else YD_LANG.get(source, source),
        'to': YD_LANG.get(target, target),
    })
    code = str(data.get('errorCode') or '0')
    if code not in ('0', 'None'):
        raise RuntimeError('有道返回错误码 %s' % code)
    tr = data.get('translation') or []
    if isinstance(tr, str):
        tr = [tr]
    translated = ''.join(str(x) for x in tr if isinstance(x, str))
    if not translated.strip():
        raise RuntimeError('有道没返回译文')
    l = str(data.get('l') or data.get('type') or '')
    detected = l.split('2', 1)[0] if '2' in l else ''
    return translated, detected


def _prov_mymemory(text, source, target):
    """MyMemory 免费接口：无 key，但单次长度/每日配额有限；放最后兜底。"""
    if len(text) > 500:
        raise RuntimeError('文本超过 MyMemory 免费接口长度限制')
    src = 'autodetect' if (not source or source == 'auto') else source
    data = _fetch_json(MYM_URL, params={'q': text,
                                        'langpair': '%s|%s' % (src, target)})
    rd = data.get('responseData') or {}
    translated = rd.get('translatedText') or ''
    if isinstance(translated, str):
        translated = html.unescape(translated)
    if not translated.strip():
        raise RuntimeError('MyMemory 没返回译文')
    detected = str(rd.get('detectedLanguage') or '')
    return translated, detected


PROVIDERS['google']['fn'] = _prov_google
PROVIDERS['google_c5']['fn'] = _prov_google_c5
PROVIDERS['youdao']['fn'] = _prov_youdao
PROVIDERS['mymemory']['fn'] = _prov_mymemory


def do_translate(text, target='auto'):
    """翻译一段文字。返回给界面用的现成结果（含缓存命中标记）。

    ★ 多通道：按 `_provider_keys()` 依次试，一个成功就记住它；全失败才回错误。
    """
    text = (text or '').strip()
    if not text:
        return {'ok': False, 'why': '没有要翻译的文字'}
    if len(text) > 5000:
        return {'ok': False, 'why': '一次最多 5000 字，太长了'}
    target = (target or 'auto').strip()

    source_hint = _guess_lang(text)
    if target == 'auto':
        # 本地粗判：中文 → 英文，其余 → 中文。和原版行为一致，但省掉一次
        # Google 检测请求——原来的 429 有一部分就是 auto 模式每次发两次请求造成的。
        target = 'en' if str(source_hint).lower().startswith('zh') else 'zh-CN'

    hit = _cache.get(_key(text, target)) if _keep_history else None
    if hit:
        return {'ok': True, 'source': hit.get('source') or source_hint or 'auto',
                'target': target, 'original': text, 'translated': hit['translated'],
                'cached': True, 'at': hit.get('at') or '', 'who': _who(),
                'provider': 'cache', 'provider_name': '本地缓存'}

    errors = []
    for key in _provider_keys():
        spec = PROVIDERS[key]
        try:
            translated, detected = spec['fn'](text, 'auto', target)
            if not (translated or '').strip():
                raise RuntimeError('没返回译文')
            source = detected or source_hint or 'auto'
            _provider_save(key)
            rec = cache_store(text, target, translated, source)
            return {'ok': True, 'source': source, 'target': target,
                    'original': text, 'translated': translated, 'cached': False,
                    'at': rec['at'], 'who': _who(),
                    'provider': key, 'provider_name': spec['name']}
        except Exception as e:                                          # noqa: BLE001
            errors.append('%s：%s' % (spec['name'], _err_text(e)))
    return {'ok': False,
            'why': '网络翻译失败（所有免费通道都试过了）：' + '；'.join(errors)}


def cache_info_payload():
    return {'ok': True, 'count': len(_cache), 'path': CACHE_FILE,
            'dir': CACHE_DIR, 'history': _history[:30], 'who': _who(),
            'keep': _keep_history, 'limit': HISTORY_LIMIT}


# ---------------------------------------------------------------- 全局热键（ctypes 低级键盘钩子）
# 自带运行时是隔离的、装不了 pynput（键盘钩子=第三方库），所以这里直接用 Windows API：
#   · 用 `SetWindowsHookEx(WH_KEYBOARD_LL)` 监听**任意键**（Ctrl 是修饰键，RegisterHotKey 认不了双击）；
#   · 用 `SendInput` 模拟 Ctrl+A / Ctrl+X / Ctrl+V，复刻原来"选中→翻译→自动粘回"。
# 只用标准库的 ctypes，Windows 专用。
_WIN32 = os.name == 'nt'

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_A, VK_X, VK_V = 0x41, 0x58, 0x56
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
DOUBLE_CLICK_INTERVAL = 0.3        # 两次 Ctrl 间隔小于它算"双击"
COOLDOWN_SECONDS = 1.0             # 触发后冷却，别连着翻

if _WIN32:
    from ctypes import wintypes as _wt

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [('vkCode', _wt.DWORD), ('scanCode', _wt.DWORD),
                    ('flags', _wt.DWORD), ('time', _wt.DWORD),
                    ('dwExtraInfo', ctypes.c_void_p)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', _wt.LONG), ('dy', _wt.LONG), ('mouseData', _wt.DWORD),
                    ('dwFlags', _wt.DWORD), ('time', _wt.DWORD),
                    ('dwExtraInfo', ctypes.c_void_p)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', _wt.WORD), ('wScan', _wt.WORD), ('dwFlags', _wt.DWORD),
                    ('time', _wt.DWORD), ('dwExtraInfo', ctypes.c_void_p)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg', _wt.DWORD), ('wParamL', _wt.WORD), ('wParamH', _wt.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [('ki', _KEYBDINPUT), ('mi', _MOUSEINPUT), ('hi', _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [('type', _wt.DWORD), ('u', _INPUTUNION)]

    _LOWLEVELPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                       _wt.WPARAM, _wt.LPARAM)

    def _set_prototypes():
        """★ 必须声明 64 位类型，否则句柄/指针被截成 32 位 ——

        实测踩过：不声明时 `SetWindowsHookExW` 返回的 `HHOOK` 被截断，
        `UnhookWindowsHookEx` 拿着半个句柄卸不掉 → 残留一个死钩子把**整机键盘卡死**。
        这些 API 的返回值/参数里 handles/pointers 都是指针宽度，一律显式声明。"""
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        u.SetWindowsHookExW.restype = _wt.HHOOK
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, _LOWLEVELPROC,
                                        _wt.HINSTANCE, _wt.DWORD]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        u.CallNextHookEx.argtypes = [_wt.HHOOK, ctypes.c_int, _wt.WPARAM, _wt.LPARAM]
        u.UnhookWindowsHookEx.restype = _wt.BOOL
        u.UnhookWindowsHookEx.argtypes = [_wt.HHOOK]
        u.GetMessageW.restype = ctypes.c_int
        u.GetMessageW.argtypes = [ctypes.POINTER(_wt.MSG), _wt.HWND, _wt.UINT, _wt.UINT]
        u.TranslateMessage.restype = _wt.BOOL
        u.TranslateMessage.argtypes = [ctypes.POINTER(_wt.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t
        u.DispatchMessageW.argtypes = [ctypes.POINTER(_wt.MSG)]
        u.PostThreadMessageW.restype = _wt.BOOL
        u.PostThreadMessageW.argtypes = [_wt.DWORD, _wt.UINT, _wt.WPARAM, _wt.LPARAM]
        u.SendInput.restype = _wt.UINT
        u.SendInput.argtypes = [_wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        k.GetCurrentThreadId.restype = _wt.DWORD
        k.GetCurrentThreadId.argtypes = []

    _set_prototypes()


def _send_key(vk, up=False):
    if not _WIN32:
        return
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=0,
                           dwFlags=(KEYEVENTF_KEYUP if up else 0), time=0, dwExtraInfo=None)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _press_combo(mod_vk, key_vk):
    """按一下 Ctrl+X 这种组合（按下 modifier → 按下键 → 松开键 → 松开 modifier）。"""
    _send_key(mod_vk)
    _send_key(key_vk)
    _send_key(key_vk, up=True)
    _send_key(mod_vk, up=True)


class Hotkey:
    """全局热键：双击 Ctrl 触发 `on_trigger()`。

    ★ 架构（踩过坑后的定版）：
      · **装钩子 + 消息循环**在专用线程 `_thread` 里（低级钩子要求装它的线程自己抽消息）；
      · **真正干活的 `on_trigger`**在常驻工作线程 `_worker` 里，靠队列 `_q` 派活 ——
        钩子回调必须在毫秒级返回（超时系统会把钩子摘掉、甚至卡住键盘），
        开线程/发网络这种慢活儿**绝不能**放回调里做。
      · 卸载放在 `finally`，并且**返回值要检查**（`UnhookWindowsHookEx` 失败=死钩子）。
    """

    def __init__(self, on_trigger):
        self._on = on_trigger
        self._running = False
        self._thread = None            # 装钩子 + 消息循环
        self._worker = None            # 消费触发、执行 on_trigger
        self._q = queue.Queue()
        self._hook = None
        self._proc = None
        self._tid = 0
        self._last_ctrl = 0.0
        self._last_fire = 0.0
        self._busy = False
        self._unhook_ok = None         # 上次卸载成功没有（探针要断言）

    def feed_ctrl(self, injected=False):
        """喂一次"Ctrl 按下了"。返回 True 表示构成双击、该触发。

        （拆出来是为了能单测：不走真钩子也能验双击逻辑。）"""
        if injected:
            return False
        now = time.time()
        if self._busy or (now - self._last_fire) < COOLDOWN_SECONDS:
            self._last_ctrl = now
            return False
        if (now - self._last_ctrl) < DOUBLE_CLICK_INTERVAL:
            self._last_ctrl = 0.0
            return True
        self._last_ctrl = now
        return False

    def _proc_impl(self, nCode, wParam, lParam):
        """钩子回调：只做"判定 + 入队"，立刻返回。"""
        try:
            if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if kb.vkCode in (VK_LCONTROL, VK_RCONTROL, VK_CONTROL):
                    if self.feed_ctrl(injected=bool(kb.flags & LLKHF_INJECTED)):
                        self._busy = True              # 立刻占位，防连击
                        self._last_fire = time.time()
                        self._q.put(1)
        except Exception:                                               # noqa: BLE001
            pass
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run_worker(self):
        while self._running:
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:                        # 收到收工信号
                break
            try:
                self._on()
            except Exception as e:                                      # noqa: BLE001
                print('[fanyi] 热键动作出错：%s' % e, flush=True)
            finally:
                self._busy = False

    def _run_hook(self):
        user32 = ctypes.windll.user32
        try:
            self._proc = _LOWLEVELPROC(self._proc_impl)
            self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            if not self._hook:
                print('[fanyi] 装键盘钩子失败（错误码 %d）' % ctypes.get_last_error(),
                      flush=True)
                self._running = False
                return
            print('[fanyi] 全局热键已开启：双击 Ctrl 翻译选中文字', flush=True)
            msg = _wt.MSG()
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            # ★ 无论如何都要把钩子摘掉 —— 摘不掉就会留个死钩子把整机键盘卡住
            if self._hook:
                self._unhook_ok = bool(user32.UnhookWindowsHookEx(self._hook))
                if not self._unhook_ok:
                    print('[fanyi] 警告：卸键盘钩子失败（错误码 %d）'
                          % ctypes.get_last_error(), flush=True)
                self._hook = None

    def start(self):
        if self._running:
            return {'ok': True, 'running': True, 'msg': '已经在跑'}
        if not _WIN32:
            return {'ok': False, 'running': False, 'msg': '只有 Windows 支持全局热键'}
        self._running = True
        self._last_ctrl = 0.0
        self._unhook_ok = None
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self._thread = threading.Thread(target=self._run_hook, daemon=True)
        self._thread.start()
        for _ in range(60):                     # 等钩子装好（最多 ~1.2s）
            if self._hook or not self._running:
                break
            time.sleep(0.02)
        ok = bool(self._hook)
        return {'ok': ok, 'running': ok,
                'msg': '已启动' if ok else '装键盘钩子失败（可能被安全软件拦了）'}

    def stop(self):
        was = self._running
        self._running = False
        self._q.put(None)                       # 唤醒工作线程退出
        if self._tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            except Exception:                                           # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._worker:
            self._worker.join(timeout=1.0)
        self._thread = None
        self._worker = None
        if self._hook:                          # 消息循环没退干净就主线程兜底摘一次
            try:
                self._unhook_ok = bool(ctypes.windll.user32.UnhookWindowsHookEx(self._hook))
            except Exception:                                           # noqa: BLE001
                pass
            self._hook = None
        if was:
            print('[fanyi] 全局热键已关闭', flush=True)
        return {'ok': True, 'running': False, 'msg': '已停止'}

    def status(self):
        return {'ok': True, 'running': bool(self._running and self._hook)}


def perform_translation_action(report):
    """双击 Ctrl 后干的活（原来的核心流程）：剪切选中文字 → 翻译 → 粘回去。

    每一步都 `report('step', {'step': N, ...})`，界面的四步进度条照它走。"""
    original, _ = clipboard_get()
    report('step', {'step': 1, 'text': '读取选中的文字（Ctrl+A / Ctrl+X）'})
    _press_combo(VK_CONTROL, VK_A)
    time.sleep(0.15)
    _press_combo(VK_CONTROL, VK_X)
    time.sleep(0.15)
    text = (clipboard_get()[0] or '').strip()
    if not text:
        report('fail', {'step': 1, 'text': '没检测到选中的文字'})
        clipboard_set(original or '')
        return
    report('step', {'step': 2, 'text': '翻译：%s' % text[:40], 'source_text': text})
    got = do_translate(text, 'auto')
    if not got.get('ok'):
        report('fail', {'step': 2, 'text': got.get('why') or '翻译失败'})
        clipboard_set(text)                     # 把切走的原文粘回去
        _press_combo(VK_CONTROL, VK_V)
        time.sleep(0.1)
        clipboard_set(original or '')           # 再还原原来的剪贴板
        return
    report('step', {'step': 3, 'text': '写入剪贴板', 'translated': got['translated']})
    clipboard_set(got['translated'])
    _press_combo(VK_CONTROL, VK_V)              # 成功：剪贴板留译文（照老版行为）
    report('done', {'step': 4, 'text': got['translated'], 'result': got})
    time.sleep(0.1)


# ---------------------------------------------------------------- 内嵌模式（stdio）
class Embedded:
    """在 stdin/stdout 上说话的那一半。方法名跟界面里 `moss.call("名字")` 一一对应。"""

    def __init__(self):
        self._out_lock = threading.Lock()
        self._hotkey = Hotkey(lambda: perform_translation_action(self._report))

    def _report(self, phase, info):
        """热键动作在后台线程里跑，进度/结果主动推给界面。"""
        self.send({'event': 'hotkey', 'data': dict(info, phase=phase)})

    def hotkey_start(self, params=None):
        r = self._hotkey.start()
        self.send({'event': 'hotkey', 'data': {'phase': 'state', 'running': r['running'],
                                               'text': r['msg']}})
        return r

    def hotkey_stop(self, params=None):
        r = self._hotkey.stop()
        self.send({'event': 'hotkey', 'data': {'phase': 'state', 'running': False,
                                               'text': r['msg']}})
        return r

    def hotkey_status(self, params=None):
        return self._hotkey.status()

    def translate(self, params=None):
        p = params or {}
        got = do_translate(p.get('text'), p.get('target'))
        if got.get('ok'):
            print('[fanyi] %s → %s：%s' % (got.get('source'), got.get('target'),
                  (got.get('translated') or '')[:60]), flush=True)
        else:
            print('[fanyi] 没翻成：%s' % got.get('why'), flush=True)
        return got

    def read_clipboard(self, params=None):
        text, err = clipboard_get()
        print('[fanyi] 读剪贴板：%d 字%s' % (len(text), ('（%s）' % err) if err else ''),
              flush=True)
        return {'ok': not err, 'text': text, 'why': err or ''}

    def copy(self, params=None):
        text = str((params or {}).get('text') or '')
        ok, err = clipboard_set(text)
        print('[fanyi] 复制到剪贴板：%s' % ('好' if ok else ('失败（%s）' % err)), flush=True)
        return {'ok': ok, 'why': err or ''}

    def cache_info(self, params=None):
        return cache_info_payload()

    def cache_clear(self, params=None):
        n = cache_clear()
        print('[fanyi] 清空历史记录 / 缓存：%d 条' % n, flush=True)
        return dict(cache_info_payload(), removed=n)

    def history_remove(self, params=None):
        p = params or {}
        n = history_remove(p.get('src'), p.get('target'))
        print('[fanyi] 删掉一条历史记录：%d 条' % n, flush=True)
        return dict(cache_info_payload(), removed=n)

    def keep_history(self, params=None):
        """读 / 改「保留历史记录」开关：params 里给了 on 就改，返回当前状态。"""
        p = params or {}
        if p.get('on') is not None:
            set_keep_history(p.get('on'))
        return cache_info_payload()          # 里面就带 keep / count / history

    def history(self, params=None):
        limit = int((params or {}).get('limit') or 30)
        return {'ok': True, 'items': _history[:max(1, limit)]}

    def targets(self, params=None):
        return {'ok': True, 'targets': TARGETS, 'default': 'auto'}

    def info(self, params=None):
        print('[fanyi] 后端信息：pid=%d python=%s（内嵌模式）'
              % (os.getpid(), sys.version.split()[0]), flush=True)
        return {'pid': os.getpid(), 'python': sys.version.split()[0], 'cwd': os.getcwd(),
                'embedded': True, 'data_dir': DATA_DIR, 'cache_path': CACHE_FILE,
                'cache_count': len(_cache), 'who': _who()}

    # ---- 输出
    def send(self, obj):
        with self._out_lock:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
            sys.stdout.flush()

    def loop(self):
        self._hotkey.start()          # 一进来就自动开始监听（界面没有独立按钮，状态区可点停/开）
        try:
            for line in sys.stdin:
                line = (line or '').strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    self.send({'event': 'error',
                               'data': {'why': '这不是 JSON：%s' % line[:80]}})
                    continue
                mid, method = msg.get('id'), str(msg.get('method') or '')
                fn = getattr(self, method, None)
                if not callable(fn) or method.startswith('_') or method in ('send', 'loop'):
                    self.send({'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method})
                    continue
                try:
                    self.send({'id': mid, 'ok': True, 'result': fn(msg.get('params'))})
                except Exception as e:                                  # noqa: BLE001
                    self.send({'id': mid, 'ok': False,
                               'error': '%s: %s' % (type(e).__name__, e)})
        finally:
            self._hotkey.stop()          # 后端要退了，顺手把钩子卸掉


# ---------------------------------------------------------------- 独立窗口模式
def run_window():
    """不带参数时：自己开一个窗口（和别的 GUI 包一样）。"""
    import webview                                                      # noqa: PLC0415

    box = {}                     # 窗口放闭包里拿（★ 别挂到 Api 上，会让 JS 桥失效）

    def report(phase, info):
        w = box.get('window')
        if w is not None:
            try:
                w.evaluate_js('window.moss && window.moss.__emit("hotkey", %s)'
                              % json.dumps(dict(info, phase=phase), ensure_ascii=False))
            except Exception:                                           # noqa: BLE001
                pass

    hk_box = {}

    def hotkey():
        if 'hk' not in hk_box:
            hk_box['hk'] = Hotkey(lambda: perform_translation_action(report))
        return hk_box['hk']

    class Api:
        """独立窗口这边的后端。

        ★ 两个坑（照 skill 抄的，都实测踩过）：
          ① 每个方法都得收得下那一个参数（pywebview 把 JS 实参原样传进来）；
          ② 别把 `window` 挂成属性（会让整个 JS 桥失效）。
        """

        def translate(self, params=None):
            p = params or {}
            got = do_translate(p.get('text'), p.get('target'))
            print('[fanyi] 翻译：%s' % ('好' if got.get('ok') else got.get('why')), flush=True)
            return got

        def read_clipboard(self, params=None):
            text, err = clipboard_get()
            return {'ok': not err, 'text': text, 'why': err or ''}

        def copy(self, params=None):
            ok, err = clipboard_set(str((params or {}).get('text') or ''))
            return {'ok': ok, 'why': err or ''}

        def cache_info(self, params=None):
            return cache_info_payload()

        def cache_clear(self, params=None):
            n = cache_clear()
            print('[fanyi] 清空历史记录 / 缓存：%d 条' % n, flush=True)
            return dict(cache_info_payload(), removed=n)

        def history_remove(self, params=None):
            p = params or {}
            n = history_remove(p.get('src'), p.get('target'))
            print('[fanyi] 删掉一条历史记录：%d 条' % n, flush=True)
            return dict(cache_info_payload(), removed=n)

        def keep_history(self, params=None):
            p = params or {}
            if p.get('on') is not None:
                set_keep_history(p.get('on'))
            return cache_info_payload()

        def history(self, params=None):
            limit = int((params or {}).get('limit') or 30)
            return {'ok': True, 'items': _history[:max(1, limit)]}

        def targets(self, params=None):
            return {'ok': True, 'targets': TARGETS, 'default': 'auto'}

        def hotkey_start(self, params=None):
            r = hotkey().start()
            report('state', {'running': r['running'], 'text': r['msg']})
            return r

        def hotkey_stop(self, params=None):
            r = hotkey().stop()
            report('state', {'running': False, 'text': r['msg']})
            return r

        def hotkey_status(self, params=None):
            return hotkey().status()

        def info(self, params=None):
            print('[fanyi] 后端信息：pid=%d（独立窗口模式）' % os.getpid(), flush=True)
            return {'pid': os.getpid(), 'python': sys.version.split()[0], 'cwd': os.getcwd(),
                    'embedded': False, 'data_dir': DATA_DIR, 'cache_path': CACHE_FILE,
                    'cache_count': len(_cache), 'who': _who()}

    window = webview.create_window(TITLE, url=UI, js_api=Api(),
                                   width=560, height=720, min_size=(420, 520))
    box['window'] = window
    hotkey().start()                  # 自动开始监听（界面状态区可点停/开）
    window.events.closing += lambda: hotkey().stop()
    webview.start()
    return 0


def main():
    _settings_load()                  # 先读设置（「保留历史」开关），再按它读缓存
    cache_load()
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        Embedded().loop()
        return 0
    return run_window()


if __name__ == '__main__':
    sys.exit(main())
