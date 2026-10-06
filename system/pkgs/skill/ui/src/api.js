/* api.js —— 后端桥的**唯一入口**（经典脚本，挂在 `window.SKILL_API` 上）
   ============================================================================
   ★ 界面层永远不直接碰 `window.pywebview` / `window.moss` —— 只有这一个文件碰。
     以后加功能、改后端方法名、加错误兜底，都只改这里。
   ★ 一份页面两种跑法（`V-222`）都从这儿出去（走 `moss-embed.js` 垫片）：
       · 内嵌在 moss 的「界面」选项卡里 → `moss.call()` → postMessage → 宿主 → 后端进程 stdin；
       · 独立窗口（pywebview）→ `moss.call()` → `window.pywebview.api.<方法>(params)`。
     两条路的参数形状一样（**一个对象**）。
   ★ 后端方法表就是 `system/pkgs/skill/core.py` 的 `Api`，一一对应，别自己加名字。
   ========================================================================== */
(function () {
  'use strict';

  var readyPromise = null;

  /* 垫片是经典脚本、排在前面，正常都已经在了；真不在就等 pywebview（独立窗口那条路）。
     谁都没来也别把界面卡死（3 秒后放行，让后面的调用自己去报错）。 */
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
        return window.moss.call(name, params || {});        // 垫片自己分流两种环境
      }
      var fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
      if (typeof fn !== 'function') throw new Error('后端没有这个方法：' + name);
      return fn(params || {});
    });
  }

  /* 复制到剪贴板：**三条路依次退**。
     ① 宿主有没有给 `sys_copy`（`exec` 那个包就是这么用的）—— 有就交给它，
        内嵌在 moss 里时这是最靠谱的一条；
     ② 浏览器自己的 `navigator.clipboard`；
     ③ 老办法（临时 textarea + `execCommand`）。
     谁都没成就**抛出**，让调用方去说一句人话，别默默失败。 */
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
    /* 后端是**一个对象参数**的规矩（`P-17`），所以这里每次都显式包一层 */
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
    reveal:   function (dir) { return call('reveal', { dir: dir || '' }); },
    copy:     copyText,
  };
})();
