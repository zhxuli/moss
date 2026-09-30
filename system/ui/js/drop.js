/* moss 界面 · drop.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 拖文件进来（`V-35` ✅ / `V-38` ✅ / `V-39` ✅）
   一句话：**拖着文件或文件夹进窗口 ⇒ 只显示"收得下它"的包；划过谁就选中谁；到详情页的
   投放框上松手，按那个包自己声明的规矩跑起来。**

   ★ 路径**不是页面拿到的**：Chromium 不给页面 `File.path`（安全），页面只看得到文件名。
     真实路径由宿主（`system/ui/main.py` 的 `_on_files_dropped`）从 WebView2 的
     `AdditionalObjects` 里取出来，再调下面这个 `window.__mossDrop(items)` 交给我们。
     **拖动时**页面只知道"拖的是文件还是文件夹"（够用来筛列表）；**松手后**才知道真实路径。
   ★ 一个包"收什么、收到哪儿"全看它 `pkg.json` 里的 `drop` 声明（`V-38`）：
        "drop": { "dir": {"cwd": true}, "file": {"param": true, "quote": true, "base": false} }
     - `cwd`   = 把拖进来的**文件夹**当工作目录（拖的是文件 → 用文件所在的那个文件夹）
     - `param` = 把路径**追加到参数串末尾**（强制末尾，你定的）
     - `quote` = 加双引号（路径里有空白时无论如何都会加，不然宿主按空格拆词就拆坏了）
     - `base`  = 只给文件名，不给完整路径（配合 `cwd` 用）
     **没写 `drop` 的包 = 完全不收拖入**（比如快捷翻译）—— 拖动时它连列表都不出现。 */
const DRAG = {on: false, kind: null, depth: 0, cmd: 0, hits: 0};
/* 上一次**拖进来**塞进参数框的那一段（"包 id + 那一段原文"）。
   为什么要记：拖进来的那一段是追加在末尾的，连着拖两次就会叠成一串 —— 实测叠起来之后
   md5 收到两条路径，于是判成字符串、算了个错的 MD5。下一次拖入时先把这一段摘掉。 */
const DROP_ARGS = {id: null, piece: ""};

/* 拖进来的到底是文件还是文件夹：Chromium 的 `webkitGetAsEntry()` 在拖动过程中就能看。
   认不出来（有些来源不给）→ null = "不知道"，那就按"两种都收的包"筛，别把人挡住。 */
function dragKind(e){
  try{
    const items = e.dataTransfer && e.dataTransfer.items;
    if (items && items.length && items[0].webkitGetAsEntry){
      const en = items[0].webkitGetAsEntry();
      if (en) return en.isDirectory ? "dir" : "file";
    }
  }catch(err){}
  return null;
}
function dragHasFiles(e){
  return !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf("Files") >= 0);
}
function dropAccepts(p, kind){
  if (!p || !p.drop || !p.drop.length) return false;
  if (kind === "dir") return p.drop.some(c => c.dir);
  if (kind === "file") return p.drop.some(c => c.file);
  return true;                                  // 不知道拖的是什么 → 两种都算
}
/* 这个包对"拖进来的是文件/文件夹"能做什么。以后一个包可以有多条命令（多个投放框）。 */
function dropCommandsFor(p, isDir){
  const k = isDir ? "dir" : "file";
  return ((p && p.drop) || []).filter(c => c[k]).map(c => ({label: c.label || "运行", rule: c[k]}));
}
function dropKindName(kind){ return kind === "dir" ? "文件夹" : (kind === "file" ? "文件" : "文件/文件夹"); }

