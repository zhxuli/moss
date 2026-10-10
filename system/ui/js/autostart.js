/* moss 界面 · autostart.js —— **自动启动**（`V-356` 起，`V-358` 搬到「详情」页）
   ============================================================================
   用户原话（2026-10-09）：
     · 「我希望可以增加一个 自动启动功能 就是启动moss的ui以后 可以自动启动一些插件或历史
        记录(可以自定义参数)」；
     · 后来（`V-358`）：「把那个自动启动放在详情里面去设置 而不是放到设置里面去 那样很不
        直观 那个地方可以编辑 删除 以及查看启动状态 … 添加和保存放在详情」。
   ⇒ 所以：**设置里那一组撤掉了**，入口在「详情」（包详情 / 历史详情各一块）：
       · 没加入 → 填参数 + 「加入自动启动」（= 添加）
       · 已加入 → 开关（看/改启动状态）+ 参数框（编辑）+ 「保存」+ 「删除」
       · **没有总开关** —— 每条自己一个开关（`V-316`：不用两个开关控一件事）
   值存在 `user_data/state/_ui_autostart.json`（宿主 `Api.autostart_get / autostart_set`），
   界面上这四下都是"改内存里那一份 → **整表**存回去"（跟插件列表排序一个路子：不会出现
   "保存漏了一半"）。

   ★ 这一页是**经典脚本**（和别的 js 一样共享全局）：顶层名字不许重名（`界面检查.py` 第 11 条）。
*/
const AUTO_MAX = 20;

/*: 内存里那一份自动启动：`{items: [...], loaded: bool}`。
    `items` 每项 = `{kind: "pkg"|"hist", id, args, cwd, name, on}`（`id`：包是包 id、
    历史是目标文件的绝对路径）。 */
const AUTO = {items: [], loaded: false};

/* 跑过没有 —— 自动启动只由**主窗口**做一次（浮动窗口不做；点刷新反复走 `init()` 也不重跑）。 */
let AUTORAN = false;

/* 一个条目的"人话名字"（历史那种 `name` 可能空着，就退回路径最后一段）。 */
function autoLabel(kind, id, name){
  if (name) return String(name);
  if (kind === "hist") return String(id || "").split(/[\\/]/).pop() || String(id || "");
  return PSYM + String(id || "");
}

/* 从内存那份里找"这个包 / 这条历史"的条目（没有回 null）。 */
function autoFind(kind, id){
  return (AUTO.items || []).find(x => x.kind === kind && String(x.id) === String(id)) || null;
}

/* ---------------------------------------------------------------- 列表上的记号（`V-366`）
   ★ 用户原话：「有时候 我们想找找到我们弄了哪些自动启动的项目 目前没有一个统一管理的方案
     我觉得可以这样设计 让自动运行的这种 列表这里 稍稍不一样」＋给了"左侧一条 3px 短竖线"的稿子。
   ⇒ 左边插件列表里，凡是**在自动运行名单里**的包，行首就多一条竖线（`.item.pkg-autorun`，
   样式在 `app.css`），鼠标停上去有 `title="已设置自动运行"`。 */
function autoPkgIds(){
  const s = new Set();
  (AUTO.items || []).forEach(x => { if (x.kind === "pkg" && x.id) s.add(String(x.id)); });
  return s;
}

/* 名单变了 ⇒ 让左边那份列表重画一遍（它是 Vue 组件，数据不是响应式的，靠举牌）。
   ★ 顺手在这儿做，不用担心"有几处忘了喊"（`autoLoad` 回来、启用、禁用都会经过它）。 */
function autoPaintMarks(){
  try{ if (typeof renderList === "function") renderList(); }catch(e){ /* 列表不在就算了 */ }
}

/* 读一次（`force` = 不管缓存重读，比如刚存完）。读不到**不抛**：详情页少一块，别的照旧。 */
async function autoLoad(force){
  if (AUTO.loaded && !force){ autoPaintMarks(); return AUTO.items; }
  let r = null;
  try{ r = await pywebview.api.autostart_get(); }catch(e){ r = null; }
  if (r && r.ok){
    AUTO.items = (r.items || []).map(x => Object.assign({}, x));
    AUTO.max = r.max || AUTO_MAX;
    AUTO.loaded = true;
  }
  autoPaintMarks();
  return AUTO.items;
}

