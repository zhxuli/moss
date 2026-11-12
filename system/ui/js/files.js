/* moss 界面 · files.js —— 文件管理（资源管理器 + 编辑器）
   ============================================================================
   `V-69`：这一块原来是一大段"拼字符串 + 手工绑事件"的命令式 DOM 代码
   （899 行，`V-67` 拆模块时原样搬进来的）。现在**画界面那部分**换成了 Vue 3 组件，
   逻辑（fs API 调用 / 排序 / 脏标记 / 保存 / 改名与对齐那笔事务）照旧留在这儿。

   怎么切的（照 `js/settings.js` 那个样板的规矩，经典脚本 + 全局组件 + 文件末尾房门面）：
     · `MossFileManager`  父：子选项卡条（`#fm-bar`）+ 页面容器（`#fm-body`）
     · `MossFileBrowse`   子：目录浏览那一页（导航 / 工具栏 / 表格 / 状态行）
     · `MossFilePage`     子：打开一个文件 = 一页（编辑器 + 保存 / 放弃 / 关闭）
   状态只有一份：全局的 `FM`（现在是 `Vue.reactive`），组件读它、逻辑改它。
   原来靠 `fmRender()` 手工重画，现在状态一变 Vue 自己重画；`fmRender()` 还在
   （外面那些调用点一行都没动），职责变成"保证挂载 + 兜底强制重画"。

   ★ 三条必须记住的（都是这里踩过的）：
     1. `FM` **必须在 Vue 之后建**（要用 `Vue.reactive`）—— `index.html` 里
        `vendor/vue.global.prod.js` 的 `<script>` 排在所有 `js/*.js` **前面**。
     2. `fmState(key)` 返回的**就是**那个响应式对象（Vue 会缓存代理），逻辑里
        缓存了再用、照样能触发重画；但别复制一份裸对象出来改了再塞回去 ——
        那份界面不认（和假后端 `fs_list` 必须回深拷贝是同一个道理）。
     3. 高亮是"覆盖层"：`hlInto()` 直接写 `<pre><code>` 的 innerHTML，**不归 Vue 管**
        （`.editor` 的 DOM 结构一个字都不能动）。所以它只在组件 mounted、
        输入防抖、以及 `$nextTick` 里被调用。

   ★ 类名 / DOM 结构（`.fbtools` / `table.fb` / `.editor` / `.b-save` …）**照旧**，
     预览场景靠这些选择器断言。
   三把钥匙（包目录名 / 清单里的 id / 数据目录）那套对账逻辑没动，
   见下面 `afterManifestSaved`。 */

/* ================================================================ 上下文与状态
   上下文按"当前对象"分，三种 key：
     · `<包 id>`   —— 这个包自己的一套
     · `hist:…`    —— **一条历史**（历史条目同样有文件管理），根是它当初的目录
     · `__all__`   —— 没选任何东西时的"全部文件"
   每个上下文记自己的当前目录、历史、选中、剪贴板、排序，以及**打开的文件子选项卡**。
   切到别的对象 = 换一套上下文，互不干扰；切回来还在原处。 */
const FM = Vue.reactive({
  ctx: null, st: {},
  /* ★ 包表（`DATA`）和历史（`HIST`）都是别的模块里的普通 `let`，**不是响应式的**。
     换包表之后，那些"从包表里算出来"的界面（子选项卡上那个包名、两层切换按钮
     要跳的目录）不会自己重算 —— 所以在这儿放一个响应式版本号：`refreshPkgs()`
     换掉 `DATA` 时 +1，组件里 `void FM.rev` 读它一下，依赖就登记上了。
     （不改这一下：改名之后子选项卡上还写着旧名字，切换按钮还指着已经不存在的目录。） */
  rev: 0,
});
const HIST_PREFIX = "hist:";

function isHistKey(key){ return String(key || "").startsWith(HIST_PREFIX); }
function histByKey(key){ return HIST.find(x => histKey(x) === key) || null; }
/* 现在该用哪一套文件管理上下文（顶部「文件管理」选项卡点进来时用） */
function fmCtxKey(){ return cur ? cur.id : (curH ? histKey(curH) : "__all__"); }

function fmState(key){
  if (!key) key = "__all__";
  if (!FM.st[key]){
    // ★ 这里有两个"hist"，**必须分开叫**：
    //     `hist`    = 这个上下文的**前进后退历史**（一个数组，`fmGoto` 要 push）
    //     `histCtx` = 这个上下文是不是"一条历史"（存那条历史的 key）
    //   曾经把第二个也起名 `hist`，同一个对象字面量里写了两遍 ⇒ 后面的把数组
    //   覆盖成 null/字符串 ⇒ `fmGoto` 里 `s.hist.slice` 直接抛异常，
    //   **整个文件管理都打不开**（实测：上下文永远停在上一次渲染的 `__all__` 上，
    //   地址栏写着 user_data，右边却显示"历史调用所在的目录"）。
    FM.st[key] = {rel:null, hist:[], hpos:-1, entries:[], sel:new Set(), clip:null,
                  sort:{key:"name", dir:1}, tabs:[], active:"__browse__",
                  pkg: (!isHistKey(key) && key !== "__all__") ? key : null,
                  histCtx: isHistKey(key) ? key : null,
                  layers: {user:false, system:false},
                  search: fmSearchFresh()};
  }
  return FM.st[key];
}
/* 检索状态，按上下文各一份（`on` 条子开着、`ran` 搜过、`files` 分组结果、`seq` 第几次搜） */
function fmSearchFresh(){
  return {on:false, q:"", cs:false, re:false, word:false,
          busy:false, ran:false, err:"", note:"",
          files:[], open:{}, nFiles:0, nHits:0, scanned:0, skipped:0, ms:0,
          truncated:false, cut:[], seq:0};
}
function fmSearch(){ return fmState(FM.ctx).search; }
/* 这个包在两层里的候选目录（`user/pkgs/<目录名>` / `system/pkgs/<目录名>`）。
   ★ 切换按钮要跳的是**同一个包在另一层的目录**，不是总目录 ——
     哪一层没有这个目录，那个按钮就不显示。
   ★ 用**真实的包目录名**拼，不能用 id 拼（`D-27` 方案 C：目录名和 id 允许不一样）——
     拿 id 拼出来的目录根本不存在，表现就是"按钮永远不显示"。 */
function fmLayerRels(key){
  const p = DATA.packages.find(x => x.id === key);
  const rel = p ? pkgRel(p) : null;
  if (!rel) return {user: "user/pkgs/" + key, system: "system/pkgs/" + key};
  const tail = rel.replace(/^(user|system)/, "");      // "/pkgs/<真实目录名>"
  return {user: "user" + tail, system: "system" + tail};
}
async function fmProbeLayers(key){
  if (!key || key === "__all__") return {user:true, system:true};
  if (isHistKey(key)) return {user:false, system:false};   // 历史没有"包的两层"
  const cand = fmLayerRels(key);
  const r = await pywebview.api.fs_exists([cand.user, cand.system]);
  const has = (r && r.has) || {};
  return {user: !!has[cand.user], system: !!has[cand.system]};
}
function fmDefaultRel(key){
  if (key === "__all__") return "user";
  if (isHistKey(key)){
    const it = histByKey(key);
    return (it && histDir(it)) || "user";
  }
  const p = DATA.packages.find(x => x.id === key);
  return (p && pkgRel(p)) || "user";
}
function fmLabel(key){
  if (key === "__all__") return "全部文件";
  if (isHistKey(key)){
    const it = histByKey(key);
    return "历史 · " + ((it && (it.name || it.target)) || key.slice(HIST_PREFIX.length));
  }
  const p = DATA.packages.find(x => x.id === key);
  return p ? (p.name + "（" + PSYM + p.id + "）") : key;
}
function isDirty(t){ return t && !t.binary && t.text !== t.original; }

/* 包改名 / 对齐目录名之后：文件管理里缓存下来的路径**全都过期了** ——
   当前所在目录 `s.rel`、前进后退历史 `s.hist`、打开着的文件子选项卡 `t.rel`，
   记的都是**旧目录**。不处理的话（你实测到的）：改名后回到文件管理，列的还是旧
   目录那份清单，**双击一个文件去编辑，宿主会说「不是文件」**（`fs_read` 拿着一
   条已经不存在的路径去查，`is_file()` 为假）。
   为什么用"换前缀"而不是"把这个上下文整个清掉"：清掉会把用户正开着的文件**凭空
   关掉**（可能还有没保存的改动）；换前缀则让那些文件跟着一起搬到新目录。
   换完给上下文打一个 `stale`，下次切过去时真的重新列一遍目录。 */
function fmReRoot(oldRel, newRel){
  if (!oldRel || !newRel || oldRel === newRel) return false;
  let any = false;
  Object.keys(FM.st).forEach(k => {
    let touched = false;
    const fix = r => {
      if (typeof r === "string" && (r === oldRel || r.startsWith(oldRel + "/"))){
        touched = true;
        return newRel + r.slice(oldRel.length);
      }
      return r;
    };
    const s = FM.st[k];
    s.rel = fix(s.rel);
    s.hist = (s.hist || []).map(fix);
    (s.tabs || []).forEach(t => { t.rel = fix(t.rel); });
    if (touched){ s.stale = true; any = true; }
  });
  return any;
}
function fmActiveTab(){
  const s = fmState(FM.ctx);
  return s.tabs.find(t => t.rel === s.active) || null;
}

async function fmSelect(key, keepTab){
  FM.ctx = key;
  const s = fmState(key);
  s.layers = await fmProbeLayers(key);          // 哪一层有"这个包的目录"
  // ★ 这个函数是**异步**的，而 `fmGoto` 认的是全局的 `FM.ctx`。连着点两个包时，
  //   前一个还卡在 `await` 上、后一个已经把 `FM.ctx` 换掉了 —— 前一个接着调
  //   `fmGoto`，就会把**它那个包的目录**写进**后一个包**的上下文里（实测：
  //   点 md5 再点别的包，那个包的"文件管理"历史里第一条是 `system/pkgs/md5`，
  //   接着打开的文件也全指向错的目录）。所以每次 `await` 回来先对一下暗号：
  //   用户已经换人了，这次结果就作废。
  if (FM.ctx !== key) return;
  if (!s.rel){
    const def = fmDefaultRel(key);
    const ok = await fmGoto(def, true, true);   // quiet: 不切顶层选项卡
    if (FM.ctx !== key) return;
    // ★ 历史那条记的目录可能早就删了/挪了 —— 退到**目标文件自己所在的目录**
    //   （和宿主 `path_start` 里那条退路同一个道理）。
    if (!ok && isHistKey(key)){
      const it = histByKey(key);
      const alt = it && it.target ? dirRel(it.target.replace(/[\\/][^\\/]*$/, "")) : null;
      if (alt && alt !== def) await fmGoto(alt, true, true);
    }
  } else if (s.stale){
    // 路径前缀被 `fmReRoot` 换过（包改名 / 对齐目录名）—— 得真的**重新列一遍**，
    // 否则界面上摆的还是旧目录那份清单，双击进去宿主会说「不是文件」。
    s.stale = false;
    await fmGoto(s.rel, false, true);
  } else fmRender();
  if (!keepTab) setTab("file");
}
/* 返回 true/false（调用方多半不看，但"历史目录没了要退一条"那里要靠它判断） */
async function fmGoto(rel, push, quiet){
  const s = fmState(FM.ctx);
  const r = await pywebview.api.fs_list(rel);
  if (!r.ok){ toast("✗ " + r.msg, true); return false; }
  s.rel = r.rel || rel;
  s.path = r.path || "";            // 真正的绝对路径（状态条上给用户看的，比 rel 好读）
  s.entries = r.entries || [];
  s.sel.clear();
  if (push !== false){
    s.hist = s.hist.slice(0, s.hpos + 1);
    s.hist.push(s.rel);
    s.hpos = s.hist.length - 1;
  }
  s.active = "__browse__";
  if (!quiet) setTab("file");
  fmRender();
  return true;
}
function fmHome(){
  const def = fmDefaultRel(FM.ctx);
  const s = fmState(FM.ctx);
  // 已经在默认目录就说一声 —— 不然点下去"什么都没发生"，看着像按钮坏了
  if (s.rel === def){ toast("已经在默认目录了：" + (s.path || def)); return; }
  fmGoto(def);
}
/* `quiet`：别抢顶层选项卡（谁在刷新就用谁的位置），而且**别把正开着的那一页关掉** ——
   AI 干完活自动刷的时候要它（`V-249`：`fmGoto` 会把 `s.active` 打回 `__browse__`，
   于是"刷一下"顺手就把你看的那个文件页收起来了）。 */
