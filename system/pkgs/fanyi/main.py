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

DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.environ.get('PA_PLUGIN_DATA_DIR')
            or os.path.join(os.environ.get('MOSS_HOME') or os.path.expanduser('~'),
                            'user_data', 'state', 'fanyi'))
CACHE_DIR = os.environ.get('MOSS_PLUGIN_CACHE_DIR') or os.path.join(DATA_DIR, 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'translation_cache.jsonl')
HISTORY_LIMIT = 200

SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
_keep_history = True

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) moss:fanyi'

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

_cache = {}
_history = []

def _key(text, target):
    return text + '\x1f' + target

LEGACY_CACHE = os.path.join(DATA_DIR, 'translation_cache.txt')

def _guess_lang(text):
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

def _import_legacy():
    if not os.path.isfile(LEGACY_CACHE):
        return 0
    n = 0
    try:
        with open(LEGACY_CACHE, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) != 2:
                    continue
                a, b = parts[0].strip(), parts[1].strip()
                if not (a and b):
                    continue
                cache_store(a, _guess_lang(b), b, '')
                cache_store(b, _guess_lang(a), a, '')
                n += 2
    except Exception as e:
        print('[fanyi] 导入旧缓存失败：%s' % e, flush=True)
        return 0
    if n:
        print('[fanyi] 已从旧缓存 %s 导入 %d 条' % (LEGACY_CACHE, n), flush=True)
    return n

def cache_load():
    global _cache, _history
    _cache, _history = {}, []
    if not os.path.isfile(CACHE_FILE):
        if not _keep_history:
            return 0
        return _import_legacy()
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
    except Exception as e:
        print('[fanyi] 读缓存失败：%s' % e, flush=True)
        return 0
    _history = _history[-HISTORY_LIMIT:][::-1]
    return n

def cache_store(original, target, translated, source):
    rec = {'original': original, 'target': target, 'translated': translated,
           'source': source or '', 'at': _now()}
    if not _keep_history:
        return rec
    _cache[_key(original, target)] = rec
    _history.insert(0, {'src': original, 'dst': translated, 'target': target,
                        'at': rec['at']})
    del _history[HISTORY_LIMIT:]
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:
        print('[fanyi] 写缓存失败：%s' % e, flush=True)
    return rec

def cache_clear():
    global _cache, _history
    n = len(_cache)
    _cache, _history = {}, []
    try:
        if os.path.isfile(CACHE_FILE):
            os.remove(CACHE_FILE)
    except Exception as e:
        print('[fanyi] 删缓存失败：%s' % e, flush=True)
    return n

def cache_save():
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
    except Exception as e:
        print('[fanyi] 写缓存失败：%s' % e, flush=True)
    return len(recs)

def history_remove(src, target=''):
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

def _settings_load():
    global _keep_history
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _keep_history = bool(data.get('keep_history', True))
    except Exception:
        _keep_history = True

def _settings_save():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'keep_history': _keep_history, 'updated': _now()}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception as e:
        print('[fanyi] 记设置失败：%s' % e, flush=True)

def set_keep_history(on):
    global _keep_history
    _keep_history = bool(on)
    _settings_save()
    print('[fanyi] 保留历史记录：%s' % ('开' if _keep_history else '关'), flush=True)
    return _keep_history

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

def _clipboard_ready():
    if os.name != 'nt':
        return False
    try:
        import ctypes
        return True
    except Exception:
        return False

def clipboard_get():
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
    for _ in range(5):
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
    except Exception as e:
        return '', '%s' % e
    finally:
        u.CloseClipboard()

def clipboard_set(text):
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
    except Exception as e:
        return False, '%s' % e
    finally:
        u.CloseClipboard()

GT_URL = 'https://translate.googleapis.com/translate_a/single'
GT_C5_URL = 'https://clients5.google.com/translate_a/t'
YDL_URL = 'https://aidemo.youdao.com/trans'
MYM_URL = 'https://api.mymemory.translated.net/get'

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
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP %s %s' % (exc.code, exc.reason)
    return (str(exc) or exc.__class__.__name__).replace('\n', ' ')[:160]

