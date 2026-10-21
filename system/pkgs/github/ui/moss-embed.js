/* moss 界面垫片（从示例包 bmi 抄来的，一个字没改逻辑）
   ============================================================================
    一句话：**让同一份界面代码，既能被嵌进 moss 的「界面」选项卡，也能自己开窗口。**

    它在页面里提供一套统一的东西给界面用：

      await moss.call('snapshot', {path: 'D:\\code\\x'})   → 调后端的一个方法
      moss.on('drop', d => { ... })                        → 接宿主/后端推过来的事件
      moss.env                                            → {embedded, pid?...}

   ★ 两种环境自动分流，界面代码一个字都不用改：
     · 被内嵌（moss 的 iframe 里）→ 跟宿主 postMessage，宿主再转发给包的**后端进程**；
     · 独立窗口（包自己开的 pywebview）→ 直接走 `window.pywebview.api.<方法>`，
       事件则靠后端调 `window.moss.__emit(name, data)` 送进来。

   ★★ `ready` 是**粘的**（`V-287`）：这一枪打得很早（内嵌时就在本文件这一句上），
     晚一步订阅的 app.js 就收不到 ⇒ 页面永远停在"正在读"。所以 ready 一发就记下来
     （`moss.ready`），**晚订阅的人补一枪**。别的（drop / visible …）不粘。
   ============================================================================ */
(function () {
  'use strict';

  const EMBEDDED = window.parent && window.parent !== window;
  const handlers = {};          // 事件名 -> [fn]
  const waiting = {};           // 请求 id -> {resolve, reject}
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

  /* ★ 每次调用都带**超时**：内嵌时这条链是
     iframe → 宿主 JS → 宿主 Python → 包的后端进程（stdin/stdout）→ 原路回来，
     中间任何一环漏掉一条回复，界面就永远等下去 —— 真机上的表现是安装窗死死停在
     「正在启动 · 已经 0 秒」、点什么都没反应，而控制台里一个字都没有。
     有超时至少会 reject，让上层能把"等不到回话"画到界面上。 */
  const CALL_TIMEOUT_MS = 30000;

  function callViaHost(method, params) {
    return new Promise(function (resolve, reject) {
      const id = 'r' + (++seq);
      const timer = setTimeout(function () {
        if (!waiting[id]) return;
        delete waiting[id];
        reject(new Error('后端 ' + Math.round(CALL_TIMEOUT_MS / 1000) +
                         ' 秒没回话（' + method + '）'));
      }, CALL_TIMEOUT_MS);
      waiting[id] = {
        resolve: function (v) { clearTimeout(timer); resolve(v); },
        reject: function (e) { clearTimeout(timer); reject(e); }
      };
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

  /* 拖放进来了 → **告诉宿主**（`V-204`）：真实路径只有父页面那侧拿得到。 */
  if (EMBEDDED) {
    let over = false;
    let captured = false;
    function tellDrag(phase) {
      if (phase === 'over' && over) return;
      if (phase === 'out' && (!over || captured)) return;
      over = (phase === 'over');
      try { window.parent.postMessage({ moss: 1, kind: 'drag', phase: phase }, '*'); } catch (e) {}
    }
    function hasFiles(e) {
      return !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf('Files') >= 0);
    }
    window.addEventListener('dragenter', function (e) { if (hasFiles(e)) tellDrag('over'); });
    window.addEventListener('dragover', function (e) { if (hasFiles(e)) tellDrag('over'); });
    window.addEventListener('dragleave', function (e) { if (!e.relatedTarget) tellDrag('out'); });
    window.addEventListener('drop', function () { tellDrag('out'); });
    moss.on('captured', function () { captured = true; });
    moss.on('dragend', function () { captured = false; over = false; });
  }

  window.addEventListener('pywebviewready', function () {
    if (!EMBEDDED) markReady({ embedded: false });
  }, { once: true });

  if (EMBEDDED) {
    window.parent.postMessage({ moss: 1, kind: 'ready' }, '*');
    setTimeout(function () { markReady({ embedded: true }); }, 0);
  }
})();
