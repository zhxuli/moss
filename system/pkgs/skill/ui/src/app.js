/* app.js —— 技能管理器 · 前端（Vue 3，根组件）
   ============================================================================
   一句话：**墙上一个方块 = 一只技能**，点开从右边滑出详情；管理动作只有三处
   （允许 / 撤销、转为插件、删除），其余都收进「⋯」和折叠区里。
   ★★ 跟后端说话只有一条路：`SKILL_API.*`（见 `src/api.js`）。
   ★★ 数据是后端算好的（`allowed` / `problems` / `origin`），界面**不自己重算**。
   ★★ 启动那一段是**踩过四次坑才对的**（`V-283` / `V-285`~`V-287` / `V-289`）——
      底下「启动」那段注释别删，它记的是"为什么不能只挂一句 `on('ready')`"、
      "为什么必须等 DOM"、"为什么挂载得上锁"。
   ★★ `V-292` 顶栏重画：**撤掉那个永远摆着的分段控件**（只有一个「全部技能」选项、
      点了也没别的，纯占地方），换成一颗**只在真有待处理时才出现**的开关；
      顺手补上了模板一直在叫、代码里却没有的 `retry`（原来点刷新会报错）。
   ========================================================================== */
(function () {
  'use strict';

  var I = window.SKILL_ICONS;
  var C = window.SKILL_COMPONENTS;

  /* ---------------------------------------------------------------- 全局小状态
     抽屉 / 弹层 / 提示条 / 就地展开的那点东西 —— 都是"看着的样子"，不是业务数据。
     根组件和子组件共用这一份（Vue 3 的 reactive，改哪儿哪儿跟着重画）。 */
  var store = Vue.reactive({
    openId: '',          // 抽屉里正开着哪一只
    openDoc: false,      // 抽屉里"它自己的说明书"展开了没
    docBusy: false,
    docText: '',
    openRel: '',         // 抽屉里展开了哪个文件的正文
    codeMax: '',         // 正在"放大看"的文件（'' = 没放大）—— 那颗最大化按钮
    fileTextMap: {},     // rel -> 正文（读过的缓存；没读过的键不存在）
    fileText: function (rel) {
      if (!rel) return '';
      var t = this.fileTextMap[rel];
      return t === undefined ? '（正在读…）' : t;
    },
    /* ★ `V-301`/`V-302`：右侧三个选项卡 + 运行那两块。
       rtab：当前选项卡；console：这次运行的实时输出（交互式，边跑边出）；
       runId：交互式运行的 id（'' = 没在跑）；runs：从宿主日志读回来的历次记录（当前技能）。 */
    rtab: 'overview',
    runId: '',
    console: { busy: false, running: false, at: '', code: null, dur: null, cmd: '', out: '', err: '', text: '' },
    runs: [],
    runsBusy: false,
  });

  var LOAD_TIMEOUT = 4000;    // 一次 list 最多等这么久（桥不回不能把页面挂死）
  var RETRY_MAX = 20;         // 连着这么多次还不成才把话说死（每次隔 700ms）

  var app = Vue.createApp({
    components: {
      SkillTile: C.SkillTile,
      SkillDrawer: C.SkillDrawer,
      ConfirmSheet: C.ConfirmSheet,
      SkillToasts: C.SkillToasts,
    },

    data: function () {
      return {
        store: store,
        data: null,          // 后端 list 回来的那份
        loading: true,
        loaded: false,       // ★ 只有 list **成功**过才是 true（失败不算，失败了还要重试）
        tries: 0,            // 连续失败次数（成功清零）
        tried: false,        // 有没有真把 list 发出去过（区分「桥没出现」和「调了没回」）
        why: '',             // 起不来时那句原因（给用户看，不是给日志看）
        got: '',             // 原样保留后端原话（"读不出来"那一段用）
        query: '',
        filt: 'all',         // 'all' | 'todo'
        drawer: false,       // 弹窗在不在场
        drawerClosing: false,
        sheet: null,
        sheetClosing: false,
        toasts: [],
        toastSeq: 0,
      };
    },

    computed: {
      skills: function () { return (this.data && this.data.skills) || []; },
      broken: function () { return (this.data && this.data.broken) || []; },
      /* 写坏了的那些后端也放在 skills 里（带 problems），但万一只给了 broken 也别漏掉。
         ★ 按 id 去重 —— 两处都有的技能不能在墙上出现两格。 */
      all: function () {
        var out = [], seen = {};
        this.skills.concat(this.broken).forEach(function (w) {
          if (!w || !w.id || seen[w.id]) return;
          seen[w.id] = 1;
          out.push(w);
        });
        return out;
      },
      nPending: function () {
        return this.all.filter(function (w) {
          return !(w.problems || []).length && !w.allowed;
        }).length;
      },
      nBroken: function () {
        return this.all.filter(function (w) { return (w.problems || []).length; }).length;
      },
      /* 要你管的 = 待批准 + 要修（顶栏那颗「待处理」开关就用它）。
         ★ `V-292`：原来这是个两段的分段控件，永远摆着「全部技能」一段 ——
           而它旁边那段在"没有要处理的东西"时不出现，于是那颗就是**唯一选项、点了也没用**。
           现在整块撤掉：只有 `nTodo > 0` 时才出现一颗开关。 */
      nTodo: function () { return this.nPending + this.nBroken; },
      filtered: function () {
        var q = this.query.trim().toLowerCase();
        var f = this.filt;
        return this.all.filter(function (w) {
          var bad = !!(w.problems || []).length;
          if (f === 'todo' && !bad && w.allowed) return false;
          if (!q) return true;
          return [w.id, w.name, w.desc, w.why, w.entry, (w.params || []).join(' ')]
            .join(' ').toLowerCase().indexOf(q) >= 0;
        });
      },
      /* 抽屉里那一只：按 id 从**当前数据**里取 —— 刷新之后拿到的永远是最新的那份 */
      current: function () {
        var id = store.openId;
        if (!id) return null;
        return this.all.filter(function (w) { return w.id === id; })[0] || null;
      },
      dir: function () { return (this.data && this.data.dir) || ''; },
      busy: function () { return this.loading && !this.loaded; },
      /* 三条空状态各自的开关（★ 独立布尔量，**不靠 v-else-if 链** —— 见 index.html 那段注释）。
         ★ `notReady` 必须是"**真失败过**（`tries > 0`）"才算 —— 不能是 `!loaded`：
           `load()` 一进门就把 `tried` 置真，用 `!loaded` 会让"还没读回来"的那零点几秒
           也弹出「读不出来」，闪一下又没了（你说的那个坏体验）。 */
      noMatch: function () {
        return this.loaded && this.all.length > 0 && this.filtered.length === 0;
      },
      noSkills: function () { return this.loaded && this.all.length === 0; },
      notReady: function () { return !this.loaded && this.tries > 0; },
    },

    watch: {
      /* 待处理的被清空 ⇒ 把「只看待处理」收回去，免得开关没了、筛选还卡着 */
      nTodo: function (n) {
        if (!n && this.filt === 'todo') this.filt = 'all';
      },
      /* 弹窗里换了哪一只 ⇒ 「详细说明」默认展开、并把它的 AGENT.md 读回来 */
      'store.openId': function (id) {
        if (!id) return;
        store.openDoc = true;
        store.docText = '';
        store.docBusy = false;
        store.codeMax = '';
        this.loadDoc();
        /* `V-301`：换技能 ⇒ 回到「数据概览」、把「命令行」清掉、把这只技能的「运行日志」读回来 */
        store.rtab = 'overview';
        store.runId = '';
        store.console = { busy: false, running: false, at: '', code: null, dur: null, cmd: '', out: '', err: '', text: '' };
        this.loadRuns(id);
      },
    },

    methods: {
      ico: I.of,

      /* ------------------------------------------------------------ 提示条 */
      toast: function (text, kind) {
        window.__skillToast = this.toast.bind(this);   // 给 `paths.js` 点到打不开的路径时用
        text = String(text == null ? '' : text).trim();
        if (!text) return;
        var id = ++this.toastSeq;
        this.toasts.push({ id: id, text: text, kind: kind || 'ok' });
        var ms = Math.min(5200, 1900 + text.length * 55);
        var self = this;
        setTimeout(function () { self.dropToast(id); }, ms);
      },
      dropToast: function (id) {
        var t = this.toasts.filter(function (x) { return x.id === id; })[0];
        if (!t) return;
        t.closing = true;                              // 先播退场，再从数组里摘掉
        var self = this;
        setTimeout(function () {
          self.toasts = self.toasts.filter(function (x) { return x.id !== id; });
        }, 160);
      },

      /* ------------------------------------------------------------ 顶栏 */
      /* ★ 模板三处 `@click="retry"` 一直是**悬空**的（代码里只有 `retryLater`）——
         点「刷新」/「重试」会抛 `retry is not a function`。这里补上：清掉计数重来一次。 */
      retry: function () {
        this.tries = 0;
        this.load();
      },
      toggleTodo: function () { this.filt = this.filt === 'todo' ? 'all' : 'todo'; },
      clearFind: function () { this.query = ''; this.filt = 'all'; },

      /* ------------------------------------------------------------ 复制 / 打开目录 */
      copy: function (text, what) {
        var self = this;
        window.SKILL_API.copy(text).then(function () {
          var msg = what === 'skill' ? '已复制这个技能的目录路径'
                  : what === 'file' ? '已复制文件内容' : '已复制目录路径';
          self.toast(msg, 'ok');
        }).catch(function (e) {
          self.toast('复制不了：' + ((e && e.message) || e), 'bad');
        });
      },
      copyPath: function () {
        var it = this.current;
        if (it) this.copy(it.dir, 'skill');
      },
      /* 复制某个文件的正文（详情里那个文件行右边的「复制」小按钮） */
      copyFile: function (rel) {
        var t = store.fileTextMap[rel];
        if (t === undefined) { this.toast('这个文件的内容还没读出来', 'info'); return; }
        this.copy(t, 'file');
      },

      /* ------------------------------------------------------------ 读数据
         ★★ 这一段是 `V-286`/`V-287` 的结论，别简化：
            · **每次调用都有超时**（桥把消息丢了不能把页面挂死）；
            · **失败 / 超时自动重试**（700ms 一次，最多 20 次，不用人点）；
            · **只有成功才算起来**（`loaded` 不锁死失败，所以"再试一次"永远有机会）。 */
      load: function () {
        var self = this;
        if (this._loading) return Promise.resolve();
        this._loading = true;
        this.tried = true;
        if (!this.loaded) this.loading = true;
        return new Promise(function (resolve) {
          var done = false;
          var timer = setTimeout(function () {
            finish(function () {
              self.retryLater('等了 ' + LOAD_TIMEOUT + 'ms 没回（桥大概把这条消息丢了）');
            });
          }, LOAD_TIMEOUT);
          function finish(fn) {
            if (done) return;
            done = true;
            clearTimeout(timer);
            self._loading = false;
            fn();
            resolve();
          }
          window.SKILL_API.list().then(function (got) {
            finish(function () {
              self.data = got || { skills: [], broken: [], dir: '' };
              self.loaded = true;
              self.loading = false;
              self.tries = 0;
              self.why = '';
              self.got = '';
              self._lastLoad = Date.now();
              /* 桌上那份数据换了：抽屉里那只可能已经没了（被删 / 被转成插件） */
              if (store.openId && !self.current) self.closeDrawer(true);
            });
          }).catch(function (e) {
            finish(function () { self.retryLater((e && e.message) ? e.message : String(e)); });
          });
        });
      },
      retryLater: function (why) {
        this.tries++;
        this.why = why;
        /* ★ 后端/桥的原话原样留着：这一页栽过三次，出问题时那句原话比一句笼统的
           "读不出来"有用得多（`V-286` 的结论）—— 它是给用户看的，不是给日志看的。 */
        this.got = why;
        if (this.tries <= RETRY_MAX) {
          var self = this;
          setTimeout(function () { self.load(); }, 700);
          return;
        }
        /* 连着这么多次都不成 ⇒ 这才把话说死（"下一步怎么办"那句在错误面板里常驻） */
        this.loading = false;
      },

      /* ------------------------------------------------------------ 弹窗 */
      openDetail: function (it) {
        store.openId = it.id;
        store.openRel = '';
        store.codeMax = '';
        this.drawer = true;
        this.drawerClosing = false;
        /* 「详细说明」默认展开 + 读正文，交给下面 `store.openId` 那个 watcher（开哪只读哪只） */
      },
      closeDrawer: function (now) {
        if (now) { this.drawer = false; store.openId = ''; store.codeMax = ''; this.drawerClosing = false; return; }
        this.drawerClosing = true;
        var self = this;
        setTimeout(function () {
          self.drawer = false;
          self.drawerClosing = false;
          store.openId = '';
          store.openDoc = false;
          store.openRel = '';
          store.codeMax = '';
        }, 120);                                        // 跟 CSS 的退场时长对齐
      },
      /* 读它自己的说明书（`AGENT.md`）—— 开弹窗（默认展开）和手动展开都走它 */
      loadDoc: function () {
        var it = this.current;
        if (!it) return;
        store.docBusy = true;
        window.SKILL_API.doc(it.id).then(function (r) {
          store.docBusy = false;
          store.docText = (r && r.text) || '（这只技能没写说明书）';
        }).catch(function (e) {
          store.docBusy = false;
          store.docText = '读不出来：' + ((e && e.message) || e);
        });
      },
      toggleDoc: function () {
        var it = this.current;
        if (!it) return;
        store.openDoc = !store.openDoc;
        if (!store.openDoc || store.docText) return;
        this.loadDoc();
      },
      openFile: function (rel) {
        var it = this.current;
        if (!it) return;
        if (store.openRel === rel) { store.openRel = ''; return; }
        store.openRel = rel;
        if (store.fileTextMap[rel] !== undefined) return;
        window.SKILL_API.read(it.id).then(function (got) {
          var all = (got && got.text) || {};
          Object.keys(all).forEach(function (k) { store.fileTextMap[k] = all[k]; });
          if (store.fileTextMap[rel] === undefined) {
            store.fileTextMap[rel] = '（这只技能里没有这个文件了）';
          }
        }).catch(function (e) {
          store.fileTextMap[rel] = '读不出来：' + ((e && e.message) || e);
        });
      },

      /* ------------------------------------------------------------ 五个动作
         都是"点了之后要人再看一眼结果"的：`reload` 就是重问一遍 list。 */
      act: function (what) {
        var it = this.current;
        if (!it) return;
        if (what === 'allow') return this.apply(window.SKILL_API.allow(it.id, !it.allowed), it.id);
        if (what === 'run') return this.runOnce(it);
        if (what === 'open') {
          var self = this;
          window.SKILL_API.reveal(it.dir).then(function (r) {
            if (r && r.ok === false) self.toast(r.msg || '打不开这个目录', 'bad');
          }).catch(function (e) { self.toast('打不开：' + ((e && e.message) || e), 'bad'); });
          return;
        }
        if (what === 'rm') return this.askRemove(it);
        if (what === 'promote') return this.askPromote(it);
      },
      apply: function (p, keepId) {
        var self = this;
        return p.then(function (r) {
          var ok = !(r && r.ok === false);
          self.toast((r && r.msg) || (ok ? '好了' : '没成'), ok ? 'ok' : 'bad');
          if (keepId) store.openId = keepId;
          return self.load();
        }).catch(function (e) {
          self.toast('出错了：' + ((e && e.message) || e), 'bad');
        });
      },
      runOnce: function (it) {
        var self = this;
        /* ★ `V-302`：交互式运行 —— 起一个进程，**自动切到「命令行」**，输出实时流、能输入、能停。
           （后端只许在"已经允许"的技能上试跑；这颗按钮也只在允许后出现。） */
        store.rtab = 'console';
        store.runId = '';
        store.console = { busy: true, running: true, at: '', code: null, dur: null, cmd: '',
                          out: '', err: '', text: '' };
        window.SKILL_API.runStart(it.id).then(function (r) {
          if (!r || r.ok === false) {
            store.console = { busy: false, running: false, at: '', code: null, dur: null,
                              cmd: '', out: '', err: '', text: '起不来：' + ((r && r.msg) || '') };
            self.toast('起不来：' + ((r && r.msg) || ''), 'bad');
            return;
          }
          store.runId = r.rid;
          store.console.cmd = (r.cmd || []).join(' ');
          self.toast('正在跑 ' + it.name + '…', 'info');
          setTimeout(function () { self.load(); }, 300);   // 立刻刷新数据概览（最近调用时间）
          self.pollRun(it.id);
        }).catch(function (e) {
          store.console = { busy: false, running: false, at: '', code: null, dur: null,
                            cmd: '', out: '', err: '', text: '起不来：' + ((e && e.message) || e) };
          self.toast('起不来：' + ((e && e.message) || e), 'bad');
        });
      },
      pollRun: function (sid) {
        var self = this;
        if (!store.runId) return;
        var rid = store.runId;
        window.SKILL_API.runPoll(rid).then(function (r) {
          if (!r || r.ok === false || store.runId !== rid) return;
          store.console.out = r.out || '';
          store.console.at = r.at || '';
          store.console.running = !!r.running;
          store.console.busy = !!r.running;
          store.console.code = (r.code === undefined ? null : r.code);
          if (r.running) { setTimeout(function () { self.pollRun(sid); }, 250); return; }
          self.loadRuns(sid);                            // 跑完刷新「运行日志」
          self.toast('跑完了（退出码 ' + (r.code === null || r.code === undefined ? '—' : r.code) + '）',
                     r.code ? 'info' : 'ok');
          setTimeout(function () { self.load(); }, 200);  // 顺带把「调用次数 / 最近调用时间」刷新一下
        }).catch(function () { /* 轮询出错就停 */ });
      },
      sendInput: function (line) {
        var self = this;
        if (!store.runId || !store.console.running) { self.toast('没在跑', 'info'); return; }
        window.SKILL_API.runInput(store.runId, String(line == null ? '' : line)).then(function (r) {
          if (r && r.ok === false) self.toast(r.msg || '写不进去', 'bad');
        }).catch(function (e) { self.toast('写不进去：' + ((e && e.message) || e), 'bad'); });
      },
      stopRun: function () {
        if (!store.runId) return;
        window.SKILL_API.runStop(store.runId).then(function () { /* 轮询会看到 running=false */ });
      },
      /* `V-301`：读这只技能的运行日志（新的在前） */
      loadRuns: function (id) {
        store.runsBusy = true;
        return window.SKILL_API.runs(id).then(function (r) {
          store.runsBusy = false;
          store.runs = (r && r.runs) || [];
        }).catch(function () {
          store.runsBusy = false;
          store.runs = [];
        });
      },
      /* 「清空日志」：先问一句，只清这只技能的 */
      clearRuns: function () {
        var it = this.current;
        if (!it) return;
        this.showSheet({
          title: '清掉「' + it.name + '」的运行日志？',
          body: '只清这只技能的历次运行记录（日志文件本身留着）。这一下收不回来。',
          ok: '清掉', danger: true,
          run: function (s, val, done) {
            window.SKILL_API.clearRuns(it.id).then(function (r) {
              if (r && r.ok === false) s.toast(r.msg || '没清掉', 'bad');
              else s.toast((r && r.msg) || '已清空', 'ok');
              s.loadRuns(it.id);
            }).catch(function (e) { s.toast('没清掉：' + ((e && e.message) || e), 'bad'); });
            done();
          },
        });
      },
      /* 删除：先把最要紧的两件事说清楚（整个目录、几个文件），再让人点头 */
      askRemove: function (it) {
        this.showSheet({
          title: '删掉「' + it.name + '」？',
          body: '它的整个目录会一起没（<code>' + this.esc(it.files_n) + ' 个文件</code>）：\n'
              + this.esc(it.dir) + '\n\n这一下收不回来。',
          ok: '删掉', danger: true,
          run: function (self, val, done) {
            self.apply(window.SKILL_API.rm(it.id));
            done();
          },
        });
      },
      /* 转为插件：**先只算不改**（id 会不会撞），撞了就把"换个名字"摆出来让人填 */
      askPromote: function (it) {
        var self = this;
        window.SKILL_API.plan(it.id).then(function (p) {
          if (!p || !p.ok) { self.toast((p && p.msg) || '算不出来', 'bad'); return; }
          var bad = (p.problems || []).length;
          self.showSheet({
            title: bad ? '插件 id 撞了 —— 换个名字' : '把「' + it.name + '」转为插件？',
            body: (bad ? p.problems.join('\n') + '\n\n' : '')
                + '转过去之后它就从技能墙搬进**插件列表**了（AI 照样能调它）：\n'
                + '  ' + self.esc(p.dir_from) + '\n  → ' + self.esc(p.dir_to),
            input: bad ? p.new_id : '',
            label: '插件 id',
            hint: bad ? '得换一个没被占的（小写字母开头）' : '留空 = 用 ' + p.new_id,
            ok: '转过去',
            run: function (self2, val, done) {
              self2.apply(window.SKILL_API.promote(it.id, val));
              done();
            },
          });
        }).catch(function (e) {
          self.toast('算不出来：' + ((e && e.message) || e), 'bad');
        });
      },
      showSheet: function (s) { this.sheet = s; this.sheetClosing = false; },
      hideSheet: function (now) {
        if (!this.sheet) return;
        if (now) { this.sheet = null; this.sheetClosing = false; return; }
        this.sheetClosing = true;
        var self = this;
        setTimeout(function () { self.sheet = null; self.sheetClosing = false; }, 140);
      },
      okSheet: function (val) {
        var s = this.sheet;
        if (!s) return;
        var self = this;
        s.run(self, val, function () { self.hideSheet(); });
      },
      esc: function (s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
          return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
      },
    },

    mounted: function () {
      var self = this;

      document.addEventListener('keydown', function (ev) {
        var tag = (ev.target && ev.target.tagName || '').toLowerCase();
        var mod = ev.ctrlKey || ev.metaKey;
        if (mod && (ev.key || '').toLowerCase() === 'f') {
          ev.preventDefault();
          if (self.$refs.search) { self.$refs.search.focus(); self.$refs.search.select(); }
          return;
        }
        if (ev.key === '/' && !mod && tag !== 'input' && tag !== 'textarea') {
          ev.preventDefault();
          if (self.$refs.search) self.$refs.search.focus();
          return;
        }
        if (ev.key === 'Escape') {
          if (store.codeMax) { store.codeMax = ''; return; }   // 放大看的代码先收
          if (self.sheet) { self.hideSheet(); return; }
          if (self.drawer) { self.closeDrawer(); return; }
          if (self.query) self.query = '';
        }
      });

      /* 宿主切走再切回来 ⇒ 顺手重问一遍（可能刚被 AI 造了新技能）。
         ★ 只在"抽屉关着、而且离上次读过了 1.5 秒"时才刷 —— 别把人正在看的东西刷没了。 */
      if (window.moss && window.moss.on) {
        window.moss.on('visible', function (d) {
          if (!d || !d.visible) return;
          if (self.drawer || !self.loaded) return;
          if (Date.now() - (self._lastLoad || 0) < 1500) return;
          self.load();
        });
        /* 宿主会说现在该用深色还是浅色（`system/ui/js/embed.js` 在帧 ready 时推一条） */
        window.moss.on('theme', function (d) {
          if (d && typeof d.dark === 'boolean') {
            document.documentElement.dataset.theme = d.dark ? 'dark' : 'light';
          }
        });
      }

      boot();
    },
  });

  /* ★ 挂到 window 上：探针和"手点一下"之外，也能在控制台里直接看它 */
  window.__skillApp = app;

  /* ================================================================ 启动
     ★★ 这一段踩过四次坑，别简化（`V-283` / `V-285` / `V-286` / `V-287` / `V-289`）：

       ⓪ **必须等 DOM 建好**：`src/*.js` 是在 `#app` 后面紧接着执行的，那一刻浏览器
          **还没把 `#app` 里面的模板解析出来** ⇒ `app.mount('#app')` 拿到一个空壳，
          Vue 编译出来是空的：**页面一片白、控制台一句错都没有**。
       ⓪′ **挂载得上锁**：这个页面有**两条路**会来叫 boot（垫片的 `ready` + 独立窗口那条轮询），
          而 `app.mount()` **返回 undefined** —— 拿返回值当哨兵等于没上锁，于是挂第二次：
          第二次把**上一轮渲染出来的 DOM** 当模板再编译一遍 ⇒ 又是白板（还是不报错）；
          就算渲染出来了，它也是**另一份组件实例**，JS 里改状态看着对、DOM 再也不动。
          所以 `mounted` 这个布尔才是锁，`vm` 只存实例。
       ① 垫片把 `ready` 做成**粘的**（晚订阅补一枪，见 `moss-embed.js`）；
       ② 这儿直接看一眼 `moss.ready`（万一垫片还是老的那份）；
       ③ **内嵌**那条路兜底：0.8 秒还没起来就自己开一次工；
          **独立窗口**那条路一直轮询 `window.pywebview.api`（500ms 一次，很便宜）；
          **页面 load 再保一枪** —— 页面被单独打开时 `ready` 与 `pywebviewready` 一个都不来。

     为什么不能只写一句 `moss.on('ready', boot)`：内嵌那一帧里，垫片是在
     `setTimeout(0)` 里就把 `ready` 打出去的 —— 而那一刻解析器正等着取 `app.js`
     （取的时候事件循环是转着的）⇒ 那一枪**先跑掉了**，可 `boot()` 还没挂上，
     谁也没接住 ⇒ 一个请求都没发出去，页面永远停在"正在读……"。
     （症状：**点一下「重试」马上就好** —— 因为那才是第一次真的发出去。） */
  var vm = null;
  var mounted = false;      // ★ 「已经挂过了」跟 `vm` 是**两件事**（见上）

  function mountAndLoad() {
    if (mounted) return;
    mounted = true;
    vm = app.mount('#app');
    if (vm) vm.load();
  }

  function boot() {
    if (mounted) return;                     // 挂过了就别再挂（boot 必须幂等）
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mountAndLoad, { once: true });
      return;
    }
    mountAndLoad();
  }

  window.SKILL_BOOT = boot;

  if (window.moss && typeof window.moss.on === 'function') {
    window.moss.on('ready', function () { boot(); });
    if (window.moss.ready) boot();                     // ②
  } else {
    boot();
  }
  window.addEventListener('load', function () { boot(); });          // 保底那一枪
  if (!(window.moss && window.moss.env && window.moss.env.embedded)) {
    (function waitBridge() {                            // 独立窗口：桥什么时候到就什么时候起
      if (mounted) return;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.list) { boot(); return; }
      setTimeout(waitBridge, 500);
    })();
  } else {
    setTimeout(function () { boot(); }, 800);          // ③
  }
})();
