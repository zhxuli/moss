(function () {
  'use strict';

  var readyPromise = null;

  function bridgeReady() {
    if (!readyPromise) {
      readyPromise = new Promise(function (resolve) {
        if (window.moss || (window.pywebview && window.pywebview.api)) return resolve();
        window.addEventListener('pywebviewready', resolve, { once: true });
        setTimeout(resolve, 3000);
      });
    }
    return readyPromise;
  }

  function call(name, params) {
    return bridgeReady().then(function () {
      if (window.moss && typeof window.moss.call === 'function') {
        return window.moss.call(name, params || {});        
      }
      var fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
      if (typeof fn !== 'function') throw new Error('后端没有这个方法：' + name);
      return fn(params || {});
    });
  }

  function copyText(text) {
    text = String(text == null ? '' : text);
    return call('sys_copy', { text: text }).then(function (r) {
      if (r && r.ok === false) throw new Error(r.msg || '复制失败');
      return true;
    }).catch(function () {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(function () { return true; });
      }
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (!ok) throw new Error('这个环境不让复制');
      return true;
    });
  }

  window.SKILL_API = {
    isEmbedded: function () {
      return !!(window.moss && window.moss.env && window.moss.env.embedded);
    },

    list:     function () { return call('list', {}); },
    read:     function (id) { return call('read', { id: id }); },
    doc:      function (id) { return call('doc', { id: id }); },
    plan:     function (id, newId) { return call('plan', { id: id, new_id: newId || '' }); },
    allow:    function (id, yes) { return call('allow', { id: id, yes: !!yes }); },
    rm:       function (id) { return call('rm', { id: id, confirm: true }); },
    promote:  function (id, newId) {
      return call('promote', { id: id, confirm: true, new_id: newId || '' });
    },
    runOnce:  function (id) { return call('run_once', { id: id, args: {} }); },

    runStart: function (id) { return call('run_start', { id: id, args: {} }); },
    runPoll:  function (rid) { return call('run_poll', { rid: rid }); },
    runInput: function (rid, line) { return call('run_input', { rid: rid, line: line }); },
    runStop:  function (rid) { return call('run_stop', { rid: rid }); },
    reveal:   function (dir) { return call('reveal', { dir: dir || '' }); },

    runs:     function (id) { return call('runs', { id: id || '' }); },
    clearRuns: function (id) { return call('clear_runs', { id: id || '' }); },

    openPath: function (path, how, raw) {
      return call('open_path', { path: path || '', mode: how === 'reveal' ? 'reveal' : 'open',
                                 raw: raw || '' });
    },
    copy:     copyText,
  };
})();
