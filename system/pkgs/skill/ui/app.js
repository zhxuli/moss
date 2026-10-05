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
  const skills = (DATA && DATA.skills) || [];
  const pkgs = (DATA && DATA.from_pkgs) || [];
  skills.forEach((it) => wall.appendChild(tile(it)));
  if (pkgs.length) {
    const sep = document.createElement('h2');
    sep.className = 'sec';
    sep.textContent = '来自插件（pkg.json 里声明了 ai.expose = true —— AI 也能调）';
    sep.style.gridColumn = '1 / -1';
    wall.appendChild(sep);
    pkgs.forEach((it) => wall.appendChild(tile(it)));
  }
  $('#empty').hidden = !!(skills.length || pkgs.length);
  const pend = skills.concat(pkgs).filter((x) => !x.problems.length && !x.allowed).length;
  $('#sub').textContent = skills.length + ' 只技能（能用 ' + DATA.n_usable + '）' +
    (pkgs.length ? ' · ' + pkgs.length + ' 个插件也暴露给 AI' : '') +
    (pend ? ' · ' + pend + ' 只等你允许' : '') + ' · ' + DATA.dir;
}

/* ---------------------------------------------------------------- 详情 */
function find(id) {
  const all = ((DATA && DATA.skills) || []).concat((DATA && DATA.from_pkgs) || []);
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
  const st = status(it);
  const canPromote = it.kind === 'skill' && it.layer === 'user';
  const chips = [];
  chips.push('<span class="chip ' + (st.dot === 'bad' ? 'bad' : (st.dot === 'pending' ? 'warn' : 'ok')) +
    '">' + esc(it.allowed ? 'AI 可以用它' : (it.problems.length ? '进不了工具表' : '还没允许')) + '</span>');
  if (it.origin === 'seed') chips.push('<span class="chip">出厂样例</span>');
  if (it.risk) chips.push('<span class="chip">风险 ' + esc(it.risk) + '</span>');
  (it.params || []).forEach((p) => chips.push('<span class="chip">' + esc(p) + '</span>'));
  (it.warns || []).forEach((w) => chips.push('<span class="chip warn">' + esc(w) + '</span>'));
  (it.problems || []).forEach((w) => chips.push('<span class="chip bad">' + esc(w) + '</span>'));

  $('#detail').hidden = false;
  $('#detail').innerHTML =
    '<div class="dhead">' +
      '<div class="ico">' + iconHTML(it) + '</div>' +
      '<div class="dtitle"><h3>' + esc(it.name) + '</h3>' +
        '<div class="id">' + esc(it.id) + '</div>' +
        '<div class="dim">' + esc(it.desc || '（没写说明）') + '</div></div>' +
      '<div class="dacts">' +
        (it.layer === 'user' && !it.problems.length
          ? '<button class="btn" id="d-allow">' + (it.allowed ? '撤销允许' : '允许') + '</button>' : '') +
        (it.allowed ? '<button class="btn" id="d-run" title="像 AI 那样跑一次（空参数）">试跑一次</button>' : '') +
        (canPromote ? '<button class="btn" id="d-promote">转为插件</button>' : '') +
        '<button class="btn" id="d-open">打开目录</button>' +
        (it.layer === 'user' ? '<button class="btn danger" id="d-rm">删除</button>' : '') +
        '<button class="btn" id="d-back">返回</button>' +
      '</div>' +
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
    '<div><b>文件（' + it.files_n + '）</b>' + filesTable(it) + '</div>';

  const on = (sel, fn) => { const b = $(sel); if (b) b.onclick = fn; };
  on('#d-back', () => { $('#detail').hidden = true; CUR = null; });
  on('#d-allow', () => call('allow', { id: it.id, yes: !it.allowed }));
  on('#d-open', () => call('reveal', { dir: it.dir }, true));
  on('#d-rm', () => confirmBox('删掉这只技能？',
    '删掉 <code>' + esc(it.id) + '</code> 的整个目录（' + it.files_n + ' 个文件）？\n' + it.dir,
    () => call('rm', { id: it.id, confirm: true })));
  on('#d-run', () => call('run_once', { id: it.id, args: {} }, true));
  on('#d-promote', () => promoteFlow(it));
  document.querySelectorAll('#detail tr.file').forEach((tr) => {
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
    DATA = got || { skills: [], from_pkgs: [], n_usable: 0, dir: '' };
    render();
    if (CUR) { const it = find(CUR.id); if (it) showDetail(it.id); else { $('#detail').hidden = true; CUR = null; } }
  }).catch((e) => { $('#sub').textContent = '读不出来：' + (e && e.message ? e.message : e); });
}

/* 初始化：等垫片的 ready（内嵌时它是宿主派活之后发的） */
moss.on('ready', () => {
  load();
  $('#btn-reload').onclick = load;
  $('#btn-seed').onclick = () => call('seed', {});
  $('#btn-open').onclick = () => call('reveal', { dir: (DATA && DATA.dir) || '' }, true);
});
