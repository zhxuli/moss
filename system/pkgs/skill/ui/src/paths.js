/* paths.js —— 把文本里的**文件 / 文件夹路径**变成可点开的超链接（`V-301`）
   ============================================================================
   你说："面板里有可能会出现的文件路径数据，写一个 js 把所有的文件路径和文件夹路径变成
   可以点击打开的超链接，通过外部资源管理器打开。"

   做法：
     · `SKILL_PATHS.linkify(text)` → 返回一段 HTML：路径被包成 `<a class="plink" data-p="…">`；
       其余文字照旧转义（防注入）。
     · 一个**委托**的点击监听挂在 `document` 上：点到 `.plink` 就调后端 `open_path`
       （目录直接开、文件开所在目录并选中）—— 这样任何面板只要 `v-html="linkify(x)"` 就有用。

   认哪些：盘符路径（`D:\a\b` / `D:/a/b`）、UNC（`\\server\share\…`）、以及 `user_data/…`
   / `system/…` 这种相对路径。**不认带空格的整条**（那样会把半句话也吞进去）—— 路径里真有
   空格时，退成"只认出到空格前那段"，够点开上级目录。
   ========================================================================== */
(function () {
  'use strict';

  var PAT = /(?:[A-Za-z]:[\\/]|\\\\|user_data[\\/]|system[\\/])[^\s"'<>|?*]+/g;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function linkify(text) {
    text = String(text == null ? '' : text);
    var out = '', last = 0, m;
    PAT.lastIndex = 0;
    while ((m = PAT.exec(text)) !== null) {
      /* 尾部的标点（句号 / 逗号 / 括号…）不算路径的一部分 */
      var p = m[0].replace(/[.,;:)\]}]+$/, '');
      if (!p) continue;
      out += esc(text.slice(last, m.index));
      out += '<a class="plink" href="javascript:void(0)" data-p="' +
             encodeURIComponent(p) + '" title="在资源管理器里打开：' + esc(p) + '">' +
             esc(p) + '</a>';
      last = m.index + p.length;
    }
    out += esc(text.slice(last));
    return out;
  }

  /* 全局委托：任何面板里点了 `.plink` 都在资源管理器里打开（不跳页） */
  document.addEventListener('click', function (ev) {
    var a = ev.target && ev.target.closest && ev.target.closest('.plink');
    if (!a) return;
    ev.preventDefault();
    var path = '';
    try { path = decodeURIComponent(a.getAttribute('data-p') || ''); } catch (e) { path = ''; }
    if (!path || !window.SKILL_API) return;
    window.SKILL_API.openPath(path).then(function (r) {
      if (r && r.ok === false && window.__skillToast) window.__skillToast(r.msg || '打不开', 'bad');
    }).catch(function () { /* 打不开就算了，别弹一堆错 */ });
  });

  window.SKILL_PATHS = { linkify: linkify };
})();
