/* paths.js —— 把文本里的**文件 / 文件夹路径**变成能点开的链接（`V-301` 建；`V-346` 重写）
   ============================================================================
   你说（`V-301`）："面板里有可能会出现的文件路径数据，写一个 js 把所有的文件路径和文件夹路径
   变成可以点击打开的超链接，通过外部资源管理器打开。"
   你说（`V-346`）："它这个解析 显然是有问题的 虽然能打开 但是这个连接的 url 确实是错了" +
   "我希望 可以打开文件夹 也可以直接打开这个文件 但是现在 它只有一个链接 显然没有支持这两种
   打开方法"。

   现在这一份给**两个动作**（默认都长在输出的同一个位置上）：
     · **路径本身**（`.plink`）= **直接打开** —— 文件交给默认程序打开，目录就打开它；
     · **紧跟的一颗小文件夹图标**（`.plink-dir`）= **打开所在文件夹** ——
       在资源管理器里打开它所在的目录、并把它选中（目录就是打开它上一级、选中它）。
   一个**委托**的点击监听挂在 `document` 上，按 `data-act` 调后端 `open_path` ——
   任何面板只要 `v-html="paths(x)"`，这两个动作就都有了。

   认哪些路径：盘符（`D:\a\b` / `D:/a/b`）、UNC（`\\server\share\…`）、
   以及 `user_data/…` / `system/…` 这种相对路径。

   ★★ `V-346` 修的那个真 bug：尾巴上为什么会蘸上一串垃圾
   --------------------------------------------------------------------------
   现场（`shot` 技能打的那句话）：

     整个屏幕 截下来了：D:\…\shot-20261008-114021.png（7680×2160，9125074 字节）

   老正则的"路径体"只排除**半角**空白和 `"'<>|?*`，**全角**的 `（` `，` 一个都不排 ⇒
   它一路吃到 `…114021.png（7680×2160，9125074` 才被那个半角空格拦住；而结尾那句
   "把标点剪掉"只认半角 `.,;:)`、末尾又正好是数字 ⇒ **一个字都没剪掉**。
   ⇒ `data-p` 是一段根本不存在的路径，点下去 `open_path` 找不到、退到**上级目录**
   —— 所以"看着能打开"，其实打开的是 `shots\` 那个文件夹，**链接本身就是错的**。

   ★ 但**不能一刀切在全角括号上停住**：`D:\项目\截图（1）.png` 是**完全合法**的文件名，
   名字里带全角括号很常见。所以分两步走：

     ① **先按"句子标点"切**（`，。；：！？、` 和全角空格 —— 这些几乎不可能出现在文件名里）；
     ② **再修括号**：切完之后若括号**配不成对**（残留一个孤零零的 `（`），就从那个括号处截断。

   上面那句切在 `，` ⇒ 残留 `（7680×2160` ⇒ 截到 `.png` ✓；
   而 `截图（1）.png` 括号是配对的 ⇒ 一个字不动 ✓。两种都保住了。

   ★ 后端还有**第二道保险**（`core.py::_open_target`）：真到了 `open_path`，整条路径若不存在，
   就**按标点从右往左往回退**、退到第一个真存在的为止 —— 判据是**文件系统本身**，
   比任何正则都可靠（前端这一层只是让**显示的链接和文字先对**）。

   ★ `href` 为什么给一个真 `file:///`（而不是原来的 `javascript:void(0)`）：
   你说"这个连接的 url 确实是错了" —— 那个 `javascript:void(0)` 确实是句假 url，
   右键"复制链接地址"拿到它没有任何意义。现在绝对路径给**真的 `file:///`**（能看、能复制、
   `title` 里也是真路径）；点击照样被那个委托监听 `preventDefault()` 接管走 `open_path`
   （监听和 `linkify` 是**同一段脚本**装的，页面上有 `.plink` 就一定有它，不会漏）。
   相对路径（`user_data/…`）拼不出正确的 `file://`，**干脆不给 `href`** ——
   拼一个假的比不给更误导；它只有 `data-p`，由后端按 moss 根解析。
   ========================================================================== */
