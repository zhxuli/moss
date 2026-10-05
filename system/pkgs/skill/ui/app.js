/* 技能管理器 · 界面（图标墙 + 详情）
   ============================================================================
   ★ 跟后端说话只有一条路：`moss.call('方法名', 参数)`（垫片 `moss-embed.js` 负责分流：
     内嵌进 moss 时走 postMessage → 宿主 → 后端的 stdin；独立窗口时直接调 pywebview）。
   ★ `--` 只在详情里露一次（id 那一行）—— 墙上只显示名字（你定的：像桌面一样）。
   ============================================================================ */
'use strict';

const $ = (s) => document.querySelector(s);
let DATA = null;          // 后端 list 回来的那份
let CUR = null;           // 详情里正在看的那一只
let OPEN_FILE = '';       // 详情里展开了哪个文件
let FILE_TEXT = {};

/* 把后端的 payload 拉平成一个数组：`skills` + 只在 `broken` 里的那些（按 id 去重）。
   ★ 为什么还要并 `broken`：宿主那边的 `broken` 本来就是 `skills` 的子集，但"只给 broken
     不给 skills"这种形状也得能吃（假桥探针就造过这种）。 */
function skillAll(got){
  got = got || {};
  const out = [], seen = {};
  (got.skills || []).concat(got.broken || []).forEach((w) => {
    if (!w || !w.id || seen[w.id]) return;
    seen[w.id] = 1;
    out.push(w);
  });
  return out;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* 图标：后端给的是洗过的 svg 正文（含 <script> 的会被后端丢掉）—— 这里直接 innerHTML */
function iconHTML(it) {
  if (it.icon_svg) return it.icon_svg;
  return '<div class="fallback">✨</div>';
}

function status(it) {
  if (it.problems && it.problems.length) return { cls: 'bad', text: '写坏了', dot: 'bad' };
  if (!it.allowed) return { cls: 'pending', text: '待批准', dot: 'pending' };
  return { cls: '', text: it.kind === 'pkg' ? '插件 · 可调用' : '可用', dot: '' };
}

function tile(it) {
  const st = status(it);
  const el = document.createElement('div');
  el.className = 'tile ' + st.cls;
  el.dataset.id = it.id;
  el.innerHTML =
    (st.dot ? '<span class="dot ' + st.dot + '"></span>' : '') +
    (it.kind === 'pkg' ? '<span class="tag">插件</span>' : '') +
    '<div class="ico">' + iconHTML(it) + '</div>' +
    '<div class="nm">' + esc(it.name) + '</div>' +
    '<div class="st">' + esc(st.text) + '</div>';
  el.onclick = () => showDetail(it.id);
  return el;
}

function render() {
  const wall = $('#wall');
  wall.innerHTML = '';
  // ★ `V-284`：**只有技能** —— 插件不出现在这一页（你说的"插件的东西不能放在技能这里显示"）。
  const skills = (DATA && DATA.skills) || [];
  const broken = (DATA && DATA.broken) || [];
  skills.forEach((it) => wall.appendChild(tile(it)));
  // 写坏了的那些宿主也放在 `skills` 里（带 problems），但万一后端只给了 broken，也别漏掉
  broken.forEach((it) => {
    if (!skills.some((x) => x.id === it.id)) wall.appendChild(tile(it));
  });
  $('#empty').hidden = !!(skills.length || broken.length);
  const pend = skills.concat(broken).filter((x) => !x.problems.length && !x.allowed).length;
  // ★ 后端没给 `dir` 的时候别摆一个 "undefined" 出来（假桥探针里就撞见过一次）
  const bits = [skills.length + ' 只技能（能用 ' + DATA.n_usable + '）'];
  if (pend) bits.push(pend + ' 只等你允许');
  if (DATA.dir) bits.push(DATA.dir);
  $('#sub').textContent = bits.join(' · ');
}

/* ---------------------------------------------------------------- 详情 */
function find(id) {
  // 只有技能（`V-284`：插件不出现在这一页）
  const all = skillAll(DATA);
  return all.filter((x) => x.id === id)[0] || null;
}

function filesTable(it) {
  if (!it.files || !it.files.length) return '<p class="dim">（空目录）</p>';
  const rows = it.files.map((f) =>
    '<tr class="file" data-file="' + esc(f.rel) + '"><td>' + esc(f.rel) + '</td>' +
    '<td>' + esc(f.size) + ' B</td><td>' + esc(f.mtime) + '</td></tr>' +
    (OPEN_FILE === f.rel
      ? '<tr><td colspan="3"><pre class="code">' +
        esc(FILE_TEXT[f.rel] == null ? '（正在读…）' : FILE_TEXT[f.rel]) + '</pre></td></tr>'
      : '')).join('');
  return '<table class="files"><tr><th>文件</th><th>大小</th><th>改过</th></tr>' + rows + '</table>';
}

function showDetail(id) {
  const it = find(id);
  if (!it) return;
  CUR = it;
  OPEN_FILE = '';
  FILE_TEXT = {};
  const st = status(it);
  const canPromote = it.layer === 'user';
  const chips = [];
  chips.push('<span class="chip ' + (st.dot === 'bad' ? 'bad' : (st.dot === 'pending' ? 'warn' : 'ok')) +
    '">' + esc(it.allowed ? 'AI 可以用它' : (it.problems.length ? '进不了工具表' : '还没允许')) + '</span>');
  if (it.origin === 'seed') chips.push('<span class="chip">出厂样例</span>');
  if (it.risk) chips.push('<span class="chip">风险 ' + esc(it.risk) + '</span>');
  (it.params || []).forEach((p) => chips.push('<span class="chip">参数 ' + esc(p) + '</span>'));
  (it.warns || []).forEach((w) => chips.push('<span class="chip warn">' + esc(w) + '</span>'));
  (it.problems || []).forEach((w) => chips.push('<span class="chip bad">' + esc(w) + '</span>'));

  // ★ 模态框里的那张卡（内容全塞进 `#detail-card`）
  const card = $('#detail-card');
  card.innerHTML =
    '<button class="x" id="d-x" title="关闭（Esc）" aria-label="关闭">✕</button>' +
    '<div class="dhead">' +
      '<div class="ico">' + iconHTML(it) + '</div>' +
      '<div class="dtitle"><h3>' + esc(it.name) + '</h3>' +
        '<div class="id">' + esc(it.id) + '</div>' +
        '<div class="dim">' + esc(it.desc || '（没写说明）') + '</div></div>' +
    '</div>' +
    (it.why ? '<div class="why"><b>为什么造它：</b>' + esc(it.why) + '</div>'
            : '<div class="why dim">（它没写 ai.why —— 「为什么造它」空着）</div>') +
    '<div class="chips">' + chips.join('') + '</div>' +
    '<div class="kv">' +
      '<span class="k">状态</span><span>' + esc(st.text + ' —— ' + (it.why_allow || '')) + '</span>' +
      '<span class="k">入口</span><span>' + esc(it.entry || '—') + '</span>' +
      '<span class="k">超时</span><span>' + esc(it.timeout) + ' 秒</span>' +
      '<span class="k">创建</span><span>' + esc(it.created || '—') + '</span>' +
      '<span class="k">改过</span><span>' + esc(it.mtime || '—') + '</span>' +
      '<span class="k">允许于</span><span>' + esc(it.allowed_at || '—') + '</span>' +
      '<span class="k">目录</span><span class="dim">' + esc(it.dir) + '</span>' +
    '</div>' +
    '<div class="dacts">' +
      (it.layer === 'user' && !it.problems.length
        ? '<button class="btn" id="d-allow">' + (it.allowed ? '撤销允许' : '允许') + '</button>' : '') +
      '<button class="btn" id="d-doc" title="这只技能自己的说明书（AGENT.md）">看说明</button>' +
      (it.allowed ? '<button class="btn" id="d-run" title="像 AI 那样跑一次（空参数）">试跑一次</button>' : '') +
      (canPromote ? '<button class="btn" id="d-promote" title="去掉技能身份、搬进插件列表">转为插件</button>' : '') +
      '<button class="btn" id="d-open">打开目录</button>' +
      (it.layer === 'user' ? '<button class="btn danger" id="d-rm">删除</button>' : '') +
    '</div>' +
    '<pre class="code" id="d-docbox" hidden></pre>' +
    '<div><b>文件（' + it.files_n + '）</b>' + filesTable(it) + '</div>';

  $('#detail').hidden = false;

  const on = (sel, fn) => { const b = $(sel); if (b) b.onclick = fn; };
  on('#d-x', closeDetail);
  on('#d-allow', () => call('allow', { id: it.id, yes: !it.allowed }));
  on('#d-open', () => call('reveal', { dir: it.dir }, true));
  on('#d-rm', () => confirmBox('删掉这只技能？',
    '删掉 <code>' + esc(it.id) + '</code> 的整个目录（' + it.files_n + ' 个文件）？\n' + it.dir,
    () => call('rm', { id: it.id, confirm: true })));
  on('#d-run', () => call('run_once', { id: it.id, args: {} }, true));
  on('#d-promote', () => promoteFlow(it));
  on('#d-doc', () => {
    const box = $('#d-docbox');
    if (!box) return;
    if (!box.hidden){ box.hidden = true; return; }        // 再点一下收起
    box.hidden = false;
    box.textContent = '（正在读…）';
    moss.call('doc', { id: it.id }).then((r) => {
      box.textContent = (r && r.text) || '（没有说明）';
    }).catch((e) => { box.textContent = '读不出来：' + (e && e.message ? e.message : e); });
  });
  document.querySelectorAll('#detail-card tr.file').forEach((tr) => {
    tr.onclick = () => {
      const rel = tr.dataset.file;
      if (OPEN_FILE === rel) { OPEN_FILE = ''; showDetail(it.id); return; }
      OPEN_FILE = rel;
      call('read', { id: it.id }).then((got) => {
        FILE_TEXT = (got && got.text) || {};
        showDetail(it.id);
      });
    };
  });
}

function closeDetail(){
  $('#detail').hidden = true;
  CUR = null;
}

/* ---------------------------------------------------------------- 转成插件 */
function promoteFlow(it) {
  call('plan', { id: it.id }).then((p) => {
    if (!p || !p.ok) { toast((p && p.msg) || '算不出来'); return; }
    const bad = (p.problems || []).length;
    confirmBox(bad ? 'id 撞了 —— 换个名字' : '转为插件？',
      (bad ? p.problems.join('\n') + '\n\n' : '') +
      '搬过去：\n  ' + p.dir_from + '\n  → ' + p.dir_to + '\n' +
      '转过去之后它就出现在**插件列表**里了（AI 照样能调它）。',
      (newId) => call('promote', { id: it.id, confirm: true, new_id: newId }),
      { input: bad ? p.new_id : '', hint: '留空 = 用 ' + p.new_id });
  });
}

/* ---------------------------------------------------------------- 小工具 */
function toast(text, bad) {
  // 包里不搞一套 toast：直接用一条浮出来的小提示条（3 秒后自己走）
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.style.cssText = 'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);' +
      'background:#0F172A;color:#fff;padding:9px 16px;border-radius:9px;font-size:13px;' +
      'max-width:80%;z-index:20;box-shadow:0 12px 30px -12px rgba(0,0,0,.5)';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.background = bad ? '#B91C1C' : '#0F172A';
  el.style.display = '';
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.display = 'none'; }, 3200);
}