function fmRefresh(quiet){
  const s = fmState(FM.ctx);
  if (!s.rel) return;
  // 手动刷新时顺便重问一遍"另一层有没有这个包的目录"（比如刚复制过去）
  fmProbeLayers(FM.ctx).then(layers => { s.layers = layers; });
  const was = s.active;
  fmGoto(s.rel, false, !!quiet).then(ok => {
    // 那一页还在（没被删掉）就把它放回来 —— 内容由 `fmReloadPages()` 负责刷新
    if (ok && quiet && was !== "__browse__" && s.tabs.some(t => t.rel === was)){
      s.active = was;
      fmRender();
    }
  });
}
/* 盘上的文件被**别人**改了 —— AI 工作台干完活、恢复快照、或者你在外面拿别的编辑器改的。
   ============================================================================
   ★ 为什么非要有这个（`V-249`，你报的"AI 改完文件后「文件管理」页不自动刷新"）：
     文件管理是"列一遍、把清单和文件内容记在 `FM.st` 里"的 —— 盘上变了它不知道。
     你切过去看到的还是**改之前**那份清单、**改之前**的内容，得自己按一下 ⟳；
     更糟的是接着一存，就把新内容又盖回旧的。
   做三件事：① 每个包的目录缓存一律作废（AI 到底动了哪个包不一定知道）；
            ② 动到 `pkg.json` ⇒ 左边那份包表也重问一遍（名字/版本会变）；
            ③ 开着的那几页：**没改过**的重新读盘上的内容；改过的只提醒、不硬盖。
   `rels`：这一次盘上变了哪些文件 —— 收**绝对路径**（AI 给的是绝对路径），
   也收页面 rel（恢复快照那边给的是 `user/...`）；两边都先过一遍 `dirRel` 归一。
   ★★ 刷新**不许把顶层选项卡抢走**（`fmRefresh(true)`）：AI 那一页正跑着，
      你盯着步骤流，它干完活把你甩到「文件管理」上是不能接受的。 */
function diskChanged(rels){
  const list = (rels || []).map(r => dirRel(r) || String(r || ""));
  try{
    Object.keys(FM.st).forEach(k => { FM.st[k].stale = true; });
    FM.rev++;
    if (list.some(isPkgManifest) && typeof refreshPkgs === "function")
      refreshPkgs((cur && cur.id) || undefined, true);
    fmReloadPages(list);
    fmRefresh(true);
    // ★ `V-250`：快照那一列也重列/重算一遍（盘上变了 ⇒ "这次快照对比当前"整个变了）
    if (typeof bkRefresh === "function") bkRefresh();
  }catch(e){}
  return list;
}
/* 开着的那几页里，凡是**盘上被改过**的：没改过的重读一遍，改过的只提醒（不硬盖）。
   返回"被提醒"的那些 rel（有未保存改动的那些）—— 探针要看这个数。 */
function fmReloadPages(rels){
  const dirty = [];
  const want = (rels || []).filter(Boolean);
  if (!want.length) return dirty;
  Object.keys(FM.st).forEach(k => {
    ((FM.st[k] || {}).tabs || []).forEach(t => {
      if (want.indexOf(t.rel) < 0) return;
      if (isDirty(t)){ dirty.push(t.rel); return; }   // 手里有没保存的改动 ⇒ 不硬盖
      pywebview.api.fs_read(t.rel).then(r => {
        if (!r || !r.ok) return;
        t.text = r.text || ""; t.original = r.text || "";
        t.binary = !!(r.binary || r.too_big);
        t.note = r.binary ? "binary" : (r.too_big ? r.msg : "");
        // 编码/BOM 照读进来的原样带上（不然存回去就把 GBK 写成 UTF-8 了）
        t.encoding = r.encoding || "utf-8"; t.bom = r.bom || "";
        fmRender();
      }).catch(() => {});
    });
  });
  if (dirty.length)
    // `V-367`："盘上"是我们这边的说法，破折号后面才是重点 ⇒ 说明白话
    toast("这些文件在别处被改过了，你手上这份还没保存 —— 先看一眼再存：" +
          dirty.join("、"), true);
  return dirty;
}
/* 能不能再往上：两个根走到顶就没了；`abs/` 那边走到**盘根**（`abs/D:/`）就到顶 ——
   再往上会得到 `abs` 那个光秃秃的前缀，宿主会拒（它不是绝对路径）。
   ★ 注意：工具栏那颗 ⬆ 的 disabled 用的是**另一条**判据（`segs.length <= 1`），
     见 `MossFileBrowse` 的 `atTop` —— 那是原来 `bindBrowse` 里后写的一行覆盖了
     这一条的结果，`V-69` 只搬结构、不顺手改行为，所以照旧。 */
function fmAtTop(rel){
  const r = String(rel || "");
  if (!r.includes("/")) return true;                    // user / system
  if (r === "abs") return true;
  if (/^abs\/[A-Za-z]:\/?$/.test(r)) return true;       // 盘根
  return false;
}
function fmUp(){
  const rel = fmState(FM.ctx).rel || "";
  if (fmAtTop(rel)){ toast("已经到顶了：" + rel); return; }
  fmGoto(rel.split("/").slice(0, -1).join("/"));
}
function fmBack(){ const s = fmState(FM.ctx); if (s.hpos > 0){ s.hpos--; fmGoto(s.hist[s.hpos], false); } }
function fmFwd(){ const s = fmState(FM.ctx); if (s.hpos < s.hist.length - 1){ s.hpos++; fmGoto(s.hist[s.hpos], false); } }

/* ---- 打开 / 关闭文件子选项卡 ---- */
async function fmOpenPage(rel){
  const s = fmState(FM.ctx);
  let t = s.tabs.find(x => x.rel === rel);
  if (!t){
    const r = await pywebview.api.fs_read(rel);
    if (!r.ok){ toast("✗ " + r.msg, true); return; }
    const name = rel.split("/").pop();
    const ext = (name.split(".").pop() || "").toLowerCase();
    const meta = extOf({name: name, ext: ext});
    const kind = previewKindOf(name);
    t = {rel: rel, name: name, lang: meta.l || "plaintext",
         text: r.text || "", original: r.text || "",
         binary: !!(r.binary || r.too_big),
         note: r.binary ? "binary" : (r.too_big ? r.msg : ""),
         // ★ 记下"读进来时是什么编码 / 有没有 BOM"，保存时原样带回去 ——
         //   不然打开一个 GBK / UTF-16 的 txt 改一个字，整个文件就被转成 UTF-8 了。
         encoding: r.encoding || "utf-8", bom: r.bom || "",
         encodingNote: r.encoding_note || "",
         // ★ HTML / Markdown 默认就是**浏览模式**；点工具栏那颗眼睛 / 代码按钮来回切。
         previewKind: kind, preview: !!kind && !r.binary && !r.too_big, previewBase: "",
         factory: rel.split("/")[0] === "system"};
    s.tabs.push(t);
  }
  s.active = rel;
  setTab("file");
  fmRender();
  // ★ 打开就把光标放进编辑器，直接能打字。原来是在 `pageOf(rel)` 那个 DOM 上
  //   同步 focus；现在界面由 Vue 画，得等这一帧渲染完（`$nextTick` 之后 textarea 才在）。
  //   注意：**每次** fmOpenPage 都 focus（原来也是 —— 那个 focus 在 `if (!t)` 外面，
  //   再双击一个已经开着的文件也会把光标放回去）。
  fmFocusActiveSoon();
}
/* 打开文件并跳到某一行（检索结果用）；行号交给该页的 `t.jump` 处理 */
let _fmJumpSeq = 0;
async function fmOpenPageAt(rel, line){
  const s = fmState(FM.ctx);
  await fmOpenPage(rel);
  const t = s.tabs.find(x => x.rel === rel);
  if (!t) return;
  t.jump = {line: Math.max(1, line | 0), seq: ++_fmJumpSeq};
  fmRender();
}
function fmClosePage(rel){
  const s = fmState(FM.ctx);
  const t = s.tabs.find(x => x.rel === rel);
  if (!t) return;
  const doClose = () => {
    s.tabs = s.tabs.filter(x => x.rel !== rel);
    if (s.active === rel) s.active = s.tabs.length ? s.tabs[s.tabs.length - 1].rel : "__browse__";
    fmRender();
  };
  if (isDirty(t)) askConfirm("有未保存的改动", "“" + t.name + "” 改过但没保存，关掉就丢了。确定关吗？", doClose);
  else doClose();
}
function fmSave(t){
  if (!t || t.binary) return;
  pywebview.api.fs_write(t.rel, t.text, t.encoding || "utf-8", t.bom || "").then(r => {
    // ★ `V-367`：**存的是包清单**（pkg.json）时由"对账"那一支说一句收尾 ——
    //   以前这里先说「已保存」、紧接着 `afterManifestSaved` 又报「这个包没收下：…」，
    //   一个动作两条互相打脸的话。现在：成功 / 被拒 / 要不要统一目录名，都只由那边说。
    if (!r.ok){ toast("✗ " + r.msg, true); return; }
    // `t.original` 一改，两处黄点（子选项卡上那颗 / 编辑器标题栏那颗）和保存按钮的
    // 灰不灰，Vue 自己就跟着重算了 —— 原来这里要手工 `fmPaintBar()` / `fmPaintDirty()`。
    t.original = t.text; fmPaintBar();
    // 存的是**包清单** ⇒ 界面手里那份包数据已经过期了，重新解析一遍
    if (isPkgManifest(t.rel)) refreshPkgs(null, true).then(() => afterManifestSaved(t.rel, t.text, r));
    else toast("已保存 " + t.rel + (r.factory ? "（出厂件）" : ""));
  });
}

