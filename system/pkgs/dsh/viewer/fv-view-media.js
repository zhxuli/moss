/* ===========================================================================
   视图插件 A：图片 / 视频 / 音频 / PDF / 字体
   每个插件形如 { id, label, kind, order, needs, match(ctx), view, controls? }
   —— 视图是 Vue 组件选项对象；controls 渲染到头部工具栏里。
   =========================================================================== */
(function () {
  var Vue = window.Vue, FV = window.FV, U = FV.util;
  if (!Vue) return; // Vue 没加载成功时整段跳过，由页面末尾给出提示
  var ref = Vue.ref, computed = Vue.computed, onMounted = Vue.onMounted, onBeforeUnmount = Vue.onBeforeUnmount, watch = Vue.watch, nextTick = Vue.nextTick;

  /* ---------------------------------------------------------------- 图标 */
  FV.icon = function (name) {
    var paths = {
      image: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="m4 17 4.5-4.5a2 2 0 0 1 2.8 0L20 21"/>',
      video: '<rect x="2.5" y="5" width="14" height="14" rx="3"/><path d="m16.5 10.5 5-3v9l-5-3z"/>',
      audio: '<path d="M9 18V6.5l10-2v11"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/>',
      pdf: '<path d="M6 3h9l4 4v14H6z"/><path d="M14.5 3v4.5H19"/><path d="M9 13h1.6a1.4 1.4 0 0 1 0 2.8H9V13zm0 2.8V19m4-6v6m0-6h2.4M13 16h2"/>',
      font: '<path d="M5 19 11 5l6 14"/><path d="M7.4 14h7.2"/>',
      code: '<path d="m9 8-4 4 4 4"/><path d="m15 8 4 4-4 4"/>',
      text: '<path d="M6 3h9l4 4v14H6z"/><path d="M14.5 3v4.5H19"/><path d="M9 12h6M9 16h4"/>',
      data: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
      doc: '<path d="M6 3h9l4 4v14H6z"/><path d="M14.5 3v4.5H19"/>',
      big: '<path d="M12 3v12"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M4 19h16"/>',
      unknown: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.9.4-1.4 1-1.4 1.9"/><path d="M12 17.2h.01"/>',
      download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
      external: '<path d="M9.4 2.6h4v4"/><path d="M13.3 2.7 7.9 8.1"/><path d="M12.6 9.9v2.7a1 1 0 0 1-1 1H3.4a1 1 0 0 1-1-1V4.3a1 1 0 0 1 1-1h2.7"/>',
      play: '<path d="M7 4.5v15l13-7.5z"/>',
      pause: '<path d="M8 5h3v14H8zM13 5h3v14h-3z"/>',
      plus: '<path d="M12 5v14M5 12h14"/>',
      minus: '<path d="M5 12h14"/>',
      fit: '<path d="M4 9V4h5"/><path d="M20 9V4h-5"/><path d="M4 15v5h5"/><path d="M20 15v5h-5"/>',
      one: '<path d="M9 8.5 11 7v10"/><path d="M15 7v10"/>',
      rotate: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
      copy: '<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M6.5 15H5.5A1.5 1.5 0 0 1 4 13.5v-8A1.5 1.5 0 0 1 5.5 4h8A1.5 1.5 0 0 1 15 5.5v1"/>',
      check: '<path d="m4.5 12.5 5 5 10-11"/>',
      wrap: '<path d="M4 6h16M4 12h11a3 3 0 0 1 0 6h-3"/><path d="M14 15.5 11.5 18 14 20.5"/><path d="M4 18h4"/>',
      search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
      close: '<path d="M6 6l12 12M18 6 6 18"/>',
      sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
      moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
      wrap2: '<path d="M4 6h16M4 12h16M4 18h10"/>',
      tree: '<path d="M4 5h6M4 12h6M4 19h6"/><path d="M14 5h6M14 12h6M14 19h6"/>',
      table: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M9 10v9M15 10v9"/>',
      eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
      expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
      volume: '<path d="M11 5 6.5 9H3v6h3.5L11 19z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5"/><path d="M18 7a7 7 0 0 1 0 10"/>',
      mute: '<path d="M11 5 6.5 9H3v6h3.5L11 19z"/><path d="m15.5 10 4 4M19.5 10l-4 4"/>',
      back10: '<path d="M11.5 5.5A7 7 0 1 1 5.6 16.4"/><path d="M11.5 2.6v3.2H8.3"/>',
      fwd10: '<path d="M12.5 5.5A7 7 0 1 0 18.4 16.4"/><path d="M12.5 2.6v3.2h3.2"/>',
      folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3l2 2.5h7.5A2.5 2.5 0 0 1 20.5 10v6.5A2.5 2.5 0 0 1 18 19H5.5A2.5 2.5 0 0 1 3 16.5z"/><path d="M8.5 13h7"/>',
      link: '<path d="M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1 1"/><path d="M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1-1"/>'
    };
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + (paths[name] || paths.doc) + "</svg>";
  };
  FV.badgeIcon = function (kind, ext) {
    var map = {
      image: "image", video: "video", audio: "audio", pdf: "pdf", font: "font",
      "md": "text", "csv": "table", "tsv": "table", "json": "tree", "jsonl": "tree",
      "yaml": "data", "yml": "data", "toml": "data", "ini": "data", "env": "data", "conf": "data", "properties": "data",
      "code": "code", "text": "text", "html": "code", "zip": "big"
    };
    return FV.icon(map[ext] || (kind === "media" ? "video" : kind === "code" ? "code" : kind === "data" ? "data" : "doc"));
  };

  /* ---------------------------------------------------------------- 图片 */
  var ImageView = {
    name: "ImageView",
    props: { ctx: Object },
    setup: function (props) {
      var api = Vue.inject("fv-api");
      var img = ref(null);
      var ready = ref(false);
      var failed = ref(false);
      var nat = ref({ w: 0, h: 0 });
      var scale = ref(1), tx = ref(0), ty = ref(0), minScale = ref(1), rotation = ref(0);
      var fitted = false; // 画布真正有尺寸之后才算过"适应窗口"，否则算出来的比例是错的
      var canvas = ref(null);
      var pointers = new Map(), dragging = false, lastX = 0, lastY = 0, pinchStart = 0, pinchScale = 1, pinchMid = null, observer = null;
      var showTransition = ref(false);

      var transform = computed(function () {
        return "translate(-50%, -50%) translate3d(" + tx.value + "px," + ty.value + "px,0) scale(" + scale.value + ") rotate(" + rotation.value + "deg)";
      });
      function clampPan() {
        var el = canvas.value; if (!el) return;
        var w = nat.value.w * scale.value, h = nat.value.h * scale.value;
        if (rotation.value % 180 !== 0) { var t = w; w = h; h = t; }
        var maxX = Math.max(0, (w - el.clientWidth) / 2), maxY = Math.max(0, (h - el.clientHeight) / 2);
        tx.value = Math.max(-maxX, Math.min(maxX, tx.value));
        ty.value = Math.max(-maxY, Math.min(maxY, ty.value));
      }
      function label() {
        var pct = Math.round(scale.value * 100);
        api.zoomLabel = pct + "%";
        api.zoomState = Math.abs(scale.value - minScale.value) < 0.001 ? "fit" : "zoom";
        api.canZoomOut = scale.value > minScale.value + 0.001;
        api.canZoomIn = scale.value < 8 - 0.001;
      }
      function fit(animate) {
        var el = canvas.value;
        if (!el || !nat.value.w || el.clientWidth === 0 || el.clientHeight === 0) return; // 尺寸没就绪就不改状态
        var s = Math.min((el.clientWidth - 24) / nat.value.w, (el.clientHeight - 24) / nat.value.h, 1);
        minScale.value = s > 0 ? s : 1;
        scale.value = minScale.value; tx.value = 0; ty.value = 0; rotation.value = 0;
        showTransition.value = !!animate;
        fitted = true;
        label();
      }
      function zoomAt(factor, cx, cy, animate) {
        var el = canvas.value; if (!el) return;
        var next = Math.max(minScale.value, Math.min(8, scale.value * factor));
        if (Math.abs(next - scale.value) < 0.0005) return;
        var rect = el.getBoundingClientRect();
        var px = (cx === undefined ? rect.width / 2 : cx - rect.left) - rect.width / 2;
        var py = (cy === undefined ? rect.height / 2 : cy - rect.top) - rect.height / 2;
        var lx = (px - tx.value) / scale.value, ly = (py - ty.value) / scale.value;
        scale.value = next;
        tx.value = px - lx * scale.value; ty.value = py - ly * scale.value;
        clampPan();
        showTransition.value = !!animate;
        label();
      }
      function onLoad() {
        var el = img.value;
        nat.value = { w: el.naturalWidth || 1, h: el.naturalHeight || 1 };
        api.dimText = nat.value.w + " × " + nat.value.h;
        api.extra = nat.value.w + " × " + nat.value.h;
        ready.value = true;
        // 挂载当帧画布可能还没布局完（宽或高为 0），这时候算出来的"适应"是错的：一直重试到有尺寸。
        var attempt = function (tries) {
          fit(false);
          if (fitted || tries > 40) return;
          requestAnimationFrame(function () { attempt(tries + 1); });
        };
        attempt(0);
      }
      function onError() { failed.value = true; }
      function onWheel(event) {
        if (!(event.ctrlKey || event.metaKey)) {
          if (scale.value <= minScale.value + 0.001) { event.preventDefault(); zoomAt(Math.exp(-event.deltaY * 0.0016), event.clientX, event.clientY, false); }
          return;
        }
        event.preventDefault();
        zoomAt(Math.exp(-event.deltaY * 0.0022), event.clientX, event.clientY, false);
      }
      function onDown(event) {
        if (event.button !== 0 && event.pointerType === "mouse") return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        try { canvas.value.setPointerCapture(event.pointerId); } catch (e) {}
        if (pointers.size === 1) { dragging = true; lastX = event.clientX; lastY = event.clientY; canvas.value.classList.add("is-panning"); }
        if (pointers.size === 2) {
          var pts = Array.from(pointers.values());
          pinchStart = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
          pinchScale = scale.value;
          pinchMid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
          dragging = false;
        }
      }
      function onMove(event) {
        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (pointers.size === 2 && pinchMid) {
          var pts = Array.from(pointers.values());
          var dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
          scale.value = Math.max(minScale.value, Math.min(8, pinchScale * (dist / pinchStart)));
          clampPan(); showTransition.value = false; label();
          return;
        }
        if (!dragging) return;
        tx.value += event.clientX - lastX; ty.value += event.clientY - lastY;
        lastX = event.clientX; lastY = event.clientY;
        clampPan(); showTransition.value = false;
      }
      function onUp(event) {
        pointers.delete(event.pointerId);
        if (pointers.size < 2) pinchMid = null;
        if (pointers.size === 0) { dragging = false; if (canvas.value) canvas.value.classList.remove("is-panning"); }
      }
      function onDbl() {
        if (Math.abs(scale.value - minScale.value) < 0.001) { scale.value = Math.min(8, 1); tx.value = 0; ty.value = 0; clampPan(); showTransition.value = true; label(); }
        else fit(true);
      }
      function onResize() { fit(false); }
      onMounted(function () {
        api.zoomIn = function () { zoomAt(1.25, undefined, undefined, true); };
        api.zoomOut = function () { zoomAt(1 / 1.25, undefined, undefined, true); };
        api.toggleFit = function () {
          if (Math.abs(scale.value - minScale.value) < 0.001 && minScale.value < 1) { scale.value = 1; tx.value = 0; ty.value = 0; clampPan(); showTransition.value = true; }
          else fit(true);
          label();
        };
        api.rotate = function () { rotation.value = (rotation.value + 90) % 360; clampPan(); showTransition.value = true; };
        api.zoomLabel = "100%"; api.zoomState = "zoom"; api.canZoomIn = true; api.canZoomOut = false;
        window.addEventListener("resize", onResize);
        // 面板宽度变化（侧边栏拖拽、手机旋转）时，仍在"适应"状态就重新适应一次
        if (typeof ResizeObserver === "function" && canvas.value !== null) {
          observer = new ResizeObserver(function () {
            if (!nat.value.w) return;
            if (!fitted || Math.abs(scale.value - minScale.value) < 0.001) fit(false);
          });
          observer.observe(canvas.value);
        }
      });
      onBeforeUnmount(function () {
        window.removeEventListener("resize", onResize);
        if (observer !== null && observer !== undefined) observer.disconnect();
        api.zoomIn = api.zoomOut = api.toggleFit = api.rotate = null;
        api.zoomLabel = null;
      });
      return { canvas: canvas, img: img, ready: ready, failed: failed, transform: transform, showTransition: showTransition, onLoad: onLoad, onError: onError, onWheel: onWheel, onDown: onDown, onMove: onMove, onUp: onUp, onDbl: onDbl, src: computed(function () { return props.ctx.dataUri || props.ctx.rawUrl; }) };
    },
    template:
      '<div class="canvas" ref="canvas" @wheel="onWheel" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp" @dblclick="onDbl">' +
      '<img ref="img" :src="src" :class="{ \'is-ready\': ready }" :style="{ transform: transform, transition: showTransition ? \'transform 190ms var(--ease-out)\' : \'none\' }" @load="onLoad" @error="onError" alt="" draggable="false">' +
      "</div>"
  };
  var ImageControls = {
    setup: function () { return { api: Vue.inject("fv-api") }; },
    template:
      '<div class="group">' +
      '<button class="btn icon" type="button" title="缩小（−）" :disabled="!api.canZoomOut" @click="api.zoomOut" v-html="icon(\'minus\')"></button>' +
      '<button class="btn chip" type="button" :data-state="api.zoomState" title="适应窗口 / 100% 切换（0）" @click="api.toggleFit">{{ api.zoomLabel }}</button>' +
      '<button class="btn icon" type="button" title="放大（+）" :disabled="!api.canZoomIn" @click="api.zoomIn" v-html="icon(\'plus\')"></button>' +
      '<button class="btn icon" type="button" title="旋转 90°" @click="api.rotate" v-html="icon(\'rotate\')"></button>' +
      "</div>",
    methods: { icon: FV.icon }
  };

  /* ---------------------------------------------------------------- 视频 */
  var VideoView = {
    name: "VideoView",
    components: { LoadingPanel: FV.ui.LoadingPanel },
    props: { ctx: Object },
    setup: function (props) {
      var failed = ref(false);
      var src = ref("");
      var loading = ref(true), objectUrl = null;
      var loadInfo = ref({ progress: 0, loaded: 0, total: FV.boot.bytes || 0, speed: 0, eta: null });
      onMounted(function () {
        // 短视频同样整包读（桥无 Range），大文件直接流式，免得先等一整包下载。
        var inlineLimit = 64 * 1024 * 1024;
        if (FV.boot.bytes > inlineLimit) {
          src.value = props.ctx.rawUrl; loading.value = false;
          return;
        }
        FV.loadBlob(props.ctx.rawUrl, function (state) { loadInfo.value = Object.assign({}, state); }).promise.then(function (blob) {
          objectUrl = URL.createObjectURL(blob);
          src.value = objectUrl;
          loading.value = false;
        }, function () {
          src.value = props.ctx.rawUrl; loading.value = false;
        });
      });
      onBeforeUnmount(function () { if (objectUrl !== null) URL.revokeObjectURL(objectUrl); });
      return {
        failed: failed, src: src, loading: loading, loadInfo: loadInfo, readTitle: "正在读取 " + FV.boot.name,
        progressPct: computed(function () { return Math.round((loadInfo.value.progress || 0) * 100); }),
        loadLeft: computed(function () {
          var info = loadInfo.value || {};
          return info.total ? U.humanBytes(info.loaded || 0) + " / " + U.humanBytes(info.total) : "已读取 " + U.humanBytes(info.loaded || 0);
        }),
        loadRight: computed(function () {
          var info = loadInfo.value || {};
          if (info.eta !== null && info.eta !== undefined) return "剩余 " + U.humanEta(info.eta);
          if (info.speed) return U.humanRate(info.speed);
          return "读取中…";
        }),
        onError: function () { failed.value = true; }
      };
    },
    template:
      '<div class="pane" v-if="!failed">' +
      '<div class="media">' +
      '<video v-if="!loading" :src="src" controls playsinline preload="auto" @error="onError"></video>' +
      '<loading-panel v-else variant="card" dark icon="video" :title="readTitle" :state="loadInfo"></loading-panel>' +
      "</div></div>" +
      '<div class="pane scroll" v-else>' +
      '<div class="card"><span class="mark warn" v-html="icon(\'video\')"></span>' +
      '<div class="ttl">这个视频浏览器放不了</div>' +
      "<div>编码或容器可能不被支持（例如 HEVC / MKV）。下载后用本机播放器打开即可。</div>" +
      '<div class="cta"><button class="btn primary" @click="dl" v-html="icon(\'download\') + \'<span class=label>下载</span>\'"></button>' +
      '<a class="btn ghost" :href="src" target="_blank" rel="noopener">在新标签页打开</a></div></div></div>',
    methods: {
      icon: FV.icon,
      dl: function () { U.download(this.src, FV.boot.name); }
    }
  };

  /* ---------------------------------------------------------------- 整包读取 */
  /** 把整个文件读成一个 Blob（桥没有 Range，音视频只能整包读）。带进度回调。 */
  FV.loadBlob = function (url, onProgress) {
    var job = FV.loadStream(url, { kind: "bytes", total: FV.boot.bytes || 0, onProgress: onProgress });
    return {
      abort: job.abort,
      state: job.state,
      promise: job.promise.then(function (bytes) {
        return new Blob([bytes], { type: job.state.type || "" });
      })
    };
  };

  /* ---------------------------------------------------------------- PDF */
  var PdfView = {
    name: "PdfView",
    components: { LoadingPanel: FV.ui.LoadingPanel },
    setup: function () {
      var rendered = ref(false);
      return { rendered: rendered, src: FV.boot.rawUrl, name: FV.boot.name };
    },
    template:
      '<div class="pane" style="flex:1;min-height:0">' +
      '<div class="find" style="justify-content:space-between">' +
      "<span style=\"font-size:12px;color:var(--muted)\">浏览器内置 PDF 视图（手机上可能被系统接管）</span>" +
      '<span class="group"><a class="btn ghost" :href="src" target="_blank" rel="noopener">新标签页打开</a>' +
      '<button class="btn" @click="dl" v-html="icon(\'download\') + \'<span class=label>下载</span>\'"></button></span>' +
      "</div>" +
      '<div class="frame-wrap">' +
      '<iframe :src="src" @load="rendered = true" :title="name"></iframe>' +
      '<div class="overlay" v-if="!rendered"><loading-panel variant="card" icon="pdf" title="正在交给浏览器渲染 PDF…" :indeterminate="true"></loading-panel></div>' +
      "</div></div>",
    methods: { icon: FV.icon, dl: function () { U.download(FV.boot.rawUrl, FV.boot.name); } }
  };

  /* ---------------------------------------------------------------- 字体 */
  var FontView = {
    name: "FontView",
    components: { LoadingPanel: FV.ui.LoadingPanel },
    setup: function () {
      var size = ref(40), sample = ref("天地玄黄 宇宙洪荒\nHandgloves 0123 !@#$%&*");
      var glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 一二三四五六七八九十 汉字测试 ！@#¥%……&*（）";
      var status = ref("loading"), family = ref("");
      var loadInfo = ref({ progress: 0, loaded: 0, total: FV.boot.bytes || 0, speed: 0, eta: null });
      onMounted(function () {
        FV.loadStream(FV.boot.rawUrl, {
          kind: "bytes",
          total: FV.boot.bytes || 0,
          onProgress: function (state) { loadInfo.value = Object.assign({}, state); }
        }).promise.then(function (bytes) {
          family.value = "fv-preview-" + Date.now();
          var face = new FontFace(family.value, bytes);
          return face.load().then(function (loaded) {
            document.fonts.add(loaded);
            status.value = "ready";
            api.extra = (loaded.family || FV.boot.name);
          });
        }).catch(function () { status.value = "error"; });
      });
      var api = Vue.inject("fv-api");
      return {
        size: size, sample: sample, glyphs: glyphs, status: status,
        family: computed(function () { return family.value || "inherit"; }),
        onRange: function () {},
        styles: computed(function () { return { fontFamily: family.value || "inherit" }; })
      };
    },
    template:
      '<div class="specimen" :style="{ \'--spec-size\': size + \'px\' }">' +
      '<loading-panel v-if="status === \'loading\'" variant="inline" :state="loadInfo"></loading-panel>' +
      '<div v-else-if="status === \'error\'" class="card"><span class="mark warn" v-html="icon(\'font\')"></span><div class="ttl">字体加载失败</div><div>文件可能损坏或格式不受支持。</div></div>' +
      "<template v-else>" +
      '<div class="sample" :style="styles">{{ sample }}</div>' +
      '<div class="row"><span class="meta">字号</span><input type="range" min="12" max="160" v-model.number="size"><span class="meta">{{ size }}px</span></div>' +
      '<div class="glyphs" :style="styles">{{ glyphs }}</div>' +
      '<div class="row"><input class="btn" style="flex:1;min-width:180px;height:auto;padding:8px 10px;text-align:left" v-model="sample"></div>' +
      '<div class="meta">字体名：{{ family }}</div>' +
      "</template>" +
      "</div>",
    methods: { icon: FV.icon }
  };

  /* ---------------------------------------------------------------- 注册 */
  var IMG = ["png","jpg","jpeg","jfif","gif","webp","bmp","ico","avif","svg","tif","tiff"];
  var VID = ["mp4","webm","mov","m4v","ogv"];
  var VID_MAYBE = ["mkv","avi","wmv","flv","ts","m2ts","3gp"];
  var AUD = ["mp3","wav","ogg","oga","m4a","aac","flac","opus","weba"];
  var FONT = ["ttf","otf","woff","woff2","ttc","eot"];

  FV.registry.register({
    id: "image", label: "图片", kind: "media", order: 100,
    match: function (ctx) { return !!ctx.dataUri || IMG.indexOf(ctx.ext) >= 0; },
    view: ImageView, controls: ImageControls
  });
  FV.registry.register({
    id: "video", label: "视频", kind: "media", order: 100,
    match: function (ctx) { return VID.concat(VID_MAYBE).indexOf(ctx.ext) >= 0 && !ctx.text; },
    view: VideoView
  });

  FV.registry.register({
    id: "pdf", label: "PDF", kind: "media", order: 95,
    match: function (ctx) { return ctx.ext === "pdf"; },
    view: PdfView
  });
  FV.registry.register({
    id: "font", label: "字体", kind: "media", order: 95,
    match: function (ctx) { return FONT.indexOf(ctx.ext) >= 0; },
    view: FontView
  });
})();







