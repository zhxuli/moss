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
                  layers: {user:false, system:false}};
  }
  return FM.st[key];
}
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
  return p ? (p.name + "（:" + p.id + "）") : key;
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
function fmRefresh(){
  const s = fmState(FM.ctx);
  if (!s.rel) return;
  // 手动刷新时顺便重问一遍"另一层有没有这个包的目录"（比如刚复制过去）
  fmProbeLayers(FM.ctx).then(layers => { s.layers = layers; });
  fmGoto(s.rel, false);
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
    const meta = extOf({name: name, ext: (name.split(".").pop() || "").toLowerCase()});
    t = {rel: rel, name: name, lang: meta.l || "plaintext",
         text: r.text || "", original: r.text || "",
         binary: !!(r.binary || r.too_big),
         note: r.binary ? "binary" : (r.too_big ? r.msg : ""),
         // ★ 记下"读进来时是什么编码 / 有没有 BOM"，保存时原样带回去 ——
         //   不然打开一个 GBK / UTF-16 的 txt 改一个字，整个文件就被转成 UTF-8 了。
         encoding: r.encoding || "utf-8", bom: r.bom || "",
         encodingNote: r.encoding_note || "",
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
    toast(r.ok ? ("已保存 " + t.rel + (r.factory ? "（出厂件）" : "")) : ("✗ " + r.msg), !r.ok);
    if (!r.ok) return;
    // `t.original` 一改，两处黄点（子选项卡上那颗 / 编辑器标题栏那颗）和保存按钮的
    // 灰不灰，Vue 自己就跟着重算了 —— 原来这里要手工 `fmPaintBar()` / `fmPaintDirty()`。
    t.original = t.text; fmPaintBar();
    // 存的是**包清单** ⇒ 界面手里那份包数据已经过期了，重新解析一遍
    if (isPkgManifest(t.rel)) refreshPkgs(null, true).then(() => afterManifestSaved(t.rel, t.text));
  });
}

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
      if (!quiet) toast("这个包已经不在列表里了（pkg.json 被删掉或改坏了）", true);
    }
  }
  fmPaintBar();                  // 子选项卡上那个包名可能变了
  // 撤回快照这件事**不能静默**（`V-31` ✅）：宿主那边有话说（多半是某个包的
  // `pkg.json` 写坏了 / id 不合法），把它原话弹出来 —— 否则你看到的现象只是
  // "我新建的包怎么不出现"，真正的原因谁也看不见。
  const sr = fresh.stale_reason;
  if (sr && sr !== lastStaleReason){
    lastStaleReason = sr;
    toast("读包表失败，界面现在显示的是旧数据：" + sr, true);
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
async function afterManifestSaved(fileRel, text){
  if (DATA.stale_reason) return;                 // 包表本身没读回来，别乱下结论（上面弹过了）
  const dirRel = String(fileRel).replace(/\/[^/]+$/, "");   // `…/pkg.json` → 它所在的包目录
  const base = dirRel.split("/").pop() || "";
  const layer = dirRel.split("/")[0];            // user / system —— 目录得改回**同一层**里
  const p = DATA.packages.find(x => pkgRel(x) === dirRel);
  let why = "", newId = "";
  if (!p){
    try{ newId = String((JSON.parse(text) || {}).id || "").trim().toLowerCase(); }
    catch(e){ why = "pkg.json 不是合法 JSON（" + e.message + "）"; }
    if (!why && !ID_RE.test(newId))
      why = "id '" + newId + "' 不合法（只允许 " + ID_RE.source + "）";
    if (!why && DATA.packages.some(x => x.id === newId))
      why = "id '" + newId + "' 已经被别的包用了";
    if (!why) why = "清单读不出来（宿主没认这个包）";
    toast("✗ 宿主没收下这个包：" + why, true);
    return;
  }
  if (p.id === base) return;                    // 三把钥匙对得上，收工
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
  if (moveData){
    const base = String(dirRel).split("/").pop();
    const rr = await pywebview.api.fs_rename("user/state/" + base, p.id);
    toast(rr.ok ? ("旧数据已搬到 state/" + p.id)
                : ("⚠ 目录名改好了，但旧数据没搬成：" + rr.msg), !rr.ok);
  }
  toast("已统一：包目录名 → " + p.id);
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
function hlInto(t, code){
  const text = t.text || "";
  if (text.length > 300000){ code.textContent = text + "\n"; return; }
  if (window.hljs && t.lang && hljs.getLanguage(t.lang)){
    try{
      code.innerHTML = hljs.highlight(text, {language: t.lang, ignoreIllegals: true}).value + "\n";
      return;
    }catch(e){}
  }
  code.textContent = text + "\n";
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
  <div class="editor">
    <pre aria-hidden="true" ref="pre"><code class="hljs" ref="code"></code></pre>
    <textarea spellcheck="false" wrap="off" ref="ta" :readonly="!!t.binary"
              :value="t.text" @input="onInput" @scroll="onScroll"
              @keydown="onKeydown"></textarea>
  </div>
</div>`,
  data(){
    return {_hlTimer: null};       // 输入停下 120ms 再高亮（原来那套防抖，一个字没改）
  },
  computed: {
    // 后缀 → 图标 / 颜色 / 语言（`core.js` 的 `EXT` / `NO_EXT`，只有一份）
    meta(){ return extOf({name: this.t.name, ext: (this.t.name.split(".").pop() || "").toLowerCase()}); },
    dirty(){ return isDirty(this.t); },
    note(){
      if (this.t.binary) return ico("binary", "i") + " 二进制文件，编辑不了；要看就用「默认程序打开」";
      if (this.t.note) return ico("alert-triangle", "i") + " " + this.t.note;
      if (this.t.factory) return ico("alert-triangle", "i") +
          " 这是出厂件（system/）—— 能改，但将来升级时会被整体替换";
      return "";
    },
  },
  mounted(){
    // 组件刚挂上时 `t.text` 还没进过 textarea 的高亮层，画一遍
    hlInto(this.t, this.$refs.code);
    // 双击一个**已经开着**的文件也会走到这儿吗？不会 —— 那种情况组件早就挂着了，
    // 光标由 `fmFocusActiveSoon()` 负责（和原来的行为一致）。
  },
  beforeUnmount(){ clearTimeout(this._hlTimer); },
  methods: {
    /* ---- 编辑器：输入 / 滚动 / 快捷键 ---- */
    onInput(ev){
      this.t.text = ev.target.value;
      clearTimeout(this._hlTimer);
      this._hlTimer = setTimeout(() => {
        if (this.$refs.code) hlInto(this.t, this.$refs.code);
      }, 120);
    },
    onScroll(){
      // 高亮层和输入层是**两张叠在一起的层**，滚动得手动同步（原来也这样）
      const pre = this.$refs.pre, ta = this.$refs.ta;
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft;
    },
    onKeydown(ev){
      const ta = this.$refs.ta;
      if (ev.key === "Tab"){
        ev.preventDefault();
        const p = ta.selectionStart;
        ta.value = ta.value.slice(0, p) + "    " + ta.value.slice(ta.selectionEnd);
        ta.selectionStart = ta.selectionEnd = p + 4;
        this.t.text = ta.value; hlInto(this.t, this.$refs.code);
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s"){
        ev.preventDefault(); fmSave(this.t);
      }
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
        this.$nextTick(() => { if (this.$refs.code) hlInto(t, this.$refs.code); });
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
    <table class="fb"><thead><tr>
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
        <td class="num">{{ e.dir ? "" : humanSize(e.size) }}</td>
      </tr>
    </tbody></table>
  </div>

  <div class="fbstatus"><span class="info">{{ infoText }}</span
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
    if (k === "Escape"){ hideCtx(); return; }
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
  if (e.key === "Escape" && $("#settings").classList.contains("on")) closeSettings();
});
document.addEventListener("click", (e) => { if (!e.target.closest("#ctxmenu")) hideCtx(); });
window.addEventListener("blur", hideCtx);
