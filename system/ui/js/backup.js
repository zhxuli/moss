/* moss 界面 · js/backup.js —— 「**版本快照**」边栏（`V-87` 备份 / `V-91` 并进文件管理）。
   ============================================================================
   一句话：**给当前这个对象（包 / 目录）留版本**，像 Time Machine 那样挂在文件管理右边。
   底下是"简易版 git"：快照里只记**指纹**（路径 → 指纹），文件内容按指纹存一份，
   所以同一个内容（换了名字、换了目录、跨好几次快照）只占一份。
   落盘按**包 id 分组**：`user_data/backups/<包id>/{objects/,<快照id>/manifest.json}`
   —— 改个 id 就改一个文件夹名、删个包就删一个文件夹。

   ★ 为什么是**边栏**而不是另一个选项卡（`V-91`，你的稿子）：快照天生是"这个目录的这些
     版本"，贴着文件列表放，语义不用解释；而且边栏只显示**当前选中对象**的快照，
     原来那个"分组下拉框"就不需要了（换对象 = 换一组快照）。
   ★ 逻辑全在宿主侧：`system/ui/backup.py`（内容寻址 + 标记-清除回收）。
   ★ 界面规矩（`V-90`）：**按钮两三个字，说明进 hover**，页面上不留大段文字。
   ============================================================================ */

/* 这一页的状态（自己一份，和文件管理那份 `FM` 无关）。
   为什么不挂进 `FM.st[ctx]`：快照是**跨上下文**的东西（一次可以覆盖好几个目录），
   不像"当前目录 / 选中 / 打开的文件"那样跟着上下文走。 */
const BK = Vue.reactive({
  items: [], stat: {}, loading: false,
  sel: null, man: null,
  view: null,                          // {rel, fp, binary, text, size, truncated} 或 null
  filter: "", busy: "", checkRows: null,
  formOpen: false, title: "", note: "",
  collapsed: false,                    // 边栏收起（窄窗口时默认收）
  exportTo: "", exportBak: false, dropOver: false,   // 导出（`V-88`）
  fps: {}, fresh: {},                   // 现读磁盘：指纹 + 现大小 + 目录子树（`V-94`，不信界面缓存）
  leftOnly: 0,
  ig: null,                            // 过滤规则（`V-105`）
  igGroup: null,                       // 这个对象自己那份规则（`V-120`）
  folded: {},                          // 哪些快照的文件列表被收起了（`V-122`）
  presets: null,                       // 预设过滤规则 + 命中数（`V-121`）                            // 过滤规则（`V-105`）：文件在哪、现在生效哪些
});

/* ================================================================ 差异视图（`V-94`）
   你的要求（2026-09-30）：「下面的路径这里 请按照原本的文件 文件夹来展示 并且 时刻保持和左侧同步
   也就是说 左侧目录切换的时候 当前镜像如果也有这个目录 那么也显示对应的目录」「黑色表示内容一致
   有变化则高亮 如果是空文件 没内容 则灰色显示」「同样有内容的情况下 高亮 但是左边文件更大和更少
   使用同样一种高亮色 但是深浅不同 左侧的多 就左侧文字更深 右侧更浅 否则就反过来」「某一边缺失
   文件 0kb文件等 都需要不同的颜色」。

   ⇒ 这一块就是"**当前目录的左右对照**"：
       左边 = 文件管理里现在这个目录（真文件）
       右边 = 这个快照里**同一个目录**（时间轴选中的那一次）
     一条文件一个状态，两种颜色维度拼出来：
       · 一致            → 正常色（黑/白），不打扰
       · 两边都有、不一样 → **同一个琥珀色**，谁**大**谁的**文字更深**（左边大 = 左深右浅）
       · 只有快照里有     → 红（该警惕：可能是你删了/改名了）
       · 只有现在有       → 绿（后加进去的，一般无害）
       · 空文件（0 字节） → 灰（有这一格，但里面什么都没有）
   判定顺序也照你说的："更大/更少"先看**大小**（便宜、也就是你要的语义）；大小一样才去比指纹
   （`backup_fp` 现算，见 `system/ui/main.py`）。 */
function bkCurDir(){
  const s = FM.st[FM.ctx || "__all__"];
  return (s && s.rel) || "";
}
function bkNowEntries(){
  const s = FM.st[FM.ctx || "__all__"];
  return (s && s.entries) || [];
}
/* 快照里 rel 这一层有什么：文件直接用，目录按"子树字节数"合成一个（好跟现在这一层比大小）。 */
function bkSnapSlice(rel){
  const man = BK.man;
  if (!man) return null;
  const pfx = rel ? String(rel).replace(/\/+$/, "") + "/" : "";
  const dirs = {}, files = {};
  (man.files || []).forEach(e => {
    const r = String(e.rel || "");
    if (pfx && r.indexOf(pfx) !== 0) return;
    const rest = pfx ? r.slice(pfx.length) : r;
    if (!rest) return;
    const i = rest.indexOf("/");
    if (i >= 0){ const d = rest.slice(0, i); dirs[d] = (dirs[d] || 0) + (e.size || 0); }
    else files[rest] = e;
  });
  (man.empty_dirs || []).forEach(d => {
    const r = String(d || "");
    if (pfx && r.indexOf(pfx) !== 0) return;
    const rest = pfx ? r.slice(pfx.length) : r;
    if (rest && rest.indexOf("/") < 0 && dirs[rest] === undefined) dirs[rest] = 0;
  });
  return {dirs: dirs, files: files};
}
function bkStateWhy(st, name, deep){
  if (st === "diff") return "两边都有、内容不一样" + (deep === "now" ? "（现在这份更大）"
                        : deep === "snap" ? "（快照里那份更大）" : "（大小一样、内容不同）");
  if (st === "snap-only") return "快照里有、现在没了（被删了还是改名了？）";
  if (st === "now-only") return "现在有、快照里没有（后加进去的）";
  if (st === "empty") return "空文件（0 字节）";
  return "和快照里一样";
}
/* 算出这一层每一条的状态（左边=现在，右边=快照） */
function bkDiffModel(){
  const rel = bkCurDir();
  const now = bkNowEntries();
  const snap = bkSnapSlice(rel);
  const fps = BK.fps || {};
  const fr = BK.fresh || {};
  const freshSize = r => (fr.sizes && (r in fr.sizes)) ? fr.sizes[r] : null;
  const freshDir = r => (fr.dirs && (r in fr.dirs)) ? fr.dirs[r] : null;
  const mine = {};
  now.forEach(e => { mine[e.name] = e; });
  const names = now.map(e => e.name);
  if (snap){
    Object.keys(snap.files).forEach(n => { if (names.indexOf(n) < 0) names.push(n); });
    Object.keys(snap.dirs).forEach(n => { if (names.indexOf(n) < 0) names.push(n); });
  }
  const entries = names.map(n => {
    const nw = mine[n] || null;
    const sFile = snap ? snap.files[n] : null;
    const sDirSize = snap ? snap.dirs[n] : undefined;
    const inSnap = !!(sFile || sDirSize !== undefined);
    const nowDir = !!(nw && nw.dir);
    // ★ 现读磁盘优先（你在外面改了文件、界面那份缓存还是旧的 —— 拿缓存比就"该亮的不亮"）
    const nowSize = nw ? (nowDir ? freshDir(nw.rel) : (freshSize(nw.rel) !== null
                                                        ? freshSize(nw.rel) : (nw.size || 0)))
                       : null;
    const snapSize = sFile ? (sFile.size || 0) : (sDirSize !== undefined ? sDirSize : null);
    let st, deep = "", fp = "";
    if (nw && inSnap){
      if (sFile && !nowDir){
        const sfp = sFile.fp || "";
        const nfp = fps[nw.rel] || "";
        if (nowSize !== snapSize) { st = "diff"; deep = (nowSize > snapSize) ? "now" : "snap"; }
        else if (nfp && sfp && nfp !== sfp) { st = "diff"; }      // 大小一样、指纹不同
        else st = "same";
        fp = sfp;
      }else{
        // 目录：两边都有就是"一致"，只有**子树字节数两边都拿得到**时才比大小
        //（拿不到就当一致 —— 不能因为"算不出来"就把每个目录都标成变了）
        if (nowSize === null || snapSize === null) st = "same";
        else {
          st = (nowSize === snapSize) ? "same" : "diff";
          if (st === "diff") deep = (nowSize > snapSize) ? "now" : "snap";
        }
      }
    }
    else if (nw) st = "now-only";
    else st = "snap-only";
    if (st === "same" && !nowDir && nowSize === 0) st = "empty";
    return {
      name: n, dir: nowDir || (sDirSize !== undefined), rel: nw ? nw.rel : ((rel ? rel + "/" : "") + n),
      now: nw ? {size: nowSize, dir: nowDir} : null,
      snap: inSnap ? {size: snapSize, fp: fp} : null,
      size: sFile ? (sFile.size || 0) : 0, fp: fp,          // 给"看内容 / 只恢复这一个"用
      state: st, deep: deep, why: bkStateWhy(st, n, deep),
    };
  });
  entries.sort((a, b) => (a.dir === b.dir) ? a.name.localeCompare(b.name) : (a.dir ? -1 : 1));
  const byRel = {};
  entries.forEach(e => { byRel[e.rel] = e; });
  return {rel: rel, entries: entries, byRel: byRel, snapOk: !!snap};
}

