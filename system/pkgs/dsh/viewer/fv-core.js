/* ===========================================================================
   核心：启动数据、工具、解析器、语法着色、插件注册表
   —— 不依赖 Vue，先于视图脚本加载。
   =========================================================================== */
window.FV = window.FV || {};

/* ------------------------------------------------------------------ 启动数据 */
FV.boot = (function () {
  var box = document.getElementById("boot");
  var nameEl = document.getElementById("boot-name");
  var sizeEl = document.getElementById("boot-size");
  var rawEl = document.getElementById("boot-raw");
  var bodyEl = document.getElementById("boot-body");
  var name = nameEl ? nameEl.textContent.trim() : document.title;
  var m = /\.([A-Za-z0-9_]+)\s*$/.exec(name);
  var body = bodyEl || document.createElement("div");
  var img = body.querySelector("img");
  var pre = body.querySelector("pre");
  var notice = body.querySelector(".empty");
  var noticeText = notice ? (notice.textContent || "").trim() : "";
  return {
    name: name,
    ext: m ? m[1].toLowerCase() : "",
    sizeText: sizeEl ? sizeEl.textContent.trim() : "",
    bytes: FV.util ? 0 : 0,
    rawUrl: rawEl ? rawEl.textContent.trim() : "",
    dataUri: img ? img.getAttribute("src") : null,
    text: pre ? pre.textContent : null,
    notice: noticeText || null,
    tooLarge: /过大/.test(noticeText)
  };
})();

/* ------------------------------------------------------------------ 带进度的读取 */
/**
 * 流式读取一个文件，边读边回报进度：大文件时进度条、速度、剩余时间都靠它。
 * @param url - 要读的地址（桥的 file.fetch）。
 * @param options - `{ kind: "text"|"bytes", total: number, onProgress: (state) => void }`。
 * @returns `{ promise, abort, state }`；promise 兑现为文本或 Uint8Array。
 */
FV.loadStream = function (url, options) {
  var opts = options || {};
  var controller = new AbortController();
  var state = { loaded: 0, total: opts.total || 0, speed: 0, eta: null, progress: 0, done: false, indeterminate: false, type: "" };
  var lastTick = Date.now(), lastBytes = 0, speed = 0;
  var emit = function () { if (opts.onProgress) opts.onProgress(state); };

  var promise = fetch(url, { cache: "no-store", signal: controller.signal }).then(function (response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    var total = parseInt(response.headers.get("content-length") || "0", 10) || state.total || 0;
    state.total = total;
    state.type = response.headers.get("content-type") || "";
    if (!response.body || typeof response.body.getReader !== "function") {
      state.indeterminate = total === 0;
      return response[opts.kind === "text" ? "text" : "arrayBuffer"]();
    }
    var reader = response.body.getReader();
    var chunks = [], received = 0;
    var decoder = opts.kind === "text" && typeof TextDecoder === "function" ? new TextDecoder("utf-8") : null;
    var text = "";
    var finish = function () {
      if (!total) state.indeterminate = true;
      state.done = true; state.progress = 1; state.eta = 0; emit();
      if (opts.kind === "text") return text + (decoder ? decoder.decode() : "");
      var out = new Uint8Array(received), offset = 0;
      for (var i = 0; i < chunks.length; i += 1) { out.set(chunks[i], offset); offset += chunks[i].length; }
      return out;
    };
    var pump = function () {
      return reader.read().then(function (step) {
        if (step.done) return finish();
        var chunk = step.value;
        received += chunk.length;
        if (decoder !== null) text += decoder.decode(chunk, { stream: true });
        else chunks.push(chunk);
        var now = Date.now();
        if (now - lastTick >= 200) {
          speed = ((received - lastBytes) / (now - lastTick)) * 1000;
          lastTick = now; lastBytes = received;
        }
        state.loaded = received;
        state.speed = speed;
        state.progress = total ? Math.min(1, received / total) : 0;
        state.indeterminate = total === 0;
        state.eta = speed > 2048 && total ? Math.max(0, (total - received) / speed) : null;
        emit();
        return pump();
      });
    };
    return pump();
  });
  return {
    promise: promise,
    abort: function () { try { controller.abort(); } catch (error) {} },
    state: state
  };
};