/* 整表存回去；成功回 true。`msg` 是给状态栏/toast 的那句话。 */
async function autoPersist(msg){
  let r = null;
  try{ r = await pywebview.api.autostart_set(AUTO.items || []); }catch(e){ r = null; }
  if (!r || !r.ok){
    toast("✗ 没存上自动启动：" + ((r && r.msg) || "宿主没回话"), true);
    return false;
  }
  AUTO.items = (r.items || []).map(x => Object.assign({}, x));
  AUTO.loaded = true;
  if (msg) toast(msg);
  return true;
}

/* 造一条新条目（`opts` 里给历史的 name；`f.cwd` / `f.args` 是那两个框里的值）。
   ★ `V-364`：**工作路径（cwd）对包也一样能设**了 —— 以前只有历史那条带 cwd。 */
function autoMake(kind, id, opts, f){
  const o = opts || {};
  const v = f || {};
  return {kind: kind, id: String(id),
          args: String(v.args !== undefined ? v.args : ""),
          cwd: String(v.cwd !== undefined ? v.cwd : (o.cwd || "")),
          name: String(o.name || ""), on: true};
}

/* ★ `V-378`：改名跟随 —— 把名单里 `kind === "pkg"` 且 id 是**旧 id** 的那条改成新 id。
   （**只动 id 一个字段**，`args` / `cwd` / `on` 一个字不改；历史那几条的 id 是目标文件的
   绝对路径、跟包 id 没关系，一律不碰。）
   ★ 为什么非要有它：这份名单是**按包 id** 记的，而 `moss --rename` 只搬包目录和数据目录 ——
   不改这一条的话，那个包改完名之后：开机时它**跑不起来**（只报一句"找不到这个包"），
   界面上又**看不见**（详情页那一块是按 id 找的，新名字下显示"还没加入"），只能删掉重加。
   ★ 为什么先 `autoLoad(true)`：`AUTO.items` 是**懒加载**的（没打开过详情页就还是空表），
   不先读回来就成了"搬了个空"。
   ★ 存回去**不带提示**：改名那句「已跟随改名：…」由 `followRename` 统一说（一次动作一条提示）；
   只有真没存上时 `autoPersist` 才会自己报一句。回"搬了几条"。 */
async function autoRename(oldId, newId){
  if (!oldId || !newId || String(oldId) === String(newId)) return 0;
  await autoLoad(true);
  let n = 0;
  (AUTO.items || []).forEach(x => {
    if (x.kind === "pkg" && String(x.id) === String(oldId)){ x.id = String(newId); n++; }
  });
  if (n) await autoPersist();
  autoPaintMarks();                      // 列表上那条「自动运行」竖线跟着挪到新名字
  return n;
}

/* ---------------------------------------------------------------- 详情页那一块
   `kind` = "pkg" | "hist"；`id` = 包 id / 历史的目标路径；`opts` 给 hist 的 cwd+name。
   同步返回 HTML（详情页是"重画一遍"的写法，所以这里不 await —— 缓存里没有就先画"未启用"，
   `autoWire` 里读完再重画一次）。

   ★ `V-361`（你 2026-10-09 的反馈，照稿子的 `toggleAutoStart` 一比一）：
     · **只有一颗按钮**：`圆圈对号 + 启用` / `圆圈斜线 + 禁用` —— 没有"保存"、没有"删除"；
     · **禁用 = 从自动启动里拿掉**（你说的"禁用就是删除"）；
     · 那一组输入平时收起来，点了「启用」才滑出来；
     · **说明那一行一直是「随宿主程序启动时自动初始化」**，不显示别的。
   ★ `V-363`：标题是 **「自动运行」**（跟"开机"没关系，是**开 moss 界面**时跑）；
     存完给提示（回车 / 失焦都算），见 `autoSavedHint()`。
   ★ `V-364`（你 2026-10-09 给的新稿子）：那一组里现在是**两个框** ——
     **工作路径**（可以**点选**〔系统文件夹对话框〕、**鼠标拖进来**、或者**手输**）+ **启动参数**。 */