/* 边栏看的是**当前这个对象**那一组快照：
     选了包  ⇒ 包 id 那一组（快照就存在 `user_data/backups/<包id>/`）
     没选包  ⇒ 整个 user_data（`@user`）——"全部文件"那个上下文
   后端按来源猜组是同一套规则（`backup.py` 的 `group_for_sources`）。 */
function bkGroupForCtx(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  // ★ `V-113`：**分组以宿主为准** —— 界面自己算的那套（包 id / @dir-… / @abs-…）只能当兜底，
  //   两边一旦算得不一样，就会出现你遇到的"提示存了 54 项、右边列表却是空的"。
  //   宿主那边是唯一真相（`backup_group_hint` → 存储的 `group_for_sources`），每次刷新前问一次。
  if (BK.group) return BK.group;
  return p ? p.id : bkHistGroup();
}
/* `V-112`：**历史那边原来是坏的** —— 界面只会算"包 id，否则 @user"，而存储的 `group_for_sources()`
   是按来源命名的（包 → id；整个 user/system → @user/@system；别的目录 → **@dir-<尾段> / @abs-<尾段>**）。
   于是历史里选一条：列表读 `@user`（空的），点 ＋ 存的时候 group 传空、存储自己算成 `@dir-xxx`
   ⇒ **存成功了但列表里看不见**，diff/restore 也摸不到。这里把存储那三条规则**照着实现一遍**（就三行）。 */
function bkHistGroup(){
  const rels = bkScopeRels().map(x => String(x || "").replace(/\\/g, "/"));
  for (const r of rels){
    const parts = r.split("/");
    if (parts.length >= 3 && (parts[1] === "pkgs" || parts[1] === "state")) return parts[2];
  }
  for (const r of rels){
    if (r === "user" || r === "system") return "@" + r;
  }
  if (rels.length){
    const first = rels[0].replace(/\/+$/, "");
    const tail = first.split("/").filter(Boolean).pop() || "misc";
    return (first.startsWith("abs/") ? "@abs-" : "@dir-") + tail.replace(/[^A-Za-z0-9_.@-]/g, "_");
  }
  return "@misc";
}
function bkCtxLabel(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  if (p) return p.name || p.id;
  if (isHistKey(key)) return "这条调用所在的目录";
  return "整个 user_data";
}
/* 快照的来源：当前对象是什么就备份什么 */
function bkScopeRels(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  if (p){
    const roots = [];
    const rel = pkgRel(p);
    if (rel) roots.push(rel);
    roots.push("user/state/" + p.id);
    return roots;
  }
  if (isHistKey(key)){
    const it = histByKey(key);
    const d = it && histDir(it);
    return d ? [d] : ["user"];
  }
  const s = FM.st[key];
  return (s && s.rel) ? [s.rel] : ["user"];
}
function bkShortFp(fp){ return String(fp || "").slice(0, 10); }
/* 看内容时的高亮：直接把 hljs 的结果塞进那个 <pre>（只读，不需要文件管理里那套
   "透明 textarea + 覆盖层"）；认不出语言或者太大就原样转义。 */
function bkHighlightHTML(text, lang){
  const t = String(text == null ? "" : text);
  if (window.hljs && lang && hljs.getLanguage(lang)){
    try{ return hljs.highlight(t, {language: lang, ignoreIllegals: true}).value; }catch(e){}
  }
  return esc(t);
}

