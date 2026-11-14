/* 左侧列表的「分组」：谁在哪一组、组叫什么、组的先后，都只存在这里
 *   user_data/state/_ui_groups.json   （跟 _ui_order.json / _ui_autostart.json 一层）
 *
 * 为什么不用 localStorage：换个窗口 / 清了缓存就没了，配置搬家也带不走。
 * 为什么不塞 config.toml：那边是设置界面的表单（有 rules 校验），放不下"谁在哪组"这种自由结构。
 *
 * 同步规则（每次启动 + 每次包列表刷新都会 sync 一遍）：
 *   · 组里记着的包已经不在了（卸载了 / 改过 id）→ 从组里摘掉，顺手落盘；
 *   · 没被任何组收着的包 → 显示在「未分组」那一段（这是显示规则，不写盘）。
 */

const GROUPS = Vue.reactive({
  rev: 0,
  ready: false,
  persist: false,           // 读盘成功才允许写盘（免得读失败时把用户的分组冲成空的）
  list: [],                 // [{id, name, ids: [...], collapsed}]
  ungroupedCollapsed: false,
  dropGid: null,            // 拖着插件时，正压在哪个分组标题上（"" / "__free__" / 组 id）
  saved: "",                // 上次写进盘的内容，一样就不再写
});

const GROUP_NAME_MAX = 40;
const GROUP_MAX = 60;
const GROUP_IDS_MAX = 400;

function groupById(gid){ return GROUPS.list.find(g => g.id === gid) || null; }
function groupOfPkg(id){
  return GROUPS.list.find(g => (g.ids || []).indexOf(id) >= 0) || null;
}
function groupLabel(g){ return (g && g.name) || "分组"; }
function groupFreeLabel(gid){
  if (gid === "__free__" || !gid) return "未分组";
  return groupLabel(groupById(gid));
}
function groupUid(){
  return "g" + Date.now().toString(36).slice(-5) + Math.random().toString(36).slice(2, 6);
}

/* 要写盘的样子（字段顺序固定，好在外面比较"有没有变"） */
function groupsPack(){
  return {
    ungrouped_collapsed: !!GROUPS.ungroupedCollapsed,
    groups: GROUPS.list.map(g => ({id: g.id, name: g.name || "分组",
                                   collapsed: !!g.collapsed,
                                   ids: (g.ids || []).slice(0, GROUP_IDS_MAX)})),
  };
}

let groupsTimer = null;
let groupsSaving = false;
let groupsDirty = false;

/* 改完就调它：合并 120ms 内的连续改动再写盘（拖动分组、连点折叠不会把盘写烂） */
function saveGroups(){
  GROUPS.rev++;
  if (groupsTimer) clearTimeout(groupsTimer);
  groupsTimer = setTimeout(() => { groupsTimer = null; groupsFlush(); }, 120);
}

async function groupsFlush(){
  /* 还没读完盘（或读盘失败）时绝不写：这时候 list 是空的，写下去就把用户的分组冲没了 */
  if (!GROUPS.ready || !GROUPS.persist) return;
  if (groupsSaving){ groupsDirty = true; return; }
  const blob = groupsPack();
  const text = JSON.stringify(blob);
  if (text === GROUPS.saved) return;
  groupsSaving = true;
  try{
    const r = await pywebview.api.list_groups_set(blob.groups, blob.ungrouped_collapsed);
    if (r && r.ok) GROUPS.saved = text;
  }catch(e){
    /* 写不进去也不该把界面搞崩：下次改动会再试 */
  }
  groupsSaving = false;
  if (groupsDirty){ groupsDirty = false; groupsFlush(); }
}

