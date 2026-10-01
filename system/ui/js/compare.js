/* moss 界面 · js/compare.js —— 文件对比窗口（`V-109`）
   ============================================================================
   一句话：**左边 = 现在这个文件，右边 = 它最新那份快照**，两栏对齐、按行标出来。
   ★ 只借人家的**库**：`vendor/difflib.js`（jsdifflib 的 SequenceMatcher，BSD，离线零依赖）
     负责算 opcodes；**界面是我们自己的** —— 不抄它那套表格，配色/字体/间距全用这套令牌：
     新增行=绿、删掉行=红、改动行=琥珀（和文件列表里那份差异色是同一套语义）。
   ★ 为什么不是"真开一个独立窗口"：WebView2 下 `window.open` 会被拦、pywebview 在启动后
     再开窗口各平台行为不一；这里用一个**整屏浮层**当窗口（自己的标题栏 + 关掉按钮），
     长得就是"弹出来一个窗口"，而且不会踩平台的坑。
   ============================================================================ */

/* 把两段文本按行比出来：返回 {html, same, add, del, chg} */
function cmpBuild(leftText, rightText){
  const A = String(leftText == null ? "" : leftText).split(/\r?\n/);
  const B = String(rightText == null ? "" : rightText).split(/\r?\n/);
  let ops;
  try{ ops = new difflib.SequenceMatcher(A, B).get_opcodes(); }
  catch(e){ ops = [["replace", 0, A.length, 0, B.length]]; }
  const out = [];
  let same = 0, add = 0, del = 0, chg = 0;
  const row = (cls, al, at, bl, bt) =>
    '<div class="cmp-row ' + cls + '">' +
      '<span class="cmp-ln">' + (al == null ? "" : al) + '</span>' +
      '<span class="cmp-tx">' + (at == null ? "" : esc(at)) + '</span>' +
      '<span class="cmp-ln">' + (bl == null ? "" : bl) + '</span>' +
      '<span class="cmp-tx">' + (bt == null ? "" : esc(bt)) + '</span>' +
    '</div>';
  ops.forEach(function(op){
    const tag = op[0], i1 = op[1], i2 = op[2], j1 = op[3], j2 = op[4];
    let k;
    if (tag === "equal"){
      for (k = 0; k < i2 - i1; k++) out.push(row("same", i1 + k + 1, A[i1 + k], j1 + k + 1, B[j1 + k]));
      same += i2 - i1;
    }else if (tag === "delete"){
      for (k = i1; k < i2; k++) out.push(row("del", k + 1, A[k], null, null));
      del += i2 - i1;
    }else if (tag === "insert"){
      for (k = j1; k < j2; k++) out.push(row("ins", null, null, k + 1, B[k]));
      add += j2 - j1;
    }else{
      const m = Math.max(i2 - i1, j2 - j1);
      for (k = 0; k < m; k++){
        const ai = (i1 + k < i2) ? (i1 + k) : null, bj = (j1 + k < j2) ? (j1 + k) : null;
        out.push(row("chg", ai == null ? null : ai + 1, ai == null ? null : A[ai],
                            bj == null ? null : bj + 1, bj == null ? null : B[bj]));
      }
      chg += m;
    }
  });
  return {html: out.join(""), same: same, add: add, del: del, chg: chg};
}

function cmpClose(){ const w = document.querySelector("#cmpwin"); if (w) w.remove(); }

/* 弹出来（整屏浮层当窗口） */
function cmpShow(left, right, hint){
  cmpClose();
  const r = cmpBuild(left.text, right.text);
  const win = document.createElement("div");
  win.id = "cmpwin";
  win.innerHTML =
    '<div class="cmp-card">' +
      '<div class="cmp-head">' +
        '<span class="cmp-title">' + esc(left.name || "") + '</span>' +
        '<span class="cmp-stat">一致 ' + r.same + ' · 改了 ' + r.chg +
          ' · 多了 ' + r.add + ' · 少了 ' + r.del + '</span>' +
        '<span class="sp"></span>' +
        (hint ? '<span class="cmp-hint">' + esc(hint) + '</span>' : '') +
        '<button class="iconbtn cmp-x" title="关掉（Esc）"></button>' +
      '</div>' +
      '<div class="cmp-body">' +
        '<div class="cmp-row cmp-hd">' +
          '<span class="cmp-ln"></span><span class="cmp-tx">现在：' + esc(right.now || "") + '</span>' +
          '<span class="cmp-ln"></span><span class="cmp-tx">快照：' + esc(left.snap || "") + '</span>' +
        '</div>' + r.html +
      '</div>' +
    '</div>';
  document.body.appendChild(win);
  const x = win.querySelector(".cmp-x");
  x.innerHTML = ico("x", "i");
  x.onclick = cmpClose;
  win.addEventListener("click", function(ev){ if (ev.target === win) cmpClose(); });
  win.tabIndex = -1;
  win.addEventListener("keydown", function(ev){ if (ev.key === "Escape") cmpClose(); });
  win.focus();
  return r;
}