/* ---- 拖动的开始 / 结束 ---- */
function dragBegin(e){
  if (DRAG.on) return;
  DRAG.on = true;
  DRAG.kind = dragKind(e);
  DRAG.hits = 0;
  DRAG.cmd = 0;
  document.body.classList.add("dragging");
  uiLog("drag begin kind=" + (DRAG.kind || "unknown") +
        " accepts=" + DATA.packages.filter(p => dropAccepts(p, DRAG.kind)).length);
  renderList();                                 // ★ 只列收得下它的包
  paintDragBar();
  // 当前这个包要是就收得下，投放框**立刻**出现（不用等你先划到别处再划回来）
  paintDropZone(false);
}
function dragEnd(){
  if (!DRAG.on){ paintDropZone(false); return; }
  DRAG.on = false; DRAG.kind = null; DRAG.depth = 0; DRAG.cmd = 0;
  document.body.classList.remove("dragging");
  renderList();
  paintDragBar();
  paintDropZone(false);
}
/* 左上角那条提示：拖动中只显示收得下它的包 —— 免得你对着一个不收的包干瞪眼 */
/* ★ `V-85` 起这两块（`#dragbar` 提示 + `#dropzone` 投放框）的内容由 **Vue 组件**画：
   状态还是这份 `DRAG`，只是"变了就喊一声"（`DRAGR.rev`），外面照旧调这两个同名门面。
   ★ 为什么 `#dragbar` 的显隐还留在这儿一行命令式：`hidden` 是**这个元素自己的**属性，
     组件是挂在他**里面**的（管不到外面那个壳）。 */
const DRAGR = Vue.reactive({rev: 0, kind: null});

function paintDragBar(){
  const bar = $("#dragbar");
  if (bar) bar.hidden = !DRAG.on;
  DRAGR.rev++;
}

/* ---- 投放框（`V-39`）：只在"当前这个包收得下"的时候出现 ---- */
function paintDropZone(over, isDir, kind){
  const p = cur;
  const k = (kind !== undefined && kind !== null) ? kind : (isDir ? "dir" : DRAG.kind);
  DRAGR.kind = k;
  const cmds = DRAG.on && p ? dropCommandsFor(p, k === "dir") : [];
  const want = !!(DRAG.on && cmds.length);
  DRAGR.rev++;                                  // 框里的内容（`.dz-box` 那几个）由组件画
  // ★ 下面这几处 class 挂在**别的元素**上（`#dropzone` 自己 / 详情页 / 右上角那颗「运行」）——
  //   它们不是组件的根，维持命令式，和改造前逐行一致。
  const zone = $("#dropzone"), pane = $("#pane-detail"), btn = $("#btn-run");
  if (zone){
    zone.classList.toggle("on", want);
    zone.classList.toggle("over", !!(want && over));
  }
  if (pane) pane.classList.toggle("hot", want);
  if (btn) btn.classList.toggle("hot", want);       // 右上角那个「运行」跟着亮
}
function dropZoneWhy(p, rule, kind){
  const what = rule.cwd && rule.param ? "当工作目录，并把这个路径追加到参数末尾"
             : (rule.cwd ? "当工作目录" : "追加到参数末尾");
  const which = kind === "dir" ? "这个文件夹" : (kind === "file" ? "这个文件" : "它");
  return ":" + p.id + " —— 把" + which + what +
         (rule.base ? "（只给文件名）" : "") + (rule.quote ? "（加引号）" : "");
}

/* 拖拽那两块的组件（`V-85`）—— 一个画左边那条提示，一个画详情页上的投放框。
   两块共用一份举牌信号：它们的数据都来自 `DRAG` / `cur`（普通变量，不是响应式的）。 */
const MossDragBar = {
  name: "moss-dragbar",
  data(){ return { R: DRAGR }; },
  computed: {
    html(){
      this.R.rev;
      if (!DRAG.on) return "";
      const n = DATA ? DATA.packages.filter(p => dropAccepts(p, DRAG.kind)).length : 0;
      return ico("copy", "i") +
        '<span>拖进来的是<b>' + dropKindName(DRAG.kind) + '</b>：只列出收得下它的 <b>' + n +
        '</b> 个包' + (n ? " —— 划过哪个就选哪个" : "（一个都没有）") + '</span>';
    },
  },
  // `display:contents`：这层壳不参与布局（`#dragbar` 是 flex，多一层会改变量）
  template: '<div style="display:contents" v-html="html"></div>',
};

const MossDropZone = {
  name: "moss-dropzone",
  data(){ return { R: DRAGR }; },
  computed: {
    cmd(){ this.R.rev; return +DRAG.cmd || 0; },
    boxes(){
      this.R.rev;
      const p = cur, k = this.R.kind;
      const cmds = (DRAG.on && p) ? dropCommandsFor(p, k === "dir") : [];
      return cmds.map(c => ({label: c.label, why: dropZoneWhy(p, c.rule, k)}));
    },
  },
  template: `
    <div v-for="(c, i) in boxes" :key="i" class="dz-box" :class="{on: i === cmd}" :data-cmd="i">
      <div class="dz-big">松手 = {{ c.label }}</div>
      <div class="dz-sub">{{ c.why }}</div>
    </div>`,
};