function autoSectionHTML(kind, id, opts){
  const it = autoFind(kind, id);
  const on = !!(it && it.on !== false);
  return '<div class="dp-item" id="auto-sec">' +
      '<div class="dp-item-info">' +
        '<span class="dp-item-ico">' + ico("rocket", "i") + '</span>' +
        '<div class="dp-item-text">' +
          '<h4>自动运行' +
            '<span class="dp-tip dp-tip-ico" data-tip="开 moss 界面时自动跑一次">' +
              ico("info", "i") + '</span>' +
          '</h4>' +
          '<p class="auto-st">随宿主程序启动时自动初始化</p>' +
        '</div>' +
      '</div>' +
      '<div class="dp-item-acts">' +
        // 那两个框（工作路径 + 启动参数）平时收着，启用才展开（稿子 `.expandable-panel`）
        '<div class="dp-expand' + (on ? " show" : "") + '" id="auto-panel">' +
          '<div class="dp-pathgroup" id="auto-dropzone" title="可以把文件夹拖到这里">' +
            '<input type="text" id="auto-cwd" placeholder="工作路径 (拖拽或点选)"' +
              ' spellcheck="false" autocomplete="off" value="' + esc(it ? it.cwd : "") + '">' +
            '<button type="button" class="dp-browse dp-tip" id="btn-auto-pick"' +
              ' data-tip="浏览目录">' + ico("folder-open", "i") + '</button>' +
          '</div>' +
          '<input type="text" class="dp-param" id="auto-args" placeholder="启动参数 (选填)"' +
            ' spellcheck="false" autocomplete="off" value="' + esc(it ? it.args : "") + '">' +
        '</div>' +
        '<button type="button" class="dp-ghost' + (on ? " on" : "") + '" id="auto-sw"' +
          ' role="switch" aria-checked="' + (on ? "true" : "false") + '" title="' +
          (on ? "现在跟着启动 —— 点一下禁用（等于从自动启动里拿掉）"
              : "点一下让它跟着启动，然后填工作路径 / 启动参数") + '">' +
          ico(on ? "circle-slash" : "circle-check", "i") +
          '<span>' + (on ? "禁用" : "启用") + '</span></button>' +
      '</div>' +
    '</div>';
}

/* 接线（在 `wireDetail` / `wireDetailHist` 里各调一次）。
   ★ `V-361`：那一颗按钮就是"加/删"，所以按下去要么整条加进去、要么整条拿掉；
     那两个框（工作路径 / 启动参数）走**回车 / 失焦即存**（不用多点一次保存）。
   ★ `V-364`：工作路径三条路都通 —— **点选**（系统文件夹对话框）、**拖进来**、**手输**。 */