/* 文件列表里那颗对比图标点了走这里（左边=现在，右边=快照那一份） */
async function bkCompareOpen(rel){
  const d = (BKD.diff && BKD.diff.byRel) ? BKD.diff.byRel[rel] : null;
  if (!d || !d.snap){ toast("这个文件没有快照版本，没得比", true); return; }
  const group = d.snap.group || bkGroupForCtx();
  try{
    const cur = await pywebview.api.fs_read(rel);
    if (!cur || !cur.ok){ toast("✗ 读不了现在这个文件：" + ((cur && cur.msg) || ""), true); return; }
    const snap = await pywebview.api.backup_blob(d.snap.fp, group);
    if (!snap || !snap.ok){ toast("✗ 读不了快照里那一份：" + ((snap && snap.msg) || ""), true); return; }
    if (snap.binary){ toast("快照里那份是二进制文件，内容没法按行比", true); return; }
    const nm = String(d.rel || rel).split("/").pop();
    cmpShow({snap: nm, text: snap.text || ""},
            {now: nm, text: cur.text || ""},
            d.state === "diff" ? "两边不一样 · 按行对齐看" : "两边内容一样");
  }catch(e){ reportError("打开对比失败", String((e && e.message) || e)); }
}


/* `V-122`：创建快照那个模态框的关闭（和对比窗口一个套路：整屏浮层 + 自己的标题栏） */
function snapClose(){ const w = document.querySelector("#snapwin"); if (w) w.remove(); }


/* ================================================================ 预设过滤规则（`V-121`/`V-126`）
   ★ 为什么放前端算（`V-126`）：文件管理**已经把"当前目录这一层"加载在 `FM.st[ctx].entries` 里了**，
     预设匹配就是拿这一层的名字去比 —— 前端算即时、零往返、改起来也不用重启宿主；
     宿主那份 `backup_presets()` 只当兜底（当前这一层还没加载时才去问它）。
   ★ 这张表**只有一份**（前端），宿主的 `PRESET_FILTERS` 只在兜底那条路用，两边内容要一致。 */
const SNAP_PRESETS = [
  {id: "logs",    label: "日志",           pat: ["*.log"],                                        why: "跑起来才产生的日志，通常不用留版本"},
  {id: "media",   label: "视频 / 音频",     pat: ["*.mp4", "*.mov", "*.avi", "*.mkv", "*.mp3", "*.wav"], why: "又大又不常改，快照会很占地方"},
  {id: "design",  label: "设计稿 / 大图",   pat: ["*.psd", "*.ai", "*.sketch", "*.xcf"],          why: "源文件很大，通常另有备份"},
  {id: "cache",   label: "缓存 / 编译产物",  pat: ["__pycache__", "*.pyc", "*.pyo", "*.class", "*.o"], why: "每次跑都会变，留了全是噪音"},
  {id: "venv",    label: "虚拟环境",        pat: ["venv", ".venv", "env", "site-packages"],      why: "几千个文件、随时能重建"},
  {id: "deps",    label: "依赖 / 构建",     pat: ["node_modules", "dist", "build", "target", ".next"], why: "能一键重装/重编，占地方"},
  {id: "temp",    label: "临时 / 备份文件",  pat: ["*.tmp", "*.bak", "*.old", "*~", "*.swp"],     why: "临时产物"},
  {id: "archive", label: "压缩包",          pat: ["*.zip", "*.7z", "*.rar", "*.tar.gz"],         why: "大且通常别处也有"},
  {id: "db",      label: "数据库文件",       pat: ["*.db", "*.sqlite", "*.sqlite3", "*.mdb"],    why: "二进制、每次都变"},
  {id: "dot",     label: "点开头的隐藏项",   pat: [".*"],                                          why: "含 .git / .env / .idea —— 勾了连 .env 一起排"},
];

/* 一个 glob（含 * ? 和末尾 / 表示只排目录）能不能命中这个名字 */
function snapGlobRe(pat){
  return new RegExp("^" + String(pat).replace(/[.+^${}()|[\]\\]/g, "\\$&")
                                     .replace(/\*/g, "[^/]*").replace(/\?/g, "[^/]") + "$", "i");
}
function snapHit(name, isDir, pats){
  return (pats || []).some(p => {
    const dirOnly = String(p).endsWith("/");
    if (dirOnly && !isDir) return false;
    const q = dirOnly ? String(p).slice(0, -1) : String(p);
    try{ return snapGlobRe(q).test(name); }catch(e){ return false; }
  });
}
/* 拿"当前这一层"已经加载好的清单算一遍（前端算；这一层还没加载就返回 null，让调用方去问宿主） */
function snapPresetLocal(){
  const es = (typeof bkNowEntries === "function") ? bkNowEntries() : [];
  if (!es || !es.length) return null;
  return SNAP_PRESETS.map(p => {
    const hit = es.filter(e => snapHit(e.name, !!e.dir, p.pat));
    // ★ `V-128`：**每个模式各命中几次**也要带上 —— 一键填入/点选只写"命中的那些模式"，
    //   不是把这一类的所有写法（`venv/.venv/env/site-packages`）全塞进去。
    const matched = (p.pat || []).filter(x => es.some(e => snapHit(e.name, !!e.dir, [x])));
    return {id: p.id, label: p.label, pat: p.pat, why: p.why, matched: matched,
            hit: hit.length, sample: hit.slice(0, 3).map(e => e.rel)};
  }).sort((a, b) => (b.hit - a.hit) || String(a.id).localeCompare(String(b.id)));
}
