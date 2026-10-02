/* PATH 管理 —— 界面（Vue 3，`V-201`）。
   ★ 这里**不做业务**：改注册表、读写备份、"会加什么/会去掉什么"全在 `main.py`。
     这一层只干两件事：把动作交给后端（`moss.call`），把结果画出来。
   ★ 拖文件夹进来（`V-201`）：
     · 独立窗口：宿主（pywebview）把真实路径送进来，垫片转成 `moss.on("drop")`；
     · 内嵌在 moss 里：moss 主界面把拖进来的路径转发给这一帧（同样是 `drop` 事件）。
     两条路的形状一样，所以下面只写一处。 */
const { createApp, ref, reactive, onMounted } = Vue;

createApp({
  setup() {
    const paths = ref([]);
    const missing = ref([]);
    const selfDir = ref("");
    const dataDir = ref("");
    const backupDir = ref("");
    const info = reactive({ pid: 0, python: "" });
    const input = ref("");
    const busy = ref(false);
    const msg = ref("");
    const msgBad = ref(false);
    const dragOn = ref(false);
    const backups = ref([]);
    const sel = ref(null);
    const preview = reactive({ add: [], remove: [] });
    const pathCount = ref(0);

    const readyHint = "只改当前用户的 PATH（HKCU\\Environment）—— 已经开着的终端不会变，新开的才看得到";
    const ic = (n) => icon(n, "i");

    function say(m, bad) { msg.value = m || ""; msgBad.value = !!bad; }
    function applyState(s) {
      if (!s) return;
      paths.value = s.paths || [];
      pathCount.value = s.count || 0;
      missing.value = s.missing || [];
      selfDir.value = s.self_dir || "";
      dataDir.value = s.data_dir || "";
      backupDir.value = s.backup_dir || "";
    }
    async function call(method, params) {
      busy.value = true;
      try {
        return await window.moss.call(method, params || {});
      } catch (e) {
        say("调后端失败：" + (e && e.message ? e.message : e), true);
        return null;
      } finally {
        busy.value = false;
      }
    }

    // ---- PATH
    async function load() {
      const r = await call("state");
      if (r) { applyState(r); say(""); }
    }
    async function add() {
      const p = input.value.trim();
      if (!p) return;
      const r = await call("add", { path: p });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      if (r.ok) input.value = "";
    }
    async function remove(p) {
      const r = await call("remove", { path: p });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
    }
    async function dedup() {
      const r = await call("dedup");
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
    }
    async function dropMissing() {
      const r = await call("drop_missing");
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
    }
    async function pick() {
      let dir = "";
      // 内嵌时先问 moss 主界面要（那扇窗有正规的文件夹对话框；同源 iframe 直接可用）
      try {
        const top = window.parent && window.parent !== window ? window.parent : null;
        if (top && top.pywebview && top.pywebview.api && top.pywebview.api.pick_dir) {
          const r = await top.pywebview.api.pick_dir("");
          if (r && r.ok && r.path) dir = r.path;
          else if (r && r.msg) say(r.msg, true);
        }
      } catch (e) { /* 问不到就走后端那条 */ }
      if (!dir) {
        const r = await call("pick_dir", { start: paths.value[0] || "" });
        if (r && r.ok) dir = r.path;
        else if (r && r.msg) { say(r.msg, true); return; }
      }
      if (dir) { input.value = dir; say("选好了，点「添加」"); }
    }

    // ---- 拖进来的目录（`V-201`）
    async function onDrop(items) {
      dragOn.value = false;
      const list = (items || []).map((it) => String(it || "")).filter(Boolean);
      if (!list.length) return;
      const r = await call("add_many", { paths: list });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
    }

    // ---- 备份
    async function makeBackup() {
      const r = await call("backup_create");
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      await openBackups();
    }
    async function openBackups() {
      const r = await call("backup_list");
      if (!r) return;
      backups.value = r.items || [];
      applyState(r.state);
      if (sel.value && !backups.value.some((b) => b.file === sel.value.file)) sel.value = null;
      if (!backups.value.length) say("还没有备份 —— 点右上角「备份一份」");
    }
    async function choose(b) {
      if (sel.value && sel.value.file === b.file) { sel.value = null; preview.add = []; preview.remove = []; return; }
      sel.value = b;
      const r = await call("backup_preview", { file: b.file });
      if (!r) return;
      preview.add = r.add || [];
      preview.remove = r.remove || [];
      say(r.msg, !r.ok);
    }
    async function restore(b) {
      const r = await call("backup_restore", { file: (b || sel.value || {}).file || "" });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      sel.value = null; preview.add = []; preview.remove = [];
      await openBackups();
    }
    async function delBackup(b) {
      const r = await call("backup_delete", { file: b.file });
      if (!r) return;
      applyState(r.state);
      say(r.msg, !r.ok);
      if (sel.value && sel.value.file === b.file) sel.value = null;
      await openBackups();
    }

    const isMissing = (p) => missing.value.some((m) => m.toLowerCase() === String(p).toLowerCase());
    const same = (a, b) => !!a && !!b && String(a).toLowerCase() === String(b).toLowerCase();
    const shortData = Vue.computed(() => {
      const d = dataDir.value || "";
      const parts = d.replace(/\\/g, "/").split("/").filter(Boolean);
      return parts.length <= 3 ? d : "…/" + parts.slice(-3).join("/");
    });

    onMounted(async () => {
      // 后端 / 宿主送来的事件
      window.moss.on("drop", (d) => onDrop((d && d.items) || []));
      window.moss.on("invoke", () => load());
      window.moss.on("visible", (d) => { if (d && d.visible) load(); });
      // 页面自己也接一次 HTML5 拖放：① 独立窗口里给个"正在拖"的反馈；
      // ② 真实路径那条（moss 宿主 / pywebview）没来的时候不至于一点反应都没有。
      let depth = 0;
      let captured = false;      // 宿主铺了罩子接住（`V-205`）：这期间别自己把提示收掉
      // 罩子把拖放接到 moss 主界面那侧之后，这一帧就收不到 dragleave/drop 了 ——
      // 宿主拖完会补一条 `dragend`（`V-204`），提示框靠它收。
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
      await load();
      await openBackups();          // 右边那一栏一进来就有东西看
    });

    return { paths, missing, selfDir, dataDir, backupDir, info, input, busy, msg, msgBad, dragOn,
             backups, sel, preview, pathCount, readyHint, shortData, ic,
             load, add, remove, dedup, dropMissing, pick, makeBackup, openBackups, choose,
             restore, delBackup, isMissing, same };
  },
}).mount("#app");
