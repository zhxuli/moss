/* ★ 出错要看得见（`V-76`）：这个界面没有能随手打开的控制台，某处一抛异常，表现就是
   "左边空了 / 某块没了"，谁也看不出为什么。所以 onerror / unhandledrejection 全部收下来，
   写到右下角状态栏（红字，一直在）+ toast + 日志文件（`user_data/state/_ui_drop.log`）。
   （外一层的"资源加载失败"捕获在 `index.html` 里内联着 —— 那一层要防的是 js 自己都没加载上。） */
/* ★ 出错要看得见（`V-76` / `V-81`）：这个界面没有能随手打开的控制台，
   某处一抛异常，表现就是“左边空了 / 某块没了”，谁也看不出为什么。
   ★ 唯一“一定跑得到”的那份在 `index.html` 里**内联**着（资源加载失败 + 页内报错
   → 状态栏红字 + `user_data/state/_ui_drop.log`）—— 因为 `js/*.js` 自己没加载上时，
   写在 js 里的报错处理根本跑不到（鸡生蛋）。所以这里**不再重复挂** window 上的
   `error` / `unhandledrejection`（以前重复挂了三份，一个错误会被报三四次），只补一件它管不到的事：
   **Vue 组件里的异常** —— Vue 默认只把它写进控制台，而这个界面没有控制台。
   （`V-81` 就是这么摸出来的：详情页接线里一个变量名写错 ⇒ 后面那串按钮全没绑上，
   界面上却一个字都不报。） */
window.__errors = window.__errors || [];

function reportError(what, msg, stack){
  const line = what + "：" + msg + (stack ? ("\n" + stack) : "");
  try{ console.error(line); }catch(e){}
  if (typeof window.__mossTell === "function"){
    try{ window.__mossTell(line); }catch(e){}     // 状态栏红字 + 日志文件，都由它写
  }else{
    try{ window.__errors.push(line); }catch(e){}
  }
  try{ if (typeof toast === "function") toast("⚠ " + msg, true); }catch(e){}
}

/* ★ 光靠上面那条 `__mossTell` 还管不到 **Vue 组件里的异常**：Vue 默认把它只写进控制台，
   而这个界面没有能随手打开的控制台 ⇒ 必须挂 errorHandler。
   ⚠️ 实测（`V-81`）：`vue.global.prod.js`（3.5.43）里**没有 `Vue.config`**
   （`typeof Vue.config === "undefined"`），所以 Vue 2 那种"设全局 config"的写法在这儿
   **一声不响地失效** —— 我第一版就是这么写的，结果你从 devtools 里看到的那条报错
   （`Proxy.rows` 读 `DATA.packages`），界面上一个字都没留下，我还差点当它是旧页面残留。
   只能**按 app 设**：`app.config.errorHandler`。 */
function onVueError(err, vm, info){
  reportError("组件出错" + (info ? ("（" + info + "）") : ""),
              (err && err.message) || String(err), (err && err.stack) || "");
}

/* 建 Vue app 一律走这个 —— 省得哪一处忘了挂 errorHandler（忘了就又是"静悄悄死掉"）。
   返回值与 `Vue.createApp(x).mount(y)` 一样（根组件实例），调用点别的都不用改。
   `globals`：往 `app.config.globalProperties` 上摊一份（文件管理那套模板助手要用）。
   自测这条路的场景：预览里的 `err-path`（用**这个函数**建一个会在 computed 里抛错的组件）。 */
function mountVue(comp, target, globals){
  const app = Vue.createApp(comp);
  app.config.errorHandler = onVueError;
  if (globals) Object.assign(app.config.globalProperties, globals);
  return app.mount(target);
}

/* moss 界面 · core.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */

/* ============================================================================
   moss 界面：详情 / 命令行 / **文件管理**
   文件管理是**每个包自己的一套**（上下文按包 id 分），里面的子选项卡：
       「文件」固定不可关（目录浏览，资源管理器那套操作）
       + 每打开一个文件一个子选项卡（可关、带未保存黄点）
   高亮与编辑器结构照抄 exec；图标用 Lucide。
   ========================================================================== */