async function autoWire(kind, id, opts){
  const o = opts || {};
  const before = AUTO.loaded;
  await autoLoad();
  // 第一次读回来跟刚才画的不一样（缓存里本来没有）⇒ 重画一次，让"启用/禁用"对上
  if (!before && AUTO.loaded && typeof renderDetail === "function") renderDetail();
  const args = $("#auto-args"), cwd = $("#auto-cwd"), sw = $("#auto-sw");
  // 记一下"现在这一页是哪一条"（拖进来的落地口 `__mossAutoDrop` 要用它找回那一条）
  AUTO.curKind = kind;
  AUTO.curId = String(id);

  if (sw) sw.onclick = async () => {
    const it = autoFind(kind, id);
    if (it){                                   // 已经启用 ⇒ **禁用就是删除**
      AUTO.items = (AUTO.items || []).filter(
        x => !(x.kind === kind && String(x.id) === String(id)));
      // ★ `V-365`：**只给一处提示**（以前 `autoPersist` 那句走 toast ⇒ 状态栏 + 深色胶囊
      //   两下一起弹，你数成"2 个弹窗"）。这里改成跟"存参数"同一套**行内**提示；
      //   ⚠️ 顺序要紧：`renderDetail()` 会把整块 DOM 换掉，所以提示要等重画之后再冒
      //   （不然刚插进去就被冲掉、一个字都看不见）。
      await autoPersist("");
      renderDetail();
      setTimeout(() => autoSavedHint($("#auto-sw"), "已移除"), 60);
      autoPaintMarks();                       // `V-366`：左边列表那条竖线跟着消失
      return;
    }
    if ((AUTO.items || []).length >= (AUTO.max || AUTO_MAX)){
      toast("自动启动最多 " + (AUTO.max || AUTO_MAX) + " 条", true); return;
    }
    // 新启用：路径默认给"它本来会在哪儿跑"（包自己的目录 / 历史当初那个目录），参数先空着
    AUTO.items.push(autoMake(kind, id, o, {cwd: o.cwd || "", args: ""}));
    await autoPersist("");
    renderDetail();
    setTimeout(() => autoSavedHint($("#auto-sw"), "已启用"), 60);
    autoPaintMarks();                         // `V-366`：左边列表那条竖线跟着出现
    // 稿子那句 `inputField.focus()`：展开之后光标落在**启动参数**框里。
    // ★ 不能只 `setTimeout(…, 30)`：`renderDetail()` 是**异步重画**（Vue 下一拍），
    //   定时器早了就 focus 到一个马上要被换掉的老节点上，光标又没了（预览里量到过）。
    //   所以盯几拍，直到焦点真的落到那个框上为止。
    let tries = 0;
    const tick = () => {
      const box = $("#auto-args");
      if (box){
        try{ box.focus(); }catch(e){ /* 聚焦失败不值得报错 */ }
        if (document.activeElement === box) return;
      }
      if (++tries < 15) setTimeout(tick, 30);
    };
    setTimeout(tick, 0);
  };

  // 两个框：回车 / 失焦都存，存完给提示（`V-363`）
  [cwd, args].forEach(box => {
    if (!box) return;
    box.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      if (await autoSaveFields(kind, id)) autoSavedHint(box);
    });
    box.addEventListener("blur", async () => {
      if (await autoSaveFields(kind, id)) autoSavedHint(box);
    });
  });

  // ---- 工作路径：点选（系统文件夹对话框）
  const pick = $("#btn-auto-pick");
  if (pick) pick.onclick = async () => {
    let r = null;
    try{ r = await pywebview.api.pick_dir(cwd ? cwd.value : ""); }catch(e){ r = null; }
    if (!r || !r.ok){
      if (!(r && r.cancelled)) toast("挑目录失败：" + ((r && r.msg) || "没回话"), true);
      return;
    }
    if (cwd) cwd.value = String(r.path || "");
    if (await autoSaveFields(kind, id)) autoSavedHint(cwd || pick);  };

  // ---- 工作路径：拖进来（真路径只有宿主知道 ⇒ 落到下面的 `__mossAutoDrop` 里取）
  const zone = $("#auto-dropzone");
  if (zone){
    zone.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
      AUTO.dragOn = true;
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", (ev) => {
      if (ev.relatedTarget && zone.contains(ev.relatedTarget)) return;
      zone.classList.remove("drag-over");
    });
    zone.addEventListener("drop", (ev) => {
      // ★ 只 preventDefault、**不要 stopPropagation** —— 真路径是宿主在 document 那一层
      //   收下、再回头调 `window.__mossDrop` 送进来的（`V-204`/`V-205`）；这里拦住就断了。
      ev.preventDefault();
      zone.classList.remove("drag-over");
    });
  }
}

/* 宿主把拖进来的真路径交给这儿（`V-364`）—— 见 `drop.js` 的 `__mossDrop`。
   只有"这次拖的落点确实是那个工作路径框"（`AUTO.dragOn`）才收下，否则交回给别的落地口。 */
window.__mossAutoDrop = function(items){
  if (!AUTO.dragOn) return false;
  AUTO.dragOn = false;
  const zone = $("#auto-dropzone");
  if (zone) zone.classList.remove("drag-over");
  const box = $("#auto-cwd");
  if (!box || !items || !items.length) return false;
  // 拖的是**文件夹**就用它自己；拖的是**文件**就用它所在的目录（宿主把 `dir` 一起给了）
  const it = items[0];
  const p = it.isDir ? it.path : (it.dir || "");
  if (!p) return false;
  box.value = String(p);
  // 拖进来的这一刻就存（不用再回车）—— 存完照旧给提示
  Promise.resolve().then(async () => {
    if (await autoSaveFields(AUTO.curKind, AUTO.curId)) autoSavedHint(box);
  });
  return true;
};

/* 把这两个框里的值存回这一条（**不重画详情页** —— 一重画框就没了、焦点也丢了）。
   两边都没变就不白写一次盘。 */
async function autoSaveFields(kind, id){
  const it = autoFind(kind, id);
  if (!it) return false;
  const cwdBox = $("#auto-cwd"), argBox = $("#auto-args");
  const next = {cwd: cwdBox ? String(cwdBox.value || "") : String(it.cwd || ""),
                args: argBox ? String(argBox.value || "") : String(it.args || "")};
  if (String(it.cwd || "") === next.cwd && String(it.args || "") === next.args) return false;
  it.cwd = next.cwd;
  it.args = next.args;
  return await autoPersist("");                          // 静默存，提示交给 autoSavedHint 单独给
}