/* 按内容搜当前目录（含子目录）。搜索在宿主那边跑，这里只负责状态和结果分组。 */
function fmSearchOpen(on){
  const st = fmSearch();
  const to = (on === undefined) ? !st.on : !!on;
  st.on = to;
  if (!to) st.busy = false;
  fmRender();
  if (to) fmFocusSearchSoon();          // 打开就把光标放进搜索框，直接能打字
}
/* 界面由 Vue 画，得等这一帧 */
function fmFocusSearchSoon(){
  const go = () => {
    const el = document.querySelector("#fm-body .fbsearch input");
    if (el){ el.focus(); el.select(); }
  };
  const a = fmApp();
  if (a) a.$nextTick(go); else go();
}
function fmSearchClose(){ fmSearchOpen(false); }
/* 改选项后，如果已经搜过就重搜一次 */
function fmSearchOpt(key){
  const st = fmSearch();
  st[key] = !st[key];
  fmSearchMaybeRerun();
}
function fmSearchMaybeRerun(){
  const st = fmSearch();
  if (st.on && st.ran && String(st.q || "").trim()) fmSearchRun();
}
async function fmSearchRun(){
  const st = fmSearch(), s = fmState(FM.ctx);
  const q = String(st.q || "");
  if (!q.trim()){ toast("先输入要搜的内容"); return; }
  const seq = ++st.seq;
  const roots = [(s.rel || "user")];       // 只搜当前路径
  st.busy = true; st.err = ""; st.note = ""; st.ran = true;
  st.files = []; st.open = {};
  st.nFiles = 0; st.nHits = 0; st.scanned = 0; st.skipped = 0; st.ms = 0;
  st.truncated = false; st.cut = [];
  fmRender();
  let r = null;
  try{
    r = await pywebview.api.fs_search(q, {roots: roots, cs: !!st.cs, re: !!st.re,
                                          word: !!st.word});
  }catch(e){
    r = {ok: false, msg: "搜索失败：" + ((e && e.message) || e)};
  }
  if (seq !== st.seq) return;             // 又搜了一次，这份结果作废
  st.busy = false;
  if (!r || !r.ok){
    st.err = (r && r.msg) || "搜索失败";
    fmRender();
    return;
  }
  st.files = r.files || [];
  st.nFiles = r.n_files || 0;
  st.nHits = r.n_hits || 0;
  st.scanned = r.scanned || 0;
  st.skipped = r.skipped || 0;
  st.ms = r.ms || 0;
  st.truncated = !!r.truncated;
  st.cut = r.cut || [];
  st.note = r.note || "";
  // 第一个文件默认展开：词很特别的时候一眼就能看到是哪一行
  st.open = {};
  if (st.files.length) st.open[st.files[0].rel] = true;
  fmRender();
}
/* 点一条命中 = 打开那个文件 + 跳到那一行 */
function fmSearchJump(rel, line){ fmOpenPageAt(rel, line); }

/* ---------------------------------------------------------------- 包数据刷新
   `pkg.json` 是宿主唯一的清单来源；它一变，界面手里那份（名字 / 说明 / 参数表 /
   图标 / 入口）就全是旧的。界面的 `DATA` 是**问宿主要来的**（不自己解析包格式，
   见 `U-16`），所以这里就是"再问一遍 + 重画受影响的地方"。
   ★ 刻意**不调用 `init()`**：那会把文件管理切回"全部文件"、丢掉当前目录和打开的
     文件 —— 用户正开着 pkg.json 在编辑，保存一下就被弹走是不能接受的。
     这里只刷新包列表、状态与详情；文件管理的目录 / 子选项卡（含编辑器里的内容）
     原样不动，只把子选项卡的**名字**重画一下。 */
function isPkgManifest(rel){
  return /(^|\/)pkg\.json$/i.test(String(rel || ""));
}
async function refreshPkgs(preferId, quiet){
  let fresh;
  try{ fresh = await pywebview.api.state(); }catch(e){ return; }
  if (!fresh || !fresh.packages) return;
  DATA = fresh;
  FM.rev++;                      // ★ 包表换了一份：让那些"从包表算出来"的界面重算（见 FM.rev）
  renderList(); paintStates();
  // `DATA` 换了新对象，`cur` 得指向新的那一份，否则详情里读到的还是旧字段。
  // `preferId` 是"刚改完名"给的提示：旧 id 当然找不到了，但那不是"包没了"，
  // 别拿它去吓人（改名那条路会把 `cur` 直接指到新 id 上）。
  if (cur){
    const id = cur.id;
    cur = DATA.packages.find(p => p.id === (preferId || id)) ||
          DATA.packages.find(p => p.id === id) || null;
    if (cur) renderDetail();
    else {                       // 清单被删/改到认不出来了：这个包已经不在了
      cur = null; renderDetail();
      // `quiet`：存清单那条路自己会说得更准（是 JSON 坏了还是 id 不合法），
      // 别在这儿再抢一句含糊的（`V-33`）。
      if (!quiet) toast("这个包已经不在列表里了（说明文件被删掉或改坏了）", true);
    }
  }
  fmPaintBar();                  // 子选项卡上那个包名可能变了
  // ★ `V-387`：包表换了 ⇒ 顶上那颗「界面」也得按**新的一份**重画。以前这里只重画
  //   列表 / 详情，于是"AI 给包加了内嵌界面（`pkg.json` 的 `ui.embed`）"之后，
  //   那个选项卡**不出现**，非要把包切走再切回来（`select()` 里才重画）才看得见
  //   —— 用户报的就是这个。
  if (typeof paintEmbedTab === "function") paintEmbedTab();
  // 撤回快照这件事**不能静默**（`V-31` ✅）：宿主那边有话说（多半是某个包的
  // `pkg.json` 写坏了 / id 不合法），把它原话弹出来 —— 否则你看到的现象只是
  // "我新建的包怎么不出现"，真正的原因谁也看不见。
  const sr = fresh.stale_reason;
  if (sr && sr !== lastStaleReason){
    lastStaleReason = sr;
    toast("包列表没读出来，下面显示的还是上一次的：" + sr, true);
  } else if (!sr){
    lastStaleReason = "";
  }
}

/* ---------------------------------------------------------------- 存完清单对一遍账
   （`V-33` ✅，你定的）你说的是：「我修改了 pkg.json 以后 我点保存按钮 你应该重新解析
   并且发现不配套的情况 然后这个时候 你应该询问用户 这种情况应该怎么处理 就类似于现在
   的更名功能 如果更改了文件夹名字 进行了统一 那么 文件管理这里 你也需要把路径从原来
   的变更新的」。

   所以这里就是"重新解析"之后的**对账**。一个包有**三把钥匙**（`D-27`）：
       包目录名 ／ 清单里的 id ／ 数据目录 state/<id>
   手工改清单最容易把它们改散，散了的后果又特别难查（数据"凭空没了"、
   文件管理指着不存在的路径）。对账分三种结果：
     · 宿主压根没收下它（JSON 坏 / id 非法 / id 被占）→ 说清楚为什么，别让它
       "从列表里消失得不明不白"；
     · 收下了，但目录名和 id 不一样 → **问一句**，你说统一就走更名那笔事务
       （目录名一起改；旧数据目录还在的话一起搬），然后把文件管理里的路径
       从旧的换成新的；
     · 都对得上 → 什么都不做。 */
async function afterManifestSaved(fileRel, text, saved){
  // ★ `V-367`：`saved` = `fs_write` 的返回。存清单这条路**只在这儿报一次**
  //   （见 `fmSave` 的注释）：收下了且三把钥匙对得上 ⇒ 说"已保存"。
  const okMsg = () => toast("已保存 " + fileRel + ((saved && saved.factory) ? "（出厂件）" : ""));
  if (DATA.stale_reason) return;                 // 包表本身没读回来，别乱下结论（上面弹过了）
  const dirRel = String(fileRel).replace(/\/[^/]+$/, "");   // `…/pkg.json` → 它所在的包目录
  const base = dirRel.split("/").pop() || "";
  const layer = dirRel.split("/")[0];            // user / system —— 目录得改回**同一层**里
  const p = DATA.packages.find(x => pkgRel(x) === dirRel);
  let why = "", newId = "";
  if (!p){
    try{ newId = String((JSON.parse(text) || {}).id || "").trim().toLowerCase(); }
    catch(e){ why = "这不是合法的 JSON（" + e.message + "）"; }
    if (!why && !ID_RE.test(newId))
      // `V-367`：别把正则源码 `^[a-z][a-z0-9_-]{0,31}$` 摆给用户看（"不合法"三个字留着 ——
      //   预览场景 `pkg-edit-bad-id` 钉的就是它）
      why = "id '" + newId + "' 不合法：只能用小写字母、数字、- 和 _，最长 32 个字，"
            + "而且要用字母开头";
    if (!why && DATA.packages.some(x => x.id === newId))
      why = "id '" + newId + "' 已经被别的包用了";
    if (!why) why = "moss 没认下这个包（清单读不出来）";
    toast("✗ 这个包没被接受：" + why, true);
    return;
  }
  if (p.id === base){ okMsg(); return; }         // 三把钥匙对得上，收工
  const oldData = "user/state/" + base, newData = "user/state/" + p.id;
  let moveData = false;
  try{
    const has = await pywebview.api.fs_exists([oldData, newData]);
    const h = (has && has.has) || {};
    moveData = !!h[oldData] && !h[newData];
  }catch(e){ moveData = false; }
  askConfirm("清单和包目录不一样了",
    "你把这个包的 id 改成了 <b>" + esc(p.id) + "</b>，但包目录还叫 <b>" + esc(base) + "</b>。" +
    (moveData ? "<br>另外旧数据目录 <b>user_data/state/" + esc(base) + "</b> 还在，" +
                "一起搬成 <b>state/" + esc(p.id) + "</b>。" : "") +
    "<br><br>要我把包目录名" + (moveData ? "（连同旧数据）" : "") +
    "一起改成 <b>" + esc(p.id) + "</b> 吗？",
    () => unifyPkgDir(p, dirRel, moveData, layer));
}

/* 统一：目录名 → id。走宿主那笔改名事务（新旧 id 都写成它现在的 id ⇒ 只改目录名），
   旧数据目录另搬一下（宿主不预建数据目录，`state/` 又在 user_data 里，用文件接口搬即可），
   最后**把文件管理里那些缓存路径从旧的换成新的**（不然双击编辑会说「不是文件」，`V-30`）。 */
async function unifyPkgDir(p, dirRel, moveData, layer){
  consoleKey = "__host__";
  const cmd = "moss --rename " + p.id + " " + p.id;
  setConsole("__host__", "$ " + cmd, "运行中");
  const r = await pywebview.api.run_host("--rename " + p.id + " " + p.id);
  setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
             r.code === 0 ? "完成" : ("退出码 " + r.code));
  if (r.code !== 0){
    toast("✗ 没统一成，看「命令行」里说了什么", true);
    setTab("console");
    return;
  }
  // ★ `V-367`：搬运结果和"统一完成"**并成一条**（以前两颗胶囊，后一颗把前一颗盖掉）
  let note = "";
  if (moveData){
    const base = String(dirRel).split("/").pop();
    const rr = await pywebview.api.fs_rename("user/state/" + base, p.id);
    note = rr.ok ? "，旧数据也一起搬好了"
                 : ("（但旧数据没搬成：" + rr.msg + "）");
  }
  toast("已统一：包目录名 → " + p.id + note, note.indexOf("没搬成") >= 0);
  const newRel = (layer || "user") + "/pkgs/" + p.id;
  await refreshPkgs(p.id);
  fmReRoot(dirRel, newRel);                       // ★ 文件管理里的路径跟着搬
  if (DATA.packages.some(x => x.id === p.id)) select(p.id);
  else renderDetail();
}

/* ================================================================ 排序 + 高亮（逻辑）
   这两件事留在组件外面：排序是纯函数（谁要用谁调），高亮是"覆盖层"（见文件头第 3 条）。 */