def _provider_load():
    if _PROVIDER['loaded']:
        return
    _PROVIDER['loaded'] = True
    try:
        with open(PROVIDER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        key = str(data.get('preferred') or '')
        if key in PROVIDERS:
            _PROVIDER['preferred'] = key
    except Exception:
        pass

def _provider_save(key):
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
    except Exception as e:
        print('[fanyi] 记翻译通道失败：%s' % e, flush=True)

def _provider_keys():
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
    text = (text or '').strip()
    if not text:
        return {'ok': False, 'why': '没有要翻译的文字'}
    if len(text) > 5000:
        return {'ok': False, 'why': '一次最多 5000 字，太长了'}
    target = (target or 'auto').strip()

    source_hint = _guess_lang(text)
    if target == 'auto':
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
        except Exception as e:
            errors.append('%s：%s' % (spec['name'], _err_text(e)))
    return {'ok': False,
            'why': '网络翻译失败（所有免费通道都试过了）：' + '；'.join(errors)}

def cache_info_payload():
    return {'ok': True, 'count': len(_cache), 'path': CACHE_FILE,
            'dir': CACHE_DIR, 'history': _history[:30], 'who': _who(),
            'keep': _keep_history, 'limit': HISTORY_LIMIT}

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
DOUBLE_CLICK_INTERVAL = 0.3
COOLDOWN_SECONDS = 1.0

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
    _send_key(mod_vk)
    _send_key(key_vk)
    _send_key(key_vk, up=True)
    _send_key(mod_vk, up=True)

class Hotkey:
    def __init__(self, on_trigger):
        self._on = on_trigger
        self._running = False
        self._thread = None
        self._worker = None
        self._q = queue.Queue()
        self._hook = None
        self._proc = None
        self._tid = 0
        self._last_ctrl = 0.0
        self._last_fire = 0.0
        self._busy = False
        self._unhook_ok = None

    def feed_ctrl(self, injected=False):
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
        try:
            if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if kb.vkCode in (VK_LCONTROL, VK_RCONTROL, VK_CONTROL):
                    if self.feed_ctrl(injected=bool(kb.flags & LLKHF_INJECTED)):
                        self._busy = True
                        self._last_fire = time.time()
                        self._q.put(1)
        except Exception:
            pass
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run_worker(self):
        while self._running:
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._on()
            except Exception as e:
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
        for _ in range(60):
            if self._hook or not self._running:
                break
            time.sleep(0.02)
        ok = bool(self._hook)
        return {'ok': ok, 'running': ok,
                'msg': '已启动' if ok else '装键盘钩子失败（可能被安全软件拦了）'}

    def stop(self):
        was = self._running
        self._running = False
        self._q.put(None)
        if self._tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._worker:
            self._worker.join(timeout=1.0)
        self._thread = None
        self._worker = None
        if self._hook:
            try:
                self._unhook_ok = bool(ctypes.windll.user32.UnhookWindowsHookEx(self._hook))
            except Exception:
                pass
            self._hook = None
        if was:
            print('[fanyi] 全局热键已关闭', flush=True)
        return {'ok': True, 'running': False, 'msg': '已停止'}

    def status(self):
        return {'ok': True, 'running': bool(self._running and self._hook)}

def perform_translation_action(report):
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
        clipboard_set(text)
        _press_combo(VK_CONTROL, VK_V)
        time.sleep(0.1)
        clipboard_set(original or '')
        return
    report('step', {'step': 3, 'text': '写入剪贴板', 'translated': got['translated']})
    clipboard_set(got['translated'])
    _press_combo(VK_CONTROL, VK_V)
    report('done', {'step': 4, 'text': got['translated'], 'result': got})
    time.sleep(0.1)

class Embedded:
    def __init__(self):
        self._out_lock = threading.Lock()
        self._hotkey = Hotkey(lambda: perform_translation_action(self._report))

    def _report(self, phase, info):
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
        p = params or {}
        if p.get('on') is not None:
            set_keep_history(p.get('on'))
        return cache_info_payload()

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

    def send(self, obj):
        with self._out_lock:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
            sys.stdout.flush()

    def loop(self):
        self._hotkey.start()
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
                except Exception as e:
                    self.send({'id': mid, 'ok': False,
                               'error': '%s: %s' % (type(e).__name__, e)})
        finally:
            self._hotkey.stop()

def run_window():
    import webview

    box = {}

    def report(phase, info):
        w = box.get('window')
        if w is not None:
            try:
                w.evaluate_js('window.moss && window.moss.__emit("hotkey", %s)'
                              % json.dumps(dict(info, phase=phase), ensure_ascii=False))
            except Exception:
                pass

    hk_box = {}

    def hotkey():
        if 'hk' not in hk_box:
            hk_box['hk'] = Hotkey(lambda: perform_translation_action(report))
        return hk_box['hk']

    class Api:
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
    hotkey().start()
    window.events.closing += lambda: hotkey().stop()
    webview.start()
    return 0

def main():
    _settings_load()
    cache_load()
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        Embedded().loop()
        return 0
    return run_window()

if __name__ == '__main__':
    sys.exit(main())
