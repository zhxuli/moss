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
    /* 机器级（系统）PATH —— `V-388` 起看得见、`V-389` 起改得动。
       ★ 它和上面那份**不是一份东西**：`sysSaved` 是注册表里现在那一份，`sysDraft` 是这儿的草稿，
         保存要走一次 UAC（管理员）——所以**草稿、脏没脏、保存按钮全都各算各的**，
         绝不会因为上面点了「保存修改」就顺手把机器级也写了。 */
    const sysSaved = ref([]);
    const sysDraft = ref([]);
    const sysMissing = ref([]);
    const sysBackupDir = ref("");
    const sysEditing = ref(-1);       // 正在就地改第几条（双击行）
    const sysEditVal = ref("");
    const sysInput = ref("");         // 「加一条到系统级」那个框
    const sysDragFrom = ref(null);    // 系统块里的拖动排序
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
    const hovered = ref("");          // 鼠标停在哪个备份上（`V-214`：一 hover 就自动对比）
    const pinned = ref("");           // 被"固定住"的那份（点了「对比」就不随鼠标收起来）
    const showAllMap = reactive({});  // 每张卡片各自的"显示全部 / 仅看差异"
    const toasts = ref([]);           // 底部那串提示
    /* 备份抽屉：备份是低频操作，常驻一栏的代价是"平时一直是块空地"。
       所以收进抽屉，按需拉出来（顶栏那颗带份数）。 */
    const drawer = ref(false);
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
      /* 最多留 2 条（`V-391`）：连点几下时原来会堆三条黑块把列表糊住。
         而且**同类替换**：新的 info 进来就把上一条 info 顶掉 —— 那只是"我刚做了一步"，
         不需要历史；错误则单独留一条。 */
      // 新的同类顶掉旧的；而且**结果一出来，先前那句"等一下…"就该消失**
      //（它只是过程提示，不该跟结果并排挂着）
      const keep = toasts.value.filter((t) => t.type !== kind &&
                                             (kind === "info" || t.type !== "info"));
      toasts.value = keep.concat([item]).slice(-2);
      item.t = setTimeout(() => { toasts.value = toasts.value.filter((t) => t.id !== item.id); },
                          kind === "error" ? 4200 : 2500);
    }
    const say = (m, bad) => toast(m, bad ? "error" : "success");
    /* ★ 两档反馈，别混（`V-391`）：`say` = **真的落盘了**（绿勾）或出错了（红）；
       `note` = 只是改了草稿 / 顺序（中性，无勾无红）。原来"加进草稿了"也顶个绿勾，
       一屏里绿勾闪三次，等于什么都没说。 */
    const note = (m) => toast(m, "info");

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
    // ---- 系统级那一段的"脏没脏 / 差几处"（和用户级同一套算法，只是各算各的）
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
      sysSaved.value = s.sys_paths || [];
      // 系统级那份草稿也"有改动就别覆盖"（force=保存成功 / 首次载入时才换）
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
    /* 把（可能带着 Vue Proxy 的）参数拍平成纯数据：JSON 一个来回就够。
       ★ 别用 `structuredClone` / 展开运算符代替：展开只拆第一层，数组元素还是代理；
         `structuredClone` 对 Proxy 一样会抛。 */
    function plain(v) {
      if (v === undefined || v === null) return {};
      try { return JSON.parse(JSON.stringify(v)); } catch (e) { return {}; }
    }

    async function call(method, params, quiet) {
      if (!quiet) busy.value = true;
      try {
        /* ★ 参数必须是**纯数据**（`V-390`）：Vue 的 `ref([...])` 拿出来的是 Proxy，
           内嵌模式过 postMessage（结构化克隆）会被当场拒掉 ——
           「Failed to execute 'postMessage': [object Object] could not be cloned」，
           界面上看着就是"点保存没反应 / 提示调后端失败"。所以在这儿统一拆一层：
           JSON 一个来回，Proxy 变普通对象/数组，顺带挡住函数之类根本传不过去的东西。 */
        return await window.moss.call(method, plain(params));
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
      return { ok: true, msg: "加进列表了（还没保存）" };   // 路径就在行上，别在提示里再念一遍
    }
    function remove(p) {
      if (leaving.value) return;
      leaving.value = p;                                  // 先播"消失"动画
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
      applyState(r.state, r.ok);       // 写成功了才用后端那份覆盖草稿（高亮随之全灭）
      armed.value = false;
      say(r.msg, !r.ok);
    }

    // ---- 系统级（机器级）那一段：加 / 删 / 双击改 / 拖动排序，全在草稿上（`V-389`）
    /* ★ 和上面那套一模一样地"先改后存"，唯一的区别在**保存**：要走一次 UAC。
         所以这里给它一套自己的按钮，绝不和上面那颗「保存修改」混在一起 ——
         一次点击只改一级，不会"我只想改用户级，结果系统级也被写了"。 */
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
      catch (err) { /* 无所谓 */ }
    }
    function sysDragOverAt(i, e) {
      if (sysDragFrom.value === null) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = "move"; } catch (err) { /* 无所谓 */ }
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
    /* 草稿一变，就问一次"这些目录还在不在"（`V-389` / `V-391`）。
       ★ 为什么必须有：行上的「不存在」红标原来只来自 `state` —— 那是**注册表里**那一份。
         刚加进草稿的、刚双击改完的还没进注册表，红标就跟不上，于是"加了一条根本不存在的
         目录，界面看着一点事都没有"。
       ★ 两条清单一起问（一次往返），并且**共用一个防抖**：分开写会让每次改动都发两次
         `scan`，白跑。`deep` 不能省 —— `push / splice` 改的是数组内部，不是 `.value` 本身。 */
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
      applyState(r.state, false);      // 系统级存成了就跟着换；**别动**上面那份用户级草稿
      // 在 UAC 上点「取消」= "这次不改"，不是失败 —— 不报红
      if (!r.ok && /取消/.test(r.msg || "")) return toast(r.msg, "info");
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
      note("填到上面了：改完点「添加」放回去");
      Vue.nextTick(() => { const el = document.getElementById("path-input"); if (el) { el.focus(); el.select(); } });
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
        note("顺序变了（还没保存）");
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
        return note("有 " + pendingN.value + " 处改动没保存 — 再点一下「刷新」就丢掉它们");
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
      if (a.ok && r.kind === "file") note("加进列表了（拖的是文件，取的是它所在的目录；还没保存）");
      else if (a.ok) note(a.msg);
      else note(a.msg);
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
      if (added) bits.push("加进列表 " + added + " 条（还没保存）");
      if (dup) bits.push("跳过 " + dup + " 条重复");
      if (bad) bits.push("跳过 " + bad + " 条目录不存在");
      if (added) note(bits.join("；"));
      else toast(bits.join("；") || "没拿到可用的目录", "error");
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
    /* 抽屉：开的时候顺手刷一遍清单（份数就在顶栏那颗上，进页面时也要有数）。 */
    async function openDrawer() {
      drawer.value = true;
      await openBackups();
    }
    function closeDrawer() { drawer.value = false; }

    async function openBackups() {
      const r = await call("backup_list", {}, true);   // 只刷清单，别让整页按钮闪一下
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

      /* Esc：先收起抽屉，再收掉正在改的那一行 / 起名框 —— 一次退一层。 */
      window.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (drawer.value) { closeDrawer(); return; }
        if (sysEditing.value >= 0) { sysEditing.value = -1; return; }
        if (naming.value) naming.value = false;
      });

      try { Object.assign(info, await window.moss.call("info", {})); } catch (e) { /* 无妨 */ }
      await fetchState();
      await openBackups();          // 顶栏那颗按钮上的份数要一进来就是真的
      // 首屏扫一遍：草稿里（可能带 %VAR%）哪些目录已经不在盘上了
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