/* ★ `V-363`（你 2026-10-09 说的：「保存以后 你倒是给个提示啊」）—— 存完在这一行里给个提示：
     ① 输入框**变一下绿**（`.saved`）；
     ② 旁边**冒一句短的**（「已保存」/「已启用」/「已移除」），1.6 秒后自己消失。
   ★ `V-365`：**不用 `toast()`**（你报的"禁用的时候出现了 2 个弹窗"）—— `toast()` 是
     "状态栏 + 一颗深色胶囊"两处一起报（`V-61` 的规矩），这一行的小动作看着就是弹了两下。
   ★ `V-366`：**连状态栏那一行也不要了**（你说「左下角显示 自动运行: 已禁用(已移除) 这是啥意思
     …给我去掉」）—— 就这么一下小动作，只留**贴着控件的那一句**，别去动全局那条状态栏。 */
function autoSavedHint(box, text){
  if (box) flashAutoInput(box);
  const words = String(text || "已保存");
  try{
    const host = (box && box.parentElement) ||
                 document.querySelector("#auto-sec .dp-item-acts");
    if (!host) return;
    let hint = host.querySelector(".dp-saved");
    if (!hint){
      hint = document.createElement("span");
      hint.className = "dp-saved";
      host.appendChild(hint);
    }
    hint.textContent = words;
    hint.classList.add("on");
    clearTimeout(hint._t);
    hint._t = setTimeout(() => { try{ hint.remove(); }catch(e){} }, 1600);
  }catch(e){ /* 拿不到 DOM 就算了，框变绿那一下还在 */ }
}

/* 「变色」那一下：给输入框挂个 `.saved`，不到一秒就摘掉（稿子没有这一段，是你点名要的）。 */
function flashAutoInput(box){
  try{
    box.classList.add("saved");
    setTimeout(() => box.classList.remove("saved"), 900);
  }catch(e){ /* 拿不到就算了，别为一下颜色报错 */ }
}

/* ---------------------------------------------------------------- 启动时跑一次（`V-356`）
   ★ 只在**主窗口**做、而且**一辈子只做一次**（浮动窗口不做；点刷新反复走 `init()` 也不重跑）。
   ★ 每条之间隔 700 毫秒：一次全塞进去会让它们挤成一团（下面那条更要紧）。
   ★★ `V-365`（你 2026-10-09 报的「设了 2 个自启动，只能启动一个；日志还全串在一屏」）：
     **这批一律走"自己的管道"（`{noTerm:true}`），不敲进那个常驻终端。**
     终端只有**一条 shell**：第一个包还占着它的时候，第二条命令是敲进**那个包的 stdin** 的
     （不是新起一个）⇒ 第二个起不来、而且所有包的日志挤在同一块屏上，各包自己的「包输出」
     反倒空着。自启动是"后台起一批"，本来就该各走各的管道、各进各的输出缓冲。 */
async function autostartRun(){
  if (FLOAT_PID || AUTORAN) return;
  AUTORAN = true;
  await autoLoad(true);
  const items = (AUTO.items || []).filter(x => x.on !== false);
  const done = [], failed = [];
  for (let i = 0; i < items.length; i++){
    const it = items[i];
    try{
      if (it.kind === "hist"){
        // 历史那条：和"点一下再跑一次"走同一条路（`path_start`，在它当初的目录里跑）
        const nm = autoLabel("hist", it.id, it.name);
        await rerunHist({target: it.id, cwd: it.cwd || "", name: nm, args: it.args || ""},
                        it.args || "");
        done.push(nm);
      }else{
        const p = (DATA.packages || []).find(x => x.id === it.id);
        if (!p){ failed.push(it.id + "（找不到这个包）"); continue; }
        // 工作路径 = 第三个参数；`noTerm` = 各走各的管道（见上面那段）
        await startRun(p, it.args || "", it.cwd || "", {noTerm: true});
        done.push(PSYM + p.id);
      }
    }catch(e){ failed.push(it.id + "：" + ((e && e.message) || e)); }
    await new Promise(r => setTimeout(r, 700));
  }
  // ★ 收尾只报**一处**（状态栏那一行）—— 但 `V-366` 之后连那行也去掉了：
  //   自启动是开机就跑的，"起了几个"这句话放在**左边列表的竖线**上更省事（`V-366`），
  //   真起不来的时候（找不到包 / 起进程报错）才值得说一句，而且只说**失败**那一半。
  const bad = failed.length;
  if (bad){
    try{ setStatus("自动运行：" + bad + " 个没起来 —— " + failed.join("、")); }
    catch(e){ /* 状态栏不在就算了 */ }
  }
}
