# -*- coding: utf-8 -*-
"""path 界面探针：把 `path` 包的那一页**真跑起来**，用假后端 + 脚本点击，验界面行为。

> `V-211` 起是"先改后存"（加/删/去重/清失效/拖动排序只改草稿、点「保存修改」才写注册表），
> `V-212` 修了"取消选文件夹会弹两次"，`V-213` 照新设计稿重做外观（条件按钮、Toast、
> 每行的复制/拿出来改/删除、拖动调优先级、差异面板 显示全部/仅看差异、输入框实时提示）。

为什么单独写一个（`tools/包界面检查.py` 差在哪）：那个工具只判"页面画得出来、没报错"，
`moss.call` 一律回空壳 —— **交互一步都验不到**。而这一页塞在内嵌 iframe 里，
`tools/界面预览.py` 读不到它的 DOM（`V-209` 踩过）。所以只能这样验：
**复制一份包 → 把垫片换成"有记忆的假后端" → 追加驱动脚本 → 无头浏览器真跑 → 读结论**。

两程：
  一程：这一页自己（假后端 + 真点击 / 真输入），验"先改后存 + 高亮 + 保存 + 每行操作 + 拖动排序 + 双击改名"；
  二程：把这一页塞进 **iframe**、父页面扮宿主，验"挑文件夹：取消 / 选到 / 没桥 / 老宿主"（`V-212`）。

用法：
    .\\venv\\Scripts\\python.exe tools\\path界面探针.py
"""
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

#: 假后端：一张内存 PATH 表 + 调用流水。★ 认路这件事**归后端**，所以桩里也照 `probe_path`
#: 的四种情况来（空 / 目录 / 文件 → 它所在目录 / 不存在），页面那边才验得出"两条分支"。
STUB = r"""<script>
(function(){
  window.__perr = [];
  window.addEventListener("error", function(e){ window.__perr.push(String(e.message || e)); });
  window.addEventListener("unhandledrejection", function(e){
    window.__perr.push("unhandledrejection: " + String((e.reason && e.reason.message) || e.reason));
  });
  if (window.Vue && Vue.createApp) {          // prod 版没有 Vue.config，只能按 app 挂
    var _c = Vue.createApp;
    Vue.createApp = function(c){
      var app = _c.call(Vue, c);
      app.config.errorHandler = function(e){ window.__perr.push("vue: " + String((e && e.message) || e)); };
      return app;
    };
  }
  // 磁盘上"真存在"的目录 / 文件（大小写不敏感），以及"注册表里有、盘上没了"的那条
  var EXIST = ["C:\\Windows", "C:\\Tools", "D:\\New", "D:\\New2", "E:\\Picked", "F:\\", "F:\\Dir1"];
  var FILES = ["F:\\File.txt"];
  var GONE = ["C:\\Gone"];
  function low(list){ var o = {}; list.forEach(function(p){ o[p.toLowerCase()] = 1; }); return o; }
  var LX = low(EXIST), LF = low(FILES), LG = low(GONE);
  var M = {                                  // 假注册表（初始：4 条，其中一条是大小写重复的）
    paths: ["C:\\Windows", "C:\\Tools", "C:\\Gone", "c:\\windows"],
    saved: null,                             // 最近一次 save 真写进去的那份清单
    calls: []
  };
  window.__M = M;
  function state(){
    return {ok:true, count:M.paths.length, paths:M.paths.slice(), self_dir:"C:\\pkgs\\path",
            self_registered:false, data_dir:"C:\\data", backup_dir:"C:\\bak", legacy_dir:"",
            missing:M.paths.filter(function(p){ return p.toLowerCase() in LG; })};
  }
  var R = {
    info: function(){ return {ok:true, pid:1, python:"?（桩）", embedded:false}; },
    state: state,
    probe_path: function(pm){
      var p = String((pm && pm.path) || "").trim();
      M.calls.push(["probe_path", p]);
      if (!p) return {ok:false, kind:"empty", msg:"先给一个目录"};
      var np = p.replace(/\//g, "\\");         // 真后端走 os.path.normpath，桩里就换一种斜杠
      var k = np.toLowerCase();
      if (k in LX) return {ok:true, kind:"dir", path:np, msg:"目录"};
      if (k in LF) {
        var d = np.replace(/[\\/][^\\/]*$/, "\\");
        return {ok:true, kind:"file", path:d, msg:"这是文件，加的是它所在的目录：" + d};
      }
      return {ok:false, kind:"none", path:np, msg:"这个路径不存在：" + np};
    },
    save: function(pm){
      var ps = ((pm && pm.paths) || []).slice();
      M.calls.push(["save", ps]);
      M.saved = ps; M.paths = ps.slice();
      return {ok:true, msg:"已保存 " + ps.length + " 条到当前用户的 PATH（已广播）", state:state()};
    },
    pick_dir: function(){ M.calls.push(["pick_dir"]); return {ok:true, path:"E:\\Picked", msg:"选好了"}; }
  };
  // 右侧那栏要有两张备份卡片可点（一张默认名、一张自己起的名）
  var BK = [
    {file:"C:\\bak\\path_backup_20261003_010203.txt", name:"", time:"2026-10-03 01:02:03",
     total:4, add:1, remove:0, legacy:false,
     paths:["C:\\Windows", "D:\\New", "C:\\Tools", "C:\\Gone"]},
    {file:"C:\\bak\\改注册表之前.txt", name:"改注册表之前", time:"2026-10-03 02:00:00",
     total:3, add:0, remove:1, legacy:false,
     paths:["C:\\Windows", "C:\\Tools", "C:\\Old"]}
  ];
  R.backup_list = function(){ return {ok:true, items:BK, state:state()}; };
  R.backup_preview = function(pm){
    var b = null;
    for (var i = 0; i < BK.length; i++) if (BK[i].file === (pm && pm.file)) b = BK[i];
    if (!b) return {ok:false, msg:"这份备份读不出来（文件没了？）", state:state()};
    M.calls.push(["backup_preview", b.file]);
    return {ok:true, add:["D:\\New"], remove:b.remove ? ["C:\\Old"] : [],
            paths:b.paths, msg:"会加 1 条、去掉 " + (b.remove ? 1 : 0) + " 条", state:state()};
  };
  R.backup_rename = function(pm){
    M.calls.push(["backup_rename", pm.file, pm.name]);
    return {ok:true, msg:"改名成功 → " + pm.name, state:state()};
  };
  var H = {};
  window.moss = {
    env: {embedded:false},
    on: function(n, cb){ (H[n] = H[n] || []).push(cb); return function(){}; },
    call: function(m, p){ var f = R[m]; return Promise.resolve(f ? f(p) : {ok:true}); }
  };
  window.__fire = function(n, d){ (H[n] || []).forEach(function(f){ f(d); }); };
})();
</script>"""