/* ------------------------------------------------------------------ 工具 */
FV.util = (function () {
  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function parseSize(text) {
    var m = /([\d.]+)\s*(B|KB|MB|GB)?/i.exec(String(text || ""));
    if (!m) return 0;
    var n = parseFloat(m[1]);
    var unit = (m[2] || "B").toUpperCase();
    var mul = unit === "GB" ? 1073741824 : unit === "MB" ? 1048576 : unit === "KB" ? 1024 : 1;
    return Math.round(n * mul);
  }
  function humanBytes(n) {
    if (!n) return "0 B";
    var units = ["B", "KB", "MB", "GB", "TB"], i = 0, v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return (i === 0 ? Math.round(v) : v.toFixed(1)) + " " + units[i];
  }
  function clock(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    var s = Math.floor(seconds % 60), m = Math.floor(seconds / 60) % 60, h = Math.floor(seconds / 3600);
    var mm = (h > 0 && m < 10 ? "0" : "") + m;
    return (h > 0 ? h + ":" : "") + mm + ":" + (s < 10 ? "0" : "") + s;
  }
  /** 速率：B/s → 人类可读。 */
  function humanRate(bytesPerSecond) {
    if (!bytesPerSecond || !isFinite(bytesPerSecond) || bytesPerSecond <= 0) return "";
    return humanBytes(bytesPerSecond) + "/s";
  }
  /** 剩余时间：秒 → "12 秒" / "1 分 20 秒"。 */
  function humanEta(seconds) {
    if (seconds === null || seconds === undefined || !isFinite(seconds) || seconds < 0) return "";
    if (seconds < 1) return "不到 1 秒";
    if (seconds < 60) return Math.round(seconds) + " 秒";
    var minutes = Math.floor(seconds / 60);
    return minutes + " 分 " + Math.round(seconds % 60) + " 秒";
  }
  /** 只允许安全协议，避免 data: 之外的 javascript: 之类。 */
  function safeUrl(url) {
    return /^(https?:|mailto:|#|\/|\.)/i.test(url) ? url : "#";
  }
  function download(url, name) {
    var a = document.createElement("a");
    a.href = url;
    if (name) a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      area.remove();
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }
  /** 带缓存的内容读取（文本 / 字节）。 */
  function makeLoader(url, kind) {
    var cache = null, pending = null;
    return function load(onProgress) {
      if (cache) return Promise.resolve(cache);
      if (pending) return pending;
      pending = FV.loadStream(url, { kind: kind, onProgress: onProgress }).promise.then(function (value) {
        cache = value; pending = null; return value;
      }, function (error) {
        pending = null; throw error;
      });
      return pending;
    };
  }
  /** 稳定的扩展名 → 大类，用于徽标配色。 */
  function kindOf(ext) {
    if (["png","jpg","jpeg","gif","webp","bmp","ico","avif","svg","tif","tiff"].indexOf(ext) >= 0) return "media";
    if (["mp4","webm","mov","m4v","mkv","avi","mp3","wav","ogg","m4a","aac","flac"].indexOf(ext) >= 0) return "media";
    if (["js","mjs","cjs","ts","tsx","jsx","py","rb","go","rs","java","c","h","cpp","hpp","cs","php","swift","kt","lua","sh","bash","bat","cmd","ps1","sql","vue","html","htm","css","scss","less"].indexOf(ext) >= 0) return "code";
    if (["json","jsonl","csv","tsv","yml","yaml","toml","ini","conf","env","properties","xml"].indexOf(ext) >= 0) return "data";
    return "doc";
  }
  var SIZE = parseSize(FV.boot.sizeText);
  FV.boot.bytes = SIZE;
  return { escapeHtml: escapeHtml, parseSize: parseSize, humanBytes: humanBytes, humanRate: humanRate, humanEta: humanEta, clock: clock, safeUrl: safeUrl, download: download, copy: copy, makeLoader: makeLoader, kindOf: kindOf };
})();

/* ------------------------------------------------------------------ 语法着色 */
FV.hl = (function () {
  var KW = {
    js: "var let const function return if else for while do break continue new class extends super this typeof instanceof in of try catch finally throw switch case default delete void yield await async import export from as static get set null true false undefined NaN".split(" "),
    py: "def class return if elif else for while break continue import from as pass raise try except finally with lambda yield global nonlocal assert del in is not and or None True False async await match case self".split(" "),
    sh: "if then else elif fi for while do done case esac function return in do export local readonly set unset echo cd exit source alias".split(" "),
    sql: "select from where insert into values update set delete create table alter drop index join left right inner outer on group by order having limit offset union all distinct as and or not null primary key foreign references default".split(" "),
    c: "int char long short float double void struct union enum typedef static const unsigned signed return if else for while do switch case default break continue goto sizeof extern register volatile inline class public private protected virtual override template typename namespace using new delete try catch throw auto bool true false nullptr this".split(" "),
    css: "important media supports keyframes import charset font-face".split(" "),
    go: "func package import var const type struct interface map chan go defer return if else for range switch case default break continue select nil true false make new".split(" "),
    rs: "fn let mut const struct enum impl trait use mod pub crate self super match if else for while loop return break continue where as dyn ref move async await unsafe true false".split(" "),
    rb: "def end class module require include return if elsif else unless while until for do begin rescue ensure raise yield block_given? nil true false self attr_accessor puts".split(" "),
    php: "function class return if else elseif foreach for while do switch case break continue new echo print public private protected static const use namespace try catch finally throw as array null true false".split(" "),
    java: "public private protected class interface extends implements return if else for while do switch case default break continue new static final void int long double float boolean char String try catch finally throw throws import package this super null true false enum".split(" ")
  };
  var FAMILY = {
    js: ["js","mjs","cjs","ts","tsx","jsx","json","jsonl","vue","svelte"],
    py: ["py","pyw"],
    sh: ["sh","bash","zsh","bat","cmd","ps1","fish"],
    sql: ["sql"],
    c: ["c","h","cpp","hpp","cc","cs","java","kt","swift","m","mm","go","rs"],
    css: ["css","scss","less"],
    rb: ["rb"],
    php: ["php"]
  };
  var MARKUP = ["html","htm","xml","svg","vue","svelte"];
  var STYLE_ATTRS = ["css","scss","less"];
  /**
   * 只有这些语言族有 C 风格的块注释 `/* … *​/`。
   * Python/Shell/Ruby 用 `#`，绝不能把代码里的 `/api/*` 当成块注释开头 —— 那会让
   * 从那儿往后的所有行都渲染成灰色注释。
   */
  var BLOCK_COMMENT = ["js","sql","c","css","php"];
  /** 有三引号多行字符串的语言族（docstring 要整段按字符串着色）。 */
  var TRIPLE_QUOTE = ["py"];
  var CAN_HIGHLIGHT = 400000; // 字符上限：超过就纯文本，避免卡顿

  function familyOf(lang) {
    for (var key in FAMILY) if (FAMILY[key].indexOf(lang) >= 0) return key;
    return null;
  }

  /** 一行一个 token 数组：[{t, c}]；c 为 null 表示普通文本。 */
  function tokenize(line, family, lang, state) {
    var out = [];
    var i = 0, n = line.length;
    var keywords = KW[family] || [];
    var lineComment = family === "py" || family === "sh" || family === "rb" ? "#" : family === "sql" ? "--" : family === "css" ? null : "//";
    var hasBlock = BLOCK_COMMENT.indexOf(family) >= 0;
    var hasTriple = TRIPLE_QUOTE.indexOf(family) >= 0;
    var isMarkup = MARKUP.indexOf(lang) >= 0;
    var buf = "";
    function flush() { if (buf) { out.push({ t: buf, c: null }); buf = ""; } }
    function push(text, cls) { flush(); out.push({ t: text, c: cls }); }

    if (isMarkup) {
      // HTML/SVG/XML：标签、属性、注释、内嵌文本
      while (i < n) {
        if (state.htmlComment) {
          var endC = line.indexOf("-->", i);
          if (endC < 0) { push(line.slice(i), "com"); i = n; }
          else { push(line.slice(i, endC + 3), "com"); i = endC + 3; state.htmlComment = false; }
          continue;
        }
        if (line.startsWith("<!--", i)) { state.htmlComment = true; continue; }
        if (line[i] === "<") {
          var gt = line.indexOf(">", i);
          var chunk = gt < 0 ? line.slice(i) : line.slice(i, gt + 1);
          var inner = chunk.replace(/^<\/?/, "").replace(/>$/, "").replace(/\/$/, "");
          var nameMatch = /^[A-Za-z][\w:-]*/.exec(inner);
          push(chunk.slice(0, 1 + (chunk[1] === "/" ? 1 : 0)), "op");
          if (nameMatch) {
            push(nameMatch[0], "tag");
            var rest = inner.slice(nameMatch[0].length);
            var attrRe = /([A-Za-z_:][\w:.-]*)(\s*=\s*)("[^"]*"|'[^']*'|[^\s>]+)?/g, am;
            var last = 0;
            while ((am = attrRe.exec(rest)) !== null) {
              if (am.index > last) push(rest.slice(last, am.index), null);
              push(am[1], "attr");
              if (am[2]) push(am[2], "op");
              if (am[3]) push(am[3], "str");
              last = am.index + am[0].length;
            }
            if (last < rest.length) push(rest.slice(last), null);
          } else {
            push(inner, null);
          }
          push(gt < 0 ? "" : ">", "op");
          i = gt < 0 ? n : gt + 1;
          continue;
        }
        var nextTag = line.indexOf("<", i);
        var text = nextTag < 0 ? line.slice(i) : line.slice(i, nextTag);
        push(text, null);
        i = nextTag < 0 ? n : nextTag;
      }
      return out;
    }

    while (i < n) {
      var ch = line[i];
      // 三引号多行字符串：跨行保持"字符串"状态，docstring 才不会被当成注释或普通文本。
      if (state.triple) {
        var endTriple = line.indexOf(state.triple, i);
        if (endTriple < 0) { push(line.slice(i), "str"); i = n; }
        else { push(line.slice(i, endTriple + 3), "str"); i = endTriple + 3; state.triple = null; }
        continue;
      }
      if (state.block) {
        var endB = line.indexOf("*/", i);
        if (endB < 0) { push(line.slice(i), "com"); i = n; }
        else { push(line.slice(i, endB + 2), "com"); i = endB + 2; state.block = false; }
        continue;
      }
      if (lineComment && line.startsWith(lineComment, i)) { push(line.slice(i), "com"); i = n; continue; }
      if (hasBlock && ch === "/" && line[i + 1] === "*") { state.block = true; i += 2; continue; }
      if (hasTriple && (line.startsWith("\"\"\"", i) || line.startsWith("'''", i))) {
        state.triple = line.substr(i, 3);
        var closedTriple = line.indexOf(state.triple, i + 3);
        if (closedTriple < 0) { push(line.slice(i), "str"); i = n; }
        else { push(line.slice(i, closedTriple + 3), "str"); i = closedTriple + 3; state.triple = null; }
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") {
        var quote = ch, j = i + 1, closed = false;
        while (j < n) {
          if (line[j] === "\\") { j += 2; continue; }
          if (line[j] === quote) { closed = true; break; }
          j += 1;
        }
        if (closed) { push(line.slice(i, j + 1), "str"); i = j + 1; }
        else { push(line.slice(i), "str"); i = n; }
        continue;
      }
      if (/[0-9]/.test(ch) && !/[\w$]/.test(line[i - 1] || "")) {
        var nm = /^(0[xX][0-9a-fA-F]+|\d+(\.\d+)?([eE][+-]?\d+)?)/.exec(line.slice(i));
        push(nm[0], "num"); i += nm[0].length; continue;
      }
      if (/[A-Za-z_$]/.test(ch)) {
        var idm = /^[A-Za-z_$][\w$]*/.exec(line.slice(i));
        var word = idm[0];
        var rest2 = line.slice(i + word.length);
        if (keywords.indexOf(word) >= 0) push(word, "kw");
        else if (/^\s*\(/.test(rest2)) push(word, "fn");
        else if (/^[A-Z]/.test(word)) push(word, "fn");
        else push(word, null);
        i += word.length;
        continue;
      }
      if (/[=+\-*/%<>!&|^~?:;,.(){}\[\]]/.test(ch)) { push(ch, "op"); i += 1; continue; }
      buf += ch; i += 1;
    }
    flush();
    return out;
  }

  /** 把整段代码切成 [{tokens, text}]，text 用于查找/复制。 */
  function highlight(code, lang) {
    var family = familyOf(lang);
    var markup = MARKUP.indexOf(lang) >= 0;
    var lines = code.split("\n");
    // 标记语言（html/xml/svg）没有关键字表，但有自己的标签/属性分词路径，不能一起挡掉。
    if ((!family && !markup) || code.length > CAN_HIGHLIGHT) {
      return lines.map(function (line) { return { tokens: [{ t: line, c: null }], text: line }; });
    }
    var state = { block: false, triple: null, htmlComment: false };
    return lines.map(function (line) {
      var tokens = tokenize(line, family, lang, state);
      return { tokens: tokens, text: line };
    });
  }

  return { highlight: highlight, familyOf: familyOf, isMarkup: function (lang) { return MARKUP.indexOf(lang) >= 0; } };
})();

/* ------------------------------------------------------------------ 解析器 */
FV.parse = (function () {
  var U = FV.util;

  /** key=value / [section] / #comment；env/properties/ini/conf 通吃。 */
  function ini(text) {
    var out = [{ name: null, entries: [], notes: [] }];
    var cur = out[0];
    text.split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line) return;
      if (/^[#;]/.test(line)) { cur.notes.push(raw); return; }
      var sec = /^\[(.+)\]$/.exec(line);
      if (sec) { cur = { name: sec[1], entries: [], notes: [] }; out.push(cur); return; }
      var kv = /^([^=:]+?)\s*[=:]\s*(.*)$/.exec(raw);
      if (kv) {
        var value = kv[2].trim();
        var cls = "str";
        if (/^(true|false|yes|no|on|off)$/i.test(value)) cls = "bool";
        else if (/^-?\d+(\.\d+)?$/.test(value)) cls = "num";
        cur.entries.push({ key: kv[1].trim(), value: value, cls: cls, quote: /^["'].*["']$/.test(value) });
      } else {
        cur.entries.push({ key: null, value: line, cls: "str", quote: false });
      }
    });
    return out.filter(function (s) { return s.name !== null || s.entries.length || s.notes.length; });
  }

  /** 极简 TOML：只管 [table] 与 key = value（含数组/内联表按原样显示）。 */
  function toml(text) { return ini(text); }

  /** 缩进树（YAML 的 key: value / - item）。 */
  function yaml(text) {
    var root = { name: null, entries: [], notes: [] };
    var stack = [{ indent: -1, section: root }];
    text.split(/\r?\n/).forEach(function (raw) {
      if (!raw.trim()) return;
      if (/^\s*[#]/.test(raw)) { stack[stack.length - 1].section.notes.push(raw); return; }
      var indent = raw.match(/^\s*/)[0].replace(/\t/g, "  ").length;
      var line = raw.trim();
      while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
      var sec = stack[stack.length - 1].section;
      var kv = /^(- )?([^:]+):\s*(.*)$/.exec(line);
      if (kv && !kv[1]) {
        var child = { name: kv[2].trim(), entries: [], notes: [] };
        if (kv[3].trim()) child.entries.push({ key: null, value: kv[3].trim(), cls: "str", quote: false });
        sec.entries.push({ key: kv[2].trim(), value: kv[3].trim(), cls: "str", quote: false, child: child });
        stack.push({ indent: indent, section: child });
        return;
      }
      var item = /^- (.*)$/.exec(line);
      if (item) { sec.entries.push({ key: null, value: "• " + item[1], cls: "str", quote: false }); return; }
      var kv2 = /^([^:]+):\s*(.*)$/.exec(line);
      if (kv2) { sec.entries.push({ key: kv2[1].trim(), value: kv2[2].trim(), cls: "str", quote: false }); return; }
      sec.entries.push({ key: null, value: line, cls: "str", quote: false });
    });
    return [root].concat(flatten(root));
    function flatten(sec) {
      var list = [];
      (sec.entries || []).forEach(function (e) { if (e.child && (e.child.entries.length || e.child.notes.length)) list.push(e.child); });
      return list.reduce(function (acc, s) { return acc.concat([s], flatten(s)); }, []);
    }
  }

  /** CSV/TSV：引号包裹、双引号转义、分隔符自动识别。 */
  function delimited(text, ext) {
    var sep = ext === "tsv" ? "\t" : null;
    var sample = text.slice(0, 4000);
    if (!sep) {
      var counts = { ",": 0, ";": 0, "\t": 0, "|": 0 };
      var inQ = false;
      for (var k = 0; k < sample.length; k += 1) {
        var c = sample[k];
        if (c === '"') inQ = !inQ;
        else if (!inQ && counts[c] !== undefined) counts[c] += 1;
      }
      sep = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0] || ",";
    }
    var rows = [], row = [], field = "", quoted = false;
    for (var i = 0; i < text.length; i += 1) {
      var ch = text[i];
      if (quoted) {
        if (ch === '"') {
          if (text[i + 1] === '"') { field += '"'; i += 1; }
          else quoted = false;
        } else field += ch;
        continue;
      }
      if (ch === '"') { quoted = true; continue; }
      if (ch === sep) { row.push(field); field = ""; continue; }
      if (ch === "\n") { row.push(field); rows.push(row); row = []; field = ""; continue; }
      if (ch === "\r") continue;
      field += ch;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    return { rows: rows, sep: sep };
  }

  /** Markdown → HTML（先整体转义，再按块解析；链接只放行安全协议）。 */
  function markdown(src) {
    var esc = U.escapeHtml;
    function inline(text) {
      var out = esc(text);
      out = out.replace(/`([^`]+)`/g, function (_, code) { return "<code>" + code + "</code>"; });
      out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, function (_, alt, url) {
        return '<a href="' + U.safeUrl(url) + '" target="_blank" rel="noopener">🖼 ' + (alt || url) + "</a>";
      });
      out = out.replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, function (_, label, url) {
        return '<a href="' + U.safeUrl(url) + '" target="_blank" rel="noopener">' + label + "</a>";
      });
      out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
      out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
      return out;
    }
    var lines = src.split(/\r?\n/), html = [], i = 0;
    var listStack = [];
    function closeLists(toDepth) {
      while (listStack.length > toDepth) { html.push("</" + listStack.pop().type + ">"); }
    }
    while (i < lines.length) {
      var line = lines[i];
      var fence = /^\s*(```|~~~)\s*([\w+-]*)\s*$/.exec(line);
      if (fence) {
        closeLists(0);
        var body = [], lang = fence[2] || "";
        i += 1;
        while (i < lines.length && !/^\s*(```|~~~)\s*$/.test(lines[i])) { body.push(lines[i]); i += 1; }
        i += 1;
        html.push('<pre data-lang="' + esc(lang) + '"><code>' + esc(body.join("\n")) + "</code></pre>");
        continue;
      }
      var heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) { closeLists(0); var lv = heading[1].length; html.push("<h" + lv + ">" + inline(heading[2]) + "</h" + lv + ">"); i += 1; continue; }
      if (/^\s*([-*_])\s*\1\s*\1[\s\S]*$/.test(line)) { closeLists(0); html.push("<hr>"); i += 1; continue; }
      if (/^\s*>/.test(line)) {
        closeLists(0);
        var quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
        html.push("<blockquote>" + markdown(quote.join("\n")) + "</blockquote>");
        continue;
      }
      // 表格：表头 + 分隔行
      if (/^\s*\|/.test(line) && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
        closeLists(0);
        var head = splitRow(line);
        i += 2;
        var body2 = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) { body2.push(splitRow(lines[i])); i += 1; }
        html.push("<table><thead><tr>" + head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
          body2.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; }).join("") +
          "</tbody></table>");
        continue;
      }
      var item = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
      if (item) {
        var depth = Math.floor(item[1].replace(/\t/g, "  ").length / 2) + 1;
        var type = /\d/.test(item[2]) ? "ol" : "ul";
        if (listStack.length < depth) {
          while (listStack.length < depth) { html.push("<" + type + ">"); listStack.push({ type: type }); }
        } else {
          closeLists(depth);
          if (listStack.length && listStack[listStack.length - 1].type !== type) { html.push("</" + listStack.pop().type + ">"); html.push("<" + type + ">"); listStack.push({ type: type }); }
        }
        var task = /^\[([ xX])\]\s+(.*)$/.exec(item[3]);
        if (task) html.push('<li class="task">' + (task[1].toLowerCase() === "x" ? "☑" : "☐") + " " + inline(task[2]) + "</li>");
        else html.push("<li>" + inline(item[3]) + "</li>");
        i += 1;
        continue;
      }
      if (!line.trim()) { closeLists(0); i += 1; continue; }
      closeLists(0);
      var para = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|\s*>|\s*```|\s*\|)/.test(lines[i])) { para.push(lines[i]); i += 1; }
      html.push("<p>" + inline(para.join("<br>")) + "</p>");
    }
    closeLists(0);
    return html.join("\n");
    function splitRow(row) { return row.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); }
  }

  /** JSON → 树节点；解析失败返回 null。 */
  function json(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }
  /** JSONL：每行一个对象。 */
  function jsonl(text) {
    var out = [];
    text.split(/\r?\n/).forEach(function (line, index) {
      if (!line.trim()) return;
      try { out.push({ line: index + 1, value: JSON.parse(line) }); }
      catch (e) { out.push({ line: index + 1, value: line, broken: true }); }
    });
    return out;
  }
  return { ini: ini, toml: toml, yaml: yaml, delimited: delimited, markdown: markdown, json: json, jsonl: jsonl };
})();

/* ------------------------------------------------------------------ 插件注册表 */
FV.registry = (function () {
  var plugins = [];
  function register(plugin) {
    if (!plugin || !plugin.id || typeof plugin.match !== "function") throw new Error("bad plugin");
    plugins.push({
      id: plugin.id,
      order: 100,
      needs: null, // "text" | "bytes" | null
      kind: "doc",
      label: plugin.label || plugin.id,
      match: plugin.match,
      view: plugin.view,
      controls: plugin.controls || null,
      probe: plugin.probe || null,
      group: plugin.group || null,
      ext: plugin.ext || null
    });
    plugins[plugins.length - 1].order = plugin.order === undefined ? 100 : plugin.order;
    plugins[plugins.length - 1].needs = plugin.needs === undefined ? null : plugin.needs;
    plugins[plugins.length - 1].kind = plugin.kind || "doc";
    return plugins[plugins.length - 1];
  }
  /**
   * 按优先级列出所有能处理该文件的插件。
   * 同一 group 里只保留优先级最高的那个：例如 .csv 既有「表格」也有专门的
   * 「源码」和通用「文本」，通用文本就不必再出现在切换器里。
   */
  function resolve(ctx) {
    var list = plugins.filter(function (p) {
      try { return p.match(ctx) === true; }
      catch (e) { return false; }
    }).sort(function (a, b) { return b.order - a.order; });
    var seen = {};
    return list.filter(function (p) {
      if (!p.group) return true;
      if (seen[p.group]) return false;
      seen[p.group] = true;
      return true;
    });
  }
  function byId(id) {
    for (var i = 0; i < plugins.length; i += 1) if (plugins[i].id === id) return plugins[i];
    return null;
  }
  return { register: register, resolve: resolve, byId: byId, all: function () { return plugins.slice(); } };
})();