let DATA = null, cur = null, tab = "detail";
/* ★ 右边那三个选项卡的"当前对象"有两种：**包**（`cur`）和**一条历史**（`curH`）。
   两者互斥 —— 选了一个就把另一个清掉，左边的高亮跟着走。
   为什么不合成一个对象：包有一堆历史没有的字段（版本/层/参数表/AI 开关/卸载），
   历史有的是包没有的（目标绝对路径 / 当初的 cwd / 那次的结果）；
   合成一个就得到处判空，不如分成两份、用一个 `selObj()` 取"现在是谁"。 */
let curH = null;
function isHist(o){ return !!o && !o.id && !!o.target; }   // 包有 id，历史有 target
function selObj(){ return curH || cur; }
let lastRun = null;
/* 上一次输入框里写的参数，**按包各记一份**。
   ★ 为什么要记：详情页在"一次运行结束"时会重画（`finishRun` → `renderDetail`），
     重画会把输入框整个换掉 —— 于是你刚填的参数（或者刚拖进来的那个路径）
     在跑完的一瞬间就消失了，看着像没生效。记一份、重画时放回去。 */
const ARGS = {};
/* 包 id 的规矩（宿主 `core/paths.py` 的 `ID_RE`，`F-26`）：它是身份，还要当目录名用
   （`state/<id>`），所以只允许小写字母开头 + 小写字母/数字/下划线/连字符，最长 32。
   界面这边也存一份：保存清单时能**当场**说清楚哪儿不合法，不用等宿主把包丢掉。 */
const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;
/* 上一次弹过的"包表没读回来"的原因 —— 同一个原因只弹一次，别每 5 秒刷一次屏。 */
let lastStaleReason = "";
const $ = s => document.querySelector(s);

