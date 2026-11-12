(function () {
  var Vue = window.Vue, FV = window.FV, U = FV.util, P = FV.parse;
  if (!Vue) return; 
  var ref = Vue.ref, computed = Vue.computed, onMounted = Vue.onMounted, watch = Vue.watch, nextTick = Vue.nextTick;
  var icon = FV.icon;

  var CardView = {
    name: "CardView",
    props: { title: String, text: String, warn: Boolean, iconName: { type: String, default: "unknown" } },
    template:
      '<div class="pane scroll"><div class="card">' +
      '<span class="mark" :class="{ warn: warn }" v-html="icon(iconName)"></span>' +
      '<div class="ttl" v-if="title">{{ title }}</div>' +
      "<div>{{ text }}</div>" +
      '<div class="cta"><button class="btn primary" @click="dl" v-html="icon(\'download\') + \'<span class=label>下载文件</span>\'"></button>' +
      '<a class="btn ghost" :href="raw" target="_blank" rel="noopener">在新标签页打开</a></div>' +
      "</div></div>",
    data: function () { return { raw: FV.boot.rawUrl }; },
    methods: { icon: icon, dl: function () { U.download(FV.boot.rawUrl, FV.boot.name); } }
  };

  var TextView = {
    name: "TextView",
    props: { ctx: Object },
    setup: function (props) {
      var wrapOn = ref(FV.prefs.wrap(props.ctx));
      var size = ref(FV.prefs.size(props.ctx));
      var findOpen = ref(false);
      var query = ref("");
      var current = ref(0);
      var box = ref(null);
      var sizes = [10, 11, 12, 13, 14, 15, 16, 18, 20, 22];
      var isCode = FV.langs.isCode(props.ctx.ext);
      var text = computed(function () { return props.ctx.text || ""; });
      var lines = computed(function () { return text.value.length ? text.value.split("\n") : [""]; });
      var rendered = computed(function () {
        if (query.value) return null;
        return FV.hl.highlight(text.value, props.ctx.ext);
      });
      var matches = computed(function () {
        var q = query.value;
        if (!q) return [];
        var out = [], needle = q.toLowerCase(), src = lines.value;
        for (var i = 0; i < src.length; i += 1) {
          var hay = src[i].toLowerCase(), from = 0, at;
          while ((at = hay.indexOf(needle, from)) >= 0) { out.push({ line: i, start: at, len: q.length }); from = at + Math.max(1, q.length); }
          if (out.length > 4000) break;
        }
        return out;
      });
      function segmentsFor(lineIndex) {
        var line = lines.value[lineIndex] || "";
        var all = matches.value;
        var segs = [], pos = 0;
        for (var i = 0; i < all.length; i += 1) {
          var m = all[i];
          if (m.line !== lineIndex) continue;
          if (m.start > pos) segs.push({ t: line.slice(pos, m.start), hit: false });
          segs.push({ t: line.substr(m.start, m.len), hit: true, index: i });
          pos = m.start + m.len;
        }
        if (!segs.length) return [{ t: line, hit: false }];
        if (pos < line.length) segs.push({ t: line.slice(pos), hit: false });
        return segs;
      }
      function goto(index) {
        var list = matches.value;
        if (!list.length) return;
        current.value = ((index % list.length) + list.length) % list.length;
        nextTick(function () {
          var el = box.value && box.value.querySelector('[data-hit="' + current.value + '"]');
          if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", inline: "nearest" });
        });
      }

      function closeFind() { findOpen.value = false; query.value = ""; }
      function findNext() { goto(current.value + 1); }
      function findPrev() { goto(current.value - 1); }
      var api = Vue.inject("fv-api");

      var bigMode = computed(function () { return text.value.length > 400000 || lines.value.length > 4000; });
      onMounted(function () {
        api.wrapOn = computed(function () { return wrapOn.value; });
        api.findAvailable = computed(function () { return !bigMode.value; });
        api.toggleWrap = function () { wrapOn.value = !wrapOn.value; FV.prefs.setWrap(props.ctx, wrapOn.value); };
        api.findOpen = computed(function () { return findOpen.value; });
        api.toggleFind = function () { findOpen.value = !findOpen.value; if (findOpen.value) nextTick(function () { var i = box.value && box.value.parentElement.querySelector(".find input"); if (i) i.focus(); }); };
        api.copyText = function () { return U.copy(text.value); };
        api.fontUp = function () { size.value = sizes[Math.min(sizes.length - 1, sizes.indexOf(size.value) + 1)]; FV.prefs.setSize(props.ctx, size.value); };
        api.fontDown = function () { size.value = sizes[Math.max(0, sizes.indexOf(size.value) - 1)]; FV.prefs.setSize(props.ctx, size.value); };
        api.canFontUp = computed(function () { return size.value < sizes[sizes.length - 1]; });
        api.canFontDown = computed(function () { return size.value > sizes[0]; });
        api.findNext = findNext;
        api.findPrev = findPrev;
        api.closeFind = closeFind;
      });
      watch(matches, function () { current.value = 0; });
      return {
        wrapOn: wrapOn, size: size, findOpen: findOpen, query: query, current: current, box: box,
        findNext: findNext, findPrev: findPrev, closeFind: closeFind,
        lines: lines, rendered: rendered, matches: matches, isCode: isCode, segmentsFor: segmentsFor,
        lineCount: computed(function () { return lines.value.length; }),
        bigMode: bigMode,
        text: text,
        showGutter: computed(function () { return !wrapOn.value && !bigMode.value && lines.value.length > 1 && lines.value.length <= 6000; })
      };
    },
    template:
      '<div class="pane" style="flex:1;min-height:0">' +
      '<div class="find" v-if="findOpen">' +
      '<input ref="findInput" v-model="query" placeholder="在当前文件里查找…" @keydown.enter.prevent="findNext" @keydown.esc.prevent="closeFind" @keydown.shift.enter.prevent="findPrev">' +
      '<span class="count">{{ matches.length ? (current + 1) + "/" + matches.length : "无匹配" }}</span>' +
      '<button class="btn icon" @click="findPrev" title="上一个" v-html="icon(\'rotate\')" style="transform:scaleX(-1)"></button>' +
      '<button class="btn icon" @click="findNext" title="下一个" v-html="icon(\'rotate\')"></button>' +
      '<button class="btn icon" @click="closeFind" title="关闭（Esc）" v-html="icon(\'close\')"></button>' +
      "</div>" +
      '<div class="pane scroll" ref="box">' +
      '<div class="doc" :class="{ measure: !isCode }" :style="{ \'--code-size\': size + \'px\' }" :data-wrap="wrapOn ? \'on\' : \'off\'">' +
      "<pre class=\"code\" v-if=\"bigMode\" :style=\"{ \'white-space\': wrapOn ? \'pre-wrap\' : \'pre\' }\">{{ text }}</pre>" +
      '<div class="codewrap" :class="{ wrap: wrapOn }" v-else>' +
      '<pre class="gutter" v-if="showGutter" aria-hidden="true">{{ lines.map((_, i) => i + 1).join("\\n") }}</pre>' +
      '<pre class="code">' +
      "<span class=\"line\" v-for=\"(line, li) in lines\" :key=\"li\">" +
      "<template v-if=\"query\">" +
      "<span v-for=\"(seg, si) in segmentsFor(li)\" :key=\"si\" :class=\"{ \'tok-com\': false }\">" +
      "<mark v-if=\"seg.hit\" class=\"hit\" :class=\"{ on: seg.index === current }\" :data-hit=\"seg.index\">{{ seg.t }}</mark>" +
      "<template v-else>{{ seg.t }}</template>" +
      "</span>" +
      "</template>" +
      "<template v-else>" +
      "<span v-for=\"(tk, ti) in (rendered ? rendered[li].tokens : [])\" :key=\"ti\" :class=\"tk.c ? \'tok-\' + tk.c : null\">{{ tk.t }}</span>" +
      "</template>" +
      "</span>" +
      "</pre></div></div></div></div>",
    methods: { icon: icon }
  };

  var TextControls = {
    setup: function () {
      var api = Vue.inject("fv-api");
      var copied = ref(false);
      return {
        api: api, copied: copied,
        copy: function () {
          if (!api.copyText) return;
          api.copyText().then(function () { copied.value = true; setTimeout(function () { copied.value = false; }, 1200); }, function () {});
        }
      };
    },
    template:
      '<div class="group">' +
      '<button class="btn icon" type="button" v-if="api.findAvailable" title="查找（Ctrl+F）" @click="api.toggleFind" v-html="icon(\'search\')"></button>' +
      '<button class="btn icon" type="button" v-if="api.toggleWrap" :aria-pressed="api.wrapOn" title="自动换行（w）" @click="api.toggleWrap" v-html="icon(\'wrap\')"></button>' +
      '<button class="btn icon" type="button" v-if="api.fontDown" title="缩小字号（−）" :disabled="api.canFontDown === false" @click="api.fontDown" v-html="icon(\'minus\')"></button>' +
      '<button class="btn icon" type="button" v-if="api.fontUp" title="放大字号（+）" :disabled="api.canFontUp === false" @click="api.fontUp" v-html="icon(\'plus\')"></button>' +
      '<button class="btn" type="button" v-if="api.expandAll" title="全部展开" @click="api.expandAll"><span class="label">展开</span></button>' +
      '<button class="btn" type="button" v-if="api.collapseAll" title="全部折叠" @click="api.collapseAll"><span class="label">折叠</span></button>' +
      '<button class="btn icon" type="button" v-if="api.copyText" :title="copied ? \'已复制\' : \'复制全部（c）\'" @click="copy" v-html="icon(copied ? \'check\' : \'copy\')"></button>' +
      "</div>",
    methods: { icon: icon }
  };

  var MarkdownView = {
    name: "MarkdownView",
    props: { ctx: Object },
    setup: function (props) {
      var html = computed(function () { return P.markdown(props.ctx.text || ""); });
      var api = Vue.inject("fv-api");
      onMounted(function () { api.copyText = function () { return U.copy(props.ctx.text || ""); }; });
      return { html: html };
    },
    template: '<div class="pane scroll"><article class="md" v-html="html"></article></div>'
  };

  var TableView = {
    name: "TableView",
    props: { ctx: Object },
    setup: function (props) {
      var parsed = computed(function () { return P.delimited(props.ctx.text || "", props.ctx.ext); });
      var rows = computed(function () { return parsed.value.rows; });
      var hasHeader = ref(true);
      var sortCol = ref(-1), sortAsc = ref(true), filter = ref(""), limit = ref(800);
      var header = computed(function () { return hasHeader.value ? (rows.value[0] || []) : []; });
      var body = computed(function () {
        var list = hasHeader.value ? rows.value.slice(1) : rows.value.slice();
        var q = filter.value.trim().toLowerCase();
        if (q) list = list.filter(function (r) { return r.some(function (c) { return String(c).toLowerCase().indexOf(q) >= 0; }); });
        if (sortCol.value >= 0) {
          list = list.slice().sort(function (a, b) {
            var x = a[sortCol.value] === undefined ? "" : a[sortCol.value], y = b[sortCol.value] === undefined ? "" : b[sortCol.value];
            var nx = parseFloat(x), ny = parseFloat(y);
            var numeric = isFinite(nx) && isFinite(ny) && String(x).trim() !== "" && String(y).trim() !== "";
            var r = numeric ? nx - ny : String(x).localeCompare(String(y), "zh");
            return sortAsc.value ? r : -r;
          });
        }
        return list;
      });
      var shown = computed(function () { return body.value.slice(0, limit.value); });
      var cols = computed(function () {
        var max = 0;
        rows.value.slice(0, 200).forEach(function (r) { max = Math.max(max, r.length); });
        return max;
      });
      function isNum(value) { return value !== "" && value !== undefined && isFinite(parseFloat(value)) && /^-?[\d.,\s]+$/.test(String(value)); }
      function sortBy(index) {
        if (sortCol.value === index) sortAsc.value = !sortAsc.value;
        else { sortCol.value = index; sortAsc.value = true; }
      }
      var api = Vue.inject("fv-api");
      onMounted(function () {
        api.copyText = function () { return U.copy(props.ctx.text || ""); };
        api.extra = rows.value.length + " 行 × " + cols.value + " 列";
      });
      return {
        header: header, body: body, shown: shown, cols: cols, hasHeader: hasHeader, sortCol: sortCol, sortAsc: sortAsc,
        filter: filter, limit: limit, isNum: isNum, sortBy: sortBy,
        more: computed(function () { return body.value.length > limit.value; })
      };
    },
    template:
      '<div class="pane" style="flex:1;min-height:0">' +
      '<div class="find">' +
      '<input v-model="filter" placeholder="过滤行…">' +
      '<label class="count" style="display:flex;align-items:center;gap:5px;cursor:pointer;min-width:auto"><input type="checkbox" v-model="hasHeader"> 首行是表头</label>' +
      '<span class="count">{{ body.length }} 行</span>' +
      "</div>" +
      '<div class="tablewrap">' +
      '<table class="grid">' +
      "<thead><tr><th class=\"idx\">#</th>" +
      "<th v-for=\"(cell, ci) in (header.length ? header : new Array(cols).fill(\'\'))\" :key=\"ci\" @click=\"sortBy(ci)\">" +
      "{{ cell || (\"列 \" + (ci + 1)) }}<span class=\"arw\" v-if=\"sortCol === ci\">{{ sortAsc ? \'▲\' : \'▼\' }}</span></th>" +
      "</tr></thead>" +
      "<tbody>" +
      "<tr v-for=\"(row, ri) in shown\" :key=\"ri\">" +
      "<td class=\"idx\">{{ (hasHeader ? ri + 2 : ri + 1) }}</td>" +
      "<td v-for=\"(cell, ci) in row\" :key=\"ci\" :class=\"{ num: isNum(cell) }\" :title=\"cell\">{{ cell }}</td>" +
      "</tr>" +
      "</tbody></table>" +
      '<div class="card" v-if="more" style="padding:18px"><button class="btn" @click="limit += 2000">还有 {{ body.length - limit }} 行，继续加载</button></div>' +
      "</div></div>"
  };

  var JsonNode = {
    name: "JsonNode",
    props: { label: String, value: null, depth: { type: Number, default: 0 }, openAll: Boolean },
    setup: function (props) {
      var open = ref(props.depth < 2 || props.openAll);
      watch(function () { return props.openAll; }, function (v) { open.value = v; });
      var type = computed(function () {
        var v = props.value;
        if (v === null) return "null";
        if (Array.isArray(v)) return "array";
        return typeof v;
      });
      var entries = computed(function () {
        if (type.value === "array") return props.value.map(function (v, i) { return { k: i, v: v }; });
        if (type.value === "object") return Object.keys(props.value).map(function (k) { return { k: k, v: props.value[k] }; });
        return [];
      });
      return {
        open: open, type: type, entries: entries,
        preview: computed(function () {
          if (type.value === "array") return "[" + props.value.length + "]";
          if (type.value === "object") return "{" + Object.keys(props.value).length + "}";
          return "";
        }),
        text: computed(function () {
          var v = props.value;
          if (type.value === "string") return JSON.stringify(v);
          if (type.value === "null") return "null";
          return String(v);
        })
      };
    },
    template:
      '<div class="tnode">' +
      '<div class="trow">' +
      '<button class="ttoggle" v-if="entries.length" :data-open="open" @click="open = !open" v-html="icon(\'rotate\')" style="width:14px;height:14px"></button>' +
      '<span v-else style="width:14px"></span>' +
      '<span class="tkey" :class="{ q: true }" v-if="label !== undefined && label !== null">{{ label }}</span>' +
      '<span class="tsep" v-if="label !== undefined && label !== null">:</span>' +
      "<template v-if=\"entries.length\"><span class=\"tmeta\">{{ preview }}</span></template>" +
      "<template v-else><span :class=\"\'t\' + type\">{{ text }}</span></template>" +
      "</div>" +
      '<div class="tkids" v-if="open && entries.length">' +
      '<json-node v-for="(e, i) in entries" :key="i" :label="e.k" :value="e.v" :depth="depth + 1" :open-all="openAll"></json-node>' +
      "</div></div>",
    methods: { icon: icon }
  };

  var JsonView = {
    name: "JsonView",
    props: { ctx: Object },
    components: { JsonNode: JsonNode },
    setup: function (props) {
      var data = computed(function () {
        if (props.ctx.ext === "jsonl") return P.jsonl(props.ctx.text || "");
        return P.json(props.ctx.text || "");
      });
      var openAll = ref(false);
      var api = Vue.inject("fv-api");
      onMounted(function () {
        api.copyText = function () { return U.copy(props.ctx.text || ""); };
        api.expandAll = function () { openAll.value = true; };
        api.collapseAll = function () { openAll.value = false; };
        var d = data.value;
        if (d && !Array.isArray(d) && typeof d === "object") api.extra = Object.keys(d).length + " 个键";
        else if (Array.isArray(d)) api.extra = d.length + " 项";
      });
      return { data: data, openAll: openAll };
    },
    template:
      '<div class="pane scroll">' +
      '<div class="tree" v-if="data !== null">' +
      "<json-node :label=\"null\" :value=\"data\" :depth=\"0\" :open-all=\"openAll\"></json-node>" +
      "</div>" +
      '<div class="card" v-else><span class="mark warn" v-html="icon(\'unknown\')"></span><div class="ttl">JSON 解析失败</div>' +
      "<div>内容不是合法 JSON，可以切到「源码」看原文。</div>" +
      '<div class="cta"><button class="btn primary" @click="dl" v-html="icon(\'download\') + \'<span class=label>下载文件</span>\'"></button></div></div>' +
      "</div>",
    methods: { icon: icon, dl: function () { U.download(FV.boot.rawUrl, FV.boot.name); } }
  };

  var ConfigView = {
    name: "ConfigView",
    props: { ctx: Object },
    setup: function (props) {
      var sections = computed(function () {
        var text = props.ctx.text || "", ext = props.ctx.ext;
        if (ext === "yml" || ext === "yaml") return P.yaml(text);
        return P.ini(text);
      });
      var api = Vue.inject("fv-api");
      onMounted(function () {
        api.copyText = function () { return U.copy(props.ctx.text || ""); };
        var count = sections.value.reduce(function (n, s) { return n + s.entries.length; }, 0);
        api.extra = count + " 项";
      });
      return { sections: sections };
    },
    template:
      '<div class="pane scroll"><div class="conf">' +
      "<section v-for=\"(sec, si) in sections\" :key=\"si\">" +
      "<h3 v-if=\"sec.name\">{{ sec.name }}</h3>" +
      '<div class="row" v-for="(e, ei) in sec.entries" :key="ei">' +
      '<span class="k" v-if="e.key">{{ e.key }}</span><span class="k" v-else style="color:var(--faint)">—</span>' +
      '<span class="v" :class="e.cls">{{ e.value }}</span>' +
      "</div>" +
      '<div class="note" v-for="(n, ni) in sec.notes" :key="\'n\' + ni">{{ n.trim() }}</div>' +
      '<div class="empty" v-if="!sec.entries.length && !sec.notes.length && sec.name">（这一节没有内容）</div>' +
      "</section>" +
      "</div></div>"
  };

  var HtmlView = {
    name: "HtmlView",
    props: { ctx: Object },
    setup: function (props) {
      var srcdoc = computed(function () { return props.ctx.text || ""; });
      return { srcdoc: srcdoc, raw: FV.boot.rawUrl };
    },
    template:
      '<div class="pane" style="flex:1;min-height:0">' +
      '<div class="find" style="justify-content:space-between">' +
      '<span style="font-size:12px;color:var(--muted)">沙箱预览：脚本可运行，但拿不到本页的数据</span>' +
      '<span class="group"><a class="btn ghost" :href="raw" target="_blank" rel="noopener">新标签页打开</a></span>' +
      "</div>" +
      '<iframe style="flex:1;min-height:0;width:100%;border:0;background:#fff" sandbox="allow-scripts allow-popups allow-forms allow-modals" :srcdoc="srcdoc"></iframe>' +
      "</div>"
  };

  var HexView = {
    name: "HexView",
    components: { LoadingPanel: FV.ui.LoadingPanel },
    props: { ctx: Object },
    setup: function (props) {
      var bytes = ref(null);
      var error = ref("");
      var loadInfo = ref({ progress: 0, loaded: 0, total: FV.boot.bytes || 0, speed: 0, eta: null });
      onMounted(function () {
        FV.loadStream(FV.boot.rawUrl, {
          kind: "bytes",
          total: FV.boot.bytes || 0,
          onProgress: function (state) { loadInfo.value = Object.assign({}, state); }
        }).promise.then(function (buffer) {
          bytes.value = new Uint8Array(buffer.slice(0, 131072));
        }, function (e) { error.value = e.message; });
      });
      var dump = computed(function () {
        if (!bytes.value) return [];
        var out = [], b = bytes.value;
        for (var i = 0; i < b.length; i += 16) {
          var chunk = b.slice(i, i + 16), hex = [], asc = "";
          for (var j = 0; j < 16; j += 1) {
            hex.push(j < chunk.length ? chunk[j].toString(16).padStart(2, "0") : "  ");
            if (j < chunk.length) { var c = chunk[j]; asc += c >= 32 && c < 127 ? String.fromCharCode(c) : "."; }
          }
          out.push({ off: i.toString(16).padStart(8, "0"), hex: hex.slice(0, 8).join(" ") + "  " + hex.slice(8).join(" "), asc: asc });
        }
        return out;
      });
      return {
        dump: dump, error: error, loadInfo: loadInfo,
        progressPct: computed(function () { return Math.round((loadInfo.value.progress || 0) * 100); }),
        truncated: computed(function () { return bytes.value && bytes.value.length >= 131072; })
      };
    },
    template:
      '<div class="pane scroll">' +
      '<div class="pane scroll" v-if="!dump.length && !error" style="display:flex;align-items:center;justify-content:center">' +
      '<loading-panel variant="card" icon="data" title="正在读取字节…" :state="loadInfo"></loading-panel></div>' +
      '<div class="hex" v-if="!error">' +
      '<div v-for="(r, i) in dump" :key="i"><span class="off">{{ r.off }}</span>  {{ r.hex }}  <span class="asc">|{{ r.asc }}|</span></div>' +
      '<div v-if="truncated" style="color:var(--warn);margin-top:8px">（只显示前 128 KB）</div>' +
      "</div>" +
      '<div class="card" v-else><span class="mark warn" v-html="icon(\'unknown\')"></span><div class="ttl">读不出内容</div><div>{{ error }}</div></div>' +
      "</div>",
    methods: { icon: icon }
  };

  var DownloadView = {
    name: "DownloadView",
    props: { ctx: Object },
    template:
      '<div class="pane scroll"><div class="card">' +
      '<span class="mark" v-html="icon(\'big\')"></span>' +
      '<div class="ttl">{{ ctx.name }}</div>' +
      "<div>{{ ctx.sizeText }} · {{ ctx.ext ? ctx.ext.toUpperCase() + \" 文件\" : \"未知类型\" }}" +
      "<template v-if=\"ctx.tooLarge\">，超过了在线预览的大小上限</template>" +
      "<template v-else-if=\"!isKnown\">，浏览器里没有对应的查看器</template></div>" +
      '<div class="cta"><button class="btn primary" @click="dl" v-html="icon(\'download\') + \'<span class=label>下载文件</span>\'"></button>' +
      '<a class="btn ghost" :href="ctx.rawUrl" target="_blank" rel="noopener">在新标签页打开</a></div>' +
      "</div></div>",
    computed: { isKnown: function () { return FV.langs.isText(this.ctx.ext) || FV.langs.isCode(this.ctx.ext); } },
    methods: { icon: icon, dl: function () { U.download(this.ctx.rawUrl, this.ctx.name); } }
  };

  FV.langs = (function () {
    var CODE = {
      js: ["js","mjs","cjs","ts","tsx","jsx","vue","svelte"], py: ["py","pyw"], sh: ["sh","bash","zsh","fish"],
      bat: ["bat","cmd","ps1"], sql: ["sql"], go: ["go"], rs: ["rs"], c: ["c","h","cpp","hpp","cc","cs"],
      java: ["java","kt","kts"], swift: ["swift"], rb: ["rb"], php: ["php"], lua: ["lua"], r: ["r"],
      css: ["css","scss","less"], html: ["html","htm"], xml: ["xml","svg"], docker: ["dockerfile"],
      make: ["mk"], tex: ["tex"]
    };
    var LABEL = {
      js: ["JavaScript / TypeScript","源码"], py: ["Python","源码"], sh: ["Shell / PowerShell","源码"], bat: ["批处理 / PowerShell","源码"],
      sql: ["SQL","源码"], go: ["Go","源码"], rs: ["Rust","源码"], c: ["C / C++ / C#","源码"], java: ["Java / Kotlin","源码"],
      swift: ["Swift","源码"], rb: ["Ruby","源码"], php: ["PHP","源码"], lua: ["Lua","源码"], r: ["R","源码"],
      css: ["CSS / 样式","源码"], html: ["HTML","源码"], xml: ["XML / SVG","源码"], docker: ["Dockerfile","源码"],
      make: ["Makefile","源码"], tex: ["LaTeX","源码"]
    };
    var TEXT = ["txt","log","csv","tsv","md","markdown","json","jsonl","yml","yaml","toml","ini","conf","env","properties","gitignore","editorconfig","license","readme","me","nfo","srt","vtt"];
    function familyOf(ext) {
      for (var key in CODE) if (CODE[key].indexOf(ext) >= 0) return key;
      return null;
    }
    return {
      familyOf: familyOf,
      isCode: function (ext) { return familyOf(ext) !== null; },
      isText: function (ext) { return TEXT.indexOf(ext) >= 0 || familyOf(ext) !== null; },
      labelOf: function (ext, fallback) { var f = familyOf(ext); return (f && LABEL[f] && LABEL[f][0]) || fallback; },
      CODE: CODE
    };
  })();

  function registerText(config) {
    FV.registry.register({
      id: config.id, label: config.label, kind: config.kind || "code", order: config.order, needs: "text",
      group: config.group || "text",
      match: function (ctx) {
        if (config.exts) return config.exts.indexOf(ctx.ext) >= 0;
        return FV.langs.isText(ctx.ext) || ctx.text !== null;
      },
      view: config.view || TextView,
      controls: config.controls === null ? null : (config.controls || TextControls)
    });
  }
  Object.keys(FV.langs.CODE).forEach(function (family, index) {
    var exts = FV.langs.CODE[family];
    registerText({ id: "code-" + family, label: FV.langs.labelOf(exts[0], "源码"), exts: exts, order: 60 - index * 0.1, kind: "code" });
  });
  registerText({ id: "text", label: "文本", kind: "doc", order: 40 });
  registerText({ id: "text-md-source", label: "源码", kind: "doc", order: 41, exts: ["md","markdown"], view: TextView });
  registerText({ id: "text-csv-source", label: "源码", kind: "data", order: 41, exts: ["csv","tsv"] });
  registerText({ id: "text-json-source", label: "源码", kind: "data", order: 41, exts: ["json","jsonl"] });
  registerText({ id: "text-conf-source", label: "源码", kind: "data", order: 41, exts: ["ini","conf","env","toml","properties","yml","yaml"] });
  registerText({ id: "text-html-source", label: "源码", kind: "code", order: 61, exts: ["html","htm"] });

  FV.registry.register({ id: "markdown", label: "预览", kind: "doc", order: 90, needs: "text", match: function (ctx) { return ["md","markdown"].indexOf(ctx.ext) >= 0; }, view: MarkdownView, controls: TextControls });
  FV.registry.register({ id: "table", label: "表格", kind: "data", order: 90, needs: "text", match: function (ctx) { return ["csv","tsv"].indexOf(ctx.ext) >= 0; }, view: TableView, controls: TextControls });
  FV.registry.register({ id: "json", label: "结构", kind: "data", order: 90, needs: "text", match: function (ctx) { return ["json","jsonl"].indexOf(ctx.ext) >= 0; }, view: JsonView, controls: TextControls });
  FV.registry.register({ id: "config", label: "解析", kind: "data", order: 90, needs: "text", match: function (ctx) { return ["ini","conf","env","toml","properties","yml","yaml"].indexOf(ctx.ext) >= 0; }, view: ConfigView, controls: TextControls });
  FV.registry.register({ id: "html", label: "预览", kind: "code", order: 85, needs: "text", match: function (ctx) { return ["html","htm"].indexOf(ctx.ext) >= 0; }, view: HtmlView, controls: null });
  FV.registry.register({ id: "hex", label: "十六进制", kind: "data", order: 30, needs: null, match: function (ctx) { return !ctx.text && !ctx.dataUri && ctx.bytes > 0 && ctx.bytes <= 131072; }, view: HexView, controls: null });
  FV.registry.register({ id: "download", label: "文件信息", kind: "doc", order: 0, match: function () { return true; }, view: DownloadView, controls: null });

  FV.CardView = CardView;
})();
