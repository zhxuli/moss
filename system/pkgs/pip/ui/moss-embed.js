(function () {
  'use strict';

  const EMBEDDED = window.parent && window.parent !== window;
  const handlers = {};
  const waiting = {};
  let seq = 0;
  let readyFired = false;
  let readyInfo = null;

  function fire(name, data) {
    (handlers[name] || []).forEach(function (fn) {
      try { fn(data); } catch (e) { console.error('[moss] 事件处理出错', name, e); }
    });
  }

  function markReady(info) {
    if (readyFired) return;
    readyFired = true;
    readyInfo = info || { embedded: EMBEDDED };
    moss.ready = true;
    fire('ready', readyInfo);
  }

  const moss = {
    env: { embedded: EMBEDDED },
    ready: false,
    on: function (name, fn) {
      (handlers[name] = handlers[name] || []).push(fn);
      if (name === 'ready' && readyFired) {
        setTimeout(function () {
          try { fn(readyInfo); } catch (e) { console.error('[moss] ready 补枪出错', e); }
        }, 0);
      }
      return function () { moss.off(name, fn); };
    },
    off: function (name, fn) {
      handlers[name] = (handlers[name] || []).filter(function (f) { return f !== fn; });
    },
    __emit: function (name, data) { fire(name, data); },
    call: function (method, params) {
      if (EMBEDDED) return callViaHost(method, params);
      return callViaPywebview(method, params);
    }
  };
  window.moss = moss;

  function callViaHost(method, params) {
    return new Promise(function (resolve, reject) {
      const id = 'r' + (++seq);
      waiting[id] = { resolve: resolve, reject: reject };
      window.parent.postMessage(
        { moss: 1, kind: 'call', id: id, method: method, params: params || {} }, '*');
    });
  }

  function callViaPywebview(method, params) {
    return new Promise(function (resolve, reject) {
      function go(api) {
        const fn = api && api[method];
        if (typeof fn !== 'function') { reject(new Error('后端没有这个方法：' + method)); return; }
        Promise.resolve(fn(params || {})).then(resolve, reject);
      }
      if (window.pywebview && window.pywebview.api) { go(window.pywebview.api); return; }
      window.addEventListener('pywebviewready', function () { go(window.pywebview.api); },
                              { once: true });
    });
  }

  if (EMBEDDED) {
    const api = new Proxy({}, {
      get: function (_t, name) {
        if (typeof name !== 'string') return undefined;
        return function (params) { return moss.call(name, params); };
      }
    });
    window.pywebview = { api: api };
  }

  window.addEventListener('message', function (ev) {
    const m = ev.data;
    if (!m || m.moss !== 1) return;
    if (m.kind === 'result') {
      const w = waiting[m.id];
      if (!w) return;
      delete waiting[m.id];
      if (m.ok) w.resolve(m.result); else w.reject(new Error(m.error || '后端报错'));
    } else if (m.kind === 'event') {
      fire(m.name, m.data);
    }
  });

  window.addEventListener('pywebviewready', function () {
    if (!EMBEDDED) markReady({ embedded: false });
  }, { once: true });

  if (EMBEDDED) {
    window.parent.postMessage({ moss: 1, kind: 'ready' }, '*');
    setTimeout(function () { markReady({ embedded: true }); }, 0);
  }
})();