/* ---------------------------------------------------------------- 后缀 → 图标/颜色/语言 */
const EXT = {
  py:{i:"file-code",c:"#3572A5",l:"python"}, pyw:{i:"file-code",c:"#3572A5",l:"python"},
  js:{i:"file-code",c:"#c9a227",l:"javascript"}, mjs:{i:"file-code",c:"#c9a227",l:"javascript"},
  ts:{i:"file-code",c:"#2b7489",l:"typescript"}, go:{i:"file-code",c:"#00ADD8",l:"go"},
  rs:{i:"file-code",c:"#dea584",l:"rust"}, c:{i:"file-code",c:"#7a7a7a",l:"c"},
  h:{i:"file-code",c:"#7a7a7a",l:"c"}, cpp:{i:"file-code",c:"#f34b7d",l:"cpp"},
  java:{i:"file-code",c:"#b07219",l:"java"}, cs:{i:"file-code",c:"#178600",l:"csharp"},
  php:{i:"file-code",c:"#7a86b8",l:"php"}, rb:{i:"file-code",c:"#cc342d",l:"ruby"},
  lua:{i:"file-code",c:"#000080",l:"lua"}, sql:{i:"database",c:"#e38c00",l:"sql"},
  html:{i:"globe",c:"#e34c26",l:"xml"}, htm:{i:"globe",c:"#e34c26",l:"xml"},
  xml:{i:"code",c:"#8a8a8a",l:"xml"}, svg:{i:"palette",c:"#ffb13b",l:"xml"},
  css:{i:"palette",c:"#563d7c",l:"css"}, scss:{i:"palette",c:"#c6538c",l:"scss"},
  less:{i:"palette",c:"#1d365d",l:"less"},
  json:{i:"braces",c:"#c9a227",l:"json"}, jsonc:{i:"braces",c:"#c9a227",l:"json"},
  md:{i:"book-open",c:"#6e7781",l:"markdown"}, markdown:{i:"book-open",c:"#6e7781",l:"markdown"},
  txt:{i:"file-text",c:"#6e7781",l:"plaintext"}, log:{i:"file-text",c:"#6e7781",l:"plaintext"},
  bat:{i:"terminal",c:"#8a8a8a",l:"dos"}, cmd:{i:"terminal",c:"#8a8a8a",l:"dos"},
  ps1:{i:"terminal",c:"#2f6fb5",l:"powershell"}, psm1:{i:"terminal",c:"#2f6fb5",l:"powershell"},
  sh:{i:"terminal",c:"#4f9d3a",l:"bash"}, bash:{i:"terminal",c:"#4f9d3a",l:"bash"},
  toml:{i:"settings",c:"#9c4221",l:"ini"}, ini:{i:"settings",c:"#9c4221",l:"ini"},
  cfg:{i:"settings",c:"#9c4221",l:"ini"}, conf:{i:"settings",c:"#9c4221",l:"ini"},
  yml:{i:"settings",c:"#cb171e",l:"yaml"}, yaml:{i:"settings",c:"#cb171e",l:"yaml"},
  png:{i:"file-image",c:"#a074c4"}, jpg:{i:"file-image",c:"#a074c4"},
  jpeg:{i:"file-image",c:"#a074c4"}, gif:{i:"file-image",c:"#a074c4"},
  webp:{i:"file-image",c:"#a074c4"}, bmp:{i:"file-image",c:"#a074c4"},
  ico:{i:"file-image",c:"#a074c4"},
  exe:{i:"binary",c:"#8a8a8a"}, dll:{i:"binary",c:"#8a8a8a"}, pyd:{i:"binary",c:"#8a8a8a"},
  zip:{i:"file-archive",c:"#e0a800"}, "7z":{i:"file-archive",c:"#e0a800"},
  rar:{i:"file-archive",c:"#e0a800"}, gz:{i:"file-archive",c:"#e0a800"},
  mp3:{i:"file-audio",c:"#1f9d55"}, wav:{i:"file-audio",c:"#1f9d55"},
  mp4:{i:"file-video",c:"#d64545"}, mkv:{i:"file-video",c:"#d64545"},
  csv:{i:"file-spreadsheet",c:"#1f9d55"}, xlsx:{i:"file-spreadsheet",c:"#1f9d55"},
  key:{i:"file-key",c:"#c9a227"}, pem:{i:"file-key",c:"#c9a227"},
  license:{i:"copyright",c:"#6e7781"},
};
const NO_EXT = {
  LICENSE:{i:"copyright",c:"#6e7781",l:"plaintext"},
  "pkg.json":{i:"braces",c:"#c9a227",l:"json"},
  ".gitignore":{i:"file-cog",c:"#8a8a8a",l:"plaintext"},
  ".gitattributes":{i:"file-cog",c:"#8a8a8a",l:"plaintext"},
};
function extOf(entry){
  const name = (entry.name || "").toLowerCase();
  if (NO_EXT[name]) return Object.assign({ext:""}, NO_EXT[name]);
  return Object.assign({ext: entry.ext || ""}, EXT[entry.ext] || {i:"file", c:"#8a8a8a"});
}
function fileIconHTML(entry, open){
  if (entry.dir) return '<span style="color:#e0a800;display:flex">' +
    ico(open ? "folder-open" : "folder", "i") + '</span>';
  const e = extOf(entry);
  return '<span style="color:' + e.c + ';display:flex">' + ico(e.i, "i") + '</span>';
}
function typeLabel(entry){
  if (entry.dir) return "文件夹";
  const e = entry.ext || "";
  return e ? (e.toUpperCase() + " 文件") : "文件";
}
function humanSize(n){
  if (n == null) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}
function fmtTime(sec){
  if (!sec) return "";
  const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0");
  return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " +
         p(d.getHours()) + ":" + p(d.getMinutes());
}
function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/[&<>"]/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
}
const esc = escapeHtml;