function confirmBox(title, body, cb, opts) {
  $('#m-title').textContent = title;
  $('#m-body').innerHTML = body;
  const extra = $('#m-extra');
  extra.hidden = !(opts && opts.input !== undefined);
  if (!extra.hidden) {
    $('#m-input').value = (opts && opts.input) || '';
    $('#m-hint').textContent = (opts && opts.hint) || '';
  }
  $('#modal').hidden = false;
  $('#m-ok').onclick = () => {
    const v = extra.hidden ? '' : $('#m-input').value.trim();
    $('#modal').hidden = true;
    cb(v);
  };
  $('#m-cancel').onclick = () => { $('#modal').hidden = true; };
}

function call(method, params, justToast) {
  return moss.call(method, params).then((r) => {
    const ok = r && (r.ok !== false);
    toast((r && r.msg) || (ok ? '好了' : '没成'), !ok);
    if (justToast) return r;
    return load();
  }).catch((e) => { toast('出错了：' + (e && e.message ? e.message : e), true); });
}

function load() {
  return moss.call('list', {}).then((got) => {
    DATA = got || { skills: [], broken: [], n_usable: 0, dir: '' };
    render();
    if (CUR) { const it = find(CUR.id); if (it) showDetail(it.id); else { $('#detail').hidden = true; CUR = null; } }
  }).catch((e) => { $('#sub').textContent = '读不出来：' + (e && e.message ? e.message : e); });
}

