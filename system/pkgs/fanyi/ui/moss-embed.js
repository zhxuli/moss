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

   ★★ `ready` 是**粘的**（`V-287`，这一条踩过，会让人看见"永远正在读"）：
     这一枪**打得很早** —— 内嵌时就在本文件这一句上（`setTimeout(0)`，那一刻解析器正等着取
     `app.js`，取的时候事件循环是转着的，所以它**先跑掉了**）；独立窗口时挂在 `pywebviewready`
     上，而那个事件**只发一次**。而订阅它的 `app.js` 往往**晚一步**才执行 ⇒ 早打的那一枪没人接、
     页面就永远停在"正在读……"（后端和桥其实一直是好的，手点一下「重试」就马上好）。
     所以：`ready` 一发就记下来（`moss.ready`），**晚订阅的人补一枪**。别的（time / drop /
     visible …）都是会重复发生的事，照旧不粘。

   ★ 还顺手把 `window.pywebview.api` 也垫出来了 —— 老包（img / exec 那种）直接写
     `window.pywebview.api.xxx()` 的，被内嵌时**一行都不用改**。
   ============================================================================ */
(function () {
  'use strict';

  const EMBEDDED = window.parent && window.parent !== window;
  const handlers = {};          // 事件名 -> [fn]
  const waiting = {};           // 请求 id -> {resolve, reject}
  let seq = 0;
  let readyFired = false;       // `ready` 打过没有
  let readyInfo = null;         // 打过的那个 payload（晚订阅的人照着补）

  function fire(name, data) {
    (handlers[name] || []).forEach(function (fn) {
      try { fn(data); } catch (e) { console.error('[moss] 事件处理出错', name, e); }
    });
  }

  /* `ready` 只许打一次，而且打过就记住（★ 粘的，见文件顶上那段） */
  function markReady(info) {
    if (readyFired) return;
    readyFired = true;
    readyInfo = info || { embedded: EMBEDDED };
    moss.ready = true;
    fire('ready', readyInfo);
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
    ready: false,               // ★ 页面就绪了没有（晚订阅 / 不订阅的人读这个）
    on: function (name, fn) {
      (handlers[name] = handlers[name] || []).push(fn);
      /* ★ `ready` 已经打过了 ⇒ **补一枪**（异步补，跟真事件一个节奏）。
         没有这一句，"订阅晚了"就是"永远收不到" —— 页面永远停在"正在读"。 */
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

  /* 拖放进来了 → **告诉宿主**（`V-204`）。
     ★ 为什么要多这一步：拖动时鼠标如果压在这一帧上，浏览器的 `dragover`/`drop` 全给了
       **这一帧**（跨文档事件不冒泡到父页面）—— 而"真实路径"只有父页面那侧（pywebview 从
       WebView2 里取）才拿得到。结果是：界面型包的 iframe 盖住右栏时，往里拖什么都会**丢**。
       这里只做一件事：把"有东西拖到我头上了 / 走了"报给宿主，宿主在自己上面铺一张罩子
       把拖放接过去，路径就回到 Python 那侧了。 */
  if (EMBEDDED) {
    let over = false;
    let captured = false;      // 宿主铺了罩子接住（`V-205`）：这期间别再报"走了"
    function tellDrag(phase) {
      if (phase === 'over' && over) return;        // 只报"进入"，别在 dragover 里刷屏
      if (phase === 'out' && (!over || captured)) return;   // 罩子盖上引起的 leave 不算
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
    // ★ 宿主说"我接住了"（`V-205`）：罩子一盖上来，这一帧就会收到一次 `dragleave`
    //   （鼠标底下的元素被换掉了）—— 要是照着报 `out`，宿主会收罩子、这一帧又收到
    //   `dragenter` 再报 `over` ⇒ **来回抖**。所以接住之后到 `dragend` 之前一律不报离开。
    moss.on('captured', function () { captured = true; });
    moss.on('dragend', function () { captured = false; over = false; });
  }

  /* 独立窗口里，后端要发事件就调 window.moss.__emit(...) —— 在这边把 pywebview 的
     就绪事件也转成统一的 ready，让界面只写一次初始化。 */
  window.addEventListener('pywebviewready', function () {
    if (!EMBEDDED) markReady({ embedded: false });
  }, { once: true });

  if (EMBEDDED) {
    // 内嵌：告诉宿主"我这边准备好了"（宿主会把它当成"可以开始派活了"）
    window.parent.postMessage({ moss: 1, kind: 'ready' }, '*');
    // ★ 这一枪**早得离谱**（此刻解析器正等着取 app.js）—— 所以 `markReady` 要记住它，
    //   晚一步订阅的 `app.js` 才收得到（`V-287`）。
    setTimeout(function () { markReady({ embedded: true }); }, 0);
  }
})();
