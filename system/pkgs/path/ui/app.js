const { createApp, ref, reactive, computed, onMounted } = Vue;

createApp({
  setup() {
    const paths = ref([]);            
    const saved = ref([]);            
    const missing = ref([]);

    const sysSaved = ref([]);
    const sysDraft = ref([]);
    const sysMissing = ref([]);
    const sysBackupDir = ref("");
    const sysEditing = ref(-1);       
    const sysEditVal = ref("");
    const sysInput = ref("");         
    const sysDragFrom = ref(null);    
    const sysDragOver = ref(-1);
    const selfDir = ref("");
    const dataDir = ref("");
    const backupDir = ref("");
    const info = reactive({ pid: 0, python: "" });
    const input = ref("");
    const inputWarn = ref("");
    const busy = ref(false);
    const dragOn = ref(false);
    const backups = ref([]);
    const hovered = ref("");          
    const pinned = ref("");           
    const showAllMap = reactive({});  
    const toasts = ref([]);           

    const drawer = ref(false);

    const naming = ref(false);
    const bkName = ref("");
    const renaming = ref(null);       
    const renameVal = ref("");
    const armed = ref(false);         
    const leaving = ref("");          

    const dragArmed = ref(null);
    const dragFrom = ref(null);
    const dragOver = ref(-1);

    const ic = (n) => icon(n, "i");

    const keyOf = (p) => String(p || "").trim().replace(/^"(.*)"$/, "$1")
      .replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
    const has = (list, p) => list.some((x) => keyOf(x) === keyOf(p));

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

      const keep = toasts.value.filter((t) => t.type !== kind &&
                                             (kind === "info" || t.type !== "info"));
      toasts.value = keep.concat([item]).slice(-2);
      item.t = setTimeout(() => { toasts.value = toasts.value.filter((t) => t.id !== item.id); },
                          kind === "error" ? 4200 : 2500);
    }
    const say = (m, bad) => toast(m, bad ? "error" : "success");

    const note = (m) => toast(m, "info");

    const pathCount = computed(() => paths.value.length);
    const savedKeys = computed(() => saved.value.map(keyOf));
    const workKeys = computed(() => paths.value.map(keyOf));
    const pendingN = computed(() => {
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
    const isFresh = (p) => !has(saved.value, p);       
    const isMissing = (p) => missing.value.some((m) => keyOf(m) === keyOf(p));

    const sysCount = computed(() => sysDraft.value.length);
    const sysDirty = computed(
      () => sysDraft.value.map(keyOf).join("\n") !== sysSaved.value.map(keyOf).join("\n"));
    const sysPendingN = computed(() => {
      const tally = (ks) => {
        const m = new Map();
        ks.forEach((k) => m.set(k, (m.get(k) || 0) + 1));
        return m;
      };
      const s = tally(sysSaved.value.map(keyOf)), w = tally(sysDraft.value.map(keyOf));
      let n = 0;
      w.forEach((c, k) => { n += Math.max(0, c - (s.get(k) || 0)); });
      s.forEach((c, k) => { n += Math.max(0, c - (w.get(k) || 0)); });
      return n;
    });
    const isSysMissing = (p) => sysMissing.value.some((m) => keyOf(m) === keyOf(p));
    const shortSysBak = computed(() => {
      const d = sysBackupDir.value || "";
      const parts = d.replace(/\\/g, "/").split("/").filter(Boolean);
      return parts.length <= 3 ? d : "…/" + parts.slice(-2).join("/");
    });
    const missingN = computed(() => paths.value.filter(isMissing).length);
    const hasMissing = computed(() => missingN.value > 0);
    const hasDup = computed(() => new Set(workKeys.value).size !== workKeys.value.length);
    const anyAction = computed(() => hasDup.value || hasMissing.value || dirty.value);

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
      if (force || !dirty.value) paths.value = saved.value.slice();   
      missing.value = s.missing || [];
      sysSaved.value = s.sys_paths || [];

      if (force || !sysDirty.value) {
        sysDraft.value = sysSaved.value.slice();
        sysEditing.value = -1;
      }
      sysMissing.value = s.sys_missing || [];
      sysBackupDir.value = s.sys_backup_dir || "";
      selfDir.value = s.self_dir || "";
      dataDir.value = s.data_dir || "";
      backupDir.value = s.backup_dir || "";
    }

    function plain(v) {
      if (v === undefined || v === null) return {};
      try { return JSON.parse(JSON.stringify(v)); } catch (e) { return {}; }
    }

    async function call(method, params, quiet) {
      if (!quiet) busy.value = true;
      try {
        return await window.moss.call(method, plain(params));
      } catch (e) {
        say("调后端失败：" + (e && e.message ? e.message : e), true);
        return null;
      } finally {
        if (!quiet) busy.value = false;
      }
    }

    function addLocal(p) {
      const v = String(p || "").trim().replace(/^"(.*)"$/, "$1");
      if (!v) return { ok: false, msg: "先给一个目录" };
      if (has(paths.value, v)) return { ok: false, msg: "这条已经在列表里了：" + v };
      paths.value.push(v);
      return { ok: true, msg: "加进列表了（还没保存）" };   
    }
    function remove(p) {
      if (leaving.value) return;
      leaving.value = p;                                  
      setTimeout(() => {
        paths.value = paths.value.filter((x) => keyOf(x) !== keyOf(p));
        leaving.value = "";
        note("从列表里去掉了（还没保存）");
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
      if (!n) return note("没有重复项");
      paths.value = keep;
      note("去掉 " + n + " 条重复项（还没保存）");
    }
    function dropMissing() {
      const gone = paths.value.filter((p) => isMissing(p));
      if (!gone.length) return note("没有失效的目录");
      const drop = new Set(gone.map(keyOf));
      paths.value = paths.value.filter((p) => !drop.has(keyOf(p)));
      note("摘掉 " + gone.length + " 条目录已经不存在的（还没保存）");
    }
    function revert() {
      if (!dirty.value) return note("没有没保存的改动");
      paths.value = saved.value.slice();
      armed.value = false;
      note("已撤销 — 回到注册表里现在的样子");
    }
    async function save() {
      const r = await call("save", { paths: paths.value });
      if (!r) return;
      applyState(r.state, r.ok);       
      armed.value = false;
      say(r.msg, !r.ok);
    }

    function sysAdd() {
      const v = String(sysInput.value || "").trim().replace(/^"(.*)"$/, "$1");
      if (!v) return note("先给一个目录");
      if (sysDraft.value.some((x) => keyOf(x) === keyOf(v))) return note("系统里已经有这条了");
      sysDraft.value = sysDraft.value.concat([v]);
      sysInput.value = "";
      note("加进系统级了（还没保存）");
    }
    function sysRemove(i) {
      sysDraft.value = sysDraft.value.filter((_, k) => k !== i);
      sysEditing.value = -1;
      note("从系统级去掉了（还没保存）");
    }
    function sysBeginEdit(i) {
      sysEditing.value = i;
      sysEditVal.value = sysDraft.value[i];
      Vue.nextTick(() => { const el = document.querySelector(".srow .sin"); if (el) { el.focus(); el.select(); } });
    }
    function sysCommitEdit(i) {
      if (sysEditing.value !== i) return;
      sysEditing.value = -1;
      const v = String(sysEditVal.value || "").trim().replace(/^"(.*)"$/, "$1");
      if (!v) return note("空的不算，这一条没改");
      if (sysDraft.value.some((x, k) => k !== i && keyOf(x) === keyOf(v))) return note("改完就和另一条重复了，没改");
      const arr = sysDraft.value.slice();
      arr[i] = v;
      sysDraft.value = arr;
      note("改好了（还没保存）");
    }
    function sysDragStart(p, e) {
      sysDragFrom.value = p;
      sysEditing.value = -1;
      try { e.dataTransfer.setData("text/plain", String(p)); e.dataTransfer.effectAllowed = "move"; }
      catch (err) {  }
    }
    function sysDragOverAt(i, e) {
      if (sysDragFrom.value === null) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = "move"; } catch (err) {  }
      sysDragOver.value = i;
    }
    function sysDropAt(i, e) {
      e.preventDefault();
      const from = sysDraft.value.indexOf(sysDragFrom.value);
      if (from < 0) return sysDragEnd();
      const to = from < i ? i - 1 : i;
      if (to !== from) {
        const arr = sysDraft.value.slice();
        const [it] = arr.splice(from, 1);
        arr.splice(to, 0, it);
        sysDraft.value = arr;
        note("系统级的先后变了（还没保存）");
      }
      sysDragEnd();
    }
    function sysDragEnd() { sysDragFrom.value = null; sysDragOver.value = -1; }

    let scanTimer = 0;
    function scheduleScan() {
      clearTimeout(scanTimer);
      scanTimer = setTimeout(async () => {
        const all = paths.value.concat(sysDraft.value);
        const r = await call("scan", { paths: all }, true);
        if (!r || !r.missing) return;
        const gone = new Set(r.missing.map(keyOf));
        missing.value = paths.value.filter((p) => gone.has(keyOf(p)));
        sysMissing.value = sysDraft.value.filter((p) => gone.has(keyOf(p)));
      }, 250);
    }
    Vue.watch(paths, scheduleScan, { deep: true });
    Vue.watch(sysDraft, scheduleScan, { deep: true });

    function sysRevert() {
      if (!sysDirty.value) return note("系统级没有未保存的改动");
      sysDraft.value = sysSaved.value.slice();
      sysEditing.value = -1;
      note("已撤销 — 回到系统里现在的样子");
    }
    async function sysSave() {
      if (!sysDirty.value) return say("系统级没有未保存的改动");
      busy.value = true;
      toast("等一下 UAC 弹窗：点「是」才会改系统 PATH", "info");
      const r = await call("sys_save", { paths: sysDraft.value }, true);
      busy.value = false;
      if (!r) return;
      applyState(r.state, false);      

      if (!r.ok && /取消/.test(r.msg || "")) return toast(r.msg, "info");
      say(r.msg, !r.ok);
    }

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

    function editPath(p) {
      input.value = String(p);
      inputWarn.value = "";
      paths.value = paths.value.filter((x) => keyOf(x) !== keyOf(p));
      note("填到上面了：改完点「添加」放回去");
      Vue.nextTick(() => { const el = document.getElementById("path-input"); if (el) { el.focus(); el.select(); } });
    }

    function dragStart(p, e) {
      dragFrom.value = p;
      dragArmed.value = null;
      try { e.dataTransfer.setData("text/plain", String(p)); e.dataTransfer.effectAllowed = "move"; }
      catch (err) {  }
    }
    function dragOverRow(i, e) {
      if (!dragFrom.value) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = "move"; } catch (err) {  }
      dragOver.value = i;
    }
    function dropAt(i, e) {
      e.preventDefault();
      const from = paths.value.indexOf(dragFrom.value);
      if (from < 0) return dragEnd();
      const to = from < i ? i - 1 : i;            
      if (to !== from) {
        const arr = paths.value.slice();
        const [it] = arr.splice(from, 1);
        arr.splice(to, 0, it);
        paths.value = arr;
        note("顺序变了（还没保存）");
      }
      dragEnd();
    }
    function dragEnd() { dragFrom.value = null; dragArmed.value = null; dragOver.value = -1; }

    async function fetchState() {
      const r = await call("state");
      if (r) { applyState(r, true); }
    }
    async function load() {                       
      if (dirty.value && !armed.value) {
        armed.value = true;
        return note("有 " + pendingN.value + " 处改动没保存 — 再点一下「刷新」就丢掉它们");
      }
      armed.value = false;
      await fetchState();
    }
    async function syncFromHost() {               
      if (dirty.value) return;
      await fetchState();
    }

    async function pickDir() {
      try {
        const top = window.parent && window.parent !== window ? window.parent : null;
        if (top && top.pywebview && top.pywebview.api && top.pywebview.api.pick_dir) {
          const r = await top.pywebview.api.pick_dir("");
          if (r && r.ok && r.path) return r.path;

          if (r && (r.cancelled || /取消|没有选/.test(r.msg || ""))) return "";
          if (r && r.msg) say(r.msg, true);            
        }
      } catch (e) {  }
      const r = await call("pick_dir", { start: paths.value[0] || "" });
      if (r && r.ok) return r.path || "";
      if (r && r.msg && !/取消|没有选/.test(r.msg)) say(r.msg, true);   
      return "";
    }
    async function add() {
      const raw = input.value.trim();
      if (!raw) {                                  
        const dir = await pickDir();
        inputWarn.value = "";
        if (!dir) return;
        const a = addLocal(dir);
        input.value = "";
        say(a.msg, !a.ok);
        return;
      }
      const r = await call("probe_path", { path: raw });   
      if (!r) return;
      if (!r.ok) { inputWarn.value = r.msg; return say(r.msg, true); }   
      const a = addLocal(r.path);
      if (a.ok && r.kind === "file") note("加进列表了（拖的是文件，取的是它所在的目录；还没保存）");
      else if (a.ok) note(a.msg);
      else note(a.msg);
      if (a.ok) { input.value = ""; inputWarn.value = ""; }
    }
    function clearInput() { input.value = ""; inputWarn.value = ""; }

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
        const r = await call("probe_path", { path: v }, true);   
        if (r && !r.ok && String(input.value).trim() === v) inputWarn.value = r.msg;
      }, 350);
    }

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
      if (added) bits.push("加进列表 " + added + " 条（还没保存）");
      if (dup) bits.push("跳过 " + dup + " 条重复");
      if (bad) bits.push("跳过 " + bad + " 条目录不存在");
      if (added) note(bits.join("；"));
      else toast(bits.join("；") || "没拿到可用的目录", "error");
    }

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

    async function openDrawer() {
      drawer.value = true;
      await openBackups();
    }
    function closeDrawer() { drawer.value = false; }

    async function openBackups() {
      const r = await call("backup_list", {}, true);   
      if (!r) return;
      backups.value = r.items || [];
      applyState(r.state);
      if (pinned.value && !backups.value.some((b) => b.file === pinned.value)) pinned.value = "";
      if (hovered.value && !backups.value.some((b) => b.file === hovered.value)) hovered.value = "";

    }
    async function restore(b) {
      const r = await call("backup_restore", { file: (b || {}).file || "" });
      if (!r) return;
      applyState(r.state, r.ok);       
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

    Vue.watch(input, watchInput);

    onMounted(async () => {
      window.moss.on("drop", (d) => onDrop((d && d.items) || []));
      window.moss.on("invoke", () => syncFromHost());
      window.moss.on("visible", (d) => { if (d && d.visible) syncFromHost(); });

      let depth = 0;
      let captured = false;      
      window.moss.on("dragend", () => { dragOn.value = false; depth = 0; captured = false; });
      window.moss.on("captured", () => { captured = true; dragOn.value = true; });
      window.addEventListener("dragenter", (e) => {
        if (!(e.dataTransfer && (e.dataTransfer.types || []).indexOf("Files") >= 0)) return;
        e.preventDefault(); depth++; dragOn.value = true;
      });
      window.addEventListener("dragover", (e) => { e.preventDefault(); });
      window.addEventListener("dragleave", () => {
        if (captured) return;                    
        if (--depth <= 0) { depth = 0; dragOn.value = false; }
      });
      window.addEventListener("drop", (e) => { e.preventDefault(); dragOn.value = false; depth = 0; });

      window.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (drawer.value) { closeDrawer(); return; }
        if (sysEditing.value >= 0) { sysEditing.value = -1; return; }
        if (naming.value) naming.value = false;
      });

      try { Object.assign(info, await window.moss.call("info", {})); } catch (e) {  }
      await fetchState();
      await openBackups();          

      const sc = await call("scan", { paths: paths.value }, true);
      if (sc && sc.missing) missing.value = sc.missing;
    });

    return { paths, saved, missing, selfDir, dataDir, backupDir, info, input, inputWarn, busy,
             drawer, openDrawer, closeDrawer,
             sysSaved, sysDraft, sysMissing, sysCount, isSysMissing, keyOf,
             sysDirty, sysPendingN, sysEditing, sysEditVal, sysInput, sysDragFrom, sysDragOver,
             shortSysBak, sysAdd, sysRemove, sysBeginEdit, sysCommitEdit, sysRevert, sysSave,
             sysDragStart, sysDragOverAt, sysDropAt, sysDragEnd,
             dragOn, backups, hovered, pinned, toasts, pathCount, pendingN, dirty, missingN,
             hasDup, hasMissing, anyAction, diffsOf, showAllOf, isOpen, hoverOn, hoverOff, togglePin,
             shortData, ic,
             naming, bkName, renaming, renameVal, leaving, dragArmed, dragFrom, dragOver,
             load, save, revert, add, remove, dedup, dropMissing, clearInput, copyPath, editPath,
             dragStart, dragOverRow, dropAt, dragEnd,
             startBackup, doBackup, startRename, doRename, openBackups, toggleAll,
             restore, delBackup, isMissing, isFresh, same, note };
  },
}).mount("#app");