function fmSorted(s){
  const {key, dir} = s.sort;
  return s.entries.slice().sort((a, b) => {
    if (a.dir !== b.dir) return a.dir ? -1 : 1;
    let x, y;
    if (key === "name"){ x = a.name.toLowerCase(); y = b.name.toLowerCase(); }
    else if (key === "mtime"){ x = a.mtime || 0; y = b.mtime || 0; }
    else if (key === "size"){ x = a.size || 0; y = b.size || 0; }
    else { x = typeLabel(a).toLowerCase(); y = typeLabel(b).toLowerCase(); }
    return x < y ? -1 * dir : (x > y ? 1 * dir : 0);
  });
}
/* ---------------------------------------------------------------- 代码高亮层
   ★ `V-272`（照你说的：别拿防抖糊住"整篇重算"）：**只高亮看得见的那一屏**。
     原做法是"每次输入 → 整篇 `hljs.highlight()` → 整块 `innerHTML`"。无头 Edge 实测
     （同一份 `highlight.min.js`、同一个调用方式）：
       · 整篇：`list.js` 832 行 **25.0 ms**、`ai.js` 1132 行 **26.3 ms**、`cli.py` 1616 行 **12.8 ms**
         （再加上写 DOM 那几毫秒；194 KB 的文件是 124 ms + 42 ms）
     打字时每敲一下都付这份钱 ⇒ 上一版拿 120ms 防抖把它压成"停下来才画一次"（权宜）。
     现在只算一屏 + 上下各留 `HL_PAD` 行 ⇒ 实测 **2~5 ms**（同样三个文件：5.8 / 4.9 / 2.1 ms）
     —— **防抖删掉**，改成按帧合并（`requestAnimationFrame`），打字时零延迟。
   ★ 三条不许破的规矩：
     ① 高亮层里的**文字必须和输入层一模一样**（差一个字就整篇错位 = 光标偏移）。所以窗口
        之外的行用 `Text` 节点**原样**放（不转义、不丢字），只有窗口那一段是 HTML；
     ② 跨行的 span（块注释 / 模板字符串）按行切开时要把标签**接着开**（`splitHlLines`），
        否则那些行的颜色会"漏出去"；
     ③ 窗口上下留 `HL_PAD` 行上下文：滚动时不至于马上露出没上色的行；而且万一窗口正好切在
        块注释中间，重新开始 token 化的那几行也落在**离视口 20 行**的地方 —— 你看不见。
   ★ 每次画完把这次的开销写进 `window.__hl`（探针的把手，跟 `ai.js` 的 `__followN` 一个路子）。 */
//: 视口上下各多算几行。**20 是量出来的**：`HL_PAD=60`（画 160 行）要 5~6 ms，`20`（画 80 行）
//: 只要 2~4 ms；而 20 行已经够那两件保险（滚动不露白、窗口起点不在视口里）。
const HL_PAD = 20;
const HL_MAX = 300000;          // 超过这么多字符就不上色（原来那道闸，照旧）

/* 把 highlight.js 出来的一整段 HTML 按行切开，**跨行的 span 在下一行接着开**。
   用法只在 `paintHl` 里；单独拎出来是为了能被探针直接钉住。 */
function splitHlLines(html){
  const out = [];
  const stack = [];                       // 还没闭合的 `<span …>`
  let cur = "";
  const re = /<span\b[^>]*>|<\/span>|\n|[^<\n]+|</g;
  let m;
  while ((m = re.exec(html)) !== null){
    const tk = m[0];
    if (tk === "\n"){
      out.push(cur + "</span>".repeat(stack.length));
      cur = stack.join("");               // 下一行开头把还开着的标签补回来
    } else if (tk === "</span>"){
      stack.pop();
      cur += tk;
    } else if (tk.charAt(0) === "<" && tk.charAt(1) === "s"){
      // ★ 这一行**必须**先判 `<`：`V-272` 第一版只写了 `tk.charAt(1) === "s"`，
      //   于是正文 `(s).` 被当成"开头标签"压进了栈，下一行开头又"接着开"一次
      //   ⇒ 屏幕上凭空多出 `(s).`（是那个"文字必须一模一样"的断言当场抓住的）。
      stack.push(tk);
      cur += tk;
    } else {
      cur += tk;
    }
  }
  out.push(cur);
  return out;
}

/* 画高亮层。`win = {first, last}` 是**看得见的行号区间**（0 基）；传 null = 整篇（兜底）。 */
function paintHl(t, code, win){
  const text = t.text || "";
  const can = text.length <= HL_MAX && window.hljs && t.lang && hljs.getLanguage(t.lang);
  if (!can){
    code.textContent = text + "\n";
    window.__hl = {mode: "plain", ms: 0, chars: text.length};
    return window.__hl;
  }
  const lines = text.split("\n");
  const n = lines.length;
  const a = win ? Math.max(0, (win.first | 0) - HL_PAD) : 0;
  const b = win ? Math.min(n - 1, (win.last | 0) + HL_PAD) : n - 1;
  const t0 = performance.now();
  let mid = "";
  try{
    mid = splitHlLines(hljs.highlight(lines.slice(a, b + 1).join("\n"),
                                      {language: t.lang, ignoreIllegals: true}).value).join("\n");
  }catch(e){ mid = ""; }
  const ms = performance.now() - t0;
  // 三段：前段纯文本 / 中间高亮 / 后段纯文本（末尾那个换行贴在最后一段上）
  const before = a > 0 ? lines.slice(0, a).join("\n") + "\n" : "";
  const after = (b < n - 1 ? "\n" + lines.slice(b + 1).join("\n") : "") + "\n";
  if (!code.__parts){                       // 只在第一次建这三个节点，之后只换内容
    code.textContent = "";
    const pm = document.createElement("span");
    pm.className = "hlwin";
    code.append(document.createTextNode(""), pm, document.createTextNode(""));
    code.__parts = true;
  }
  const p1 = code.childNodes[0], pm = code.childNodes[1], p2 = code.childNodes[2];
  if (p1.nodeValue !== before) p1.nodeValue = before;       // 纯文本，不用转义、不丢字
  if (pm.__html !== mid){ pm.innerHTML = mid; pm.__html = mid; }
  if (p2.nodeValue !== after) p2.nodeValue = after;
  window.__hl = {mode: "window", ms: ms, chars: text.length, lines: n,
                 a: a, b: b, painted: b - a + 1};
  return window.__hl;
}

/* 老名字（外面/老注释里还叫 `hlInto`）：整篇画一遍 —— 只在量不到视口时兜底 */
function hlInto(t, code){ return paintHl(t, code, null); }

/* ---------------------------------------------------------------- HTML / Markdown 浏览模式
   ★ 用户要的不是"把 md / html 当代码看"，而是能在**浏览（渲染）**和**代码**之间来回切。
   · Markdown：前端自己渲染（转义优先，不执行原文里的 HTML / JS）；
   · HTML：放进 sandbox iframe，保留它自己的 CSS / JS；
   · 相对路径靠宿主的 `fs_preview_url` 给一个本地 HTTP base，WebView2 才能加载。
   文件本身仍是打开的那个 tab，保存按钮、编码、BOM 全按原逻辑走 —— 预览只是多一个视图。 */
function previewKindOf(name){
  const ext = String(name || "").split(".").pop().toLowerCase();
  if (ext === "md" || ext === "markdown") return "md";
  if (ext === "html" || ext === "htm") return "html";
  return "";
}

function mdSafeUrl(u){
  const s = String(u || "").trim();
  return /^(javascript|vbscript|data:text\/html)/i.test(s) ? "#" : s;
}

/* 行内 Markdown。输入先整体转义，再只生成我们认识的标签 ⇒ 原文里的 HTML 不执行。 */
function mdInline(text){
  let s = esc(String(text || ""));
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (m, t) => {
    codes.push(t);
    return "\u0000C" + (codes.length - 1) + "\u0000";
  });
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (m, alt, u) => '<img src="' + mdSafeUrl(u) + '" alt="' + alt + '">');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
    (m, txt, u) => '<a href="' + mdSafeUrl(u) + '" target="_blank" rel="noopener noreferrer">' + txt + '</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  s = s.replace(/\u0000C(\d+)\u0000/g, (m, i) => "<code>" + codes[+i] + "</code>");
  return s;
}