#: 驱动脚本：追加在 `app.js` 之后。全是**真点击 / 真输入 / 真拖拽**，断言只看**渲染出来的 DOM**
#: （行、class、按钮在不在、Toast 说了什么）+ 假后端记下的 `save` 流水。
DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  async function tick(){ await sleep(70); }
  function q(s){ return document.querySelector(s); }
  function qa(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function rows(){ return qa(".plist .row"); }
  function fresh(){ return rows().filter(function(r){ return r.classList.contains("fresh"); }); }
  function listed(){ return rows().map(function(r){ return r.querySelector(".ptext").textContent.trim(); }); }
  function btn(t){
    var want = t.replace(/\s+/g, "");
    return qa("button").filter(function(b){
      return b.textContent.replace(/\s+/g, "").indexOf(want) >= 0;
    })[0];
  }
  function shown(id){ return !!document.getElementById(id); }          // 条件按钮：在不在 DOM 里
  function toasts(){ return qa("#toast-container .toast"); }
  function lastToast(){ var t = toasts(); return t.length ? t[t.length-1].textContent.replace(/\s+/g, "") : ""; }
  function errN(){ return toasts().filter(function(t){ return t.classList.contains("error"); }).length; }
  function head(){ var e = q(".title p"); return e ? e.textContent.replace(/\s+/g, "") : ""; }
  function foot(){ var e = q("#status-text"); return e ? e.textContent.replace(/\s+/g, "") : ""; }
  function statusHint(){ var e = q(".statusbar .r"); return e ? e.textContent.replace(/\s+/g, "") : ""; }
  function inputEl(){ return q("#path-input"); }
  function setInput(v){
    var i = inputEl();
    i.value = v; i.dispatchEvent(new Event("input", {bubbles:true}));
  }
  function saves(){ return window.__M.calls.filter(function(c){ return c[0] === "save"; }); }
  function rowOf(p){
    return rows().filter(function(r){ return r.querySelector(".ptext").textContent.trim() === p; })[0];
  }
  function dragRow(from, to){                      // 真拖：dragstart → dragover → drop
    var rs = rows(), dt;
    try { dt = new DataTransfer(); } catch(e){ dt = null; }
    var ev = function(t){ return new DragEvent(t, {bubbles:true, cancelable:true, dataTransfer:dt}); };
    rs[from].dispatchEvent(ev("dragstart"));
    rs[to].dispatchEvent(ev("dragover"));
    rs[to].dispatchEvent(ev("drop"));
    rs[from].dispatchEvent(ev("dragend"));
  }

  for (var i = 0; i < 120 && rows().length === 0; i++) await sleep(50);   // 等挂载 + 第一趟 state
  await tick();

  try {

  // t0 —— 一进来：注册表里的 4 条按**原顺序**显示；该出现的按钮才出现
  chk("t0 初始 4 行", rows().length === 4, "实际 " + rows().length);
  chk("t0 顺序 = 注册表顺序",
      listed().join("|") === ["C:\\Windows", "C:\\Tools", "C:\\Gone", "c:\\windows"].join("|"),
      listed().join(" | "));
  chk("t0 没有高亮", fresh().length === 0, "高亮 " + fresh().length);
  chk("t0 失效那条标红（warning 图标在）", !!q(".row.invalid .pico"), "");
  chk("t0 有重复 ⇒ 「去重」露出来", shown("btn-dedup"), "");
  chk("t0 有失效 ⇒ 「清理失效」露出来", shown("btn-clean"), "");
  chk("t0 没改动 ⇒ 没有「保存修改」", !shown("btn-save") && !shown("btn-undo"), "");
  chk("t0 底栏是「总计 N 条路径」", foot() === "总计4条路径", foot());

  // t1 —— 输入框实时提示：格式不像路径 ⇒ 立刻警告；像但不存在 ⇒ 问过后警告
  setInput("这不是个路径"); await tick();
  chk("t1 不像路径 ⇒ 立刻出警告三角", !!q("#input-warning"), "");
  chk("t1 警告说的是格式", (q("#input-warning").getAttribute("title") || "").indexOf("不像个路径") >= 0,
      q("#input-warning").getAttribute("title"));
  setInput("Z:\\NoSuch"); await tick(); await sleep(500);
  chk("t1 像路径但不存在 ⇒ 问过之后警告",
      !!q("#input-warning") && (q("#input-warning").getAttribute("title") || "").indexOf("不存在") >= 0,
      q("#input-warning") ? q("#input-warning").getAttribute("title") : "（没有警告）");
  chk("t1 清空按钮在", !!q("#btn-clear"), "");
  q("#btn-clear").click(); await tick();
  chk("t1 清空后输入框空了、警告也没了", inputEl().value === "" && !q("#input-warning"), inputEl().value);

  // t2 —— 去重：只改草稿（后端不该收到 save），撤销回得来
  var calls0 = window.__M.calls.length;
  btn("去重").click(); await tick();
  chk("t2 去重后 3 行", rows().length === 3, listed().join(" | "));
  chk("t2 去重没写注册表", saves().length === 0, JSON.stringify(window.__M.calls.slice(calls0)));
  chk("t2 去重后「去重」自己收起来（没重复了）", !shown("btn-dedup"), "");
  chk("t2 有改动 ⇒ 「保存修改」露出来", shown("btn-save") && shown("btn-undo"), "");
  chk("t2 底栏说有几处没保存", statusHint().indexOf("有1处没保存") >= 0, statusHint());
  btn("撤销").click(); await tick();
  chk("t2 撤销回 4 行", rows().length === 4 && fresh().length === 0, listed().join(" | "));
  chk("t2 撤销后「保存修改」收起来、重复还在 ⇒ 「去重」还露着",
      !shown("btn-save") && !shown("btn-undo") && shown("btn-dedup"), "");

  // t3 —— 清失效：还是只改草稿
  btn("清理失效").click(); await tick();
  chk("t3 清失效后 3 行", rows().length === 3, listed().join(" | "));
  chk("t3 失效那条没了、按钮也收起来", listed().indexOf("C:\\Gone") < 0 && !shown("btn-clean"),
      listed().join(" | "));
  btn("撤销").click(); await tick();

  // t4 —— 「添加」有值 + 真目录 ⇒ 进草稿、**亮着**
  setInput("D:\\New"); btn("添加").click(); await tick();
  chk("t4 加进来 1 行", rows().length === 5, listed().join(" | "));
  chk("t4 它是唯一高亮的", fresh().length === 1 && fresh()[0].querySelector(".ptext").textContent.trim() === "D:\\New",
      fresh().length + " 条高亮");
  chk("t4 它挂着「未保存」小标签",
      !!rowOf("D:\\New").querySelector(".chip.new"), "");
  chk("t4 输入框清空了", inputEl().value === "", "");
  chk("t4 后端一次都没被写", saves().length === 0, "");

  setInput("D:\\New2"); btn("添加").click(); await tick();
  chk("t5 第二条也亮着（高亮 2）", fresh().length === 2, "高亮 " + fresh().length);

  // t6 —— 有值但不是目录 ⇒ 报错、行数不变、**输入框一个字不动**
  setInput("Z:\\NoSuch"); btn("添加").click(); await tick();
  chk("t6 不存在的加不进来", rows().length === 6, listed().join(" | "));
  chk("t6 报了错（红 Toast）", errN() >= 1 && lastToast().indexOf("不存在") >= 0, lastToast());
  chk("t6 输入框留着原文", inputEl().value === "Z:\\NoSuch", inputEl().value);
  setInput(""); await tick();

  // t7 —— 输入框留空 ⇒ 弹选择框（后端给 E:\Picked）⇒ 同样进草稿
  btn("添加").click(); await tick();
  chk("t7 空输入 = 选文件夹后加进来", rows().length === 7 && listed()[6] === "E:\\Picked", listed().join(" | "));
  chk("t7 高亮 3 条", fresh().length === 3, "高亮 " + fresh().length);

  // t8 —— 重复的不给加
  setInput("c:/windows"); btn("添加").click(); await tick();
  chk("t8 重复的不给加", rows().length === 7, listed().join(" | "));
  chk("t8 说清了为啥", lastToast().indexOf("已经在列表里") >= 0, lastToast());
  setInput(""); await tick();

  // t9 —— 拖动排序：把第 1 条拖到第 3 条**上面** ⇒ 它就插到第 3 条前面（指示线画在那行上沿）
  dragRow(0, 2); await tick();
  chk("t9 拖完顺序变了（Windows 插到 Gone 前面）",
      listed().join("|") === ["C:\\Tools", "C:\\Windows", "C:\\Gone", "c:\\windows",
                              "D:\\New", "D:\\New2", "E:\\Picked"].join("|"),
      listed().join(" | "));
  chk("t9 拖动也没写注册表", saves().length === 0, "");

  // t10 —— 每行：复制 / 拿出来改 / 删除（三颗都是「图标 + 文字」，`V-214`）
  var target = rowOf("D:\\New2");
  var acts = target.querySelectorAll(".ract");
  chk("t10 三颗按钮都是「图标 + 文字」",
      acts.length === 3 && acts[0].textContent.trim() === "复制" &&
      acts[1].textContent.trim() === "拿出来改" && acts[2].textContent.trim() === "删除" &&
      !!acts[0].querySelector("svg") && !!acts[1].querySelector("svg") && !!acts[2].querySelector("svg"),
      Array.prototype.map.call(acts, function(b){ return b.textContent.trim(); }).join(" / "));
  var before = toasts().length;
  target.querySelectorAll(".ract")[0].click(); await tick();
  chk("t10 复制那颗按钮点了有回话（Toast 是「复制」相关）",
      toasts().length > before || lastToast().indexOf("复制") >= 0, lastToast());
  target = rowOf("D:\\New2");
  target.querySelectorAll(".ract")[1].click(); await tick();      // 拿出来改
  chk("t10 拿出来改：路径填回输入框", inputEl().value === "D:\\New2", inputEl().value);
  chk("t10 拿出来改：那一条先从列表里拿掉了", rows().length === 6 && !rowOf("D:\\New2"),
      listed().join(" | "));
  btn("添加").click(); await tick();
  chk("t10 点「添加」它按改后的样子回来了（还是亮着）",
      rows().length === 7 && listed()[6] === "D:\\New2" && fresh().length === 3, listed().join(" | "));
  target = rowOf("D:\\New2");
  target.querySelectorAll(".ract")[2].click(); await sleep(420);   // 删除（有 300ms 消失动画）
  chk("t10 删除那颗：行没了", rows().length === 6 && !rowOf("D:\\New2"), listed().join(" | "));
  chk("t10 删除也说了句人话", lastToast().indexOf("去掉了") >= 0, lastToast());

  // t11 —— 点「保存修改」：真写一次、顺序 = 拖过之后的草稿顺序、**高亮全灭**
  var want = ["C:\\Tools", "C:\\Windows", "C:\\Gone", "c:\\windows", "D:\\New", "E:\\Picked"];
  btn("保存修改").click(); await tick();
  chk("t11 只写了 1 次注册表", saves().length === 1, "写 " + saves().length + " 次");
  chk("t11 写进去的顺序对", JSON.stringify(saves()[0] && saves()[0][1]) === JSON.stringify(want),
      JSON.stringify(saves()[0] && saves()[0][1]));
  chk("t11 保存后高亮全灭", fresh().length === 0, "高亮 " + fresh().length);
  chk("t11 保存后按钮组收起来", !shown("btn-save") && !shown("btn-undo"), "");
  chk("t11 保存后不再说「没保存」", statusHint().indexOf("没保存") < 0 && head().indexOf("没保存") < 0,
      statusHint());
  chk("t11 Toast 报了结果", lastToast().indexOf("已保存6条") >= 0, lastToast());

  // t12 —— 保存完再加一条：亮的只有这一条（"每次加进来的都亮着，存了才灭"）
  setInput("F:\\Dir1"); btn("添加").click(); await tick();
  chk("t12 保存后再加，只有它亮", rows().length === 7 && fresh().length === 1 &&
      fresh()[0].querySelector(".ptext").textContent.trim() === "F:\\Dir1", "高亮 " + fresh().length);
  btn("撤销").click(); await tick();

  // t13 —— 拖进来的（`drop` 事件）：目录直接用，文件取它所在的目录，不存在的跳过 —— 也只进草稿
  window.__fire("drop", {items:["F:\\Dir1", "F:\\File.txt", "Z:\\Nope"]}); await tick();
  chk("t13 拖 3 条加进 2 条", rows().length === 8, listed().join(" | "));
  chk("t13 文件取的是它所在的目录", listed().indexOf("F:\\") >= 0, listed().join(" | "));
  chk("t13 两条都亮着", fresh().length === 2, "高亮 " + fresh().length);
  chk("t13 说明里提了要保存", lastToast().indexOf("记得点「保存修改」") >= 0, lastToast());

  // t14 —— 有草稿时点「刷新」：第一下只提醒，第二下才丢
  document.getElementById("btn-refresh").click(); await tick();
  chk("t14 第一下先提醒", lastToast().indexOf("再点一下「刷新」就丢掉它们") >= 0, lastToast());
  chk("t14 第一下草稿还在", rows().length === 8, "行 " + rows().length);
  document.getElementById("btn-refresh").click(); await tick();
  chk("t14 第二下真刷新（回到注册表 6 条）", rows().length === 6 && fresh().length === 0, listed().join(" | "));

  // t15 —— 差异面板（`V-214` 改的）：**一 hover 就自动展开**、移开自动收、点「对比」= 固定住
  var entries = qa(".bentry");
  chk("t15 两张备份卡片", entries.length === 2, "卡片 " + entries.length);
  chk("t15 卡片上不再有「改名」按钮",
      qa(".bcard").every(function(c){ return c.textContent.indexOf("改名") < 0; }),
      qa(".bcard").map(function(c){ return c.textContent.replace(/\s+/g, " "); }).join(" / ").slice(0, 80));
  function entry(i){ return qa(".bentry")[i]; }
  function card(i){ return qa(".bcard")[i]; }
  function panel(i){ return entry(i).querySelector(".bdiff"); }
  function over(i){ entry(i).dispatchEvent(new MouseEvent("mouseenter", {bubbles:true})); }
  function out(i){ entry(i).dispatchEvent(new MouseEvent("mouseleave", {bubbles:true})); }
  chk("t15 一开始收着（没 hover）", !panel(0).classList.contains("open"), "");
  over(0); await tick();
  chk("t15 ★一 hover 就自动展开（不用点）", panel(0).classList.contains("open"), "");
  chk("t15 hover 时那三颗按钮也露着", entry(0).classList.contains("open"), "");
  chk("t15 面板里有「- 减少」（草稿里有、这份备份里没有的那些）",
      !!panel(0).querySelector(".ditem.del"),
      panel(0).querySelector(".difflist").textContent.replace(/\s+/g, " ").slice(0, 80));
  chk("t15 这状态下没有「+ 增加」（这份备份里的草稿里都有）",
      !panel(0).querySelector(".ditem.add"),
      panel(0).querySelector(".difflist").textContent.replace(/\s+/g, " ").slice(0, 80));
  chk("t15 默认只列差异（没有「= 相同」）", !panel(0).querySelector(".ditem.same"), "");
  var pv = window.__M.calls.filter(function(c){ return c[0] === "backup_preview"; }).length;
  chk("t15 差异是本地算的（后端没被问过一次）", pv === 0, "backup_preview " + pv + " 次");
  out(0); await tick();
  chk("t15 ★移开就自动收起", !panel(0).classList.contains("open"), "");
  card(0).querySelector(".bact").click(); await tick();
  out(0); await tick();
  chk("t15 ★点过「对比」之后，鼠标移开也不收（固定住了）", panel(0).classList.contains("open"), "");
  chk("t15 那颗按钮变成「已固定」",
      card(0).querySelector(".bact").textContent.indexOf("已固定") >= 0,
      card(0).querySelector(".bact").textContent.trim());
  card(0).querySelector(".difftoggle").click(); await tick();
  chk("t15 「显示全部」把「= 相同」也列出来", !!panel(0).querySelector(".ditem.same"),
      panel(0).querySelector(".difflist").textContent.replace(/\s+/g, " ").slice(0, 90));
  card(0).querySelector(".difftoggle").click(); await tick();
  chk("t15 再点回「仅看差异」", !panel(0).querySelector(".ditem.same"), "");
  card(0).querySelector(".bact").click(); await tick();
  chk("t15 再点一下取消固定、又收起来", !panel(0).classList.contains("open"), "");

  // t16 —— 双击名字改名（`V-211`）：输入框原样、预填对、回车真改名、Esc 不发请求
  cards = qa(".bcard");
  chk("t16 提示写着双击改名",
      (cards[0].querySelector(".namelabel").getAttribute("title") || "").indexOf("双击改名") >= 0,
      cards[0].querySelector(".namelabel").getAttribute("title"));
  var ncalls0 = window.__M.calls.length;
  cards[0].querySelector(".namelabel").dispatchEvent(new MouseEvent("dblclick", {bubbles:true})); await tick();
  var ri = document.getElementById("bk-rename-input");
  chk("t16 双击弹出改名输入框", !!ri, ri ? "有" : "没有");
  chk("t16 预填原来的文件名（去掉 .txt）",
      !!ri && ri.value === "path_backup_20261003_010203", ri ? ri.value : "");
  chk("t16 进输入框时标签让位", !cards[0].querySelector(".namelabel"), "");
  ri.value = "备份A";
  ri.dispatchEvent(new Event("input", {bubbles:true}));
  ri.dispatchEvent(new KeyboardEvent("keyup", {key:"Enter", bubbles:true})); await tick();
  var rn = window.__M.calls.slice(ncalls0).filter(function(c){ return c[0] === "backup_rename"; });
  chk("t16 回车 = 真去改名了", rn.length === 1 && rn[0][2] === "备份A", JSON.stringify(rn));
  chk("t16 改完输入框收起来", !document.getElementById("bk-rename-input"), "");
  cards = qa(".bcard");
  chk("t16 自定义名是加粗的", cards[1].querySelector(".namelabel.custom") !== null, "");   // 进输入框前先看
  cards[1].querySelector(".namelabel").dispatchEvent(new MouseEvent("dblclick", {bubbles:true})); await tick();
  var ri3 = document.getElementById("bk-rename-input");
  chk("t16 自定义名的预填自定义名", !!ri3 && ri3.value === "改注册表之前", ri3 ? ri3.value : "");
  var ncalls1 = window.__M.calls.length;
  ri3.dispatchEvent(new Event("input", {bubbles:true}));
  ri3.dispatchEvent(new KeyboardEvent("keyup", {key:"Escape", bubbles:true})); await tick();
  chk("t16 Esc 就退出、没发请求",
      !document.getElementById("bk-rename-input") && window.__M.calls.slice(ncalls1).length === 0,
      JSON.stringify(window.__M.calls.slice(ncalls1)));

  // t17 —— ★★ 差异比的是**界面上的清单**（不是注册表）：这是 `V-214` 你点名要的那条
  var regBefore = JSON.stringify(window.__M.paths);
  rowOf("C:\\Tools").querySelectorAll(".ract")[1].click();       // 拿出来改 = 草稿里少一条
  await tick();
  chk("t17 草稿里少了一条，注册表里还在", !rowOf("C:\\Tools") && JSON.stringify(window.__M.paths) === regBefore,
      "注册表 " + regBefore);
  over(0); await sleep(260);
  var addRow = panel(0).querySelector(".ditem.add .dp");
  chk("t17 ★按草稿比：C:\\Tools 出现在「+ 增加」里（按注册表比就不会有）",
      !!addRow && addRow.textContent.trim() === "C:\\Tools",
      panel(0).querySelector(".difflist").textContent.replace(/\s+/g, " ").slice(0, 110));
  out(0); await tick();
  setInput("F:\\Dir1"); btn("添加").click(); await tick();        // 再加一条没保存的
  over(0); await sleep(260);
  var delPaths = Array.prototype.map.call(panel(0).querySelectorAll(".ditem.del .dp"),
                                         function(e){ return e.textContent.trim(); });
  chk("t17 ★没保存的新条目也进对比（F:\\Dir1 在「- 减少」里）", delPaths.indexOf("F:\\Dir1") >= 0,
      delPaths.join(" | ").slice(0, 110));
  out(0); await tick();

  } catch (e) {   // ★ 驱动脚本自己抛错也要留下结论（不然只看到"没跑到最后"，白查半天）
    RES.push({name: "★ 驱动脚本抛错", ok: false,
              detail: String((e && (e.stack || e.message)) || e).slice(0, 400)});
  }

  await tick();
  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && window.__perr.length === 0)
    ? "PROBE-OK " + RES.length : "PROBE-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""

