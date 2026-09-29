/* moss 界面 · js/settings.js —— ★ 设置面板（`V-60` ✅ / `V-63` ✅ / `V-66` ✅ / `V-67` ✅）
   ============================================================================
   这是**第一个 Vue 3 组件**（`V-67`：原来它是一大段命令式 DOM 代码，散在 index.html 里）。

   它自己带：模板（写在这个文件里）、状态、校验、保存、hover 提示 —— 外面只管两件事：
     · `<div id="settings-host"></div>` 这么个挂载点；
     · 齿轮点一下调 `openSettings()`。

   ★ 数据全是宿主给的（`moss --settings` / `--settings-check` / `--settings-set`）：
     分组 / 图标 / 标签 / 说明 / 控件类型 / 当前值 / 「现在这样」/ 冲突原因。
     这个组件**不认识任何设置项，也不自己实现校验规则** —— 规则只有 `core/config.py` 那一份。
   ★ 为什么是"经典脚本 + 全局组件"而不是 .vue 单文件：页面是 pywebview 从 `file://`
     打开的，`file://` 下的 ES module 会被 CORS 拦掉（见 index.html 里的说明）。
     `vue.global.prod.js` 自带模板编译器，所以 `template:` 字符串在这里能用。 */
const MossSettings = {
  name: "moss-settings",
  template: `
<div id="settings" :class="{on: show}" @click.self="close">
  <div class="card wide">
    <div class="set-head">
      <h3>设置</h3>
      <span class="set-sub" id="set-path" :title="path">{{ shortPath }}</span>
      <button class="set-x" id="set-close" title="关闭（Esc）" aria-label="关闭"
              @click="close" v-html="icon('x')"></button>
    </div>

    <div class="set-main">
      <div class="set-nav" id="set-nav">
        <button v-for="g in groups" :key="g.name" type="button" class="set-navitem"
                :class="{on: g.name === active, 'has-bad': badGroups[g.name] === 'bad',
                         'has-warn': badGroups[g.name] === 'warn'}"
                :data-group="g.name" :title="navTitle(g.name)" @click="setActive(g.name)">
          <span v-html="icon(g.icon || 'settings')"></span><span>{{ g.name }}</span>
          <span class="set-dot"></span>
        </button>
      </div>

      <div class="set-body" id="set-body" @mouseleave="hideTip" @scroll="hideTip">
        <div v-for="g in groups" :key="g.name" class="set-pane" :class="{on: g.name === active}"
             :data-group="g.name">

          <h3 class="set-ptitle">{{ g.name }}</h3>
          <p class="set-pdesc" v-if="g.blurb">{{ g.blurb }}</p>

          <!-- 输入类：标签在上、控件在下（两列网格） -->
          <div class="set-fields" v-if="fieldsOf(g).length">
            <div v-for="it in fieldsOf(g)" :key="it.key" class="set-field" :data-key="it.key"
                 :class="rowClass(it.key)">
              <div class="set-lbl">
                <span>{{ it.label }}</span>
                <span v-if="it.hint" class="set-info" :data-tip-key="it.key"
                      @mouseover="showTip(it.key, $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <div v-if="it.type === 'int'" class="step">
                <button type="button" title="减一" :disabled="Number(values[it.key]) <= 1"
                        @click="bump(it.key, -1)">−</button>
                <input class="num" :data-key="it.key" :value="values[it.key]" inputmode="numeric"
                       @change="setVal(it.key, clampNum($event.target.value))">
                <button type="button" title="加一" :disabled="Number(values[it.key]) >= 20"
                        @click="bump(it.key, 1)">+</button>
              </div>
              <input v-else class="inp" :data-key="it.key" spellcheck="false" autocomplete="off"
                     :placeholder="it.type === 'symbol' ? '空' : '留空 = 不打印'"
                     :value="values[it.key]"
                     @input="setVal(it.key, $event.target.value)">
              <div class="set-prob" data-role="prob">{{ probText(it.key) }}</div>
            </div>
          </div>

          <!-- 开关类：名字在左、开关在右 -->
          <div class="set-list" v-if="rowsOf(g).length" :style="fieldsOf(g).length ? 'margin-top:16px' : ''">
            <div v-for="it in rowsOf(g)" :key="it.key" class="set-item" :data-key="it.key"
                 :class="rowClass(it.key)">
              <div class="set-lbl">
                <span>{{ it.label }}</span>
                <span v-if="it.hint" class="set-info" :data-tip-key="it.key"
                      @mouseover="showTip(it.key, $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <button type="button" class="sw" :data-key="it.key" role="switch"
                      :aria-checked="values[it.key] ? 'true' : 'false'"
                      :title="values[it.key] ? '开 —— 点一下关掉' : '关 —— 点一下打开'"
                      @click="setVal(it.key, !values[it.key])"></button>
              <div class="set-prob" data-role="prob">{{ probText(it.key) }}</div>
            </div>
          </div>

          <!-- 快捷命令那页：底下一条预览行（宿主算的那句话） -->
          <div v-if="g.live" class="set-live" id="set-live" :class="{bad: /^⚠/.test(live || '')}">
            <b>预览：</b> {{ live }}
          </div>
        </div>
      </div>
    </div>

    <div class="set-foot">
      <span class="set-state" id="set-state" :class="footClass">{{ footText }}</span>
      <button class="btn-quiet" id="set-cancel" @click="close">取消</button>
      <button class="btn primary" id="set-save" :disabled="!canSave" @click="save">保存</button>
    </div>
  </div>

  <!-- hover 提示：挂在组件里（原来那个全局 #tip 已经不需要了）。fixed 定位 —— 
       放进滚动层里会被裁掉。 -->
  <div id="tip" v-if="tip.show" :style="{left: tip.x + 'px', top: tip.y + 'px'}">
    <b>{{ tip.title }}</b>
    <div v-if="tip.hint">{{ tip.hint }}</div>
    <div class="tip-now" v-if="tip.now">{{ tip.now }}</div>
    <div v-for="(p, i) in tip.problems" :key="i" class="tip-prob"
         :class="p.level === 'warn' ? 'warn' : 'bad'">
      {{ (p.level === 'warn' ? '提醒：' : '') + p.why }}
    </div>
  </div>
</div>`,
  data(){
    return {
      show: false,
      path: "",
      groups: [],
      items: {},          // key -> 定义（标签 / 类型 / 说明）
      values: {},         // key -> 现在的值
      orig: {},           // key -> 打开时的值（判断"改了没有"）
      problems: [],
      notes: {},
      live: "",
      active: "",
      msg: "",            // 宿主顺带说的话（首次运行建了配置文件之类）
      saving: false,
      tip: {show: false, x: 0, y: 0, title: "", hint: "", now: "", problems: []},
      _timer: null,
      _seq: 0,
    };
  },
  computed: {
    shortPath(){
      const s = String(this.path || "").replace(/\\/g, "/");
      const parts = s.split("/").filter(Boolean);
      return parts.length <= 2 ? s : "…/" + parts.slice(-2).join("/");
    },
    changed(){
      return Object.keys(this.values).filter(k => String(this.values[k]) !== String(this.orig[k]));
    },
    errs(){
      return this.problems.filter(p => p.level !== "warn").length;
    },
    canSave(){
      return this.errs === 0 && this.changed.length > 0 && !this.saving;
    },
    footText(){
      if (this.saving) return "正在保存…";
      if (this.errs) return "✗ " + this.errs + " 处冲突 —— 把标红的地方改好才能保存";
      if (this.changed.length){
        return "改了 " + this.changed.length + " 项 · 保存后下一次启动 moss 生效"
               + (this.msg ? "（" + this.msg + "）" : "");
      }
      return "还没有改动" + (this.msg ? "（" + this.msg + "）" : "");
    },
    footClass(){
      if (this.errs) return "bad";
      return this.changed.length ? "moved" : "";
    },
    // 哪一组里有红/黄 —— 要在左边分类上点一个小圆点（不然切走了看不见）
    badGroups(){
      const out = {};
      (this.problems || []).forEach(p => {
        [p.key].concat(p.also || []).forEach(k => {
          const g = this.groupOf(k);
          if (!g) return;
          if (out[g] !== "bad") out[g] = (p.level === "warn") ? "warn" : "bad";
        });
      });
      return out;
    },
  },
  methods: {
    icon(name){ return ico(name, "i"); },
    fieldsOf(g){ return (g.items || []).filter(it => it.type !== "bool"); },
    rowsOf(g){ return (g.items || []).filter(it => it.type === "bool"); },
    groupOf(key){
      const g = this.groups.find(x => (x.items || []).some(it => it.key === key));
      return g ? g.name : "";
    },
    rowClass(key){
      const mine = (this.problems || []).filter(p => p.key === key || (p.also || []).indexOf(key) >= 0);
      if (mine.some(p => p.level !== "warn")) return "bad";
      if (mine.length) return "warn";
      return "";
    },
    probText(key){
      // ★ 原因只写在**主**那一项上；被牵连的那项只标色（同一句话不必说两遍）
      return (this.problems || []).filter(p => p.key === key)
        .map(p => (p.level === "warn" ? "提醒：" : "") + p.why).join(" ");
    },
    navTitle(name){
      const st = this.badGroups[name];
      if (st === "bad") return "这一组里有冲突";
      if (st === "warn") return "这一组里有提醒";
      return "";
    },
    clampNum(v){
      const n = parseInt(v, 10);
      return isFinite(n) ? Math.max(1, Math.min(20, n)) : 1;
    },

    /* ---- 打开 / 关闭 / 切换分类 ---- */
    async open(){
      const r = await pywebview.api.settings();
      if (!r || !r.ok){ toast("✗ 读设置失败：" + ((r && r.msg) || ""), true); return; }
      this.path = r.path || "";
      this.groups = r.groups || [];
      this.items = {}; this.values = {}; this.orig = {};
      this.groups.forEach(g => (g.items || []).forEach(it => {
        this.items[it.key] = it;
        this.values[it.key] = it.value;
        this.orig[it.key] = it.value;
      }));
      this.msg = r.msg || "";
      this.problems = []; this.notes = {}; this.live = "";
      this.saving = false;
      this.setActive((this.groups[0] || {}).name || "");
      this.show = true;
      if (this.msg) toast(this.msg);
      this.scheduleCheck(0);          // 立刻问一次：把 hover 里那些「现在这样」填上
    },
    close(){
      if (this._timer) clearTimeout(this._timer);
      this._seq++;                    // 关掉之后飞回来的检查结果一律作废
      this.hideTip();
      this.show = false;
    },
    setActive(gid){
      this.active = gid;
      this.hideTip();
    },
    setVal(key, v){
      this.values[key] = v;
      this.scheduleCheck();           // 防抖后问宿主一次（规则在那边）
      this.$forceUpdate();
    },
    bump(key, d){
      this.setVal(key, this.clampNum((parseInt(this.values[key], 10) || 1) + d));
    },

    /* ---- 校验（问宿主：规则只有 core 那一份）---- */
    scheduleCheck(delay){
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this.check(), delay == null ? 250 : delay);
    },
    async check(){
      this._timer = null;
      const seq = ++this._seq;
      const r = await pywebview.api.settings_check(Object.assign({}, this.values));
      if (seq !== this._seq) return;   // 慢的那次回来了也别盖掉新的
      this.problems = (r && r.problems) || [];
      this.notes = (r && r.notes) || {};
      this.live = (r && r.live) || "";
      if (r && r.msg) this.msg = r.msg;
      if (this.tip.show && this.tip.key) this.showTip(this.tip.key);
    },

    /* ---- 保存 / 只送改过的那几项 ---- */
    pairs(){
      const out = {};
      this.changed.forEach(k => { out[k] = this.values[k]; });
      return out;
    },
    async save(){
      const pairs = this.pairs();
      if (!Object.keys(pairs).length){ toast("没有改动"); this.close(); return; }
      this.saving = true;
      const r = await pywebview.api.settings_save(pairs);
      this.saving = false;
      const list = (r && r.problems) || [];
      if (!r || !r.ok || list.some(p => p.level !== "warn")){
        this.problems = list.length ? list
          : [{key: "", why: (r && r.msg) || "宿主没说为什么", level: "error", also: []}];
        toast("没保存 —— 看标红的地方", true);
        return;
      }
      Object.keys(pairs).forEach(k => { this.orig[k] = this.values[k]; });
      toast("已保存到 config.toml（下一次启动 moss 生效）");
      this.close();
    },

    /* ---- hover 提示（`?` 上悬停）---- */
    showTip(key, ev){
      const it = this.items[key];
      if (!it) return;
      const anchor = (ev && ev.target) ||
        document.querySelector('#set-body .set-info[data-tip-key="' + key + '"]');
      const r = anchor ? anchor.getBoundingClientRect() : {left: 40, bottom: 40, top: 40};
      this.tip = {
        show: true, key: key, title: it.label || key, hint: it.hint || "",
        now: this.notes[key] || "",
        problems: (this.problems || []).filter(p => p.key === key || (p.also || []).indexOf(key) >= 0),
        x: 0, y: 0,
      };
      this.$nextTick(() => {
        const t = document.getElementById("tip");
        const w = t ? t.offsetWidth : 300;
        const h = t ? t.offsetHeight : 80;
        let x = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
        let y = r.bottom + 8;
        if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
        this.tip.x = Math.round(x); this.tip.y = Math.round(y);
      });
    },
    hideTip(){ this.tip.show = false; },
  },
};

/* ---- 挂载 + 给外面的几个门面（别的地方只认这几个名字）---- */
let _settingsApp = null;

function settingsApp(){
  if (!_settingsApp){
    const host = document.getElementById("settings-host");
    if (!host) return null;
    _settingsApp = Vue.createApp(MossSettings).mount(host);
  }
  return _settingsApp;
}
function openSettings(){ const a = settingsApp(); return a ? a.open() : null; }
function closeSettings(){ const a = settingsApp(); if (a) a.close(); }
function saveSettings(){ const a = settingsApp(); return a ? a.save() : null; }
function setActive(gid){ const a = settingsApp(); if (a) a.setActive(gid); }
function showTip(key, ev){ const a = settingsApp(); if (a) a.showTip(key, ev); }
function hideTip(){ const a = settingsApp(); if (a) a.hideTip(); }
function collectSettings(){ const a = settingsApp(); return a ? a.pairs() : {}; }