/* ===========================================================================
   音频播放器视图 —— 与 ZeEn「音乐播放器」参考页 1:1
   参考：D:\python\wwwroot\ZeEn\AppTools\templates\MultimediaTools\MediaPlay\index.html
   （浅色 Mac 风格 · 纯色柱状频谱 · Canvas 逆时针音量环）

   与参考页的差异只有两处，都是按需求刻意去掉的：
     · 左侧目录 / 播放列表（单文件查看器没有列表）
     · 拖拽文件夹的覆盖层（同上）
   其余 DOM 结构、类名、尺寸、颜色、字体、图标、交互（空格/⌘←→/⌘↑↓、
   单击静音、拖拽转角度调音量、滚轮调音量、中键全屏、频谱左键开关）全部照搬。
   图标用内联 SVG 等价替换 Font Awesome（见 fv-icons.js），图形取自同一版本 6.4.0。
   =========================================================================== */
(function () {
  var Vue = window.Vue, FV = window.FV, U = FV.util;
  if (!Vue) return;
  var ref = Vue.ref, computed = Vue.computed, onMounted = Vue.onMounted, onBeforeUnmount = Vue.onBeforeUnmount;

  /* ================================================================ 工具 */
  /** 与参考页 formatTime 完全一致：mm:ss，两位补零。 */
  function formatTime(seconds) {
    if (!seconds || isNaN(seconds) || seconds === Infinity) return "00:00";
    var m = Math.floor(seconds / 60);
    var s = Math.floor(seconds % 60);
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  /** 与参考页 cleanTitle 一致：去掉文件名里的方括号内容。 */
  function cleanTitle(title) {
    if (!title) return "";
    return title.replace(/\[[^\]]*\]/g, "").trim();
  }

  /* ================================================================ 元数据 */
  /* 参考页用 music-metadata-browser 解析 ID3 拿封面/标题；这里不引外网库，
     直接读本地 Blob 的 ID3v2 / ID3v1 / FLAC 块，够用且零依赖。 */
  var TD = window.TextDecoder;
  function decodeText(bytes, enc) {
    try {
      if (enc === 1) return new TD("utf-16").decode(bytes);   // 带 BOM
      if (enc === 2) return new TD("utf-16be").decode(bytes);
      if (enc === 3) return new TD("utf-8").decode(bytes);
      return new TD("windows-1252").decode(bytes);           // 0 = ISO-8859-1
    } catch (error) {
      var out = "";
      for (var i = 0; i < bytes.length; i++) out += String.fromCharCode(bytes[i]);
      return out;
    }
  }
  function trimNul(text) { return (text || "").replace(/\u0000+$/g, "").replace(/^\u0000+/, "").trim(); }
  function syncsafe(b, o) { return ((b[o] & 0x7f) << 21) | ((b[o + 1] & 0x7f) << 14) | ((b[o + 2] & 0x7f) << 7) | (b[o + 3] & 0x7f); }
  function be32(b, o) { return (b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]; }
  function latin1(bytes) {
    var out = "";
    for (var i = 0; i < bytes.length; i++) out += String.fromCharCode(bytes[i]);
    return out;
  }
  function empty() { return { title: "", artist: "", album: "", cover: null }; }

  /** APIC 帧：编码字节 + MIME + 图片类型 + 描述(按编码终止) + 图片数据 */
  function parseApic(d) {
    if (!d || d.length < 4) return null;
    var enc = d[0], p = 1;
    while (p < d.length && d[p] !== 0) p++;
    var mime = latin1(d.subarray(1, p)) || "image/jpeg";
    p += 2; // 跳过 MIME 的 \0 与图片类型字节
    if (enc === 1 || enc === 2) {
      while (p + 1 < d.length && !(d[p] === 0 && d[p + 1] === 0)) p += 2;
      p += 2;
    } else {
      while (p < d.length && d[p] !== 0) p++;
      p += 1;
    }
    var img = d.subarray(p);
    return img.length ? { mime: mime, bytes: img } : null;
  }

  function parseId3v2(tag) {
    var out = empty();
    var ver = tag[3];
    var pos = 10;
    if (tag[5] & 0x40) pos += ver === 4 ? syncsafe(tag, pos) : be32(tag, pos); // 扩展头
    while (pos + 10 <= tag.length) {
      var id = latin1(tag.subarray(pos, pos + 4));
      if (!/^[A-Z0-9]{4}$/.test(id)) break;
      var size = ver === 4 ? syncsafe(tag, pos + 4) : be32(tag, pos + 4);
      if (size <= 0 || pos + 10 + size > tag.length) break;
      var data = tag.subarray(pos + 10, pos + 10 + size);
      if (id === "APIC") { if (!out.cover) out.cover = parseApic(data); }
      else if (id === "TIT2") out.title = trimNul(decodeText(data.subarray(1), data[0]));
      else if (id === "TPE1") out.artist = trimNul(decodeText(data.subarray(1), data[0]));
      else if (id === "TALB") out.album = trimNul(decodeText(data.subarray(1), data[0]));
      pos += 10 + size;
    }
    return out;
  }

  function parseId3v1(tail) {
    if (tail.length < 128 || latin1(tail.subarray(0, 3)) !== "TAG") return null;
    return {
      title: trimNul(decodeText(tail.subarray(3, 33), 0)),
      artist: trimNul(decodeText(tail.subarray(33, 63), 0)),
      album: trimNul(decodeText(tail.subarray(63, 93), 0))
    };
  }

  /** FLAC VORBIS_COMMENT：小端长度 + "KEY=value" */
  function parseVorbisComment(d) {
    var out = empty();
    var dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
    var p = 0;
    if (d.length < 8) return out;
    p += 4 + dv.getUint32(0, true);
    var count = dv.getUint32(p, true);
    p += 4;
    for (var i = 0; i < count && p + 4 <= d.length; i++) {
      var len = dv.getUint32(p, true);
      p += 4;
      if (p + len > d.length) break;
      var kv = decodeText(d.subarray(p, p + len), 3);
      p += len;
      var eq = kv.indexOf("=");
      if (eq <= 0) continue;
      var key = kv.slice(0, eq).toLowerCase(), val = kv.slice(eq + 1).trim();
      if (key === "title" && !out.title) out.title = val;
      else if (key === "artist" && !out.artist) out.artist = val;
      else if (key === "album" && !out.album) out.album = val;
    }
    return out;
  }

  /** FLAC PICTURE：大端，MIME + 描述 + 宽高深色 + 数据长度 + 数据 */
  function parseFlacPicture(d) {
    if (d.length < 32) return null;
    var dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
    var mimeLen = dv.getUint32(4, false);
    var mime = latin1(d.subarray(8, 8 + mimeLen)) || "image/jpeg";
    var p = 8 + mimeLen;
    p += 4 + dv.getUint32(p, false); // 描述
    p += 16;                          // 宽 高 色深 索引色
    var dataLen = dv.getUint32(p, false);
    p += 4;
    var img = d.subarray(p, Math.min(d.length, p + dataLen));
    return img.length ? { mime: mime, bytes: img } : null;
  }

  /**
   * 从本地 Blob 解析音频元数据（标题/艺术家/专辑/封面）。
   * 认不出的容器不算错，返回 null，界面回落文件名。
   * @param {Blob} blob
   * @returns {Promise<{title:string,artist:string,album:string,cover:?{mime:string,bytes:Uint8Array}}|null>}
   */
  FV.parseAudioMeta = function (blob) {
    var size = blob.size;
    function read(off, len) {
      return blob.slice(off, off + len).arrayBuffer().then(function (buf) { return new Uint8Array(buf); });
    }
    function readFlac() {
      var out = empty();
      function walk(pos) {
        if (pos + 4 > size) return Promise.resolve();
        return read(pos, 4).then(function (head) {
          var last = !!(head[0] & 0x80), type = head[0] & 0x7f;
          var len = (head[1] << 16) | (head[2] << 8) | head[3];
          var next = pos + 4 + len;
          if (type !== 4 && type !== 6) return last ? Promise.resolve() : walk(next);
          return read(pos + 4, len).then(function (body) {
            if (type === 4) {
              var v = parseVorbisComment(body);
              out.title = out.title || v.title;
              out.artist = out.artist || v.artist;
              out.album = out.album || v.album;
            } else if (!out.cover) {
              out.cover = parseFlacPicture(body);
            }
            return last ? Promise.resolve() : walk(next);
          });
        });
      }
      return read(0, 4).then(function (magic) {
        if (latin1(magic) !== "fLaC") return null;
        return walk(4).then(function () { return out; });
      });
    }
    return read(0, 10).then(function (head) {
      if (latin1(head.subarray(0, 3)) !== "ID3") return readFlac();
      var tagSize = syncsafe(head, 6);
      return read(0, Math.min(tagSize + 10, size)).then(function (tag) {
        var out = parseId3v2(tag);
        if (out.title && out.artist && out.album && out.cover) return out;
        var tailLen = Math.min(128, size);
        return read(Math.max(0, size - tailLen), tailLen).then(function (tail) {
          var v1 = parseId3v1(tail);
          if (v1) {
            out.title = out.title || v1.title;
            out.artist = out.artist || v1.artist;
            out.album = out.album || v1.album;
          }
          return out;
        });
      });
    }).catch(function () { return null; });
  };

  /* ================================================================ 视图 */
  var AudioView = {
    name: "AudioView",
    props: { ctx: Object },
    components: { LoadingPanel: FV.ui.LoadingPanel },
    setup: function () {
      /* ---------- 状态（默认值与参考页一致） ---------- */
      var isPlaying = ref(false);
      var volume = ref(0.7);
      var isMuted = ref(false);
      var spectrumEnabled = ref(true);
      var title = ref(cleanTitle(FV.boot.name.replace(/\.[^.]+$/, "")) || FV.boot.name);
      var artist = ref("未知艺术家");
      var album = ref((FV.boot.sizeText || "") + (FV.boot.ext ? " · " + FV.boot.ext.toUpperCase() : ""));
      var coverUrl = ref(null);
      var toastMsg = ref(""), toastShow = ref(false);
      var hudPct = ref(70), hudShow = ref(false);
      var curText = ref("00:00"), durText = ref("00:00"), progressPct = ref(0);
      var loading = ref(true);
      var loadState = ref({ loaded: 0, total: 0, speed: 0, eta: null, progress: 0 });

      /* ---------- DOM ---------- */
      var audioEl = ref(null);
      var specCanvas = ref(null);
      var volCtl = ref(null), volCanvas = ref(null);
      var progressTrack = ref(null);

      /* ---------- 非响应式内部状态 ---------- */
      var sctx = null;                 // 频谱 2d context
      var vctx = null;                 // 音量环 2d context
      var audioContext = null, analyser = null, dataArray = null, sourceNode = null;
      var blockPositions = [];
      var animId = null;
      var audioUrl = null, coverObjectUrl = null, job = null;
      var toastTimer = null, hudTimer = null;
      var isDraggingProgress = false;
      var isDraggingVolume = false, isClick = false, lastDeg;
      var disposed = false, canceled = false;

      /* ---------- 提示 / HUD ---------- */
      function showToast(msg, duration) {
        toastMsg.value = msg;
        toastShow.value = true;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { toastShow.value = false; }, duration || 2200);
      }
      function showHud(percent) {
        hudPct.value = percent;
        hudShow.value = true;
        clearTimeout(hudTimer);
        hudTimer = setTimeout(function () { hudShow.value = false; }, 1200);
      }

      /* ---------- 音量环（Canvas 逆时针，从顶部开始） ---------- */
      function drawVolumeRing() {
        var canvas = volCanvas.value;
        if (!canvas) return;
        if (!vctx) vctx = canvas.getContext("2d");
        var w = canvas.width, h = canvas.height;
        var cx = w / 2, cy = h / 2, radius = 20, lineWidth = 2;
        vctx.clearRect(0, 0, w, h);
        vctx.beginPath();
        vctx.arc(cx, cy, radius, 0, Math.PI * 2);
        vctx.strokeStyle = "rgba(0,0,0,0.04)";
        vctx.lineWidth = lineWidth;
        vctx.stroke();
        var startAngle = -Math.PI / 2;
        var endAngle = startAngle - volume.value * Math.PI * 2;
        vctx.beginPath();
        vctx.arc(cx, cy, radius, startAngle, endAngle, true);
        vctx.strokeStyle = (isMuted.value || volume.value === 0) ? "rgba(0,0,0,0.08)" : "#007aff";
        vctx.lineWidth = lineWidth;
        vctx.lineCap = "round";
        vctx.stroke();
      }
      function updateVolumeRing() {
        drawVolumeRing();
        var a = audioEl.value;
        if (a) a.volume = isMuted.value ? 0 : volume.value;
      }

      /* ---------- 频谱（纯色柱状 + 缓降，占满宽度） ---------- */
      function drawSpectrum() {
        var canvas = specCanvas.value;
        if (!canvas || !canvas.parentElement) return;
        if (!sctx) sctx = canvas.getContext("2d");
        var rect = canvas.parentElement.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var w = rect.width || 600;
        var h = rect.height || 160;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + "px";
        canvas.style.height = h + "px";
        sctx.setTransform(1, 0, 0, 1, 0, 0);
        sctx.scale(dpr, dpr);

        if (!spectrumEnabled.value || !analyser || !dataArray) {
          sctx.clearRect(0, 0, w, h);
          sctx.fillStyle = "rgba(0,0,0,0.04)";
          sctx.font = "14px -apple-system, sans-serif";
          sctx.textAlign = "center";
          sctx.textBaseline = "middle";
          sctx.fillText("频谱已关闭 · 点击开启", w / 2, h / 2);
          return;
        }

        analyser.getByteFrequencyData(dataArray);
        var usedLen = Math.min(dataArray.length, 256);
        var barCount = Math.min(usedLen, 72);
        var step = Math.max(1, Math.floor(usedLen / barCount));

        for (var i = 0; i < barCount; i++) {
          var sum = 0;
          for (var j = 0; j < step && i * step + j < usedLen; j++) sum += dataArray[i * step + j] || 0;
          var target = (sum / step) / 255;
          if (blockPositions[i] === undefined) blockPositions[i] = 0;
          if (target > blockPositions[i]) blockPositions[i] = target;
          else blockPositions[i] = Math.max(0, blockPositions[i] - 0.025);
        }

        sctx.clearRect(0, 0, w, h);
        var gap = 1;
        var barWidth = (w - (barCount - 1) * gap) / barCount;
        var maxHeight = h * 0.88;
        var bottomOffset = h * 0.06;

        sctx.shadowColor = "rgba(0,122,255,0.08)";
        sctx.shadowBlur = 4;
        for (var k = 0; k < barCount; k++) {
          var x = k * (barWidth + gap);
          var height = Math.max(0, (blockPositions[k] || 0) * maxHeight);
          var y = h - bottomOffset - height;
          sctx.fillStyle = "#007aff";
          sctx.fillRect(x, y, barWidth, height);
          if (height > 2) {
            var blockH = Math.min(3, height * 0.1 + 2);
            var blockY = y - blockH + 1;
            sctx.fillStyle = "#007aff";
            sctx.shadowBlur = 8;
            sctx.shadowColor = "rgba(0,122,255,0.15)";
            sctx.fillRect(x, blockY, barWidth, blockH);
            sctx.shadowBlur = 0;
            sctx.fillStyle = "rgba(255,255,255,0.08)";
            sctx.fillRect(x, blockY, barWidth, 1);
          }
        }
        sctx.shadowBlur = 0;
        sctx.strokeStyle = "rgba(0,0,0,0.04)";
        sctx.lineWidth = 1;
        sctx.setLineDash([2, 4]);
        sctx.beginPath();
        sctx.moveTo(0, h - bottomOffset);
        sctx.lineTo(w, h - bottomOffset);
        sctx.stroke();
        sctx.setLineDash([]);
      }
      function startVisualization() {
        if (animId) cancelAnimationFrame(animId);
        var loop = function () {
          if (!isPlaying.value || !analyser) { animId = null; return; }
          drawSpectrum();
          animId = requestAnimationFrame(loop);
        };
        loop();
      }
      function stopVisualization() {
        if (animId) { cancelAnimationFrame(animId); animId = null; }
      }

      /* ---------- Web Audio：把 <audio> 接进分析器（参考页 initAudioContext） ---------- */
      function initAudioContext() {
        var a = audioEl.value;
        if (!a) return Promise.resolve(false);
        if (analyser) {
          if (audioContext.state === "suspended") audioContext.resume().catch(function () {});
          return Promise.resolve(true);
        }
        try {
          audioContext = new (window.AudioContext || window.webkitAudioContext)();
          sourceNode = audioContext.createMediaElementSource(a);
          analyser = audioContext.createAnalyser();
          analyser.fftSize = 1024;
          analyser.smoothingTimeConstant = 0.8;
          sourceNode.connect(analyser);
          analyser.connect(audioContext.destination);
          dataArray = new Uint8Array(analyser.frequencyBinCount);
          blockPositions = new Float32Array(analyser.frequencyBinCount);
          return Promise.resolve(true);
        } catch (error) {
          analyser = null;
          showToast("浏览器没让接分析器，频谱不可用", 3000);
          return Promise.resolve(false);
        }
      }

      /* ---------- 播放控制 ---------- */
      function play() {
        var a = audioEl.value;
        if (!a || !a.src) return;
        return initAudioContext().then(function () {
          if (audioContext && audioContext.state === "suspended") return audioContext.resume().catch(function () {});
        }).then(function () {
          return a.play();
        }).catch(function () {
          showToast("无法播放，请检查文件");
        });
      }
      function togglePlay() {
        var a = audioEl.value;
        if (!a || !a.src) { showToast(loading.value ? "正在读取文件…" : "请先加载歌曲"); return; }
        if (isPlaying.value) { a.pause(); return; }
        play();
      }
      function prevSong() {
        var a = audioEl.value;
        if (!a) return;
        if (a.currentTime > 2) { a.currentTime = 0; return; }   // 参考页：>2 秒先回到开头
        showToast("已经是第一首");                                // 单文件：没有上一首可切
      }
      function nextSong() {
        if (!audioEl.value) return;
        showToast("已经是最后一首");                              // 单文件：没有下一首可切
      }
      function toggleFullscreen() {
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen().catch(function () {});
        } else if (document.exitFullscreen) {
          document.exitFullscreen().catch(function () {});
        }
      }
      /** 放完就停（去掉了循环设置，不再自动重放）。 */
      function handleTrackEnd() {
        isPlaying.value = false;
      }

      /* ---------- 频谱交互 ---------- */
      function onSpectrumClick(e) {
        if (loading.value || (e && e.button !== 0)) return;
        spectrumEnabled.value = !spectrumEnabled.value;
        if (spectrumEnabled.value && isPlaying.value) startVisualization();
        else { stopVisualization(); drawSpectrum(); }
        showToast(spectrumEnabled.value ? "频谱已开启" : "频谱已关闭", 1200);
      }
      function onSpectrumAux(e) {
        e.preventDefault();
        toggleFullscreen();
      }

      /* ---------- 进度条 ---------- */
      function pctOf(time) {
        var a = audioEl.value;
        if (!a || !a.duration) return 0;
        return Math.min((time / a.duration) * 100, 100);
      }
      function updateProgressFromMouse(e) {
        var track = progressTrack.value, a = audioEl.value;
        if (!track || !a || !a.duration) return;
        var rect = track.getBoundingClientRect();
        var x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
        progressPct.value = x * 100;
        curText.value = formatTime(x * a.duration);
      }
      function onProgressDown(e) {
        var a = audioEl.value;
        if (!a || !a.duration) return;
        e.preventDefault();
        isDraggingProgress = true;
        updateProgressFromMouse(e);
        var onMove = function (ev) { updateProgressFromMouse(ev); };
        var onUp = function () {
          isDraggingProgress = false;
          if (a.duration) a.currentTime = (progressPct.value / 100) * a.duration;
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      }

      /* ---------- 音量交互（角度） ---------- */
      function getAngleFromMouse(e) {
        var box = volCtl.value;
        if (!box) return 0;
        var rect = box.getBoundingClientRect();
        var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
        var clientX, clientY;
        if (e.touches) { clientX = e.touches[0].clientX; clientY = e.touches[0].clientY; }
        else { clientX = e.clientX; clientY = e.clientY; }
        var deg = (Math.atan2(clientY - cy, clientX - cx) * 180 / Math.PI + 90 + 360) % 360;
        return deg;
      }
      function onVolMove(e) {
        if (!isDraggingVolume) return;
        e.preventDefault();
        var deg = getAngleFromMouse(e);
        if (lastDeg !== undefined) {
          var diff = deg - lastDeg;
          if (diff > 180) diff -= 360;
          if (diff < -180) diff += 360;
          if (Math.abs(diff) > 2) isClick = false;
        }
        lastDeg = deg;
        volume.value = Math.min(1, Math.max(0, 1 - deg / 360));
        if (isMuted.value && volume.value > 0) isMuted.value = false;
        updateVolumeRing();
        if (!isClick) showHud(Math.round(volume.value * 100));
      }
      function onVolEnd() {
        isDraggingVolume = false;
        document.removeEventListener("mousemove", onVolMove);
        document.removeEventListener("mouseup", onVolEnd);
        document.removeEventListener("touchmove", onVolMove);
        document.removeEventListener("touchend", onVolEnd);
        lastDeg = undefined;
        if (isClick) {
          isMuted.value = !isMuted.value;
          if (!isMuted.value && volume.value === 0) volume.value = 0.5;
          updateVolumeRing();
          showToast(isMuted.value ? "已静音" : "已取消静音", 1000);
          showHud(Math.round(volume.value * 100));
        }
        isClick = false;
      }
      function onVolDown(e) {
        e.preventDefault();
        isDraggingVolume = true;
        isClick = true;
        lastDeg = getAngleFromMouse(e);
        document.addEventListener("mousemove", onVolMove);
        document.addEventListener("mouseup", onVolEnd);
        document.addEventListener("touchmove", onVolMove, { passive: false });
        document.addEventListener("touchend", onVolEnd, { passive: false });
      }
      function onVolWheel(e) {
        e.preventDefault();
        e.stopPropagation();
        volume.value = Math.min(1, Math.max(0, volume.value + (e.deltaY > 0 ? -0.05 : 0.05)));
        if (isMuted.value && volume.value > 0) isMuted.value = false;
        updateVolumeRing();
        showHud(Math.round(volume.value * 100));
      }

      /* ---------- 键盘（与参考页同一套） ---------- */
      function onKey(e) {
        var t = e.target, tag = t && t.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || (t && t.isContentEditable)) return;
        var accel = e.metaKey || e.ctrlKey;
        if (e.code === "Space") { e.preventDefault(); togglePlay(); return; }
        if (e.code === "ArrowRight" && accel) { e.preventDefault(); nextSong(); return; }
        if (e.code === "ArrowLeft" && accel) { e.preventDefault(); prevSong(); return; }
        if (e.code === "ArrowUp" && accel) {
          e.preventDefault();
          volume.value = Math.min(1, volume.value + 0.05);
          if (isMuted.value) isMuted.value = false;
          updateVolumeRing();
          showHud(Math.round(volume.value * 100));
          return;
        }
        if (e.code === "ArrowDown" && accel) {
          e.preventDefault();
          volume.value = Math.max(0, volume.value - 0.05);
          if (volume.value === 0) isMuted.value = true;
          updateVolumeRing();
          showHud(Math.round(volume.value * 100));
        }
      }

      /* ---------- 读取文件 + 元数据 ---------- */
      /** 取消整包读取：直接切到流式播放（桥是"整包读再回"，超大文件读不动时也用这条路）。 */
      function cancelLoad() {
        canceled = true;
        if (job && job.abort) { try { job.abort(); } catch (error) {} }
      }
      function applyMeta(m) {
        if (!m) return;
        if (m.title) title.value = cleanTitle(m.title) || title.value;
        if (m.artist) artist.value = m.artist;
        if (m.album) album.value = m.album;
        if (m.cover && m.cover.bytes && m.cover.bytes.length) {
          coverObjectUrl = URL.createObjectURL(new Blob([m.cover.bytes], { type: m.cover.mime || "image/jpeg" }));
          coverUrl.value = coverObjectUrl;
        }
      }

      onMounted(function () {
        var a = audioEl.value;
        if (!a) return;
        window.addEventListener("keydown", onKey);
        drawVolumeRing();
        if (a) a.volume = volume.value;

        a.addEventListener("play", function () {
          isPlaying.value = true;
          if (spectrumEnabled.value) startVisualization();
        });
        a.addEventListener("pause", function () { isPlaying.value = false; stopVisualization(); });
        a.addEventListener("ended", handleTrackEnd);
        a.addEventListener("timeupdate", function () {
          if (!isDraggingProgress) {
            curText.value = formatTime(a.currentTime);
            progressPct.value = pctOf(a.currentTime);
          }
        });
        a.addEventListener("loadedmetadata", function () { durText.value = formatTime(a.duration); });
        a.addEventListener("durationchange", function () { durText.value = formatTime(a.duration); });
        a.addEventListener("error", function () { if (a.src) showToast("无法播放，请检查文件"); });

        job = FV.loadBlob(FV.boot.rawUrl, function (state) { loadState.value = Object.assign({}, state); });
        job.promise.then(function (blob) {
          if (disposed) return;
          audioUrl = URL.createObjectURL(blob);
          a.src = audioUrl;
          a.load();
          loading.value = false;
          return FV.parseAudioMeta(blob).then(function (m) { if (!disposed) applyMeta(m); });
        }, function () {
          if (disposed) return;
          // 桥是"整包读取再回"的，超大文件会失败：退回直接流式，界面布局不动
          a.src = FV.boot.rawUrl;
          a.load();
          loading.value = false;
          showToast(canceled ? "改为边下边播" : "整包读取失败，改为边下边播", 3000);
        });
      });

      onBeforeUnmount(function () {
        disposed = true;
        window.removeEventListener("keydown", onKey);
        document.removeEventListener("mousemove", onVolMove);
        document.removeEventListener("mouseup", onVolEnd);
        document.removeEventListener("touchmove", onVolMove);
        document.removeEventListener("touchend", onVolEnd);
        stopVisualization();
        clearTimeout(toastTimer);
        clearTimeout(hudTimer);
        if (job && job.abort) { try { job.abort(); } catch (error) {} }
        var a = audioEl.value;
        if (a) { try { a.pause(); a.removeAttribute("src"); a.load(); } catch (error) {} }
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        if (coverObjectUrl) URL.revokeObjectURL(coverObjectUrl);
        if (audioContext) { try { audioContext.close(); } catch (error) {} }
      });

      return {
        // 状态
        isPlaying: isPlaying, volume: volume, isMuted: isMuted,
        spectrumEnabled: spectrumEnabled,
        title: title, artist: artist, album: album, coverUrl: coverUrl,
        toastMsg: toastMsg, toastShow: toastShow, hudPct: hudPct, hudShow: hudShow,
        curText: curText, durText: durText, progressPct: progressPct,
        loading: loading, loadState: loadState,
        // DOM
        audioEl: audioEl, specCanvas: specCanvas, volCtl: volCtl, volCanvas: volCanvas, progressTrack: progressTrack,
        // 动作
        togglePlay: togglePlay, prevSong: prevSong, nextSong: nextSong,
        toggleFullscreen: toggleFullscreen,
        onSpectrumClick: onSpectrumClick, onSpectrumAux: onSpectrumAux,
        onProgressDown: onProgressDown, onVolDown: onVolDown, onVolWheel: onVolWheel,
        cancelLoad: cancelLoad, showToast: showToast,
        // 计算
        mutedIcon: computed(function () { return (isMuted.value || volume.value === 0) ? "volume-mute" : "volume-up"; }),
        playIcon: computed(function () { return isPlaying.value ? "pause" : "play"; })
      };
    },
    methods: { fa: function (name) { return FV.faIcon(name); } },
    template: [
      '<div class="mp-wrap"><div class="mp">',
      /* 标题栏：只留红绿灯 */
      '<div class="titlebar"><div class="dots">',
      '<span class="dot-red"></span><span class="dot-yellow"></span><span class="dot-green"></span>',
      "</div></div>",
      '<div class="body"><div class="main">',
      '<div class="main-title"><i v-html="fa(\'music\')"></i> 音乐播放器</div>',
      /* Toast + 音量 HUD */
      '<div class="modal-container">',
      '<div class="toast-right" :class="{ show: toastShow }">{{ toastMsg }}</div>',
      '<div class="vol-hud-right" :class="{ show: hudShow }">',
      '<span class="hud-icon"><i v-html="fa(mutedIcon)"></i></span>',
      '<span class="hud-percent">{{ hudPct }}%</span>',
      "</div></div>",
      /* 顶部元数据 */
      '<div class="top-row">',
      '<div class="album-art">',
      '<img v-if="coverUrl" :src="coverUrl" alt="封面">',
      '<span v-else class="fallback"><i v-html="fa(\'music\')"></i></span>',
      "</div>",
      '<div class="track-meta">',
      '<div class="title">{{ title }}</div>',
      '<div class="artist">{{ artist }}</div>',
      '<div class="album">{{ album }}</div>',
      "</div></div>",
      /* 频谱 */
      '<div class="spectrum-wrap" @click="onSpectrumClick" @auxclick="onSpectrumAux">',
      '<canvas ref="specCanvas"></canvas>',
      '<div class="spectrum-label"><i v-html="fa(\'chart-bar\')"></i> 频谱</div>',
      '<div class="spectrum-toggle-hint"><i v-html="fa(\'toggle-off\')"></i> 点击切换</div>',
      '<div class="load-overlay" v-if="loading">',
      '<loading-panel variant="card" icon="audio" title="正在读取音频…" :state="loadState" :cancel="cancelLoad" cancel-label="先流式播放"></loading-panel>',
      "</div></div>",
      /* 控制栏 */
      '<div class="controls">',
      '<div class="progress-row">',
      '<span class="time current">{{ curText }}</span>',
      '<div class="progress-track" ref="progressTrack" @mousedown="onProgressDown">',
      '<div class="progress-fill" :style="{ width: progressPct + \'%\' }"></div>',
      "</div>",
      '<span class="time duration">{{ durText }}</span>',
      "</div>",
      '<div class="btn-row">',
      /* 左组与右组镜像对称：[全屏][上一首] ▶ [下一首][音量环] */
      '<div class="btn-group left">',
      '<button title="全屏" @click="toggleFullscreen" v-html="fa(\'expand\')"></button>',
      '<button title="上一首" @click="prevSong" v-html="fa(\'backward\')"></button>',
      "</div>",
      '<button class="play-btn" title="播放/暂停 (Space)" @click="togglePlay" v-html="fa(playIcon)"></button>',
      '<div class="btn-group right">',
      '<button title="下一首" @click="nextSong" v-html="fa(\'forward\')"></button>',
      '<div class="volume-control" ref="volCtl" @mousedown="onVolDown" @touchstart="onVolDown" @wheel="onVolWheel">',
      '<canvas ref="volCanvas" width="48" height="48"></canvas>',
      '<span class="vol-icon" :class="{ muted: isMuted || volume === 0 }"><i v-html="fa(mutedIcon)"></i></span>',
      "</div></div></div></div>",
      "</div></div></div>",
      '<audio ref="audioEl" preload="auto" style="display:none"></audio>',
      "</div>"
    ].join("")
  };

  /* ---------------------------------------------------------------- 注册 */
  var AUD = ["mp3", "wav", "ogg", "oga", "m4a", "aac", "flac", "opus", "weba"];
  FV.registry.register({
    id: "audio", label: "音频", kind: "media", order: 100,
    match: function (ctx) { return AUD.indexOf(ctx.ext) >= 0 && !ctx.text; },
    view: AudioView
  });
})();
