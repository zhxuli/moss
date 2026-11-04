'use strict';
/* 极简同步 —— 前端（三段垂直流）
   ============================================================================
   界面就一条竖线：本地工作区 → 本地历史记录 → GitHub 云端，中间是管道。
   状态自己抢焦点（不用 Tab、不用菜单）：
     有未保存改动 → 第一段琥珀发光、管道 1 往下流
     有版本待备份 → 第二段电光蓝、管道 2 往下流
     云端有新版本 → 第三段引力紫、管道 2 往上流
   全部对齐 → 三段都退成静默态（半透明、低调）。

   ★ 不引任何外部资源：图标是下面 ICON 表里的内嵌 SVG（照 lucide 的画法手画的线条），
     样式全在 style.css 里手写。
   ★ 所有数据都来自后端（main.py）的真 git 仓库状态，没有一处是假数据。
   ============================================================================ */

/* ---------------------------------------------------------------- 图标 */
var ICON = {
  feather: '<path d="M20.2 3.8a5 5 0 0 0-7 0L4 13v7h7l9.2-9.2a5 5 0 0 0 0-7z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M16 8 8 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3c.7 0 1.3.3 1.7.9l1 1.4h7.3A2.5 2.5 0 0 1 21 9.8v7.7A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  refresh: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/><path d="M20.5 3.8v4.7h-4.7" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
  laptop: '<rect x="4" y="5" width="16" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M2.5 19.2h19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  history: '<path d="M3.6 12a8.4 8.4 0 1 0 2.6-6.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M3.2 4.5v4.4h4.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 8v4.3l3 1.8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  cloud: '<path d="M7.6 18.5h8.9a3.5 3.5 0 0 0 .5-6.95A5.2 5.2 0 0 0 7.05 9.9 4.05 4.05 0 0 0 7.6 18.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  chevronDown: '<path d="M6 9.5 12 15.5 18 9.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  arrowDown: '<path d="M12 5v13M12 18l-4.5-4.5M12 18l4.5-4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  arrowUp: '<path d="M12 19V6M12 6 7.5 10.5M12 6l4.5 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  rotate: '<path d="M3.6 12a8.4 8.4 0 1 1 2.9 6.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M3.2 17.5V13h4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  x: '<path d="M4 4 12 12M12 4 4 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  chart: '<path d="M3 13.2V9.6M7.6 13.2V5.4M12.2 13.2V7.8M16.8 13.2V3.4"/>',
  warn: '<path d="M8 2.6 14.6 14H1.4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 6.4v3.2M8 11.6v.1" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  check: '<path d="M3 8.6 6.4 12 13 4.8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
  link: '<path d="M6.6 9.4a2.6 2.6 0 0 1 0-3.7l1.6-1.6a2.6 2.6 0 1 1 3.7 3.7l-.9.9M9.4 6.6a2.6 2.6 0 0 1 0 3.7l-1.6 1.6a2.6 2.6 0 1 1-3.7-3.7l.9-.9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  search: '<circle cx="6.6" cy="6.6" r="4.4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M10.2 10.2 14 14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  check: '<path d="m4.5 12.5 5 5 10-11" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>',
  eye: '<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  plus: '<path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  branch: '<path d="M7 5v9.5A3.5 3.5 0 0 0 10.5 18H17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="7" cy="4.3" r="1.9" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="17.6" cy="6.6" r="1.9" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="17.6" cy="18" r="1.9" fill="none" stroke="currentColor" stroke-width="1.7"/>',
  tag: '<path d="M4.5 12.4 12 5h7v7l-7.5 7.5a1.4 1.4 0 0 1-2 0L4.5 14.4a1.4 1.4 0 0 1 0-2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="15.6" cy="8.5" r="1.2" fill="currentColor"/>',
  command: '<rect x="3" y="5" width="18" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m7.5 10 2.6 2.2-2.6 2.2M12.8 14.6h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  mirror: '<rect x="3.4" y="5" width="7.4" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><rect x="13.2" y="6.6" width="7.4" height="10.8" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-dasharray="3 2.2"/>',
  drive: '<circle cx="12" cy="12" r="8.4" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="2.3" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  sparkles: '<path d="M12 4.4 13.5 9.9 19 11.4 13.5 12.9 12 18.4 10.5 12.9 5 11.4 10.5 9.9z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
  download: '<path d="M12 4.5v10M12 14.5 8.5 11M12 14.5 15.5 11" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 18.5h14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
  wifi: '<path d="M3.5 9.5a12.5 12.5 0 0 1 17 0M6.8 13a8 8 0 0 1 10.4 0M10 16.4a3.4 3.4 0 0 1 4 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="19.4" r="1.2" fill="currentColor"/>',
  save: '<path d="M5 5h10l4 4v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8.5 5v4.5h6V5M8.5 20v-5.5h7V20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  undo: '<path d="M9 7.5 4.5 12 9 16.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/><path d="M4.5 12h9a6 6 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
};
function svg(name) {
  return '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICON[name] || '') + '</svg>';
}
function put(id, name) {
  var n = el(id);
  if (n) { n.innerHTML = svg(name); }
}

