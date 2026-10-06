/* comp-drawer.js —— 详情（`V-293` 照参考稿改成**居中大弹窗**）
   ============================================================================
   参考稿那个弹窗是**两块**：
     · 左（320px）：身份与操作中枢 —— 大图标 + 名字 + 标签，底部"状态开关 + 动作按钮"；
     · 右：数据与内容 —— 数据概览 / 功能描述 / 折叠说明 / 工作目录 / 文件清单。
   底色 / 面板 / 开关都是这一套令牌（鼠尾草绿 + 赤陶橙）。
   ★ 探针契约（`tools\技能界面探针.py`）一个字没动：根节点仍是 `.drawer` 且带
     `role="dialog"` + `aria-modal="true"`，旁边有 `.scrim`，里面有 `.kv`、
     `#d-doc`（看它自己的说明书）、`#d-x`（✕ 关）；点 `#d-x` 要真能拆掉。
   ★ `#d-doc` 挂在"折叠说明"的标题那一行，点它 = 展开 / 收起它自己的 `AGENT.md`。
   ★ 参考稿的 `instructions` 是假数据 ⇒ 这里接**真东西**：`doc {id}`（它目录里的 AGENT.md）。
   ========================================================================== */
(function () {
  'use strict';

  var I = window.SKILL_ICONS;

  /* 后缀 → highlight.js 的语言名（跟主界面 `system/ui/js/core.js` 的 `EXT` 一个口径，
     只留"能上色"的那些；`pkg.json` / 无后缀的按 json / plaintext 走）。 */
  var EXT_LANG = {
    py: 'python', pyw: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript',
    ts: 'typescript', jsx: 'javascript', tsx: 'typescript', json: 'json', jsonc: 'json',
    md: 'markdown', markdown: 'markdown', html: 'xml', htm: 'xml', xml: 'xml', svg: 'xml',
    css: 'css', scss: 'scss', less: 'less', go: 'go', rs: 'rust', c: 'c', h: 'c',
    cpp: 'cpp', cc: 'cpp', hpp: 'cpp', java: 'java', cs: 'csharp', php: 'php', rb: 'ruby',
    lua: 'lua', sql: 'sql', sh: 'bash', bash: 'bash', bat: 'dos', cmd: 'dos',
    ps1: 'powershell', psm1: 'powershell', yml: 'yaml', yaml: 'yaml', toml: 'ini',
    ini: 'ini', cfg: 'ini', conf: 'ini', txt: 'plaintext', log: 'plaintext',
  };
  var HL_MAX = 400000;                 // 超过这么多字符就不上色（跟主界面一样的闸）

  window.SKILL_COMPONENTS = window.SKILL_COMPONENTS || {};
  window.SKILL_COMPONENTS.SkillDrawer = {
    name: 'skill-drawer',
    props: {
      it: { type: Object, required: true },
      closing: { type: Boolean, default: false },
      store: { type: Object, required: true },
    },
    emits: ['close', 'act', 'toggle-doc', 'open-file', 'copy', 'copy-file', 'gone',
            'reload-runs', 'clear-runs', 'send-input', 'stop-run'],
    // `openLog` = 运行日志里展开了哪一条（右侧当前选项卡 `store.rtab` 在根组件的 store 上）
    data: function () { return { openLog: -1 }; },
    computed: {
      /* `V-301`：运行面板的数据（都挂在根组件的 store 上，跟着当前技能变） */
      con: function () { return this.store.console || {}; },
      runs: function () { return this.store.runs || []; },
      broken: function () { return !!(this.it.problems && this.it.problems.length); },
      pending: function () { return !this.broken && !this.it.allowed; },
      /* 允许 / 撤销这颗只在"它还能被 AI 调"的时候给（出厂的、写坏的都轮不到它） */
      canAllow: function () { return this.it.layer !== 'system' && !this.broken; },
      canPromote: function () { return this.it.layer === 'user'; },
      canRemove: function () { return this.it.layer === 'user' && this.it.kind !== 'pkg'; },
      statusText: function () {
        if (this.broken) return '要修一下';
        return this.it.allowed ? '已启用' : '等待允许';
      },
      /* 标签（和卡片同一套 .tag）：一眼看清"能不能用 / 哪来的 / 多危险 / 要什么参数"。
         图标一律**实心**（`ph-fill` 调子）；`code` 没有实心那份，退回细线。 */
      tags: function () {
        var t = [], it = this.it;
        if (this.broken) t.push({ k: 's', label: '进不了工具表', icon: 'warn', tone: 'bad', solid: 1 });
        else if (this.pending) t.push({ k: 's', label: '还没允许', icon: 'info', tone: 'warn', solid: 1 });
        else t.push({ k: 's', label: 'AI 可以用它', icon: 'robot', tone: 'ok', solid: 1 });
        if (it.origin === 'seed') t.push({ k: 'o', label: '出厂样例', icon: 'box', tone: 'violet', solid: 1 });
        if (it.risk) t.push({ k: 'r', label: '风险 ' + it.risk, icon: 'shield', tone: 'plain', solid: 1 });
        (it.params || []).forEach(function (p) {
          t.push({ k: 'p' + p, label: p, icon: 'code', tone: 'sky' });
        });
        return t;
      },
      tip: function () {
        return this.it.why || '这只技能没写「为什么造它」—— 它自己的 pkg.json 里 ai.why 是空的。';
      },
      tipMuted: function () { return !this.it.why; },
      files: function () { return this.it.files || []; },
      /* 正在看的那份正文（行内）—— 高亮成 HTML + 行号 */
      openHtml: function () { return this.renderCode(this.store.openRel); },
      openLines: function () { return this.renderLines(this.store.openRel); },
      /* 「放大看」那个模态框里的同一份内容 */
      popHtml: function () { return this.renderCode(this.store.codeMax); },
      popLines: function () { return this.renderLines(this.store.codeMax); },
      popName: function () { return this.store.codeMax; },
    },
    watch: {
      /* 换一只技能 = 把就地展开的文件收起来。
         ★「详细说明」的展开状态由根组件统一管（默认展开），别在这儿把它关掉。 */
      'it.id': function () {
        this.store.openRel = '';
        this.openLog = -1;                               // 换一只技能 ⇒ 日志展开收起来
      },
    },
    methods: {
      ico: I.of,
      fil: I.fill,
      /* 标签图标：实心那份没有的名字（比如 code）退回细线。
         ★ 这是个**方法**（模板里带参数调它）—— 别挪进 `computed`（`V-291` 踩过：
           `tagIcon is not a function`，整块弹窗都画不出来，prod 版还把错误吞掉）。 */
      tagIcon: function (t) {
        return t.solid ? I.fill(t.icon) : I.of(t.icon);
      },
      sizeH: function (n) {
        n = Number(n || 0);
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1048576).toFixed(1) + ' MB';
      },
      /* 文件类型 → 图标 + 颜色（md 蓝 / svg 紫 / json 琥珀 / py 翠绿） */
      fileIcon: function (name) {
        var n = String(name || '').toLowerCase();
        if (/\.md$/.test(n)) return { d: 'fileText', c: 'f-md' };
        if (/\.svg$/.test(n)) return { d: 'image', c: 'f-svg' };
        if (/\.jsonc?$/.test(n)) return { d: 'braces', c: 'f-json' };
        if (/\.(py|pyw)$/.test(n)) return { d: 'fileCode', c: 'f-py' };
        return { d: 'file', c: 'f-other' };
      },
      /* 这个文件该按什么语言上色（认不出来就返回空 = 不上色） */
      langOf: function (rel) {
        var n = String(rel || '').toLowerCase();
        if (n === 'pkg.json') return 'json';
        var m = /\.([a-z0-9]+)$/.exec(n);
        return m ? (EXT_LANG[m[1]] || '') : '';
      },
      /* 交给 highlight.js 上色；没装 / 语言认不出 / 太大 ⇒ 退回转义后的纯文本 */
      highlight: function (text, lang) {
        text = String(text == null ? '' : text);
        try {
          if (window.hljs && lang && lang !== 'plaintext'
              && text.length <= HL_MAX && hljs.getLanguage(lang)) {
            return hljs.highlight(text, { language: lang, ignoreIllegals: true }).value;
          }
        } catch (e) { /* 上色失败就退回纯文本 */ }
        return this.escapeHtml(text);
      },
      escapeHtml: function (s) {
        return String(s == null ? '' : s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      },
      /* 一份正文 → 高亮 HTML（认不出语言 / 没装 hljs / 太大 ⇒ 转义后的纯文本） */
      renderCode: function (rel) {
        if (!rel) return '';
        var text = this.store.fileTextMap[rel];
        if (text === undefined) return this.escapeHtml('（正在读…）');
        return this.highlight(text, this.langOf(rel));
      },
      /* 一份正文 → 左边那串行号（`\n` 连起来，交给 `<pre>` 按行排） */
      renderLines: function (rel) {
        if (!rel) return '';
        var text = this.store.fileTextMap[rel];
        if (text === undefined) return '1';
        var n = text.length ? text.split('\n').length : 1;
        var out = [];
        for (var i = 1; i <= n; i++) out.push(i);
        return out.join('\n');
      },
      /* `V-302`：命令行那个输入框 —— 把这一行发给正在跑的技能，然后清空 */
      sendLine: function (ev, force) {
        var inp = this.$refs.rin;                         // 组件是**碎片模板**，`$el` 只到第一块，用 ref
        if (!inp) return;
        var v = inp.value;
        if (!v && !force) return;
        this.$emit('send-input', v);
        inp.value = '';
      },
      /* `V-301`：把一段文本里的路径变成可点开链接（`paths.js`）—— 复制 / 输出里到处是路径 */
      paths: function (t) {
        return (window.SKILL_PATHS && window.SKILL_PATHS.linkify)
          ? window.SKILL_PATHS.linkify(t) : String(t == null ? '' : t);
      },
      /* 放大看 / 收起（那颗最大化按钮） */
      maxCode: function (rel) { this.store.codeMax = rel; },
      closeCode: function () { this.store.codeMax = ''; },
      act: function (what) {
        this.$emit('act', what);
      },
    },
    template: [
      '<div class="scrim" @click="$emit(\'close\')"></div>',
      '<aside class="drawer modal-content" :class="{ closing: closing }" role="dialog" aria-modal="true"',
      '       :aria-label="it.name">',
      '  <button type="button" class="btn-close" id="d-x" title="关闭（Esc）"',
      '          aria-label="关闭" @click="$emit(\'close\')" v-html="ico(\'x\')"></button>',

      /* ---- 左：身份与操作中枢 ---- */
      '  <div class="detail-left">',
      '    <div class="detail-header-wrap rise">',
      '      <div class="detail-icon-wrap">',
      '        <span v-if="it.icon_svg" v-html="it.icon_svg"></span>',
      '        <span v-else v-html="ico(\'spark\')"></span>',
      '      </div>',
      '      <h2 class="detail-title">{{ it.name }}</h2>',
      '      <p class="detail-id">{{ it.id }}</p>',
      '      <div class="tag-list">',
      '        <span v-for="t in tags" :key="t.k" class="tag" :class="t.tone">',
      '          <span class="tag-ic" v-html="tagIcon(t)"></span>{{ t.label }}</span>',
      '      </div>',
      '    </div>',

      '    <div class="detail-footer rise" style="animation-delay:70ms">',
      '      <div class="status-box" :class="{ \'is-on\': it.allowed }">',
      '        <div>',
      '          <span class="status-label">技能状态</span>',
      '          <span class="status-value">{{ statusText }}</span>',
      '        </div>',
      '        <div v-if="canAllow" class="toggle-switch" :class="{ active: it.allowed }"',
      '             :title="it.allowed ? \'点击撤销允许\' : \'点击允许\'" @click="act(\'allow\')"></div>',
      '        <span v-else class="toggle-note" title="这只技能改不了" v-html="ico(\'lock\')"></span>',
      '      </div>',

      '      <div class="action-buttons">',
      '        <button v-if="it.allowed" type="button" class="btn btn-run" id="d-run" @click="act(\'run\')">',
      '          <span v-html="fil(\'play\')"></span>运行测试</button>',
      '        <button v-if="canPromote" type="button" class="btn btn-ghost" @click="act(\'promote\')">',
      '          <span v-html="ico(\'puzzle\')"></span>转换为插件</button>',
      '        <button v-if="canRemove" type="button" class="btn btn-danger" @click="act(\'rm\')">',
      '          <span v-html="ico(\'trash\')"></span>删除此技能</button>',
      '      </div>',
      '    </div>',
      '  </div>',

      /* ---- 右：数据与内容 ---- */
      '  <div class="detail-right">',
      /* ★ `V-301`：右侧改成**三个平级选项卡**（数据概览 / 命令行 / 运行日志），各自占满右侧窗口。
         数据是常驻的（`v-show`，切来切去不丢），默认落在「数据概览」。 */
      '    <div class="right-tabs">',
      '      <button type="button" :class="{ on: store.rtab === \'overview\' }" @click="store.rtab = \'overview\'">数据概览</button>',
      '      <button type="button" :class="{ on: store.rtab === \'console\' }" @click="store.rtab = \'console\'">命令行</button>',
      '      <button type="button" :class="{ on: store.rtab === \'log\' }" @click="store.rtab = \'log\'">运行日志</button>',
      '    </div>',
      '    <div class="right-body">',
      '    <div class="rtab-pane scroll" v-show="store.rtab === \'overview\'">',
      '    <h3 class="section-title rise"><span v-html="ico(\'chartLine\')"></span>数据概览</h3>',
      /* ★ `.kv` 是探针的契约（`document.querySelector(".drawer .kv")`）—— 挂在这行统计上 */
      '    <div class="stats-row kv rise" style="animation-delay:40ms">',
      '      <div class="stat-item">',
      '        <span class="stat-label">调用次数</span>',
      '        <span class="stat-value huge">{{ it.calls || 0 }}</span>',
      '      </div>',
      '      <div class="stat-item">',
      '        <span class="stat-label">入口文件</span>',
      '        <span class="stat-value">{{ it.entry || \'—\' }}</span>',
      '      </div>',
      '      <div class="stat-item">',
      '        <span class="stat-label">创建时间</span>',
      '        <span class="stat-value">{{ it.created || \'—\' }}</span>',
      '      </div>',
      '      <div class="stat-item">',
      '        <span class="stat-label">最近调用时间</span>',
      '        <span class="stat-value">{{ it.last_called || \'—\' }}</span>',
      '      </div>',
      '    </div>',

      '    <div class="notice rise" v-if="broken" style="animation-delay:60ms">',
      '      <span v-html="ico(\'warn\')"></span>',
      '      <p style="margin:0"><b>它进不了 AI 的工具表。</b><br>{{ it.problems.join(\'；\') }}</p>',
      '    </div>',

      '    <h3 class="section-title rise" style="animation-delay:80ms"><span v-html="ico(\'quote\')"></span>功能描述</h3>',
      '    <p class="desc-box rise" style="animation-delay:80ms">{{ it.desc || it.why || \'（这只技能没写说明）\' }}</p>',

      '    <div class="tip rise" style="animation-delay:120ms" :class="{ muted: tipMuted }">',
      '      <span v-html="fil(\'info\')"></span>',
      '      <p style="margin:0"><b>AI 行为指引 · </b>{{ tip }}</p>',
      '    </div>',

      '    <h3 class="section-title rise" style="animation-delay:200ms"><span v-html="ico(\'folder\')"></span>工作目录</h3>',
      '    <div class="dir-row rise" style="animation-delay:200ms">',
      '      <span :title="it.dir">{{ it.dir }}</span>',
      '      <div class="dir-actions">',
      '        <button type="button" class="icon-btn" title="复制路径" @click="$emit(\'copy\')" v-html="ico(\'copy\')"></button>',
      '        <button type="button" class="icon-btn" title="在资源管理器中打开" @click="act(\'open\')" v-html="ico(\'externalLink\')"></button>',
      '      </div>',
      '    </div>',

      '    <h3 class="section-title rise" style="animation-delay:240ms"><span v-html="ico(\'fileCode\')"></span>包含的文件清单</h3>',
      '    <p class="hint rise" v-if="!files.length" style="animation-delay:240ms">（空目录）</p>',
      '    <div class="file-list rise" v-else style="animation-delay:240ms">',
      '      <div class="file-item" v-for="f in files" :key="f.rel">',
      '        <div class="file-head" :class="{ open: store.openRel === f.rel }">',
      '          <button type="button" class="file-name" :class="{ open: store.openRel === f.rel }"',
      '                  :title="store.openRel === f.rel ? \'收起\' : \'看一眼它写了什么\'"',
      '                  @click="$emit(\'open-file\', f.rel)">',
      '            <span :class="fileIcon(f.rel).c" v-html="fil(fileIcon(f.rel).d)"></span>',
      '            <span class="f-rel">{{ f.rel }}</span>',
      '            <span class="f-size">{{ sizeH(f.size) }}</span>',
      '            <span class="f-chev" v-html="ico(store.openRel === f.rel ? \'chevronUp\' : \'chevronDown\')"></span>',
      '          </button>',
      '          <button type="button" class="file-copy" title="复制这个文件的内容"',
      '                  aria-label="复制内容" @click.stop="$emit(\'copy-file\', f.rel)"',
      '                  v-html="ico(\'copy\')"></button>',
      '          <button type="button" class="file-copy file-max" title="放大看"',
      '                  aria-label="放大看" @click.stop="maxCode(f.rel)"',
      '                  v-html="ico(\'maximize\')"></button>',
      '        </div>',
      '        <transition name="slide-fade">',
      '          <div class="code-view" v-if="store.openRel === f.rel">',
      '            <pre class="code-gutter" aria-hidden="true">{{ openLines }}</pre>',
      '            <pre class="code-body"><code class="hljs" v-html="openHtml"></code></pre>',
      '          </div>',
      '        </transition>',
      '      </div>',
      '    </div>',

      /* 详细说明：放在最下面、默认展开。
         `#d-doc` 是这一块标题（探针按它判"有没有看说明"）。 */
      '    <div class="instruction-acc rise" style="animation-delay:280ms">',
      '      <div class="instruction-head" id="d-doc" @click="$emit(\'toggle-doc\')">',
      '        <span><span v-html="ico(\'book\')"></span>详细说明</span>',
      '        <span v-html="ico(store.openDoc ? \'chevronUp\' : \'chevronDown\')"></span>',
      '      </div>',
      '      <transition name="slide-fade">',
      '        <div class="instruction-body" v-show="store.openDoc">',
      '          <pre class="prose" v-if="store.docBusy">（正在读…）</pre>',
      '          <pre class="prose" v-else>{{ store.docText }}</pre>',
      '        </div>',
      '      </transition>',
      '    </div>',
      '    </div>',

      /* ---- 命令行（这次跑了什么 + 输出；整页占满右侧）---- */
      '    <div class="rtab-pane full" v-show="store.rtab === \'console\'">',
      '      <div class="run-panel">',
      '        <div class="run-head">',
      '          <h4><span v-html="ico(\'terminal\')"></span>命令行</h4>',
      '          <span class="run-sub" v-if="con.running">● 正在跑</span>',
      '          <span class="run-sub" v-else-if="con.code !== null && con.code !== undefined">退出码 {{ con.code }}</span>',
      '          <span style="flex:1"></span>',
      '          <button v-if="it.allowed && !con.running" type="button" class="icon-btn" title="再跑一次"',
      '                  @click="act(\'run\')" v-html="ico(\'play\')"></button>',
      '          <button v-if="con.running" type="button" class="icon-btn stop" title="停掉"',
      '                  @click="$emit(\'stop-run\')" v-html="ico(\'x\')"></button>',
      '        </div>',
      '        <div class="run-body mono">',
      '          <span v-if="!con.out && con.running" class="dim">正在跑… 输出会实时出现在这儿；它要是问了你什么，在下面输入后回车。</span>',
      '          <span v-else-if="!con.out" class="dim">点右上角「运行测试」跑一次，输出会显示在这儿。</span>',
      '          <pre class="run-out" v-html="paths(con.out || \'\')"></pre>',
      '        </div>',
      '        <div class="run-input">',
      '          <input ref="rin" class="rin" type="text" spellcheck="false" autocomplete="off"',
      '                 :disabled="!con.running"',
      '                 placeholder="输入一行、回车发给正在跑的技能（它一问就能答）"',
      '                 @keydown.enter.prevent="sendLine($event)">',
      '          <button type="button" class="icon-btn" :disabled="!con.running" title="发送"',
      '                  @click="sendLine($event, true)" v-html="ico(\'arrowRight\')"></button>',
      '        </div>',
      '      </div>',
      '    </div>',

      /* ---- 运行日志（历次记录，点开看输出；整页占满右侧）---- */
      '    <div class="rtab-pane full" v-show="store.rtab === \'log\'">',
      '      <div class="run-panel">',
      '        <div class="run-head">',
      '          <h4><span v-html="ico(\'clock\')"></span>运行日志</h4>',
      '          <span class="run-sub" v-if="runs.length">{{ runs.length }} 条</span>',
      '          <span style="flex:1"></span>',
      '          <button type="button" class="icon-btn" title="刷新日志"',
      '                  @click="$emit(\'reload-runs\')" v-html="ico(\'refresh\')"></button>',
      '          <button type="button" class="icon-btn" title="清空这只技能的日志"',
      '                  @click="$emit(\'clear-runs\')" v-html="ico(\'trash\')"></button>',
      '        </div>',
      '        <div class="run-body">',
      '          <p class="dim run-empty" v-if="!runs.length">还没有运行记录 —— 点「运行测试」跑一次就有了。</p>',
      '          <div v-else class="log-item" v-for="(r, i) in runs" :key="i" :class="{ bad: r.ok === false }">',
      '            <div class="log-line" @click="openLog = (openLog === i ? -1 : i)">',
      '              <span class="log-ico" v-html="ico(r.ok === false ? \'warn\' : \'check\')"></span>',
      '              <span class="log-at">{{ r.at || \'—\' }}</span>',
      '              <span class="log-code">退出 {{ r.code === null || r.code === undefined ? \'—\' : r.code }}</span>',
      '              <span class="log-dur" v-if="r.dur != null">{{ r.dur }}s</span>',
      '              <span class="log-chev" v-html="ico(openLog === i ? \'chevronUp\' : \'chevronDown\')"></span>',
      '            </div>',
      '            <div class="log-out mono" v-if="openLog === i">',
      '              <div class="dim" v-if="r.cmd">{{ r.cmd }}</div>',
      '              <pre v-if="r.out" v-html="paths(r.out)"></pre>',
      '              <pre class="run-err" v-if="r.err" v-html="paths(r.err)"></pre>',
      '              <div class="dim" v-if="!r.out && !r.err">（没有输出）</div>',
      '            </div>',
      '          </div>',
      '        </div>',
      '      </div>',
      '    </div>',
      '    </div>',
      '  </div>',
      '</aside>',

      /* ---- 放大看：盖在最上面的一层大代码窗（点遮罩 / Esc / ✕ 关） ---- */
      '<div class="code-pop" v-if="store.codeMax">',
      '  <div class="scrim" @click="closeCode"></div>',
      '  <div class="code-pop-card">',
      '    <div class="code-pop-top">',
      '      <span class="code-pop-name">{{ popName }}</span>',
      '      <button type="button" class="icon-btn" title="复制内容" aria-label="复制内容"',
      '              @click="$emit(\'copy-file\', store.codeMax)" v-html="ico(\'copy\')"></button>',
      '      <button type="button" class="icon-btn" title="关闭（Esc）" aria-label="关闭"',
      '              @click="closeCode" v-html="ico(\'x\')"></button>',
      '    </div>',
      '    <div class="code-view big">',
      '      <pre class="code-gutter" aria-hidden="true">{{ popLines }}</pre>',
      '      <pre class="code-body"><code class="hljs" v-html="popHtml"></code></pre>',
      '    </div>',
      '  </div>',
      '</div>',
    ].join('\n'),
  };
})();
