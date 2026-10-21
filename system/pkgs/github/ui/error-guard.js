/* moss 插件界面 · 错误兜底（`ui/error-guard.js`）
   ============================================================================
   干什么：把界面里**任何没被接住的异常**变成看得见的一条 —— 页面底部一条红条，
   点开有堆栈、能一键复制。同时往包自己的数据目录记一份（`ui-errors.log`）。

   为什么要有它（真事，2026-10-20）：github 插件点「帮我装 gh」永远停在
   “正在启动 · 已经 0 秒”。根因是 `S.modalActs` 没初始化，`envInstall()` 第一句
   就抛 `TypeError` —— 异常只躺在 DevTools 控制台里：**用户看不见、AI 也读不到**，
   于是三个人围着同一个死现象猜了三轮。这个文件就是堵那个洞。

   ★ 两种跑法都必须工作（这是硬要求）：
     · **内嵌**（moss 的「界面」选项卡 → iframe）：`window.moss.call(...)`
       → 宿主 → 包的后端进程（stdin/stdout 上的 JSON 行）；
     · **独立窗口**（包自己 pywebview 开的窗）：`window.pywebview.api.<方法>`
       → 后端（`build_api()` 按 Core 自动转发）。
     这里**不自己判断模式**：统一用垫片给的 `window.moss.call`，它内部已经分流
     （`moss-embed.js` 的 `callViaHost` / `callViaPywebview`）。只在本文件比垫片
     先跑、`moss` 还没出现时排队，等它 ready 再补发。

   ★ 三条铁律：
     1. 兜底代码自己绝不能抛（整段 try/catch，且一次性防重入）；
     2. 不许把原错误吞掉 —— 照样 `console.error`，方便 DevTools 里看；
     3. 不许刷屏：内存里最多留 30 条、每次页面最多上报 40 条、红条同时只显示一条摘要。
   ============================================================================ */
