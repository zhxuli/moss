/* moss 界面 · js/backup.js —— 「备份」那一页（`V-87`，`V-89` 分组，`V-90` 界面收拾）。
   ============================================================================
   一句话：**开发时把数据存一份**。跟 git 一个路子 —— 备份里只记**指纹**（路径 → 指纹），
   文件内容按指纹单独存一份，所以同一个内容（换了名字、换了目录、跨好几次备份）只占一份。
   落盘按**包 id 分组**：`user_data/backups/<包id>/{objects/,<备份id>/manifest.json}`
   —— 改个 id 就改一个文件夹名、删个包就删一个文件夹。

   这一页是**文件管理里的第二个常驻子选项卡**（和「文件」并排、同样不能关），
   挂载点是 `MossFileManager` 模板里的 `<moss-file-backup>`；那个组件在 `js/files.js` 里
   （本文件在它**之后**加载），所以这边只做一件事：把组件塞进它的 `components` 里。

   ★ 逻辑全在宿主侧：`system/ui/backup.py`（内容寻址 + 标记-清除回收）。
     页面这一层只管"点一下 → 调 api → 把结果摆出来"，自己不碰文件系统。

   ★ 界面规矩（`V-90`，你定的）：**按钮两三个字，说明进 hover**。所以：
     · 恢复 = 一个「恢复」+ 一个两段式滑块「合并 / 镜像」（git 味的名字）
     · 分组不搞下拉框，就两个小段：`当前包 / 全部`（默认跟着文件管理里选中的包）
     · 页面上不留大段解释文字，全部塞进 `title`
   ============================================================================ */

/* 这一页的状态（自己一份，和文件管理那份 `FM` 无关）。
   为什么不挂进 `FM.st[ctx]`：备份是**跨上下文**的东西（一次备份可以覆盖好几个目录），
   不像"当前目录 / 选中 / 打开的文件"那样跟着"现在选的是哪个包"走。 */
const BK = Vue.reactive({
  items: [], stat: {}, groups: [], loading: false,
  sel: null, man: null,
  view: null,                          // {rel, fp, binary, text, size, truncated} 或 null
  formOpen: false, title: "", note: "", scope: "",
  filter: "", busy: "", checkRows: null,
  exportTo: "", exportBak: false, exportInfo: null, dropOver: false,   // 导出（`V-88`）
  listOnly: "pkg",                     // 列表看哪些：`pkg` = 当前这个包，`all` = 所有分组
  mode: "merge",                       // 恢复方式：`merge` 合并 / `mirror` 镜像（`V-90`）
  groupHint: "",                       // 这次新建会落到哪个分组（按来源算）
});

/* 「当前包」这个段对应哪一组：文件管理里选中的那个包（`cur`）的 id。
   不是包（历史条目 / 全部文件）时退回"所有分组"。 */
function bkListGroup(){
  if (BK.listOnly !== "pkg") return "";
  return (cur && cur.id) || "";
}
function bkCurGroupName(){ return bkListGroup() || ""; }