/* ---------------------------------------------------------------- 小工具 */
function el(id) { return document.getElementById(id); }
function sub(s) { return document.querySelector(s); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function n0(v) { return (v === null || v === undefined) ? 0 : v; }
function baseName(p) {
  return String(p || '').split(/[\\/]+/).filter(function (x) { return x; }).pop() || String(p || '');
}
function samePath(a, b) {
  var f = function (x) { return String(x || '').replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase(); };
  return !!f(a) && f(a) === f(b);
}
function stamp() {
  var d = new Date(), p = function (v) { return (v < 10 ? '0' : '') + v; };
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

/* ---------------------------------------------------------------- 忙碌 / 提示 */
var busyN = 0, busyT = null;
function busyOn(t) {
  busyN++;
  if (busyN > 1) { return; }
  busyT = setTimeout(function () {
    var x = el('busyText'); if (x) { x.textContent = t || '正在处理…'; }
    el('busy').classList.add('show');
  }, 120);
}
function busyOff() {
  busyN = Math.max(0, busyN - 1);
  if (!busyN) { clearTimeout(busyT); el('busy').classList.remove('show'); }
}
function log(t) { var x = el('log'); if (x) { x.textContent = t; } }
function toast(text, kind) {
  var box = el('toastBox'), t = document.createElement('div');
  t.className = 'toast ' + (kind || '');
  t.textContent = text;
  box.appendChild(t);
  setTimeout(function () { t.classList.add('out'); }, 4200);
  setTimeout(function () { if (t.parentNode) { t.parentNode.removeChild(t); } }, 5000);
}

/* ---------------------------------------------------------------- 跟后端说话 */
function call(m, p) {
  if (!window.moss || typeof moss.call !== 'function') {
    return Promise.reject(new Error('界面垫片 moss-embed.js 没加载'));
  }
  return Promise.resolve(moss.call(m, p || {}));
}
function fail(e) {
  var why = (e && e.message) ? e.message : String(e);
  log('出了点问题：' + why);
  toast('出了点问题：' + why, 'no');
}

/* ------------------------------------------------ v12：搜索 / 快捷填入（小配件）
   ★ 列表是"重画"的，输入框本身在 HTML 里、不会被换掉，所以边打字边筛不会丢焦点。 */
function bindSearch(inputId, wrapId) {
  var inp = el(inputId), wrap = el(wrapId);
  if (!inp || !wrap) { return; }
  var isLocal = (inputId === 'qLocal');
  inp.addEventListener('input', function () {
    var q = inp.value.trim();
    wrap.classList.toggle('has-q', !!q);
    if (isLocal) { S.qLocal = q; } else { S.qCloud = q; }
    syncUI();
  });
  var x = wrap.querySelector('.sx');
  if (x) {
    x.addEventListener('click', function () {
      inp.value = '';
      wrap.classList.remove('has-q');
      if (isLocal) { S.qLocal = ''; } else { S.qCloud = ''; }
      syncUI();
      inp.focus();
    });
  }
}

/* 「快捷填入」：点一下把常用的开头填进说明框（已经填过就不重复堆） */
function bindQuickFill() {
  Array.prototype.forEach.call(document.querySelectorAll('.qf'), function (b) {
    b.addEventListener('click', function () {
      var note = el('note'); if (!note) { return; }
      var t = b.getAttribute('data-text') || '';
      if (note.value.indexOf(t) < 0) { note.value = t + note.value; }
      note.focus();
    });
  });
}

/* ============================================================ v14：环境状态
   这一块的目标只有一个：**任何"用不了"都必须在界面上说出来，并给一颗能点的按钮。**
   （之前"没装 git"和"这文件夹不是仓库"长得一模一样，人只能猜 —— 真机反馈过。）
   ============================================================================ */
var ENV_STEPS = {
  git: '这台电脑上还没有 git —— 记录版本、保存、上传全靠它，先把它装上。',
  gh: '缺 gh（GitHub CLI）。装了它，「备份到云端」就能替你**一键建仓库并上传**，'
      + '不用你手动去网站建好了再贴地址进来。',
  login: 'GitHub 还没登录。登录之后才能真正上传；没登录也能在本地存版本，只是传不上去。',
  id: '还没填署名。不填的话第一次「保存版本」会失败（报错叫 Author identity unknown），'
      + '我替你填一个就行。',
  net: '连不上 github.com。本地保存不受影响，但上传/拉取暂时不行 —— 有代理的话打开代理再试。'
};

/* 带超时的 Promise：界面**绝不允许**无限等下去（真机反馈"点了一下就卡着，
   等一分钟也不行"——后端一条线程被 git/gh 拖住时，前端就是这么干等的） */
function withTimeout(p, ms, tag) {
  return new Promise(function (resolve, reject) {
    var done = false;
    var t = setTimeout(function () {
      if (!done) { done = true; reject(new Error('TIMEOUT:' + (tag || ''))); }
    }, ms);
    Promise.resolve(p).then(function (v) {
      if (!done) { done = true; clearTimeout(t); resolve(v); }
    }, function (e) {
      if (!done) { done = true; clearTimeout(t); reject(e); }
    });
  });
}

/* 拉一次环境状态，画到顶部那条 + 决定按钮给几颗
   ★ 8 秒还不回来就明确说"太慢 / 超时了"，并给命令行自查的办法，不让人对着转圈发愣。 */
function refreshEnv(fresh) {
  /* 等待上限 6 秒：真机上一分钟都没反应，这个上限必须硬 */
  return withTimeout(call('env_check', { path: S.path, fresh: fresh ? 1 : 0 }), 6000, 'env')
    .then(function (r) {
      S.env = r || {};
      S.envTimeout = false;
      paintEnv();
      return r;
    }).catch(function (e) {
      var msg = String((e && e.message) || e);
      S.env = S.env || {};
      S.envTimeout = true;
      paintTimeout(msg.indexOf('TIMEOUT') === 0);
      return S.env;
    });
}

/* 超时/出错时顶部那条长什么样 */
function paintTimeout(isTimeout) {
  var bar = el('envBar');
  if (!bar) { return; }
  bar.className = 'envbar red';
  el('envIco').innerHTML = svg('warn');
  el('envTitle').textContent = isTimeout ? '环境检查太慢，先不等了' : '环境检查没跑起来';
  el('envSub').textContent = isTimeout
    ? '多半是这台机器上 git 或 gh 在某一步卡住了（网络/大目录）。界面不会被它拖住，可以照常干活。'
    : '界面和后端没通上。关掉界面重新打开这个包试试。';
  el('envBtns').innerHTML =
    '<button class="env-btn alt" data-act="env-recheck">再试一次</button>' +
    '<button class="env-btn alt" data-act="env-detail">看详情</button>';
}

function paintEnv() {
  var bar = el('envBar');
  if (!bar) { return; }
  var e = S.env || {};
  var items = e.items || [];
  var bad = items.filter(function (i) { return i.state === 'bad'; });
  var warn = items.filter(function (i) { return i.state === 'warn'; });

  /* 正在装东西时，状态条优先报"正在装"（带秒数），别的都往后放 */
  if (e.pendingInstall) {
    var pw = e.pendingInstall.what || '';
    bar.className = 'envbar';
    el('envIco').innerHTML = svg('download');
    el('envTitle').textContent = '正在装 ' + (pw === 'git' ? 'Git' : 'GitHub CLI') + '…';
    el('envSub').textContent = '已经 ' + (e.pendingInstall.secs || 0) + ' 秒' +
      ' —— 进度和日志都在「看进度」里，可以关掉窗口，装完我会告诉你。';
    el('envBtns').innerHTML =
      '<button class="env-btn" data-act="env-progress" data-what="' + esc(pw) + '">看进度</button>' +
      '<button class="env-btn alt" data-act="env-recheck">再检查一次</button>';
    /* 三秒后再看一次，让秒数自己走（只在这一种状态下才定时） */
    if (S.envTimer) { clearTimeout(S.envTimer); }
    S.envTimer = setTimeout(function () {
      S.envTimer = null;
      refreshEnv();
    }, 3000);
    return;
  }
  if (S.envTimer) { clearTimeout(S.envTimer); S.envTimer = null; }

  /* 全好：不占地方，收起来（只在缺东西时才占一条） */
  if (!bad.length && !warn.length && !e.pendingInstall) {
    bar.className = 'envbar ok';
    if (items.length && !S.envSeen) {
      /* 第一次检查就全好 —— 也别刷屏，直接收起来 */
      bar.classList.add('hide');
      S.envSeen = 1;
      return;
    }
    S.envSeen = 1;
    el('envIco').innerHTML = svg('check');
    el('envTitle').textContent = '环境都齐了';
    el('envSub').textContent = 'Git、署名、GitHub 登录、网络都正常。';
    el('envBtns').innerHTML = '<button class="env-btn alt" data-act="env-detail">看详情</button>';
    return;
  }

  bar.className = 'envbar' + (bad.length ? ' red' : '');
  el('envIco').innerHTML = svg(bad.length ? 'warn' : 'warn');
  /* 一次只说**一件最要紧的**，别把五条错误糊人一脸 */
  var first = bad[0] || warn[0] || {};
  var rest = bad.length + warn.length - 1;
  el('envTitle').textContent = bad.length
    ? ('还差一步才能用：' + (first.label || ''))
    : ('建议补上：' + (first.label || ''));
  el('envSub').textContent = (first.detail || '')
    + (rest > 0 ? '（另外还有 ' + rest + ' 项，点「看详情」）' : '');

  var h = '';
  if (first.fix === 'install_git') {
    h += '<button class="env-btn" data-act="env-install" data-what="git">帮我装 Git</button>' +
         '<button class="env-btn alt" data-act="env-open" data-url="' + URL_GIT_DL + '">下载页</button>';
  } else if (first.fix === 'install_gh') {
    h += '<button class="env-btn" data-act="env-install" data-what="gh">帮我装 gh</button>' +
         '<button class="env-btn alt" data-act="env-detail">看看别的办法</button>';
  } else if (first.fix === 'gh_login') {
    h += '<button class="env-btn" data-act="env-login">登录 GitHub</button>' +
         '<button class="env-btn alt" data-act="env-open" data-url="' + URL_SIGNUP + '">还没有账号？注册</button>';
  } else if (first.fix === 'identity') {
    h += '<button class="env-btn" data-act="env-identity">帮我填好</button>';
  } else {
    h += '<button class="env-btn alt" data-act="env-detail">看详情</button>';
  }
  h += '<button class="env-btn alt" data-act="env-recheck" title="装完 / 登录完之后点这个">再检查一次</button>';
  /* 真搞不定时的最后一颗按钮：一键把这段求助文字复制走，粘给 moss 的 AI 就行 */
  h += '<button class="env-btn alt" data-act="env-askai" title="把现在的情况复制成一段话，粘给 AI">告诉 AI</button>';
  if (!bad.length) {
    /* 本地能用、只是传不上云：给一条"也能不装 gh"的退路 */
    h += '<button class="env-btn alt" data-act="env-detail">别的办法</button>';
  }
  el('envBtns').innerHTML = h;
  S.envSeen = 1;
}

var URL_GIT_DL = 'https://git-scm.com/download/win';
var URL_GH_DL = 'https://cli.github.com/';
var URL_SIGNUP = 'https://github.com/signup';

/* 环境详情：把每一条都摆出来，每条该点什么 */
function dialogEnv() {
  openModal('环境检查', '<div class="note">正在检查…（最多等 8 秒，不会一直转）</div>',
    [{ text: '再检查一次', key: 'ok', kind: 'primary' },
     { text: '关闭', key: 'close', kind: 'ghost' }], true);
  /* ★ 「再检查一次」要强制重查（fresh=1），否则 4 秒缓存会让你以为没反应 */
  S.modalActs.ok = function () { refreshEnv(true).then(function () { dialogEnv(); }); };
  refreshEnv(true).then(function (r) {
    var e = r || S.env || {};
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    /* 超时 / 后端没答：把话说清楚，别留一个"正在检查…" */
    if (S.envTimeout) {
      b.innerHTML = '<div class="note"><b>这次检查没能按时完成。</b><br>' +
        '多半是这台机器上 git 或 gh 在某一步卡住了（网络不通 / 目录特别大）。' +
        '<br>界面不会因此卡死，你可以照常保存、上传。</div>' +
        '<div class="note">想直接看结论，可以在命令行敲：<br>' +
        '<span class="hintline">moss :github action=env_check</span></div>';
      return;
    }
    var mark = { ok: '✓', warn: '!', bad: '✗', skip: '·' };
    var h = '<div class="note">这一屏就是"为什么用不了 / 还差什么"。' +
      '缺的东西我能替你装的都直接装了，装不了的给你下载页。</div><div class="envlist">';
    (r.items || []).forEach(function (i, n) {
      h += '<div class="envrow ' + i.state + '">' +
        '<span class="st">' + (mark[i.state] || '?') + '</span><div class="bd">' +
        '<div class="lb">' + esc(i.label) + '</div>' +
        '<div class="dt">' + esc(i.detail || '') + '</div>' +
        (i.extra ? '<div class="dt">' + esc(i.extra) + '</div>' : '') +
        (i.help && i.state !== 'ok' ? '<div class="hp">' + esc(i.help) + '</div>' : '') +
        '<div class="row-btns">';
      if (i.fix === 'install_git') {
        h += '<button class="env-btn" data-act="env-install" data-what="git">帮我装</button>';
      } else if (i.fix === 'install_gh') {
        h += '<button class="env-btn" data-act="env-install" data-what="gh">帮我装</button>';
      } else if (i.fix === 'gh_login') {
        h += '<button class="env-btn" data-act="env-login">登录 GitHub</button>';
      } else if (i.fix === 'identity') {
        h += '<button class="env-btn" data-act="env-identity">帮我填好</button>';
      }
      if (i.key === 'gh' || i.key === 'git') {
        h += '<button class="env-btn alt" data-act="env-open" data-url="' +
          (i.key === 'git' ? URL_GIT_DL : URL_GH_DL) + '">手动下载页</button>';
      }
      if (i.key === 'login') {
        h += '<button class="env-btn alt" data-act="env-open" data-url="' + URL_SIGNUP +
          '">注册 GitHub</button>';
      }
      h += '</div></div></div>';
    });
    h += '</div>';
    h += '<div class="note" style="padding:4px 0 8px">' +
      '<button class="env-btn alt" data-act="env-askai">把这段情况复制给 AI</button></div>';
    if (e.next) {
      h += '<div class="note"><b>下一步：</b>' + esc(e.next) + ' —— ' + esc(e.nextText || '') + '</div>';
    } else {
      h += '<div class="note">该有的都齐了，可以正常用。</div>';
    }
    h += '<div class="note">' + esc(e.help || '') + '</div>';
    if (e.pendingInstall) {
      h += '<div class="note">刚才那次安装（' + esc(e.pendingInstall.what) + '）是 '
        + esc(e.pendingInstall.ago) + ' 起步的 —— 装完点「再检查一次」。</div>';
    }
    b.innerHTML = h;
  });
}

/* 帮人装：点了之后立刻说清"接下来会发生什么"，别让人对着没反应的屏幕猜 */
/* ==================================================== 装东西：进度条 + 实时日志
   ★ 这一段是照真机反馈重写的：第一版点了「帮我装 gh」之后**既没进度条也没日志**，
     只能干等，人根本不知道在动还是在卡。现在：
       ① 点下去**立刻**出窗口（不等后端返回，避免"点了没反应"）；
       ② 每秒问一次后端「到哪一步了」，画进度条 + 读日志尾巴；
       ③ 装完 / 失败都当场换成对应的脸，并把下一步按钮摆好。
   ============================================================================ */
var INST = { timer: null, what: '', t0: 0, lastLog: '', lastBtnSig: '', lastSig: '' };

function stopInstPoll() {
  if (INST.timer) { clearInterval(INST.timer); INST.timer = null; }
}

function instFace(what, st) {
  var label = (what === 'git') ? 'Git' : 'GitHub CLI';
  var secs = (st && st.secs) || Math.round((Date.now() - INST.t0) / 1000);
  var phase = (st && st.phase) || 'run';
  var say = (st && st.text) || '正在准备…';
  var pct = (st && typeof st.percent === 'number') ? st.percent : null;
  var done = !!st && st.phase === 'done';
  var bad = !!st && st.phase === 'fail';

  var bar = done
    ? '<div class="pbar done"><i style="width:100%"></i></div>'
    : (bad ? '<div class="pbar bad"><i style="width:100%"></i></div>'
      : (pct === null
        ? '<div class="pbar indet"><i></i></div>'          /* 抠不到百分比就走不确定态 */
        : '<div class="pbar"><i style="width:' + pct + '%"></i></div>'));

  var head =
    '<div class="inst-head">' +
    (done ? '<span class="inst-ico ok">' + svg('check') + '</span>'
      : (bad ? '<span class="inst-ico no">' + svg('warn') + '</span>'
        : '<span class="inst-spin"></span>')) +
    '<div class="inst-txt"><div class="inst-title">' +
    (done ? (label + ' 装好了') : (bad ? (label + ' 没装成') : (say + ' ' + label + '…'))) +
    '</div><div class="inst-sub">' +
    (done ? ('一共花了 ' + secs + ' 秒。下一步：登录 GitHub。')
      : (bad ? ('用了 ' + secs + ' 秒，看下面的日志。')
        : ('已经 ' + secs + ' 秒' + (pct !== null ? ' · ' + pct + '%' : '') +
           ' · 可以关掉这个窗口，安装会继续'))) +
    '</div></div></div>';
  /* ★ 注意：进度条只在最后拼一次（以前这里多写了个 `+ bar`，
     结果界面上出现两条一模一样的进度条 —— 真机反馈过）。 */

  var log = (st && st.log) ? st.log : '';
  var box = '<div class="inst-logbox"><div class="inst-loglabel">安装日志（实时）</div>' +
    '<pre class="inst-log" id="instLog">' + esc(log || '（还没输出，等一下下…）') + '</pre></div>';
  /* 卡住了就说清"可能卡在哪、还能怎么办" —— 别让人干等 */
  var hint = (st && st.hint) ? '<div class="inst-hint">' + esc(st.hint) + '</div>' : '';

  return head + bar + hint + box;
}

function instButtons(what, st) {
  var done = !!st && st.phase === 'done';
  var bad = !!st && st.phase === 'fail';
  var label = (what === 'git') ? 'Git' : 'GitHub CLI';
  if (done) {
    return [{ text: what === 'gh' ? '登录 GitHub' : '再检查一次', key: 'next', kind: 'primary' },
            { text: '关闭', key: 'close', kind: 'ghost' }];
  }
  if (bad) {
    return [{ text: '打开下载页', key: 'dl', kind: 'primary' },
            { text: '再检查一次', key: 'next', kind: 'ghost' },
            { text: '关闭', key: 'close', kind: 'ghost' }];
  }
  return [{ text: '装好了？再检查一次', key: 'next', kind: 'ghost' },
          { text: '关掉窗口（安装继续）', key: 'close', kind: 'ghost' }];
}

function envInstall(what) {
  var label = (what === 'git') ? 'Git' : 'GitHub CLI';
  INST.what = what;
  INST.t0 = Date.now();
  INST.lastLog = '';      /* 换一次安装就重来，否则日志框会沿用上一次的内容 */
  INST.lastBtnSig = '';

  /* ① 立刻出窗口：先给一个"正在启动"，不让屏幕空着 */
  openModal('正在装 ' + label,
    instFace(what, { phase: 'run', text: '正在启动', secs: 0, log: '' }),
    instButtons(what, null), true);
  S.modalActs.next = function () { refreshEnv().then(dialogEnv); };
  S.modalActs.dl = function () { call('open_url', { url: what === 'git' ? URL_GIT_DL : URL_GH_DL }); };

  /* ★★ ② 关键顺序：**先起轮询，再发"开始装"**。
     以前是先等 `install_tool` 回话、回到话里才起轮询 —— 那个响应一旦不回来
     （内嵌模式下宿主串行转发，慢调用会把后面全堵住），轮询就永远不启动，
     界面死死停在"正在启动 已经 0 秒"，等多久都一样（真机就是这样）。
     现在不管那个响应来不来，进度都会自己往下走。 */
  startInstPoll(what);

  /* ③ 再真的去装（它的回复只用来补充说明，不影响进度） */
  call('install_tool', { what: what }).then(function (r) {
    /* ★★ 后端说"已经装好了"（`installed`）：**立刻收摊**，不要再假装装一遍。
       真机踩过：界面上的状态是旧的，人一点就重下一份，装十次都是同一个结果。 */
    if (r && r.installed) {
      stopInstPoll();
      INST.what = '';
      openModal(label + ' 已经装好了', 
        '<div class="note">' + esc(r.why || (label + ' 已经装好了')) + '</div>' +
        '<div class="note">不用再装 —— 这一步可以直接关掉这个窗口。' +
        '下面那条环境提示我也会顺手刷新。</div>',
        [{ text: '好', key: 'close', kind: 'primary' }], true);
      refreshEnv(true);
      return;
    }
    if (!r.ok && !r.started) {
      stopInstPoll();
      openModal('我这边装不了 ' + label,
        '<div class="note">' + esc(r.why || '') + '</div>' +
        (r.opened ? '<div class="note">下载页已经替你打开了。装完（一路「下一步」）回到这里点「再检查一次」。</div>'
          : ''),
        [{ text: '打开下载页', key: 'dl', kind: 'primary' },
         { text: '再检查一次', key: 'next', kind: 'ghost' },
         { text: '关闭', key: 'close', kind: 'ghost' }], true);
      S.modalActs.dl = function () { call('open_url', { url: r.url || URL_GH_DL }); };
      S.modalActs.next = function () { refreshEnv().then(dialogEnv); };
      refreshEnv();
      return;
    }
    toast(r.already ? (label + ' 已经在装了') : ('开始装 ' + label + ' 了，看进度'), 'ok');
  }).catch(function (e) {
    /* ★ 触发失败也**不能撤掉进度窗**（以前这里 stopInstPoll + 一闪而过的提示，
       人看到的就是"弹窗永远停在正在启动 0 秒"）。把原因写进窗口里，让进度继续试。 */
    var why = (e && e.message) || String(e);
    var sub2 = sub('.inst-sub');
    if (sub2) { sub2.textContent = '启动请求没成功（' + why + '），正在重试…'; }
    var boxWrap = sub('.inst-logbox');
    if (boxWrap && !sub('.inst-hint')) {
      var d = document.createElement('div');
      d.className = 'inst-hint';
      d.textContent = '启动请求出错了：' + why +
        '。我会继续查状态；实在不行就点「打开下载页」手动装。';
      boxWrap.parentNode.insertBefore(d, boxWrap);
    }
    INST.startFailed = why;
  });
}

/* 把一次安装状态**就地画到已有窗口上**（不重画整窗）。
   ★ 以前是"变了就 openModal 重画一遍"，副作用是日志框被重建、滚动位置丢失、
     而且每重画一次窗口就闪一下。现在只改文字和进度条宽度。 */
function paintInst(what, st) {
  var label = (what === 'git') ? 'Git' : 'GitHub CLI';
  var phase = (st && st.phase) || 'run';
  var done = phase === 'done', bad = phase === 'fail';
  /* 秒数取"后端说的"和"我们自己掐的表"里大的那个 ——
     后端没回话时也能继续走，绝不冻在 0 秒（真机就是这个症状）。 */
  var secs = Math.max((st && st.secs) || 0, Math.round((Date.now() - INST.t0) / 1000));
  var pct = (st && typeof st.percent === 'number') ? st.percent : null;

  var t = sub('.inst-title');
  if (t) {
    t.textContent = done ? (label + ' 装好了')
      : (bad ? (label + ' 没装成') : ((st.text || '正在装') + ' ' + label + '…'));
  }
  var s = sub('.inst-sub');
  if (s) {
    s.textContent = done
      ? ('一共花了 ' + secs + ' 秒。' + (what === 'gh' ? '下一步：登录 gh（可选）。' : '下一步：再检查一次。'))
      : (bad ? ('用了 ' + secs + ' 秒，看下面的日志。')
        : ('已经 ' + secs + ' 秒' + (pct !== null ? ' · ' + pct + '%' : '') +
           ' · 可以关掉这个窗口，安装会继续'));
  }
  /* 转圈 / 对勾 / 警告 */
  var ico = sub('.inst-ico') || sub('.inst-spin');
  if (ico) {
    if (done) { ico.className = 'inst-ico ok'; ico.innerHTML = svg('check'); }
    else if (bad) { ico.className = 'inst-ico no'; ico.innerHTML = svg('warn'); }
  }
  /* 进度条：确定百分比 / 不确定 / 完成 / 失败 */
  var bar = sub('.pbar');
  if (bar) {
    bar.className = 'pbar' + (done ? ' done' : (bad ? ' bad' : (pct === null ? ' indet' : '')));
    var fill = bar.querySelector('i');
    if (fill) { fill.style.width = (pct === null && !done && !bad) ? '' : ((pct === null ? 100 : pct) + '%'); }
  }
  /* 日志：跟着滚到底 */
  var box = el('instLog');
  if (box && st && st.log && st.log !== INST.lastLog) {
    INST.lastLog = st.log;
    box.textContent = st.log;
    box.scrollTop = box.scrollHeight;
  }
  /* 提示（卡在哪、还能怎么办） */
  var old = sub('.inst-hint');
  if (st && st.hint) {
    if (old) { old.textContent = st.hint; }
    else {
      var boxWrap = sub('.inst-logbox');
      if (boxWrap) {
        var d = document.createElement('div');
        d.className = 'inst-hint';
        d.textContent = st.hint;
        boxWrap.parentNode.insertBefore(d, boxWrap);
      }
    }
  } else if (old) { old.remove(); }
}

/* 按钮也按状态换（装好了就该出现「登录 gh」） */
function paintInstButtons(what, st) {
  var sig = [what, st && st.phase].join('|');
  if (sig === INST.lastBtnSig) { return; }
  INST.lastBtnSig = sig;
  var f = sub('.dlg-f');
  if (!f) { return; }
  f.innerHTML = '';
  instButtons(what, st).forEach(function (b) {
    var btn = document.createElement('button');
    btn.className = 'dbtn ' + (b.kind || 'ghost');
    btn.setAttribute('data-act', 'modal-' + b.key);
    btn.textContent = b.text;
    f.appendChild(btn);
  });
  /* 「下一步」按状态给对的东西：装好 gh 就该直接去登录，别让人再翻菜单 */
  S.modalActs.next = function () {
    if (st && st.phase === 'done' && what === 'gh') {
      closeModal();
      envLogin();
    } else {
      refreshEnv().then(dialogEnv);
    }
  };
  S.modalActs.dl = function () { call('open_url', { url: what === 'git' ? URL_GIT_DL : URL_GH_DL }); };
}

/* 带超时的 call。
   ★ 内嵌模式下宿主是串行转发的：一个慢调用会把后面的全堵住，而 `moss.call`
     的 promise 没有超时 —— 一旦不回来，等多久都是它。所以这里自己掐表。 */
function callTimeout(m, p, ms) {
  return new Promise(function (resolve, reject) {
    var done = false;
    var t = setTimeout(function () {
      if (!done) { done = true; reject(new Error('等 ' + Math.round((ms || 8000) / 1000) + ' 秒没回话')); }
    }, ms || 8000);
    var q;
    try { q = call(m, p); } catch (e) { done = true; clearTimeout(t); reject(e); return; }
    if (!q || !q.then) { done = true; clearTimeout(t); reject(new Error('没拿到异步结果')); return; }
    q.then(function (v) { if (!done) { done = true; clearTimeout(t); resolve(v); } },
           function (e) { if (!done) { done = true; clearTimeout(t); reject(e); } });
  });
}

/* 每秒读一次进度。
   ★ 三条铁律（都是真机踩出来的）：
     ① 任何一次读都**必须带超时**，否则一个不回来的请求会让界面永远停在"0 秒"；
     ② 读不到也要**把计时刷起来**，让人觉得界面是活的、只是后端慢；
     ③ 别急着下结论：刚开始那几秒后端可能还没写好状态，要容忍几次"没有记录"。 */
function startInstPoll(what) {
  stopInstPoll();
  var tick = 0, silent = 0, noneSeen = 0;
  function local() { return Math.round((Date.now() - INST.t0) / 1000); }

  function poll() {
    if (!el('modal') || !el('modal').classList.contains('show')) { stopInstPoll(); return; }
    callTimeout('install_status', { what: what }, 8000).then(function (st) {
      silent = 0;
      if (!el('modal') || !el('modal').classList.contains('show')) { stopInstPoll(); return; }
      if (!st || st.phase === 'none') {
        noneSeen += 1;
        /* 前几秒"还没记录"很正常（后端正在起下载进程），只把计时刷起来 */
        paintInst(what, { phase: 'run', text: '正在启动', secs: local(), log: '' });
        if (noneSeen >= 8) {
          stopInstPoll();
          openModal('安装没启动起来',
            '<div class="note">等了 ' + local() + ' 秒，后端还是没有这次安装的记录 —— ' +
            '大概率是启动下载进程那一步没成。</div>' +
            '<div class="note">不用再等了：直接点「打开下载页」手动装（一路「下一步」），' +
            '效果完全一样。</div>',
            [{ text: '打开下载页', key: 'dl', kind: 'primary' },
             { text: '再检查一次', key: 'next', kind: 'ghost' },
             { text: '关闭', key: 'close', kind: 'ghost' }], true);
          S.modalActs.dl = function () { call('open_url', { url: what === 'git' ? URL_GIT_DL : URL_GH_DL }); };
          S.modalActs.next = function () { refreshEnv().then(dialogEnv); };
          refreshEnv();
        }
        return;
      }
      noneSeen = 0;
      paintInst(what, st);
      paintInstButtons(what, st);
      if (st.phase === 'done') {
        stopInstPoll();
        toast((what === 'git' ? 'Git' : 'GitHub CLI') + ' 好了', 'ok');
        refreshEnv();
        if (what === 'gh') { S.gh = null; }
        return;
      }
      if (st.phase === 'fail') { stopInstPoll(); refreshEnv(); return; }
      tick += 1;
      if (tick > 600) { stopInstPoll(); }      /* 10 分钟兜底，别无限轮询 */
    }).catch(function (e) {
      silent += 1;
      /* 后端没回话 ≠ 安装停了。把秒数刷起来，让人看到"界面在等"，而不是冻住 */
      paintInst(what, { phase: 'run', text: '正在等后端回话', secs: local(), log: '' });
      if (silent >= 3) {
        instPollBroken((e && e.message) || String(e));
      }
    });
  }
  poll();
  INST.timer = setInterval(poll, 1000);
}

/* 读进度这条路本身坏了 —— 也要让人看见，而不是停在"0 秒" */
function instPollBroken(why) {
  stopInstPoll();
  openModal('读不到安装进度',
    '<div class="note">界面这边拿不到进度（' + esc(why || '未知原因') + '）。' +
    '但安装本身可能已经在后台跑着。</div>' +
    '<div class="note">你可以：① 点「再检查一次」看看是不是已经装好了；' +
    '② 直接点「打开下载页」手动装。</div>',
    [{ text: '再检查一次', key: 'next', kind: 'primary' },
     { text: '打开下载页', key: 'dl', kind: 'ghost' },
     { text: '关闭', key: 'close', kind: 'ghost' }], true);
  S.modalActs.next = function () { refreshEnv().then(dialogEnv); };
  S.modalActs.dl = function () {
    var w = (INST && INST.what) || 'gh';
    call('open_url', { url: w === 'git' ? URL_GIT_DL : URL_GH_DL });
  };
}

function envLogin() {
  busyOn('正在打开登录窗口…');
  call('gh_login', {}).then(function (r) {
    busyOff();
    if (r.ok) {
      openModal('登录 gh（可选，不影响上传）',
        '<div class="note">我已经开好一个窗口（标题「GitHub 登录（照窗口里的字做）」）。' +
        '窗口最上面就写着步骤，照做就行：</div>' +
        '<div class="note">① 窗口里出现一个 <b>8 位代码</b>，像 <span class="hintline">ABCD-1234</span><br>' +
        '② 按一下回车 → 自动打开浏览器<br>' +
        '③ 把代码粘进去（或直接点页面上的 Authorize）→ 点同意<br>' +
        '④ 窗口里出现 <b>Logged in as 你的名字</b> = 成了</div>' +
        '<div class="note">窗口<b>不会一闪就没</b>了：出什么错都会停在窗口里给你看。' +
        '卡住的话直接关掉它，我再帮你换别的办法。</div>' +
        '<div class="note"><b>这一步是"可选"的</b>：它只是让「备份到云端」能替你自动建仓库。' +
        '<b>上传本身用不着它</b>（走的是 git 自己的登录，第一次推会自己弹浏览器）。' +
        '不想弄就点「关闭」，用「我已有仓库，填地址」一样能上传。</div>' +
        '<div class="note">还没有 GitHub 账号？点下面的「注册 GitHub」（免费，两分钟）。</div>',
        [{ text: '登录好了，再检查', key: 'ok', kind: 'primary' },
         { text: '注册 GitHub', key: 'signup', kind: 'ghost' },
         { text: '不用它也行', key: 'close', kind: 'ghost' }], true);
      S.modalActs.ok = function () { refreshEnv().then(dialogEnv); };
      S.modalActs.signup = function () { call('open_url', { url: URL_SIGNUP }); };
    } else {
      openModal('打不开登录窗口', '<div class="note">' + esc(r.why || '') + '</div>',
        [{ text: '手动下载 gh', key: 'ok', kind: 'primary' },
         { text: '关闭', key: 'close', kind: 'ghost' }], true);
      S.modalActs.ok = function () { call('open_url', { url: URL_GH_DL }); };
    }
  }).catch(function (e) { busyOff(); fail(e); });
}

/* 「告诉 AI」：把当前体检结果拼成一段人话复制到剪贴板。

   ★ 为什么做这个：人描述"我这用不了"往往说不清是哪一项缺了，AI 只能瞎猜。
     这里直接把**机器读到的事实**（哪一项什么状态、报的什么）拼好，粘过去就能对症。
     剪贴板走 navigator.clipboard（WebView2 里可用），不行就退回"让人自己复制"。 */
function envAskAi() {
  var e = S.env || {};
  var lines = ['我这个 moss 的 github 包用不了，帮我看看。', '',
               '目录：' + (S.path || '（还没选）')];
  var mark = { ok: '正常', warn: '缺', bad: '缺', skip: '跳过' };
  (e.items || []).forEach(function (i) {
    lines.push('- ' + i.label + '：' + (mark[i.state] || i.state) + '　' + (i.detail || ''));
    if (i.extra) { lines.push('    ' + i.extra); }
  });
  if (e.next) { lines.push('', '它建议的下一步：' + e.next); }
  var text = lines.join('\n');

  function fallback() {
    openModal('把这段话复制给 AI',
      '<div class="note">点一下下面这块，全选复制，然后粘给 moss 的 AI 就行。</div>' +
      '<pre class="out" id="askAiText">' + esc(text) + '</pre>',
      [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
    var pre = el('askAiText');
    if (pre && window.getSelection) {
      var r = document.createRange();
      r.selectNodeContents(pre);
      var sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(r);
    }
  }

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function () {
      openModal('已经复制好了',
        '<div class="note">这段内容已经在剪贴板里。去外面跟 moss 的 AI 说一句：</div>' +
        '<div class="note"><b>「帮我按这个把环境弄好」</b>，然后粘上去（Ctrl+V）。</div>' +
        '<div class="note">AI 能看到同样的信息，也知道该装什么、点哪里。</div>',
        [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
    }).catch(fallback);
  } else {
    fallback();
  }
}

function envIdentity() {
  call('fix_identity', { path: S.path }).then(function (r) {
    toast(r.ok ? '署名填好了' : '没填上，看看详情', r.ok ? 'ok' : 'no');
    refreshEnv();
  }).catch(fail);
}

/* 搜索命中判断：版本号 / 说明 / 短哈希 / 文件名都能搜 */
function hitQ(q, parts) {
  if (!q) { return true; }
  for (var i = 0; i < parts.length; i++) {
    if (String(parts[i] == null ? '' : parts[i]).toLowerCase().indexOf(q) >= 0) { return true; }
  }
  return false;
}

/* ---------------------------------------------------------------- 状态 */
var S = {
  boot: null, gh: null, actions: [], groups: [],
  snap: null, tl: null, cloud: null, path: '', picks: null, limit: 20,
  last: null, drawer: false, cloudOpen: true,
  /* ★ 弹窗按钮的动作表：**开窗时**由 `openModal()` 重置（不能只靠 `closeModal`） */
  modalActs: {},
  /* v12 新增：两个列表的搜索词、文件行内 Diff 的展开状态与缓存 */
  qLocal: '', qCloud: '', openDiff: {}, diffs: {}
};

/* ================================================================ 启动 */
function boot() {
  put('icoLogo', 'feather'); put('icoFolder', 'folder'); put('icoScan', 'refresh');
  put('icoLaptop', 'laptop'); put('icoHistory', 'history'); put('icoCloud', 'cloud');
  /* 本地工作区右上角那颗「统计」图标：点开就是代码行数面板 */
  put('icoStat', 'chart');
  put('drawerArrow', 'chevronDown');
  put('icoDown', 'arrowDown'); put('icoDown2', 'arrowDown'); put('icoUp', 'arrowUp');

  /* v12：两个搜索框的清空按钮 + 快捷键/快捷填入的绑定 */
  [['qLocalX', 'x'], ['qCloudX', 'x'],
   ['icoSearchL', 'search'], ['icoSearchC', 'search']].forEach(function (p) {
    var b = el(p[0]); if (b) { b.innerHTML = svg(p[1]); }
  });
  bindSearch('qLocal', 'qLocalWrap');
  bindSearch('qCloud', 'qCloudWrap');
  bindQuickFill();
  bindEnvRecheck();          // 页面重新被看见 ⇒ 重查环境（见函数上那段说明）

  busyOn('正在准备…');
  /* ★ 打开页面这一段原来是**一条链慢慢串下来**：
       boot → actions → gh（各自等回话）→ loadAll（里面又串三个）→ refreshEnv
     每个后端都要跑好几条 git（这台机器每条启进程 0.26 秒），加起来就是十几秒。
     用户的原话："每次打开这个页面都特别慢，不知道哪里出了问题"。
     现在：① boot/actions/gh 一起发；② 三个只读请求 loadAll 内部并行；
           ③ **环境检查不再挡路** —— 它最慢，但界面不用等它，先画出来再说，
              结果回来了往顶部那条提示里填（本来就有一条独立的提示条）。
     加起来等待 ≈ 最慢那一个，而不是所有之和。 */
  var pBoot = call('boot', {}).then(function (b) {
    S.boot = b;
    S.path = b.preferred || '';
    return b;
  });
  var pActs = call('actions', {}).then(function (a) {
    S.actions = a.actions || []; S.groups = a.groups || [];
  }).catch(function () { /* 菜单没读到不影响主流程 */ });
  var pGh = call('gh', {}).then(function (g) { S.gh = g; })
    .catch(function () { /* 没 gh 不影响主流程 */ });

  return pBoot.then(function () {
    // 环境检查**和**数据加载一起发，谁也不等谁；界面的骨架立刻画出来
    var pEnv = refreshEnv().catch(function () { return null; });
    return loadAll().then(function () { busyOff(); }).catch(function () { busyOff(); })
      .then(function () { return Promise.all([pActs, pGh]); })
      .then(function () { return pEnv; });
  }).catch(function () { busyOff(); });
}

/* 读全部状态。★ 三个请求**一起发**：
   以前是 snapshot 回来才发 timeline、timeline 回来才发 cloud_versions ——
   后端每个都要跑十几条 git（这台机器每条启进程 0.26 秒），串着等就是十几秒，
   用户的原话是"每次打开这个页面都特别慢"。三个都是只读、互不依赖，并行发就行；
   后端那边也改成并发处理只读请求了（Embedded.loop / PARALLEL_METHODS）。
   谁先回谁先画，最后一起 syncUI。 */
function loadAll() {
  busyOn('正在读取…');
  var got = 0, want = 3;

  function done() { got += 1; if (got >= want) { syncUI(); busyOff(); } }

  var pSnap = call('snapshot', { path: S.path }).then(function (s) {
    S.snap = s; S.path = s.path || S.path;
    /* v12：刷新后旧的行内 Diff 缓存作废（文件可能已经变了） */
    S.diffs = {}; S.openDiff = {};
    renderHead();
    if (!s.isRepo) { S.tl = null; S.cloud = null; syncUI(); got = want; busyOff(); }
    return s;
  });

  var pTl = call('timeline', { path: S.path, limit: S.limit })
    .then(function (t) { S.tl = t; })
    .catch(function (e) { S.tl = S.tl || {}; fail(e); });

  // 云端版本列表（只读本地那份远端跟踪记录，不联网，所以很快）
  var pCloud = call('cloud_versions', { path: S.path, limit: 30 })
    .then(function (c) { S.cloud = c; })
    .catch(function (e) {
      // ★ 拿不到就说清为什么（以前这里静默吞掉，界面上就是"什么都没有"，
      //   根本看不出是后端没这个方法、还是仓库没数据）。
      S.cloud = { ok: false, commits: [],
                  why: '读不到云端版本：' + ((e && e.message) || e) +
                       '（界面比后端新？把包重新运行一次）' };
    });

  return Promise.all([
    pSnap.then(done).catch(function (e) { done(); return fail(e); }),
    pTl.then(done),
    pCloud.then(done)
  ]);
}

/* 联网刷新云端信息（fetch），刷完再读一遍列表 */
function refreshCloud() {
  busyOn('正在联网读云端…');
  shootOrb('track2', 'up', 'purple');
  return call('run_action', { name: 'fetch', path: S.path }).then(function (r) {
    if (!r.ok) { toast('读不到云端：' + (r.why || ''), 'no'); }
    S.last = { title: '刷新云端', res: r, at: stamp() };
    return loadAll();
  }).catch(fail).then(function () { busyOff(); });
}

/* ================================================================ 头部 */
function renderHead() {
  var s = S.snap || {};
  var name = s.isRepo ? baseName((s.repo || {}).root || s.path) : baseName(s.path);
  el('dirName').textContent = name || '选文件夹';
  el('dirBtn').title = s.path || '';
  renderDirMenu(dirOpen);
}

var dirOpen = false;
function renderDirMenu(open) {
  dirOpen = !!open;
  var box = el('dirMenu');
  if (!box) { return; }
  box.classList.toggle('show', dirOpen);
  if (!dirOpen) { box.innerHTML = ''; return; }
  var rec = Array.isArray((S.snap || {}).recent) ? S.snap.recent : [];
  var h = '<div class="dm-hd">换一个文件夹' + (rec.length ?
    '<span class="grow"></span><button class="link mut" data-act="dir-clear">清空记录</button>' : '') + '</div>';
  if (!rec.length) { h += '<div class="dm-empty">还没有用过的文件夹。</div>'; }
  rec.slice(0, 10).forEach(function (it) {
    h += '<div class="dm-item' + (samePath(it.path, S.path) ? ' on' : '') + '" data-act="use-dir" ' +
      'data-path="' + esc(it.path) + '" title="' + esc(it.path) + '">' +
      '<span class="dm-dot' + (it.repo ? ' repo' : '') + '"></span>' +
      '<span class="dm-txt"><span class="dm-name">' + esc(it.name || baseName(it.path)) + '</span>' +
      '<span class="dm-path">' + esc(it.path) + '</span></span>' +
      (it.exists === false ? '<span class="dm-gone">不在了</span>' : '') +
      '<span class="dm-x" data-act="forget-dir" data-path="' + esc(it.path) + '">' + svg('x') + '</span></div>';
  });
  h += '<div class="dm-item" data-act="pick-dir"><span class="dm-dot"></span>' +
    '<span class="dm-txt"><span class="dm-name">选别的文件夹…</span>' +
    '<span class="dm-path">打开文件夹选择器</span></span></div>';
  h += '<div class="dm-item" data-act="type-dir"><span class="dm-dot"></span>' +
    '<span class="dm-txt"><span class="dm-name">手动输入路径…</span>' +
    '<span class="dm-path">直接粘贴一个路径</span></span></div>';
  box.innerHTML = h;
}
function closeDirMenu() { if (dirOpen) { renderDirMenu(false); } }

/* ================================================================ 状态引擎
   算清"现在最该干什么"，然后一次性把三段卡片 / 两条管道 / 按钮都渲染成对应样子。 */
function viewState() {
  var s = S.snap || {}, r = s.repo || {}, n = s.net || {}, t = S.tl || {};
  var hasRemote = !!(n.ok && n.remote);
  var unpushed = hasRemote ? n0(n.ahead) : 0;
  var behind = hasRemote ? n0(n.behind) : 0;
  return {
    isRepo: !!s.isRepo,
    dirty: !!(s.isRepo && r.dirty),
    count: n0(r.changeCount),
    changes: r.changes || [],
    pushedKnown: !!t.pushedKnown,
    unpushed: unpushed,
    behind: behind,
    hasRemote: hasRemote,
    netWhy: n.why || '',
    ver: t.ver || '',
    cloudVer: t.cloudVer || '',
    total: n0(t.total),
    commits: t.commits || [],
    more: !!t.more
  };
}

function syncUI() {
  var v = viewState();

  /* ---- 第一段：本地工作区 ---- */
  var cardWork = el('cardWork'), workIcon = el('workIcon'), workStatus = el('workStatus');
  cardWork.className = 'node' + (v.isRepo && v.dirty ? ' node-active-amber' : ' node-done');
  workIcon.className = 'node-ico ' + (v.isRepo && v.dirty ? 'amber' : 'gray');
  workIcon.innerHTML = svg(v.isRepo && v.dirty ? 'laptop' : (v.isRepo ? 'check' : 'laptop'));
  if (!v.isRepo) {
    workStatus.className = 'node-sub amber';
    workStatus.textContent = '还不是托管文件夹，点下面的按钮开始记录';
  } else if (v.dirty) {
    workStatus.className = 'node-sub amber';
    workStatus.textContent = v.count + ' 个文件有修改，待打包保存';
  } else {
    workStatus.className = 'node-sub';
    workStatus.textContent = '无未保存改动';
  }
  el('workBody').classList.toggle('open', !v.isRepo || v.dirty);
  var filesBtn = el('filesBtn');
  filesBtn.style.display = v.isRepo && v.dirty ? '' : 'none';
  el('checkedCount').textContent = String(S.picks ? S.picks.length : v.count);
  el('drawerArrow').innerHTML = svg('chevronDown');
  el('drawerArrow').style.transform = S.drawer ? 'rotate(180deg)' : '';
  el('note').placeholder = v.isRepo ? '用一句话描述你做了什么修改...' : '这是新建记录，写一句说明...';

  /* ---- 管道 1 + 保存按钮 ---- */
  var p1 = el('pipe1'), p1a = el('pipe1Arrow'), btnSave = el('btnSave');
  if (!v.isRepo) {
    p1.setAttribute('class', 'pipe-amber');
    p1a.setAttribute('fill', 'var(--amber)');
    btnSave.className = 'pipe-btn amber-btn';
    btnSave.setAttribute('data-act', 'init-repo');
    el('btnSaveTxt').textContent = '开始记录';
  } else if (v.dirty) {
    p1.setAttribute('class', 'pipe-amber');
    p1a.setAttribute('fill', 'var(--amber)');
    btnSave.className = 'pipe-btn amber-btn';
    btnSave.setAttribute('data-act', 'save-local');
    el('btnSaveTxt').textContent = '保存到本地';
  } else {
    p1.setAttribute('class', 'pipe-idle');
    p1a.setAttribute('fill', 'var(--mut2)');
    btnSave.className = 'pipe-btn muted';
    btnSave.setAttribute('data-act', 'save-local');
    el('btnSaveTxt').textContent = '已保存';
  }

  /* ---- 第二段：本地历史记录 ---- */
  var cardLocal = el('cardLocal'), localIcon = el('localIcon'), localVer = el('localVer');
  if (v.dirty) {
    cardLocal.className = 'node';
    localIcon.className = 'node-ico gray';
  } else if (v.unpushed > 0) {
    cardLocal.className = 'node node-active-blue';
    localIcon.className = 'node-ico blue';
  } else {
    cardLocal.className = 'node';
    localIcon.className = 'node-ico gray';
  }
  localIcon.innerHTML = svg('history');
  localVer.textContent = v.ver || '—';
  localVer.className = 'ver-pill mono ' + (v.unpushed > 0 && !v.dirty ? 'blue' : 'gray');

  /* ---- 管道 2 + 备份/获取按钮 ---- */
  var p2 = el('pipe2'), p2d = el('pipe2Down'), p2u = el('pipe2Up');
  var btnBackup = el('btnBackup'), btnFetch = el('btnFetch');
  p2u.classList.remove('on');
  if (v.behind > 0) {
    p2.setAttribute('class', 'pipe-purple');
    p2d.setAttribute('fill', 'var(--mut2)');
    p2u.setAttribute('fill', 'var(--purple)');
    p2u.classList.add('on');
  } else if (v.unpushed > 0) {
    p2.setAttribute('class', 'pipe-blue');
    p2d.setAttribute('fill', 'var(--blue)');
    p2u.setAttribute('fill', 'var(--mut2)');
  } else {
    p2.setAttribute('class', 'pipe-idle');
    p2d.setAttribute('fill', 'var(--mut2)');
    p2u.setAttribute('fill', 'var(--mut2)');
  }
  if (v.unpushed > 0) {
    btnBackup.className = 'pipe-btn blue-btn';
    el('btnBackupTxt').textContent = '备份到云端 (' + v.unpushed + ')';
  } else if (!v.hasRemote && v.isRepo) {
    btnBackup.className = 'pipe-btn soft';
    el('btnBackupTxt').textContent = '备到 GitHub';
  } else {
    btnBackup.className = 'pipe-btn muted';
    el('btnBackupTxt').textContent = '云端已最新';
  }
  btnFetch.className = 'pipe-btn soft ghostish' + (v.behind > 0 ? ' pulse' : '');
  el('btnFetchTxt').textContent = v.behind > 0 ? ('获取最新版 (' + v.behind + ')') : '获取最新版';

  /* ---- 第三段：GitHub 云端 ---- */
  var cardCloud = el('cardCloud'), cloudIcon = el('cloudIcon'),
      cloudStatus = el('cloudStatus'), cloudVer = el('cloudVer'), cloudDot = el('cloudDot');
  if (!v.isRepo) {
    cardCloud.className = 'node node-done';
    cloudIcon.className = 'node-ico gray'; cloudIcon.innerHTML = svg('cloud');
    cloudStatus.className = 'node-sub';
    cloudStatus.textContent = '先开始记录这个文件夹';
    cloudVer.className = 'ver-pill gray mono'; cloudDot.className = 'dot gray';
    el('cloudVerNum').textContent = '—';
  } else if (!v.hasRemote) {
    cardCloud.className = 'node node-active-purple';
    cloudIcon.className = 'node-ico purple'; cloudIcon.innerHTML = svg('cloud');
    cloudStatus.className = 'node-sub purple';
    cloudStatus.textContent = '还没连上 GitHub —— 点「备到 GitHub」';
    cloudVer.className = 'ver-pill gray mono'; cloudDot.className = 'dot gray';
    el('cloudVerNum').textContent = '—';
  } else if (v.behind > 0) {
    cardCloud.className = 'node node-active-purple';
    cloudIcon.className = 'node-ico purple'; cloudIcon.innerHTML = svg('cloud');
    cloudStatus.className = 'node-sub purple';
    cloudStatus.textContent = '云端有 ' + v.behind + ' 个新版本，等待上方获取';
    cloudVer.className = 'ver-pill blue mono'; cloudDot.className = 'dot blue';
    el('cloudVerNum').textContent = v.cloudVer || '—';
  } else if (v.unpushed > 0) {
    cardCloud.className = 'node';
    cloudIcon.className = 'node-ico amber'; cloudIcon.innerHTML = svg('cloud');
    cloudStatus.className = 'node-sub amber';
    cloudStatus.textContent = '落后本地 ' + v.unpushed + ' 个版本，等待上方备份';
    cloudVer.className = 'ver-pill amber mono'; cloudDot.className = 'dot amber';
    el('cloudVerNum').textContent = v.cloudVer || '—';
  } else {
    cardCloud.className = 'node node-done';
    cloudIcon.className = 'node-ico green'; cloudIcon.innerHTML = svg('cloud');
    cloudStatus.className = 'node-sub';
    cloudStatus.textContent = '已与本地对齐，文件很安全';
    cloudVer.className = 'ver-pill green mono'; cloudDot.className = 'dot green';
    el('cloudVerNum').textContent = v.cloudVer || v.ver || '—';
  }

  /* 云端那张卡的展开状态跟着走 */
  var cb = el('cloudBody'), ct = el('cloudCaret');
  if (cb) { cb.classList.toggle('open', S.cloudOpen); }
  if (ct) { ct.innerHTML = svg('chevronDown'); ct.style.transform = S.cloudOpen ? 'rotate(180deg)' : ''; }

  renderFiles(v);
  renderHistory(v);
  renderCloudList(v);
  el('log').textContent = v.isRepo
    ? ('当前：' + baseName(S.path) + (v.ver ? '　' + v.ver : '') +
       (v.dirty ? '　' + v.count + ' 个待保存' : '') +
       (v.unpushed ? '　待备份 ' + v.unpushed : '') + (v.behind ? '　待获取 ' + v.behind : ''))
    : ('当前：' + (S.path || '—') + '（还不是托管文件夹）');
}

/* ---- 文件清单（第一段里那个可折叠抽屉） ---- */
function renderFiles(v) {
  var box = el('fileList');
  if (!v.isRepo || !v.dirty) { box.innerHTML = ''; return; }
  var picked = S.picks;
  var h = '';
  (v.changes || []).forEach(function (f) {
    var p = f.path;
    var on = !picked || picked.indexOf(p) >= 0;
    var isNew = f.flag === 'untracked';
    var open = !!S.openDiff[p];
    h += '<div class="fitem' + (open ? ' open' : '') + '">' +
      '<div class="frow">' +
      '<label class="fl"><input type="checkbox" class="fn" data-file="' + esc(p) + '"' +
      (on ? ' checked' : '') + '>' +
      '<span class="dot ' + (isNew ? 'green' : 'amber') + '"></span>' +
      '<span class="fname" title="' + esc(p) + '">' + esc(p) + '</span></label>' +
      '<span class="fstat ' + (isNew ? 'new' : 'mod') + '">' +
      (isNew ? '新增' : wordFlag(f.flag)) + '</span>' +
      '<span class="fx" data-diff="' + esc(p) + '" title="' +
      (open ? '收起代码对比' : '展开这个文件改了什么') + '">' + svg('chevronDown') + '</span>' +
      '</div>' +
      (open ? '<pre class="fdiff mono">' + diffBlock(p) + '</pre>' : '') +
      '</div>';
  });
  box.innerHTML = h;
  bindFileChecks();
  bindInlineDiff();
}

/* ---- 行内 Diff（v12）：不弹窗，直接在文件名下面展开红绿对比 ---- */
function diffBlock(p) {
  var d = S.diffs[p];
  if (d === 0) { return '<span class="wait">正在读改动…</span>'; }   /* 0 = 正在读 */
  if (d === null) { return '<span class="wait">看不到这个文件的改动</span>'; }
  if (typeof d === 'string') { return colorDiff(d); }
  return '<span class="wait">点右侧箭头展开…</span>';
}
function loadInlineDiff(p) {
  S.diffs[p] = 0;
  call('file_op', { path: S.path, op: 'diff', file: p }).then(function (r) {
    S.diffs[p] = r.ok ? String(r.out || '（没有可显示的改动）') : null;
    renderFiles(viewState());
  }).catch(function () {
    S.diffs[p] = null;
    renderFiles(viewState());
  });
}
function bindInlineDiff() {
  Array.prototype.forEach.call(document.querySelectorAll('#fileList .fx'), function (b) {
    b.addEventListener('click', function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      var p = b.getAttribute('data-diff');
      if (!p) { return; }
      if (S.openDiff[p]) { delete S.openDiff[p]; }
      else {
        S.openDiff[p] = true;
        if (S.diffs[p] === undefined) { loadInlineDiff(p); }
      }
      renderFiles(viewState());
    });
  });
}
function wordFlag(f) {
  return { staged: '已包含', unstaged: '改过了', untracked: '新文件', conflict: '有冲突' }[f] || '改过了';
}
function bindFileChecks() {
  Array.prototype.forEach.call(document.querySelectorAll('#fileList input.fn'), function (b) {
    b.addEventListener('change', function () {
      var all = document.querySelectorAll('#fileList input.fn');
      var list = [];
      Array.prototype.forEach.call(all, function (x) {
        if (x.checked) { list.push(x.getAttribute('data-file')); }
      });
      S.picks = (list.length === all.length) ? null : list;
      el('checkedCount').textContent = String(list.length);
    });
  });
}

/* ---- 云端版本列表（第三段）
   ★ 这是"从云端拉取"的入口：能看见云端有哪些版本，挑一条就能取到本地。
     后端 `cloud_versions` 读的是本地那份「远端跟踪分支」的记录（不联网，秒开），
     想拿真的最新数据就点「刷新云端」。 */
function renderCloudList(v) {
  var box = el('cloudList'), more = el('cloudMore'), refEl = el('cloudRef');
  if (!box) { return; }
  var c = S.cloud;                       // null = 还没读到
  if (refEl) {
    refEl.textContent = (c && c.ref) ? ('看的是 ' + c.ref) : '';
  }
  if (c === null || c === undefined) {
    box.innerHTML = '<div class="cloud-empty">正在读取云端版本…</div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  if (!v.isRepo) {
    box.innerHTML = '<div class="cloud-empty">先开始记录这个文件夹，云端才会有东西。</div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  if (!v.hasRemote) {
    box.innerHTML = '<div class="cloud-empty">这个文件夹还没连 GitHub。<br>' +
      '点上面「备到 GitHub」建一个，或者连到一个已有的仓库。</div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  if (!c.ok) {
    box.innerHTML = '<div class="cloud-empty">' + esc(c.why || '读不到云端版本') + '</div>' +
      '<div class="cloud-actions">' +
      '<button class="mini-btn" data-act="cloud-refresh">' + svg('refresh') +
      '刷新云端（联网读一次）</button></div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  if (!(c.commits || []).length) {
    box.innerHTML = '<div class="cloud-empty">云端还没有任何版本。</div>' +
      '<div class="cloud-actions"><button class="mini-btn" data-act="cloud-refresh">' +
      svg('refresh') + '刷新云端</button></div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  /* v12：云端列表也支持搜索 */
  var qc = (S.qCloud || '').toLowerCase();
  var shown = (c.commits || []).filter(function (cm) {
    return hitQ(qc, [cm.ver, cm.subject, cm.short, cm.hash]);
  });
  if (qc && !shown.length) {
    box.innerHTML = '<div class="hist-none">云端没有匹配「' + esc(S.qCloud) + '」的版本</div>';
    if (more) { more.innerHTML = ''; }
    return;
  }
  var h = '';
  shown.forEach(function (cm) {
    var missing = !cm.inLocal;            // 本地还没有这个版本
    h += '<div class="hrow cloud ' + (missing ? 'missing' : 'haslocal') + '">' +
      '<div class="hl"><span class="hdot"></span>' +
      '<span class="hver mono">' + esc(cm.ver || '') + '</span>' +
      '<span class="hmsg" title="' + esc(cm.subject || '') + '">' +
      esc(cm.subject || '（没有说明）') + '</span>' +
      '<span class="inlocal">' + (missing ? '本地还没有' : '本地已有') + '</span></div>' +
      '<div class="hacts">' +
      '<button class="mini-btn" data-act="detail" data-hash="' + esc(cm.hash) + '">' +
      svg('eye') + '看</button>' +
      '<button class="mini-btn" data-act="cloud-take" data-hash="' + esc(cm.hash) +
      '" title="把这个云端版本取到本地">' + svg('download') + '取到本地</button>' +
      '</div></div>';
  });
  box.innerHTML = h;
  if (more) {
    more.innerHTML = c.more
      ? '<button class="link" data-act="cloud-more">查看更早的云端版本…</button>'
      : '<span class="hintline">云端共 ' + n0(c.total) + ' 个版本</span>';
  }
}

/* 挑一个云端版本取到本地：跟本地「切回」一样给两条路，安全的排前面 */
function cloudTake(hash) {
  var v = viewState();
  openModal('把这个云端版本取到本地',
    '<div class="note">云端这条：<span class="hintline">' + esc(String(hash).slice(0, 8)) +
    '</span>。选一种做法：</div>' +
    '<div class="actions">' +
    '<button class="act" data-act="cloud-take-safe" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('branch') + '</span><span>' +
    '<span class="at">取到一个新分支，不动现在的文件</span>' +
    '<span class="ad">安全：现在的文件一个都不改，只是多一条线，想看就看</span></span></button>' +
    '<button class="act" data-act="cloud-take-hard" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('download') + '</span><span>' +
    '<span class="at">用这个云端版本覆盖本地文件</span>' +
    '<span class="ad">本地文件会变成那个版本；没保存的改动会先自动备份（之后能找回）</span></span></button>' +
    '</div>', [{ text: '取消', key: 'close', kind: 'ghost' }], true);
}

/* ---- 历史记录列表 ---- */
function renderHistory(v) {
  var box = el('historyList'), more = el('histMore');
  if (!v.isRepo) {
    box.innerHTML = '<div class="hist-empty">还没有记录。<br>' +
      '点上面的「开始记录」，之后每次保存都会在这里多一条。</div>';
    more.innerHTML = ''; return;
  }
  if (!v.commits.length) {
    box.innerHTML = '<div class="hist-empty">这个文件夹还没有任何记录。<br>' +
      '写一句说明，点「保存到本地」，第一条就出来了。</div>';
    more.innerHTML = ''; return;
  }
  /* v12：本地历史支持搜索（版本号 / 说明 / 短哈希都能搜） */
  var q = (S.qLocal || '').toLowerCase();
  var list = (v.commits || []).filter(function (c) {
    return hitQ(q, [c.ver, c.subject, c.short, c.tag]);
  });
  if (q && !list.length) {
    box.innerHTML = '<div class="hist-none">没有匹配「' + esc(S.qLocal) + '」的记录</div>';
    more.innerHTML = '';
    return;
  }
  var h = '';
  /* ★ 待上传的那一条自己带一个「上传」按钮。
     用户报的 bug：本地列表里明明写着「待上传云端」，界面上却找不到任何上传按钮
     （下面那个大按钮还是灰的「云端已最新」）。根因在后端 ahead 算成 0，已修；
     这里再补一个就近的入口：git push 一次会把所有未上传的版本一起推上去，
     所以只在**最上面那条**待上传的记录上标出来，不重复刷屏。 */
  var firstUnsent = -1;
  for (var ui = 0; ui < list.length; ui++) {
    if (!list[ui].pushed) { firstUnsent = ui; break; }
  }
  list.forEach(function (c, i) {
    var unsent = !c.pushed;
    var dim = (!unsent && i > 0) ? ' dim' + Math.min(3, i) : '';
    h += '<div class="hrow ' + (unsent ? 'unsent' : 'sent') + dim + '">' +
      '<div class="hl"><span class="hdot"></span>' +
      '<span class="hver mono">' + esc(c.ver || '') + '</span>' +
      '<span class="hmsg" title="' + esc(c.subject || '') + '">' +
      esc(c.subject || '（没有说明）') + '</span></div>' +
      '<div class="hacts">' +
      (i === firstUnsent
        ? '<button class="mini-btn up" data-act="backup" title="' +
          esc(v.hasRemote ? '把还没上传的版本一起传到 GitHub'
                          : '先连一个 GitHub 仓库，再上传') + '">' +
          svg('arrowUp') + '上传</button>'
        : '') +
      '<button class="mini-btn" data-act="detail" data-hash="' + esc(c.hash) + '">' +
      svg('eye') + '看</button>' +
      '<button class="mini-btn" data-act="restore" data-hash="' + esc(c.hash) + '">' +
      svg('rotate') + '切回</button>' +
      '<button class="mini-btn del" data-act="del-commit" data-hash="' + esc(c.hash) + '">' +
      svg('x') + '删</button>' +
      '</div></div>';
  });
  box.innerHTML = h;
  more.innerHTML = v.more
    ? '<button class="link" data-act="more-commits">查看更早的记录…</button>'
    : '<span class="hintline">已经到底了</span>';
}

/* ================================================================ 三个主动作 */
function shootOrb(trackId, dir, color) {
  var track = el(trackId);
  if (!track) { return; }
  var o = document.createElement('div');
  o.className = 'orb ' + color + ' ' + dir;
  track.appendChild(o);
  setTimeout(function () { if (o.parentNode) { o.parentNode.removeChild(o); } }, 600);
}

/* ============================================ 长操作：后台跑 + 看得见的进度
   ★ 为什么改成这样（真机"三十秒没反应"的根因之一）：
     以前界面发一条 RPC 然后干等，而垫片里那条 RPC 的上限写死 **30 秒** ——
     首次推送两百多兆时，三十秒一到就报"后端没回话"，可 git 其实还在传；
     人以为失败了又点一次，越点越乱。现在：
       ① 发 `job_start` 立刻拿到号（这条一定秒回，永远不会超时）；
       ② 界面拿号每 0.5 秒问一次 `job_state`，把每一行进度画出来；
       ③ 想停就 `job_cancel` —— 真的把那个子进程杀掉；
       ④ 静默太久就直说"还没回话"，不让人对着转圈发愣。
   ============================================================================ */
var JOB = { id: '', timer: null, t0: 0, lastSig: '', after: null };

function stopJobPoll() { if (JOB.timer) { clearInterval(JOB.timer); JOB.timer = null; } }

function jobFace(st, title) {
  var secs = (st && st.elapsed) || Math.round((Date.now() - JOB.t0) / 1000);
  var silent = (st && st.silent) || 0;
  var lines = (st && st.lines) || [];
  var stall = silent >= 12;
  var h = '<div class="inst-head">' +
    (stall ? '<span class="inst-ico no">' + svg('warn') + '</span>'
           : '<span class="inst-spin"></span>') +
    '<div class="inst-txt"><div class="inst-title">' + esc(title || '正在处理') + '…</div>' +
    '<div class="inst-sub">已经 ' + secs + ' 秒' +
    (silent >= 4 ? '　·　' + Math.round(silent) + ' 秒没有新动静' : '') +
    '　·　可以关掉这个窗口，活儿会继续' + '</div></div></div>' +
    '<div class="pbar indet"><i></i></div>';
  h += '<div class="inst-logbox"><div class="inst-loglabel">进度（实时）</div>' +
    '<pre class="inst-log" id="jobLog">' +
    esc(lines.length ? lines.join('\n') : '正在启动…') + '</pre></div>';
  if (stall) {
    h += '<div class="inst-hint">' +
      esc('还在等，只是没新输出 —— 网络慢或者这一步本来就要传很多东西（大仓库第一次推送）。' +
          '真不想等了，点下面的「停下」。') + '</div>';
  }
  return h;
}

/* 开一个长操作；跑完自动收尾（after 是"跑完之后接着干什么"，可选） */
function startJob(method, params, title, orb, after) {
  busyOn(title + '…');
  if (orb) { shootOrb(orb[0], orb[1], orb[2]); }
  var p;
  if (method === 'run_action_key') {
    p = { path: S.path, method: 'run_action', label: title,
          params: { name: params.name, path: S.path } };
  } else {
    p = { path: S.path, method: method, label: title, params: params || {} };
  }
  return call('job_start', p).then(function (r) {
    busyOff();
    if (!r || !r.ok) {
      toast((r && r.why) || '没跑起来（后端没答话）', 'no');
      return null;
    }
    JOB.id = r.id; JOB.t0 = Date.now(); JOB.lastSig = ''; JOB.after = after || null;
    openModal(title || '正在处理', jobFace(null, title),
      [{ text: '停下', key: 'stop', kind: 'ghost' }], true);
    S.modalActs.stop = function () {
      call('job_cancel', { id: JOB.id }).catch(function () { /* 无所谓 */ });
      toast('已经让它停下了', 'ok');
    };
    startJobPoll(title);
    return r.id;
  }).catch(function (e) { busyOff(); fail(e); return null; });
}

function startJobPoll(title) {
  stopJobPoll();
  JOB.timer = setInterval(function () {
    call('job_state', { id: JOB.id }).then(function (st) {
      if (!st || !st.ok) { return; }
      if (el('modal').classList.contains('show')) {
        var b = sub('.dlg-b');
        /* 只在"有变化"时重画：每拍重建 DOM 会让人选中不了日志、也会闪 */
        var sig = String(st.state) + '|' + ((st.lines || []).length) + '|' +
          Math.round((st.elapsed || 0) / 5) + '|' + (st.silent >= 12 ? 1 : 0);
        if (b && sig !== JOB.lastSig) {
          JOB.lastSig = sig;
          b.innerHTML = jobFace(st, title);
          var lg = el('jobLog');
          if (lg) { lg.scrollTop = lg.scrollHeight; }
        }
      }
      if (st.state === 'done' || st.state === 'cancelled') {
        stopJobPoll();
        finishJob(st, title);
      }
    }).catch(function () { /* 一次没问到不要紧，下一拍再问 */ });
  }, 500);
}

function finishJob(st, title) {
  var res = (st && st.result) || {};
  var after = JOB.after;
  JOB.after = null;
  S.last = { title: title, res: res, at: stamp() };
  if (res.ok) {
    toast('完成：' + title, 'ok');
    log('完成：' + title);
    if (el('note')) { el('note').value = ''; }
    S.picks = null; S.drawer = false;
    closeModal();
  } else {
    toast('没成功：' + (res.why || '看看详情'), 'no');
    log('没成功：' + (res.why || title));
    showResult(title);
  }
  loadAll();
  if (typeof after === 'function') { after(res); }
}

function doSteps(method, params, title, orb, after) {
  return startJob(method, params, title, orb, after);
}

/* ① 保存到本地 */
function saveLocal() {
  var s = S.snap || {}, r = s.repo || {};
  if (!s.isRepo) { startRepo(); return; }
  if (!r.dirty) { toast('没有新的改动要保存', 'ok'); return; }
  var msg = (el('note').value || '').trim() || ('更新 · ' + stamp());
  doSteps('commit_all', { message: msg, files: S.picks || [], push: false },
    '保存到本地', ['track1', 'down', 'amber']);
}

/* ② 备份到云端（有改动先存再传，一个按钮到底）
   ★ 推之前先"体检"一次：这一推多大、有没有 GitHub 装不下的文件（单文件 100MB 上限）。
     真事：一个项目的初版提交里有个 182MB 的模型文件，那一推**必然失败**，可失败前
     先把它整个传一遍 —— 界面上三十秒没动静，人只会以为软件坏了。现在先警告、先问，
     想屏蔽的话一键处理（写进 .gitignore + 从库里去掉，磁盘上的文件一个不删）。 */
function backup() {
  var v = viewState();
  if (!v.isRepo) { startRepo(); return; }
  if (!v.hasRemote) { mirrorMenu(); return; }
  if (!v.dirty && v.unpushed <= 0) { toast('云端已经是最新的了', 'ok'); return; }
  pushGuard(function () {
    if (v.dirty) {
      var msg = (el('note').value || '').trim() || ('更新 · ' + stamp());
      doSteps('commit_all', { message: msg, files: S.picks || [], push: true },
        '保存并备份到云端', ['track2', 'down', 'blue']);
      return;
    }
    doSteps('sync', {}, '备份到云端', ['track2', 'down', 'blue']);
  });
}

/* 推之前体检：没问题就直接往下走；有偏大/推不上去的文件就摆出来问一句 */
function pushGuard(next) {
  busyOn('正在看这一推有多大…');
  call('push_check', { path: S.path }).then(function (r) {
    busyOff();
    var big = (r && r.big) || [];
    if (!r || !r.ok || !big.length) { next(); return; }
    var block = big.filter(function (b) { return b.level === 'block'; });
    var h = '<div class="note">这一推要传 <b>' + n0(r.files) + ' 个文件</b>，大约 <b>' +
      esc(r.size || '') + '</b>。' + (r.initial ? '这是第一次上传，全部都要传一遍。' : '') +
      '</div>';
    h += '<div class="note" style="color:#b45309">' + (block.length
      ? '<b>有 ' + block.length + ' 个文件超过了 GitHub 的上限（单个 ' + esc(r.limitHard) +
        '），照这样推一定失败</b>；而且失败前会先把它们整个传一遍 —— 看着就像"卡住了"。'
      : '<b>有几个文件偏大</b>，推起来会慢，但能推上去。') + '</div>';
    h += '<div class="picklist" style="max-height:30vh">';
    big.forEach(function (b) {
      h += '<div class="pick-row"><span class="nm">' + esc(b.path) + '</span>' +
        '<span class="hintline">' + esc(b.size) +
        (b.level === 'block' ? '　推不上去' : '　偏大') + '</span></div>';
    });
    h += '</div>';
    h += '<div class="note">选「屏蔽」= 这些不再跟着提交（<b>电脑上的文件一个都不会删</b>），' +
      '以后换了机器自己放回去就行。想一个个挑，去「更多功能 → 屏蔽清单」。</div>';
    openModal(block.length ? '这一推一定失败' : '这一推会有点慢', h,
      [{ text: '先别推', key: 'close', kind: 'ghost' },
       { text: '照这样硬推', key: 'force', kind: 'ghost' },
       { text: '屏蔽它们再推', key: 'shield', kind: 'primary' }], true);
    S.modalActs.force = function () { closeModal(); next(); };
    S.modalActs.shield = function () {
      var seen = {}, pats = [];
      big.forEach(function (b) {
        if (b.pattern && !seen[b.pattern]) { seen[b.pattern] = 1; pats.push(b.pattern); }
      });
      closeModal();
      startJob('shield', { patterns: pats },
        '屏蔽 ' + pats.length + ' 项（不跟着提交）', null, function (res) {
          if (res && res.ok) { next(); }
        });
    };
  }).catch(function (e) { busyOff(); fail(e); });
}

/* ③ 获取最新版 */
function fetchNew() {
  var v = viewState();
  if (!v.isRepo) { toast('先选一个文件夹', 'no'); return; }
  if (!v.hasRemote) { toast('这个文件夹还没连上 GitHub', 'no'); return; }
  var extra = v.dirty
    ? '现在有 <b>' + v.count + ' 个文件改了还没保存</b>，我会先把它们收起来备份（之后能在「更多功能 → 找回收起的改动」里拿回来）。'
    : '现在没有没保存的改动，不会丢东西。';
  openModal('获取最新版',
    '<div class="note">会把 GitHub 上的内容拿下来，<b>本地文件会变得和云端一样</b>。' +
    (v.cloudVer ? '（' + esc(v.cloudVer) + '）' : '') + '<br>' + extra +
    '<br><br>只想看看云端有什么、不动本地文件的话，点「取消」。</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '获取最新版', key: 'ok', kind: 'primary' }]);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('pull_overwrite', {}, '获取最新版', ['track2', 'up', 'purple']);
  };
}

function startRepo() {
  var s = S.snap || {};
  /* ★ 没装 git 的话，这里点下去一定失败。与其让人看一句英文报错，
     不如现在就换成"怎么把它装上"（v14）。 */
  if (S.env && S.env.ready === false) {
    openModal('还没法开始记录：缺 Git',
      '<div class="note">记录版本要用 Git，但这台电脑上还没装。' +
      '我可以直接替你装（大概 1~3 分钟）。</div>' +
      '<div class="note">' + esc((S.env.items || [])[0] ?
        ((S.env.items || [])[0].help || '') : '') + '</div>' +
      '<div class="note" style="padding:6px 0">' +
      '<button class="env-btn" data-act="env-install" data-what="git">帮我装 Git</button> ' +
      '<button class="env-btn alt" data-act="env-open" data-url="' + URL_GIT_DL + '">自己下载</button>' +
      '</div>',
      [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
    return;
  }
  openModal('开始记录这个文件夹',
    '<div class="note">会给 <b>' + esc(baseName(s.path)) +
    '</b> 建一个记录本（隐藏的 <span class="hintline">.git</span>），不会动你的文件、也不会删东西。<br><br>' +
    '如果这些文件其实已经在 GitHub 上有了，用「更多功能 → 从 GitHub 下载一份」更合适。</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '开始记录', key: 'ok', kind: 'primary' }]);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('run_action_key', { name: 'init' }, '开始记录这个文件夹', ['track1', 'down', 'amber']);
  };
}

/* ================================================================ 弹层 */
function openModal(title, body, buttons, wide) {
  /* ★★ 每次开窗都**重开一张动作表**。以前只在 `closeModal()` 里 `S.modalActs = {}`，
     于是**页面刚打开、还没关过任何窗口**时它是 `undefined` —— 谁要在这时候挂
     `S.modalActs.ok = …` 就当场抛 `TypeError: Cannot set properties of undefined`，
     而那一句之后的所有代码（起轮询、发 install_tool）全都不会执行：
     界面就停在「正在启动 · 已经 0 秒」不动（真机踩了三次、AI 三次都没找到）。
     现在开窗就初始化，页面第一次弹窗也一定是好的。 */
  S.modalActs = {};
  var h = '<div class="mask" data-act="modal-close"></div><div class="dlg' + (wide ? ' wide' : '') + '">' +
    '<div class="dlg-h">' + esc(title) + '</div><div class="dlg-b">' + body + '</div><div class="dlg-f">';
  (buttons || [{ text: '关闭', key: 'close', kind: 'ghost' }]).forEach(function (b) {
    h += '<button class="dbtn ' + (b.kind || 'ghost') + '" data-act="modal-' +
      (b.key || (b.close ? 'close' : 'ok')) + '">' + esc(b.text) + '</button>';
  });
  h += '</div></div>';
  el('modal').innerHTML = h;
  el('modal').classList.add('show');
}
function closeModal() {
  /* 关窗口就停掉安装进度轮询（安装本身还在后台跑，只是不再刷新界面） */
  if (typeof stopInstPoll === 'function') { stopInstPoll(); }
  /* ★ 关掉"安装/登录"那类窗口之后**重查一次环境** —— 以前不查，于是关窗之后
     顶上那条还是旧结论（"建议补上：GitHub CLI" + 帮我装 gh），人一点就重下一份。
     真机就是这么"每次打开都装一次"的。 */
  if (INST && INST.what) {
    INST.what = '';
    if (typeof refreshEnv === 'function') { refreshEnv(); }
  }
  el('modal').classList.remove('show');
  el('modal').innerHTML = '';
  S.modalActs = {};
}

/* ★ 页面重新被看见就重查环境。
   包的内嵌帧是**长期存活**的（切走只是藏起来），重新打开「界面」标签并不会重载页面 ——
   不重查的话，环境条会一直停在"上次打开那一刻"的结论上。三种入口都接：
     · 内嵌：宿主发的 `visible` 事件（`moss-embed.js` 的 on('visible')）；
     · 独立窗口：窗口拿到焦点；
     · 浏览器/WebView 自己的 visibilitychange。 */
function bindEnvRecheck() {
  var last = 0;
  function recheck() {
    var t = Date.now();
    if (t - last < 1500) { return; }                  // 防抖：三个入口可能一起响
    last = t;
    if (typeof refreshEnv === 'function') { refreshEnv(); }
  }
  try {
    if (window.moss && typeof moss.on === 'function') {
      moss.on('visible', function (d) { if (!d || d.visible !== false) { recheck(); } });
    }
  } catch (e) { /* 无妨 */ }
  window.addEventListener('focus', recheck);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { recheck(); }
  });
}
function field(label, value, ph, multiline, name) {
  var id = 'f_' + Math.random().toString(36).slice(2, 7);
  var mark = name ? ' data-f="' + esc(name) + '"' : '';
  return '<div class="field"><label>' + esc(label) + '</label>' +
    (multiline
      ? '<textarea id="' + id + '"' + mark + ' placeholder="' + esc(ph || '') + '">' + esc(value || '') + '</textarea>'
      : '<input type="text" id="' + id + '"' + mark + ' value="' + esc(value || '') +
        '" placeholder="' + esc(ph || '') + '">') + '</div>';
}
function fieldValues() {
  var out = {};
  Array.prototype.forEach.call(document.querySelectorAll('.dlg-b [data-f]'), function (n) {
    out[n.getAttribute('data-f')] = String(n.value || '');
  });
  return out;
}

function showResult(title) {
  var r = (S.last && S.last.res) || null, h = '';
  if (!r) { h = '<div class="note">还没做过什么操作。</div>'; }
  else {
    h += '<div class="note">' + (r.ok ? '✓ 做完了' : '✗ ' + esc(r.why || '没成功')) + '</div>';
    if (r.cmd) {
      h += '<div class="field"><label>实际执行的命令（不用懂，留着给想看的人）</label>' +
        '<pre class="out">' + esc(r.cmd) + '</pre></div>';
    }
    if (r.steps && r.steps.length) {
      h += '<div class="steps">';
      r.steps.forEach(function (s, i) {
        h += '<div class="step ' + (s.ok ? 'ok' : 'no') + '">' +
          '<div class="sh">' + (s.ok ? '✓' : '✗') + ' ' + esc(s.label || ('第 ' + (i + 1) + ' 步')) +
          '<span class="ms">' + n0(s.ms) + ' ms</span></div>' +
          (s.out ? '<pre class="out">' + esc(String(s.out).slice(0, 3000)) + '</pre>' : '') +
          (!s.ok && s.why ? '<div class="note">' + esc(s.why) + '</div>' : '') + '</div>';
      });
      h += '</div>';
    } else if (r.out) {
      h += '<pre class="out">' + esc(String(r.out).slice(0, 6000)) + '</pre>';
    }
  }
  openModal(title || '这次做了什么', h, [{ text: '知道了', key: 'close', kind: 'ghost' }], true);
}

/* ================================================================ 看某条记录 / 切回 */
function showCommit(hash) {
  openModal('这条改了什么', '<div class="note" style="padding:12px 0">正在读…</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  call('show_commit', { path: S.path, hash: hash }).then(function (r) {
    if (!el('modal').classList.contains('show')) { return; }
    var b = sub('.dlg-b'); if (!b) { return; }
    if (!r.ok) { b.innerHTML = '<div class="note">读不到：' + esc(r.why || '') + '</div>'; return; }
    var h = '<p style="font-size:13.5px;font-weight:700;margin:4px 0 10px">' +
      esc(r.subject || '（没有说明）') + '</p>';
    h += '<div class="note" style="margin-bottom:10px">' +
      '<span class="hintline">' + esc(r.short) + '</span>　' + esc(baseName(r.author)) +
      '　' + esc(r.when) + '（' + esc(r.rel) + '）</div>';
    if (r.body) { h += '<pre class="out">' + esc(r.body) + '</pre>'; }
    if ((r.files || []).length) {
      h += '<div class="field" style="margin-top:12px"><label>改了 ' + r.fileCount + ' 个文件</label>' +
        '<div class="picklist" style="max-height:22vh">';
      r.files.forEach(function (f) {
        h += '<div class="pick-row"><span class="nm">' + esc(f.path) + '</span>' +
          '<span class="hintline">+' + esc(f.add) + ' / -' + esc(f.del) + '</span></div>';
      });
      h += '</div></div>';
    }
    h += '<div class="field"><label>具体改了什么</label><pre class="out">' + colorDiff(r.out) + '</pre></div>';
    h += '<div class="actions" style="margin-top:6px"><button class="act" data-act="restore" data-hash="' +
      esc(r.hash) + '"><span class="ai">' + svg('rotate') + '</span>' +
      '<span><span class="at">切回这个版本</span>' +
      '<span class="ad">把它变成现在的样子（会先备份当前没保存的改动）</span></span></button>' +
      '<button class="act" data-act="del-commit" data-hash="' + esc(r.hash) + '">' +
      '<span class="ai">' + svg('x') + '</span>' +
      '<span><span class="at">删掉这个版本</span>' +
      '<span class="ad">有严重 bug / 泄了密钥时用：可以安全撤销，也可以彻底抹掉</span></span></button></div>';
    b.innerHTML = h;
  }).catch(fail);
}
function colorDiff(text) {
  return esc(String(text || '')).split('\n').map(function (l) {
    if (/^(@@|\+\+\+|---)/.test(l)) { return '<span class="hunk">' + l + '</span>'; }
    if (/^\+/.test(l)) { return '<span class="add">' + l + '</span>'; }
    if (/^-/.test(l)) { return '<span class="del">' + l + '</span>'; }
    return l;
  }).join('\n');
}

function restoreDialog(hash) {
  var v = viewState();
  openModal('切回这个版本',
    '<div class="note">这条记录：<span class="hintline">' + esc(String(hash).slice(0, 8)) +
    '</span>。两种做法，上面那个安全：</div>' +
    '<div class="actions">' +
    '<button class="act" data-act="restore-safe" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('branch') + '</span><span>' +
    '<span class="at">先存成一条新记录，不动现在的文件</span>' +
    '<span class="ad">安全：现在的文件一个都不改，只是多一条记录，想看就看</span></span></button>' +
    '<button class="act" data-act="restore-hard" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('rotate') + '</span><span>' +
    '<span class="at">用这个版本覆盖现在的文件</span>' +
    '<span class="ad">当前没保存的改动会先自动备份（之后能找回），文件变成那时候的样子</span></span></button>' +
    '</div>', [{ text: '取消', key: 'close', kind: 'ghost' }], true);
}
function restoreHard(hash) {
  openModal('用这个版本覆盖现在的文件？',
    '<div class="note">本地文件会变成 <span class="hintline">' + esc(String(hash).slice(0, 8)) +
    '</span> 那时候的样子。<br>没保存的改动会先自动收起来备份。</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '覆盖', key: 'ok', kind: 'danger' }]);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('restore', { hash: hash, mode: 'worktree' }, '用这个版本覆盖', ['track1', 'up', 'blue']);
  };
}

/* ================================================================ 删掉某个版本 */
function findCommit(hash) {
  var list = ((S.tl || {}).commits) || [];
  for (var i = 0; i < list.length; i++) {
    if (list[i].hash === hash || String(list[i].hash).indexOf(hash) === 0) { return list[i]; }
  }
  return null;
}

/* 两种「删」，先说清差别再让人点（不写术语，普通人看得懂的话） */
function deleteDialog(hash) {
  var c = findCommit(hash) || {};
  openModal('删掉这个版本',
    '<div class="note">要处理的是 <span class="hintline">' +
    esc(c.ver || String(hash).slice(0, 7)) + '</span>' +
    (c.subject ? '：' + esc(c.subject) : '') +
    (c.pushed ? '<br>它<b>已经传到 GitHub 上了</b>，所以云端那份也要一起处理。'
              : '<br>它<b>还没上云端</b>，只在你这台电脑上。') +
    '</div><div class="actions">' +
    '<button class="act" data-act="del-revert" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('rotate') + '</span><span>' +
    '<span class="at">撤销它（推荐，安全）</span>' +
    '<span class="ad">坏代码马上不生效；历史里多一条「撤销某某」，两版都还查得到，' +
    '别人不用重新下载</span></span></button>' +
    '<button class="act" data-act="del-purge" data-hash="' + esc(hash) + '">' +
    '<span class="ai">' + svg('x') + '</span><span>' +
    '<span class="at">彻底抹掉（危险，通常只有泄了密钥才需要）</span>' +
    '<span class="ad">从历史里抠掉这一版，后面的版本号全变' +
    (c.pushed ? '，还要强推覆盖云端' : '') + '</span></span></button>' +
    '</div>', [{ text: '取消', key: 'close', kind: 'ghost' }], true);
}

function purgeConfirm(hash) {
  var c = findCommit(hash) || {};
  openModal('真的要从历史里抹掉？',
    '<div class="note">这一版：<span class="hintline">' + esc(c.ver || '') + '</span> ' +
    esc(c.subject || '') + '<br><br>' +
    '· 它会从记录里消失，<b>它后面的版本号全部重排</b><br>' +
    (c.pushed ? '· 已经推上 GitHub ⇒ 会强推覆盖，<b>别人手上的这份记录会对不上</b><br>' : '') +
    '· 动手前我先打一个 <span class="hintline">moss-undo-…</span> 的标签，反悔时能回到现在这样<br>' +
    '· GitHub 上旧版本不会马上消失（一串哈希短期内还能打开）——' +
    '<b>要是这一版里泄了密码/密钥，务必先把那把密钥换掉再删</b></div>',
    [{ text: '算了', key: 'close', kind: 'ghost' },
     { text: '抹掉', key: 'ok', kind: 'danger' }], true);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('delete_commit', { hash: hash, mode: 'purge', push: true },
      '抹掉这个版本', ['track1', 'up', 'purple']);
  };
}

/* ================================================================ 看文件改动 */
function fileDiff(file) {
  busyOn('正在读…');
  call('file_op', { path: S.path, op: 'diff', file: file }).then(function (r) {
    openModal('改动：' + file,
      r.ok ? '<pre class="out">' + colorDiff(r.out) + '</pre>'
           : '<div class="note">看不到改动：' + esc(r.why || '') + '</div>',
      [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  }).catch(fail).then(function () { busyOff(); });
}

/* ================================================================ 更多功能 */
function moreMenu() {
  var v = viewState();
  var items = [
    ['branches', 'branch', '分支', '换一条线干活 / 把云端分支拿下来'],
    ['tags', 'tag', '标记版本', '给某个版本起个名字（v1.0 那种）'],
    ['changes', 'eye', '文件改动明细', '看每个文件改了什么、要不要丢弃'],
    ['mirror', 'mirror', '镜像 / 备份', '在 GitHub 上建仓库、整份备份到本地'],
    ['remote', 'cloud', '看看 GitHub 上长什么样', '星标、描述、默认分支'],
    ['log', 'command', '上次执行了什么命令', '这次点按钮到底跑了什么'],
    ['disks', 'drive', '磁盘空间', '看看各个盘还剩多少'],
    ['stash', 'save', '找回收起的改动', '获取最新版时自动备份的那些'],
    ['ignores', 'x', '屏蔽清单（不跟着提交的东西）', '哪些东西不进仓库；哪条其实还在库里'],
    ['big', 'drive', '体积排行', '谁把仓库撑大了（大文件会让推送推不上去）'],
    ['loc', 'command', '代码行数', '多少行代码（按文件行数，空行注释也算）'],
    ['synclog', 'command', '同步日志', '推送 / 拉取每一步花了多久、卡在哪一句'],
    ['precheck', 'eye', '推送前体检', '这一推多大、有没有 GitHub 装不下的文件'],
    ['clone', 'download', '从 GitHub 下载一份', '把云端仓库拷贝到这台电脑'],
    ['probe', 'wifi', '测一下能不能连上 GitHub', '网络 / 权限有没有问题'],
    ['all', 'command', '全部命令', '所有能做的事（给想用命令行的人）']
  ];
  var h = '<div class="actions">';
  items.forEach(function (it) {
    h += '<button class="act" data-act="more-item" data-what="' + it[0] + '">' +
      '<span class="ai">' + svg(it[1]) + '</span><span><span class="at">' + esc(it[2]) +
      '</span><span class="ad">' + esc(it[3]) + '</span></span></button>';
  });
  if (!v.isRepo) {
    h += '<button class="act" data-act="more-item" data-what="init">' +
      '<span class="ai">' + svg('plus') + '</span><span><span class="at">开始记录这个文件夹</span>' +
      '<span class="ad">把它变成受管理的文件夹</span></span></button>';
  }
  h += '</div>';
  openModal('更多功能', h, [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
}
function moreItem(w) {
  if (w === 'branches') { return dialogBranches(); }
  if (w === 'tags') { return dialogTags(); }
  if (w === 'changes') { return dialogChanges(); }
  if (w === 'mirror') { return mirrorMenu(); }
  if (w === 'remote') { return dialogRemote(); }
  if (w === 'log') { return showResult('上次执行了什么'); }
  if (w === 'disks') { return dialogDisks(); }
  if (w === 'stash') { return dialogStash(); }
  if (w === 'clone') { return dialogClone(); }
  if (w === 'probe') { return dialogProbe(); }
  if (w === 'ignores') { return dialogIgnore(); }
  if (w === 'big') { return dialogBigfiles(); }
  if (w === 'loc') { return dialogLoc(); }
  if (w === 'synclog') { return dialogSyncLog(); }
  if (w === 'precheck') { return dialogPrecheck(); }
  if (w === 'init') { closeModal(); return startRepo(); }
  if (w === 'all') { return dialogAll(); }
}
/* ============================ 屏蔽清单 / 体积排行 / 同步日志 / 推送前体检
   四张小面板的共同心思：**把黑盒打开**。以前"什么没跟着提交""为什么推不上去"
   只能去翻隐藏文件或者找 AI，现在界面上直接看、直接改。
   ============================================================================ */
function dialogIgnore() {
  openModal('屏蔽清单', '<div class="note" style="padding:12px 0">正在读…</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  paintIgnore();
}

function paintIgnore() {
  call('ignore', { path: S.path }).then(function (r) {
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    var rows = (r && r.entries) || [];
    var h = '<div class="note">这些写法命中的文件<b>不跟着提交</b>（电脑上照旧在用）。' +
      '标着「还在库里」的是以前已经被提交进去的 —— 那些每次推送都会跟着传一遍，' +
      '想让它们彻底不传，点后面的按钮。</div>';
    if (!rows.length) {
      h += '<div class="note">清单是空的 —— 现在什么都跟着提交，包括临时文件和模型、视频这类大件。</div>';
    }
    h += '<div class="picklist" style="max-height:44vh">';
    rows.forEach(function (e) {
      var bad = n0(e.tracked) > 0;
      h += '<div class="pick-row"><span class="nm">' + esc(e.pattern) + '</span>' +
        '<span class="hintline">' + (bad
          ? ('还在库里 ' + e.tracked + ' 个 / ' + esc(e.size || '')) : '') + '</span>' +
        (bad ? '<button class="mini-btn" data-act="unshield" data-pattern="' +
          esc(e.pattern) + '">从库里去掉</button>' : '') +
        '<button class="mini-btn" data-act="unignore" data-pattern="' +
        esc(e.pattern) + '">删掉这条</button></div>';
    });
    h += '</div>';
    h += '<div class="field"><label>再加一条（目录写 <span class="hintline">名字/</span>，' +
      '文件写文件名）</label><input type="text" id="igNew" ' +
      'placeholder="例如 .venv/ 或 data/ 或 *.mp4">' +
      '<div class="row-btns" style="margin-top:8px">' +
      '<button class="env-btn" data-act="ignore-add">加进清单</button></div></div>';
    h += '<div class="note">删掉一条只是让它<b>以后重新跟着提交</b>；已经提交过的文件' +
      '不会自己回来，要用命令行 <span class="hintline">git add</span> 再加一次。</div>';
    b.innerHTML = h;
  }).catch(fail);
}

function dialogBigfiles() {
  openModal('体积排行', '<div class="note" style="padding:12px 0">正在数…</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  call('bigfiles', { path: S.path, limit: 30 }).then(function (r) {
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    if (!r || !r.ok) {
      b.innerHTML = '<div class="note">数不出来：' + esc((r && r.why) || '') + '</div>';
      return;
    }
    var h = '<div class="note">版本库里一共 <b>' + n0(r.count) + '</b> 个文件，' +
      '合计 <b>' + esc(r.size || '') + '</b>。下面是最占地方的几个 —— ' +
      '推送慢、被 GitHub 拒，基本都是它们。</div>';
    h += '<div class="picklist" style="max-height:50vh">';
    (r.top || []).forEach(function (f, i) {
      h += '<div class="pick-row"><span class="nm">' + (i + 1) + '. ' + esc(f.path) + '</span>' +
        '<span class="hintline">' + esc(f.size) + '</span>' +
        '<button class="mini-btn" data-act="shield-one" data-pattern="' +
        esc(pathDir(f.path)) + '">屏蔽这类</button></div>';
    });
    h += '</div>';
    if ((r.bytes || 0) > 50 * 1024 * 1024) {
      h += '<div class="note" style="color:#b45309">超过 50MB 了。GitHub 单文件上限 100MB，' +
        '超了那一推一定失败 —— 用右边的「屏蔽这类」处理掉，别硬推。</div>';
    }
    b.innerHTML = h;
  }).catch(fail);
}

/* 一条文件路径 → 它所在目录（给"屏蔽这一类"用，省得一个个点） */
function pathDir(p) {
  var s = String(p || '').replace(/\\/g, '/');
  var i = s.lastIndexOf('/');
  return i > 0 ? (s.slice(0, i) + '/') : s;
}

/* 代码行数：两种口径并排（git 跟踪的 / 磁盘上全部），每种语言一行 */
function dialogLoc() {
  openModal('代码行数', '<div class="note" style="padding:12px 0">正在数…（文件多的话要几秒）</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  var libs = S.locLibs ? 1 : 0;
  /* ★ 两段加载（用户原话："每次都要等"）：
     第一段只数「跟着提交的」那一份 —— 0.3 秒就回来，先让人看到数字；
     第二段再去扫「磁盘上全部」—— 你这种项目里有几十万个素材文件，要好几秒。
     不让用户对着一个空转圈等到最后才看见结果。 */
  call('loc', { path: S.path, libs: libs, fast: 1 }).then(function (r0) {
    var b0 = sub('.dlg-b');
    if (b0 && el('modal').classList.contains('show') && r0 && r0.ok) {
      b0.innerHTML = '<div class="note">按「一个文件有多少行就算多少行」数的 —— ' +
        '<b>空行、注释都算</b>。只数代码，配置文件不算。</div>' +
        locBlock('跟着提交的（跟 GitHub 上一致）', r0.tracked, 'tracked') +
        '<div class="note" id="locAll">正在数「磁盘上全部」（这一份要几秒）…</div>';
    }
    return call('loc', { path: S.path, libs: libs });
  }).then(function (r) {
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    if (!r || !r.ok) {
      b.innerHTML = '<div class="note">数不出来：' + esc((r && r.why) || '') + '</div>';
      return;
    }
    var h = '<div class="note">按「一个文件有多少行就算多少行」数的 —— ' +
      '<b>空行、注释都算</b>。只数代码，配置文件（json / ini / txt / md / yml）不算。</div>';
    h += locBlock('跟着提交的（跟 GitHub 上一致）', r.tracked, 'tracked');
    h += locBlock('磁盘上全部（含还没提交的）', r.all, 'all');
    var top = ((r.all || {}).top || []).slice(0, 8);
    if (top.length) {
      h += '<div class="inst-loglabel" style="margin-top:10px">行数最多的文件</div>' +
        '<div class="picklist" style="max-height:26vh">';
      top.forEach(function (f, i) {
        h += '<div class="pick-row"><span class="nm">' + (i + 1) + '. ' + esc(f.path) + '</span>' +
          '<span class="hintline">' + esc(f.lang) + '　' + n0(f.lines) + ' 行</span></div>';
      });
      h += '</div>';
    }
    h += '<div class="row-btns" style="margin-top:10px">' +
      '<button class="env-btn alt" data-act="loc-libs">' +
      (libs ? '不数第三方库' : '连第三方库一起数') + '</button></div>';
    h += '<div class="note">第三方库 = 别人写的 vue / bootstrap / 图标包那些；' +
      '算进来数字会大很多，但那是「项目总共带了多少行」，不是「你写了多少行」。</div>';
    b.innerHTML = h;
  }).catch(fail);
}

function locBlock(title, d, key) {
  d = d || {};
  /* 没走完的那一份加「≥」——数字是数到哪儿算哪儿，不标就像数全了 */
  var h = '<div class="inst-loglabel" style="margin-top:12px">' + esc(title) + '　' +
    '<b>' + (d.cut ? '≥ ' : '') + n0(d.lines || 0) + '</b> 行　<span class="hintline">' +
    n0(d.files || 0) + ' 个文件</span></div>';
  if (d.cut) {
    h += '<div class="note" style="color:#b45309">这一份没走完（' + esc(d.secs || '') +
      ' 秒 / 目录太多就先停了）：这个项目里有海量素材目录（音频、图标、上传件），' +
      '那些不是代码。要确定的数字看上面「跟着提交的」那一份。</div>';
  }
  var rows = d.byLang || [];
  if (!rows.length) { return h + '<div class="note">没有代码文件。</div>'; }
  h += '<div class="picklist" style="max-height:32vh">';
  rows.forEach(function (x) {
    h += '<div class="pick-row"><span class="nm">' + esc(x.lang) + '</span>' +
      '<span class="hintline">' + n0(x.lines) + ' 行　' + n0(x.files) + ' 个文件</span></div>';
  });
  h += '</div>';
  return h;
}

function dialogSyncLog() {
  openModal('同步日志', '<div class="note" style="padding:12px 0">正在读…</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  call('sync_log', { n: 150 }).then(function (r) {
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    var lines = (r && r.lines) || [];
    var h = '<div class="note">推送 / 拉取每一步<b>花了多久、退出码、最后几行输出</b>都在这里。' +
      '再遇到"没反应"，把这一段发出来就能看出卡在哪一句、是网慢还是推不上去。</div>';
    h += '<div class="note"><span class="hintline">' + esc((r && r.path) || '') + '</span>' +
      (lines.length ? '（共 ' + n0(r.total) + ' 行，下面是最后 ' + lines.length + ' 行）' : '') +
      '</div>';
    h += '<pre class="out">' + esc(lines.length ? lines.join('\n')
      : ((r && r.out) || '还没有记录 —— 跑一次推送或获取最新版，这里就有了')) + '</pre>';
    b.innerHTML = h;
  }).catch(fail);
}

function dialogPrecheck() {
  openModal('推送前体检', '<div class="note" style="padding:12px 0">正在数…</div>',
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  call('push_check', { path: S.path }).then(function (r) {
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    if (!r || !r.ok) {
      b.innerHTML = '<div class="note">查不了：' + esc((r && r.why) || '') + '</div>';
      return;
    }
    var big = r.big || [];
    var h = '<div class="note">要传 <b>' + n0(r.files) + '</b> 个文件，大约 <b>' +
      esc(r.size || '') + '</b>，' + n0(r.commits) + ' 个提交还没上云端。</div>';
    if (!big.length) {
      h += '<div class="note">没有偏大的文件（上限是单个 ' + esc(r.limitHard) +
        '）—— 可以放心推。</div>';
    } else {
      h += '<div class="picklist" style="max-height:40vh">';
      big.forEach(function (x) {
        h += '<div class="pick-row"><span class="nm">' + esc(x.path) + '</span>' +
          '<span class="hintline">' + esc(x.size) +
          (x.level === 'block' ? '　推不上去' : '　偏大') + '</span>' +
          '<button class="mini-btn" data-act="shield-one" data-pattern="' +
          esc(x.pattern) + '">屏蔽</button></div>';
      });
      h += '</div>';
      h += '<div class="note" style="color:#b45309">' +
        esc(big[0].why) + '。屏蔽之后电脑上的文件还在，只是不再跟着提交。</div>';
    }
    b.innerHTML = h;
  }).catch(fail);
}

function dialogBranches() {
  var t = S.tl || {};
  var h = '<div class="note">现在在 <b>' + esc(t.head || '?') + '</b> 这条线上。</div>' +
    '<div class="picklist">';
  (t.branches || []).forEach(function (b) {
    h += '<div class="pick-row"><span class="nm">' + esc(b.name) +
      (b.current ? '　← 现在这条' : '') + '</span>' +
      '<span class="hintline">' + (b.ahead ? '本地多 ' + b.ahead + '　' : '') +
      (b.behind ? '云端多 ' + b.behind : '') + '</span>' +
      (b.current ? '' : '<button class="mini-btn" data-act="go-branch" data-branch="' +
        esc(b.name) + '">换过去</button>') + '</div>';
  });
  (t.remoteBranches || []).forEach(function (b) {
    var local = String(b.name).replace(/^[^/]+\//, '');
    h += '<div class="pick-row"><span class="nm">' + esc(b.name) + '</span>' +
      '<span class="hintline">云端的</span>' +
      '<button class="mini-btn" data-act="take-remote" data-branch="' + esc(b.name) +
      '" data-local="' + esc(local) + '">拿下来</button></div>';
  });
  h += '</div>';
  openModal('分支', h, [{ text: '新建一条线', key: 'new', kind: 'ghost' },
    { text: '关闭', key: 'close', kind: 'ghost' }], true);
  S.modalActs.new = function () {
    openModal('新建一条线', field('新分支叫什么', '', '例如：试试新写法', false, 'name') +
      '<div class="note">从现在的状态开一条新线，原来那条不受影响。</div>',
      [{ text: '取消', key: 'close', kind: 'ghost' },
       { text: '新建并换过去', key: 'ok', kind: 'primary' }]);
    S.modalActs.ok = function () {
      var v = (fieldValues().name || '').trim();
      closeModal();
      if (!v) { toast('给它起个名字', 'no'); return; }
      doSteps('switch_branch', { branch: v, create: true, stash: true }, '新建并换到 ' + v);
    };
  };
}
function dialogTags() {
  var t = S.tl || {};
  var h = '<div class="note">标记版本就是给某条记录起个名字，方便以后找回来。</div>';
  if (!(t.tags || []).length) { h += '<div class="note">还没有标记。</div>'; }
  else {
    h += '<div class="picklist">';
    t.tags.forEach(function (g) {
      h += '<div class="pick-row"><span class="nm">' + esc(g.name) + '</span>' +
        '<span class="hintline">' + esc(g.when || '') + '</span>' +
        '<button class="mini-btn" data-act="restore" data-hash="' + esc(g.short) + '">切回</button></div>';
    });
    h += '</div>';
  }
  openModal('标记版本', h, [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
}
function dialogChanges() {
  var r = ((S.snap || {}).repo) || {};
  if (!r.dirty) {
    openModal('文件改动', '<div class="note">没有新改动 —— 所有文件都已经保存过了。</div>',
      [{ text: '关闭', key: 'close', kind: 'ghost' }], true); return;
  }
  var h = '<div class="picklist">';
  (r.changes || []).forEach(function (f) {
    h += '<div class="pick-row"><span class="nm">' + esc(f.path) + '</span>' +
      '<span class="hintline">' + esc(wordFlag(f.flag)) + '</span>' +
      '<button class="mini-btn" data-act="file-diff" data-file="' + esc(f.path) + '">看改动</button>' +
      '<button class="mini-btn" data-act="file-drop" data-file="' + esc(f.path) + '">丢弃</button></div>';
  });
  h += '</div>';
  openModal('文件改动（' + n0(r.changeCount) + ' 个）',
    '<div class="note">「看改动」只看不动；「丢弃」会把这个文件的改动扔掉（回不到，小心）。</div>' + h,
    [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
}
function fileDrop(file) {
  openModal('丢弃这个文件的改动？',
    '<div class="note"><b>' + esc(file) + '</b> 里的改动会被扔掉，回到上次保存的样子。这一步回不去。</div>',
    [{ text: '算了', key: 'close', kind: 'ghost' },
     { text: '丢弃', key: 'ok', kind: 'danger' }]);
  S.modalActs.ok = function () {
    closeModal();
    busyOn('正在丢弃…');
    call('file_op', { path: S.path, op: 'discard', file: file }).then(function (r) {
      toast(r.ok ? '已丢弃：' + file : ('没成功：' + (r.why || '')), r.ok ? 'ok' : 'no');
      return loadAll();
    }).catch(fail).then(function () { busyOff(); });
  };
}
function dialogRemote() {
  busyOn('正在问 GitHub…');
  call('remote_repo', { path: S.path }).then(function (r) {
    busyOff();
    if (!r.ok) {
      openModal('GitHub 上的情况', '<div class="note">' + esc(r.why || '读不到') +
        '<br><br>想连上 GitHub，用「更多功能 → 镜像 / 备份」。</div>',
        [{ text: '关闭', key: 'close', kind: 'ghost' }]); return;
    }
    openModal('GitHub 上的情况',
      '<div class="note"><b>' + esc(r.fullName) + '</b>' +
      (r.visibility ? '（' + esc(r.visibility) + '）' : '') + '<br>' +
      esc(r.desc || '（没有描述）') + '</div>' +
      '<div class="note" style="margin-top:8px">★ ' + n0(r.stars) + '　fork ' + n0(r.forks) +
      '　默认分支 ' + esc(r.defaultBranch || '?') + '　最后推送 ' + esc(r.pushedAt || '-') + '</div>' +
      (r.url ? '<div class="field" style="margin-top:8px"><label>地址</label>' +
        '<pre class="out">' + esc(r.url) + '</pre></div>' : ''),
      [{ text: '关闭', key: 'close', kind: 'ghost' }]);
  }).catch(function (e) { busyOff(); fail(e); });
}
function dialogDisks() {
  busyOn('正在看磁盘…');
  call('disks', {}).then(function (r) {
    busyOff();
    var h = '<div class="picklist">';
    (r.disks || []).forEach(function (d) {
      h += '<div class="pick-row"><span class="nm">' + esc(d.root) + '</span>' +
        '<span class="hintline">' + (d.ready
          ? esc(d.type + ' · 剩 ' + d.freeText + ' / ' + d.totalText)
          : esc(d.type + ' · 读不到')) + '</span></div>';
    });
    h += '</div>';
    openModal('磁盘空间', h, [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
  }).catch(function (e) { busyOff(); fail(e); });
}
function dialogStash() {
  openModal('收起来的改动', '<div class="note" style="padding:12px 0">正在读…</div>',
    [{ text: '放回来（最近那份）', key: 'ok', kind: 'primary' },
     { text: '关闭', key: 'close', kind: 'ghost' }], true);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('run_action_key', { name: 'stash_pop' }, '把收起来的改动放回来', ['track1', 'up', 'blue']);
  };
  /* v12：列出每一份，多的可以一份一份删掉（原来只能看到"有几份"） */
  call('stashes', { path: S.path }).then(function (r) {
    S.stashItems = (r && r.items) || [];
    var b = sub('.dlg-b');
    if (!b || !el('modal').classList.contains('show')) { return; }
    var h = '<div class="note">获取最新版 / 换分支之前，我会把没保存的改动先收起来备份。' +
      '现在有 <b>' + n0(r.count) + '</b> 份。<br>' +
      '「放回来」是把<b>最近</b>那份放回文件里；「删掉」是扔掉某一份，删了就找不回。</div>';
    if (!r.ok) {
      h = '<div class="note">列不出来：' + esc(r.why || '') + '</div>';
    } else if (!(r.items || []).length) {
      h += '<div class="note">现在一份都没有。</div>';
    } else {
      h += '<div class="picklist">';
      r.items.forEach(function (it) {
        h += '<div class="pick-row"><span class="nm">' + esc(it.subject || '（没有说明）') + '</span>' +
          '<span class="hintline">' + esc(it.when || '') + '　' + esc(it.name) + '</span>' +
          '<button class="mini-btn del" data-act="stash-drop" data-index="' + esc(it.index) +
          '">删掉</button></div>';
      });
      h += '</div>';
    }
    b.innerHTML = h;
  }).catch(function () { /* 列不出来就保持原来的说明，不影响「放回来」 */ });
}
function stashDrop(index, label) {
  if (!label) {
    var hit = (S.stashItems || []).filter(function (x) { return x.index === index; })[0];
    label = (hit && hit.subject) || ('stash@{' + index + '}');
  }
  openModal('删掉这份收起的改动？',
    '<div class="note">这一份：<b>' + esc(label || '') + '</b><br><br>' +
    '删掉之后就<b>找不回来了</b>（不是放回文件，是直接扔掉）。</div>',
    [{ text: '算了', key: 'close', kind: 'ghost' },
     { text: '删掉', key: 'ok', kind: 'danger' }]);
  S.modalActs.ok = function () {
    closeModal();
    doSteps('drop_stash', { index: index }, '删掉一份收起的改动', ['track1', 'up', 'purple']);
  };
}
function dialogProbe() {
  busyOn('正在测试…');
  call('net_probe', { path: S.path }).then(function (r) {
    busyOff();
    openModal('能不能连上 GitHub',
      '<div class="note">' + (r.ok
        ? '✓ 能连上（' + n0(r.ms) + ' 毫秒' + (r.heads ? '，看到 ' + n0(r.heads) + ' 个分支' : '') + '）'
        : '✗ 连不上：' + esc(r.why || '')) + '</div>' +
      (r.cmd ? '<div class="field"><label>试的命令</label><pre class="out">' +
        esc(r.cmd) + '</pre></div>' : ''),
      [{ text: '关闭', key: 'close', kind: 'ghost' }]);
  }).catch(function (e) { busyOff(); fail(e); });
}
function dialogClone() {
  openModal('从 GitHub 下载一份',
    field('仓库地址', '', 'https://github.com/你的名字/仓库.git', false, 'url') +
    '<div class="note">会下载到<b>现在这个文件夹里面</b>。想放到新文件夹，先用右上角换文件夹。</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '下载', key: 'ok', kind: 'primary' }]);
  S.modalActs.ok = function () {
    var v = (fieldValues().url || '').trim();
    closeModal();
    if (!v) { toast('还没填仓库地址', 'no'); return; }
    busyOn('正在下载…');
    shootOrb('track2', 'up', 'purple');
    call('run_action', { name: 'clone', arg: v, path: S.path }).then(function (res) {
      S.last = { title: '从 GitHub 下载一份', res: res, at: stamp() };
      toast(res.ok ? '下载完成' : ('没成功：' + (res.why || '')), res.ok ? 'ok' : 'no');
      if (!res.ok) { showResult('从 GitHub 下载一份'); }
      return loadAll();
    }).catch(fail).then(function () { busyOff(); });
  };
}
function dialogAll() {
  var h = '';
  S.groups.forEach(function (g) {
    var list = S.actions.filter(function (a) { return a.group === g; });
    if (!list.length) { return; }
    h += '<div class="field"><label>' + esc(g) + '</label><div class="actions">';
    list.forEach(function (a) {
      h += '<button class="act" data-act="act" data-name="' + esc(a.name) + '"' +
        (a.needArg ? ' data-need="' + esc(a.needArg) + '"' : '') + '>' +
        '<span class="ai">' + svg('command') + '</span><span><span class="at">' + esc(a.label) +
        '</span><span class="ad">' + esc(a.cmd) + '　' + esc(a.desc) + '</span></span></button>';
    });
    h += '</div></div>';
  });
  openModal('全部命令', h, [{ text: '关闭', key: 'close', kind: 'ghost' }], true);
}

function mirrorMenu() {
  var hasGh = S.gh && S.gh.installed && S.gh.loggedIn;
  openModal('备到 GitHub',
    '<div class="note">这个文件夹还没连上 GitHub。选一种：</div>' +
    '<div class="actions">' +
    '<button class="act" data-act="mirror-pick" data-mode="gh_create"' + (hasGh ? '' : ' disabled') + '>' +
    '<span class="ai">' + svg('cloud') + '</span><span>' +
    '<span class="at">让 GitHub 自动建一个仓库并传上去</span>' +
    '<span class="ad">' + (hasGh ? '最简单，一键完成（账号：' + esc(S.gh.user || '已登录') + '）'
      : '要先装 gh 并登录一次（可选功能）。不想弄就直接选下面「我已经有一个仓库」——'
        + '上传用的是 git 自己的登录，跟 gh 没关系') +
    '</span></span></button>' +
    /* ★ 缺 gh / 没登录时，别只把按钮变灰让人发愣：就地给一条能走的路 */
    (hasGh ? '' :
      '<div class="note" style="padding:2px 0 6px">' +
      '<button class="env-btn" data-act="env-install" data-what="gh">帮我装 gh</button> ' +
      '<button class="env-btn alt" data-act="env-login">登录 gh（可选）</button> ' +
      '<button class="env-btn alt" data-act="env-open" data-url="' + URL_SIGNUP + '">还没有账号？注册</button>' +
      '</div>') +
    '<button class="act" data-act="mirror-pick" data-mode="url">' +
    '<span class="ai">' + svg('arrowUp') + '</span><span>' +
    '<span class="at">我已经有一个 GitHub 仓库，填地址</span>' +
    '<span class="ad">不想装 gh 就走这条：先去 github.com 点「New repository」建个空仓库，' +
    '把地址（形如 https://github.com/你的名字/仓库.git）粘进来</span></span></button>' +
    '<button class="act" data-act="mirror-pick" data-mode="local_clone">' +
    '<span class="ai">' + svg('mirror') + '</span><span>' +
    '<span class="at">只在本地备份一份（不用 GitHub）</span>' +
    '<span class="ad">在旁边生成一个整份拷贝，断网也能做</span></span></button>' +
    '</div>', [{ text: '取消', key: 'close', kind: 'ghost' }], true);
}
function mirrorForm(mode) {
  if (mode === 'gh_create') {
    var name = baseName(((S.snap || {}).repo || {}).root || S.path) || 'my-project';
    openModal('在 GitHub 上建一个仓库',
      field('仓库名', name, 'my-project', false, 'name') +
      '<label class="chk"><input type="checkbox" id="priv"> 建成私有的（别人看不到）</label>' +
      '<div class="note">会在这个账号下建好仓库，并把现在的文件传上去。</div>',
      [{ text: '取消', key: 'close', kind: 'ghost' },
       { text: '建好并上传', key: 'ok', kind: 'primary' }]);
    S.modalActs.ok = function () {
      var v = (fieldValues().name || '').trim() || name;
      var priv = !!(sub('.dlg-b #priv') || {}).checked;
      closeModal();
      doSteps('mirror', { mode: 'gh_create', name: v, private: priv },
        '在 GitHub 上建仓库并上传', ['track2', 'down', 'blue']);
    };
    return;
  }
  if (mode === 'url') {
    openModal('连到一个已有的 GitHub 仓库',
      field('仓库地址', '', 'https://github.com/你的名字/仓库.git', false, 'url') +
      '<div class="note">会把现在的文件传上去。如果云端已经有内容、你还没拉过，' +
      '建议先「获取最新版」。</div>',
      [{ text: '取消', key: 'close', kind: 'ghost' },
       { text: '连上并上传', key: 'ok', kind: 'primary' }]);
    S.modalActs.ok = function () {
      var v = (fieldValues().url || '').trim();
      closeModal();
      if (!v) { toast('还没填地址', 'no'); return; }
      doSteps('mirror', { mode: 'add_remote', url: v, remote: 'origin' },
        '连上 GitHub 并上传', ['track2', 'down', 'blue']);
    };
    return;
  }
  var root = ((S.snap || {}).repo || {}).root || S.path;
  var guess = String(root).replace(/[\\/]+$/, '') + '-备份.git';
  openModal('在本地备份一份',
    field('备份到哪里', guess, guess, false, 'dest') +
    '<div class="note">会在那个位置生成一个整份拷贝（所有版本都在里面），断网也能做。</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '开始备份', key: 'ok', kind: 'primary' }]);
  S.modalActs.ok = function () {
    var v = (fieldValues().dest || '').trim() || guess;
    closeModal();
    doSteps('mirror', { mode: 'local_clone', dest: v }, '在本地备份一份', ['track2', 'down', 'blue']);
  };
}

/* ================================================================ 选文件夹 */
function pickDir() {
  S.pick = { path: S.path };
  openModal('选一个文件夹', '<div class="note" style="padding:12px 0">正在读…</div>',
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '用这个文件夹', key: 'ok', kind: 'primary' }], true);
  gotoDir(S.path);
}
function gotoDir(p) {
  S.modalActs.ok = function () {
    var path = (S.pick && S.pick.path) || S.path;
    closeModal();
    openPath(path);
  };
  call('browse', { path: p }).then(function (r) {
    if (!el('modal').classList.contains('show')) { return; }
    var b = sub('.dlg-b'); if (!b) { return; }
    if (!r.ok) { b.innerHTML = '<div class="note">读不到：' + esc(r.why || '') + '</div>'; return; }
    S.pick.path = r.path;
    var h = '<div class="note">' + (r.isRepo ? '✓ 这个文件夹已经是托管文件夹' : '这个文件夹还没开始记录（也能选）') +
      '<br><span class="hintline">' + esc(r.path) + '</span></div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">';
    (r.roots || []).forEach(function (d) {
      h += '<button class="mini-btn" data-act="goto" data-path="' + esc(d.path) + '"' +
        (d.ready ? '' : ' disabled') + '>' + esc(d.name) + '</button>';
    });
    h += '<button class="mini-btn" data-act="goto" data-path="' + esc(r.parent) + '">上一层</button></div>' +
      '<div class="picklist">';
    if (!(r.dirs || []).length) {
      h += '<div class="pick-row"><span class="hintline">这下面没有子文件夹</span></div>';
    }
    (r.dirs || []).forEach(function (d) {
      h += '<div class="pick-row" data-act="goto" data-path="' + esc(d.path) + '" style="cursor:pointer">' +
        '<span class="nm">' + esc(d.name) + '</span>' +
        (d.repo ? '<span class="hintline">仓库</span>' : '') +
        '<span class="hintline">进去 →</span></div>';
    });
    h += '</div>';
    b.innerHTML = h;
  }).catch(fail);
}
function typeDir() {
  closeDirMenu();
  openModal('手动输入路径', field('文件夹路径', S.path || '', 'D:\\我的项目', false, 'path'),
    [{ text: '取消', key: 'close', kind: 'ghost' },
     { text: '打开', key: 'ok', kind: 'primary' }]);
  S.modalActs.ok = function () {
    var v = (fieldValues().path || '').trim();
    closeModal();
    if (v) { openPath(v); }
  };
}
function openPath(p) {
  if (!p) { toast('还没填路径', 'no'); return; }
  busyOn('正在打开…');
  call('set_path', { path: p }).then(function (r) {
    if (r.ok === false) { toast(r.why || '打不开这个文件夹', 'no'); log(r.why || ''); return null; }
    S.path = r.path || p; S.picks = null; S.limit = 20; S.tl = null; S.drawer = false;
    S.snap = r;
    renderHead();
    if (!r.isRepo) { syncUI(); return null; }
    return call('timeline', { path: S.path, limit: S.limit }).then(function (t) {
      S.tl = t; syncUI(); return t;
    });
  }).catch(fail).then(function () { busyOff(); });
}

/* ================================================================ 点击分发 */
document.addEventListener('click', function (ev) {
  var node = ev.target.closest ? ev.target.closest('[data-act]') : null;
  if (!node) { closeDirMenu(); return; }
  var act = node.getAttribute('data-act');
  var d = function (k) { return node.getAttribute('data-' + k); };

  if (act !== 'dir-menu' && act !== 'forget-dir' && act !== 'dir-clear') { closeDirMenu(); }
  if (act.indexOf('modal-') === 0) {
    var key = act.slice(6);
    if (key !== 'close' && S.modalActs && S.modalActs[key]) { S.modalActs[key](); return; }
    closeModal();
    return;
  }

  if (act === 'dir-menu') { renderDirMenu(!dirOpen); return; }
  if (act === 'forget-dir') {
    ev.stopPropagation();
    call('forget_path', { path: d('path') }).then(function (r) {
      if (S.snap) { S.snap.recent = r.recent; }
      renderDirMenu(true);
    }).catch(fail);
    return;
  }
  if (act === 'dir-clear') {
    ev.stopPropagation();
    call('forget_path', { path: '' }).then(function (r) {
      if (S.snap) { S.snap.recent = r.recent; }
      renderDirMenu(true);
      toast('记录清空了（文件夹本身没动）', 'ok');
    }).catch(fail);
    return;
  }
  if (act === 'use-dir') { openPath(d('path')); return; }
  if (act === 'goto') { ev.stopPropagation(); gotoDir(d('path')); return; }

  switch (act) {
    case 'refresh': {
      var btn = sub('.scan-btn');
      if (btn) { btn.classList.add('turning'); setTimeout(function () { btn.classList.remove('turning'); }, 520); }
      loadAll().then(function () { toast('已重新扫描', 'ok'); });
      break;
    }
    case 'pick-dir': pickDir(); break;
    case 'type-dir': typeDir(); break;
    case 'init-repo': startRepo(); break;
    case 'files-drawer':
      S.drawer = !S.drawer;
      el('fileDrawer').classList.toggle('open', S.drawer);
      el('drawerArrow').style.transform = S.drawer ? 'rotate(180deg)' : '';
      break;
    case 'save-local': saveLocal(); break;
    case 'backup': backup(); break;
    case 'fetch-new': fetchNew(); break;
    case 'more-commits': S.limit += 20; loadAll(); break;
    case 'detail': showCommit(d('hash')); break;
    case 'cloud-toggle':
      S.cloudOpen = !S.cloudOpen;
      syncUI();
      break;
    case 'cloud-refresh': refreshCloud(); break;
    case 'cloud-more':
      busyOn('正在读更早的云端版本…');
      call('cloud_versions', { path: S.path, limit: 120 }).then(function (c) {
        S.cloud = c; syncUI();
      }).catch(fail).then(function () { busyOff(); });
      break;
    case 'cloud-take': cloudTake(d('hash')); break;
    case 'cloud-take-safe':
      closeModal();
      doSteps('restore', { hash: d('hash'), mode: 'branch' },
        '取到一个新分支', ['track1', 'down', 'amber']);
      break;
    case 'cloud-take-hard':
      closeModal();
      openModal('用这个云端版本覆盖本地文件？',
        '<div class="note">本地文件会变成 <span class="hintline">' +
        esc(String(d('hash')).slice(0, 8)) + '</span> 那个版本的样子。<br>' +
        '没保存的改动会先自动收起来备份（之后能在「更多功能 → 找回收起的改动」里拿回来）。</div>',
        [{ text: '取消', key: 'close', kind: 'ghost' },
         { text: '覆盖本地', key: 'ok', kind: 'danger' }]);
      S.modalActs.ok = (function (hh) {
        return function () {
          closeModal();
          doSteps('restore', { hash: hh, mode: 'worktree' }, '把云端版本取到本地',
            ['track2', 'up', 'purple']);
        };
      })(d('hash'));
      break;
    case 'restore': restoreDialog(d('hash')); break;
    case 'restore-safe':
      closeModal();
      doSteps('restore', { hash: d('hash'), mode: 'branch' }, '存成一条新记录', ['track1', 'up', 'blue']);
      break;
    case 'restore-hard': restoreHard(d('hash')); break;
    case 'del-commit': deleteDialog(d('hash')); break;
    case 'del-revert':
      closeModal();
      doSteps('delete_commit', { hash: d('hash'), mode: 'revert', push: true },
        '撤销这个版本', ['track1', 'up', 'blue']);
      break;
    case 'del-purge': purgeConfirm(d('hash')); break;
    case 'stash-drop': stashDrop(Number(d('index')), d('label')); break;
    case 'env-detail': dialogEnv(); break;
    case 'env-recheck': refreshEnv().then(function () { toast('又检查了一遍', 'ok'); }); break;
    case 'env-install': envInstall(d('what')); break;
    case 'env-login': envLogin(); break;
    case 'env-identity': envIdentity(); break;
    case 'env-open': call('open_url', { url: d('url') }); break;
    case 'env-askai': envAskAi(); break;
    /* 「看进度」= 重新开那个进度窗口（关掉之后还能回来看） */
    case 'env-progress':
      INST.what = d('what') || 'gh';
      INST.t0 = Date.now() - (((S.env || {}).pendingInstall || {}).secs || 0) * 1000;
      INST.lastSig = '';
      openModal('装 ' + (INST.what === 'git' ? 'Git' : 'GitHub CLI') + ' 的进度',
        instFace(INST.what, { phase: 'run', text: '正在装', log: '' }),
        instButtons(INST.what, null), true);
      S.modalActs.next = function () { refreshEnv().then(dialogEnv); };
      startInstPoll(INST.what);
      break;
    case 'unignore':
      call('ignore', { path: S.path, op: 'remove', pattern: d('pattern') })
        .then(function () { toast('这条删掉了', 'ok'); paintIgnore(); }).catch(fail);
      break;
    case 'unshield':
      startJob('untrack', { arg: d('pattern') },
        '把 ' + d('pattern') + ' 从库里去掉', null, function () { dialogIgnore(); });
      break;
    case 'shield-one':
      startJob('shield', { patterns: [d('pattern')] },
        '屏蔽 ' + d('pattern'), null, function () { dialogPrecheck(); });
      break;
    case 'loc-open':
      dialogLoc();
      break;
    case 'loc-libs':
      S.locLibs = !S.locLibs;
      dialogLoc();
      break;
    case 'ignore-add': {
      var igv = ((el('igNew') || {}).value || '').trim();
      if (!igv) { toast('先填一条再点', 'no'); break; }
      call('ignore', { path: S.path, op: 'add', pattern: igv }).then(function (r) {
        toast((r && r.kept) ? '这条已经在清单里了' : '加好了', 'ok');
        paintIgnore();
      }).catch(fail);
      break;
    }
    case 'file-diff': fileDiff(d('file')); break;
    case 'file-drop': fileDrop(d('file')); break;
    case 'more': moreMenu(); break;
    case 'more-item': closeModal(); moreItem(d('what')); break;
    case 'mirror-pick': closeModal(); mirrorForm(d('mode')); break;
    case 'go-branch':
      closeModal();
      doSteps('switch_branch', { branch: d('branch'), stash: true }, '换到 ' + d('branch'));
      break;
    case 'take-remote':
      closeModal();
      doSteps('switch_branch', { branch: d('local'), create: true, base: d('branch') }, '把云端分支拿下来');
      break;
    case 'act': {
      var name = d('name');
      if (d('need')) {
        var a = S.actions.filter(function (x) { return x.name === name; })[0] || {};
        openModal(a.label || name,
          field(a.needArg || '填一下', '', a.needArg || '', false, 'arg') +
          '<div class="note">等价的命令：<span class="hintline">' + esc(a.cmd || '') + '</span></div>',
          [{ text: '取消', key: 'close', kind: 'ghost' },
           { text: '执行', key: 'ok', kind: 'primary' }]);
        S.modalActs.ok = function () {
          var v = (fieldValues().arg || '').trim();
          closeModal();
          if (!v) { toast('还没填', 'no'); return; }
          /* 走后台任务：这类动作可能很慢（比如屏蔽一整年的日志目录），
             不能因为一条 RPC 等太久就判它失败 */
          startJob('run_action', { name: name, arg: v }, a.label || name);
        };
      } else {
        closeModal();
        doSteps('run_action_key', { name: name }, node.textContent.trim() || name);
      }
      break;
    }
  }
});

/* 输入框回车 = 保存到本地（设计稿里那个「↵ 回车」） */
document.addEventListener('keydown', function (ev) {
  if (ev.key === 'Enter' && ev.target && ev.target.id === 'note') {
    saveLocal();
  }
  if (ev.key === 'Escape') { closeDirMenu(); }
  /* v14：F8 = 环境检查（出问题时不用满界面找入口） */
  if (ev.key === 'F8') { ev.preventDefault(); dialogEnv(); }
});

/* ================================================================ 拖放
   契约 §4.2 / §8：提示只能靠宿主的 dragend / drop 收；真路径在 moss.on('drop') 里。 */
var dragCaptured = false;
function hasFiles(e) {
  return !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf('Files') >= 0);
}
function showHint() { el('hint').classList.add('show'); }
function hideHint() { el('hint').classList.remove('show'); }
window.addEventListener('dragover', function (e) { if (hasFiles(e)) { e.preventDefault(); showHint(); } });
window.addEventListener('dragenter', function (e) { if (hasFiles(e)) { e.preventDefault(); } });
window.addEventListener('dragleave', function (e) {
  if (!dragCaptured && e.relatedTarget === null) { hideHint(); }
});
window.addEventListener('dragend', function () { dragCaptured = false; hideHint(); });
window.addEventListener('blur', function () { dragCaptured = false; hideHint(); });

if (window.moss) {
  moss.on('captured', function () { dragCaptured = true; });
  moss.on('dragend', function () { dragCaptured = false; hideHint(); });
  moss.on('drop', function (d) {
    hideHint(); dragCaptured = false;
    var items = (d && d.items) || [];
    if (!items.length) { toast('没拿到路径（拖的可能是文件，这个窗口只认文件夹）', 'no'); return; }
    var p = String(items[0]);
    toast('打开：' + baseName(p), 'ok');
    openPath(p);
  });
  moss.on('invoke', function (d) {
    var p = (d && (d.dir || d.path || (d.params && d.params.path))) || '';
    if (p) { openPath(String(p)); }
  });
  moss.on('visible', function () { loadAll(); });
}

boot();
