"use strict";

import { createApp } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { iconFor } from "./icons.js";
import Toasts from "./components/Toasts.js";
import HoverTip from "./components/HoverTip.js";
import NewSheet from "./components/NewSheet.js";
import CodeEditor from "./components/CodeEditor.js";
import SideTree from "./components/SideTree.js";
import DetailPane from "./components/DetailPane.js";

window.__execApp = createApp({
  components: { Toasts, HoverTip, NewSheet, CodeEditor, SideTree, DetailPane },

  data() {
    return {
      commands: [], types: {}, picker: [], newTypes: {},
      afterActions: [], placeholders: [], dataDir: "",
      selectedKey: null, originalAlias: null, query: "", expanded: {},
      dirty: false, confirming: false, lastArgs: "", toasts: [], toastSeq: 0,
      sheetOpen: false, hover: null, htmlView: "code",
      run: { output: null, running: false, id: null, returncode: null },
      panelReady: false, tab: "view", frameUrl: "", saving: false,
    };
  },

  computed: {
    groups() {
      const q = this.query.trim().toLowerCase();
      const out = [];
      for (const g of this.picker) {
        let items = this.commands.filter(c => g.types.includes(c.type));
        if (q) items = items.filter(c => this.matches(c, q));
        if (q && !items.length) continue;
        out.push({ id: g.id, label: g.label, icon: g.icon, items });
      }
      return out;
    },

    filtered() {
      return this.groups.reduce((acc, g) => acc.concat(g.items), []);
    },

    current() {
      return this.commands.find(c => c._key === this.selectedKey) || null;
    },
    spec() {
      return (this.current && this.types[this.current.type]) || this.types.python || {};
    },
    isHtml() {
      return !!this.current && this.current.type === "html";
    },
    // 网址命令就能在右边看：能贴真窗口就贴（任何站点都行），
    // 贴不了（界面被内嵌进 moss 时没有自己的窗口）就用 iframe
    canBrowse() {
      const c = this.current;
      return !!(c && !c._new && c.type === "url"
                && (c.open_in || "panel") === "panel");
    },
    browsing() {
      return this.canBrowse && this.tab === "view";
    },
    aliasBad() {
      const a = this.current && this.current.alias;
      return !!a && !/^[a-z0-9_-]{1,64}$/.test(a);
    },
    wantsArgs() {
      return this.spec.kind === "proc" || this.current && this.current.type === "url";
    },
    placeholderHint() {
      return "可用占位符：" + this.placeholders.map(p => p.token).join("　");
    },

    codeText: {
      get() {
        const c = this.current;
        return c ? (c.codes[c.type] || "") : "";
      },
      set(v) {
        const c = this.current;
        if (!c) return;
        c.codes[c.type] = v;
      },
    },
  },

  watch: {
    selectedKey() { this.dirty = false; this.confirming = false; this.tab = "view"; },
    query() { this.ensureVisible(); },
    browsing() { this.$nextTick(() => this.syncPanel()); },
    "current.open_in"() { this.$nextTick(() => this.syncPanel()); },
  },

  methods: {
    iconFor,

    stamp(list) {
      let n = 0;
      for (const c of (list || [])) if (!c._key) c._key = c.alias || ("__new__" + (++n));
      return list || [];
    },
    toast(text, bad) {
      const id = ++this.toastSeq;
      this.toasts.push({ id, text, bad: !!bad });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 1800);
    },
    matches(c, q) {
      return c.alias.toLowerCase().includes(q)
        || (c.description || "").toLowerCase().includes(q)
        || Object.values(c.codes || {}).some(v => String(v || "").toLowerCase().includes(q));
    },

    isOpen(g) {
      if (this.query.trim()) return true;
      return this.expanded[g.id] !== false;
    },
    toggle(id) {
      this.expanded = Object.assign({}, this.expanded, { [id]: this.expanded[id] === false });
    },
    expandAll(open) {
      const next = {};
      for (const g of this.picker) next[g.id] = open;
      this.expanded = next;
    },
    ensureVisible() {
      if (this.current && this.filtered.some(c => c._key === this.selectedKey)) return;
      if (this.filtered.length) this.select(this.filtered[0]._key);
      else { this.selectedKey = null; this.originalAlias = null; }
    },
    select(key) {
      this.selectedKey = key;
      const c = this.commands.find(x => x._key === key);
      this.originalAlias = c ? c.alias : null;

      this.htmlView = (c && c.type === "html" && (c.codes.html || "").trim()) ? "preview" : "code";
      this.run = { output: null, running: false, id: null, returncode: null };
      this.lastArgs = "";
    },
    openFirst() {
      if (this.filtered.length) this.select(this.filtered[0]._key);
    },
    async pickInto(target) {
      const kind = target === "dir" ? "dir" : "file";
      const r = await api.sys.pickPath(kind);
      if (!r || !r.ok) { if (r && r.message) this.toast(r.message, true); return; }
      if (!r.path) return;
      if (target === "cwd") this.current.cwd = r.path;
      else this.codeText = r.path;
      this.dirty = true;
    },
    setOpenIn(id) {
      if (!this.current) return;
      this.current.open_in = id;
      this.dirty = true;
    },
    setTab(id) {
      this.tab = id === "edit" ? "edit" : "view";
    },

    /* 右侧浏览：能贴真窗口就贴（任何站点都能显示），贴不了就用 iframe */
    async syncPanel(force) {
      if (!this.browsing || !this.current) {
        this.frameUrl = "";
        await api.panel.hide();
        return;
      }
      const r = await api.panel.url({
        alias: this.current.alias,
        args: this.lastArgs || "",
      });
      const url = (r && r.url) || "";
      if (!url) { this.frameUrl = ""; return; }
      if (!this.panelReady) { this.frameUrl = url; return; }

      const host = document.querySelector(".view-host");
      if (!host || !host.offsetWidth) { this.frameUrl = url; return; }
      const b = host.getBoundingClientRect();
      const res = await api.panel.show({
        alias: this.current.alias,
        args: this.lastArgs || "",
        open_in: this.current.open_in || "panel",
        force: !!force,
        rect: { x: b.left, y: b.top, w: b.width, h: b.height },
        dpr: window.devicePixelRatio || 1,
      });
      if (!res || !res.ok) {
        // 这台机器上贴不上窗口（比如界面被内嵌了），退回 iframe
        this.panelReady = false;
        this.frameUrl = url;
        return;
      }
      this.frameUrl = "";
      // 窗口是后台建的：等一会儿还没出来就退回 iframe，别让右边一直空着
      this.$nextTick(() => {
        setTimeout(async () => {
          if (!this.browsing) return;
          try {
            const st = await api.panel.state();
            if (st && st.ok && !st.ready) {
              this.panelReady = false;
              this.frameUrl = url;
            }
          } catch (e) { /* 查不到就算了，下回再试 */ }
        }, 3000);
      });
    },
    refreshPanel() {
      this.syncPanel(true);
    },

    newCommand(typeId) {
      this.sheetOpen = false;
      this.query = "";
      const g = this.picker.find(x => x.types.includes(typeId));
      if (g) this.expanded = Object.assign({}, this.expanded, { [g.id]: true });

      const pending = this.commands.find(c => c._new);
      if (pending) {
        pending.type = typeId;
        pending.codes = {};
        this.select(pending._key);
        this.focusAlias();
        return;
      }
      const c = {
        _key: "__new__", alias: "", type: typeId, description: "", codes: {},
        cwd: "", env: "", elevated: false, after: "none", open_in: "panel", _new: true,
      };
      this.commands.push(c);
      this.select(c._key);
      this.focusAlias();
    },
    focusAlias() {
      this.$nextTick(() => { const el = this.$refs.aliasInput; if (el) el.focus(); });
    },
    async save() {
      const c = this.current;
      if (!c) { this.toast("没有选中命令", true); return false; }
      if (this.saving) return false;
      this.saving = true;
      try {
        let res;
        try {
          res = await api.cmd.save({
            alias: c.alias, type: c.type, description: c.description,
            codes: c.codes || {}, cwd: c.cwd || "", env: c.env || "",
            elevated: !!c.elevated, after: c.after || "none",
            open_in: c.open_in || "browser",
          }, c._new ? null : this.originalAlias);
        } catch (e) {
          this.toast("保存失败：" + this.reason(e), true);
          return false;
        }
        if (!res || !res.ok) {
          this.toast((res && res.message) || "保存失败：后端没有返回结果", true);
          return false;
        }
        try {
          const list = await api.cmd.list();
          this.commands = this.stamp((list && list.commands) || []);
        } catch (e) {
          this.toast("已写入，但列表没刷新：" + this.reason(e), true);
          return true;
        }
        const saved = this.commands.find(x => x.alias === res.alias);
        this.select(saved ? saved._key : null);
        this.toast("已保存");
        return true;
      } finally {
        this.saving = false;
      }
    },

    /* 把任何异常变成一句话，别让失败静默 */
    reason(e) {
      if (!e) return "未知错误";
      if (typeof e === "string") return e;
      return e.message || e.error || JSON.stringify(e);
    },
    async doDelete() {
      const c = this.current;
      if (!c) return;
      const res = await api.cmd.remove(this.originalAlias || c.alias);
      if (!res.ok) { this.toast(res.message, true); return; }
      const list = await api.cmd.list();
      this.commands = this.stamp(list.commands || []);
      this.selectedKey = null;
      this.originalAlias = null;
      this.confirming = false;
      this.ensureVisible();
      this.toast("已删除");
    },

    async runCommand() {
      const c = this.current;
      if (!c) return;
      if (c._new) { this.toast("请先保存再运行", true); return; }
      // 正在右侧浏览时，「运行」就是按当前参数重新加载这一页
      if (this.browsing) {
        if (this.dirty && !(await this.save())) return;
        this.syncPanel(true);
        return;
      }
      // 改了设置（比如换「打开方式」）直接按运行，先落盘再跑，免得跑的是旧设置
      if (this.dirty && !(await this.save())) return;
      this.run = { output: "", running: true, id: null, returncode: null };
      const res = await api.run.start(c.alias, this.lastArgs || "");
      if (!res.ok) { this.toast(res.message, true); this.run.output = null; return; }
      this.run.id = res.id;
      this.poll();
    },
    async saveThenRun() {
      if (await this.save()) this.runCommand();
    },
    async poll() {
      const id = this.run.id;
      if (!id) return;
      const st = await api.run.poll(id);
      this.run.output = st.output || "";
      this.run.running = !!st.running;
      this.run.returncode = st.returncode;
      if (st.running) setTimeout(() => this.poll(), 160);
      else {
        const code = st.returncode;
        if (code === 0 || code === null || code === undefined) this.toast("执行完成");
        else this.toast("退出码 " + code, true);
      }
    },
    async stopRun() {
      if (this.run.id) await api.run.stop(this.run.id);
    },
    closeRun() { this.run = { output: null, running: false, id: null, returncode: null }; },
    async openConsole() {
      const c = this.current;
      if (!c || c._new) { this.toast("请先保存再运行", true); return; }
      const res = await api.run.console(c.alias, this.lastArgs || "");
      if (!res.ok) this.toast(res.message, true); else this.toast("已在新控制台窗口运行");
    },
    async reveal() {
      const r = await api.sys.reveal();
      if (r && !r.ok && r.message) this.toast(r.message, true);
    },

    applyAppearance(r) {
      if (r.theme) document.documentElement.dataset.theme = r.theme;
      const a = r.accent || {};
      for (const k of ["accent", "accent-fg", "accent-press", "ring", "field-focus"]) {
        if (a[k]) document.documentElement.style.setProperty("--" + k, a[k]);
      }
    },
  },

  async mounted() {
    const r = await api.bootstrap();
    this.applyAppearance(r);
    this.commands = this.stamp(r.commands || []);
    this.types = r.types || {};
    this.picker = r.picker || [];
    this.newTypes = r.newTypes || [];
    this.afterActions = r.afterActions || [];
    this.placeholders = r.placeholders || [];
    this.dataDir = r.dataDir || "";
    this.panelReady = !!r.panel;
    if (this.commands.length) this.select(this.commands[0]._key);
    this.$nextTick(() => this.syncPanel());

    let resizeTimer = 0;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => this.syncPanel(), 120);
    });

    // 任何没接住的异常都要冒出来，不能表现成「点了没反应」
    window.addEventListener("unhandledrejection", (e) => {
      const r = e && e.reason;
      console.error("[unhandled]", r);
      this.toast("出错了：" + this.reason(r), true);
    });
    window.addEventListener("error", (e) => {
      if (e && e.message) { console.error("[error]", e.message); }
    });

    document.addEventListener("keydown", (e) => {
      const mod = e.ctrlKey || e.metaKey;
      const k = (e.key || "").toLowerCase();
      if (mod && k === "n") { e.preventDefault(); this.sheetOpen = true; }
      else if (mod && k === "s") { e.preventDefault(); this.save(); }
      else if (mod && k === "f") { e.preventDefault(); this.$refs.search.focus(); this.$refs.search.select(); }
      else if (mod && e.key === "Enter") { e.preventDefault(); this.saveThenRun(); }
      else if (e.key === "Escape") {
        if (this.sheetOpen) this.sheetOpen = false;
        else if (this.confirming) this.confirming = false;
        else if (this.query) this.query = "";
      }
    });
  },
}).mount("#app");
