/* ==========================================================================
   moss 概览面板
   - 只在「没有选中插件 / 历史记录」时显示
   - 这里只表达一个概念：插件
   - 所有数字来自插件启动记录；历史里的文件运行属于左侧「历史」，不混进来
   ========================================================================== */
const HOME = Vue.reactive({
  rev: 0,
  year: new Date().getFullYear(),
  month: new Date().getMonth(),
  mode: "ai",
  idea: "",
  manual: {name: "", id: "", desc: "", task: ""},
  busy: false,
  err: "",
  stats: { today: 0, month: 0, total: 0, active_days: 0, days: {}, months: {} },
  created: { today: 0, month: 0, total: 0, active_days: 0, days: {}, months: {} },
});

/* 概览里的插件分组直接复用左侧列表的 GROUPS，不再维护一份写死的分类表。
 * 这样新增分组、拖动分组、把插件放进别的组，首页和列表页会始终一致。 */
function homeSectionsOf(plugins){
  const rows = (plugins || []).slice();
  const groups = (typeof GROUPS !== "undefined" && GROUPS && Array.isArray(GROUPS.list))
    ? GROUPS.list : [];
  if (!groups.length){
    return rows.length
      ? [{id: "__all__", title: "全部插件", icon: "package", rows: rows}]
      : [];
  }

  const byGroup = new Map();
  const owner = new Map();
  groups.forEach(g => {
    byGroup.set(g.id, []);
    (g.ids || []).forEach(id => {
      if (!owner.has(id)) owner.set(id, g.id);   // 和列表页一样：同一个插件只归第一个组
    });
  });

  const rest = [];
  rows.forEach(p => {
    const gid = owner.get(p.id);
    if (gid && byGroup.has(gid)) byGroup.get(gid).push(p);
    else rest.push(p);
  });

  const out = [];
  groups.forEach(g => {
    const groupRows = byGroup.get(g.id) || [];
    if (groupRows.length){
      out.push({id: "g:" + g.id, title: g.name || "（没名字的分组）",
                icon: "folder", rows: groupRows});
    }
  });
  if (rest.length){
    out.push({id: "__free__", title: "未分组", icon: "package", rows: rest});
  }
  return out;
}
function hmPad(n){ return String(n).padStart(2, "0"); }
function hmDayKey(d){
  return d.getFullYear() + "-" + hmPad(d.getMonth() + 1) + "-" + hmPad(d.getDate());
}
function hmHeatLevel(v){
  if (v <= 0) return 0;
  if (v <= 2) return 1;
  if (v <= 5) return 2;
  if (v <= 10) return 3;
  return 4;
}
async function homeRefresh(){
  let runs = null, creates = null;
  try{
    if (window.pywebview && pywebview.api && typeof pywebview.api.plugin_run_stats === "function")
      runs = await pywebview.api.plugin_run_stats();
  }catch(e){ runs = null; }
  try{
    if (window.pywebview && pywebview.api && typeof pywebview.api.plugin_create_stats === "function")
      creates = await pywebview.api.plugin_create_stats();
  }catch(e){ creates = null; }
  if (runs && runs.ok){
    HOME.stats = {
      today: +runs.today || 0,
      month: +runs.month || 0,
      total: +runs.total || 0,
      active_days: +runs.active_days || 0,
      days: runs.days || {},
      months: runs.months || {},
    };
  }
  if (creates && creates.ok){
    HOME.created = {
      today: +creates.today || 0,
      month: +creates.month || 0,
      total: +creates.total || 0,
      active_days: +creates.active_days || 0,
      days: creates.days || {},
      months: creates.months || {},
    };
  }
  HOME.rev++;
}

let _homeRefreshT = null;
function homeScheduleRefresh(){
  if (_homeRefreshT) clearTimeout(_homeRefreshT);
  _homeRefreshT = setTimeout(() => { _homeRefreshT = null; homeRefresh(); }, 180);
}
window.homeRefresh = homeRefresh;
window.homeScheduleRefresh = homeScheduleRefresh;
window.homeBump = function(){ HOME.rev++; };