/* ---- 备份来源的候选（跟着"现在选的是哪个包"走）---- */
function bkScopes(){
  const out = [];
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  if (p){
    const roots = [];
    const rel = pkgRel(p);
    if (rel) roots.push(rel);
    roots.push("user/state/" + p.id);          // 数据目录（没有也不碍事，备份时按"空的"处理）
    out.push({id: "pkg", label: "这个包：" + (p.name || p.id), rels: roots,
              hint: "包目录 + 它的数据目录"});
  }
  out.push({id: "user", label: "整个 user_data", rels: ["user"],
            hint: "所有用户资产（回收站和备份库自己会跳过）"});
  const s = FM.st[key] || (FM.ctx ? fmState(FM.ctx) : null);
  if (s && s.rel){
    out.push({id: "here", label: "当前浏览的目录：" + s.rel, rels: [s.rel],
              hint: "文件管理里现在站着的那个目录"});
  }
  return out;
}
function bkDefaultScope(){ return (bkScopes()[0] || {}).id || "user"; }
function bkScopeRels(){
  const list = bkScopes();
  const hit = list.find(x => x.id === (BK.scope || bkDefaultScope())) || list[0];
  return (hit && hit.rels) || [];
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

const MossFileBackup = {
  name: "moss-file-backup",
  props: {active: {type: Boolean, default: false}},
  // ★ 模板里够不着模块级的 BK（Vue 模板只认实例上的东西）—— 显式交出去。
  data(){ return { BK: BK }; },
  computed: {
    scopes(){ void FM.rev; void FM.st; return bkScopes(); },
    scopeRelsText(){ void FM.rev; void FM.st; return bkScopeRels().join("、"); },
    curGroup(){ void FM.rev; return bkListGroup(); },
    rows(){
      const f = (BK.filter || "").trim().toLowerCase();
      let list = (BK.man && BK.man.files) || [];
      if (f) list = list.filter(e => String(e.rel || "").toLowerCase().includes(f));
      return list;
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
    /* 工具条右边那点字：短，细节进 hover */
    statLine(){
      const s = BK.stat || {};
      const bits = [(s.backups || 0) + " 次", (s.store_bytes || 0) ? humanSize(s.store_bytes) : "0 B"];
      if (s.saved) bits.push("省 " + humanSize(s.saved));
      return bits.join(" · ");
    },
    statTip(){
      const s = BK.stat || {};
      return "备份 " + (s.backups || 0) + " 次 · 文件 " + (s.files || 0) + " 个 · 内容块 " +
             (s.objects || 0) + " 个（占 " + humanSize(s.store_bytes) + "）" +
             (s.saved ? ("；去重省了 " + humanSize(s.saved)) : "") +
             "。" + ((s.groups || 0) > 1 ? ("（共 " + s.groups + " 个分组）") : "");
    },
  },
  watch: {
    active(on){ if (on) this.refresh(); },
  },
  mounted(){
    if (this.active) this.refresh();
    // ★ 拖一个文件夹到「导出到」那一行上 ⇒ 当导出目标。
    //   真路径只有宿主知道（Chromium 不给页面 `File.path`）—— 宿主从 WebView2 拿到之后
    //   调 `window.__mossDrop(items)`，`js/drop.js` 会**先问这个钩子**：收下了就返回 true，
    //   不然还走原来那条"拖着文件跑一个包"的路（互不打架）。
    window.__mossDropHook = (items) => {
      if (!BK.dropOver) return false;
      const it = (items || [])[0];
      if (!it) return false;
      const p = it.isDir ? it.path : it.dir;          // 拖的是文件 ⇒ 用它所在的目录
      if (!p) return false;
      BK.exportTo = p;
      BK.exportInfo = null;
      BK.dropOver = false;
      toast("导出到 " + p);
      return true;                                    // 这条拖放我们收下了
    };
  },
  unmounted(){ if (window.__mossDropHook) window.__mossDropHook = null; },
  methods: {
    humanSize: n => humanSize(n),
    fmtWhen(t){ return t ? fmtTime(t) : ""; },
    shortFp: bkShortFp,
    isMirror(){ return BK.mode === "mirror"; },
    setMode(m){ BK.mode = m; },
    setList(which){ if (BK.listOnly !== which){ BK.listOnly = which; this.switchList(); } },

    async refresh(){
      BK.loading = true;
      try{
        const r = await pywebview.api.backup_list(bkListGroup());
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "拿不到备份列表"), true); return; }
        BK.items = r.items || [];
        BK.stat = r.stat || {};
        BK.groups = r.groups || [];
        if (BK.sel && !BK.items.some(x => x.id === BK.sel)){ BK.sel = null; BK.man = null; }
        if (!BK.sel && BK.items.length) await this.open(BK.items[0].id, BK.items[0].group);
      }catch(e){ reportError("备份列表读不出来", String((e && e.message) || e)); }
      finally{ BK.loading = false; }
    },
    async open(id, group){
      BK.sel = id; BK.view = null; BK.checkRows = null;
      try{
        const m = await pywebview.api.backup_manifest(id, group || "");
        if (!m || !m.ok){ toast("✗ " + ((m && m.msg) || "清单读不出来"), true); BK.man = null; return; }
        BK.man = m;
      }catch(e){ reportError("备份清单读不出来", String((e && e.message) || e)); }
    },
    async switchList(){
      BK.sel = null; BK.man = null; BK.view = null;
      await this.refresh();
    },
    toggleForm(){
      BK.formOpen = !BK.formOpen;
      if (BK.formOpen){
        BK.scope = bkDefaultScope();
        BK.title = "";
        BK.note = "";
        this.hintGroup();
      }
    },
    /* 这次新建会落到哪个分组（按来源算，和后端同一套规则）—— 表单上一小行 */
    async hintGroup(){
      try{
        const r = await pywebview.api.backup_group_hint(bkScopeRels());
        BK.groupHint = (r && r.ok) ? (r.group || "") : "";
      }catch(e){ BK.groupHint = ""; }
    },
    async create(){
      const rels = bkScopeRels();
      if (!rels.length){ toast("✗ 没有要备份的东西", true); return; }
      BK.busy = "备份中…";
      try{
        const r = await pywebview.api.backup_create(rels, BK.title, BK.note, "");
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "备份失败"), true); return; }
        const st = r.stats || {};
        toast("已备份 " + (st.files || 0) + " 个文件（新增 " + (st.new_objects || 0) +
              " 块）→ " + (r.group || ""));
        BK.formOpen = false;
        await this.refresh();
        await this.open(r.id, r.group);
      }catch(e){ reportError("备份失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },
    /* 删掉**这一组**的备份（连它的内容块）。目标 = 现在这份备份所在的分组，
       没选备份就用"当前包"那一组。 */
    async dropGroup(){
      const g = (BK.man && BK.man.group) || bkListGroup();
      if (!g){ toast("先选一次备份（或者切到「当前包」）", true); return; }
      const info = await pywebview.api.backup_group_info(g);
      if (!info || !info.ok){ toast("✗ " + ((info && info.msg) || "拿不到分组信息"), true); return; }
      if (!info.backups){ toast("这一组还没有备份"); return; }
      askConfirm("删掉 " + g + " 的备份",
        "分组 <b>" + esc(g) + "</b> 里 <b>" + info.backups + "</b> 次备份、" +
        humanSize(info.store_bytes) + "，整个文件夹都会删掉（别的分组不动）。<br>不可撤销。",
        async () => {
          BK.busy = "删除中…";
          try{
            const r = await pywebview.api.backup_drop_group(g);
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "删不掉"), true); return; }
            toast(r.msg);
            BK.sel = null; BK.man = null; BK.view = null;
            await this.refresh();
          }catch(e){ reportError("删分组失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },
    async viewFile(e){
      BK.busy = "读内容…";
      const g = (BK.man && BK.man.group) || "";
      try{
        const r = await pywebview.api.backup_blob(e.fp, g);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读不出来"), true); return; }
        BK.view = Object.assign({rel: e.rel, size: e.size}, r);
      }catch(err){ reportError("读备份内容失败", String((err && err.message) || err)); }
      finally{ BK.busy = ""; }
    },
    closeView(){ BK.view = null; },

    /* 恢复：**一个按钮 + 一个两段滑块**（`V-90`）。
         merge（合并）= 把备份里的写回来（缺的补上、不一样的回退 / 覆盖前留 .bak），
                        **现在多出来的一个都不动** —— 跟 git 的 merge 一个意思。
         mirror（镜像）= 连"现在多出来的"也挪进回收站，让它和这次备份一模一样
                        （跟 `rsync --delete` / `git clone --mirror` 一个意思）。
       两步走：先 `plan` 算清楚，弹确认框把数字摆出来，点了才动手。 */
    async restore(mode, rels){
      if (!BK.sel) return;
      const m = mode || BK.mode || "merge";
      const sync = (m === "mirror");
      const g = (BK.man && BK.man.group) || "";
      BK.busy = "算计划…";
      let plan = null;
      try{
        plan = await pywebview.api.backup_plan(BK.sel, rels || null, "changed", sync, g);
        if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "计划算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      const c = plan.counts || {};
      const over = c.overwrite || 0, cre = c.create || 0, same = c.skip || 0, err = c.error || 0;
      const extra = c.extra || 0;
      if (!over && !cre && !(sync && extra)){
        toast("不用恢复：已经和备份里一样了" + (err ? ("（另有 " + err + " 块缺失）") : ""));
        return;
      }
      const one = rels && rels.length === 1;
      const title = one ? "恢复这一个文件" : (sync ? "镜像到这次备份" : "合并这次备份");
      askConfirm(title,
        (one ? ("<b class=\"mono\">" + esc(rels[0]) + "</b><br>") : "") +
        "补 <b>" + cre + "</b> · 回退 <b>" + over + "</b>" +
        (sync ? (" · <b>挪走 " + extra + "<\/b>（进回收站）") : "") +
        " · 跳过 <b>" + same + "</b>" +
        (err ? ("<br>⚠ " + err + " 块内容缺失，恢复不了") : "") + "<br>继续？",
        async () => {
          BK.busy = sync ? "镜像中…" : "合并中…";
          try{
            const r = await pywebview.api.backup_restore(BK.sel, rels || null, "changed", sync, g);
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "恢复失败"), true); return; }
            const cc = r.counts || {};
            toast("补 " + (cc.restored || 0) + " · 挪走 " + (cc.trashed || 0) +
                  (cc.errors ? (" · 出错 " + cc.errors) : ""));
            if (r.errors && r.errors.length) console.warn("恢复出错：", r.errors);
            this.afterDiskChange(r.restored || []);
            BK.view = null;
          }catch(e){ reportError("恢复失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
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
    /* ---- 导出到别的文件夹（`V-88`）------------------------------------------
       ①「选择」挑一个；②把文件夹从资源管理器**拖到那一行上**；③在框里接着敲子目录
       （`D:\out` 再敲成 `D:\out\2\` ⇒ 落到 `D:\out\2\…`）。
       导出是"另存一份"：原来那些文件一个都不动。 */
    onExportDragOver(){ BK.dropOver = true; },
    onExportDragLeave(){ BK.dropOver = false; },
    async pickExportDir(){
      BK.busy = "挑文件夹…";
      try{
        const r = await pywebview.api.pick_dir(BK.exportTo || "");
        if (r && r.ok){ BK.exportTo = r.path; BK.exportInfo = null; }
        else if (r && r.msg && !/取消|超时/.test(r.msg)) toast("✗ " + r.msg, true);
      }catch(e){ reportError("挑文件夹失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },
    async exportTo(rels){
      if (!BK.man) return;
      const target = (BK.exportTo || "").trim();
      if (!target){ toast("✗ 先选目标文件夹（或者把文件夹拖到那一行上）", true); return; }
      const g = (BK.man && BK.man.group) || "";
      BK.busy = "算计划…";
      let plan = null;
      try{
        plan = await pywebview.api.backup_export_plan(BK.man.id, target, "", rels || null, g);
        if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "算不出导出计划"), true); return; }
      }finally{ BK.busy = ""; }
      BK.exportInfo = plan;
      const one = rels && rels.length === 1;
      askConfirm(one ? "导出这一个文件" : "导出这次备份",
        "写到 <b class=\"mono\">" + esc(plan.root) + "</b><br>新写 <b>" + plan.new +
        "</b> · 覆盖 <b>" + plan.overwrite + "</b> · 共 " + humanSize(plan.bytes) +
        "<br>原文件不动。" + (BK.exportBak ? "<br>覆盖前各留一份 <span class=\"mono\">.bak</span>。" : "") +
        "<br>开始？",
        async () => {
          BK.busy = "导出中…";
          try{
            const r = await pywebview.api.backup_export(BK.man.id, target, "", rels || null,
                                                        !!BK.exportBak, g);
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "导出失败"), true); return; }
            toast("导出 " + ((r.counts || {}).written || 0) + " 个 → " + r.root);
          }catch(e){ reportError("导出失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },
    async del(id, title){
      askConfirm("删掉这次备份",
        "「" + esc(title || id) + "」<br>删完会把没人再引用的内容块一并回收（还有别人引用的留着）。" +
        "<br>不可撤销。",
        async () => {
          BK.busy = "删除中…";
          try{
            const r = await pywebview.api.backup_delete(id, (BK.man && BK.man.group) || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "删不掉"), true); return; }
            toast("已删掉（回收 " + (r.removed || 0) + " 块）");
            if (BK.sel === id){ BK.sel = null; BK.man = null; BK.view = null; }
            await this.refresh();
          }catch(e){ reportError("删备份失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },
    async gcNow(){
      const g = (BK.man && BK.man.group) || "";
      BK.busy = "算中…";
      let pre = null;
      try{
        pre = await pywebview.api.backup_gc(true, g);
        if (!pre || !pre.ok){ toast("✗ " + ((pre && pre.msg) || "算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      if (!pre.removed){ toast("没有可回收的内容块"); return; }
      askConfirm("回收内容块",
        "有 <b>" + pre.removed + "</b> 块没人引用了（约 " + humanSize(pre.freed) +
        "）。<br>（删备份时会自动回收，这里是手动再扫一遍。）<br>清掉？",
        async () => {
          const r = await pywebview.api.backup_gc(false, g);
          toast((r && r.msg) || "清理完了");
          await this.refresh();
        });
    },
    async checkNow(){
      BK.busy = "校验中…";
      try{
        const r = await pywebview.api.backup_check(null, (BK.man && BK.man.group) || "");
        if (!r || !r.ok){ toast("✗ 校验失败", true); return; }
        BK.checkRows = r.rows || [];
        const bad = BK.checkRows.filter(x => x.missing || x.broken);
        toast(bad.length ? ("⚠ " + bad.length + " 次备份缺内容块（看下面那行）")
                         : "校验通过：内容块都在");
      }finally{ BK.busy = ""; }
    },
  },
  template: `
<div class="fmpage" :class="{on: active}" data-page="__backup__">
  <div class="bk-tools">
    <button class="iconbtn b-bknew" title="新建一次备份（存一份当前这个包的数据）"
            v-html='ico("file-plus", "i")' @click="toggleForm()"></button>
    <button class="iconbtn b-bkrefresh" title="刷新" v-html='ico("refresh-cw", "i")'
            @click="refresh()"></button>
    <span class="gap"></span>
    <div class="bk-seg" data-bk-seg="list">
      <button :class="{on: BK.listOnly === 'pkg'}" data-bk-list="pkg" @click="setList('pkg')"
              title="只看**当前这个包**的备份（备份是按包 id 分文件夹存的，改 id 会跟着改）"
              >当前包</button>
      <button :class="{on: BK.listOnly === 'all'}" data-bk-list="all" @click="setList('all')"
              :title="'看所有分组的备份（现在有 ' + (BK.groups || []).length + ' 组）'"
              >全部</button>
    </div>
    <span class="gap"></span>
    <button class="iconbtn b-bkcheck" title="校验：清单里提到的内容块都还在吗"
            v-html='ico("check", "i")' @click="checkNow()"></button>
    <button class="iconbtn b-bkgc" title="回收：把没人引用的内容块删掉（删备份时会自动做）"
            v-html='ico("eraser", "i")' @click="gcNow()"></button>
    <button class="iconbtn warn b-bkdropgroup" title="删掉这一组的备份（连它的内容块，别的分组不动）"
            v-html='ico("trash-2", "i")' @click="dropGroup()"></button>
    <span class="sp"></span>
    <span class="bk-stat" :title="statTip">{{ statLine }}</span>
    <span v-if="BK.busy" class="bk-busy">{{ BK.busy }}</span>
  </div>

  <div v-if="BK.formOpen" class="bk-form">
    <div class="bk-formrow">
      <select v-model="BK.scope" class="bk-scope" @change="hintGroup()"
              title="备份哪些东西：当前这个包（包目录 + 数据目录）/ 整个 user_data / 当前浏览的目录">
        <option v-for="s in scopes" :key="s.id" :value="s.id">{{ s.label }}</option>
      </select>
      <span class="bk-tag" :title="'这一组存在 user_data/backups/' + (BK.groupHint || '?')">
        {{ BK.groupHint || "?" }}</span>
      <input v-model="BK.title" class="bk-title" placeholder="标题（可留空）"
             title="给这次备份起个名，留空就用时间">
      <input v-model="BK.note" class="bk-note" placeholder="注释（可留空）"
             title="这次改了什么、为什么要存 —— 以后翻备份时看得懂">
      <span class="sp"></span>
      <button class="btn" @click="BK.formOpen = false">取消</button>
      <button class="btn primary" :disabled="!!BK.busy" @click="create()"
              title="开始备份（内容按指纹去重，重复的只存一份）">备份</button>
    </div>
  </div>

  <div class="bk-body">
    <div class="bk-left">
      <div v-if="BK.loading" class="bk-empty">读列表…</div>
      <div v-else-if="!BK.items.length" class="bk-empty">
        <span v-if="BK.listOnly === 'pkg'">这个包还没有备份</span>
        <span v-else>还没有备份</span>
      </div>
      <div v-for="it in BK.items" :key="it.id" class="bk-item" :class="{on: it.id === BK.sel}"
           :data-bk="it.id" :title="it.note || it.title" @click="open(it.id, it.group)">
        <div class="bk-it-title">
          <span v-if="BK.listOnly === 'all'" class="bk-gtag">{{ it.group }}</span>{{ it.title }}
        </div>
        <div class="bk-it-sub">{{ it.created_text }} · {{ it.files }} 个 · {{ humanSize(it.bytes) }}</div>
        <div v-if="it.broken" class="bk-it-bad">清单读不出来</div>
      </div>
    </div>

    <div class="bk-right">
      <div v-if="!BK.man" class="bk-empty">选一次备份</div>
      <template v-else>
        <div class="bk-detail-head">
          <div class="bk-dh-text">
            <div class="bk-title-line">{{ BK.man.title }}</div>
            <div class="bk-it-sub" :title="(BK.man.sources || []).join('、')">
              <span class="bk-gtag">{{ BK.man.group }}</span>
              {{ BK.man.created_text }} · {{ (BK.man.files || []).length }} 个文件
              <span v-if="BK.man.note">· {{ BK.man.note }}</span>
            </div>
          </div>
          <span class="sp"></span>
          <div class="bk-seg" data-bk-seg="mode">
            <button :class="{on: BK.mode === 'merge'}" data-bk-mode="merge" @click="setMode('merge')"
                    title="合并（merge）：把备份里的写回来 —— 缺的补上、不一样的回退（覆盖前留 .bak）；现在多出来的文件一个都不动"
                    >合并</button>
            <button :class="{on: BK.mode === 'mirror'}" data-bk-mode="mirror" @click="setMode('mirror')"
                    title="镜像（mirror）：让它和这次备份一模一样 —— 缺的补上、不一样的回退，现在多出来的挪进回收站（不真删）"
                    >镜像</button>
          </div>
          <button class="btn primary" data-bk-act="restore" @click="restore()"
                  :title="BK.mode === 'mirror' ? '按镜像方式恢复这次备份' : '按合并方式恢复这次备份'"
                  >恢复</button>
          <button class="iconbtn danger b-bkdel" data-bk-act="del"
                  title="删掉这次备份（内容块没人引用了会自动回收）"
                  v-html='ico("trash-2", "i")' @click="del(BK.man.id, BK.man.title)"></button>
        </div>

        <div class="bk-export" :class="{dover: BK.dropOver}"
             @dragover.prevent.stop="onExportDragOver()" @dragleave="onExportDragLeave()">
          <span class="bk-hint" title="把这次备份（或某一个文件）另存到别的文件夹；原文件不动">导出</span>
          <input v-model="BK.exportTo" class="bk-out" data-bk-out
                 :title="'目标文件夹。可以按「选择」挑，也可以把文件夹拖到这一行上；' +
                         '后面能接着敲子目录（比如 /2/ 就落到它的子文件夹里）'"
                 placeholder="目标文件夹（也可以拖一个进来，或敲 /2/ 落到子目录）">
          <button class="iconbtn b-bkpick" data-bk-act="pick" @click="pickExportDir()"
                  title="选一个文件夹" v-html='ico("folder-open", "i")'></button>
          <button class="iconbtn b-bkbak" :class="{on: BK.exportBak}" @click="BK.exportBak = !BK.exportBak"
                  :title="'覆盖同名文件前，各留一份 .bak（现在是' + (BK.exportBak ? '开' : '关') + '）'"
                  v-html='ico("save", "i")'></button>
          <button class="btn" data-bk-act="export" @click="exportTo(null)"
                  title="按这个目标导出这次备份（另存一份）">导出</button>
          <span v-if="BK.exportInfo" class="bk-hint mono" data-bk-outinfo
                :title="BK.exportInfo.root">将写 {{ BK.exportInfo.new }} 个</span>
        </div>

        <div class="bk-filter">
          <input v-model="BK.filter" class="bk-q" placeholder="筛路径"
                 title="按路径筛下面的文件列表（比如 pkg.json / state）">
          <span class="bk-hint">{{ rows.length }} / {{ (BK.man.files || []).length }}</span>
          <span v-if="(BK.man.empty_dirs || []).length" class="bk-hint"
                title="这次备份里还有几个空目录，恢复时会一起建出来">空目录 {{ BK.man.empty_dirs.length }}</span>
          <span v-if="(BK.man.errors || []).length" class="bk-hint bk-warn"
                :title="(BK.man.errors || []).slice(0, 3).join('；')">读不了 {{ BK.man.errors.length }}</span>
        </div>

        <div class="bk-scroll">
          <table class="bk-tbl">
            <thead><tr>
              <th title="备份里的路径（相对 user_data / system）">文件</th>
              <th class="w-size">大小</th>
              <th class="w-when">时间</th>
              <th class="w-act"></th>
            </tr></thead>
            <tbody>
              <tr v-for="e in rows" :key="e.rel" class="row" :data-rel="e.rel">
                <td class="nmcell" :title="e.rel + '\\n指纹 ' + e.fp"><span class="mono">{{ e.rel }}</span></td>
                <td class="num">{{ humanSize(e.size) }}</td>
                <td class="dim">{{ fmtWhen(e.mtime) }}</td>
                <td>
                  <button class="iconbtn b-bkview" title="看内容" v-html='ico("eye", "i")'
                          @click="viewFile(e)"></button>
                  <button class="iconbtn b-bkone" title="只恢复这一个（合并方式）"
                          v-html='ico("undo-2", "i")' @click="restore('merge', [e.rel])"></button>
                  <button class="iconbtn b-bkoutone" title="只导出这一个到上面的目标"
                          v-html='ico("corner-up-right", "i")' @click="exportTo([e.rel])"></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="BK.view" class="bk-view">
          <div class="bk-view-head">
            <span class="mono">{{ BK.view.rel }}</span>
            <span class="bk-hint" :title="'指纹 ' + BK.view.fp">
              {{ humanSize(BK.view.size) }}
              <span v-if="BK.view.binary" title="二进制内容，这里只给大小和头部字节">· 二进制</span>
              <span v-else-if="BK.view.truncated" title="文件太大，这里只给前一段；要看全的请导出/恢复出来">· 截断</span>
            </span>
            <span class="sp"></span>
            <button class="iconbtn b-bkviewclose" title="关掉" v-html='ico("x", "i")'
                    @click="closeView()"></button>
          </div>
          <pre v-if="BK.view.binary" class="bk-view-bin">（二进制内容，头部字节：{{ BK.view.head }}）</pre>
          <pre v-else class="bk-view-text" v-html="viewHTML"></pre>
        </div>

        <div v-if="BK.checkRows" class="bk-checkbar">
          <template v-for="(r, i) in BK.checkRows" :key="i"
            >{{ i ? " · " : "" }}{{ r.id.slice(-4) }}:
            <b :class="{bad: r.missing || r.broken}"
               >{{ r.broken ? "坏" : (r.missing ? ("缺 " + r.missing) : "好") }}</b
          ></template>
        </div>
      </template>
    </div>
  </div>
</div>`,
};

/* 把这一页塞进文件管理那个组件里（`js/files.js` 的模板里写着 `<moss-file-backup>`） */
MossFileManager.components.MossFileBackup = MossFileBackup;
