/* 快捷执行 —— 前端入口
 *
 * 用原生 ES Module，不做打包：pywebview 走本地 HTTP，浏览器直接吃 import。
 * 改完文件重启 pa 就生效，不需要 node / npm / 构建步骤。
 */
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

/* 挂到 window 上便于调试与自动化验收 */
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
    };
  },

  computed: {
    /* 分类 + 命令的一棵树：搜索时只留有命中的分类 */
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
    /* 当前可见的命令（扁平），供空状态和"回车打开第一条"用 */
    filtered() {
      return this.groups.reduce((acc, g) => acc.concat(g.items), []);
    },
    /* 选中项按稳定的 _key 找，绝不能按别名 —— 别名是可编辑字段，
       一旦按它查找，用户改别名的瞬间 current 就变 null，整张卡片会消失。 */
    current() {
      return this.commands.find(c => c._key === this.selectedKey) || null;
    },
    spec() {
      return (this.current && this.types[this.current.type]) || this.types.python || {};
    },
    isHtml() {
      return !!this.current && this.current.type === "html";
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
    /* 内容跟着执行方式走：每种类型读自己的格子 */
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
    selectedKey() { this.dirty = false; this.confirming = false; },
    query() { this.ensureVisible(); },
  },

  methods: {
    /* 图标是纯函数，从 icons.js 引进来给模板用 */
    iconFor,

    /* ------------------------------------------------ 基础 */
    stamp(list) {
      /* 给每条命令挂一个加载时的稳定 key（存盘不写这个字段） */
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
    /* 展开态：默认全展开；搜索时强制全开（否则命中的结果看不见） */
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
      /* 筛选/搜索把当前选中项滤掉时，自动选第一条 —— 避免列表里没有它、右侧却还显示它 */
      if (this.current && this.filtered.some(c => c._key === this.selectedKey)) return;
      if (this.filtered.length) this.select(this.filtered[0]._key);
      else { this.selectedKey = null; this.originalAlias = null; }
    },
    select(key) {
      this.selectedKey = key;
      const c = this.commands.find(x => x._key === key);
      this.originalAlias = c ? c.alias : null;
      /* HTML 已经有内容就直接给预览（预览本来就是它的重点），空的新命令给源码 */
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

    /* ------------------------------------------------ 增删改 */
    /* 新建：类型在 sheet 里选好，之后不再允许切换 */
    newCommand(typeId) {
      this.sheetOpen = false;
      this.query = "";
      const g = this.picker.find(x => x.types.includes(typeId));
      if (g) this.expanded = Object.assign({}, this.expanded, { [g.id]: true });
      /* 已经有未保存的新命令就直接改它的类型，别堆两条空壳 */
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
        cwd: "", env: "", elevated: false, after: "none", _new: true,
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
      if (!c) return false;
      const res = await api.cmd.save({
        alias: c.alias, type: c.type, description: c.description,
        codes: c.codes || {}, cwd: c.cwd || "", env: c.env || "",
        elevated: !!c.elevated, after: c.after || "none",
      }, c._new ? null : this.originalAlias);
      if (!res.ok) { this.toast(res.message, true); return false; }
      const list = await api.cmd.list();
      this.commands = this.stamp(list.commands || []);
      const saved = this.commands.find(c => c.alias === res.alias);
      this.select(saved ? saved._key : null);      // 同时把 originalAlias 更新成新别名
      this.toast("已保存");
      return true;
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

    /* ------------------------------------------------ 运行 */
    async runCommand() {
      const c = this.current;
      if (!c) return;
      if (c._new) { this.toast("请先保存再运行", true); return; }
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

    /* ------------------------------------------------ 外观 */
    applyAppearance(r) {
      if (r.theme) document.documentElement.dataset.theme = r.theme;
      const a = r.accent || {};
      for (const k of ["accent", "accent-fg", "accent-press", "ring", "field-focus"]) {
        if (a[k]) document.documentElement.style.setProperty("--" + k, a[k]);
      }
    },
  },

  async mounted() {
    /* 等桥就绪的逻辑已收进 api.js */
    const r = await api.bootstrap();
    this.applyAppearance(r);
    this.commands = this.stamp(r.commands || []);
    this.types = r.types || {};
    this.picker = r.picker || [];
    this.newTypes = r.newTypes || [];
    this.afterActions = r.afterActions || [];
    this.placeholders = r.placeholders || [];
    this.dataDir = r.dataDir || "";
    if (this.commands.length) this.select(this.commands[0]._key);

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