#: 第二程：**宿主那一侧**（`V-212` 修的那个"取消一次弹两个框"）。
#: 挑文件夹是"先问 moss 主界面、问不到才退回包自己那张"—— 而"用户点了取消"**不是**"问不到"。
#: 要真跑这条分支，页面得**在 iframe 里**（`window.parent !== window`，同源才能拿到
#: `parent.pywebview`），而结论要写进**父页面**（`--dump-dom` 只倒顶层文档）。
PICK_HOST = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HOST-START</title></head>
<body style="margin:0">
<iframe id="fr" src="path/ui/probe2.html" style="width:1264px;height:884px;border:0"></iframe>
<script>
  window.__hostCalls = [];
  window.MODE = "cancel";
  window.pywebview = {api:{ pick_dir: function(){
    window.__hostCalls.push(1);
    if (window.MODE === "ok") return Promise.resolve({ok:true, path:"G:\\HostPicked"});
    if (window.MODE === "oldcancel") return Promise.resolve({ok:false, msg:"没有选（取消）"});
    return Promise.resolve({ok:false, cancelled:true, msg:"没有选（取消）"});
  }}};
</script>
</body></html>"""

#: 第三程：**量一遍**（`V-213`）—— 设计稿是拿 Tailwind 写的，这里把关键尺寸/颜色/圆角/阴影
#: 按 Tailwind 的默认刻度（p-6=24px、rounded-xl=12px、text-sm=14px、zinc-50=#fafafa…）
#: 一条条量出来对。**不靠眼睛看图**，靠 `getComputedStyle`。
#: 顺带钉一条最要紧的：**一个外网资源都没有**（设计稿引了 Tailwind / lucide / SortableJS /
#: Google Fonts 四个 CDN —— moss 得能离线跑，所以那些全不许有）。
STYLE_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  var q = function(s){ return document.querySelector(s); };
  function cs(sel){ var e = q(sel); return e ? getComputedStyle(e) : null; }
  function eq(sel, prop, want, what){
    var s = cs(sel);
    if (!s) return chk(what || (sel + " " + prop), false, "页面上没有 " + sel);
    var got = s[prop];
    chk(what || (sel + " " + prop), got === want, sel + "." + prop + " = " + got + "（设计稿 " + want + "）");
  }
  function near(sel, prop, want, tol, what){
    var s = cs(sel), got = parseFloat(s && s[prop]);
    chk(what || (sel + " " + prop), Math.abs(got - want) <= tol,
        sel + "." + prop + " = " + got + "（期望 " + want + " ±" + tol + "）");
  }
  function has(sel, prop, part, what){
    var s = cs(sel);
    if (!s) return chk(what, false, "页面上没有 " + sel);
    var got = String(s[prop]);
    chk(what, got.indexOf(part) >= 0, sel + "." + prop + " = " + got.slice(0, 80));
  }
  // hover 态量不到（getComputedStyle 不认伪类）—— 那就**读样式表原文**（`V-214`：
  // "hover 颜色变化不大"这条得能对账，不能靠肉眼）。★ 不能走 CSSOM：`file://` 下
  // `styleSheets[i].cssRules` 抛 SecurityError（`--allow-file-access-from-files` 也救不了），
  // 所以由外面（Python）把 `style.css` 的**原文**注进来（`var CSS_TEXT = ...`）。
  var CSS_TEXT = null;
  function cssRule(sel, prop){
    var esc = sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    var m = new RegExp(esc + "\\s*\\{([^}]*)\\}").exec(CSS_TEXT || "");
    if (!m) return "";
    var m2 = new RegExp("(?:^|;)\\s*" + prop + "\\s*:\\s*([^;]+)").exec(m[1]);
    return m2 ? m2[1].trim() : "";
  }
  function rule(sel, prop, want, what){
    var got = cssRule(sel, prop);
    chk(what, got === want, sel + " 的 " + prop + " = " + (got || "（没这条）") + "（期望 " + want + "）");
  }
  function rootVar(name, want, what){
    var got = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    chk(what, got === want, name + " = " + got + "（期望 " + want + "）");
  }

  for (var i = 0; i < 120 && !q(".row"); i++) await sleep(50);
  await sleep(120);

  try {

  // ① 不联网（设计稿那四个 CDN 一个都不许在）
  var ext = performance.getEntriesByType("resource")
              .map(function(r){ return r.name; })
              .filter(function(u){ return /^https?:/i.test(u); });
  chk("① 一个外网资源都没加载（Tailwind / lucide CDN / SortableJS / Google Fonts 全没有）",
      ext.length === 0, ext.slice(0, 3).join(" , ") || "（干净）");

  // ② 外壳：max-w-1400 / p-6 / gap-6 / 7:3 两栏
  eq(".wrap", "maxWidth", "1400px");
  eq(".wrap", "padding", "24px");
  eq(".wrap", "gap", "24px");
  eq(".wrap", "flexDirection", "row");
  eq(".wrap", "flexWrap", "nowrap");
  eq(".card", "borderRadius", "12px");
  eq(".card", "borderTopWidth", "1px");
  eq(".card", "borderTopColor", "rgb(228, 228, 231)");
  has(".card", "boxShadow", "0px 1px 2px", ".card 阴影 = shadow-sm");
  // `V-215`：右边**固定 360px**（不再按 3/10 伸缩），左边吃掉剩下的
  eq(".aside", "width", "360px");
  eq(".aside", "flexGrow", "0");
  eq(".aside", "flexShrink", "0");
  eq(".aside", "flexBasis", "360px");
  eq(".main", "flexGrow", "1");
  near(".main", "width", window.innerWidth - 48 - 24 - 360, 6,
       "② 左栏 = 剩下的全部（视口 " + window.innerWidth + " − 左右留白 − gap − 360）");

  // ③ 顶栏
  eq(".hd", "padding", "20px 24px");
  eq(".hd", "gap", "20px");
  eq(".title h1", "fontSize", "18px");
  eq(".title h1", "fontWeight", "600");
  eq(".title p", "fontSize", "14px");
  eq(".title p", "color", "rgb(113, 113, 122)");              // zinc-500
  eq("#btn-refresh", "width", "32px");
  eq(".actgroup", "padding", "4px");
  eq(".actgroup", "borderRadius", "8px");
  eq(".actbtn", "fontSize", "14px");
  eq(".actbtn", "fontWeight", "500");
  eq(".actbtn", "borderRadius", "6px");
  eq(".actbtn", "color", "rgb(82, 82, 91)");                  // zinc-600
  // 「保存修改」和那条竖分隔线**只在有改动时**才在页面上 —— 先点一下「去重」把它们叫出来
  var dedup = document.getElementById("btn-dedup");
  chk("③ 一开始没有「保存修改」（没事不出现）", !!dedup && !q("#btn-save"), "");
  if (dedup) dedup.click();
  for (var k = 0; k < 40 && !q("#btn-save"); k++) await sleep(50);
  eq(".actsave", "backgroundColor", "rgb(37, 99, 235)");      // blue-600（`V-214`：不再是黑的）
  eq(".actsave", "color", "rgb(255, 255, 255)");
  eq(".actdiv", "width", "1px");

  // ④ 输入 + 添加 的复合组
  eq(".compound", "borderRadius", "8px");
  eq(".compound", "borderTopColor", "rgb(228, 228, 231)");
  eq(".inputwrap input", "padding", "10px 64px 10px 36px");
  eq(".inputwrap input", "fontSize", "14px");
  has(".inputwrap input", "fontFamily", "Consolas", "④ 输入框是等宽字体（路径好认）");
  eq(".addbtn", "padding", "10px 20px");
  eq(".addbtn", "backgroundColor", "rgb(250, 250, 250)");     // zinc-50

  // ⑤ 列表行
  eq(".row", "padding", "12px 16px 12px 24px");
  eq(".row", "borderBottomColor", "rgb(244, 244, 245)");      // zinc-100
  // ★ `V-215`：把手 + 右边那三颗**都浮着、不占宽度** —— 不 hover 时路径能用满整行
  eq(".grip", "position", "absolute");
  eq(".racts", "position", "absolute");
  eq(".bacts", "position", "absolute");
  (function(){
    var r = q(".row"), pc = q(".pcell");
    var used = r.clientWidth - pc.clientWidth;
    chk("⑤ 不 hover 时三颗工具**不占宽度**（路径区 ≈ 整行宽 − 内边距）", used <= 40,
        "行 " + r.clientWidth + "px / 路径区 " + pc.clientWidth + "px（被吃掉 " + used + "px）");
    var left = Math.round(pc.getBoundingClientRect().left - r.getBoundingClientRect().left);
    chk("⑤ 路径从左边一点点就开始（把手浮在外面）", left >= 20 && left <= 30, "左侧留白 " + left + "px");
  })();
  eq(".ptext", "fontSize", "13px");
  eq(".ptext", "color", "rgb(63, 63, 70)");                   // zinc-700
  has(".ptext", "fontFamily", "Consolas", "⑤ 路径是等宽字体");
  eq(".racts", "opacity", "0");                               // 悬停才滑出来
  has(".racts", "transform", "12", "⑤ 工具是「从右侧滑入」的起点（translateX 12px）");
  eq(".chip", "fontSize", "10px");
  eq(".chip", "borderRadius", "4px");
  has(".row.invalid", "backgroundImage", "repeating-linear-gradient", "⑤ 失效那行的红色斜纹在");
  eq(".row.invalid .ptext", "color", "rgb(220, 38, 38)");     // red-600
  eq(".statusbar", "padding", "8px 16px");
  eq(".statusbar", "fontSize", "12px");
  eq(".statusbar", "color", "rgb(113, 113, 122)");

  // ⑥ 右边：备份时间线
  eq(".rhd", "padding", "16px 20px");
  eq(".rhd", "backgroundColor", "rgba(244, 244, 245, 0.5)");  // zinc-100/50
  eq(".axis", "left", "27px");
  eq(".axis", "width", "1px");
  eq(".dot", "width", "10px");
  eq(".dot", "marginTop", "6px");
  eq(".dot.latest", "backgroundColor", "rgb(24, 24, 27)");
  eq(".bcard", "borderRadius", "8px");
  eq(".bbody", "padding", "12px");
  eq(".btime", "fontSize", "12px");
  eq(".btime", "color", "rgb(113, 113, 122)");
  eq(".namelabel", "fontSize", "14px");
  eq(".namelabel", "fontWeight", "500");
  eq(".namelabel.custom", "fontWeight", "600");
  eq(".bacts", "opacity", "0");
  eq(".bacts", "gap", "4px");
  near(".bbody", "height", 92, 14, "⑥ 卡片本体只有三行（工具浮在右下角，不再多占一行）");
  eq(".bdiff", "display", "grid");
  eq(".bdiff", "gridTemplateRows", "0px");                    // 收着的时候（0fr → 1fr 的展开动画）
  eq(".bact", "fontSize", "11px");

  // ⑨ `V-214` 你那五条里的配色/hover：保存键不再是黑的、hover 要有**明显底色**
  rootVar("--blue50", "#eff6ff", "⑨ --blue50 = Tailwind 的 blue-50");
  rootVar("--blue600", "#2563eb", "⑨ --blue600 = Tailwind 的 blue-600");
  rootVar("--blue700", "#1d4ed8", "⑨ --blue700 = Tailwind 的 blue-700");
  rule(".actsave", "background-color", "var(--blue600)", "⑨ ①「保存修改」= 明亮的蓝（不再是黑的）");
  rule(".actsave:hover", "background-color", "var(--blue700)", "⑨ ① 保存键 hover 再深一档");
  rule(".ract:hover", "background-color", "var(--blue50)", "⑨ ⑤ 每行按钮 hover **有底色**（不是只换字色）");
  rule(".ract:hover", "color", "var(--blue700)", "⑨ ⑤ 每行按钮 hover 字色 = blue-700");
  rule(".ract.del:hover", "background-color", "var(--red50)", "⑨ ⑤ 删除那颗 hover 是红底");
  rule(".row:hover .racts", "opacity", "1", "⑨ 鼠标放到行上，那三颗才浮出来");
  rule(".bentry.open .bacts", "opacity", "1", "⑨ 固定住的备份卡片，那三颗一直露着");
  rule(".bact:hover", "background-color", "var(--blue50)", "⑨ ⑤ 备份那三颗 hover 有底色");
  rule(".bact.danger:hover", "background-color", "var(--red50)", "⑨ ⑤ 备份的删除 hover 是红底");
  rule(".addbtn:hover", "background-color", "var(--blue600)", "⑨ ⑤ 「添加」hover 整颗变蓝");
  rule(".ghostbtn:hover", "background-color", "var(--blue50)", "⑨ ⑤ 「备份当前」hover 有底色");
  rule(".iconbtn:hover", "background-color", "var(--blue50)", "⑨ ⑤ 刷新图标 hover 有底色");
  eq(".racts", "gap", "4px");
  eq(".ract", "fontSize", "11px");
  eq(".ract", "padding", "3px 8px");

  // ⑧ 该滚的地方滚得动（不是靠页面整体滚）
  var lw = q(".listwrap");
  chk("⑧ 列表区自己滚（overflow-y:auto）", cs(".listwrap").overflowY === "auto", cs(".listwrap").overflowY);
  chk("⑧ 备份区自己滚（overflow-y:auto）", cs(".blistwrap").overflowY === "auto", cs(".blistwrap").overflowY);
  chk("⑧ 页面本身不滚（body 锁在视口高度）",
      getComputedStyle(document.body).overflow === "hidden" && lw.clientHeight < window.innerHeight,
      "body " + getComputedStyle(document.body).overflow + " / listwrap " + lw.clientHeight +
      " < " + window.innerHeight);
  chk("⑧ 备份卡片确实画出来了（有 2 张）", document.querySelectorAll(".bcard").length === 2,
      document.querySelectorAll(".bcard").length + " 张");

  } catch (e) {
    RES.push({name: "★ 驱动脚本抛错", ok: false,
              detail: String((e && (e.stack || e.message)) || e).slice(0, 400)});
  }

  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && window.__perr.length === 0)
    ? "STYLE-OK " + RES.length : "STYLE-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""

PICK_DRIVER = r"""<script>
(async function(){
  var RES = [], HOST = window.parent;
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  async function tick(){ await sleep(90); }
  function q(s){ return document.querySelector(s); }
  function qa(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function rows(){ return qa(".plist .row"); }
  function listed(){ return rows().map(function(r){ return r.querySelector(".ptext").textContent.trim(); }); }
  function fresh(){ return rows().filter(function(r){ return r.classList.contains("fresh"); }); }
  function btn(t){
    var want = t.replace(/\s+/g, "");
    return qa("button").filter(function(b){
      return b.textContent.replace(/\s+/g, "").indexOf(want) >= 0;
    })[0];
  }
  function errN(){ return qa("#toast-container .toast.error").length; }
  function bpick(){ return (window.__M.calls || []).filter(function(c){ return c[0] === "pick_dir"; }).length; }
  function hpick(){ return HOST.__hostCalls.length; }

  for (var i = 0; i < 120 && rows().length === 0; i++) await sleep(50);
  await tick();
  var n0 = rows().length;
  async function clickAdd(mode){ HOST.MODE = mode; btn("添加").click(); await tick(); }

  // p1-p4 —— 宿主那张框**被取消**：这是"这次不选"，不是"问不到" ⇒ 不许再弹第二个
  await clickAdd("cancel");
  chk("p1 取消后一行都没多", rows().length === n0, listed().join(" | "));
  chk("p2 宿主被问了一次", hpick() === 1, "宿主 " + hpick() + " 次");
  chk("p3 ★没再弹第二个框（包自己的选择框 0 次）", bpick() === 0, "后端 pick_dir " + bpick() + " 次");
  chk("p4 取消不报错（没有红 Toast）", errN() === 0, "红 " + errN());

  // p5-p6 —— 真选到一个：加进草稿（高亮）、还是没碰后端那张框
  await clickAdd("ok");
  chk("p5 选到的目录加进来了", rows().length === n0 + 1 && listed()[n0] === "G:\\HostPicked",
      listed().join(" | "));
  chk("p5 它是高亮着的（还没保存）", fresh().length === 1, "高亮 " + fresh().length);
  chk("p5 输入框被清空了", q("#path-input").value === "", q("#path-input").value);
  chk("p6 宿主问了两次、后端仍是 0 次", hpick() === 2 && bpick() === 0, hpick() + " / " + bpick());

  // p7 —— **真没有桥**（独立开窗那种）才退回包自己的选择框
  delete HOST.pywebview;
  btn("添加").click(); await tick();
  chk("p7 没桥才退回包自己的框（1 次）且加进来了",
      bpick() === 1 && rows().length === n0 + 2, "后端 " + bpick() + " 次 / 行 " + rows().length);

  // p8 —— 老宿主（只有一句人话、没有 cancelled 这个准信）也不许弹第二个
  HOST.pywebview = {api:{ pick_dir: function(){
    HOST.__hostCalls.push(1);
    return Promise.resolve({ok:false, msg:"没有选（取消）"});
  }}};
  var b8 = bpick();
  await clickAdd("oldcancel");
  chk("p8 老宿主（没 cancelled）也不弹第二个", bpick() === b8, "后端多弹了 " + (bpick() - b8) + " 次");

  await tick();
  var bad = RES.filter(function(r){ return !r.ok; });
  var box = HOST.document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  HOST.document.body.appendChild(box);
  HOST.document.title = (bad.length === 0 && window.__perr.length === 0)
    ? "PICK-OK " + RES.length : "PICK-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""


#: 第四程（`V-215`）：**窄窗口下也必须是左右结构**（不做自适应塌成一列），右边仍然固定 360px。
#: 拿 760×900 跑一遍，量 `.wrap` 的方向和两块的位置关系 —— "没塌"这件事得能对账。
NARROW_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function q(s){ return document.querySelector(s); }
  function cs(s){ var e = q(s); return e ? getComputedStyle(e) : null; }
  for (var i = 0; i < 120 && !q(".row"); i++) await sleep(50);
  await sleep(150);
  var main = q(".main").getBoundingClientRect(), aside = q(".aside").getBoundingClientRect();
  chk("窄窗口（" + window.innerWidth + "px）下仍是**横排**两栏",
      cs(".wrap").flexDirection === "row", cs(".wrap").flexDirection);
  chk("窄窗口下右边仍**固定 360px**", Math.abs(aside.width - 360) <= 1, aside.width + "px");
  chk("左右并排（右栏在右栏右边、两栏顶端对齐）",
      aside.left >= main.right - 1 && Math.abs(aside.top - main.top) <= 1,
      "main.left=" + Math.round(main.left) + " right=" + Math.round(main.right) +
      " / aside.left=" + Math.round(aside.left) + " top=" + Math.round(aside.top));
  chk("左边还剩得下东西（>200px）", main.width > 200, Math.round(main.width) + "px");
  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && window.__perr.length === 0)
    ? "NARROW-OK " + RES.length : "NARROW-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def build_page(dst, name, driver):
    """复制出来的包里生成一个"换了桩 + 追加驱动"的页面（原页面一个字不动，留着对账）。

    ★ 顺手把 `style.css` 的**原文**注进驱动脚本（`var CSS_TEXT = ...`）：hover 那几条规则
      量不到（`getComputedStyle` 不认伪类），而 CSSOM 在 `file://` 下读不到 —— 只能拿原文正则。
    """
    src = (dst / "ui" / "index.html").read_text(encoding="utf-8")
    if '<script src="moss-embed.js"></script>' not in src:
        raise RuntimeError("这一页里没找到垫片那行 —— 探针没法换桩")
    css = (dst / "ui" / "style.css").read_text(encoding="utf-8")
    driver = driver.replace("var CSS_TEXT = null;", "var CSS_TEXT = " + json.dumps(css) + ";")
    out = src.replace('<script src="moss-embed.js"></script>', STUB)
    out = out.replace('<script src="app.js"></script>', driver + '\n<script src="app.js"></script>')
    page = dst / "ui" / name
    page.write_text(out, encoding="utf-8")
    return page


def dump(exe, page, tmp, size="1280,900"):
    prof = tmp / ("_prof_" + page.stem)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + str(prof),
           "--allow-file-access-from-files", "--window-size=" + size,
           "--virtual-time-budget=40000", "--dump-dom",
           "file:///" + str(page).replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=240)
    return r.stdout or ""


def report(dom, exe, label):
    """打印一趟的结论；返回 True/False。"""
    title = (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1].strip()
    m = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
    print("浏览器 : %s" % exe)
    print("=" * 72)
    print("第 %s" % label)
    print("=" * 72)
    if not m:
        print("  ✗ 没跑到最后（读不到结论）—— 标题=%s" % (title or "（空）"))
        print("  DOM %d KB；前 2000 字：" % (len(dom) // 1024))
        print(dom[:2000])
        return False
    box = json.loads(html.unescape(m.group(1)))
    for it in box["res"]:
        print("  %s %s" % ("OK  " if it["ok"] else "FAIL", it["name"])
              + (("   ← " + it["detail"]) if (not it["ok"] and it["detail"]) else ""))
    if box["perr"]:
        print("  页面报错：")
        for e in box["perr"][:6]:
            print("    ! %s" % e)
    print("  —— %s（%d 条，失败 %d，页面报错 %d）"
          % ("✅ 全过" if box["ok"] and not box["perr"] else "✗ 有不对的",
             box["n"], box["bad"], len(box["perr"])))
    return bool(box["ok"] and not box["perr"])


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                                # noqa: BLE001
            pass
    exe = browser()
    if not exe:
        print("[跳过] 找不到 Edge/Chrome —— 这个探针要一个浏览器来真跑界面")
        return 0
    pdir = ROOT / "system" / "pkgs" / "path"
    if not pdir.is_dir():
        print("找不到 %s" % pdir)
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="moss_pathprobe_"))
    try:
        dst = tmp / "path"
        shutil.copytree(pdir, dst)
        # 第一程：这一页自己（假后端 + 真点击，验"先改后存"和新界面那几处交互）
        p1 = build_page(dst, "probe1.html", DRIVER)
        ok1 = report(dump(exe, p1, tmp), exe, "一程：这一页自己（先改后存 / 高亮 / 保存 / 每行操作 / 拖动排序 / 双击改名）")
        # 第二程：把这一页塞进 iframe，父页面扮"宿主"，验"取消一次不许弹两个框"
        p2 = build_page(dst, "probe2.html", PICK_DRIVER)
        host = tmp / "host.html"
        host.write_text(PICK_HOST, encoding="utf-8")
        print()
        ok2 = report(dump(exe, host, tmp), exe, "二程：内嵌在宿主里挑文件夹（取消 / 选到 / 没桥 / 老宿主）")
        # 第三程：量一遍设计稿的尺寸/颜色（不靠眼睛看图），顺带钉住"一个外网资源都没有"
        p3 = build_page(dst, "probe3.html", STYLE_DRIVER)
        print()
        ok3 = report(dump(exe, p3, tmp), exe, "三程：量关键尺寸与配色（对着设计稿的 Tailwind 数值）")
        # 第四程：窄窗口下也不许塌成一列（`V-215`）
        p4 = build_page(dst, "probe4.html", NARROW_DRIVER)
        print()
        ok4 = report(dump(exe, p4, tmp, size="760,900"), exe, "四程：窄窗口（760px）下仍是固定的左右两栏")
        print("=" * 72)
        print("结论：%s（四程都过才算过）" % ("✅ 全过" if (ok1 and ok2 and ok3 and ok4) else "✗ 有不对的"))
        return 0 if (ok1 and ok2 and ok3 and ok4) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