async function loadGroups(){
  if (groupsTimer){ clearTimeout(groupsTimer); groupsTimer = null; }
  await groupsFlush();                      // 刚改过还没落盘的，先落盘，别被下面的读取盖掉
  let r = null;
  try{ r = await pywebview.api.list_groups(); }
  catch(e){ r = {ok: false, msg: (e && e.message) || String(e)}; }
  const ok = !!(r && r.ok);
  GROUPS.persist = ok;
  if (ok && Array.isArray(r.groups)){
    GROUPS.list = r.groups.map(g => ({
      id: String(g.id || groupUid()),
      name: String(g.name || "分组").slice(0, GROUP_NAME_MAX),
      ids: (g.ids || []).map(String),
      collapsed: !!g.collapsed,
    }));
    GROUPS.ungroupedCollapsed = !!r.ungrouped_collapsed;
  }
  GROUPS.ready = true;
  GROUPS.saved = JSON.stringify(groupsPack());
  if (groupsSync()) saveGroups();          // 上次到现在删过包 → 顺手把盘也修干净
  GROUPS.rev++;
  if (!ok){
    toast("分组文件读不出来（" + ((r && r.msg) || "宿主没回话") +
          "）—— 这次改的分组不会保存", true);
  }
}

/* 把"已经不在的包"从各组里摘掉、去掉重复；返回有没有改动 */
function groupsSync(){
  const known = new Set((DATA && DATA.packages ? DATA.packages : []).map(p => p.id));
  const seen = new Set();
  const before = JSON.stringify(groupsPack());
  const out = [];
  GROUPS.list.forEach(g => {
    const ids = [];
    (g.ids || []).forEach(id => {
      const s = String(id || "");
      if (!s || !known.has(s) || seen.has(s)) return;
      seen.add(s);
      ids.push(s);
    });
    out.push({id: g.id, name: g.name, collapsed: !!g.collapsed, ids: ids});
  });
  GROUPS.list = out;
  GROUPS.rev++;
  return before !== JSON.stringify(groupsPack());
}

/* 包列表变了（刷新 / 卸载 / 新建）之后调一次 */
function groupsRefresh(){
  if (!GROUPS.ready) return;
  if (groupsSync()) saveGroups();
}

/* 包改 id 的时候（moss --rename 或界面里更名）：组里的记录跟着改，别丢分组。
   ★ 这里不能顺手 groupsSync()：改名时 DATA 里还是旧 id，同步会把刚换上的新 id 当成
     "已经不存在的包" 扔掉（要等 refreshPkgs 之后 DATA 更新了再同步）。 */
