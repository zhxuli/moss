/* ===========================================================================
   应用外壳：偏好、插件解析、头部工具栏、快捷键、挂载
   =========================================================================== */
(function () {
  var Vue = window.Vue, FV = window.FV, U = FV.util, icon = FV.icon;
  if (!Vue) return; // Vue 没加载成功时整段跳过，由页面末尾给出提示
  var ref = Vue.ref, computed = Vue.computed, watch = Vue.watch, onMounted = Vue.onMounted, nextTick = Vue.nextTick;

  /* ---------------------------------------------------------------- 偏好 */
  FV.prefs = (function () {
    var ls = window.localStorage;
    function get(key, fallback) { try { var value = ls.getItem(key); return value === null ? fallback : value; } catch (e) { return fallback; } }
    function set(key, value) { try { ls.setItem(key, value); } catch (e) {} }
    return {
      theme: function () { return get("fv-theme", "auto"); },
      setTheme: function (value) { set("fv-theme", value); },
      wrap: function (ctx) {
        var value = get("fv-wrap", null);
        if (value === "on") return true;
        if (value === "off") return false;
        return !FV.langs.isCode(ctx.ext);
      },
      setWrap: function (ctx, on) { set("fv-wrap", on ? "on" : "off"); },
      size: function (ctx) {
        var value = parseInt(get("fv-size", "0"), 10);
        return value > 0 ? value : (FV.langs.isCode(ctx.ext) ? 12 : 13);
      },
      setSize: function (ctx, px) { set("fv-size", String(px)); },
      view: function (ext) { return get("fv-view-" + ext, null); },
      setView: function (ext, id) { set("fv-view-" + ext, id); }
    };
  })();

  /* ---------------------------------------------------------------- 应用 */
  var App = {
    components: { LoadingPanel: FV.ui.LoadingPanel, StateCard: FV.ui.StateCard },
    setup: function () {
      var boot = FV.boot;
      var ctx = Vue.reactive({
        name: boot.name, ext: boot.ext, sizeText: boot.sizeText, bytes: boot.bytes,
        rawUrl: boot.rawUrl, dataUri: boot.dataUri, text: boot.text, tooLarge: boot.tooLarge, notice: boot.notice
      });
      var api = Vue.reactive({
        zoomLabel: null, zoomState: null, canZoomIn: false, canZoomOut: false,
        wrapOn: null, findOpen: null, canFontUp: true, canFontDown: true,
        extra: "", zoomIn: null, zoomOut: null, toggleFit: null, rotate: null,
        toggleWrap: null, toggleFind: null, copyText: null, fontUp: null, fontDown: null,
        findNext: null, findPrev: null, closeFind: null, expandAll: null, collapseAll: null
      });
      Vue.provide("fv-api", api);

      var toastText = ref(""), toastTimer = 0;
      function toast(text) {
        toastText.value = text;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { toastText.value = ""; }, 1600);
      }


      /**
       * 插件记录刻意留在**普通数组**里：放进 reactive 会把组件定义也包成 Proxy，
       * Vue 拿到被代理的组件对象就渲染不出东西（只剩一个注释占位）。
       * 模板只需要 id/label，所以另存一份轻量副本。
       */
      var registryList = FV.registry.resolve(ctx);
      var plugins = ref(registryList.map(function (p) { return { id: p.id, label: p.label, kind: p.kind, needs: p.needs }; }));
      var activeId = ref(null);
      var loading = ref(false);
      var loadError = ref("");
      var loadState = ref(null);   // { loaded, total, progress, speed, eta } —— 大文件读取进度
      var loadJob = null;
      var loadPct = computed(function () {
        var state = loadState.value;
        return state && state.total ? Math.round(Math.min(1, state.loaded / state.total) * 100) : 0;
      });
      var loadIndeterminate = computed(function () { var state = loadState.value; return !state || !state.total; });
      var loadStats = computed(function () {
        var state = loadState.value;
        if (!state) return "";
        var parts = [];
        if (state.total) parts.push(U.humanBytes(state.loaded) + " / " + U.humanBytes(state.total));
        else if (state.loaded) parts.push("已读取 " + U.humanBytes(state.loaded));
        if (state.speed) parts.push(U.humanRate(state.speed));
        if (state.eta !== null && state.eta !== undefined) parts.push("剩余 " + U.humanEta(state.eta));
        return parts.join(" · ");
      });
      var stageRev = ref(0); // 挂载后再渲染一次：首帧的 v-if 链只读了 loading，active 要等下一帧才被读到

      function pickDefault() {
        var remembered = FV.prefs.view(ctx.ext);
        var found = null;
        for (var i = 0; i < registryList.length; i += 1) if (registryList[i].id === remembered) found = registryList[i];
        activeId.value = (found || registryList[0] || { id: "download" }).id;
      }
      pickDefault();

      var active = computed(function () {
        var id = activeId.value;
        for (var i = 0; i < registryList.length; i += 1) if (registryList[i].id === id) return registryList[i];
        return registryList[0] || null;
      });
      var activeView = computed(function () {
        var plugin = active.value;
        return plugin && plugin.view ? plugin.view : null;
      });
      var activeControls = computed(function () {
        var plugin = active.value;
        return plugin && plugin.controls ? plugin.controls : null;
      });
      var alternatives = computed(function () {
        return plugins.value.filter(function (p) { return p.id !== activeId.value && p.id !== "download"; });
      });

      /** 换视图时先把上一个视图注册进 api 的东西清掉，避免工具栏调到已经卸载的组件。 */
      function clearApi() {
        ["zoomIn","zoomOut","toggleFit","rotate","toggleWrap","toggleFind","copyText","fontUp","fontDown",
         "findNext","findPrev","closeFind","expandAll","collapseAll"].forEach(function (key) { api[key] = null; });
        api.zoomLabel = null; api.zoomState = null; api.wrapOn = null; api.findOpen = null;
        api.findAvailable = null; api.canFontUp = true; api.canFontDown = true; api.extra = "";
      }

      function loadText() {
        if (ctx.text !== null || loading.value) return;
        loading.value = true; loadError.value = "";
        loadState.value = { loaded: 0, total: boot.bytes || 0, progress: 0, speed: 0, eta: null };
        var job = FV.loadStream(boot.rawUrl, {
          kind: "text",
          total: boot.bytes || 0,
          onProgress: function (state) { loadState.value = Object.assign({}, state); }
        });
        loadJob = job;
        job.promise.then(function (value) {
          loadJob = null; ctx.text = value; loading.value = false; loadState.value = null;
        }, function (error) {
          loadJob = null; loading.value = false; loadState.value = null;
          if (error && (error.name === "AbortError" || String(error.message || "").indexOf("abort") >= 0)) { toast("已取消读取"); return; }
          loadError.value = error && error.message ? error.message : String(error);
        });
      }
      /** 大文件读失败时给一句能照做的解释：这条通道对单次响应有大小上限。 */
      var loadErrorHint = computed(function () {
        if (!loadError.value) return "";
        if ((ctx.bytes || 0) > 12 * 1024 * 1024 && /fetch|network|Failed|HTTP 5/i.test(loadError.value)) {
          return "这条通道对单次响应有大小限制（实测 10MB 能过、16MB 会被断开）。大文件请用下面的按钮下载后在本机查看。";
        }
        return "";
      });
      function cancelLoad() {
        if (loadJob !== null) loadJob.abort();
        loadJob = null;
        loading.value = false;
        loadState.value = null;
        // 取消后落到"读不出内容"那张卡片：下载 / 新标签页两个出口还在。
        loadError.value = "已取消读取（大文件建议直接下载后在本机看）";
      }
      watch(active, function (plugin) {
        clearApi();
        if (!plugin) return;
        FV.prefs.setView(ctx.ext, plugin.id);
        if (plugin.needs === "text" && ctx.text === null) loadText();
      }, { flush: "sync" }); // 同步跑：先把上一个视图注册的能力清掉，再让新视图挂载时重新注册
      // 文本类默认视图需要正文；没内联时先取回来。
      if (ctx.text === null && registryList.some(function (p) { return p.needs === "text"; })) loadText();

      /* 路径直达：贴一个本机绝对路径，按 URL 编码跳 file.view —— 方便随时测任意文件 */
      var pathOpen = ref(false);
      var pathInput = ref("");
      var recent = ref(readRecent());
      function readRecent() {
        try {
          var value = JSON.parse(window.localStorage.getItem("fv-recent") || "[]");
          return Array.isArray(value) ? value.filter(function (x) { return typeof x === "string"; }).slice(0, 8) : [];
        } catch (error) { return []; }
      }
      function saveRecent(list) {
        try { window.localStorage.setItem("fv-recent", JSON.stringify(list.slice(0, 8))); } catch (error) {}
      }
      /** 粘进来的可能是带引号的、file:/// 开头的、或正斜杠写法：统一成干净的 Windows 绝对路径。 */
      function normalizePath(raw) {
        var text = String(raw === undefined || raw === null ? "" : raw).trim().replace(/^["']+|["']+$/g, "");
        if (/^file:\/\//i.test(text)) {
          try { text = decodeURIComponent(text.replace(/^file:\/\//i, "").replace(/^\//, "")); } catch (error) {}
        }
        return text.replace(/^\/+/, "").replace(/\//g, "\\");
      }
      var pathUrl = computed(function () {
        var clean = normalizePath(pathInput.value);
        return clean ? "file.view?path=" + encodeURIComponent(clean) : "file.view";
      });
      function goPath() {
        var clean = normalizePath(pathInput.value);
        if (!clean) { toast("先粘一个本机绝对路径"); return; }
        if (!/^[A-Za-z]:\\/.test(clean) && clean.slice(0, 2) !== "\\\\") toast("提示：要用盘符开头的完整路径");
        pathInput.value = clean;
        var list = [clean].concat(recent.value.filter(function (item) { return item !== clean; })).slice(0, 8);
        recent.value = list; saveRecent(list);
        window.location.href = "file.view?path=" + encodeURIComponent(clean);
      }
      function togglePath() {
        pathOpen.value = !pathOpen.value;
        if (!pathOpen.value) return;
        if (!pathInput.value) {
          try { pathInput.value = decodeURIComponent((window.location.search.match(/[?&]path=([^&]*)/) || [])[1] || ""); } catch (error) {}
        }
        nextTick(function () {
          var field = document.querySelector(".pathbar input");
          if (field) { field.focus(); if (field.select) field.select(); }
        });
      }
      function baseNameOf(value) {
        var parts = String(value).split(/[\\/]/);
        return parts[parts.length - 1] || value;
      }
      function copyPathUrl() {
        var absolute = "";
        try { absolute = new URL(pathUrl.value, window.location.href).href; } catch (error) { absolute = pathUrl.value; }
        U.copy(absolute).then(function () { toast("链接已复制"); }, function () { toast("复制失败"); });
      }

      /* 主题 */
      var theme = ref(FV.prefs.theme());
      function applyTheme() {
        if (theme.value === "auto") document.documentElement.removeAttribute("data-theme");
        else document.documentElement.setAttribute("data-theme", theme.value);
        FV.prefs.setTheme(theme.value);
      }
      applyTheme();
      watch(theme, applyTheme);
      function toggleTheme() {
        var dark = document.documentElement.getAttribute("data-theme") === "dark" ||
          (theme.value === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
        theme.value = dark ? "light" : "dark";
      }

      var kindClass = computed(function () { return "kind-" + U.kindOf(ctx.ext); });
      var badge = computed(function () {
        return FV.badgeIcon(U.kindOf(ctx.ext), ["md","markdown"].indexOf(ctx.ext) >= 0 ? "md" : ctx.ext);
      });
      var meta = computed(function () {
        var parts = [];
        if (ctx.sizeText) parts.push(ctx.sizeText);
        if (ctx.ext) parts.push(ctx.ext.toUpperCase());
        if (api.extra) parts.push(api.extra);
        return parts.join(" · ");
      });

      function openExternal() { window.open(ctx.rawUrl, "_blank", "noopener"); }
      function copyPath() {
        var path = "";
        try { path = decodeURIComponent((location.search.match(/[?&]path=([^&]*)/) || [])[1] || ""); } catch (e) { path = ""; }
        U.copy(path || ctx.rawUrl).then(function () { toast("路径已复制"); }, function () { toast("复制失败"); });
      }
      function copyContent() {
        var run = api.copyText || function () { return U.copy(ctx.text || ""); };
        run().then(function () { toast("已复制"); }, function () { toast("复制失败"); });
      }
      function download() { U.download(ctx.rawUrl, ctx.name); }
      function fullscreen() {
        var el = document.documentElement;
        if (document.fullscreenElement) { document.exitFullscreen().catch(function () {}); return; }
        if (el.requestFullscreen) el.requestFullscreen().catch(function () { toast("这个环境不允许全屏"); });
      }

      /* 快捷键 */
      function onKey(event) {
        var tag = event.target && event.target.tagName;
        var typing = tag === "INPUT" || tag === "TEXTAREA" || (event.target && event.target.isContentEditable);
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey) {
          if (event.key === "f" || event.key === "F") { if (api.toggleFind) { event.preventDefault(); api.toggleFind(); } return; }
          if (event.key === "s" || event.key === "S") { event.preventDefault(); download(); return; }
          if (event.key === "c" && !api.copyText && ctx.text) return;
          return;
        }
        if (typing) return;
        var id = active.value ? active.value.id : "";
        if (event.key === "o" || event.key === "O") { event.preventDefault(); togglePath(); return; }
        if (event.key === "Escape") { if (api.closeFind) api.closeFind(); if (pathOpen.value) pathOpen.value = false; if (document.fullscreenElement) document.exitFullscreen().catch(function () {}); return; }
        if (id === "image") {
          if (event.key === "+" || event.key === "=") { event.preventDefault(); api.zoomIn && api.zoomIn(); }
          else if (event.key === "-" || event.key === "_") { event.preventDefault(); api.zoomOut && api.zoomOut(); }
          else if (event.key === "0") { event.preventDefault(); api.toggleFit && api.toggleFit(); }
          else if (event.key === "r" || event.key === "R") { event.preventDefault(); api.rotate && api.rotate(); }
          else if (event.key === "f" || event.key === "F") { event.preventDefault(); fullscreen(); }
          return;
        }
        if (active.value && active.value.needs === "text") {
          if (event.key === "w" || event.key === "W") { event.preventDefault(); api.toggleWrap && api.toggleWrap(); }
          else if (event.key === "c" || event.key === "C") { event.preventDefault(); copyContent(); }
          else if (event.key === "+" || event.key === "=") { event.preventDefault(); api.fontUp && api.fontUp(); }
          else if (event.key === "-" || event.key === "_") { event.preventDefault(); api.fontDown && api.fontDown(); }
        }
      }
      onMounted(function () { window.addEventListener("keydown", onKey); });
      Vue.onBeforeUnmount(function () { window.removeEventListener("keydown", onKey); });

      return {
        ctx: ctx, api: api, plugins: plugins, active: active, alternatives: alternatives, activeId: activeId,
        activeView: activeView, activeControls: activeControls, stageRev: stageRev,
        pathOpen: pathOpen, pathInput: pathInput, pathUrl: pathUrl, recent: recent,
        togglePath: togglePath, goPath: goPath, copyPathUrl: copyPathUrl, baseName: baseNameOf,
        openPathTab: function () { window.open(pathUrl.value, "_blank", "noopener"); },
        pickRecent: function (value) { pathInput.value = value; goPath(); },
        loading: loading, loadError: loadError, loadErrorHint: loadErrorHint, loadState: loadState, cancelLoad: cancelLoad, readTitle: computed(function () { return "正在读取 " + ctx.name; }), badgeIcon: computed(function () { return U.kindOf(ctx.ext) === "media" ? "video" : "doc"; }), theme: theme, kindClass: kindClass, badge: badge, meta: meta,
        toastText: toastText, icon: icon,
        pick: function (id) { activeId.value = id; },
        toggleTheme: toggleTheme, openExternal: openExternal, copyPath: copyPath, copyContent: copyContent,
        download: download, fullscreen: fullscreen,
        fullscreenCapable: computed(function () { var id = active.value && active.value.id; return id === "image" || id === "video"; })
      };    },
    template:
      '<header class="bar">' +
      '<div class="ident">' +
      '<span class="badge" :class="kindClass" aria-hidden="true" v-html="badge"></span>' +
      '<div class="titles">' +
      '<h1 class="name" :title="ctx.name">{{ ctx.name }}</h1>' +
      '<div class="sub"><span>{{ meta }}</span><span v-if="loadError" style="color:var(--warn)">读取失败</span></div>' +
      "</div></div>" +

      '<div class="tools">' +
      '<div class="seg" v-if="alternatives.length">' +
      '<button type="button" :aria-selected="activeId === active.id" @click="pick(active.id)">{{ active.label }}</button>' +
      '<button v-for="p in alternatives" :key="p.id" type="button" aria-selected="false" @click="pick(p.id)">{{ p.label }}</button>' +
      "</div>" +
      "<component :is=\"activeControls\" v-if=\"activeControls\"></component>" +
      '<div class="group">' +
      '<button class="btn icon" type="button" title="全屏（F）" v-if="fullscreenCapable" @click="fullscreen" v-html="icon(\'expand\')"></button>' +
      '<button class="btn icon" type="button" title="打开本地路径（o）：贴一个盘符路径直接看" @click="togglePath" v-html="icon(\'folder\')"></button>' +
      '<button class="btn icon" type="button" title="复制文件路径" @click="copyPath" v-html="icon(\'copy\')"></button>' +
      '<a class="btn icon" :href="ctx.rawUrl" target="_blank" rel="noopener" title="在新标签页打开" v-html="icon(\'external\')"></a>' +
      '<button class="btn icon ghost" type="button" title="切换深/浅色" @click="toggleTheme" v-html="icon(theme === \'dark\' ? \'sun\' : \'moon\')"></button>' +
      '<button class="btn primary" type="button" title="下载（Ctrl+S）" @click="download" v-html="icon(\'download\') + \'<span class=label>下载</span>\'"></button>' +
      "</div></div></header>" +

      // 路径直达条：输入 → 实时显示编码后的链接 → 回车跳转
      '<div class="pathbar" v-if="pathOpen">' +
      '<div class="row">' +
      '<input v-model="pathInput" spellcheck="false" autocomplete="off" placeholder="例：E:\\zhxuli\\muisc\\demo.mp3（也可用正斜杠）" @keydown.enter.prevent="goPath" @keydown.esc.prevent="pathOpen = false">' +
      '<button class="btn primary" type="button" @click="goPath">打开</button>' +
      '<button class="btn icon" type="button" title="复制编码后的链接" @click="copyPathUrl" v-html="icon(\'link\')"></button>' +
      '<button class="btn icon" type="button" title="在新标签页打开" @click="openPathTab" v-html="icon(\'external\')"></button>' +
      '<button class="btn icon" type="button" title="关闭（Esc）" @click="pathOpen = false" v-html="icon(\'close\')"></button>' +
      "</div>" +
      '<div class="encoded" title="点击复制这条编码后的链接" @click="copyPathUrl">{{ pathUrl }}</div>' +
      '<div class="chips" v-if="recent.length">' +
      '<button class="chip" type="button" v-for="item in recent" :key="item" :title="item" @click="pickRecent(item)">{{ baseName(item) }}</button>' +
      "</div></div>" +

      '<main class="stage">' +
      '<div class="pane scroll" v-show="loading">' +
      '<loading-panel variant="card" :icon="badgeIcon" :title="readTitle" :state="loadState" :cancel="cancelLoad"></loading-panel>' +
      "</div>" +
      '<div class="pane scroll" v-show="loadError">' +
      '<state-card icon="unknown" warn title="读不出文件内容" :text="loadError">' +
      '<div v-if="loadErrorHint" style="color:var(--warn)">{{ loadErrorHint }}</div>' +
      '<div class="cta"><button class="btn primary" @click="download" v-html="icon(\'download\') + \'<span class=label>下载文件</span>\'"></button>' +
      '<a class="btn ghost" :href="ctx.rawUrl" target="_blank" rel="noopener">在新标签页打开</a></div>' +
      "</state-card></div>" +
      // 视图一直挂在固定的位置上（不参与 v-if 分支切换，也不用 key 重建），
      // 只由插件解析结果决定是不是渲染 —— 分支切换 + 动态组件很容易把子树 patch 成空注释。
      "<component v-if=\"activeView\" :is=\"activeView\" :ctx=\"ctx\" :key=\"activeId\"></component>" +
      "</main>" +
      '<div class="toast" :class="{ \'is-on\': toastText }" role="status" aria-live="polite">{{ toastText }}</div>'
  };

  FV.app = Vue.createApp(App);
  // 渲染期错误一定要留痕：生产版 Vue 遇到组件渲染报错只会把子树换成注释占位，
  // 表面上就是"页面空了一块"。window.__fvErrors 里能看到真实原因。
  FV.app.config.errorHandler = function (error, instance, info) {
    var line = String((error && error.message) || error) + " @" + info;
    (window.__fvErrors = window.__fvErrors || []).push(line);
    if (window.console && console.error) console.error("[file.view]", line);
  };
  FV.mount = function () {
    var instance = FV.app.mount("#app");
    // 调试口：控制台里 FV.debug.api / FV.debug.ctx 可以看当前视图注册进来的能力与上下文。
    FV.debug = instance;
    var boot = document.getElementById("boot");
    if (boot) boot.remove();
  };
})();