/* ---------------------------------------------------------------- 启动（★ 这里栽过一次）

   ★ 第一版只挂了 `moss.on('ready', ...)` 一句 —— 结果独立窗口那种跑法（`moss :skill` /
     插件列表里点「运行」）**可能永远停在"正在读……"**：
     `moss-embed.js` 在非内嵌时是把 `ready` 挂在 `pywebviewready` 上的，而那个事件
     **只发一次**、还有可能在 `app.js` 执行之前就发过了（页面拆成外部脚本之后就有这个竞态）。
     错过就永远等不到 ⇒ `load()` 从不运行 ⇒ **什么都不报，就一句"正在读"**。
     这是主界面当年修过的同一个坑（账本 `V-68`：`system/ui/js/app.js`）—— 照它两手准备。

   ★ 你后来说的也对：「哪怕没有，也不能一直显示正在读吧」—— 所以加了兜底提示。
   ★★ `V-285`（你报的"界面里点运行 → 先说读不出来、点了重试就好"）：
      根因是我把兜底设成 8 秒、却**只轮询 6 秒** —— "界面里点「运行」"那条路（宿主给包加
      `MOSS_INTERACTIVE=1`、stdio 全是管道）桥要 8 秒以后才就绪，于是提示先蹦出来、轮询早停了；
      一点「重试」恰好赶上桥已就绪 ⇒ 看起来像"重试才管用"。现在分两档 + 一直轮询：
        · 6 秒：只说「正在读……（后端起来得有点慢，再等一会儿）」+ 重试
        · 20 秒：才说「读不出来 —— 后端没上来」
        · 轮询**一直继续**（500ms 一次，很便宜），桥什么时候到就什么时候自己起来，不用人点 */
