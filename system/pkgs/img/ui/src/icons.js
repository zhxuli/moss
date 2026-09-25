/* 界面用的小图标 —— 统一 24×24 网格、1.5 描边、圆头圆角。
 *
 * 为什么不再用 ▾ ⟳ ▸ ✓ 这些文字符号：它们在不同字体里字重、基线、留白都不一样，
 * 渲染出来粗细对不齐，看着就不像正经图标（用户指出下拉箭头"好丑"）。
 * 内联 SVG 用的是同一套几何，颜色跟随 currentColor，主题切换自动跟着变。
 */

const PATHS = {
  /* 下拉 / 展开 */
  chevronDown: '<path d="M7 10l5 5 5-5"/>',
  chevronRight: '<path d="M10 7l5 5-5 5"/>',
  /* 刷新：两个半圆弧 + 两个箭头 */
  refresh: '<path d="M20 12a8 8 0 0 1-13.7 5.6"/><path d="M4 12a8 8 0 0 1 13.7-5.6"/>'
         + '<path d="M17.7 3.2v3.6h-3.6"/><path d="M6.3 20.8v-3.6h3.6"/>',
  check: '<path d="M5 12.8l4.2 4.2L19 7.4"/>',
  close: '<path d="M7 7l10 10"/><path d="M17 7L7 17"/>',
  plus: '<path d="M12 5.5v13"/><path d="M5.5 12h13"/>',
  /* 空状态用 */
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>'
       + '<circle cx="9" cy="10" r="1.6"/><path d="M4.5 17l4.6-4.3 3.4 3.2 2.6-2.3 4.4 4"/>',
  folder: '<path d="M3.5 7.2a2 2 0 0 1 2-2h3.3l1.9 2.1h7.8a2 2 0 0 1 2 2v6.5'
        + 'a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6.5 3.5h6.6l4.9 4.9v11.1a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V4.5'
      + 'a1 1 0 0 1 1-1z"/><path d="M13 3.5v5h5"/>',
  filePlus: '<path d="M6.5 3.5h6.6l4.9 4.9v11.1a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V4.5'
          + 'a1 1 0 0 1 1-1z"/><path d="M13 3.5v5h5"/>'
          + '<path d="M8.6 15h5.8"/><path d="M11.5 12.1v5.8"/>',
  trash: '<path d="M4.2 6.6h15.6"/>'
       + '<path d="M9.4 6.6V4.9a1.3 1.3 0 0 1 1.3-1.3h2.6a1.3 1.3 0 0 1 1.3 1.3v1.7"/>'
       + '<path d="M6.6 6.6 7.5 19.9a1 1 0 0 0 1 .9h7a1 1 0 0 0 1-.9l.9-13.3"/>'
       + '<path d="M10.3 10.4v6.6"/><path d="M13.7 10.4v6.6"/>',
  undo: '<path d="M4.6 9.6h9.6a5 5 0 0 1 0 10H8.4"/>'
      + '<path d="M8.2 5.6 4.2 9.6l4 4"/>',
  play: '<path d="M8 5.4v13.2l10.4-6.6z"/>',
  checkSquare: '<rect x="3.8" y="3.8" width="16.4" height="16.4" rx="3.4"/>'
             + '<path d="M8.4 12.3l2.7 2.7 4.9-5.4"/>',
  xSquare: '<rect x="3.8" y="3.8" width="16.4" height="16.4" rx="3.4"/>'
         + '<path d="M9.2 9.2l5.6 5.6"/><path d="M14.8 9.2l-5.6 5.6"/>',
  alert: '<path d="M12 4.4 2.8 19.6h18.4z"/><path d="M12 10v4.2"/>'
       + '<path d="M12 17h.01"/>',
  checkCircle: '<circle cx="12" cy="12" r="8.6"/><path d="M8.2 12.3l2.7 2.7 4.9-5.4"/>',
  xCircle: '<circle cx="12" cy="12" r="8.6"/>'
         + '<path d="M9.3 9.3l5.4 5.4"/><path d="M14.7 9.3l-5.4 5.4"/>',
  help: '<circle cx="12" cy="12" r="8.6"/>'
      + '<path d="M9.7 9.5a2.5 2.5 0 0 1 4.9.5c0 1.7-2.4 2.1-2.4 3.7"/>'
      + '<path d="M12 17h.01"/>',
};

export function svg(name, cls) {
  return '<svg' + (cls ? ' class="' + cls + '"' : '')
       + ' viewBox="0 0 24 24" fill="none" stroke="currentColor"'
       + ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
       + (PATHS[name] || '') + '</svg>';
}

/* 把页面上所有 <span data-icon="名字"> 换成真图标。
   放一个探针属性就行，不用到处写一大坨 SVG。 */
export function mountIcons(root) {
  (root || document).querySelectorAll('[data-icon]').forEach((node) => {
    const name = node.dataset.icon;
    if (!name || node.dataset.iconDone === name) return;
    node.innerHTML = svg(name);
    node.dataset.iconDone = name;
  });
}
