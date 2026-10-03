/* PATH 管理 —— 界面（Vue 3，`V-213`：照新设计稿一比一重做外观）。
   ★ 这里**不做业务**：改注册表、读写备份、"会加什么/会去掉什么"全在 `main.py`。
     这一层只干两件事：把动作交给后端（`moss.call`），把结果画出来。
   ★ **先改后存**（`V-211`）：加 / 删 / 去重 / 清失效 / **拖动排序**都只改界面上的草稿（`paths`）；
     新加进来的那些挂着 `.fresh` 高亮 + 「未保存」小标签，一直亮到点「保存修改」为止。
     `saved` 是注册表里那一份，两者一比就知道脏没脏（`dirty`）、有几处（`pendingN`）。
   ★ 反馈一律走 **Toast**（设计稿那套：底部居中、成功绿勾、失败红底）—— 底栏留给"状态 + 提示"，
     同一件事不在一屏里说两遍（`V-211` 的教训）。
   ★ 拖文件夹进来（`V-201`）：独立窗口走宿主 pywebview、内嵌走 moss 主界面转发 ——
     两条路都是 `moss.on("drop")`。**列表内的拖动**是调优先级（HTML5 DnD），两回事：
     前者拖的是"系统里的文件"（`dataTransfer` 里有 `Files`），后者拖的是页面里的行。 */
const { createApp, ref, reactive, computed, onMounted } = Vue;