/* ---- 页面这一侧的拖动事件（真实路径不在这里，见文件头的说明）---- */
function bindDropZone(){
  const pane = $("#pane-detail");
  if (!pane) return;
  document.addEventListener("dragenter", e => {
    if (!dragHasFiles(e)) return;
    DRAG.depth++;
    if (!DRAG.on) dragBegin(e);
    e.preventDefault();
  });
  // ★ 这一行是"在详情页松手却被浏览器打开文件"的解药（`V-42` ✅）：
  //   HTML 的规矩是 —— **只有 `dragover` 被 preventDefault，drop 事件才会发**；
  //   不 preventDefault 的话浏览器就执行它自己的默认动作（把那个文件/文件夹**打开**）。
  //   为什么以前只挂在具体元素上不够：投放框 `#dropzone` 是 `#pane-detail` 的**兄弟**
  //   （不是子节点），鼠标落在框上时，drag 事件根本不经过 `#pane-detail` —— 于是那条
  //   preventDefault 从来没执行过。挂在 `document` 上就没有这个死角（拖动一定会冒泡到它）。
  document.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });
  // 松手之后把界面收拾干净（不管落在哪儿）。真正的路径由宿主从另一条路送进
  // `window.__mossDrop`，这里只负责"别留着一堆高亮"。
  document.addEventListener("drop", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    uiLog("page drop: files=" + ((e.dataTransfer.files || []).length));
    setTimeout(() => { if (DRAG.on) dragEnd(); }, 1200);   // 给宿主那条路一点时间
  });
  // ★ 列表那一列：划过哪个包就选中它（省得你再回去点一下）。
  //   拖动过程中鼠标事件是不发的，只有 drag 事件 —— 所以用 dragover。
  const list = $("#list");
  if (list) list.addEventListener("dragover", e => {
    if (!DRAG.on) return;
    e.preventDefault();                 // 允许在列表上松手（松在这儿不跑，见 drop）
    const row = e.target && e.target.closest ? e.target.closest(".item") : null;
    if (!row) return;
    const id = row.dataset.id;
    if (id && (!cur || cur.id !== id)){
      select(id);                       // 自动激活（它的详情页会跟着出现投放框）
      paintDropZone(false);
    }
  });
  pane.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                 // 这一条是"好看"用的；真正管用的是 document 那条
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    const box = e.target && e.target.closest ? e.target.closest(".dz-box") : null;
    if (box){ const i = +box.dataset.cmd || 0; if (i !== DRAG.cmd){ DRAG.cmd = i; paintDropZone(true); } }
    // ★ 记一笔（`V-85` 查明的，**没改**）：`#dropzone` 是 `#pane-detail` 的**兄弟**（`V-42`），
    //   框里的事件根本不经过这个 pane ⇒ 这一段里的 `paintDropZone(true)` 实际到不了，
    //   CSS 里那条 `#dropzone.over .dz-box{transform:scale(1.02)…}` 也就一直没亮过。
    //   想让它亮，得单独给 `#dropzone` 挂 dragover（还得防连发重画）—— 那是**改行为**，
    //   不混在这一轮"纯搬运"里，等哪轮专门做。
    pane.classList.add("dover");
  });
  pane.addEventListener("dragleave", e => {
    if (!dragHasFiles(e)) return;
    DRAG.depth = Math.max(0, DRAG.depth - 1);
    if (!e.relatedTarget) dragEnd();
    pane.classList.remove("dover");
  });
  pane.addEventListener("drop", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                 // 真实路径由宿主送过来，这里只收拾界面
    pane.classList.remove("dover");
    // ★ 先别拆投放框：宿主的路径是另一条路送来的（几毫秒后到 `__mossDrop`）
  });
  // 拖出窗口 / 按 Esc 也要收干净，不然那块高亮会一直挂着
  window.addEventListener("dragend", dragEnd);
  window.addEventListener("blur", dragEnd);
  document.addEventListener("dragleave", e => { if (!e.relatedTarget) dragEnd(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") dragEnd(); });
}

/* 宿主把真实路径送过来（drag & drop 的落地口）。items: [{path, isDir, dir, name}, …]
   ★ 到这一步我们才知道真实路径，也才知道拖的到底是文件还是文件夹（以宿主说的为准）。 */
window.__mossDrop = function(items){
  const cmdIdx = DRAG.cmd;
  dragEnd();
  if (!items || !items.length){ uiLog("host drop: 没有路径（WebView2 没给）"); return; }
  // ★ `V-88`：拖进来的路径**先问一下有没有"别人更想要"**（比如备份那一页的「导出到」
  //   那一行：把文件夹拖上去 = 导出目标）。钩子收下了就到此为止，别再去跑包。
  //   真路径只有宿主知道（Chromium 不给 `File.path`），所以这条"落地口"必须留个插口。
  try{
    if (typeof window.__mossDropHook === "function" && window.__mossDropHook(items)){
      uiLog("host drop: 被页面钩子收下了（备份导出目标之类）");
      return;
    }
  }catch(e){ uiLog("host drop: 钩子抛了 " + e); }
  const p = cur;
  const it = items[0];
  uiLog("host drop: " + JSON.stringify(items));
  if (items.length > 1)
    toast("拖进来 " + items.length + " 个，先用第一个：" + (it.name || it.path));
  const cmds = dropCommandsFor(p, it.isDir);
  if (!p || !cmds.length){
    toast("✗ " + (p ? (":" + p.id + " 不收" + (it.isDir ? "文件夹" : "文件"))
                    : "先选一个包") + " —— 拖动时只列收得下它的包", true);
    return;
  }
  const cmd = cmds[Math.min(cmdIdx || 0, cmds.length - 1)].rule;
  // 参数串 = "你自己打的那些" + "这次拖进来的那一段"。上一次**拖进来的**那一段先摘掉，
  // 免得连着拖两次叠成一串（实测过：叠起来之后 md5 收到两条路径，判成字符串算了）。
  const box = argsInput();
  let base = box ? box.value : "";
  if (DROP_ARGS.id && base.endsWith(DROP_ARGS.piece))
    base = base.slice(0, base.length - DROP_ARGS.piece.length);
  base = base.trim();
  let cwd = "";
  if (cmd.cwd) cwd = it.isDir ? it.path : it.dir;      // 拖的是文件 → 用它所在的文件夹
  let piece = "";
  if (cmd.param){
    let v = cmd.base ? (it.name || "") : it.path;
    // ★ 一律加引号（除非声明里明写 `"quote": false`）：Windows 路径里全是反斜杠，
    //   而参数串到宿主那边要过一次 `shlex` —— 不加引号的 `C:\a\b.ico` 会被吃成
    //   `C:ab.ico`（实测），包就只能当字符串算了（`V-41`）。
    if (cmd.quote !== false) v = '"' + v + '"';
    piece = v;
  }
  const args = (base + (piece ? " " + piece : "")).trim();
  if (piece) DROP_ARGS.id = p.id, DROP_ARGS.piece = piece;
  else DROP_ARGS.id = null;
  if (box){ box.value = args; box.dispatchEvent(new Event("input")); }
  toast((cwd ? "以 " + cwd + " 为当前目录" : "按当前参数") +
        (piece ? (cmd.base ? "、只把文件名交给它" : "") : "") + "运行 :" + p.id);
  startRun(p, args, cwd);
};

/* 拖放这条线自己的日志（`user_data/state/_ui_drop.log`）。
   `V-40` 就是"拖了没反应、什么都不知道" —— 有这条日志，一次就能分清是页面没收到拖动、
   还是 WebView2 没给路径。失败不影响功能（纯记事）。 */
function uiLog(text){
  try{ pywebview.api.ui_log(String(text || "")); }catch(e){}
}

/* ---------------------------------------------------------------- 挂载（放最后）
   ★ 同前面几块：等 `DRAG` / `DRAGR` 这些 `const` 都声明完再挂（`mountVue()` 当场渲染）。 */
mountVue(MossDragBar, "#dragbar", {ico: ico});
mountVue(MossDropZone, "#dropzone");