(function () {
  'use strict';

  /* 路径体里**绝对不该有**的字符：
       半角空白 + 引号 + 重定向/通配符号（老规矩）
       + 全角"句子标点"（`，。；：！？、` + 全角空格 `　`）—— 这些几乎不可能出现在文件名里。
     ★ **全角括号故意不在里面**（`截图（1）.png` 合法），交给下面 `trimTail` 修。 */
  var PAT = /(?:[A-Za-z]:[\\/]|\\\\|user_data[\\/]|system[\\/])[^\s"'<>|?*，。；：！？、　]+/g;

  /* 尾巴上还剩下的**句子标点**（成对的括号由 `trimTail` 自己按配对处理，不在这儿剪） */
  var SENT_TAIL = /[.,;:!?，。；：！？、"'\u2018\u2019\u201c\u201d]+$/;

  /* 尾巴上那个括号组：是"说明文字"还是"文件名的一部分"？**唯一一条判据**：
     括号**前面已经是一个带扩展名的完整文件名**（`…\app.log（这个文件）`、`…\a.png（7680×2160）`）
     ⇒ 那是说明文字，剪掉。真文件名几乎不会把扩展名写在括号前面。
     反例全保住：`D:\项目\截图（1）.png`（括号后面还有 `.png`）、`D:\备份（副本）`（前面没扩展名）
     ⇒ 一个字不动。
     ★ 判错的代价很小：后端 `open_path` 会**拿没剪过的原样先试一次**（见 `core.py::_open_target`）——
       所以哪怕真有个文件就叫 `a.png（副本）`，点下去照样开的是它，只是链接文字短了一截。 */
  var EXT_TAIL = /\.[A-Za-z0-9]{1,5}$/;
  var PAIR = { ')': '(', '）': '（', ']': '[', '】': '【' };

  /* 尾巴上是一个**配对的**括号组、且它前面已经是带扩展名的完整名字 ⇒ 把这个组剪掉。
     循环调用是为了 `…\a.png（1）（2）` 这种连着好几个的情况。 */
  function cutTailGroup(s) {
    var open = PAIR[s.charAt(s.length - 1)];
    if (!open) return s;
    var i = s.lastIndexOf(open, s.length - 2);
    if (i <= 0) return s;
    var before = s.slice(0, i);
    return EXT_TAIL.test(before) ? before : s;
  }

  /* 打开所在文件夹那颗小图标（手画的细线 svg，跟 `icons.js` 一个风格；**不用图标字体**）。 */
  var ICON_DIR =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>' +
    '</svg>';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* 尾巴修剪（`V-346`，理由全在文件头）。三步，顺序不能换：
       ① **按配对处理括号**：从右往左销 —— 撞上"孤零零的开括号"（说明文字的开头）
          就从那儿截断；剩下几个没销掉的收括号（半角 `)` 那种）就剪掉几个；
       ② **尾巴上那个括号组**：它前面已经是一个带扩展名的完整名字 ⇒ 是说明文字，剪掉；
       ③ 最后剪一遍剩下的句子标点。 */
  function trimTail(raw) {
    var s = String(raw);
    var depth = 0, cut = -1, i, c;
    for (i = s.length - 1; i >= 0; i--) {
      c = s.charAt(i);
      if (c === ')' || c === '）' || c === ']' || c === '】') depth++;
      else if (c === '(' || c === '（' || c === '[' || c === '【') {
        if (depth > 0) depth--;
        else { cut = i; break; }
      }
    }
    if (cut >= 0) s = s.slice(0, cut);
    else if (depth > 0) s = s.slice(0, s.length - depth);
    for (i = 0; i < 4; i++) {                           // `（1）（2）` 连着几个也剪得掉
      c = cutTailGroup(s);
      if (c === s) break;
      s = c;
    }
    return s.replace(SENT_TAIL, '');
  }

  /* 绝对路径 → `file:///…`（给 `href` 用：能看、能复制）。相对路径（`user_data/…`）回空串。 */
  function toFileUrl(p) {
    var s = String(p).replace(/\\/g, '/');
    var unc = s.slice(0, 2) === '//';
    if (!unc && !/^[A-Za-z]:\//.test(s)) return '';
    var body = s.split('/').map(function (x) {
      return encodeURIComponent(x).replace(/%3A/gi, ':');        // 盘符那个冒号别编码
    }).join('/');
    return unc ? 'file:' + body : 'file:///' + body;
  }

  function linkify(text) {
    text = String(text == null ? '' : text);
    var out = '', last = 0, m;
    PAT.lastIndex = 0;
    while ((m = PAT.exec(text)) !== null) {
      var p = trimTail(m[0]);
      if (!p) continue;
      var enc = encodeURIComponent(p);
      var url = toFileUrl(p);
      /* `data-r` = **没修剪过的原样**：后端先拿它试一次 —— 文件名里真带全角括号
         （`报告（旧）.txt`）时这一道能把被前端剪掉的那截救回来（见 `core.py::_open_target`）。
         两个动作都带上它（开文件夹那条也一样，退路是同一套）。 */
      var dat = ' data-p="' + enc + '" data-r="' + encodeURIComponent(m[0]) + '"';
      out += esc(text.slice(last, m.index));
      out += '<a class="plink" role="link" tabindex="0"' + dat + ' data-act="open"' +
             (url ? ' href="' + esc(url) + '"' : '') +
             ' title="直接打开：' + esc(p) + '">' + esc(p) + '</a>';
      out += '<button type="button" class="plink-dir"' + dat + ' data-act="reveal"' +
             ' title="在资源管理器里打开它所在的文件夹：' + esc(p) + '"' +
             ' aria-label="打开所在文件夹">' + ICON_DIR + '</button>';
      last = m.index + p.length;
    }
    out += esc(text.slice(last));
    return out;
  }

  /* 点开：`data-act` 决定怎么开（`open` = 直接打开 / `reveal` = 开所在文件夹）。
     ★ `preventDefault()` 一律先做 —— 那个 `file:///` 的 `href` 只是给"复制链接"看的，
       真动作走后端（不然在 webview 里会把整个界面导航跑掉）。 */
  function fire(el) {
    var p = '', r = '';
    try { p = decodeURIComponent(el.getAttribute('data-p') || ''); } catch (e) { p = ''; }
    try { r = decodeURIComponent(el.getAttribute('data-r') || ''); } catch (e) { r = ''; }
    if (!p || !window.SKILL_API) return;
    var how = el.getAttribute('data-act') === 'reveal' ? 'reveal' : 'open';
    window.SKILL_API.openPath(p, how, r).then(function (res) {
      if (res && res.ok === false && window.__skillToast) window.__skillToast(res.msg || '打不开', 'bad');
    }).catch(function () { /* 打不开就算了，别弹一堆错 */ });
  }

  /* 全局委托：任何面板里点到这两个都在这儿收口（不跳页） */
  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest && ev.target.closest('.plink, .plink-dir');
    if (!el) return;
    ev.preventDefault();
    fire(el);
  });

  /* 键盘也能用（相对路径那条没有 `href`、本来不可聚焦，给它 `tabindex` 之后回车得能用） */
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var el = ev.target && ev.target.closest && ev.target.closest('a.plink');
    if (!el) return;
    ev.preventDefault();
    fire(el);
  });

  window.SKILL_PATHS = { linkify: linkify };
})();