createApp({
  setup() {
    const paths = ref([]);            // 草稿（顺序 = 保存时写回注册表的顺序 = PATH 的优先级）
    const saved = ref([]);            // 注册表里那一份
    const missing = ref([]);
    const selfDir = ref("");
    const dataDir = ref("");
    const backupDir = ref("");
    const info = reactive({ pid: 0, python: "" });
    const input = ref("");
    const inputWarn = ref("");
    const busy = ref(false);
    const dragOn = ref(false);
    const backups = ref([]);
    const hovered = ref("");          // 鼠标停在哪个备份上（`V-214`：一 hover 就自动对比）
    const pinned = ref("");           // 被"固定住"的那份（点了「对比」就不随鼠标收起来）
    const showAllMap = reactive({});  // 每张卡片各自的"显示全部 / 仅看差异"
    const toasts = ref([]);           // 底部那串提示
    // 备份起名 / 改名（`V-209`）
    const naming = ref(false);
    const bkName = ref("");
    const renaming = ref(null);       // 正在改名的那一份（存 file 全路径）
    const renameVal = ref("");
    const armed = ref(false);         // 「刷新」点第一下只提醒（有草稿时）
    const leaving = ref("");          // 正在播"消失"动画的那一行
    // 列表里拖动排序（调优先级）
    const dragArmed = ref(null);
    const dragFrom = ref(null);
    const dragOver = ref(-1);

    const ic = (n) => icon(n, "i");
    /* 比大小写、比斜杠 —— 但**不动顺序**（顺序就是 PATH 的优先级，不能顺手重排）。
       `C:\A`、`c:/a`、`C:\A\` 认成同一条。 */
    const keyOf = (p) => String(p || "").trim().replace(/^"(.*)"$/, "$1")
      .replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
    const has = (list, p) => list.some((x) => keyOf(x) === keyOf(p));

    // ---- Toast（`V-213`）：底部居中、2.5 秒自己走；同一个内容叠着刷就换掉旧的
    let toastSeq = 0;
    function toast(text, type) {
      const s = String(text || "").trim();
      if (!s) return;
      const kind = type === "error" ? "error" : (type === "success" ? "success" : "info");
      const old = toasts.value.find((t) => t.text === s && t.type === kind);
      if (old) {
        clearTimeout(old.t);
        toasts.value = toasts.value.filter((t) => t !== old);
      }
      const item = { id: ++toastSeq, text: s, type: kind, t: 0 };
      toasts.value = toasts.value.concat([item]).slice(-3);      // 最多留 3 条，别糊一屏
      item.t = setTimeout(() => { toasts.value = toasts.value.filter((t) => t.id !== item.id); },
                          kind === "error" ? 4200 : 2500);
    }
    const say = (m, bad) => toast(m, bad ? "error" : "success");

    const pathCount = computed(() => paths.value.length);
    const savedKeys = computed(() => saved.value.map(keyOf));
    const workKeys = computed(() => paths.value.map(keyOf));
    const pendingN = computed(() => {
      // 按**条数**算差（注册表里本来就可能有一模一样的两条：去重去掉一条也算一处改动）
      const tally = (ks) => {
        const m = new Map();
        ks.forEach((k) => m.set(k, (m.get(k) || 0) + 1));
        return m;
      };
      const s = tally(savedKeys.value), w = tally(workKeys.value);
      let n = 0;
      w.forEach((c, k) => { n += Math.max(0, c - (s.get(k) || 0)); });
      s.forEach((c, k) => { n += Math.max(0, c - (w.get(k) || 0)); });
      return n;
    });
    const dirty = computed(() => workKeys.value.join("\n") !== savedKeys.value.join("\n"));
    const isFresh = (p) => !has(saved.value, p);       // 还没保存过的新条目 ⇒ 亮着
    const isMissing = (p) => missing.value.some((m) => keyOf(m) === keyOf(p));
    const missingN = computed(() => paths.value.filter(isMissing).length);
    const hasMissing = computed(() => missingN.value > 0);
    const hasDup = computed(() => new Set(workKeys.value).size !== workKeys.value.length);
    const anyAction = computed(() => hasDup.value || hasMissing.value || dirty.value);

    // ---- 差异面板（设计稿那张"会加 / 会去掉 / 一样"的表）
    /* ★ `V-214`：比的是**你现在界面上的这份清单**（草稿），不是注册表里那份 ——
       存没存都按界面来（你看到的清单就是它要比的东西），所以这个提示也不需要了。
       也正因为是本地算的：**一 hover 就能立刻展开**（不用先问后端一趟），改了草稿它跟着变。 */
    function diffsOf(b) {
      const bkPaths = (b && b.paths) || [];
      const cur = paths.value;
      const inCur = new Set(cur.map(keyOf));
      const inBk = new Set(bkPaths.map(keyOf));
      const out = [];
      bkPaths.forEach((p) => out.push({ type: inCur.has(keyOf(p)) ? "same" : "add", path: p }));
      cur.forEach((p) => { if (!inBk.has(keyOf(p))) out.push({ type: "del", path: p }); });
      return showAllOf(b) ? out : out.filter((d) => d.type !== "same");
    }
    const showAllOf = (b) => !!(b && showAllMap[b.file]);
    function toggleAll(b) { if (b) showAllMap[b.file] = !showAllMap[b.file]; }
    // 一 hover 就展开、移开就收；点过「对比」的那份钉住不收
    const isOpen = (b) => !!b && (pinned.value === b.file || hovered.value === b.file);
    function hoverOn(b) { if (b) hovered.value = b.file; }
    function hoverOff(b) { if (b && hovered.value === b.file) hovered.value = ""; }
    function togglePin(b) {
      if (!b) return;
      pinned.value = pinned.value === b.file ? "" : b.file;
      if (pinned.value) hovered.value = b.file;
    }

    function applyState(s, force) {
      if (!s) return;
      saved.value = s.paths || [];
      if (force || !dirty.value) paths.value = saved.value.slice();   // 有草稿就别覆盖它
      missing.value = s.missing || [];
      selfDir.value = s.self_dir || "";
      dataDir.value = s.data_dir || "";
      backupDir.value = s.backup_dir || "";
    }
    async function call(method, params, quiet) {
      if (!quiet) busy.value = true;
      try {
        return await window.moss.call(method, params || {});
      } catch (e) {
        say("调后端失败：" + (e && e.message ? e.message : e), true);
        return null;
      } finally {
        if (!quiet) busy.value = false;
      }
    }

    // ---- 草稿：增 / 删 / 去重 / 清失效 / 排序（一律不碰注册表）
    function addLocal(p) {
      const v = String(p || "").trim().replace(/^"(.*)"$/, "$1");
      if (!v) return { ok: false, msg: "先给一个目录" };
      if (has(paths.value, v)) return { ok: false, msg: "这条已经在列表里了：" + v };
      paths.value.push(v);
      return { ok: true, msg: "加进列表了（还没保存）：" + v };
    }
    function remove(p) {
      if (leaving.value) return;
      leaving.value = p;                                  // 先播"消失"动画（设计稿那 300ms）
      setTimeout(() => {
        paths.value = paths.value.filter((x) => keyOf(x) !== keyOf(p));
        leaving.value = "";
        say("从列表里去掉了（点「保存修改」才写进 PATH）：" + p);
      }, 300);
    }
    function dedup() {
      const seen = new Set(), keep = [];
      let n = 0;
      for (const p of paths.value) {
        const k = keyOf(p);
        if (seen.has(k)) { n++; continue; }
        seen.add(k); keep.push(p);
      }
      if (!n) return say("没有重复项", true);
      paths.value = keep;
      say("去掉 " + n + " 条重复项（点「保存修改」才写进 PATH）");
    }
    function dropMissing() {
      const gone = paths.value.filter((p) => isMissing(p));
      if (!gone.length) return say("没有失效的目录", true);
      const drop = new Set(gone.map(keyOf));
      paths.value = paths.value.filter((p) => !drop.has(keyOf(p)));
      say("摘掉 " + gone.length + " 条目录已经不存在的");
    }
    function revert() {
      if (!dirty.value) return say("没有没保存的改动");
      paths.value = saved.value.slice();
      armed.value = false;
      say("已撤销 —— 回到注册表里现在的样子");
    }
    async function save() {
      const r = await call("save", { paths: paths.value });
      if (!r) return;
      applyState(r.state, r.ok);       // 写成功了才用后端那份覆盖草稿（高亮随之全灭）
      armed.value = false;
      say(r.msg, !r.ok);
    }
    // 复制一条路径（设计稿每行第一颗按钮）
    function copyPath(p) {
      try {
        const ta = document.createElement("textarea");
        ta.value = String(p);
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(ta);
        say(ok ? "路径已复制到剪贴板" : "复制没成功（浏览器不给）", !ok);
      } catch (e) {
        say("复制失败：" + (e && e.message ? e.message : e), true);
      }
    }
    /* 「拿出来改」：把这一条填回上面的输入框、同时从草稿里去掉 ——
       改完点「添加」它就按改后的样子回来（顺序排在最后）。比"就地编辑"少一个后端接口，
       而且**改的仍然是草稿**：不点保存，注册表一个字节都不动。 */
    function editPath(p) {
      input.value = String(p);
      inputWarn.value = "";
      paths.value = paths.value.filter((x) => keyOf(x) !== keyOf(p));
      say("已拿出来改：改好点「添加」放回去，再点「保存修改」");
    }

    // ---- 列表里拖动排序（= 调 PATH 优先级；同样只改草稿）
    function dragStart(p, e) {
      dragFrom.value = p;
      dragArmed.value = null;
      try { e.dataTransfer.setData("text/plain", String(p)); e.dataTransfer.effectAllowed = "move"; }
      catch (err) { /* 无所谓 */ }
    }
    function dragOverRow(i, e) {
      if (!dragFrom.value) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = "move"; } catch (err) { /* 无所谓 */ }
      dragOver.value = i;
    }
    function dropAt(i, e) {
      e.preventDefault();
      const from = paths.value.indexOf(dragFrom.value);
      if (from < 0) return dragEnd();
      const to = from < i ? i - 1 : i;            // 指示线画在"这一行上面" ⇒ 插到它前面
      if (to !== from) {
        const arr = paths.value.slice();
        const [it] = arr.splice(from, 1);
        arr.splice(to, 0, it);
        paths.value = arr;
        say("顺序变了（点「保存修改」才写进 PATH）");
      }
      dragEnd();
    }
    function dragEnd() { dragFrom.value = null; dragArmed.value = null; dragOver.value = -1; }

    // ---- 读
    async function fetchState() {
      const r = await call("state");
      if (r) { applyState(r, true); }
    }
    async function load() {                       // 「刷新」按钮：有草稿先问一声
      if (dirty.value && !armed.value) {
        armed.value = true;
        return say("有 " + pendingN.value + " 处改动没保存 —— 再点一下「刷新」就丢掉它们", true);
      }
      armed.value = false;
      await fetchState();
    }
    async function syncFromHost() {               // 宿主喊我们（切回来 / 被调用）：别悄悄丢掉草稿
      if (dirty.value) return;
      await fetchState();
    }

    // ---- 「添加」：输入框空着 = 选文件夹；有内容 = 先问后端这是不是个真目录
    /* 挑文件夹（`V-211`，`V-212` 修过一次"弹两次"）：
       · 内嵌在 moss 里 ⇒ 先问**主界面**要（那扇窗有正规的系统对话框；同源 iframe 直接可用）；
       · **主界面答了话就不再往下走** —— 用户自己关掉对话框（`cancelled`）是"这次不选"，不是
         "这条路走不通"。以前分不清这两件事：取消 ⇒ 没拿到路径 ⇒ 又去问包自己的后端
         ⇒ **第二个框又弹出来**（你点的就是这条）。
       · 只有**根本没问到**（没有桥 / 主界面还没准备好 / 调用抛错）才退回包自己的选择框 ——
         独立开窗时就是这条路（`window.parent === window`，压根没有主界面可问）。 */
    async function pickDir() {
      try {
        const top = window.parent && window.parent !== window ? window.parent : null;
        if (top && top.pywebview && top.pywebview.api && top.pywebview.api.pick_dir) {
          const r = await top.pywebview.api.pick_dir("");
          if (r && r.ok && r.path) return r.path;
          // 用户取消（`cancelled` 是宿主给的准信；老宿主只有一句话，就认那句话）
          if (r && (r.cancelled || /取消|没有选/.test(r.msg || ""))) return "";
          if (r && r.msg) say(r.msg, true);            // 窗口没准备好之类：退回包自己那条
        }
      } catch (e) { /* 问不到（跨源 / 没有桥）就走后端那条 */ }
      const r = await call("pick_dir", { start: paths.value[0] || "" });
      if (r && r.ok) return r.path || "";
      if (r && r.msg && !/取消|没有选/.test(r.msg)) say(r.msg, true);   // 取消不算错，不报红
      return "";
    }
    async function add() {
      const raw = input.value.trim();
      if (!raw) {                                  // 空着 ⇒ 弹文件夹选择框
        const dir = await pickDir();
        inputWarn.value = "";
        if (!dir) return;
        const a = addLocal(dir);
        input.value = "";
        say(a.msg, !a.ok);
        return;
      }
      const r = await call("probe_path", { path: raw });   // 有内容 ⇒ 问一句"这是啥"
      if (!r) return;
      if (!r.ok) { inputWarn.value = r.msg; return say(r.msg, true); }   // 不存在：报错，输入框不动
      const a = addLocal(r.path);
      if (a.ok && r.kind === "file") say(r.msg + "（还没保存）");
      else say(a.msg, !a.ok);
      if (a.ok) { input.value = ""; inputWarn.value = ""; }
    }
    function clearInput() { input.value = ""; inputWarn.value = ""; }

    // 输入框里随手看一眼"像不像个路径 / 到底在不在"（设计稿那个会跳的警告三角）
    let probeTimer = 0;
    function watchInput() {
      clearTimeout(probeTimer);
      const v = input.value.trim();
      inputWarn.value = "";
      if (!v) return;
      if (!/^([a-zA-Z]:[\\/]|%[a-zA-Z0-9_()]+%|\\\\|\/)/.test(v)) {
        inputWarn.value = "这看着不像个路径（盘符 / %变量% / UNC 总得有一个）";
        return;
      }
      probeTimer = setTimeout(async () => {
        const r = await call("probe_path", { path: v }, true);   // 只读、不占 busy（别让按钮跟着闪）
        if (r && !r.ok && String(input.value).trim() === v) inputWarn.value = r.msg;
      }, 350);
    }

    // ---- 拖进来的（`V-201`）：同样只进草稿
    async function onDrop(items) {
      dragOn.value = false;
      const list = (items || []).map((it) => String(it || "")).filter(Boolean);
      if (!list.length) return;
      let added = 0, dup = 0, bad = 0;
      for (const it of list) {
        const r = await call("probe_path", { path: it });
        if (!r || !r.ok) { bad++; continue; }
        if (addLocal(r.path).ok) added++; else dup++;
      }
      const bits = [];
      if (added) bits.push("加进列表 " + added + " 条（记得点「保存修改」）");
      if (dup) bits.push("跳过 " + dup + " 条重复");
      if (bad) bits.push("跳过 " + bad + " 条目录不存在");
      say(bits.join("；") || "没拿到可用的目录", !added);
    }

    // ---- 备份
    /* 起名（`V-209`）：默认还是时间戳，想改就改 —— 输入框预填的就是"默认会用的那个名字"，
       不改直接回车 = 和以前一样。 */
    function defaultName() {
      const d = new Date(), p = (n) => String(n).padStart(2, "0");
      return "path_backup_" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" +
             p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
    }
    function startBackup() {
      naming.value = true;
      bkName.value = defaultName();
      Vue.nextTick(() => { const i = document.getElementById("bk-name-input"); if (i) { i.focus(); i.select(); } });
    }
    async function doBackup() {
      const name = bkName.value.trim();
      const r = await call("backup_create", { name: name });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      if (r.ok) naming.value = false;
      await openBackups();
    }
    // 双击名字改名（`V-211`）：默认名的备份预填文件名（去掉路径和 .txt）
    function startRename(b) {
      renaming.value = b.file;
      renameVal.value = b.name || stemOf(b.file);
      Vue.nextTick(() => { const i = document.getElementById("bk-rename-input"); if (i) { i.focus(); i.select(); } });
    }
    function stemOf(f) {
      return String(f || "").replace(/^.*[\\/]/, "").replace(/\.txt$/i, "");
    }
    async function doRename(b) {
      const r = await call("backup_rename", { file: b.file, name: renameVal.value.trim() });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      if (r.ok) renaming.value = null;
      await openBackups();
    }
    async function openBackups() {
      const r = await call("backup_list");
      if (!r) return;
      backups.value = r.items || [];
      applyState(r.state);
      if (pinned.value && !backups.value.some((b) => b.file === pinned.value)) pinned.value = "";
      if (hovered.value && !backups.value.some((b) => b.file === hovered.value)) hovered.value = "";
      // 没备份**不用**再在别处念一句 —— 右栏空状态自己就写着"点上面「备份当前」"（`V-211`）
    }
    async function restore(b) {
      const r = await call("backup_restore", { file: (b || {}).file || "" });
      if (!r) return;
      applyState(r.state, r.ok);       // 恢复是真的写注册表 ⇒ 草稿跟着换成新的这份
      armed.value = false;
      say(r.msg, !r.ok);
      pinned.value = ""; hovered.value = "";
      await openBackups();
    }
    async function delBackup(b) {
      const r = await call("backup_delete", { file: b.file });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      if (pinned.value === b.file) pinned.value = "";
      if (hovered.value === b.file) hovered.value = "";
      await openBackups();
    }

    const same = (a, b) => !!a && !!b && keyOf(a) === keyOf(b);
    const shortData = computed(() => {
      const d = dataDir.value || "";
      const parts = d.replace(/\\/g, "/").split("/").filter(Boolean);
      return parts.length <= 3 ? d : "…/" + parts.slice(-3).join("/");
    });

    // 输入框一变就看一眼（v-model 之后跑）
    Vue.watch(input, watchInput);

    onMounted(async () => {
      // 后端 / 宿主送来的事件
      window.moss.on("drop", (d) => onDrop((d && d.items) || []));
      window.moss.on("invoke", () => syncFromHost());
      window.moss.on("visible", (d) => { if (d && d.visible) syncFromHost(); });
      // 页面自己也接一次 HTML5 拖放：① 独立窗口里给个"正在拖"的反馈；
      // ② 真实路径那条（moss 宿主 / pywebview）没来的时候不至于一点反应都没有。
      // ★ 只认**系统文件**（`dataTransfer.types` 里有 `Files`）—— 列表内拖行不该把这层提示叫出来。
      let depth = 0;
      let captured = false;      // 宿主铺了罩子接住（`V-205`）：这期间别自己把提示收掉
      window.moss.on("dragend", () => { dragOn.value = false; depth = 0; captured = false; });
      window.moss.on("captured", () => { captured = true; dragOn.value = true; });
      window.addEventListener("dragenter", (e) => {
        if (!(e.dataTransfer && (e.dataTransfer.types || []).indexOf("Files") >= 0)) return;
        e.preventDefault(); depth++; dragOn.value = true;
      });
      window.addEventListener("dragover", (e) => { e.preventDefault(); });
      window.addEventListener("dragleave", () => {
        if (captured) return;                    // 罩子盖上来引起的那次 leave 不算（`V-205`）
        if (--depth <= 0) { depth = 0; dragOn.value = false; }
      });
      window.addEventListener("drop", (e) => { e.preventDefault(); dragOn.value = false; depth = 0; });

      try { Object.assign(info, await window.moss.call("info", {})); } catch (e) { /* 无妨 */ }
      await fetchState();
      await openBackups();          // 右边那一栏一进来就有东西看
    });

    return { paths, saved, missing, selfDir, dataDir, backupDir, info, input, inputWarn, busy,
             dragOn, backups, hovered, pinned, toasts, pathCount, pendingN, dirty, missingN,
             hasDup, hasMissing, anyAction, diffsOf, showAllOf, isOpen, hoverOn, hoverOff, togglePin,
             shortData, ic,
             naming, bkName, renaming, renameVal, leaving, dragArmed, dragFrom, dragOver,
             load, save, revert, add, remove, dedup, dropMissing, clearInput, copyPath, editPath,
             dragStart, dragOverRow, dropAt, dragEnd,
             startBackup, doBackup, startRename, doRename, openBackups, toggleAll,
             restore, delBackup, isMissing, isFresh, same };
  },
}).mount("#app");