function groupsRenamePkg(oldId, newId){
  if (!oldId || !newId || oldId === newId || !GROUPS.list.length) return;
  let changed = false;
  GROUPS.list.forEach(g => {
    const i = (g.ids || []).indexOf(oldId);
    if (i >= 0){ g.ids[i] = newId; changed = true; }
  });
  if (!changed) return;
  const seen = new Set();
  GROUPS.list.forEach(g => {
    g.ids = (g.ids || []).filter(id => {
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  });
  saveGroups();
}

/* ---------- 改分组 ---------- */

function groupSetPkg(id, gid){
  id = String(id || "");
  if (!id) return false;
  const tgt = gid ? groupById(gid) : null;
  if (gid && !tgt) return false;
  let changed = false;
  GROUPS.list.forEach(g => {
    if (g === tgt) return;
    const i = (g.ids || []).indexOf(id);
    if (i >= 0){ g.ids.splice(i, 1); changed = true; }
  });
  if (tgt && (tgt.ids || []).indexOf(id) < 0){
    tgt.ids.push(id);
    changed = true;
  }
  if (changed) saveGroups();
  return changed;
}

function groupNew(name, ids, afterGid){
  const nm = String(name || "").replace(/\s+/g, " ").trim().slice(0, GROUP_NAME_MAX) || "新分组";
  const g = {id: groupUid(), name: nm, collapsed: false, ids: []};
  const at = afterGid ? GROUPS.list.findIndex(x => x.id === afterGid) : -1;
  if (at >= 0) GROUPS.list.splice(at + 1, 0, g);
  else GROUPS.list.push(g);
  saveGroups();
  (ids || []).forEach(id => groupSetPkg(id, g.id));   // 顺手从别的组挪过来（一个包只在一组）
  return g;
}

function groupNewAsk(ids, afterGid){
  if (GROUPS.list.length >= GROUP_MAX){
    toast("分组最多 " + GROUP_MAX + " 个", true);
    return;
  }
  const tip = (ids && ids.length) ? "给这一组起个名字（" + ids.map(x => PSYM + x).join("、") + " 会放进去）"
                                 : "给这一组起个名字（建好后，右键插件 →「移到分组」放进去）";
  askText(tip, "", (v) => {
    const nm = String(v || "").replace(/\s+/g, " ").trim();
    if (!nm) return;
    const g = groupNew(nm, ids || [], afterGid);
    toast("已新建分组「" + groupLabel(g) + "」");
  });
}

function groupRename(g){
  if (!g) return;
  askText("给分组改名", g.name || "", (v) => {
    const nm = String(v || "").replace(/\s+/g, " ").trim().slice(0, GROUP_NAME_MAX);
    if (!nm || nm === g.name) return;
    g.name = nm;
    saveGroups();
    toast("分组已改名：" + nm);
  });
}

function groupDel(g){
  if (!g) return;
  const n = (g.ids || []).length;
  askConfirm("删掉这个分组",
    "「" + esc(groupLabel(g)) + "」里的 <b>" + n + "</b> 个插件会退回「未分组」，插件本身不动。" +
    "<br><br>确定删掉这个分组吗？",
    () => {
      GROUPS.list = GROUPS.list.filter(x => x.id !== g.id);
      saveGroups();
      toast("已删掉分组：" + groupLabel(g));
    });
}

function groupMove(g, dir){
  const i = GROUPS.list.indexOf(g), j = i + dir;
  if (i < 0 || j < 0 || j >= GROUPS.list.length) return;
  const arr = GROUPS.list.slice();
  arr.splice(i, 1);
  arr.splice(j, 0, g);
  GROUPS.list = arr;
  saveGroups();
}

function groupToggle(g, val){
  if (!g) return;
  const want = (val === undefined) ? !g.collapsed : !!val;
  if (!!g.collapsed === want) return;
  g.collapsed = want;
  saveGroups();
}

function groupsToggleFree(val){
  const want = (val === undefined) ? !GROUPS.ungroupedCollapsed : !!val;
  if (!!GROUPS.ungroupedCollapsed === want) return;
  GROUPS.ungroupedCollapsed = want;
  saveGroups();
}

function groupsCollapseAll(on){
  GROUPS.list.forEach(g => { g.collapsed = !!on; });
  GROUPS.ungroupedCollapsed = !!on;
  saveGroups();
}

/* ---------- 菜单（跟文件管理共用 #ctxmenu） ---------- */

function ctxMenuOpen(x, y, items){
  const menu = $("#ctxmenu");
  if (!menu) return;
  menu.innerHTML = items.map(it => {
    if (it.sep) return '<div class="sep"></div>';
    const cls = "mi" + (it.dis ? " dis" : "") + (it.danger ? " danger" : "");
    return '<div class="' + cls + '"' +
      (it.tip ? ' title="' + esc(it.tip) + '"' : "") + '>' +
      ico(it.icon || "file", "i") + '<span>' + esc(it.label) + '</span>' +
      (it.note ? '<span class="mi-note">' + esc(it.note) + '</span>' : "") + '</div>';
  }).join("");
  menu.hidden = false;
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.max(6, Math.min(x, window.innerWidth - w - 8)) + "px";
  menu.style.top = Math.max(6, Math.min(y, window.innerHeight - h - 8)) + "px";
  let k = 0;
  menu.querySelectorAll(".mi").forEach(node => {
    const it = items.filter(x => !x.sep)[k++];
    if (!it || it.dis || !it.run) return;
    node.onclick = (ev) => {
      ev.stopPropagation();
      hideCtx();
      try{ it.run(); }
      catch(e){ reportError("分组菜单", (e && e.message) || String(e), (e && e.stack) || ""); }
    };
  });
}

function groupBarMenu(x, y){
  const anyOpen = GROUPS.list.some(g => !g.collapsed);
  const anyClosed = GROUPS.list.some(g => g.collapsed);
  ctxMenuOpen(x, y, [
    {icon: "folder-plus", label: "新建分组…", run: () => groupNewAsk()},
    {sep: true},
    {icon: "chevron-down", label: "全部展开", dis: !anyClosed,
     run: () => { groupsCollapseAll(false); toast("分组都展开了"); }},
    {icon: "chevron-right", label: "全部收起", dis: !anyOpen,
     run: () => { groupsCollapseAll(true); toast("分组都收起了"); }},
    {sep: true},
    {icon: "trash-2", label: "清掉所有分组…", danger: true, dis: !GROUPS.list.length,
     tip: "只删分组这层壳：插件都退回「未分组」，插件本身不动",
     run: () => {
       askConfirm("清掉所有分组",
         "一共 <b>" + GROUPS.list.length + "</b> 个分组会被删掉，里面的插件全部退回「未分组」" +
         "（插件本身不动）。<br><br>确定吗？",
         () => {
           GROUPS.list = [];
           GROUPS.ungroupedCollapsed = false;
           saveGroups();
           toast("分组已经清掉了");
         });
     }},
  ]);
}

function groupHeadMenu(g, x, y){
  if (!g) return;
  const i = GROUPS.list.indexOf(g), n = GROUPS.list.length;
  ctxMenuOpen(x, y, [
    {icon: "pencil", label: "重命名分组…", run: () => groupRename(g)},
    {icon: "arrow-up", label: "上移", dis: i <= 0, run: () => groupMove(g, -1)},
    {icon: "arrow-down", label: "下移", dis: i >= n - 1, run: () => groupMove(g, 1)},
    {sep: true},
    {icon: "folder-plus", label: "在它后面新建分组…", run: () => groupNewAsk([], g.id)},
    {icon: g.collapsed ? "chevron-down" : "chevron-right",
     label: g.collapsed ? "展开这个分组" : "收起这个分组",
     run: () => groupToggle(g)},
    {sep: true},
    {icon: "trash-2", label: "删掉这个分组", danger: true,
     tip: "里面的插件退回「未分组」，插件本身不动",
     run: () => groupDel(g)},
  ]);
}

function groupFreeMenu(x, y){
  ctxMenuOpen(x, y, [
    {icon: GROUPS.ungroupedCollapsed ? "chevron-down" : "chevron-right",
     label: GROUPS.ungroupedCollapsed ? "展开「未分组」" : "收起「未分组」",
     run: () => groupsToggleFree()},
    {sep: true},
    {icon: "pencil", label: "这一段是自动的：没进任何分组的插件都在这儿", dis: true},
  ]);
}

function pkgGroupMenu(id, x, y){
  if (!(DATA && DATA.packages || []).some(x => x.id === id)) return;
  const now = groupOfPkg(id);
  const items = [{icon: "package", label: PSYM + id, dis: true}];
  if (GROUPS.list.length) items.push({sep: true});
  GROUPS.list.forEach(g => {
    const isNow = !!now && now.id === g.id;
    items.push({icon: isNow ? "check" : "folder", label: groupLabel(g),
                note: isNow ? "当前" : "", dis: isNow,
                run: () => {
                  if (groupSetPkg(id, g.id))
                    toast("已把 " + PSYM + id + " 移到「" + groupLabel(g) + "」");
                }});
  });
  if (now){
    items.push({icon: "circle-slash", label: "移出分组（回「未分组」）",
                run: () => {
                  if (groupSetPkg(id, "")) toast("已把 " + PSYM + id + " 移回「未分组」");
                }});
  }
  items.push({sep: true});
  items.push({icon: "folder-plus", label: "新建分组并放进来…",
              run: () => groupNewAsk([id])});
  ctxMenuOpen(x, y, items);
}

/* 顶部工具栏那个「分组」按钮的菜单 */
function groupsBarClick(ev){
  if (ev) ev.stopPropagation();
  const b = $("#btn-groups");
  if (!b) return;
  const r = b.getBoundingClientRect();
  groupBarMenu(r.left, r.bottom + 4);
}
