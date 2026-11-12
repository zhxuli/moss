(function () {
  'use strict';

  var I = window.SKILL_ICONS;
  var C = window.SKILL_COMPONENTS;

  var store = Vue.reactive({
    openId: '',          
    openDoc: false,      
    docBusy: false,
    docText: '',
    openRel: '',         
    codeMax: '',         
    fileTextMap: {},     
    fileText: function (rel) {
      if (!rel) return '';
      var t = this.fileTextMap[rel];
      return t === undefined ? '（正在读…）' : t;
    },

    rtab: 'overview',
    runId: '',
    console: { busy: false, running: false, at: '', code: null, dur: null, cmd: '', out: '', err: '', text: '' },
    runs: [],
    runsBusy: false,
  });

  var LOAD_TIMEOUT = 4000;    
  var RETRY_MAX = 20;         

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
        data: null,          
        loading: true,
        loaded: false,       
        tries: 0,            
        tried: false,        
        why: '',             
        got: '',             
        query: '',
        filt: 'all',         
        drawer: false,       
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

      current: function () {
        var id = store.openId;
        if (!id) return null;
        return this.all.filter(function (w) { return w.id === id; })[0] || null;
      },
      dir: function () { return (this.data && this.data.dir) || ''; },
      busy: function () { return this.loading && !this.loaded; },

      noMatch: function () {
        return this.loaded && this.all.length > 0 && this.filtered.length === 0;
      },
      noSkills: function () { return this.loaded && this.all.length === 0; },
      notReady: function () { return !this.loaded && this.tries > 0; },
    },

    watch: {
      nTodo: function (n) {
        if (!n && this.filt === 'todo') this.filt = 'all';
      },

      'store.openId': function (id) {
        if (!id) return;
        store.openDoc = true;
        store.docText = '';
        store.docBusy = false;
        store.codeMax = '';
        this.loadDoc();

        store.rtab = 'overview';
        store.runId = '';
        store.console = { busy: false, running: false, at: '', code: null, dur: null, cmd: '', out: '', err: '', text: '' };
        this.loadRuns(id);
      },
    },

    methods: {
      ico: I.of,

      toast: function (text, kind) {
        window.__skillToast = this.toast.bind(this);   
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
        t.closing = true;                              
        var self = this;
        setTimeout(function () {
          self.toasts = self.toasts.filter(function (x) { return x.id !== id; });
        }, 160);
      },

      retry: function () {
        this.tries = 0;
        this.load();
      },
      toggleTodo: function () { this.filt = this.filt === 'todo' ? 'all' : 'todo'; },
      clearFind: function () { this.query = ''; this.filt = 'all'; },

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

      copyFile: function (rel) {
        var t = store.fileTextMap[rel];
        if (t === undefined) { this.toast('这个文件的内容还没读出来', 'info'); return; }
        this.copy(t, 'file');
      },

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

        this.got = why;
        if (this.tries <= RETRY_MAX) {
          var self = this;
          setTimeout(function () { self.load(); }, 700);
          return;
        }

        this.loading = false;
      },

      openDetail: function (it) {
        store.openId = it.id;
        store.openRel = '';
        store.codeMax = '';
        this.drawer = true;
        this.drawerClosing = false;

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
        }, 120);                                        
      },

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
          setTimeout(function () { self.load(); }, 300);   
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
          self.loadRuns(sid);                            
          self.toast('跑完了（退出码 ' + (r.code === null || r.code === undefined ? '—' : r.code) + '）',
                     r.code ? 'info' : 'ok');
          setTimeout(function () { self.load(); }, 200);  
        }).catch(function () {  });
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
        window.SKILL_API.runStop(store.runId).then(function () {  });
      },

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
          if (store.codeMax) { store.codeMax = ''; return; }   
          if (self.sheet) { self.hideSheet(); return; }
          if (self.drawer) { self.closeDrawer(); return; }
          if (self.query) self.query = '';
        }
      });

      if (window.moss && window.moss.on) {
        window.moss.on('visible', function (d) {
          if (!d || !d.visible) return;
          if (self.drawer || !self.loaded) return;
          if (Date.now() - (self._lastLoad || 0) < 1500) return;
          self.load();
        });

        window.moss.on('theme', function (d) {
          if (d && typeof d.dark === 'boolean') {
            document.documentElement.dataset.theme = d.dark ? 'dark' : 'light';
          }
        });
      }

      boot();
    },
  });

  window.__skillApp = app;

  var vm = null;
  var mounted = false;      

  function mountAndLoad() {
    if (mounted) return;
    mounted = true;
    vm = app.mount('#app');
    if (vm) vm.load();
  }

  function boot() {
    if (mounted) return;                     
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mountAndLoad, { once: true });
      return;
    }
    mountAndLoad();
  }

  window.SKILL_BOOT = boot;

  if (window.moss && typeof window.moss.on === 'function') {
    window.moss.on('ready', function () { boot(); });
    if (window.moss.ready) boot();                     
  } else {
    boot();
  }
  window.addEventListener('load', function () { boot(); });          
  if (!(window.moss && window.moss.env && window.moss.env.embedded)) {
    (function waitBridge() {                            
      if (mounted) return;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.list) { boot(); return; }
      setTimeout(waitBridge, 500);
    })();
  } else {
    setTimeout(function () { boot(); }, 800);          
  }
})();
