(function () {
  'use strict';
  if (window.__mossErrorGuard) return;              
  window.__mossErrorGuard = true;

  var MAX_KEEP = 30;            
  var MAX_SEND = 40;            
  var MAX_STACK = 1200;         

  var errors = [];              
  var queue = [];               
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

  function oneLine(e) {
    var s = e.msg || '(没有消息)';
    if (e.src) s += '（' + String(e.src).split('/').pop() + ':' + (e.line || 0) +
                    (e.col ? ':' + e.col : '') + '）';
    return s;
  }

  function trySend(payload) {
    if (sent >= MAX_SEND) return false;
    var m = window.moss;
    if (!m || typeof m.call !== 'function') { queue.push(payload); return false; }
    sent += 1;
    try {
      var p = m.call('ui_error', payload);
      if (p && typeof p.then === 'function') p.then(function () {}, function () {});
    } catch (e) {  }
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
    try {
      if (window.moss && typeof window.moss.on === 'function') window.moss.on('ready', flush);
    } catch (e) {  }
    var tries = 0;
    var t = setInterval(function () {
      tries += 1;
      flush();
      if (!queue.length || tries > 20) clearInterval(t);      
    }, 500);
  }

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
          selectDetail();
          bCopy.textContent = '已选中 · 按 Ctrl+C';
        }
        setTimeout(function () { bCopy.textContent = '复制'; }, 2400);
      });
    };
    bClose.onclick = function () { bar.style.display = 'none'; };
    return bar;
  }

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
    } catch (e) {  }
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

  function copyText(text, done) {
    var reported = false;
    function finish(ok) {
      if (reported) return;
      reported = true;
      try { done(!!ok); } catch (e) {  }
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
    } catch (e) {  }
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
      bar.style.display = 'block';                       
      bar.style.background = '#7f1d1d';
    } catch (e) {
    } finally {
      busy = false;
    }
  }

  var lastSig = '', lastAt = 0;

  function report(e) {
    try {
      if (!e || !e.msg) return;

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
    } catch (x) {  }
  }

  window.addEventListener('error', function (ev) {
    try {
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
    } catch (x) {  }
  }, true);                                   

  window.addEventListener('unhandledrejection', function (ev) {
    try {
      var r = ev && ev.reason;
      var msg = (r && (r.message || r.msg)) || String(r || '未处理的 Promise 拒绝');
      report({at: nowText(), msg: '未处理的 Promise：' + str(msg, 300),
              src: '', line: 0, col: 0, stack: (r && r.stack) || ''});
    } catch (x) {  }
  });

  window.onerror = function () { return false; };

  armFlush();

  window.__mossErrorGuardApi = {
    list: function () { return errors.slice(); },
    dump: dumpText,
    report: report,                            
    flush: flush
  };
})();
