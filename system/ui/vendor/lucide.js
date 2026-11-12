/* 图标：`ico(name, cls)` → 一段 `<svg>` 的 innerHTML。
 *
 * ★ `V-267`：**图标数据不在这份代码里了** —— 一个图标一个文件，放在
 *   `system/icon/svg/<名字>.svg`（260 条 path 从这份 .js 里搬走了，代码瘦下来）。
 *   运行期由宿主/预览读那些文件、注入成 `window.__MOSS_ICONS = {名字: {vb, body}}`
 *   （实现见 `system/ui/icons.py` 的 `script_tag()`）。
 *   用法没变：`ico('play')`，所有调用点一个字都不用改。
 *
 * ★ 文件里那段 `<g>` **自带画笔**（描边族的 fill/stroke、自绘那几颗的缩放与实心填充
 *   都已经烤进 .svg），所以这里不需要知道"实心还是描边"，只管套个 `<svg class=…>`。
 *
 * 补图标：从 lucide-static 取 SVG，放到 system/icon/svg/<名字>.svg。
 * 许可：Lucide（ISC）见 `vendor/lucide-LICENSE.txt`。
 */
function ico(name, cls) {
  const T = window.__MOSS_ICONS || {};
  const s = T[name] || T["file"] || {vb: "0 0 24 24", body: ""};
  return '<svg class="' + (cls || 'i') + '" viewBox="' + s.vb + '" aria-hidden="true">' +
         s.body + '</svg>';
}
