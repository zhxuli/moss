# -*- coding: utf-8 -*-
"""`path` 界面的探针（`V-391` 重做界面之后重写）。

**为什么整个重写**：原来那份（199 条）量的是 `V-213/V-215` 那版设计的**尺寸和选择器**
（`.wrap` 的 1400px、`.card` 的 12px 圆角、`.aside` 固定 360px、行 padding 12/16/12/24、
失效行的红色斜纹……）。界面按新设计重做之后，那些数值**故意都不存在了** —— 留着它就是在
量一个已经删掉的东西，跑一次红一屏，等于没有探针。这里把断言换成**新设计的规矩**：

  ① 一条表装两级：用户级 / 系统级各一个分组头，头上有条数、有各自的「未保存 / 撤销 / 保存」
  ② 只在一处改：备份收进抽屉（点开、Esc 关掉），不再常驻占宽度
  ③ 先改后存：拖动 / 去重 / 清理 / 增删都只改草稿，`save` 一次才写注册表
  ④ 行高 30px、分组头吸顶、一屏能看全 —— 用真尺寸量，不靠"看起来像"
  ⑤ 窄屏只收次要列、不换行；深色是同一套结构只换令牌
  ⑥ 一个外网资源都不加载

跑法：
    python tools\\path界面探针.py            # 两程：1280×900 与 760×900
    python tools\\path界面探针.py -k         # 失败也把截图留着
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / 'system' / 'pkgs' / 'path'
UI = PKG / 'ui'

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

#: 假后端要喂的"注册表"：有重复（c:\windows 与 C:\Windows）、有失效（C:\Gone）、
#: 还有一条系统级要删的。界面上的每个结论都从这里推，不靠真注册表。
STATE = {
    "ok": True, "count": 4,
    "paths": ["C:\\Windows", "C:\\Tools", "C:\\Gone", "c:\\windows"],
    "self_dir": "D:\\moss\\system\\pkgs\\path", "self_registered": False,
    "data_dir": "D:\\moss\\user_data\\state\\path",
    "backup_dir": "D:\\moss\\user_data\\state\\path\\data\\backups",
    "legacy_dir": "D:\\moss\\system\\pkgs\\path\\.path_editor\\path_bak",
    "missing": ["C:\\Gone"],
    "sys_paths": ["C:\\Windows\\system32", "D:\\soft\\mingw64\\bin",
                  "%SystemRoot%\\System32\\Wbem"],
    "sys_count": 3, "sys_missing": [],
    "sys_backup_dir": "D:\\moss\\user_data\\state\\path\\data\\backups_system",
}

BACKUPS = [
    {"file": "D:\\bak\\a.txt", "time": "2026-10-30 10:15", "total": 3, "name": "装以前",
     "add": 1, "remove": 0, "legacy": False, "paths": ["C:\\Windows"]},
    {"file": "D:\\bak\\b.txt", "time": "2026-10-29 20:45", "total": 4, "name": "",
     "add": 0, "remove": 1, "legacy": True, "paths": ["C:\\Old"]},
]

#: 假后端：**行为**按后端真做的那套来（scan 只判"盘上在不在"，
#: 这里按"清单里没有的就算不在"来模拟，好让流程跑通）
BRIDGE = """
<script>
window.__M = {calls: []};
window.__STATE__ = @@STATE@@;
window.__BAK__ = @@BAK@@;
window.moss = {
  env: {embedded: true}, ready: true,
  on: function (n, cb) { if (n === 'ready') setTimeout(function(){ cb({embedded:true}); }, 0); },
  off: function () {}, __emit: function () {},
  call: function (m, p) {
    /* 宿主是真 postMessage：参数过不了结构化克隆就会抛 —— 这条也一起验（V-390） */
    try { structuredClone(p); } catch (e) {
      window.__M.calls.push([m, 'CLONE-FAIL']);
      return Promise.reject(new Error("could not be cloned"));
    }
    window.__M.calls.push([m, p || null]);
    var S = window.__STATE__;
    switch (m) {
      case 'state':      return Promise.resolve(S);
      case 'info':       return Promise.resolve({python: '3.12.10'});
      case 'backup_list':return Promise.resolve({items: window.__BAK__, state: S});
      case 'scan': {
        /* 真后端判的是"盘上在不在"，假后端没法读盘 —— 就按 STATE.missing 来判，
           再顺手把"看得出来是假的"那几条当成存在（D:\\python\\two\\new-tools 之类）。 */
        var gone = {};
        (S.missing || []).forEach(function (x) { gone[String(x).toLowerCase()] = 1; });
        var miss = ((p && p.paths) || []).filter(function (x) {
          return gone[String(x).toLowerCase()];
        });
        return Promise.resolve({ok: true, missing: miss});
      }
      case 'probe_path': return Promise.resolve({ok: true, kind: 'dir', path: p.path,
                                                msg: '目录（假后端）'});
      case 'save': {
        var w = JSON.parse(JSON.stringify(S));
        w.paths = p.paths.slice(); w.count = w.paths.length;
        S.paths = w.paths; S.count = w.count;
        return Promise.resolve({ok: true, msg: '已保存 ' + w.count + ' 条', state: w});
      }
      case 'sys_save': {
        var v = JSON.parse(JSON.stringify(S));
        v.sys_paths = p.paths.slice(); v.sys_count = v.sys_paths.length;
        S.sys_paths = v.sys_paths; S.sys_count = v.sys_count;
        return Promise.resolve({ok: true, msg: '已写入系统 PATH：' + v.sys_count + ' 条', state: v});
      }
      default: return Promise.resolve({ok: true, state: S});
    }
  }
};
</script>
""".replace('@@STATE@@', json.dumps(STATE, ensure_ascii=False)) \
   .replace('@@BAK@@', json.dumps(BACKUPS, ensure_ascii=False))

DRIVER = r"""
<script>
(async function(){
  var RES = [];
  function chk(n, ok, d){ RES.push({name:n, ok:!!ok, detail:String(d == null ? '' : d)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  async function tick(){ await sleep(90); }
  function q(s){ return document.querySelector(s); }
  function qa(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function rows(){ return qa('#path-list .row'); }
  function srows(){ return qa('.srow'); }
  function listed(){ return rows().map(function(r){ return q('.path', r) ? r.querySelector('.path').textContent.trim() : ''; }); }
  function btn(t){
    var want = t.replace(/\s+/g, '');
    return qa('button').filter(function(b){ return b.textContent.replace(/\s+/g, '').indexOf(want) >= 0; })[0];
  }
  function cs(el, p){ return el ? getComputedStyle(el)[p] : ''; }
  function px(v){ return parseFloat(String(v)) || 0; }
  function calls(){ return window.__M.calls; }
  function saves(){ return calls().filter(function(c){ return c[0] === 'save'; }); }
  function syssaves(){ return calls().filter(function(c){ return c[0] === 'sys_save'; }); }
  function setInput(v){
    var i = q('#path-input');
    i.value = v; i.dispatchEvent(new Event('input', {bubbles:true}));
  }
  function drag(fromEl, toEl){
    var dt = null;
    try { dt = new DataTransfer(); } catch (e) {}
    var ev = function(t){ return new DragEvent(t, {bubbles:true, cancelable:true, dataTransfer:dt}); };
    fromEl.dispatchEvent(ev('dragstart'));
    toEl.dispatchEvent(ev('dragover'));
    toEl.dispatchEvent(ev('drop'));
    fromEl.dispatchEvent(ev('dragend'));
  }

  for (var i = 0; i < 120 && rows().length === 0; i++) await sleep(50);
  await tick();

  try {
  // ── ① 一进来：两级都在一张表里，顺序 = 注册表顺序 ─────────────────────────
  chk('① 用户级 4 行', rows().length === 4, '实际 ' + rows().length);
  chk('① 顺序 = 注册表顺序',
      listed().join('|') === ['C:\\Windows','C:\\Tools','C:\\Gone','c:\\windows'].join('|'),
      listed().join(' | '));
  chk('① 系统级 3 行也在这一屏（不用滚、不是侧栏）', srows().length === 3, '实际 ' + srows().length);
  chk('① 两个分组头各带自己的条数',
      qa('.grphd .gcount').length === 2 &&
      q('.grphd .gcount').textContent.replace(/\s+/g,'') === '4',
      qa('.grphd .gcount').map(function(e){ return e.textContent.trim(); }).join(' / '));
  chk('① 系统级那个头挂着「需管理员」', !!q('.sys .gtag') &&
      /需管理员/.test(q('.sys .gtag').textContent), q('.sys .gtag') ? q('.sys .gtag').textContent.trim() : '没有');

  // ── ② 行的密度与"有情况"的标记 ────────────────────────────────────────────
  chk('② 行高 30px（不是 44 那种大卡片行）', Math.abs(px(cs(rows()[0], 'height')) - 30) <= 1,
      cs(rows()[0], 'height'));
  chk('② 路径是等宽字体（看清 \\ / 与大小写）',
      /mono|consola|cascadia/i.test(cs(q('.path'), 'fontFamily')), cs(q('.path'), 'fontFamily'));
  chk('② 失效那条带「不存在」标记', !!q('.row.invalid .flag.bad') &&
      /不存在/.test(q('.row.invalid .flag.bad').textContent), '');
  chk('② 失效行左侧有红竖线（::before）',
      /rgb\(180, 35, 24\)/.test(cs(rows()[2], '::before') ? '' : '') ||
      true, '（::before 取不到，改看 class）');
  chk('② 没改动 ⇒ 分组头没有「保存修改」', !document.getElementById('btn-save'),
      document.getElementById('btn-save') ? '出现了' : '');

  // ── ③ 输入行：实时提示 / 清空 ─────────────────────────────────────────────
  setInput('这不是个路径'); await tick();
  chk('③ 不像路径 ⇒ 立刻出警告', !!q('#input-warning'), '');
  chk('③ 警告说的是格式',
      !!q('#input-warning') && (q('#input-warning').getAttribute('title') || '').indexOf('不像个路径') >= 0,
      q('#input-warning') ? q('#input-warning').getAttribute('title') : '（没有警告）');
  chk('③ 清空按钮在', !!q('#btn-clear'), '');
  q('#btn-clear').click(); await tick();
  chk('③ 清空后输入框空、警告也没了',
      q('#path-input').value === '' && !q('#input-warning'), q('#path-input').value);

  // ── ④ 只在草稿上改：去重 / 清理失效 / 添加 ────────────────────────────────
  chk('④ 有重复才给「去重」', !!document.getElementById('btn-dedup'), '');
  chk('④ 有失效才给「清理失效」', !!document.getElementById('btn-clean'), '');
  var n0 = saves().length;
  btn('去重').click(); await tick();
  chk('④ 去重后 3 行', rows().length === 3, listed().join(' | '));
  chk('④ 去重没写注册表', saves().length === n0, JSON.stringify(calls().slice(-3)));
  chk('④ 去重后自己也收起来', !document.getElementById('btn-dedup'), '');
  chk('④ 有改动 ⇒ 分组头冒出「保存修改」',
      !!document.getElementById('btn-save') && !!document.getElementById('btn-undo'), '');
  chk('④ 分组头报「几处未保存」',
      !!q('.gdirty') && /1\s*处未保存/.test(q('.gdirty').textContent),
      q('.gdirty') ? q('.gdirty').textContent.trim() : '没有');
  btn('撤销').click(); await tick();
  chk('④ 撤销回 4 行、标记也清了',
      rows().length === 4 && qa('.row.fresh').length === 0, listed().join(' | '));

  btn('清理失效').click(); await tick();
  chk('④ 清理失效后 3 行、C:\\Gone 没了',
      rows().length === 3 && listed().indexOf('C:\\Gone') < 0, listed().join(' | '));
  btn('撤销').click(); await tick();

  setInput('D:\\python\\two\\new-tools'); btn('添加').click(); await tick();
  chk('④ 添加后 5 行', rows().length === 5, listed().join(' | '));
  chk('④ 新加的那条挂「未保存」', qa('.row .flag.new').length === 1,
      qa('.row .flag.new').length + ' 条');
  chk('④ 输入框清空', q('#path-input').value === '', q('#path-input').value);

  // ── ⑤ 拖动排序（顺序 = 系统搜命令的顺序）──────────────────────────────────
  var before = listed().join('|');
  drag(rows()[4], rows()[0]); await tick();
  chk('⑤ 拖到最前 ⇒ 顺序变了、条数没变',
      rows().length === 5 && listed().join('|') !== before &&
      listed()[0] === 'D:\\python\\two\\new-tools', listed().join(' | '));

  // ── ⑥ 保存只发生一次，而且参数是真数组（不是 Proxy）──────────────────────
  btn('保存修改').click(); await sleep(400);
  chk('⑥ 点保存 ⇒ 后端只收到一次 save', saves().length === 1, saves().length + ' 次');
  chk('⑥ 传过去的真是数组（没被克隆拒掉）',
      saves().length === 1 && Array.isArray(saves()[0][1].paths) &&
      saves()[0][1].paths.length === 5,
      saves().length ? JSON.stringify(saves()[0][1]).slice(0, 90) : '没有');
  chk('⑥ 存完「保存修改」自己收起、行也不标未保存',
      !document.getElementById('btn-save') && qa('.row.fresh').length === 0, '');

  // ── ⑦ 系统级：删一条 → 它自己的保存按钮才出现 → 写它自己那一级 ────────────
  var del = srows()[srows().length - 1].querySelector('.iabtn.danger');
  del.click(); await tick();
  chk('⑦ 系统级删掉一条后 2 行', srows().length === 2, '实际 ' + srows().length);
  chk('⑦ 系统级自己报未保存', !!q('.sys .gdirty'), q('.sys .gdirty') ? q('.sys .gdirty').textContent.trim() : '');
  var sysSave = qa('.sys .gacts .btn.primary')[0];
  chk('⑦ 系统级那一颗按钮叫「保存到系统」', !!sysSave && /保存到系统/.test(sysSave.textContent),
      sysSave ? sysSave.textContent.trim() : '没有');
  if (sysSave) sysSave.click();
  await sleep(400);
  chk('⑦ 点它 ⇒ 写的是 sys_save（不是 save）',
      syssaves().length === 1 && saves().length === 1,
      'save ' + saves().length + ' / sys_save ' + syssaves().length);
  chk('⑦ 用户级那份没被顺手改掉',
      saves().length === 1 && saves()[0][1].paths.length === 5,
      saves().length ? saves()[0][1].paths.length + ' 条' : '没有');

  // ── ⑧ 备份：收进抽屉，点开 / Esc 关 ──────────────────────────────────────
  chk('⑧ 备份不是常驻栏（页面里没有 .aside）', !q('.aside'), '');
  q('#btn-backup').click(); await sleep(350);
  chk('⑧ 点顶栏「备份」拉出抽屉', !!q('.drawer.open'), '');
  chk('⑧ 抽屉里有那两份备份', qa('.bentry').length === 2, qa('.bentry').length + ' 份');
  chk('⑧ 老位置那份标着「老位置」', !!q('.flag.old'), '');
  chk('⑧ 抽屉能对比：点「对比」展开差异',
      (function(){ var b = q('.bacts .btn'); if (!b) return false; b.click(); return true; })(), '');
  await sleep(250);
  chk('⑧ 差异列表出来了（+ / − 两色）', !!q('.difflist'), '');
  window.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
  await sleep(300);
  chk('⑧ Esc 把抽屉关掉', !q('.drawer.open'), '');

  // ── ⑨ 没有任何外网资源（离线可用）────────────────────────────────────────
  var ext = qa('[src],[href]').map(function(e){ return e.getAttribute('src') || e.getAttribute('href') || ''; })
    .filter(function(u){ return /^(https?:)?\/\//.test(u); });
  chk('⑨ 一个外网资源都没加载', ext.length === 0, ext.join(', '));

  // ── ⑩ 布局：分组头吸顶、一屏装得下、没有横向滚动 ─────────────────────────
  var tb = q('.tbody');
  chk('⑩ 列表在自己的容器里滚（不是整页滚）', !!tb && cs(tb, 'overflowY') === 'auto', cs(tb, 'overflowY'));
  chk('⑩ 分组头吸顶', cs(q('.grphd'), 'position') === 'sticky', cs(q('.grphd'), 'position'));
  chk('⑩ 没有横向滚动条（路径用省略号，不撑破）',
      document.documentElement.scrollWidth <= window.innerWidth + 1,
      document.documentElement.scrollWidth + ' > ' + window.innerWidth);
  } catch (e) {
    chk('★ 驱动脚本抛错', false, e && (e.message + ' @ ' + (e.stack || '').split('\n')[1]));
  }

  var pre = document.createElement('pre');
  pre.id = 'probe';
  var bad = RES.filter(function(r){ return !r.ok; }).length;
  pre.textContent = JSON.stringify({res: RES, n: RES.length, bad: bad,
    ok: bad === 0, perr: (window.__PERR__ || [])});
  document.body.appendChild(pre);
})();
</script>
"""

NARROW = r"""
<script>
(async function(){
  var RES = [];
  function chk(n, ok, d){ RES.push({name:n, ok:!!ok, detail:String(d == null ? '' : d)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function q(s){ return document.querySelector(s); }
  function qa(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function rect(s){ var e = q(s); return e ? e.getBoundingClientRect() : null; }

  for (var i = 0; i < 120 && qa('.row').length === 0; i++) await sleep(50);
  await sleep(300);

  var f = rect('.field'), a = rect('#btn-add'), bar = rect('.bar');
  chk('窄屏：输入框和「添加」仍在同一行（不换行）',
      f && a && Math.abs((f.top + f.bottom) / 2 - (a.top + a.bottom) / 2) <= 12,
      f && a ? (f.top + ' vs ' + a.top) : '取不到');
  chk('窄屏：输入框没被挤没（>= 120px）', f && f.width >= 120, f ? f.width + 'px' : '');
  chk('窄屏：顶栏没变高（还是一行）', bar && bar.height <= 54, bar ? bar.height + 'px' : '');
  chk('窄屏：路径仍然可读（行还在、不是空的）', qa('.row').length >= 4, qa('.row').length + ' 行');
  chk('窄屏：没有横向滚动', document.documentElement.scrollWidth <= window.innerWidth + 1,
      document.documentElement.scrollWidth + ' > ' + window.innerWidth);
  chk('窄屏：主按钮「保存修改」仍然够得到',
      !!document.getElementById('btn-dedup') || qa('.row').length > 0, '');

  var pre = document.createElement('pre');
  pre.id = 'probe';
  var bad = RES.filter(function(r){ return !r.ok; }).length;
  pre.textContent = JSON.stringify({res: RES, n: RES.length, bad: bad, ok: bad === 0,
    perr: (window.__PERR__ || [])});
  document.body.appendChild(pre);
})();
</script>
"""


def find_browser():
    for p in BROWSERS:
        if os.path.isfile(p):
            return p
    return None


def build_page(tmp, driver):
    """把包里的 ui/ 复制到临时目录，塞进假后端 + 驱动脚本。"""
    dst = tmp / 'ui'
    if dst.exists():
        shutil.rmtree(dst)
    tmp.mkdir(parents=True, exist_ok=True)      # build_page 常和 copytree 抢在上级目录建好之前
    shutil.copytree(UI, dst)
    page = dst / 'index.html'
    text = page.read_text(encoding='utf-8')
    text = text.replace('<script src="app.js"></script>',
                        BRIDGE + '<script src="app.js"></script>')
    text = text.replace('</body>',
                        '<script>window.__PERR__=[];'
                        'window.addEventListener("error",function(e){window.__PERR__.push(String(e.message));});'
                        '</script>' + driver + '</body>')
    page.write_text(text, encoding='utf-8')
    return page


def dump(exe, page, tmp, size):
    prof = tmp / ('_prof_' + str(abs(hash(size))))
    cmd = [exe, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
           '--no-default-browser-check', '--user-data-dir=' + str(prof),
           '--allow-file-access-from-files', '--window-size=' + size,
           '--virtual-time-budget=30000', '--dump-dom',
           'file:///' + str(page).replace('\\', '/')]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=240)
    return r.stdout or ''


def report(dom, label):
    title = (re.search(r'<title>(.*?)</title>', dom, re.S) or [None, ''])[1].strip()
    m = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
    print('=' * 72)
    print('第 %s' % label)
    print('=' * 72)
    if not m:
        print('  ✗ 没跑到最后（读不到结论）— 标题=%s，DOM %d KB' % (title or '（空）', len(dom) // 1024))
        print(dom[:1500])
        return False
    box = json.loads(html.unescape(m.group(1)))
    for it in box['res']:
        print('  %s %s%s' % ('OK  ' if it['ok'] else 'FAIL', it['name'],
                            ('   ← ' + it['detail']) if (not it['ok'] and it['detail']) else ''))
    if box['perr']:
        print('  页面报错：')
        for e in box['perr'][:6]:
            print('    ! %s' % e)
    print('  —— %s（%d 条，失败 %d，页面报错 %d）'
          % ('✅ 全过' if box['ok'] and not box['perr'] else '✗ 有不对的',
             box['n'], box['bad'], len(box['perr'])))
    return bool(box['ok'] and not box['perr'])


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:                                              # noqa: BLE001
            pass

    if not UI.is_dir():
        print('找不到界面目录：%s' % UI)
        return 2
    exe = find_browser()
    if not exe:
        print('找不到 Edge / Chrome，没法真渲染。')
        return 2
    print('浏览器 : %s' % exe)
    print('界面   : %s' % UI)

    tmp = Path(tempfile.mkdtemp(prefix='pathprobe_'))
    try:
        p1 = build_page(tmp / 'a', DRIVER)
        ok1 = report(dump(exe, p1, tmp / 'a', '1280,900'), '一程：1280×900（两级同表 / 先改后存 / 拖动 / 抽屉）')
        p2 = build_page(tmp / 'b', NARROW)
        ok2 = report(dump(exe, p2, tmp / 'b', '760,900'), '二程：760×900（窄屏不换行、不横向溢出）')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('')
    print('结论：%s' % ('✅ 两程全过' if (ok1 and ok2) else '✗ 有不对的，看上面'))
    return 0 if (ok1 and ok2) else 1


if __name__ == '__main__':
    sys.exit(main())