const MossFileSnap = {
  name: "moss-file-snap",
  // ★ 模板里够不着模块级的 BK（Vue 模板只认实例上的东西）—— 显式交出去。
  data(){ return { BK: BK, BKD: BKD }; },   // ★ BKD（差异容器）是 core.js 里的 const，模板看不见它，得这样递进去
  computed: {
    ctxKey(){ void FM.rev; void FM.st; return (FM.ctx || "__all__") + "|" + bkScopeRels().join(","); },
    ctxLabel(){ void FM.rev; void FM.st; return bkCtxLabel(); },
    /* 盘上那个文件夹叫什么（= 分组名 = 包 id；没选包就是 `@user`）—— 和 `ctxLabel` 分开：
       一个是给你看的名字，一个是磁盘上的名字（`V-89`：改 id 就改文件夹名）。 */
    ctxGroup(){ void FM.rev; void FM.st; return bkGroupForCtx(); },
    /* 目录 / 选中的快照 / 这一层有几个东西 —— 任意一个变了就重算对照（`V-94`） */
    mirrorKey(){
      void FM.rev;
      const s = FM.st[FM.ctx || "__all__"];
      const es = (s && s.entries) || [];
      // ★ 键里必须带**每一条的名字 + 大小**（不能只数个数）：你在外面把文件改大了、回来按一下
      //   刷新，文件数没变、目录没变 —— 只数个数的话这个 watcher 根本不动，差异视图就一直是旧的
      //   （真机探针当场抓到：刷新完还是 same）。
      return bkCurDir() + "|" + (BK.sel || "") + "|" + es.length + "|" +
             es.map(e => e.name + ":" + (e.size || 0) + (e.dir ? "d" : "")).join(",") +
             "|" + ((s && s.stale) ? 1 : 0);
    },
    /* 过滤提示（`V-105`）：创建快照那一小块里那一行淡字 —— 你说的"不那么明显的位置提示" */
    igShort(){
      const g = BK.ig || {};
      if (!g.ok) return "snapshot.ignore";
      return g.name + (g.count ? ("（" + g.count + " 条）") : "（空）");
    },
    igTip(){
      const g = BK.ig || {};
      const builtin = (g.builtin || []).join(" / ");
      return "存快照时按这份规则过滤（写法同 .gitignore 的常用那几条）：\n" +
             (g.path || "user_data/snapshot.ignore") + "\n" +
             (g.count ? ("你的规则：\n" + (g.user || []).join("\n")) : "你的规则：还没有（点一下看怎么写）") +
             "\n内置（永远生效）：" + builtin +
             "\n写法：*.log 按名字 / build/ 只排目录 / user/pkgs/old/ 按路径 / !keep.log 反向保留";
    },
    /* 差异视图（`V-94`）：行 = 当前目录这一层的"左边（现在）+ 右边（快照）" */
    /* ★ 快照那一列**只列快照里真有的东西**："只有现在有"的那些（绿色）只出现在**左边**那张表里。
       你 2026-09-30 反馈的第一条就是它 —— 新建一个 `untitled.py`，快照里怎么也冒出来了。 */
    foldedNow(){ void BK.folded; return !!BK.folded[BK.sel || ""]; },
    mirrorRows(){
      void BKD.diff;
      if (this.foldedNow) return [];
      return ((BKD.diff && BKD.diff.entries) || []).filter(e => e.state !== "now-only");
    },
    mirrorPath(){
      void FM.rev;
      const rel = bkCurDir();
      return rel ? rel : "（根目录）";
    },
    mirrorTip(){
      return "跟着左边的文件管理走：左侧进哪个目录，这里就对照哪个目录\n" +
             "左边 = 现在的工作区（" + (bkCurDir() || "根目录") + "）\n" +
             "右边 = 这次快照里的同一个目录\n" +
             "颜色：一致=正常 · 两边都有但不一样=琥珀（谁大谁更深）· " +
             "只有快照里有=红 · 只有现在有=绿 · 空文件=灰";
    },
    mirrorCount(){
      void BKD.diff;
      const es = (BKD.diff && BKD.diff.entries) || [];
      const n = s => es.filter(e => e.state === s).length;
      const d = n("diff"), g = n("snap-only"), w = n("now-only");
      return es.length + " 项" + (d ? " · 变 " + d : "") + (g ? " · 缺 " + g : "") +
             (w ? " · 多 " + w : "");
    },
    mirrorCountTip(){
      void BKD.diff;
      const es = (BKD.diff && BKD.diff.entries) || [];
      const n = s => es.filter(e => e.state === s).length;
      return "一致 " + n("same") + " · 变了 " + n("diff") + " · 空文件 " + n("empty") +
             " · 只有快照里有 " + n("snap-only") + " · 只有现在有 " + n("now-only");
    },
    viewLang(){
      if (!BK.view || !BK.view.rel) return "";
      const ext = (String(BK.view.rel).split(".").pop() || "").toLowerCase();
      return ((EXT[ext] || {}).l) || "";
    },
    viewHTML(){
      if (!BK.view || BK.view.binary) return "";
      return bkHighlightHTML(BK.view.text, this.viewLang);
    },
    statLine(){
      const s = BK.stat || {};
      return (s.backups || 0) + " 次 · " + humanSize(s.store_bytes || 0) +
             (s.saved ? (" · 省 " + humanSize(s.saved)) : "");
    },
    statTip(){
      const s = BK.stat || {};
      return "这个对象的快照：" + (s.backups || 0) + " 次 · 文件 " + (s.files || 0) +
             " 个 · 内容块 " + (s.objects || 0) + " 个（占 " + humanSize(s.store_bytes) + "）" +
             (s.saved ? ("；去重省了 " + humanSize(s.saved)) : "");
    },
    scopeTip(){
      return "快照的来源：\n" + bkScopeRels().join("\n") +
             "\n（按这组来源算出来的分组就是 " + bkGroupForCtx() + "）";
    },
  },
  watch: {
    ctxKey(){ this.switchCtx(); },        // 换了对象 ⇒ 换一组快照
    mirrorKey(){ this.reloadMirror(); },  // 换了目录 / 换了选中的快照 ⇒ 重算对照
  },
  mounted(){
    this.refresh();
    this.loadIgnore();
    /* 边栏宽度能拖（`V-92`）：细线贴在根元素左边缘上，往右拖变窄、往左拖变宽。
       上限按窗口宽度算（最多占 60%），双击回到 320。 */
    bindColResize(this.$el.querySelector(".b-bkgrip"), this.$el, -1, 200,
                  () => Math.round((window.innerWidth || 1200) * 0.6), 320);
    /* 拖一个文件夹**到边栏上** = 把它设成"导出到"（`V-88` ✅）。
       ★ 为什么必须走钩子：拖进来的**真实路径**只有宿主知道（Chromium 不给页面 `File.path`），
         落地口在 `js/drop.js` 的 `window.__mossDrop` 里，这里只是插一脚。
       ★ 为什么先看 `BK.dropOver`：那个钩子是**全局**的（任何拖入都先问它），
         要是不加这道判断，"拖文件进来跑包"（`V-35`）就被边栏整个抢走了。 */
    window.__mossDropHook = (items) => {
      if (!BK.dropOver) return false;
      const it = (items || []).find(x => x && x.path && x.isDir !== false);
      if (!it) return false;
      BK.exportTo = String(it.path || "");
      BK.dropOver = false;
      toast("导出目标： " + BK.exportTo + " —— 点快照上的「导出」就用它");
      return true;
    };
  },
  unmounted(){
    if (window.__mossDropHook) window.__mossDropHook = null;
    BK.dropOver = false;
  },
  methods: {
    humanSize: n => humanSize(n),
    /* 差异视图（`V-94`）的渲染小工具 —— 侧栏这一列是"右边（快照）"，深浅和左边**反过来**：
       快照那份更大 ⇒ 这里更深。 */
    mirrorCls(e){
      if (e.state === "snap-only") return {"df-gone": true};
      if (e.state === "now-only") return {"df-new": true};
      if (e.state === "empty") return {"df-empty": true};
      if (e.state === "diff") return e.deep === "snap" ? {"df-chg": true, "df-deep": true}
                                                      : {"df-chg": true, "df-soft": true};
      return null;
    },
    mirrorSize(e){
      if (e.snap === null) return "—";
      if (e.dir) return humanSize(e.snap.size);
      return humanSize(e.snap.size);
    },
    mirrorSizeCls(e){
      if (e.snap === null) return {dim: true};
      return {dim: e.state === "empty"};
    },
    /* 读过滤规则（`V-105`）：进边栏时读一次，用户点那一行时再读一次（他可能刚编辑过文件） */
    async loadIgnore(){
      try{
        const r = await pywebview.api.backup_ignore();
        BK.ig = r || {ok: false};
      }catch(e){ BK.ig = {ok: false}; }
    },
    /* 点那行淡字：弹一个**说明**（不是编辑器 —— 在界面里改过滤规则是 `V-104 E` 那一条，还没做） */
    /* 收起/展开这个快照的文件列表（`V-122`）：卡片还在、只把行藏起来，方便一屏扫多次快照 */
    toggleFoldFiles(){
      const k = BK.sel || "";
      BK.folded = Object.assign({}, BK.folded, {[k]: !BK.folded[k]});
    },
    /* 创建快照 = 一个模态框（`V-122`）：标题/注释 + **常驻**规则框 + 预设点选 + 记住（只对这个对象） */
    async snapModalOpen(){
      const rels = bkScopeRels();
      const group = bkGroupForCtx();
      snapClose();
      const w = document.createElement("div");
      w.id = "snapwin";
      w.innerHTML =
        '<div class="snap-card">' +
          '<div class="snap-head"><b>创建快照</b><span class="sp"></span>' +
            '<button class="iconbtn snap-x" title="关掉（Esc）"></button></div>' +
          '<div class="snap-body">' +
            '<div class="snap-row"><span>标题</span><input id="snap-title" placeholder="可留空（留空就用时间）"></div>' +
            '<div class="snap-row"><span>注释</span><input id="snap-note" placeholder="这次改了什么"></div>' +
            '<div class="snap-sub">过滤规则 —— 这次要排掉的东西（下面是我们**发现的东西**，点一下加/去；也能自己改）</div>' +
            '<div class="snap-pres" id="snap-pres">读预设…</div>' +
            '<div class="snap-rules-top"><span class="snap-hint" id="snap-rt">规则（一行一条）</span>' +
              '<span class="sp"></span>' +
              '<button class="btn snap-fill" id="snap-fill" title="把上面命中的规则一次全写进来">' +
                '<span class="snap-ico"></span>一键填入</button>' +
              '<button class="btn" id="snap-clear" title="清空规则框">' +
                '<span class="snap-ico"></span>清空</button>' +
            '</div>' +
            '<textarea id="snap-rules" rows="7" spellcheck="false" placeholder="一行一条：*.log / build/ / !keep.log"></textarea>' +

            '<div class="snap-hint" id="snap-hint"></div>' +
          '</div>' +
          '<div class="snap-foot"><span class="sp"></span>' +
            '<button class="btn" id="snap-cancel">取消</button>' +
            '<button class="btn primary" id="snap-save">存快照</button></div>' +
        '</div>';
      document.body.appendChild(w);
      w.querySelector(".snap-x").innerHTML = ico("x", "i");
      w.querySelector(".snap-x").onclick = snapClose;
      w.querySelector("#snap-cancel").onclick = snapClose;
      w.addEventListener("click", ev => { if (ev.target === w) snapClose(); });
      w.tabIndex = -1;
      w.addEventListener("keydown", ev => { if (ev.key === "Escape") snapClose(); });
      w.focus();
      const rulesOf = () => String(w.querySelector("#snap-rules").value || "")
        .split("\n").map(x => x.trim()).filter(Boolean);
      w.querySelector("#snap-save").onclick = async () => {
        const btn = w.querySelector("#snap-save");
        const ex = rulesOf();
        btn.disabled = true; btn.textContent = "存…";
        try{
          BK.busy = "存快照…";
          const r = await pywebview.api.backup_create(rels, w.querySelector("#snap-title").value,
                                                       w.querySelector("#snap-note").value, "", ex);
          if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "失败"), true); btn.disabled = false; btn.textContent = "存快照"; return; }
          const st = r.stats || {};
          toast("快照已存：" + (st.files || 0) + " 项 · 新增 " + (st.new_objects || 0) + " 块"
                + (ex.length ? (" · 按 " + ex.length + " 条规则排掉一些") : ""));
          snapClose();
          await this.refresh();
          await this.open(r.id, r.group, false);
        }catch(e){ reportError("存快照失败", String((e && e.message) || e)); }
        finally{ BK.busy = ""; }
      };
      try{
        const h = await pywebview.api.backup_group_hint(rels);
        if (h && h.ok) w.querySelector("#snap-hint").textContent = "会存到分组：" + h.group;
      }catch(e){}
      try{
        // ★ `V-126`：**先用前端算**（当前这一层已经在内存里，即时出结果、不用问宿主）；
        //   这一层还没加载（比如范围不是正看着的目录）才回退问宿主。
        let list = snapPresetLocal();
        const gi = await pywebview.api.backup_group_ignore(group);
        if (!list){
          try{
            const pv = await pywebview.api.backup_presets(rels);
            list = (pv && pv.presets) || [];
          }catch(e){ list = []; }
        }
        const ta = w.querySelector("#snap-rules");
        // ★ `V-127`：**默认规则取上次的**（本对象记住的 + 上一次快照实际用的），不是每次从空开始。
        const base = [];
        [].concat((gi && gi.rules) || [], (gi && gi.last) || [], ta.value.split("\n")).forEach(x => {
          const v = String(x || "").trim();
          if (v && base.indexOf(v) < 0) base.push(v);
        });
        ta.value = base.join("\n");
        w.querySelector("#snap-hint").textContent +=
          (gi && gi.ok && gi.rules && gi.rules.length) ? ("　·　这个对象已记住 " + gi.rules.length + " 条") : "";
        const box = w.querySelector("#snap-pres");
        /* 新加进去的规则**插在最上面**（你说点了以后掉到下面很难受） */
        const addRules = (pats) => {
          const cur = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
          const add = (pats || []).filter(x => cur.indexOf(x) < 0);
          ta.value = add.concat(cur).join("\n");
        };
        const dropRules = (pats) => {
          const cur = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
          ta.value = cur.filter(x => (pats || []).indexOf(x) < 0).join("\n");
        };
        /* 命中的组里、**还没进规则框**的那些模式 —— 「一键填入」要写的就是这些；
           一个都没有 ⇒ 这颗按钮就没必要显示（`V-136`）。 */
        const pendingPats = () => {
          const cur = rulesOf();
          let out = [];
          hotL.forEach(p => {
            patsOf(p).forEach(x => { if (cur.indexOf(x) < 0 && out.indexOf(x) < 0) out.push(x); });
          });
          return out;
        };
        const fill = w.querySelector("#snap-fill"), clr = w.querySelector("#snap-clear");
        // ★ `V-136`：两颗按钮**按情况显示**（没东西可填就不显示「一键填入」；规则框空着就不显示「清空」）。
        //   做法：`syncBtns()` 先给个空实现，等预设加载完（下面）再赋真正的实现 + 立刻算一次；
        //   规则框打字、点 chip、点更多都会再算一次。
        let syncBtns = () => {};
        if (fill){
          fill.querySelector(".snap-ico").innerHTML = ico("check", "i");
          fill.onclick = (ev) => {
            ev.stopPropagation();
            const pats = pendingPats();
            if (!pats.length) return;                    // 没得填就什么都不做（按钮本来也该是藏着的）
            addRules(pats);
            syncBtns();
            toast("已填入 " + pats.length + " 条规则");
          };
        }
        if (clr){
          clr.querySelector(".snap-ico").innerHTML = ico("eraser", "i");
          clr.onclick = (ev) => { ev.stopPropagation(); ta.value = ""; ta.focus(); syncBtns(); };
        }
        /* `V-128`：一条预设该写哪些模式 —— 命中的组只写**命中的那些**；
           没命中的组（在「更多」里、用户主动点的）才写整组（那时无从"只写命中的"）。 */
        const patsOf = (p) => (p.hit > 0 && p.matched && p.matched.length) ? p.matched : (p.pat || []);
        const chip = (p) =>
          '<span class="snap-chip' + (p.hit ? " hot" : "") + '" data-id="' + esc(p.id) + '"' +
          ' title="' + esc(p.hit ? (p.why || "") : ("这次没匹配到（" + (p.why || "") + "）")) + '">' +
          esc(p.label) + (p.hit ? (' <b>' + p.hit + '</b>') : '') +
          ((p.sample && p.sample.length) ? ('<i>' + esc(String(p.sample[0]).split('/').pop()) + '</i>') : '') +
          '</span>';
        // ★ `V-123`（你点明的）：**默认只显示"匹配上的"** —— 这个目录里没有压缩包/数据库，
        //   那两条就不该出现（否则一排 0 看着莫名其妙）；没匹配到的折在「更多（N）」后面。
        // ★ `V-127`：已有规则（本对象记住的 + 上次实际用的）里出现过的模式，就不再当"新建议"推给你
        const cur0 = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
        const covered = (p) => p.pat.every(x => cur0.indexOf(x) >= 0);
        const hotL = list.filter(p => p.hit > 0 && !covered(p));
        const coldL = list.filter(p => p.hit <= 0 || covered(p));
        box.innerHTML =
          (hotL.length ? hotL.map(chip).join("")
                       : '<span class="snap-hint">这个目录里没匹配到常见规则</span>') +
          (coldL.length ? ('<span class="snap-more" id="snap-more" title="看全部预设（这些这次没匹配到）">更多（' + coldL.length + '）</span>') : "");
        syncBtns = () => {
          if (fill) fill.hidden = (pendingPats().length === 0);
          if (clr) clr.hidden = (String(ta.value || "").trim() === "");
        };
        syncBtns();
        ta.addEventListener("input", syncBtns);
        const more = box.querySelector("#snap-more");
        if (more) more.onclick = (ev) => {
          ev.stopPropagation();
          more.insertAdjacentHTML("beforebegin", coldL.map(chip).join(""));
          more.remove();
          syncBtns();
        };
        box.onclick = (ev) => {
          const c = ev.target.closest ? ev.target.closest(".snap-chip") : null;
          if (!c) return;
          const pr = list.find(x => x.id === c.dataset.id);
          if (!pr) return;
          const cur = rulesOf();
          const allIn = pr.pat.every(x => cur.indexOf(x) >= 0);
          const pp = patsOf(pr);
          if (allIn) dropRules(pp); else addRules(pp);
          c.classList.toggle("on", !allIn);
          syncBtns();
        };
      }catch(e){ w.querySelector("#snap-pres").textContent = "（读不到预设）"; }
    },
    async editIgnore(){
      await this.loadIgnore();
      const g = BK.ig || {};
      askText("快照的过滤规则（每行一条）", ((g.user || []).join("\n")) || "", async (v) => {
        const r = await pywebview.api.backup_ignore_save(String(v || ""));
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "存不下"), true); return; }
        await this.loadIgnore();
        notice("过滤规则已保存", "现在生效 <b>" + (r.count || 0) + "</b> 条（覆盖前留了一份 .bak）<br>下次存快照就按新规则。");
      }, {multiline: true});
    },
    async preview(){
      BK.busy = "试算…";
      try{
        const r = await pywebview.api.backup_preview(bkScopeRels());
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "算不出来"), true); return; }
        const ex = (r.exclude || []).slice(0, 6).join("<br>");
        notice("按现在的规则会这样存", "会存 <b>" + r.n_in + "</b> 个 · 排掉 <b>" + r.n_out + "</b> 个<br><br>" + (r.n_out ? ("排掉的：<br>" + esc(ex)) : ""));
      }catch(e){ reportError("试算失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },
    async showIgnore(){
      await this.loadIgnore();
      const g = BK.ig || {};
      const rules = (g.user && g.user.length)
        ? g.user.map(x => "<code>" + esc(x) + "</code>").join("、")
        : "（还没有规则，现在只按内置那几条排）";
      notice("快照的过滤规则",
        "存快照时，下面这些东西**不会被存进去**：<br><br>" +
        "你的规则文件：<b class=\"mono\">" + esc(g.path || "") + "</b><br>" +
        "现在生效： " + rules + "<br><br>" +
        "内置（永远生效，改不掉）：<span class=\"mono\">" +
        esc((g.builtin || []).join(" / ")) + "</span><br><br>" +
        "<b>兼容</b>（和 .gitignore 一个意思）：<br>" +
        "<code>*.log</code> 按名字 · <code>build/</code> 只排目录 · <code>?ache</code> 一个字符 · " +
        "<code>**/deep.txt</code> 任意层级 · <code>logs/**</code> 目录下全部 · " +
        "<code>/user/state/tmp</code> 从根锚定 · <code>user/pkgs/old/</code> 按路径 · " +
        "<code>!keep.log</code> 反向保留 · <code>[0-9]*.tmp</code> 字符集 · <code>#</code> 注释<br><br>" +
        "<b>不兼容</b>：子目录各自的 .gitignore 继承 / 转义（<code>\\#</code>、<code>\\!</code>）/ " +
        "大小写敏感（我们一律不区分）/ git 那条「被排掉的目录里不能再 <code>!</code> 放回来」（我们允许）。<br><br>" +
        "完整的清单也写在那个文件里（打开就是模板）。用记事本改完就生效 —— 下次存快照按新规则。",
        {tip: "在界面里直接改这个文件还没做（记在 V-104 E）"});
    },
    /* 重算"当前目录"的对照：先问一下现在这一层每个文件的指纹（大小不一样就不必问），
       再拼出模型。选中快照变化、目录切换、盘上变了都会走到这里。 */
    async reloadMirror(){
      const now = bkNowEntries();
      const files = now.filter(e => !e.dir);
      const subs = now.filter(e => e.dir);
      if (BK.sel){
        try{
          const r = await pywebview.api.backup_fp(files.map(e => e.rel), subs.map(e => e.rel));
          BK.fps = (r && r.fps) || {};
          BK.fresh = {sizes: (r && r.sizes) || {}, dirs: (r && r.dirs) || {}};
        }catch(e){ BK.fps = {}; BK.fresh = {}; }
      }else{
        BK.fps = {}; BK.fresh = {};
      }
      BKD.title = (BK.man && BK.man.title) || "";
      BKD.diff = bkDiffModel();
    },
    /* 收起 / 展开边栏（`V-91`，`V-92` 补一个坑）。
       ★ 收起时要**清掉拖出来的行内宽度**：`.mini{width:auto}` 是**类**，压不过行内样式
         （行内 > 类）—— 不清的话收起后它还是原来那么宽，旁边白留一条；展开时再还给你。 */
    toggleFold(){
      const el = this.$el;
      BK.collapsed = !BK.collapsed;
      if (!el) return;
      if (BK.collapsed){ this._w = el.style.width; el.style.width = ""; }
      else if (this._w){ el.style.width = this._w; }
    },
    fmtWhen(t){ return t ? fmtTime(t) : ""; },
    shortFp: bkShortFp,
    shortTime(t){
      // 时间轴上一格就那么宽：今天只给时分秒，别的给 月/日
      const s = String(t || "");
      const today = new Date().toISOString().slice(0, 10);
      return s.slice(0, 10) === today ? s.slice(11, 19) : s.slice(5, 16);
    },

    async refresh(){
      BK.loading = true;
      try{
        try{
          const h = await pywebview.api.backup_group_hint(bkScopeRels());
          if (h && h.ok && h.group) BK.group = h.group;
        }catch(e){ /* 宿主不给就退回本地那套规则 */ }
        const r = await pywebview.api.backup_list(bkGroupForCtx());
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "拿不到快照列表"), true); return; }
        BK.items = r.items || [];
        BK.stat = r.stat || {};
        if (BK.sel && !BK.items.some(x => x.id === BK.sel)){ BK.sel = null; BK.man = null; }
        // ★ `V-94`：边栏现在是"**和左边当前目录对照**"的一块，没有选中的快照就没得对照 ⇒
        //   进来就自动选中**最新那一次**（时间轴第一条）。点别的格子照旧换人。
        if (!BK.sel && BK.items.length){
          await this.open(BK.items[0].id, BK.items[0].group, false);
        }else{
          await this.reloadMirror();
        }
      }catch(e){ reportError("快照列表读不出来", String((e && e.message) || e)); }
      finally{ BK.loading = false; }
    },
    async switchCtx(){
      BK.sel = null; BK.man = null; BK.view = null; BK.checkRows = null;
      BK.formOpen = false;
      BKD.diff = null; BK.fps = {}; BK.group = null;
      await this.refresh();
    },
    async open(id, group, toggle){
      if (toggle !== false && BK.sel === id){ BK.sel = null; BK.man = null; BK.view = null; BKD.diff = null; return; }  // 再点一下收起
      BK.sel = id; BK.view = null; BK.checkRows = null;
      try{
        const m = await pywebview.api.backup_manifest(id, group || "");
        if (!m || !m.ok){ toast("✗ " + ((m && m.msg) || "清单读不出来"), true); BK.man = null; return; }
        BK.man = m;
        await this.reloadMirror();          // 选中变了 ⇒ 重算对照（`V-94`）
      }catch(e){ reportError("快照清单读不出来", String((e && e.message) || e)); }
    },
    toggleForm(){
      BK.formOpen = !BK.formOpen;
      if (BK.formOpen){ BK.title = ""; BK.note = ""; }
    },
    async create(){
      const rels = bkScopeRels();
      if (!rels.length){ toast("✗ 没有要备份的东西", true); return; }
      BK.busy = "存快照…";
      try{
        const r = await pywebview.api.backup_create(rels, BK.title, BK.note, "");
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "失败"), true); return; }
        const st = r.stats || {};
        toast("快照已存：" + (st.files || 0) + " 项 · 新增 " + (st.new_objects || 0) + " 块");
        BK.formOpen = false;
        await this.refresh();
        await this.open(r.id, r.group, false);
      }catch(e){ reportError("存快照失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },
    /* 恢复（`V-87`；`V-92` 按"向 git 看齐"重做）。
       ★ 原来这里是**一个常驻的「合并 / 镜像」两段滑块**（`V-90`），你的原话是
         「似乎没什么效果 …… 还是说这个根本就是画蛇添足呢」。你想对了：它只在
         "现在比快照**多出来的**文件"存在时才有区别，而它又是个常驻模式 —— 点了它屏幕上
         什么都不变（状态只写在弹框文字里），新存的快照一点它当然没反应。
       ★ git 的做法：**两个动作，不是一个模式** ——
           `git restore`（只把快照里的写回工作区；多出来的**不动**）
           `git reset --hard` / `git clean`（连多出来的也一起清掉，让工作区**一模一样**）
         所以现在：滑块去掉，「恢复」点下去先算一份计划（**连多出来的也数出来**，纯读），
         弹框里把两个动词摆出来给你挑，还会把"多出来几个"写在脸上 —— 数字有了，区别就看得见。
         没有"多出来的"时候只给一个动词（git 那边也没东西可 clean）。 */
    async restore(it){
      const id = (it && it.id) || BK.sel;
      const group = (it && it.group) || (BK.man && BK.man.group) || "";
      if (!id){ toast("先选一个快照", true); return; }
      BK.busy = "算计划…";
      let plan = null;
      try{
        // `sync=true` 在这里**没有副作用**（只是让计划里多列几个 `extra` 行）——
        // 就是为了把"多出来的"数出来，好让两个动词各自的代价写在弹框上。
        plan = await pywebview.api.backup_plan(id, null, "changed", true, group);
        if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "计划算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      const c = plan.counts || {};
      const over = c.overwrite || 0, cre = c.create || 0, same = c.skip || 0;
      const err = c.error || 0, extra = c.extra || 0;
      if (!over && !cre && !extra){
        toast("不用恢复：已经和快照里一样了" + (err ? ("（另有 " + err + " 块缺失）") : ""));
        return;
      }
      const run = (sync) => async () => {
        BK.busy = sync ? "对齐中…" : "恢复中…";
        try{
          const r = await pywebview.api.backup_restore(id, null, "changed", sync, group);
          if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "恢复失败"), true); return; }
          const cc = r.counts || {};
          toast("补 " + (cc.restored || 0) + " · 挪走 " + (cc.trashed || 0) +
                (cc.errors ? (" · 出错 " + cc.errors) : ""));
          if (r.errors && r.errors.length) console.warn("恢复出错：", r.errors);
          this.afterDiskChange(r.restored || []);
          BK.view = null;
        }catch(e){ reportError("恢复失败", String((e && e.message) || e)); }
        finally{ BK.busy = ""; }
      };
      const body = "<b>" + esc(plan.title || "") + "</b><br>" +
        "缺的补上 <b>" + cre + "</b> · 不一样的回退 <b>" + over + "</b> · 已经一样 <b>" + same + "</b>" +
        (err ? ("<br>⚠ <b>" + err + "</b> 块内容缺失") : "") +
        (extra ? ("<br>快照里没有的（现在多出来的）<b>" + extra +
                  "</b> 个：只写回就留着，一模一样就挪进回收站（不真删）") : "");
      if (!extra){
        askConfirm("恢复这个快照",
          body + "<br>没有多出来的文件，两种做法是一样的。<br>开始？", run(false));
      }else{
        askConfirm2("恢复这个快照", body,
          {label: "只写回", title: "只把快照里的写回来（git restore）：多出来的一个不动",
           cb: run(false)},
          {label: "一模一样", title: "连多出来的 " + extra + " 个也挪进回收站（git reset --hard / clean），不真删",
           cb: run(true)});
      }
    },
    /* 盘上文件变了 ⇒ 文件管理那份缓存得作废（不然双击进去还是旧的清单） */
    afterDiskChange(rels){
      try{
        Object.keys(FM.st).forEach(k => { FM.st[k].stale = true; });
        FM.rev++;
        if ((rels || []).some(r => /pkg\.json$/i.test(r)) && typeof refreshPkgs === "function")
          refreshPkgs((cur && cur.id) || undefined, true);
        fmRefresh();
      }catch(e){}
    },
    /* 看某个文件在快照里的内容（只读；文本顺手高亮） */
    async viewFile(e){
      BK.busy = "读内容…";
      const group = (BK.man && BK.man.group) || "";
      try{
        const r = await pywebview.api.backup_blob(e.fp, group);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读不出来"), true); return; }
        BK.view = Object.assign({rel: e.rel, size: e.size}, r);
      }catch(err){ reportError("读快照内容失败", String((err && err.message) || err)); }
      finally{ BK.busy = ""; }
    },
    closeView(){ BK.view = null; },
    /* 恢复单个文件（快照展开后每行那颗「恢复」） */
    restoreOne(rel){
      const group = (BK.man && BK.man.group) || "";
      if (!BK.sel) return;
      pywebview.api.backup_restore(BK.sel, [rel], "all", false, group).then(r => {
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "恢复失败"), true); return; }
        toast("已恢复 " + rel);
        this.afterDiskChange([rel]);
      });
    },
    /* ---- 导出（`V-88`）----------------------------------------------------
       目标用**一个弹窗**问（边栏太窄，塞不下输入框）；也可以把文件夹**拖到边栏上**，
       拖进来就直接当目标（真路径只有宿主知道，见 `js/drop.js` 那个钩子）。 */
    onExportDragOver(){ BK.dropOver = true; },
    onExportDragLeave(){ BK.dropOver = false; },
    exportDialog(it){
      const id = (it && it.id) || BK.sel;
      const group = (it && it.group) || (BK.man && BK.man.group) || "";
      if (!id){ toast("先选一个快照", true); return; }
      askText("导出到哪个文件夹", BK.exportTo || "", async (v) => {
        const target = String(v || "").trim();
        if (!target) return;
        BK.exportTo = target;
        BK.busy = "算计划…";
        let plan = null;
        try{
          plan = await pywebview.api.backup_export_plan(id, target, "", null, group);
          if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "算不出来"), true); return; }
        }finally{ BK.busy = ""; }
        askConfirm("导出这个快照",
          "写到 <b class=\"mono\">" + esc(plan.root) + "</b><br>新写 <b>" + plan.new +
          "</b> · 覆盖 <b>" + plan.overwrite + "</b> · " + humanSize(plan.bytes) +
          "<br>原文件不动。<br>开始？",
          async () => {
            BK.busy = "导出中…";
            try{
              const r = await pywebview.api.backup_export(id, target, "", null,
                                                          !!BK.exportBak, group);
              if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "导出失败"), true); return; }
              toast("导出 " + ((r.counts || {}).written || 0) + " 个 → " + r.root);
            }catch(e){ reportError("导出失败", String((e && e.message) || e)); }
            finally{ BK.busy = ""; }
          });
      });
    },
    async del(id, title){
      askConfirm("删掉这个快照",
        "「" + esc(title || id) + "」<br>删完会把没人再引用的内容块一并回收。<br>不可撤销。",
        async () => {
          BK.busy = "删除中…";
          try{
            const r = await pywebview.api.backup_delete(id, (BK.man && BK.man.group) || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "删不掉"), true); return; }
            toast("已删掉（回收 " + (r.removed || 0) + " 块）");
            if (BK.sel === id){ BK.sel = null; BK.man = null; BK.view = null; }
            await this.refresh();
          }catch(e){ reportError("删快照失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },
    /* 把**这一组**（当前对象）的快照全删掉 */
    async dropGroup(){
      const g = bkGroupForCtx();
      const info = await pywebview.api.backup_group_info(g);
      if (!info || !info.ok){ toast("✗ " + ((info && info.msg) || "拿不到信息"), true); return; }
      if (!info.backups){ toast("还没有快照"); return; }
      askConfirm("删掉这个对象的全部快照",
        "<b>" + esc(g) + "</b>：<b>" + info.backups + "</b> 次、" + humanSize(info.store_bytes) +
        "，整个文件夹都会删掉。<br>不可撤销。",
        async () => {
          const r = await pywebview.api.backup_drop_group(g);
          toast((r && r.msg) || "删完了");
          BK.sel = null; BK.man = null; BK.view = null;
          await this.refresh();
        });
    },
    async gcNow(){
      const g = bkGroupForCtx();
      BK.busy = "算中…";
      let pre = null;
      try{
        pre = await pywebview.api.backup_gc(true, g);
        if (!pre || !pre.ok){ toast("✗ " + ((pre && pre.msg) || "算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      if (!pre.removed){ toast("没有可回收的内容块"); return; }
      askConfirm("回收内容块",
        "有 <b>" + pre.removed + "</b> 块没人引用了（约 " + humanSize(pre.freed) + "）。清掉？",
        async () => {
          const r = await pywebview.api.backup_gc(false, g);
          toast((r && r.msg) || "清理完了");
          await this.refresh();
        });
    },
    async checkNow(){
      BK.busy = "校验中…";
      try{
        const r = await pywebview.api.backup_check(null, bkGroupForCtx());
        if (!r || !r.ok){ toast("✗ 校验失败", true); return; }
        BK.checkRows = r.rows || [];
        const bad = BK.checkRows.filter(x => x.missing || x.broken);
        toast(bad.length ? ("⚠ " + bad.length + " 次快照缺内容块") : "校验通过：内容块都在");
      }finally{ BK.busy = ""; }
    },
  },
  template: `
<div class="bk-snap" :class="{dover: BK.dropOver, mini: BK.collapsed}"
     @dragover.prevent.stop="onExportDragOver()" @dragleave="onExportDragLeave()">
  <!-- 左边那条"拖我调宽"的细线（V-92）：拖它改边栏宽度，双击回到 320。
       注意：这里是**模板字符串里面**，注释里不能出现反引号（会把模板提前截断）。 -->
  <div class="grip b-bkgrip" title="拖我调宽（双击复原）"></div>
  <div class="bk-snap-head">
    <span class="bk-snap-title" :title="'「' + ctxLabel + '」的版本快照 —— 存在 user_data/backups/' + ctxGroup + '/（按包 id 分文件夹，改 id 就改这个名字）'">
      <span v-html='ico("history", "i")'></span>版本快照
    </span>
    <span class="sp"></span>
    <button class="iconbtn b-bknew" title="给「{{ ctxLabel }}」创建一个快照"
            v-html='ico("moss-camera", "i")'
            @click="snapModalOpen()"></button>
    <button class="iconbtn b-bkfold" :title="BK.collapsed ? '展开边栏' : '收起边栏'"
            v-html='ico("panel-left", "i")' @click="toggleFold()"></button>
  </div>

  <template v-if="!BK.collapsed">
    <div v-if="BK.formOpen" class="bk-form">
      <input v-model="BK.title" class="bk-title" placeholder="标题（可留空）"
             title="给这次快照起个名，留空就用时间">
      <input v-model="BK.note" class="bk-note" placeholder="注释（可留空）"
             title="这次改了什么、为什么要存 —— 以后翻快照时看得懂">
      <div class="bk-ig" :title="igTip" @click.stop="editIgnore()">
        过滤：{{ igShort }}
      </div>
      <span class="bk-ig bk-pre" title="试算：按现在的规则，这次会存哪些、排掉哪些（不落盘）"
            @click.stop="preview()">试算</span>
      <span class="sp"></span>
      <button class="iconbtn b-bkcancel" title="取消（不存了）" v-html='ico("x", "i")'
              @click="BK.formOpen = false"></button>
      <button class="iconbtn b-bksave" :disabled="!!BK.busy"
              title="存成一次快照（内容按指纹去重，重复的只存一份）"
              v-html='ico("check", "i")' @click="create()"></button>
    </div>

    <div class="bk-tl">
      <div class="bk-tl-item active">
        <div class="bk-tl-dot"></div>
        <div class="bk-card flat">
          <div class="bk-card-top"><b>当前工作区</b><span class="bk-time">现在</span></div>
          <div class="bk-card-sub" :title="scopeTip">{{ ctxLabel }}</div>
        </div>
      </div>

      <div v-if="BK.loading" class="bk-empty">读快照…</div>
      <div v-else-if="!BK.items.length" class="bk-empty">还没有快照 —— 点上面的 ＋</div>

      <div v-for="it in BK.items" :key="it.id" class="bk-tl-item" :class="{on: it.id === BK.sel}"
           :data-bk="it.id">
        <div class="bk-tl-dot"></div>
        <div class="bk-card" @click="open(it.id, it.group)">
          <!-- ★ V-177：一条快照 = 一行。常态「名字 靠左 + N项/大小/时间 靠右（完整显示）」；
               hover 才展开成两行（标题+按钮 / 项目数+大小 靠左、时间靠右）。布局靠 grid 换 areas，见 CSS。 -->
          <b class="bk-t" :title="it.note || it.title">{{ it.title }}</b>
          <span class="bk-cnt">{{ it.files }} 项</span>
          <span class="bk-size">{{ humanSize(it.bytes) }}</span>
          <span class="bk-time">{{ shortTime(it.created_text) }}</span>
          <div class="bk-card-act">
            <button class="iconbtn b-bkrestore" data-bk-act="restore" @click.stop="restore(it)"
                    title="恢复（git restore）：把快照里的写回来 —— 缺的补上、不一样的回退（覆盖前留 .bak）；现在多出来的一个都不动"
                    v-html='ico("moss-history", "i")'></button>
            <button class="iconbtn b-bkexport" data-bk-act="export" @click.stop="exportDialog(it)"
                    title="导出到文件夹（另存一份；也可以直接把一个文件夹拖到边栏上）"
                    v-html='ico("moss-folder-out", "i")'></button>
            <button class="iconbtn danger b-bkdel" data-bk-act="del"
                    title="删掉这个快照（没人引用的内容块会自动回收）"
                    v-html='ico("trash-2", "i")' @click.stop="del(it.id, it.title)"></button>
          </div>
        </div>

        <div v-if="it.id === BK.sel && BK.man" class="bk-files">
          <div class="bk-files-top">
            <span class="bk-hint bk-mpath" :title="mirrorTip">{{ mirrorPath }}</span>
            <span class="sp"></span>
            <span class="bk-hint bk-mcount" :title="mirrorCountTip">{{ mirrorCount }}</span>
            <button class="iconbtn b-bkfoldfiles" :title="foldedNow ? '展开文件列表' : '收起文件列表'"
                    :class="{folded: foldedNow}" v-html='ico("chevron-right", "i")'
                    @click.stop="toggleFoldFiles()"></button>
            <button class="iconbtn b-bkviewall" title="看整个快照的统计/校验"
                    v-html='ico("info", "i")' @click="checkNow()"></button>
          </div>
          <div v-if="BKD.diff && !BKD.diff.snapOk" class="bk-empty">快照里没有这个目录</div>
          <div v-if="foldedNow" class="bk-empty bk-folded" @click="toggleFoldFiles()">
            文件列表已收起（{{ mirrorCount }}）—— 点这里展开
          </div>
          <div v-for="e in mirrorRows" :key="e.name" class="bk-file" :class="mirrorCls(e)"
               :data-rel="e.rel" :data-dir="e.dir ? 1 : 0" :data-state="e.state" :title="e.why">
            <span class="bk-fname" :class="{isdf: e.dir}">{{ e.name }}{{ e.dir ? "/" : "" }}</span>
            <span class="bk-fsize" :class="mirrorSizeCls(e)">{{ mirrorSize(e) }}</span>
            <button v-if="e.snap && !e.dir" class="iconbtn b-bkview" title="看快照里这份的内容"
                    v-html='ico("eye", "i")' @click.stop="viewFile(e)"></button>
            <button v-if="e.snap && !e.dir" class="iconbtn b-bkone"
                    title="只恢复这一个（只写回：覆盖前留 .bak）"
                    v-html='ico("undo-2", "i")' @click.stop="restoreOne(e.rel)"></button>
          </div>
          <div v-if="BK.checkRows" class="bk-checkbar">
            <template v-for="(r, i) in BK.checkRows" :key="i"
              >{{ i ? " · " : "" }}{{ r.id.slice(-4) }}:
              <b :class="{bad: r.missing || r.broken}"
                 >{{ r.broken ? "坏" : (r.missing ? ("缺 " + r.missing) : "好") }}</b
            ></template>
          </div>
        </div>
      </div>
    </div>

    <div class="bk-view" v-if="BK.view">
      <div class="bk-view-head">
        <span class="mono bk-vname">{{ BK.view.rel }}</span>
        <span class="bk-hint" :title="'指纹 ' + BK.view.fp">
          {{ humanSize(BK.view.size) }}
          <span v-if="BK.view.binary" title="二进制内容，这里只给大小和头部字节">· 二进制</span>
          <span v-else-if="BK.view.truncated" title="文件太大，只给前一段；要看全的请导出/恢复出来">· 截断</span>
        </span>
        <span class="sp"></span>
        <button class="iconbtn b-bkviewclose" title="关掉" v-html='ico("x", "i")'
                @click="closeView()"></button>
      </div>
      <pre v-if="BK.view.binary" class="bk-view-bin">（二进制内容，头部字节：{{ BK.view.head }}）</pre>
      <pre v-else class="bk-view-text" v-html="viewHTML"></pre>
    </div>

    <div class="bk-snap-foot">
      <span class="bk-hint" :title="statTip">{{ statLine }}</span>
      <span class="sp"></span>
      <span v-if="BK.busy" class="bk-busy">{{ BK.busy }}</span>
      <button class="iconbtn b-bkgc" title="回收：把没人引用的内容块删掉（删快照时会自动做）"
              v-html='ico("eraser", "i")' @click="gcNow()"></button>
      <button class="iconbtn warn b-bkdropgroup" title="删掉这个对象的全部快照（整个文件夹）"
              v-html='ico("trash-2", "i")' @click="dropGroup()"></button>
    </div>
  </template>
</div>`,
  // 边栏收起时那一列只剩标题栏，高度占满
  beforeMount(){ BK.collapsed = (window.innerWidth || 1200) < 1080; },
};

/* 把边栏塞进文件管理那个组件里（`js/files.js` 的模板里写着 `<moss-file-snap>`） */
MossFileManager.components.MossFileSnap = MossFileSnap;