(function () {
  'use strict';
  if (window.__mossErrorGuard) return;              // 只装一次（页面被重复执行也不叠）
  window.__mossErrorGuard = true;

  var MAX_KEEP = 30;            // 内存里留多少条
  var MAX_SEND = 40;            // 本页最多上报多少次（防死循环刷日志）
  var MAX_STACK = 1200;         // 堆栈截断

  var errors = [];              // [{at,msg,src,line,col,stack}]
  var queue = [];               // 还没发出去的（垫片还没就绪时）
  var sent = 0;
  var busy = false;

  var BAR_ID = 'moss-error-guard';

  function nowText() {
    var d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function modeName() {
    try {
      if (window.parent && window.parent !== window) return 'embedded';
      if (window.pywebview && window.pywebview.api) return 'standalone';
      return 'unknown';
    } catch (e) { return 'unknown'; }
  }

  function str(v, n) {
    var s = (v === null || v === undefined) ? '' : String(v);
    return s.length > (n || 300) ? s.slice(0, n || 300) + '…' : s;
  }

  /* 统一的一行摘要：`消息（文件:行:列）` */
  function oneLine(e) {
    var s = e.msg || '(没有消息)';
    if (e.src) s += '（' + String(e.src).split('/').pop() + ':' + (e.line || 0) +
                    (e.col ? ':' + e.col : '') + '）';
    return s;
  }

  /* ---------------------------------------------------------------- 上报后端
     `moss.call('ui_error', {...})`：两种跑法都由垫片分流；
     垫片还没就绪 → 先排队，等 ready 补发；10 秒还没等到就只留在内存里。 */
  function trySend(payload) {
    if (sent >= MAX_SEND) return false;
    var m = window.moss;
    if (!m || typeof m.call !== 'function') { queue.push(payload); return false; }
    sent += 1;
    try {
      var p = m.call('ui_error', payload);
      if (p && typeof p.then === 'function') p.then(function () {}, function () {});
    } catch (e) { /* 上报失败不能再抛 */ }
    return true;
  }

  function flush() {
    if (!queue.length) return;
    var m = window.moss;
    if (!m || typeof m.call !== 'function') return;
    var todo = queue.splice(0, queue.length);
    for (var i = 0; i < todo.length; i++) trySend(todo[i]);
  }

  function armFlush() {
    // 垫片 ready 的两种触发（内嵌是它自己给的，独立窗口等 pywebviewready）
    try {
      if (window.moss && typeof window.moss.on === 'function') window.moss.on('ready', flush);
    } catch (e) { /* 无妨 */ }
    var tries = 0;
    var t = setInterval(function () {
      tries += 1;
      flush();
      if (!queue.length || tries > 20) clearInterval(t);      // 最多等 10 秒
    }, 500);
  }

  /* ---------------------------------------------------------------- 红条 */
  function ensureBar() {
    var bar = document.getElementById(BAR_ID);
    if (bar) return bar;
    var host = document.body || document.documentElement;
    if (!host) return null;
    bar = document.createElement('div');
    bar.id = BAR_ID;
    bar.setAttribute('role', 'alert');
    bar.style.cssText = [
      'position:fixed', 'left:8px', 'right:8px', 'bottom:8px', 'z-index:2147483000',
      'background:#7f1d1d', 'color:#fff', 'border-radius:10px', 'overflow:hidden',
      'box-shadow:0 12px 34px rgba(0,0,0,.38)',
      'font:12px/1.5 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif',
      'text-align:left'
    ].join(';');

    var head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 10px';

    var tag = document.createElement('span');
    tag.textContent = '界面报错了';
    tag.style.cssText = 'flex:none;font-weight:600';

    var msg = document.createElement('span');
    msg.id = BAR_ID + '-msg';
    msg.style.cssText = ('flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;' +
                         'white-space:nowrap;opacity:.92');

    function mkBtn(text, title) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = text;
      if (title) b.title = title;
      b.style.cssText = ('flex:none;border:0;border-radius:6px;padding:3px 8px;cursor:pointer;' +
                         'background:rgba(255,255,255,.16);color:#fff;font:inherit');
      return b;
    }
    var bMore = mkBtn('详情', '看这几条错误的堆栈');
    var bCopy = mkBtn('复制', '把这段错误复制下来发给 AI');
    var bClose = mkBtn('×', '先收起来（错误还在内存里）');

    head.appendChild(tag);
    head.appendChild(msg);
    head.appendChild(bMore);
    head.appendChild(bCopy);
    head.appendChild(bClose);

    var detail = document.createElement('div');
    detail.id = BAR_ID + '-detail';
    detail.style.cssText = ('display:none;max-height:210px;overflow:auto;padding:8px 10px;' +
                            'background:rgba(0,0,0,.28);border-top:1px solid rgba(255,255,255,.18)');

    bar.appendChild(head);
    bar.appendChild(detail);
    host.appendChild(bar);

    bMore.onclick = function () {
      detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
      bMore.textContent = detail.style.display === 'none' ? '详情' : '收起';
    };
    bCopy.onclick = function () {
      copyText(dumpText(), function (ok) {
        if (ok) {
          bCopy.textContent = '已复制';
        } else {
          // 两条复制路都被挡（内嵌 iframe 常见）→ 展开并**全选**文本，直接 Ctrl+C
          selectDetail();
          bCopy.textContent = '已选中 · 按 Ctrl+C';
        }
        setTimeout(function () { bCopy.textContent = '复制'; }, 2400);
      });
    };
    bClose.onclick = function () { bar.style.display = 'none'; };
    return bar;
  }

  /* 复制两条路都被挡时：展开详情并**全选**文本 —— 用户直接 Ctrl+C 就行，
     不用自己在小字里拖选（内嵌 iframe 里这是最常见的情形）。 */
  function selectDetail() {
    try {
      var detail = document.getElementById(BAR_ID + '-detail');
      if (detail) detail.style.display = 'block';
      var pre = detail && detail.querySelector('pre');
      if (!pre) return;
      var r = document.createRange();
      r.selectNodeContents(pre);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    } catch (e) { /* 无妨 */ }
  }

  function dumpText() {
    var out = ['[moss 界面报错] 模式=' + modeName() +
               ' 页面=' + str(location.href, 200) + ' 条数=' + errors.length];
    for (var i = 0; i < errors.length; i++) {
      var e = errors[i];
      out.push('--- ' + e.at + ' ' + oneLine(e));
      if (e.stack) out.push(e.stack);
    }
    return out.join('\n');
  }

  /* 复制：优先 clipboard，其次 execCommand，最后把文本塞进可选中区域让用户 Ctrl+C。
     ★ 内嵌的 iframe 里 clipboard 经常被权限挡住，所以必须有退路；
     ★ 而且 `writeText` 失败是**异步 reject** —— 不接住的话它会变成一条
       "未处理的 Promise"，被本文件自己记成一条假错误（真机上就这么绕过一次）。
       所以这里一律走 `done(ok)` 回调，按钮文案按**实际结果**给。 */
  function copyText(text, done) {
    var reported = false;
    function finish(ok) {
      if (reported) return;
      reported = true;
      try { done(!!ok); } catch (e) { /* 无妨 */ }
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        var p = navigator.clipboard.writeText(text);
        if (p && typeof p.then === 'function') {
          p.then(function () { finish(true); }, function () { finish(legacyCopy(text)); });
        } else {
          finish(true);
        }
        return;
      }
    } catch (e) { /* 往下走 */ }
    finish(legacyCopy(text));
  }

  function legacyCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return !!ok;
    } catch (e) { return false; }
  }

  function paint() {
    if (busy) return;
    busy = true;
    try {
      var bar = ensureBar();
      if (!bar) return;
      var msg = document.getElementById(BAR_ID + '-msg');
      var last = errors[errors.length - 1];
      if (msg) msg.textContent = oneLine(last) + (errors.length > 1 ? '（+' + (errors.length - 1) + '）' : '');
      var detail = document.getElementById(BAR_ID + '-detail');
      if (detail) {
        var pre = detail.querySelector('pre');
        if (!pre) { pre = document.createElement('pre'); detail.appendChild(pre); }
        pre.style.cssText = ('margin:0;font:11px/1.45 ui-monospace,Consolas,monospace;' +
                             'white-space:pre-wrap;word-break:break-word');
        pre.textContent = dumpText();
      }
      bar.style.display = 'block';                       // 之前被 × 收起来了 → 有新错误再弹出来
      bar.style.background = '#7f1d1d';
    } catch (e) {
      /* 兜底本身出错：算了，绝不能因此再触发一轮 */
    } finally {
      busy = false;
    }
  }

  /* ---------------------------------------------------------------- 记一条 */
  var lastSig = '', lastAt = 0;

  function report(e) {
    try {
      if (!e || !e.msg) return;
      /* ★ 去重：同一个错误在极短时间里会从两条路各来一次（`error` 事件 + 老的
         `window.onerror`），重复的只留一条 —— 否则红条上写着"（+1）"、
         日志里也是两条一模一样的东西，看着像两个 bug。 */
      var sig = e.msg + '|' + (e.src || '') + '|' + (e.line || 0);
      var t = Date.now();
      if (sig === lastSig && t - lastAt < 400) return;
      lastSig = sig;
      lastAt = t;

      errors.push(e);
      if (errors.length > MAX_KEEP) errors.splice(0, errors.length - MAX_KEEP);
      window.__mossUiErrors = errors;
      try { console.error('[moss 界面报错]', e.msg, e.stack || ''); } catch (x) {}
      paint();
      trySend({msg: e.msg, src: e.src || '', line: e.line || 0, col: e.col || 0,
               stack: str(e.stack, MAX_STACK), at: e.at, mode: modeName(),
               url: str(location.href, 300)});
    } catch (x) { /* 绝不外抛 */ }
  }

  /* ---------------------------------------------------------------- 挂钩子 */
  window.addEventListener('error', function (ev) {
    try {
      // 资源加载失败（img/script）也会走这里，但它们没有 `ev.error`，消息也不一样
      var t = ev && (ev.target || null);
      if (t && t !== window && (t.src || t.href)) {
        report({at: nowText(), msg: '资源加载失败：' + str(t.src || t.href, 200),
                src: '', line: 0, col: 0, stack: ''});
        return;
      }
      var err = ev && ev.error;
      report({at: nowText(),
              msg: (err && err.message) || (ev && ev.message) || '未知脚本错误',
              src: (ev && ev.filename) || '',
              line: (ev && ev.lineno) || 0,
              col: (ev && ev.colno) || 0,
              stack: (err && err.stack) || ''});
    } catch (x) { /* 绝不外抛 */ }
  }, true);                                   // 捕获阶段：资源错误才会冒到这里

  window.addEventListener('unhandledrejection', function (ev) {
    try {
      var r = ev && ev.reason;
      var msg = (r && (r.message || r.msg)) || String(r || '未处理的 Promise 拒绝');
      report({at: nowText(), msg: '未处理的 Promise：' + str(msg, 300),
              src: '', line: 0, col: 0, stack: (r && r.stack) || ''});
    } catch (x) { /* 绝不外抛 */ }
  });

  /* 老的 `window.onerror`：**只保留"不吞错"的语义**，不再另行上报 ——
     `addEventListener('error')` 那条已经在，两个都报会让同一条错误记两遍
     （去重虽然兜得住，但少一条路更干净）。返回 false = 控制台照旧报。 */
  window.onerror = function () { return false; };

  armFlush();

  // 给自检/探针用的把手（不占全局名，撞不了）
  window.__mossErrorGuardApi = {
    list: function () { return errors.slice(); },
    dump: dumpText,
    report: report,                            // 手测用：__mossErrorGuardApi.report({msg:'测试'})
    flush: flush
  };
})();
