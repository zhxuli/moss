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