const MossHome = {
  name: "moss-home",
  data(){ return { H: HOME }; },
  computed: {
    pluginList(){
      this.H.rev;
      return ((typeof DATA !== "undefined" && DATA && DATA.packages) || []).slice();
    },
    pluginTotal(){ return this.pluginList.length; },
    createdMonth(){
      this.H.rev;
      return +this.H.created.month || 0;
    },

    sections(){
      this.H.rev;
      /* 列表页的分组、搜索排序都在这两个响应式对象里；home 要跟着一起变。 */
      if (typeof GROUPS !== "undefined" && GROUPS) GROUPS.rev;
      if (typeof LISTR !== "undefined" && LISTR) LISTR.rev;
      /* DATA 要等 init() 里的 pywebview.api.state() 回来才有；挂载首帧时不能直接碰它。 */
      const rows = (typeof _sortedPkgs === "function" && typeof DATA !== "undefined" && DATA)
        ? _sortedPkgs() : this.pluginList;
      return homeSectionsOf(rows);
    },

    runningTasks(){
      this.H.rev;
      const out = [];
      const seen = {};
      const pkgs = this.pluginList;
      const runs = (typeof RUNS !== "undefined" && RUNS) ? RUNS : {};

      Object.keys(runs).forEach(key => {
        const run = runs[key] || {};
        const isHist = key.indexOf("hist:") === 0;
        const p = !isHist ? pkgs.find(x => x.id === key) : null;
        const it = isHist ? ((typeof HIST !== "undefined" ? HIST : []).find(x =>
          (typeof histKey === "function") && histKey(x) === key) || null) : null;
        let icon = '<span class="hm-ri-icon">' + ico("terminal", "i") + '</span>';
        if (p && typeof iconHTML === "function") icon = iconHTML(p, "hm-ri-icon");
        else if (it && typeof histIconHTML === "function") icon = histIconHTML(it, "hm-ri-icon");
        let startedAt = +run.startedAt || +run.t0 || 0;
        out.push({
          key: key, name: p ? p.name : (it ? it.name : (key.replace(/^hist:/, "").split(" ")[0] || key)),
          icon: icon, startedAt: startedAt, isHist: !!isHist, packageId: p ? p.id : "",
          canOpen: !!(p || it),
        });
        seen[key] = true;
      });

      const pst = (typeof PST !== "undefined" && PST) ? PST : {};
      Object.keys(pst).forEach(id => {
        if (seen[id]) return;
        const st = pst[id] || {};
        if (!st.running) return;
        const p = pkgs.find(x => x.id === id);
        if (!p) return;
        let startedAt = 0;
        try{
          const s = st.procs && st.procs[0] ? String(st.procs[0].started || "") : "";
          if (s) startedAt = new Date(s.replace(" ", "T")).getTime() || 0;
        }catch(e){}
        out.push({
          key: id, name: p.name,
          icon: (typeof iconHTML === "function") ? iconHTML(p, "hm-ri-icon")
                : ('<span class="hm-ri-icon">' + ico("package", "i") + '</span>'),
          startedAt: startedAt, isHist: false, packageId: id, canOpen: true, external: true,
        });
      });
      return out;
    },
    runningCount(){ return this.runningTasks.length; },

    /* 唯一口径：后端记录的「插件启动」事件。 */
    dayCounts(){
      this.H.rev;
      return this.H.stats.days || {};
    },
    todayExtra(){
      this.H.rev;
      return Math.max(0, this.runningCount - (+this.H.stats.today || 0));
    },
    todayCount(){
      this.H.rev;
      return (+this.H.stats.today || 0) + this.todayExtra;
    },
    monthCount(){
      this.H.rev;
      return (+this.H.stats.month || 0) + this.todayExtra;
    },
    monthActiveDays(){
      this.H.rev;
      return (+this.H.stats.active_days || 0) +
        (this.todayExtra > 0 && !(+this.H.stats.today || 0) ? 1 : 0);
    },
    todayMeta(){
      this.H.rev;
      if (this.runningCount) return "其中 " + this.runningCount + " 个插件正在运行";
      if (this.todayCount) return "次插件启动";
      return "今天还没有启动插件";
    },
    calendar(){
      this.H.rev;
      const year = this.H.year, month = this.H.month;
      const first = new Date(year, month, 1);
      const startOffset = (first.getDay() + 6) % 7;
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const rows = Math.ceil((startOffset + daysInMonth) / 7);
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const cells = [];
      let active = 0, monthTotal = 0;
      const statsDays = this.H.stats.days || {};
      const createdDays = this.H.created.days || {};

      for (let i = 0; i < rows * 7; i++){
        let dayNum, mo;
        if (i < startOffset){
          const prevDays = new Date(year, month, 0).getDate();
          dayNum = prevDays - startOffset + 1 + i; mo = -1;
        }else if (i >= startOffset + daysInMonth){
          dayNum = i - startOffset - daysInMonth + 1; mo = 1;
        }else{
          dayNum = i - startOffset + 1; mo = 0;
        }
        const d = new Date(year, month + mo, dayNum);
        const key = hmDayKey(d);
        const future = d.getTime() > today.getTime();
        const isToday = d.getTime() === today.getTime();
        const count = (+statsDays[key] || 0) + (isToday ? this.todayExtra : 0);
        const created = +createdDays[key] || 0;
        if (!mo && count > 0){ active++; monthTotal += count; }
        cells.push({
          day: dayNum, key: key, other: mo !== 0, today: isToday, future: future,
          count: count, heat: future ? 0 : hmHeatLevel(count),
          hasRuns: !future && (count > 0 || created > 0),
          tip: (d.getMonth() + 1) + "月" + d.getDate() + "日\n" +
               (future ? "暂无数据" : ("启动 " + count + " 次" +
                 (created ? ("\n新建 " + created + " 个插件") : "") +
                 (isToday && this.runningCount ? ("\n其中 " + this.runningCount + " 个插件正在运行") : ""))),
        });
      }
      return {
        label: year + "年" + (month + 1) + "月",
        cells: cells,
        activeDays: active,
        monthTotal: monthTotal,
      };
    },
  },
  mounted(){
    homeRefresh();
    if (!window.__homeTick){
      window.__homeTick = setInterval(() => {
        const pane = document.getElementById("pane-home");
        if (pane && pane.classList.contains("on")) HOME.rev++;
      }, 1000);
      window.__homeStatTick = setInterval(() => {
        const pane = document.getElementById("pane-home");
        if (pane && pane.classList.contains("on")) homeRefresh();
      }, 60000);
    }
  },
  methods: {
    ico: ico,
    iconHTML: iconHTML,
    mode(m){
      this.H.mode = m === "manual" ? "manual" : "ai";
      this.H.err = "";
    },
    async createPlugin(modeOverride){
      const mode = (modeOverride === "manual" || modeOverride === "ai")
        ? modeOverride : this.H.mode;

      /* AI 创建仍然走原来的标准 AI 新建弹窗（会先让 AI 补全 id/名字/介绍）。 */
      if (mode === "ai"){
        if (typeof cmdNewPkg !== "function") return;
        const idea = String(this.H.idea || "").trim();
        cmdNewPkg("ai");
        Vue.nextTick(() => {
          try{
            if (idea){
              const el = document.getElementById("np-idea");
              if (el) el.value = idea;
            }
          }catch(e){}
        });
        return;
      }

      /* 手动编写直接在首页表单里创建，不再弹窗。 */
      if (this.H.busy) return;
      const id = String(this.H.manual.id || "").trim().toLowerCase();
      const name = String(this.H.manual.name || "").trim();
      const desc = String(this.H.manual.desc || "").trim();
      if (!/^[a-z][a-z0-9_-]{0,31}$/.test(id)){
        this.H.err = "包 ID 要小写字母开头，只含 a-z、0-9、-、_（最长 32 位）";
        return;
      }
      this.H.err = "";
      this.H.busy = true;
      let r = null;
      try{ r = await pywebview.api.new_pkg(id, name, desc); }
      catch(e){ r = {ok: false, msg: "创建失败：" + ((e && e.message) || e)}; }
      this.H.busy = false;
      if (!r || !r.ok){
        this.H.err = (r && r.msg) || "创建失败（没有返回原因）";
        return;
      }
      this.H.manual = {name: "", id: "", desc: "", task: ""};
      toast("已创建 " + PSYM + id + (name ? " · " + name : ""));
      await init();
      select(id, true);
    },
    shiftMonth(delta){
      let m = this.H.month + delta;
      this.H.year += Math.floor(m / 12);
      this.H.month = ((m % 12) + 12) % 12;
      this.H.rev++;
    },
    openTask(t){
      if (!t || !t.canOpen) return;
      try{
        if (t.isHist){
          const it = (HIST || []).find(x => histKey(x) === t.key);
          if (it) selectHist(it);
        }else if (t.packageId){
          if (typeof setSide === "function") setSide("pkg");
          select(t.packageId);
        }
      }catch(e){}
    },
    async stopTask(t){
      if (!t || !t.key) return;
      try{
        if (t.external && typeof stopFromList === "function") await stopFromList(t.key);
        else if (typeof stopRun === "function") await stopRun(t.key);
      }catch(e){}
      setTimeout(() => { homeRefresh(); }, 350);
      HOME.rev++;
    },
    elapsed(t){
      this.H.rev;
      if (!t || !t.startedAt) return "运行中";
      const diff = Math.max(0, Math.floor((Date.now() - t.startedAt) / 1000));
      return hmPad(Math.floor(diff / 3600)) + ":" +
             hmPad(Math.floor((diff % 3600) / 60)) + ":" + hmPad(diff % 60);
    },
    openPkg(p){
      if (!p) return;
      try{
        if (typeof setSide === "function") setSide("pkg");
        select(p.id);
      }catch(e){}
    },
    pkgTitle(p){
      return (p.name || p.id) + " · " + PSYM + p.id;
    },
    pkgCmd(p){
      return PSYM + String((p && p.id) || "");
    },
  },
  template: `
    <div class="hm-scroll">
      <div class="hm-dashboard">
        <section class="hm-hero">
          <h1 class="hm-hero-title">你想创造什么？</h1>
          <p class="hm-hero-sub">{{ H.mode === 'manual' ? '直接填写插件信息，创建后再到详情页继续设置' : '用一句话描述，AI 帮你瞬间生成专属插件' }}</p>
          <div class="hm-create">
            <textarea v-if="H.mode === 'ai'" class="hm-create-area" v-model="H.idea" spellcheck="false"
              placeholder="例如：帮我写一个能自动将截图上传到图床并返回 Markdown 链接的插件..."
              @keydown.ctrl.enter.prevent="createPlugin()"></textarea>

            <div v-else class="hm-manual">
              <div class="hm-manual-grid">
                <input class="hm-manual-field" v-model="H.manual.name" autocomplete="off"
                       spellcheck="false" placeholder="名字">
                <input class="hm-manual-field hm-manual-mono" v-model="H.manual.id" autocomplete="off"
                       spellcheck="false" placeholder="包 ID（a-z、0-9、-、_）">
              </div>
              <input class="hm-manual-field" v-model="H.manual.desc" autocomplete="off"
                     spellcheck="false" placeholder="一句话介绍">
              <textarea class="hm-manual-field hm-manual-area" v-model="H.manual.task"
                        spellcheck="false" placeholder="首句任务（可选，创建后可继续编辑）"></textarea>
              <div v-if="H.err" class="hm-create-status">{{ H.err }}</div>
            </div>

            <div class="hm-create-bar">
              <div class="hm-modes">
                <button type="button" class="hm-mode" :class="{on: H.mode === 'ai'}"
                        @click="mode('ai')">
                  <span style="display:contents" v-html='ico("sparkles","i")'></span>
                  <span>AI 创建</span>
                </button>
                <button type="button" class="hm-mode" :class="{on: H.mode === 'manual'}"
                        @click="mode('manual')">
                  <span style="display:contents" v-html='ico("settings","i")'></span>
                  <span>手动编写</span>
                </button>
              </div>
              <button type="button" class="hm-create-btn" :disabled="H.busy" @click="createPlugin()">
                <span style="display:contents" v-html='ico("sparkles","i")'></span>
                <span>{{ H.mode === 'manual' ? (H.busy ? '创建中…' : '创建插件') : '生成插件' }}</span>
              </button>
            </div>
          </div>
        </section>

        <div class="hm-runs-wrap" :class="{on: runningTasks.length}">
          <div class="hm-runs-inner">
            <div class="hm-task-board">
              <div class="hm-tb-head">
                <div class="hm-tb-title"><span class="hm-tb-dot"></span>正在运行</div>
                <div class="hm-tb-count">{{ runningTasks.length }} 个插件正在运行</div>
              </div>
              <div class="hm-tb-list">
                <div v-for="t in runningTasks" :key="t.key" class="hm-run-item"
                     :title="t.canOpen ? '打开 ' + t.name : t.name" @click="openTask(t)">
                  <span style="display:contents" v-html="t.icon"></span>
                  <div class="hm-ri-info">
                    <span class="hm-ri-name">{{ t.name }}</span>
                    <span class="hm-ri-time">{{ elapsed(t) }}</span>
                  </div>
                  <button type="button" class="hm-ri-stop" title="停止这个插件"
                          @click.stop="stopTask(t)"
                          v-html='ico("x","i")'></button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="hm-overview">
          <div class="hm-overview-left">
            <div class="hm-stat-card">
              <div class="hm-stat-label">
                <span style="display:contents" v-html='ico("package","i")'></span>
                <span>插件总数</span>
              </div>
              <div class="hm-stat-num">{{ pluginTotal }}</div>
              <div class="hm-stat-meta">本月新建 {{ createdMonth }} 个</div>
            </div>
            <div class="hm-stat-card">
              <div class="hm-stat-label">
                <span style="display:contents" v-html='ico("activity","i")'></span>
                <span>今日启动</span>
              </div>
              <div class="hm-stat-num">{{ todayCount }}</div>
              <div class="hm-stat-meta">{{ todayMeta }}</div>
            </div>
            <div class="hm-stat-card">
              <div class="hm-stat-label">
                <span style="display:contents" v-html='ico("play-circle","i")'></span>
                <span>本月启动</span>
              </div>
              <div class="hm-stat-num">{{ monthCount }}</div>
              <div class="hm-stat-meta">次插件启动 · 活跃 {{ monthActiveDays }} 天</div>
            </div>
            <div class="hm-stat-card">
              <div class="hm-stat-label">
                <span style="display:contents" v-html='ico("loader-circle","i")'></span>
                <span>正在运行</span>
              </div>
              <div class="hm-stat-num">{{ runningCount }}</div>
              <div class="hm-stat-meta">{{ runningCount ? "个插件正在运行" : "当前没有运行中的插件" }}</div>
            </div>
          </div>

          <div class="hm-calendar" @wheel.prevent="shiftMonth($event.deltaY > 0 ? 1 : -1)">
            <div class="hm-cal-head">
              <div class="hm-cal-month">{{ calendar.label }}</div>
              <div class="hm-cal-nav">
                <button type="button" class="hm-cal-arrow" title="上个月"
                        @click="shiftMonth(-1)" v-html='ico("chevron-right","i")'
                        style="transform:rotate(180deg)"></button>
                <button type="button" class="hm-cal-arrow" title="下个月"
                        @click="shiftMonth(1)" v-html='ico("chevron-right","i")'></button>
              </div>
            </div>
            <div class="hm-cal-weekdays">
              <span>一</span><span>二</span><span>三</span><span>四</span>
              <span>五</span><span>六</span><span>日</span>
            </div>
            <div class="hm-cal-grid">
              <div v-for="(c, i) in calendar.cells" :key="i" class="hm-cal-cell"
                   :class="{other: c.other, future: c.future, today: c.today}"
                   :data-heat="c.heat || null" :data-tip="c.tip">
                {{ c.day }}
                <span v-if="c.hasRuns" class="hm-cal-dot"></span>
              </div>
            </div>
            <div class="hm-cal-foot">本月活跃 <b>{{ calendar.activeDays }}</b> 天 · 启动 <b>{{ calendar.monthTotal }}</b> 次 · 新建 <b>{{ createdMonth }}</b> 个</div>
          </div>
        </div>

        <div v-if="!sections.length" class="hm-empty">还没有插件。用上面的输入框创建第一个。</div>
        <section v-for="sec in sections" :key="sec.id" class="hm-section">
          <div class="hm-section-head">
            <span class="hm-sec-ico" v-html='ico(sec.icon,"i")'></span>
            <span class="hm-sec-title">{{ sec.title }}</span>
            <span>{{ sec.rows.length }} 个插件</span>
          </div>
          <div class="hm-grid">
            <div v-for="p in sec.rows" :key="p.id" class="hm-app-card"
                 :title="pkgTitle(p)" @click="openPkg(p)">
              <span class="hm-app-icon-slot" v-html="iconHTML(p, 'hm-app-icon')"></span>
              <div class="hm-app-name">{{ p.name }}</div>
              <div class="hm-app-cmd">{{ pkgCmd(p) }}</div>
            </div>
          </div>
        </section>
      </div>
    </div>`,
};

mountVue(MossHome, "#pane-home");

/* 点左上角 moss 标志回到概览；这也是选中插件时回到总览的入口。 */
window.mossShowHome = function(){
  try{
    cur = null; curH = null;
    if (typeof setSide === "function") setSide("pkg");
    renderList(); renderHist(); renderDetail(); paintConsole();
    if (typeof paintActions === "function") paintActions(null);
    if (typeof setTab === "function") setTab("home");
    homeRefresh();
  }catch(e){}
};
document.addEventListener("DOMContentLoaded", function(){
  /* 页面标题栏空白处也能取消选择、回到概览。输入框 / 按钮除外。 */
  const header = document.querySelector("header");
  if (header){
    header.addEventListener("click", function(e){
      if (e.target.closest("button,input")) return;
      if (typeof window.mossShowHome === "function") window.mossShowHome();
    });
  }
});