let _booted = false;
let _hintTimer = null;
let _bootTimer = null;

function boot(){
  if (_booted) return;
  _booted = true;
  if (_hintTimer){ clearTimeout(_hintTimer); _hintTimer = null; }
  if (_bootTimer){ clearTimeout(_bootTimer); _bootTimer = null; }
  load();
  $('#btn-reload').onclick = load;
  $('#btn-seed').onclick = () => call('seed', {});
  $('#btn-open').onclick = () => call('reveal', { dir: (DATA && DATA.dir) || '' }, true);
  // 模态框：点背景关、Esc 关（✕ 那颗在卡片里，showDetail 里绑）
  const d = $('#detail');
  if (d) d.onclick = (ev) => { if (ev.target === d) closeDetail(); };
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape'){
      if (!$('#modal').hidden){ $('#modal').hidden = true; return; }
      if (!$('#detail').hidden) closeDetail();
    }
  });
}

/* 「重试」那颗按钮：两档计时重新起，并立刻再试一次 boot（桥要是在了就成了） */
function _retryBtn(){
  const b = $('#btn-retry');
  if (b) b.onclick = () => {
    _booted = false;
    _hintTimer = setTimeout(slowHint, 6000);
    _bootTimer = setTimeout(notReady, 20000);
    boot();
  };
}

function slowHint(){
  if (_booted) return;
  $('#sub').innerHTML = '正在读……（后端起来得有点慢，再等一会儿）' +
    '<button class="btn" id="btn-retry" style="margin-left:8px">重试</button>';
  _retryBtn();
}

function notReady(){
  if (_booted) return;
  $('#sub').innerHTML = '读不出来 —— 后端没上来。' +
    '<button class="btn" id="btn-retry" style="margin-left:8px">重试</button>' +
    '<br><span class="dim">（关掉这个界面重开一次也行；要是还不行，' +
    '把 <code>moss :skill</code> 在终端里跑一遍看它报什么。）</span>';
  _retryBtn();
}

moss.on('ready', boot);
/* ★ 桥可能在 `ready` 之前就绪、也可能 `ready` 已经错过 ⇒ **独立窗口**那条路一直自己轮询；
   而**内嵌**那条路老实等垫片的 `ready`：宿主是靠那个握手把这一帧登记下来的
   （`EMB.alive[pid]`），抢在它前面调 `list` 反而可能被丢掉。谁先到算谁，`boot()` 幂等。 */
if (!(moss.env && moss.env.embedded)){
  (function waitBridge(){
    if (_booted) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.list){ boot(); return; }
    setTimeout(waitBridge, 500);
  })();
}
_hintTimer = setTimeout(slowHint, 6000);
_bootTimer = setTimeout(notReady, 20000);

