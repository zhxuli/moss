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
