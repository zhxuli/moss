/* moss 界面垫片（示例包用；其它包直接把这个文件抄走就行）
   ============================================================================
   一句话：**让同一份界面代码，既能被嵌进 moss 的「界面」选项卡，也能自己开窗口。**

   它在页面里提供一套统一的东西给界面用：

     await moss.call('bmi', {height: 175, weight: 70})   → 调后端的一个方法
     moss.on('time', d => { ... })                       → 接后端主动推过来的事件
     moss.on('ready', fn) / moss.on('invoke', fn) ...    → 接宿主发来的事件（见 §事件）
     moss.env                                            → {embedded, pid?...}

   ★ 两种环境自动分流，界面代码一个字都不用改：
     · 被内嵌（moss 的 iframe 里）→ 跟宿主 postMessage，宿主再转发给包的**后端进程**；
     · 独立窗口（包自己开的 pywebview）→ 直接走 `window.pywebview.api.<方法>`，
       事件则靠后端调 `window.moss.__emit(name, data)` 送进来。

   ★ 还顺手把 `window.pywebview.api` 也垫出来了 —— 老包（img / exec 那种）直接写
     `window.pywebview.api.xxx()` 的，被内嵌时**一行都不用改**。
   ============================================================================ */
(function () {
  'use strict';

  const EMBEDDED = window.parent && window.parent !== window;
  const handlers = {};          // 事件名 -> [fn]
  const waiting = {};           // 请求 id -> {resolve, reject}
  let seq = 0;

  function fire(name, data) {
    (handlers[name] || []).forEach(function (fn) {
      try { fn(data); } catch (e) { console.error('[moss] 事件处理出错', name, e); }
    });
  }

  /* ---------------------------------------------------------------- 事件
     宿主 / 后端能发过来的：
       ready    页面就绪（垫片自己发一次）
       invoke   宿主在详情页点了「运行」，params 就是参数框里那串
       drop     拖进来的真实路径（宿主给的，见 moss 的 V-41/V-42）
       theme    深浅色变了 {dark: true|false}
       visible  切到 / 离开这一页 {visible: true|false}
       close    要关掉了，给一次保存机会
       time 等  后端自己推的业务事件（示例：Python 推的时间） */
  const moss = {
    env: { embedded: EMBEDDED },
    on: function (name, fn) {
      (handlers[name] = handlers[name] || []).push(fn);
      return function () { moss.off(name, fn); };
    },
    off: function (name, fn) {
      handlers[name] = (handlers[name] || []).filter(function (f) { return f !== fn; });
    },
    /* 宿主 / 包自己的后端用它往页面发事件（两种环境都走这里） */
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
        // 宿主统一只给一个参数（`P-17`：参数是一个字符串/一份 JSON，不做 argv 数组）
        Promise.resolve(fn(params || {})).then(resolve, reject);
      }
      if (window.pywebview && window.pywebview.api) { go(window.pywebview.api); return; }
      window.addEventListener('pywebviewready', function () { go(window.pywebview.api); },
                              { once: true });
    });
  }

  /* 老包用的那套桥：内嵌时把它垫出来（方法名转发到宿主） */
  if (EMBEDDED) {
    const api = new Proxy({}, {
      get: function (_t, name) {
        if (typeof name !== 'string') return undefined;
        return function (params) { return moss.call(name, params); };
      }
    });
    window.pywebview = { api: api };
  }

  /* 宿主 → 页面：结果、事件 */
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

  /* 独立窗口里，后端要发事件就调 window.moss.__emit(...) —— 在这边把 pywebview 的
     就绪事件也转成统一的 ready，让界面只写一次初始化。 */
  window.addEventListener('pywebviewready', function () {
    if (!EMBEDDED) fire('ready', { embedded: false });
  }, { once: true });

  if (EMBEDDED) {
    // 内嵌：告诉宿主"我这边准备好了"（宿主会把它当成"可以开始派活了"）
    window.parent.postMessage({ moss: 1, kind: 'ready' }, '*');
    setTimeout(function () { fire('ready', { embedded: true }); }, 0);
  }
})();