/* 轻量 Markdown 块解析：标题 / 段落 / 列表 / 引用 / 代码块 / 分割线 / 表格。够看文档，不追求规范全实现。 */
function renderMarkdown(src){
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0, list = "";
  const closeList = () => { if (list){ out.push("</" + list + ">"); list = ""; } };
  const blockStart = (ln) => /^\s*(#{1,6}\s|>\s?|```|~~~|[-*+]\s|\d+\.\s|---|\*\*\*|___)/.test(ln);
  while (i < lines.length){
    const line = lines[i];
    const fence = line.match(/^\s*(```+|~~~+)\s*([A-Za-z0-9_+.-]*)/);
    if (fence){
      closeList();
      const mark = fence[1].charAt(0), lang = fence[2] || "";
      const body = [];
      i++;
      while (i < lines.length && !new RegExp("^\\s*" + mark + "{3,}").test(lines[i])) body.push(lines[i++]);
      if (i < lines.length) i++;
      out.push('<pre><code' + (lang ? ' class="language-' + esc(lang) + '"' : "") + '>' +
               esc(body.join("\n")) + '</code></pre>');
      continue;
    }
    if (!line.trim()){ closeList(); i++; continue; }
    const h = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (h){ closeList(); const n = h[1].length; out.push("<h" + n + ">" + mdInline(h[2]) + "</h" + n + ">"); i++; continue; }
    if (/^\s*(?:---|\*\*\*|___)\s*$/.test(line)){ closeList(); out.push("<hr>"); i++; continue; }
    if (/^\s*>\s?/.test(line)){
      closeList();
      const q = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push("<blockquote>" + renderMarkdown(q.join("\n")) + "</blockquote>");
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)){
      if (list !== "ul"){ closeList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + mdInline(line.replace(/^\s*[-*+]\s+/, "")) + "</li>"); i++; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)){
      if (list !== "ol"){ closeList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + mdInline(line.replace(/^\s*\d+\.\s+/, "")) + "</li>"); i++; continue;
    }
    // 表格：本行有 |，下一行是 |---|:---:| 这种。
    if (line.indexOf("|") >= 0 && i + 1 < lines.length &&
        /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1]) && lines[i + 1].indexOf("-") >= 0){
      closeList();
      const cells = (ln) => ln.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(x => x.trim());
      const head = cells(line);
      i += 2;
      let html = "<table><thead><tr>" + head.map(x => "<th>" + mdInline(x) + "</th>").join("") + "</tr></thead><tbody>";
      while (i < lines.length && lines[i].trim() && lines[i].indexOf("|") >= 0){
        html += "<tr>" + cells(lines[i++]).map(x => "<td>" + mdInline(x) + "</td>").join("") + "</tr>";
      }
      html += "</tbody></table>";
      out.push(html);
      continue;
    }
    closeList();
    const para = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !blockStart(lines[i]) &&
           !(lines[i].indexOf("|") >= 0 && i + 1 < lines.length &&
             /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1]))){
      para.push(lines[i++].trim());
    }
    out.push("<p>" + para.map(mdInline).join(" ") + "</p>");
  }
  closeList();
  return out.join("\n") || '<p class="pv-empty">（空文件）</p>';
}

function previewVars(){
  const cs = getComputedStyle(document.documentElement);
  return ["--bg","--panel","--panel2","--fg","--fg2","--dim","--accent","--line","--line2","--code-bg","--hover","--fill"]
    .map(n => n + ":" + (cs.getPropertyValue(n) || "")).join(";");
}

function previewDocument(t, base){
  if (!t) return "";
  const kind = t.previewKind || previewKindOf(t.name);
  const b = String(base || "");
  if (kind === "md"){
    const css = ":root{" + previewVars() + "}" +
      "html,body{margin:0;background:var(--bg);color:var(--fg)}" +
      "body{padding:24px 30px;font:14px/1.75 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}" +
      ".pv-body{max-width:980px;margin:0 auto;word-wrap:break-word}" +
      "h1,h2,h3,h4,h5,h6{line-height:1.35;margin:1.4em 0 .55em;color:var(--fg)}" +
      "h1{font-size:2em;border-bottom:1px solid var(--line2);padding-bottom:.3em}" +
      "h2{font-size:1.55em;border-bottom:1px solid var(--line2);padding-bottom:.22em}" +
      "p{margin:.7em 0}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}" +
      "code{font-family:Consolas,'Cascadia Code',monospace;font-size:.92em;background:var(--code-bg);padding:.12em .35em;border-radius:5px}" +
      "pre{background:var(--code-bg);border:1px solid var(--line2);border-radius:10px;padding:14px 16px;overflow:auto}" +
      "pre code{background:none;padding:0}" +
      "blockquote{margin:.9em 0;padding:.2em 1em;border-left:3px solid var(--accent);color:var(--fg2);background:var(--panel2)}" +
      "table{border-collapse:collapse;margin:1em 0;width:100%}th,td{border:1px solid var(--line2);padding:6px 10px;text-align:left}" +
      "th{background:var(--panel2)}img{max-width:100%;height:auto;border-radius:6px}" +
      "hr{border:0;border-top:1px solid var(--line2);margin:1.5em 0}.pv-empty{color:var(--dim)}";
    const head = '<!doctype html><html><head><meta charset="utf-8">' +
      (b ? '<base href="' + esc(b) + '">' : "") +
      '<meta name="viewport" content="width=device-width,initial-scale=1"><style>' + css + '</style></head>';
    return head + '<body><div class="pv-body">' + renderMarkdown(t.text) + '</div></body></html>';
  }
  let raw = String(t.text || "");
  if (!b) return raw;
  const tag = '<base href="' + esc(b) + '">';
  if (/<head[^>]*>/i.test(raw)) return raw.replace(/<head[^>]*>/i, m => m + tag);
  if (/<html[^>]*>/i.test(raw)) return raw.replace(/<html[^>]*>/i, m => m + "<head>" + tag + "</head>");
  return tag + raw;
}

/* ================================================================ 界面（Vue 3 组件）
   三个组件，一个状态：父组件管子选项卡条和页面容器，两个子组件各画一页。
   `active` 而不是 `on` 当 prop 名 —— `on` 在 Vue 里是事件前缀那一族，别去蹭。

   ★ 模板里那些 `v-html='ico("save", "i")'` 为什么用单引号包属性：里面的 JS 用双引号，
     正好让 `tools/界面检查`（静态检查脚本）那条"ico() 的图标名都在 lucide 表里"
     继续能扫到（它按 `ico("名字"` 匹配）。
   ★ 图标用 `v-html` 直接写在按钮上（和原来 `b.innerHTML = ico(...)` 生成的 DOM 一模一样）；
     子选项卡条那颗图标外面多包了一层 `<span>`（一个按钮里既有图标又有文字，
     `v-html` 只能在元素上），`.fmtab` / `svg.i` 那两条 CSS 不受影响。 */

const MossFilePage = {
  name: "moss-file-page",
  props: {
    t: {type: Object, required: true},
    active: {type: Boolean, default: false},
  },
  template: `
<div class="fmpage" :class="{on: active}" :data-page="t.rel">
  <div class="outbar">
    <span :style="'color:' + meta.c + ';display:flex'" v-html='ico(meta.i, "i")'></span>
    <span class="mono">{{ t.rel }}</span>
    <!-- 猜到的编码写出来：不然遇到乱码不知道是"文件本来就这样"还是"猜错了" -->
    <span v-if="t.encodingNote" class="encnote">{{ t.encodingNote }}</span>
    <span class="dirtydot" :hidden="!dirty" title="有未保存的改动"></span>
    <span style="flex:1"></span>
    <button v-if="canPreview && !previewOn" class="iconbtn b-preview" title="浏览模式（渲染 Markdown / HTML）"
            v-html='ico("eye", "i")' @click="togglePreview"></button>
    <button v-if="canPreview && previewOn" class="iconbtn b-preview on" title="代码模式（继续编辑）"
            v-html='ico("code", "i")' @click="togglePreview"></button>
    <button class="iconbtn b-save" title="保存（Ctrl+S）" :disabled="!dirty"
            v-html='ico("save", "i")' @click="save"></button>
    <button class="iconbtn b-revert" title="放弃改动，重新读一遍"
            v-html='ico("undo-2", "i")' @click="revert"></button>
    <button class="iconbtn b-default" title="用系统默认程序打开"
            v-html='ico("external-link", "i")' @click="openDefault"></button>
    <button class="iconbtn b-reveal" title="在资源管理器里显示"
            v-html='ico("folder-open", "i")' @click="reveal"></button>
    <button class="iconbtn b-close" title="关闭这个选项卡"
            v-html='ico("x", "i")' @click="close"></button>
  </div>
  <div class="note" v-if="note" v-html="note"></div>
  <div class="editor" v-show="!previewOn">
    <pre aria-hidden="true" ref="pre"><code class="hljs" ref="code"></code></pre>
    <textarea spellcheck="false" wrap="off" ref="ta" :readonly="!!t.binary"
              :value="t.text" @input="onInput" @scroll="onScroll"
              @keydown="onKeydown"></textarea>
    <div class="gutter" ref="gutter" aria-hidden="true"></div>
  </div>
  <div class="previewpane" v-if="previewOn">
    <iframe class="preview-frame" :srcdoc="previewDoc" title="浏览模式"
            sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups"></iframe>
  </div>
</div>`,
  data(){
    return {_raf: 0};              // `V-272`：按帧合并（不再用 120ms 定时器）
  },
  watch: {
    /* ★ `V-249`：`t.text` 不一定是**在这儿**改的 —— AI 干完活、恢复快照、
       或者外面动了盘上的文件之后，`fmReloadPages()` 会把内容重新读进来。
       以前只有 `onInput` 会重画高亮层，于是"字换了、颜色还是旧的"（或者干脆全白）。
       所以改成盯住 `t.text`：不管谁改的，都会重画。 */
    "t.text"(){ this.scheduleHl(); },
    /* ★ `V-272`：这一页从"藏着"变成"显示"时补画一次 —— 藏着的时候量不到视口高度
       （`clientHeight = 0`），窗口会算成"从第一行开始的一小段"。
       ★ `V-376`：补画那一下顺带 `syncScroll()`（见 `paintHl`）—— 藏着的时候三层都不能写
       scrollTop（会被夹成 0），所以"切回来"这一刻必须重新对一次。 */
    active(v){ if (v){ this.scheduleHl(); if (this.previewOn) this.ensurePreview(); } },
    "t.preview"(v){ if (v) this.ensurePreview(); },
    /* 检索结果点进来时跳到那一行（等 textarea 有内容再跳） */
    "t.jump"(v){ if (v) this.$nextTick(() => this.jumpTo(v.line)); },
  },
  computed: {
    // 后缀 → 图标 / 颜色 / 语言（`core.js` 的 `EXT` / `NO_EXT`，只有一份）
    meta(){ return extOf({name: this.t.name, ext: (this.t.name.split(".").pop() || "").toLowerCase()}); },
    dirty(){ return isDirty(this.t); },
    canPreview(){ return !!this.t.previewKind && !this.t.binary; },
    previewOn(){ return !!this.t.preview && this.canPreview; },
    previewDoc(){ return this.previewOn ? previewDocument(this.t, this.t.previewBase) : ""; },
    note(){
      if (this.t.binary) return ico("binary", "i") + " 二进制文件，编辑不了；要看就用「默认程序打开」";
      if (this.t.note) return ico("alert-triangle", "i") + " " + this.t.note;
      if (this.t.factory) return ico("alert-triangle", "i") +
          " 这是出厂件（system/）—— 能改，但将来升级时会被整体替换";
      return "";
    },
  },
  mounted(){
    // ★ `V-376`：打开一个文件时**先把光标放回开头**，再画高亮 —— 不然光标会"漂"。
    //   两层是叠在一起的两个视图：`:value="t.text"` 是按属性写进 textarea 的，而 HTML
    //   规定"**没聚焦**时设 value ⇒ 选区折叠到文本**末尾**"；紧接着 `fmOpenPage` 的
    //   `fmFocusActiveSoon()` 一 `focus()`，浏览器为了"让光标可见"又把 textarea
    //   **滚到最底**，可高亮层那个 `pre` 还停在顶上（第一次画高亮还会把 `code` 清空一次、
    //   顺手把 `pre.scrollTop` 夹回 0）⇒ **你看到的字**和**光标逻辑上所在的位置**差着好几屏：
    //   点一下光标不上不下（两种情况的行线刚好错开半行），一按删除删掉的是别处的内容。
    //   实测（`bench/big.js`，2774 行）：打开后 `ta.scrollTop=55370 / pre.scrollTop=0`；
    //   随便滚一下 `onScroll` 又把它对齐了 —— 所以这个 bug 只在"刚打开"那一会儿看得见。
    this.homeScroll();
    this.scheduleHl();
    if (this.previewOn) this.ensurePreview();
    // 双击一个**已经开着**的文件也会走到这儿吗？不会 —— 那种情况组件早就挂着了，
    // 光标由 `fmFocusActiveSoon()` 负责（和原来的行为一致）。
  },
  beforeUnmount(){
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
  },
  methods: {
    /* ---- 编辑器：输入 / 滚动 / 快捷键 ---- */
    /* 现在看得见哪几行（0 基，含端点）—— 行高从计算样式拿（`.editor > pre` 是
       `font:13px/1.55` ⇒ 20.15px；拿不到就退回 20）。 */
    hlWindow(){
      const ta = this.$refs.ta, pre = this.$refs.pre;
      if (!ta) return null;
      const cs = pre ? getComputedStyle(pre) : null;
      const lh = (cs && parseFloat(cs.lineHeight)) || 20;
      const first = Math.max(0, Math.floor((ta.scrollTop || 0) / lh));
      const last = first + Math.ceil((ta.clientHeight || 0) / lh) + 1;
      return {first: first, last: last};
    },
    /* 高亮层重画的**唯一**入口（输入、滚动、Tab 补空格、外面换了内容都走它）。
       ★ `V-272`：按**帧**合并 —— 一帧里改几次都只画一次；不再用 120ms 那个时间常数。 */
    scheduleHl(){
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = 0;
        this.paintHl();
      });
    },
    paintHl(){
      const code = this.$refs.code;
      if (!code) return;
      window.__hlWin = this.hlWindow();          // 探针的把手：这次用的是哪个窗口
      paintHl(this.t, code, window.__hlWin);
      this.paintGutter();                        // 行号跟高亮层一起重画
      // ★ `V-376`：画完再对一次滚动。第一次画会把 `code` 清空一次（`paintHl` 里建那三个
      //   节点那段），内容一空 `pre.scrollTop` 就被夹成 0；外面换了内容（AI 改盘上的文件、
      //   恢复快照 ⇒ `fmReloadPages`）也是这条。少了这一下，两层就永远差着那一段。
      this.syncScroll();
    },
    /* 左侧行号：行数 = 文本的行数（`wrap="off"` ⇒ 逻辑行 = 视觉行，1:1 对齐）。
       只在行数变了才重铺；铺完立刻跟 textarea 对一次滚动位置。 */
    paintGutter(){
      const g = this.$refs.gutter;
      if (!g) return;
      const text = this.t.text || "";
      const n = text.length ? text.split("\n").length : 1;
      if (this._gn !== n){
        this._gn = n;
        let s = "";
        for (let i = 1; i <= n; i++) s += i + "\n";
        g.textContent = s;
      }
      this.syncGutter();
    },
    /* 行号和输入层是两层，纵向滚动得手动同步（横向不动 —— 行号永远贴在左边） */
    syncGutter(){
      const g = this.$refs.gutter, ta = this.$refs.ta;
      if (g && ta) g.scrollTop = ta.scrollTop || 0;
    },
    /* ★ `V-376`：高亮层跟输入层对齐 —— 输入层 / 高亮层 / 行号槽是**同一次滚动的三个视图**，
       谁滚都得让另外两个跟上。
       ★ 藏在别的选项卡里时**不写**：`display:none` ⇒ `clientHeight = 0`，写进去会被浏览器
       夹成 0，等你切回来正好成了"光标在上面、字在下面"（`V-376` 那条）。 */
    syncScroll(){
      const ta = this.$refs.ta, pre = this.$refs.pre;
      if (!ta || !pre || !ta.clientHeight) return;
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft;
      this.syncGutter();
    },
    /* 光标回开头 + 三层一起回左上角（打开一个文件时用，见 `mounted`） */
    homeScroll(){
      const ta = this.$refs.ta;
      if (!ta) return;
      if (!ta.readOnly) ta.setSelectionRange(0, 0);
      ta.scrollTop = 0; ta.scrollLeft = 0;
      this.syncScroll();
    },
    /* 跳到第 line 行：选中那一行、滚到中间，然后对齐三层视图 */
    jumpTo(line){
      const ta = this.$refs.ta;
      const lines = String(this.t.text || "").split("\n");
      const n = Math.max(1, Math.min(line | 0 || 1, lines.length));
      let off = 0;
      for (let i = 0; i < n - 1; i++) off += lines[i].length + 1;
      if (ta){
        if (!ta.readOnly){
          ta.setSelectionRange(off, off + (lines[n - 1] || "").length);
          ta.focus();
        }
        const cs = getComputedStyle(this.$refs.pre || ta);
        const lh = (cs && parseFloat(cs.lineHeight)) || 20;
        ta.scrollTop = Math.max(0, (n - 1) * lh - (ta.clientHeight || 0) / 2 + lh / 2);
        ta.scrollLeft = 0;
      }
      this.syncScroll();
      this.scheduleHl();
    },
    onInput(ev){
      this.t.text = ev.target.value;
      this.scheduleHl();
    },
    onScroll(){
      // 三层（输入层 / 高亮层 / 行号槽）是同一次滚动的三个视图，立刻对齐，别等下一帧
      this.syncScroll();
      // ★ `V-272`：窗口只画了"视口 ± 60 行" —— 滚出去了得把那几行补上色（按帧合并）
      this.scheduleHl();
    },
    onKeydown(ev){
      const ta = this.$refs.ta;
      if (ev.key === "Tab"){
        ev.preventDefault();
        const p = ta.selectionStart;
        ta.value = ta.value.slice(0, p) + "    " + ta.value.slice(ta.selectionEnd);
        ta.selectionStart = ta.selectionEnd = p + 4;
        this.t.text = ta.value; this.paintHl();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s"){
        ev.preventDefault(); fmSave(this.t);
      }
    },
    /* ---- 浏览 / 代码切换 ---- */
    async ensurePreview(){
      const t = this.t;
      if (!t || !this.canPreview || t.previewBase || t._pvLoading) return;
      t._pvLoading = true;
      try{
        const got = await pywebview.api.fs_preview_url(t.rel);
        if (got && got.ok){ t.previewBase = got.base || ""; }
        else if (got && got.msg){ toast("预览资源加载不了：" + got.msg, true); }
      }catch(e){ toast("预览资源加载不了：" + (e && e.message ? e.message : e), true); }
      finally { t._pvLoading = false; }
    },
    togglePreview(){
      this.t.preview = !this.t.preview;
      if (this.t.preview) this.ensurePreview();
      fmRender();
      // 从浏览切回代码时编辑器刚从 `v-show=false` 恢复，量得到高度之后要补画一次高亮 / 滚动。
      this.$nextTick(() => this.scheduleHl());
    },
    /* ---- 标题栏那三颗 + 关闭 ---- */
    save(){ fmSave(this.t); },
    revert(){
      const t = this.t;
      askConfirm("放弃改动", "“" + t.name + "” 重新从磁盘读一遍，没保存的改动会丢。确定吗？", async () => {
        const r = await pywebview.api.fs_read(t.rel);
        if (!r.ok){ toast("✗ " + r.msg, true); return; }
        t.text = r.text || ""; t.original = r.text || "";
        // textarea 的 value 由 `:value="t.text"` 在下一帧补上；高亮层得自己补
        this.$nextTick(() => this.scheduleHl());
      });
    },
    openDefault(){
      pywebview.api.fs_open_default(this.t.rel).then(r => toast(r.msg, !r.ok));
    },
    reveal(){
      pywebview.api.fs_reveal(this.t.rel).then(r => toast(r.msg, !r.ok));
    },
    close(){ fmClosePage(this.t.rel); },
  },
};

const MossFileBrowse = {
  name: "moss-file-browse",
  props: {
    s: {type: Object, required: true},
    active: {type: Boolean, default: false},
  },
  template: `
<div class="fmpage" :class="{on: active}" data-page="__browse__">
  <div class="fbnav">
    <!-- ★「回到默认目录」放在这一排的**最左边** —— 它是个"导航"动作，和 ⬅ ➡ ⬆ ⟳ 同类 -->
    <button class="iconbtn b-home" :title="homeTitle" v-html='ico("home", "i")'
            @click="fmHome()"></button>
    <button class="iconbtn b-back" title="后退" :disabled="s.hpos <= 0"
            v-html='ico("corner-up-left", "i")' @click="fmBack()"></button>
    <button class="iconbtn b-fwd" title="前进" :disabled="s.hpos >= s.hist.length - 1"
            v-html='ico("corner-up-right", "i")' @click="fmFwd()"></button>
    <button class="iconbtn b-up" title="向上一级（Backspace）" :disabled="atTop"
            v-html='ico("arrow-up", "i")' @click="fmUp()"></button>
    <button class="iconbtn b-reload" title="刷新（F5）" v-html='ico("refresh-cw", "i")'
            @click="fmRefresh()"></button>
    <!-- 按内容搜当前目录（Ctrl+F） -->
    <button class="iconbtn b-search" :class="{on: st.on}"
            title="按内容搜当前目录（Ctrl+F）"
            v-html='ico("search", "i")' @click="fmSearchOpen()"></button>
    <!-- 面包屑。★ abs/ 那个上下文里第一段是相对写法，**不是**能点进去的目录
         （abs 本身不是路径），所以它只当个标签："此电脑"。 -->
    <div class="crumbs"><template v-for="(c, i) in crumbs" :key="i"
      ><span v-if="i" class="sep">›</span
      ><span v-if="c.here" class="here">{{ c.label }}</span
      ><span v-else class="seg" :data-rel="c.rel" @click="fmGoto(c.rel)">{{ c.label }}</span
    ></template></div>
    <div class="layers">
      <span v-if="s.histCtx" class="hint"
            style="align-self:center;margin-top:0;white-space:nowrap"
            >历史调用所在的目录{{ hereLayer === "abs" ? "（在 user_data / system 之外）" : "" }}</span>
      <template v-else-if="!s.pkg">
        <button class="iconbtn" :class="{on: hereLayer === 'user'}" data-go="user"
                title="user_data 根目录" @click="fmGoto('user')">user_data</button>
        <button class="iconbtn" :class="{on: hereLayer === 'system'}" data-go="system"
                title="system 根目录" @click="fmGoto('system')">system</button>
      </template>
      <template v-else>
        <button v-if="s.layers.user" class="iconbtn" :class="{on: hereLayer === 'user'}"
                :data-go="cand.user"
                :title="'user_data 里这个包的目录（' + cand.user + '）'"
                @click="fmGoto(cand.user)">user_data</button>
        <button v-if="s.layers.system" class="iconbtn" :class="{on: hereLayer === 'system'}"
                :data-go="cand.system"
                :title="'system 里这个包的目录（' + cand.system + '）'"
                @click="fmGoto(cand.system)">system</button>
        <span v-if="!s.layers.user && !s.layers.system" class="hint"
              style="align-self:center;margin-top:0;white-space:nowrap">这个包只在当前目录里</span>
      </template>
    </div>
  </div>

  <!-- 按内容搜当前目录：左边是范围，回车开始 -->
  <div class="fbsearch" v-if="st.on">
    <span class="fbs-scope" title="搜这个目录和它的子目录">
      <span class="ic" v-html='ico("folder-search", "i")'></span
      ><span class="p">{{ s.rel || "user" }}</span>
    </span>
    <input class="fbs-q" v-model="st.q" spellcheck="false" autocomplete="off"
           placeholder="按内容搜…（回车开始）"
           @keydown.enter.prevent="runSearch" @keydown.esc.prevent="fmSearchClose()">
    <button class="fbs-t" :class="{on: st.cs}" title="区分大小写" @click="toggleOpt('cs')">Aa</button>
    <button class="fbs-t" :class="{on: st.word}" :disabled="st.re"
            title="全词匹配（不匹配词中间那一段）" @click="toggleOpt('word')">全词</button>
    <button class="fbs-t" :class="{on: st.re}" title="按正则表达式搜" @click="toggleOpt('re')">.*</button>
    <button class="fbs-go" :disabled="st.busy" @click="runSearch">{{ st.busy ? "搜索中…" : "搜索" }}</button>
    <button class="iconbtn b-search-x" title="关掉检索（Esc）" v-html='ico("x", "i")'
            @click="fmSearchClose()"></button>
  </div>

  <div class="fbtools">
    <button class="iconbtn b-newdir" title="新建文件夹" v-html='ico("folder-plus", "i")'
            @click="fmCmd('newdir')"></button>
    <button class="iconbtn b-newfile" title="新建文件" v-html='ico("file-plus", "i")'
            @click="fmCmd('newfile')"></button>
    <button class="iconbtn b-rename" title="重命名（F2）" :disabled="selN !== 1"
            v-html='ico("pencil", "i")' @click="fmCmd('rename')"></button>
    <button class="iconbtn warn b-del" title="删除（Delete）→ 挪进回收站" :disabled="!selN"
            v-html='ico("trash-2", "i")' @click="fmCmd('del')"></button>
    <span class="gap"></span>
    <button class="iconbtn b-copy" title="复制（Ctrl+C）" :disabled="!selN"
            v-html='ico("copy", "i")' @click="fmCmd('copy')"></button>
    <button class="iconbtn b-cut" title="剪切（Ctrl+X）" :disabled="!selN"
            v-html='ico("scissors", "i")' @click="fmCmd('cut')"></button>
    <button class="iconbtn b-paste" title="粘贴（Ctrl+V）" :disabled="!s.clip"
            v-html='ico("clipboard-paste", "i")' @click="fmCmd('paste')"></button>
    <span class="gap"></span>
    <button class="iconbtn b-default" title="用默认程序打开选中的东西" :disabled="!selN"
            v-html='ico("external-link", "i")' @click="fmCmd('default')"></button>
    <button class="iconbtn b-opendir" title="用 Windows 资源管理器打开这个文件夹"
            v-html='ico("folder-open", "i")' @click="fmCmd('opendir')"></button>
  </div>

  <div class="fbwrap" @contextmenu="wrapCtx">
    <table class="fb" v-if="!searchView"><thead><tr>
      <th data-sort="name" @click="sortBy('name')">名称<span v-if="s.sort.key === 'name'"
          class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="mtime" style="width:150px" @click="sortBy('mtime')">修改日期<span
          v-if="s.sort.key === 'mtime'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="type" style="width:110px" @click="sortBy('type')">类型<span
          v-if="s.sort.key === 'type'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="size" style="width:100px" @click="sortBy('size')">大小<span
          v-if="s.sort.key === 'size'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
    </tr></thead><tbody>
      <tr v-if="!rows.length"><td colspan="4" class="dim"
          style="padding:22px;text-align:center">这个文件夹是空的</td></tr>
      <tr v-for="(e, idx) in rows" :key="e.rel" class="row"
          :class="[{sel: s.sel.has(e.rel)}, bkDiffRow(e.rel)]"
          :data-rel="e.rel" :data-dir="e.dir ? 1 : 0" :title="bkDiffWhy(e.rel)"
          @click="rowClick(e, idx, $event)" @dblclick="rowDbl(e)"
          @contextmenu="rowCtx(e, idx, $event)">
        <td class="nmcell" v-html="fileIconHTML(e, false) + '<span>' + esc(e.name) + '</span>'"></td>
        <td class="dim">{{ fmtTime(e.mtime) }}</td>
        <td class="dim">{{ typeLabel(e) }}</td>
        <td class="num">{{ e.dir ? "" : humanSize(e.size) }}<span
            class="df-mark">{{ bkDiffMark(e.rel) }}</span><button v-if="!e.dir && bkHasSnap(e.rel)"
            class="iconbtn cmpbtn" title="和快照里那一份对比（弹出来两栏看）"
            @click.stop="cmp(e)" v-html='ico("git-branch", "i")'></button></td>
      </tr>
    </tbody></table>

    <!-- 检索结果：按文件分组，点一行跳过去 -->
    <div class="fbres" v-else>
      <div class="fbres-empty bad" v-if="st.err">{{ st.err }}</div>
      <div class="fbres-empty" v-else-if="st.busy">搜索中…</div>
      <div class="fbres-empty" v-else-if="!st.files.length">没有找到 “{{ st.q }}”{{ st.note ? "　（" + st.note + "）" : "" }}</div>
      <template v-else>
        <div class="fbres-file" v-for="f in st.files" :key="f.rel">
          <div class="fbres-head" :title="f.rel" @click="toggleFile(f)">
            <span class="caret">{{ st.open[f.rel] ? "▾" : "▸" }}</span>
            <span class="fname" v-html="fileIconHTML({name: f.name, ext: f.ext}, false) + '<span>' + esc(f.name) + '</span>'"></span>
            <span class="fdir">{{ f.dir }}</span>
            <span class="fcount">{{ f.n }}{{ f.more ? "+" : "" }} 行</span>
          </div>
          <template v-if="st.open[f.rel]">
            <div class="fbres-hit" v-for="(h, i) in f.hits" :key="i"
                 :title="'打开并跳到第 ' + h.line + ' 行'" @click="jump(f, h)">
              <span class="ln">{{ h.line }}</span>
              <span class="tx" v-html="hitHTML(h)"></span>
            </div>
          </template>
        </div>
      </template>
      <div class="fbres-more" v-if="st.truncated">结果没搜完：{{ cutText }}。换个更具体的词，或者进到更里面那层目录再搜。</div>
    </div>
  </div>

  <div class="fbstatus"><span class="info">{{ searchView ? searchInfo : infoText }}</span
    ><span class="clipinfo">{{ clipText }}</span></div>
</div>`,
  computed: {
    // ★ `DATA`（包表）不是响应式的：读一下版本号登记依赖。目录名被"对齐目录名"改过
    //   之后，这两颗切换按钮要跳的目录也得跟着换（否则跳进一个不存在的目录）。
    pkgsRev(){ return FM.rev; },
    segs(){ return (this.s.rel || "").split("/"); },
    crumbs(){
      // 面包屑：逐段累加出 rel。第一段显示成人话（user → user_data…），
      // 而且**最后一段**（当前目录）和 `abs` 那一段是纯标签，不能点。
      let acc = "";
      return this.segs.map((seg, i) => {
        acc = i === 0 ? seg : acc + "/" + seg;
        const label = i === 0
          ? (seg === "user" ? "user_data" : (seg === "system" ? "system"
             : (seg === "abs" ? "此电脑" : seg)))
          : seg;
        return {label: label, rel: acc, here: (i === this.segs.length - 1) || (i === 0 && seg === "abs")};
      });
    },
    rows(){ return fmSorted(this.s); },
    hereLayer(){ return (this.s.rel || "").split("/")[0]; },
    homeTitle(){
      return isHistKey(FM.ctx) ? "回到这条调用当初的目录" : "回到默认目录（这个包的目录）";
    },
    // ★ 这一条和 `fmAtTop()` **不是**同一个判据：原来 `bindBrowse` 里先按 `fmAtTop(s.rel)`
    //   设过一次 disabled，紧接着（`V-67` 那份代码的第 631 行）又用 `segs.length <= 1`
    //   覆盖了它。后写的算数，所以这里照**结果**写。`V-69` 只搬结构，不顺手改行为。
    atTop(){ return this.segs.length <= 1; },
    selN(){ return this.s.sel.size; },
    /* 检索相关的三个 computed（模板里裸用） */
    st(){ return this.s.search || fmSearchFresh(); },
    searchView(){ return !!this.st.on && !!this.st.ran; },
    /* 哪些根被掐断了（写出来，否则"没搜到"会被当成"不存在"） */
    cutText(){
      const st = this.st;
      const nm = r => (r === "user" ? "user_data" : (r === "system" ? "system" : r));
      const one = "一次最多扫 " + (st.scanned || 0) + " 个文件、回 " + (st.nHits || 0) + " 行命中";
      const cut = (st.cut || []).map(nm);
      return cut.length ? (one + "；" + cut.join("、") + " 还没扫完") : one;
    },
    searchInfo(){
      const st = this.st;
      if (st.busy) return "搜索中…";
      if (st.err) return st.err;
      let t = st.nFiles + " 个文件里 " + st.nHits + " 行命中" +
              " · 扫了 " + st.scanned + " 个文件";
      if (st.skipped) t += "（跳过 " + st.skipped + " 个非文本 / 太大）";
      t += " · " + st.ms + " ms · 范围 " + (this.s.rel || "user");
      if (st.note) t += " · " + st.note;
      if (st.truncated) t += " · 有地方没扫完";
      return t;
    },
    cand(){
      void this.pkgsRev;                    // 见 `pkgsRev` 的注释
      return this.s.pkg ? fmLayerRels(this.s.pkg) : {user: "", system: ""};
    },
    infoText(){
      const s = this.s, rows = this.rows, n = s.sel.size;
      const bytes = rows.filter(e => s.sel.has(e.rel) && !e.dir)
                        .reduce((a, e) => a + (e.size || 0), 0);
      return rows.length + " 项" +
        (n ? " · 选中 " + n + " 项" + (bytes ? "（" + humanSize(bytes) + "）" : "") : "") +
        " · " + (s.path || s.rel);
    },
    clipText(){
      const c = this.s.clip;
      return c ? ("剪贴板：" + c.rels.length + " 项" + (c.cut ? "（剪切）" : "（复制）")) : "";
    },
  },
  methods: {
    /* ★ `V-94`：这两条是**给模板用的**（行上色 + hover 说明）。
       ★ 为什么还要在这儿转一手：这个 Vue 构建的模板是"带前缀"编译的（`_ctx.xxx`），
         **看不见**脚本里的全局函数（`humanSize` 那几条也是这么递的，见下面 `data()`）——
         直接写 `bkDiffRow(e.rel)` 会得到 "bkDiffRow is not a function"（`pkg-file` 场景当场抓到）。 */
    bkDiffRow: rel => bkDiffRow(rel),
    bkDiffWhy: rel => bkDiffWhy(rel),
    bkDiffMark: rel => bkDiffMark(rel),
    bkHasSnap: rel => bkHasSnap(rel),
    cmp(e){ bkCompareOpen(e.rel); },
    /* 按内容搜：逻辑在 `fmSearch*`，这里只是给模板用 */
    runSearch(){ fmSearchRun(); },
    toggleOpt(k){ fmSearchOpt(k); },
    toggleFile(f){
      const st = this.st;
      st.open[f.rel] = !st.open[f.rel];
    },
    jump(f, h){ fmSearchJump(f.rel, h.line); },
    /* 一行命中 → 带 <mark> 的 HTML（按宿主给的 cols 切，别自己重新匹配） */
    hitHTML(h){
      const text = String(h.text || "");
      const cols = (h.cols || []).slice().sort((a, b) => a[0] - b[0]);
      let out = "", at = 0;
      cols.forEach(c => {
        const s0 = Math.max(0, c[0] | 0), len = Math.max(1, c[1] | 0);
        if (s0 < at || s0 > text.length) return;     // 压在一起的（重叠命中）跳过
        out += esc(text.slice(at, s0)) + "<mark>" + esc(text.slice(s0, s0 + len)) + "</mark>";
        at = s0 + len;
      });
      return out + esc(text.slice(at));
    },
    /* ---- 表头排序 ---- */
    sortBy(k){
      const s = this.s;
      s.sort = {key: k, dir: (s.sort.key === k ? -s.sort.dir : 1)};
    },
    /* ---- 选中：普通点击 / Ctrl 点 / Shift 点（和原来逐字一致）---- */
    rowClick(e, idx, ev){
      const s = this.s, rows = this.rows;
      if (ev.ctrlKey || ev.metaKey){
        s.sel.has(e.rel) ? s.sel.delete(e.rel) : s.sel.add(e.rel);
        s.lastIdx = idx;
      } else if (ev.shiftKey && s.lastIdx >= 0){
        const a = Math.min(s.lastIdx, idx), b = Math.max(s.lastIdx, idx);
        s.sel.clear();
        for (let i = a; i <= b; i++) s.sel.add(rows[i].rel);
      } else {
        s.sel.clear(); s.sel.add(e.rel); s.lastIdx = idx;
      }
    },
    rowDbl(e){ e.dir ? fmGoto(e.rel) : fmOpenPage(e.rel); },
    /* 右键：点在**没选中**的那一行上，先把选中换成它（和资源管理器一样）。 */
    rowCtx(e, idx, ev){
      ev.preventDefault();
      const s = this.s;
      if (!s.sel.has(e.rel)){
        s.sel.clear(); s.sel.add(e.rel); s.lastIdx = idx;
      }
      showCtx(ev.clientX, ev.clientY, e.rel);
    },
    /* 空白处的右键：清空选中，菜单是"新建 / 粘贴 / 刷新"那一套 */
    wrapCtx(ev){
      if (this.searchView) return;                 // 检索结果上不给文件操作菜单（不是文件列表）
      if (ev.target.closest("tr.row")) return;
      ev.preventDefault();
      this.s.sel.clear();
      showCtx(ev.clientX, ev.clientY, null);
    },
  },
};

const MossFileManager = {
  name: "moss-file-manager",
  // ★ 「版本快照」边栏（`MossFileSnap`）在 `js/backup.js` 里（那个文件在**本文件之后**
  //   加载）：这边模板里直接写 `<moss-file-snap>`，那边
  //   `MossFileManager.components.MossFileSnap = MossFileSnap` 把组件补进来。
  //   挂载是懒的（第一次 `fmRender()` 才挂），来得及。
  //   `V-91`：它从"另一个子选项卡"变成**右边一条边栏** —— 快照天生是"这个目录的这些版本"，
  //   贴着文件列表放最直观，而且边栏只看**当前选中对象**的快照，"分组"下拉就不需要了。
  components: {MossFileBrowse: MossFileBrowse, MossFilePage: MossFilePage},
  template: `
<div class="fm-main">
  <div id="fm-bar">
    <button class="fmtab" :class="{on: s.active === '__browse__'}" data-fm="__browse__"
            title="目录浏览（这一页不能关）" @click="s.active = '__browse__'">
      <span v-html='ico("folder", "i")'></span><span class="fname">{{ tabLabel }}</span>
    </button>
    <button v-for="t in s.tabs" :key="t.rel" class="fmtab" :class="{on: s.active === t.rel}"
            :data-fm="t.rel" :title="t.rel" @click="s.active = t.rel">
      <span :style="'color:' + tabIcon(t).c + ';display:flex'" v-html='ico(tabIcon(t).i, "i")'></span>
      <span class="fname">{{ t.name }}</span>
      <span v-if="isDirty(t)" class="fdot" title="有未保存的改动"></span>
      <span class="x" :data-close="t.rel" title="关闭" @click.stop="fmClosePage(t.rel)">×</span>
    </button>
  </div>
  <div class="fmwrap" id="fm-body">
    <moss-file-browse :s="s" :active="s.active === '__browse__'"></moss-file-browse>
    <moss-file-page v-for="t in s.tabs" :key="t.rel" :t="t"
                    :active="s.active === t.rel"></moss-file-page>
  </div>
</div>
<moss-file-snap></moss-file-snap>`,
  computed: {
    s(){ return FM.st[FM.ctx || "__all__"] || fmState(FM.ctx); },
    tabLabel(){
      void FM.rev;              // 包表换了要重算（见 `FM.rev` 的注释）
      return fmLabel(FM.ctx);
    },
  },
  methods: {
    tabIcon(t){
      return extOf({name: t.name, ext: (t.name.split(".").pop() || "").toLowerCase()});
    },
  },
};

/* 模板里要用的那些全局函数（`ico` / `esc` / `fmGoto` …）。
   ★ 为什么显式登记：Vue 的运行时编译器是 `with(this)` 那套，模板里的标识符本来
     也能落到全局作用域去 —— 但那是"能跑就行"的隐式行为；登记一遍，谁都看得见
     这个函数是从哪来的（也免得以后换构建模式就悄悄失效）。 */
const FM_TEMPLATE_HELPERS = {
  ico: ico, esc: esc, isDirty: isDirty,
  fileIconHTML: fileIconHTML, fmtTime: fmtTime, typeLabel: typeLabel, humanSize: humanSize,
  fmGoto: fmGoto, fmHome: fmHome, fmBack: fmBack, fmFwd: fmFwd, fmUp: fmUp,
  fmRefresh: fmRefresh, fmCmd: fmCmd, fmClosePage: fmClosePage,
  fmSearchOpen: fmSearchOpen, fmSearchClose: fmSearchClose,
};

/* ---- 挂载 + 外面认的那两个"重画"门面 ----
   `fmRender()` / `fmPaintBar()` 原来真的是把 DOM 重画一遍；现在界面是响应式的，
   它俩只剩两件事：① 第一次调用把组件挂到 `#pane-file` 上；
   ② 兜底 `$forceUpdate()`（包表/历史不是响应式，`refreshPkgs()` 这类地方
   照旧喊一声"重画"，跟拆分之前的分工一样）。
   ★ 挂载点是 `#pane-file`：模板的根是**两个**兄弟节点（`#fm-bar` + `#fm-body`），
     Vue 3 允许（fragment 根），挂上去之后 index.html 里那两个占位 div 会被换掉。 */
let _fmApp = null;

function fmApp(){
  if (!_fmApp){
    const host = document.getElementById("pane-file");
    if (!host) return null;
    // ★ 走 `mountVue()`（`V-81`）：它顺手挂 `app.config.errorHandler` —— `V-69` 那版是
    //   裸 `Vue.createApp`，组件里一抛异常只会进控制台，这个界面没有控制台。
    _fmApp = mountVue(MossFileManager, host, FM_TEMPLATE_HELPERS);
  }
  return _fmApp;
}
function fmRender(){ const a = fmApp(); if (a) a.$forceUpdate(); }
function fmPaintBar(){ const a = fmApp(); if (a) a.$forceUpdate(); }

/* 把光标放进当前那一页的编辑器里（`fmOpenPage` 打开文件时用）。
   ★ 原来是在 `pageOf(rel).querySelector("textarea")` 上同步 focus；现在 DOM 由 Vue
     在下一帧画出来，所以走 `$nextTick`。判据照旧：二进制那页（textarea readonly）不抢焦点。 */
function fmFocusActiveSoon(){
  const go = () => {
    const page = document.querySelector("#fm-body .fmpage.on");
    const ta = page && page.querySelector("textarea");
    if (ta && !ta.readOnly) ta.focus();
  };
  const a = fmApp();
  if (a) a.$nextTick(go); else go();
}

/* ---- 文件操作（浏览页的按钮 / 右键菜单 / 键盘）---- */
function showCtx(x, y, rel){
  const s = fmState(FM.ctx);
  const has = !!rel, one = s.sel.size === 1;
  const items = has
    ? [["folder-open", "打开", "open"],
       ["external-link", "用默认程序打开", "default"],
       ["app-window", "在资源管理器里显示", "reveal"],
       ["sep"],
       ["copy", "复制", "copy"], ["scissors", "剪切", "cut"],
       ["sep"],
       ["pencil", "重命名", "rename", one],
       ["trash-2", "删除（进回收站）", "del"]]
    : [["file-plus", "新建文件", "newfile"], ["folder-plus", "新建文件夹", "newdir"],
       ["sep"], ["clipboard-paste", "粘贴", "paste", !!s.clip],
       ["refresh-cw", "刷新", "reload"]];
  const menu = $("#ctxmenu");
  menu.innerHTML = items.map(it => {
    if (it[0] === "sep") return '<div class="sep"></div>';
    const dis = it[3] === false;
    return '<div class="mi' + (dis ? " dis" : "") + '" data-act="' + it[2] + '">' +
      ico(it[0], "i") + '<span>' + esc(it[1]) + '</span></div>';
  }).join("");
  menu.hidden = false;
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.min(x, window.innerWidth - w - 8) + "px";
  menu.style.top = Math.min(y, window.innerHeight - h - 8) + "px";
  menu.querySelectorAll(".mi").forEach(mi => {
    if (mi.classList.contains("dis")) return;
    mi.onclick = () => { hideCtx(); fmCmd(mi.dataset.act); };
  });
}
function hideCtx(){ $("#ctxmenu").hidden = true; }

function fmTargetDir(){
  const s = fmState(FM.ctx);
  const selArr = [...s.sel];
  if (selArr.length === 1){
    const e = s.entries.find(x => x.rel === selArr[0]);
    if (e && e.dir) return e.rel;
  }
  return s.rel;
}
async function fmCmd(act){
  const s = fmState(FM.ctx);
  const selArr = [...s.sel];
  if (act === "open"){
    if (selArr.length === 1){
      const e = s.entries.find(x => x.rel === selArr[0]);
      if (e && e.dir) fmGoto(e.rel); else if (e) fmOpenPage(e.rel);
    }
    return;
  }
  if (act === "default" || act === "reveal"){
    if (!selArr.length) return;
    const r = act === "default" ? await pywebview.api.fs_open_default(selArr[0])
                                : await pywebview.api.fs_reveal(selArr[0]);
    toast(r.msg, !r.ok);
    return;
  }
  if (act === "opendir"){
    // 对目录调 startfile 就是"用 Windows 资源管理器打开它"
    const r = await pywebview.api.fs_open_default(s.rel);
    toast(r.msg, !r.ok);
    return;
  }
  if (act === "copy" || act === "cut"){
    if (!selArr.length) return;
    s.clip = {rels: selArr, cut: act === "cut"};
    fmRender();
    toast((act === "cut" ? "已剪切 " : "已复制 ") + selArr.length + " 项");
    return;
  }
  if (act === "paste"){
    if (!s.clip) return;
    const r = await pywebview.api.fs_copy(s.clip.rels, s.rel, s.clip.cut);
    toast(r.msg, !r.ok);
    if (r.ok && s.clip.cut) s.clip = null;
    fmRefresh();
    if (r.ok && (r.made || []).some(isPkgManifest)) refreshPkgs();   // 搬进/搬出了一个包
    return;
  }
  if (act === "newfile" || act === "newdir"){
    const dir = fmTargetDir(), isDir = act === "newdir";
    askText(isDir ? "新建文件夹" : "新建文件", isDir ? "新建文件夹" : "untitled.py", async (name) => {
      const r = isDir ? await pywebview.api.fs_mkdir(dir, name)
                      : await pywebview.api.fs_touch(dir, name);
      toast(r.msg, !r.ok);
      if (r.ok){
        if (dir !== s.rel) await fmGoto(dir, true); else await fmRefresh();
        const s2 = fmState(FM.ctx);
        s2.sel.clear(); s2.sel.add(r.rel);
        if (!isDir) fmOpenPage(r.rel); else fmRender();
        if (isPkgManifest(r.rel)) refreshPkgs();     // 新建了一个清单 ⇒ 这是新包
      }
    });
    return;
  }
  if (act === "rename"){
    if (selArr.length !== 1){ toast("重命名一次只能一个", true); return; }
    const e = s.entries.find(x => x.rel === selArr[0]);
    askText("重命名", e ? e.name : "", async (name) => {
      const r = await pywebview.api.fs_rename(selArr[0], name);
      toast(r.msg, !r.ok);
      if (r.ok){
        const s2 = fmState(FM.ctx);
        const t = s2.tabs.find(x => x.rel === r.old);
        if (t){ t.rel = r.rel; t.name = r.rel.split("/").pop(); }
        s2.sel.clear(); s2.sel.add(r.rel);
        fmRefresh();
        if (isPkgManifest(r.old) || isPkgManifest(r.rel)) refreshPkgs();
      }
    });
    return;
  }
  if (act === "del"){
    if (!selArr.length) return;
    const names = s.entries.filter(e => s.sel.has(e.rel)).map(e => e.name);
    askConfirm("删除", "把 " + (names.length === 1 ? "“" + names[0] + "”" : names.length + " 项") +
      " 挪进 user_data/trash/（<b>不是永久删除</b>，能拿回来）。确定吗？", async () => {
        const r = await pywebview.api.fs_delete(selArr);
        toast(r.msg, !r.ok);
        if (r.ok){
          const s2 = fmState(FM.ctx);
          s2.tabs = s2.tabs.filter(t => !selArr.some(x => t.rel === x || t.rel.startsWith(x + "/")));
          if (!s2.tabs.some(t => t.rel === s2.active)) s2.active = "__browse__";
          s2.sel.clear();
          fmRefresh();
          if (selArr.some(isPkgManifest)) refreshPkgs();
        }
      });
    return;
  }
  if (act === "reload") fmRefresh();
}

/* ---- 键盘 ---- */
document.addEventListener("keydown", (e) => {
  if ($("#modal").classList.contains("on")) return;
  const typing = /^(INPUT|TEXTAREA)$/.test((e.target.tagName || "").toUpperCase());
  if (tab === "file" && !typing){
    const s = fmState(FM.ctx), k = e.key;
    if (k === "Enter"){ e.preventDefault(); fmCmd("open"); return; }
    if (k === "F2"){ e.preventDefault(); fmCmd("rename"); return; }
    if (k === "Delete"){ e.preventDefault(); fmCmd("del"); return; }
    if (k === "Backspace"){ e.preventDefault(); fmUp(); return; }
    if (k === "F5"){ e.preventDefault(); fmRefresh(); return; }
    // Ctrl+F：开检索条（Esc 关）
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "f"){
      e.preventDefault(); fmSearchOpen(true); return;
    }
    if (k === "Escape"){ hideCtx(); if (fmSearch().on) fmSearchOpen(false); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "c"){ e.preventDefault(); fmCmd("copy"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "x"){ e.preventDefault(); fmCmd("cut"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "v"){ e.preventDefault(); fmCmd("paste"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "w"){
      e.preventDefault();
      if (s.active !== "__browse__") fmClosePage(s.active);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "a"){
      e.preventDefault();
      s.entries.forEach(x => s.sel.add(x.rel));
      fmRender();
      return;
    }
  }
  if (e.key === "Escape" && $("#modal").classList.contains("on")) closeModal();
  // 「设置」面板也认 Esc（`V-60`）：确认框那条路在上面 —— 两个不会同时在
  // ★ 要判空（`V-188` 查出来的真报错）：`#settings` 是**设置组件挂载时**才建出来的
  //   （settings.js 的模板里有它，挂载前 getElementById 拿到的是 null）—— 没打开过设置
  //   就按 Esc，这里原来是 `null.classList` ⇒ 每次都在 `_ui_drop.log` 里留一条
  //   「Cannot read properties of null (reading 'classList')」。平时不显眼，拖东西时
  //   按 Esc 取消就会撞上（正好是用户最常见的动作），把后面的处理一起打断。
  const setBox = $("#settings");
  if (e.key === "Escape" && setBox && setBox.classList.contains("on")) closeSettings();
});
document.addEventListener("click", (e) => { if (!e.target.closest("#ctxmenu")) hideCtx(); });
window.addEventListener("blur", hideCtx);
