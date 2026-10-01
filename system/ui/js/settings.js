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

          <!-- ★ AI 那一组（V-138）：组名是用户自己起的、一组一份参数，摆不成
               「一个键一行」，所以单独一块 —— 选组 / 新增 / 复制 / 删除 / 设为当前 / 测连接。
               底下的通用块用 v-if 让开（ai.active / ai.profiles 那两行不再重复渲染）。 -->
          <div class="set-ai" v-if="isAi(g)">
            <div class="ai-bar">
              <label class="ai-lbl" for="ai-sel">用哪一组</label>
              <select class="ai-sel" id="ai-sel" :value="ai.name" @change="aiPick($event)">
                <option v-for="n in ai.profiles" :key="n" :value="n"
                        :data-active="n === ai.active ? '1' : '0'">{{ n }}</option>
              </select>
              <button class="btn-quiet sm" id="ai-new" type="button" @click="aiNew()">新增</button>
              <button class="btn-quiet sm" id="ai-copy" type="button" :disabled="!ai.name"
                      @click="aiCopy()" title="连密钥一起复制成新的一组">复制</button>
              <button class="btn-quiet sm" id="ai-del" type="button" :disabled="!ai.name"
                      @click="aiDel()">删除</button>
              <button class="btn-quiet sm" id="ai-use" type="button"
                      :disabled="!ai.name || ai.name === ai.active"
                      @click="aiUse()" title="以后跑包注入的就是这一组">设为当前</button>
            </div>

            <p class="ai-none" v-if="!ai.profiles.length">
              还没有任何一组 —— 点「新增」起个名字，填上接口地址和模型就能用了。
            </p>

            <!-- ★ 动作行放在**上面**（V-138 第二版）：九项字段排下来比一屏高，
                 摆在底下就得滚动才看得见「保存这一组」—— 主操作不能藏在折线下面。 -->
            <div class="ai-bar ai-acts" v-if="ai.name">
              <button class="btn primary" id="ai-save" type="button"
                      :disabled="!aiDirty() || ai.busy" @click="aiSave()">
                {{ ai.busy ? "正在存…" : "保存这一组" }}
              </button>
              <button class="btn-quiet" id="ai-test" type="button" :disabled="ai.busy || !ai.name"
                      @click="aiTest()" title="按这一组真发一个最小请求，看流式能不能回来">
                测试连接
              </button>
              <span class="ai-state" id="ai-state" :class="ai.statusOk ? 'ok' : 'bad'"
                    v-if="ai.status">{{ ai.status }}</span>
              <span class="ai-tip" v-else>
                参数<b>明文</b>存在 <code>user_data/config.toml</code>；跑包时按当前这一组注入
                <code>MOSS_AI_*</code> 给子进程。
              </span>
            </div>

            <div class="set-fields ai-fields" v-if="ai.name">
              <div v-for="f in aiFields" :key="f.k" class="set-field" :data-ai="f.k">
                <div class="set-lbl">
                  <span>{{ f.label }}</span>
                  <span v-if="f.hint" class="set-info ai-info" :title="f.hint"
                        v-html="icon('info')"></span>
                </div>
                <div v-if="f.type === 'bool'" class="ai-swbox">
                  <button type="button" class="sw" :data-ai="f.k" role="switch"
                          :aria-checked="aiVal(f.k) ? 'true' : 'false'"
                          :title="aiVal(f.k) ? '开 —— 点一下关掉' : '关 —— 点一下打开'"
                          @click="aiSet(f.k, !aiVal(f.k))"></button>
                  <span class="ai-swtxt">{{ aiVal(f.k) ? "开 · 边生成边往回吐" : "关 · 等整段说完再回" }}</span>
                </div>
                <div v-else-if="f.type === 'key'" class="ai-keyrow">
                  <input class="inp" :data-ai="f.k" :type="ai.revealed ? 'text' : 'password'"
                         spellcheck="false" autocomplete="off" :placeholder="aiKeyPh()"
                         :value="aiVal(f.k)" @input="aiSet(f.k, $event.target.value)">
                  <button class="btn-quiet sm" id="ai-eye" type="button" @click="aiEye()"
                          :title="ai.revealed ? '点一下藏起来' : '点一下看明文（要向宿主读一次）'">
                    {{ ai.revealed ? "藏起来" : "露出来" }}
                  </button>
                </div>
                <input v-else class="inp" :data-ai="f.k" spellcheck="false" autocomplete="off"
                       :placeholder="f.ph || ''" :value="aiVal(f.k)"
                       @input="aiSet(f.k, $event.target.value)">
              </div>
            </div>
          </div>

          <template v-else>
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
          </template>
        </div>
      </div>
    </div>

    <div class="set-foot">
      <span class="set-state" id="set-state" :class="footClass">{{ aiPane
        ? "AI 那一组用上面那颗「保存这一组」—— 这一页不动 config.toml 的其它段"
        : footText }}</span>
      <button class="btn-quiet" id="set-cancel" @click="close">取消</button>
      <!-- ★ AI 那一页**不摆**全局那颗「保存」（V-138）：AI 的参数走上面那条自己的保存，
           全局这颗只认「设置项」，在 AI 页上按下去只会说"没有改动"然后关窗 ——
           看着像存上了、其实什么都没发生，这种坑不如不放。 -->
      <button class="btn primary" id="set-save" v-if="!aiPane" :disabled="!canSave"
              @click="save">保存</button>
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
      // ★ AI 那一组（`V-138`）：界面**不解析 TOML**，全都问宿主（`pywebview.api.ai_*`）。
      //   `params` = 宿主给的那一组（key **打码**）；`draft` = 用户改过、还没保存的字段
      //   （存的时候**只送这几个**，不会把打码那串当值写回去）。
      ai: {loaded: false, busy: false, name: "", active: "", profiles: [],
           params: {}, draft: {}, revealed: false, status: "", statusOk: false},
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
    // ★ AI 那一组的字段表（`V-138`）：**顺序就是显示顺序**，跟 `core/config.py` 的
    //   `AI_FIELDS` 对应（那边管"存哪些"，这边多一层"怎么摆、怎么说"）。
    //   ★ 必须放**计算属性**里：放 methods 就是把这个函数本身递给 `v-for` ——
    //     函数没有可枚举属性，于是那一块**一个字段都不渲染**（第一版就这么写的，
    //     场景里 `字段=0/0/0` 才看出来）。
    aiFields(){
      return [
        {k: "base_url", label: "接口地址", ph: "https://api.deepseek.com/v1",
         hint: "OpenAI 兼容的地址，填到 /v1 为止 —— 后面那截 /chat/completions 由 moss 拼。"},
        {k: "api_key", label: "密钥", type: "key",
         hint: "明文存在 user_data/config.toml（你定的：明文即可）。留空 = 不改原来那串。"},
        {k: "model", label: "模型", ph: "deepseek-chat",
         hint: "请求里那个 model 字段 —— 各家自己起的名字（deepseek-chat / qwen2.5:7b …）。"},
        {k: "stream", label: "流式输出", type: "bool",
         hint: "开 = 边生成边往回吐（SSE），关 = 等整段说完再回。"},
        {k: "temperature", label: "temperature", ph: "0.7",
         hint: "越大越发散。留空 = 用服务商的默认值。"},
        {k: "max_tokens", label: "max_tokens", ph: "2048",
         hint: "一次最多生成多少 token。留空 = 用服务商的默认值。"},
        {k: "top_p", label: "top_p", ph: "1",
         hint: "另一种截断方式，和 temperature 挑一个调就行。"},
        {k: "timeout", label: "超时（秒）", ph: "60",
         hint: "连不上这么久就放弃 —— 本地小模型可以调大点。"},
        {k: "note", label: "备注", ph: "这一组是干什么的",
         hint: "只给自己看，不发给服务商。"},
      ];
    },
    // 现在这一页是不是 AI 那一组（是的话底部那颗全局「保存」就不摆 —— 见模板里的注释）
    aiPane(){ return this.isAiName(this.active); },
  },
  methods: {
    icon(name){ return ico(name, "i"); },
    isAi(g){ return this.isAiName(g && g.name); },
    isAiName(name){
      const g = (this.groups || []).find(x => x.name === name);
      return !!(g && (g.items || []).some(it => it.key === "ai.active"));
    },
    aiVal(k){
      if (Object.prototype.hasOwnProperty.call(this.ai.draft, k)) return this.ai.draft[k];
      // 打码的那串**不当值填进框里** —— 不然保存时会把 "sk-a…7890" 存成真 key
      if (k === "api_key" && !this.ai.revealed) return "";
      const v = this.ai.params[k];
      return v == null ? "" : v;
    },
    aiKeyPh(){
      if (this.ai.revealed) return "明文已经读出来了，不动它就不会改";
      const m = this.ai.params.api_key;
      return m ? (m + "（留空不改）") : "还没填";
    },
    aiSet(k, v){
      this.ai.draft[k] = v;
      this.ai.status = "";            // 改了参数，上次那个测试结果就不算数了
    },
    aiDirty(){ return Object.keys(this.ai.draft).length > 0; },
    async aiLoad(name){
      const r = await pywebview.api.ai_config(name || "", false);
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读 AI 参数失败"), true); return false; }
      this.ai.loaded = true;
      this.ai.active = r.active || "";
      this.ai.profiles = r.profiles || [];
      this.ai.name = r.name || "";
      this.ai.params = r.params || {};
      this.ai.draft = {};
      this.ai.revealed = false;
      this.ai.status = "";
      return true;
    },
    async aiPick(ev){
      const sel = ev && ev.target;
      const name = sel ? sel.value : "";
      if (!name || name === this.ai.name) return;
      const back = () => { if (sel) sel.value = this.ai.name; };
      if (this.aiDirty()){
        askConfirm("这一组还没保存", "换一组会把刚改的丢掉。", () => { this.aiLoad(name); });
        back();
        return;
      }
      if (!(await this.aiLoad(name))) back();
    },
    aiNew(){ askText("新的一组叫什么名字", "", (nm) => this.aiCreate(String(nm || "").trim())); },
    async aiCreate(name, seed){
      if (!name) return;
      if (this.ai.profiles.indexOf(name) >= 0){ toast("已经有「" + name + "」了", true); return; }
      const r = await pywebview.api.ai_save(name, seed || {base_url: "", model: ""});
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没存上"), true); return; }
      await this.aiLoad(name);
      toast("加了一组「" + name + "」—— 填上地址和模型再点「测试连接」");
    },
    aiCopy(){
      const src = this.ai.name;
      if (!src) return;
      askText("复制成哪一组（换个名字）", src + "-副本", async (nm) => {
        nm = String(nm || "").trim();
        if (!nm) return;
        if (nm === src || this.ai.profiles.indexOf(nm) >= 0){
          toast("已经有「" + nm + "」了 —— 换个名字", true); return;
        }
        // ★ 复制要连**真密钥**一起（打码那串复制过去就是废的）⇒ 走 reveal 读一次明文
        const r0 = await pywebview.api.ai_config(src, true);
        const seed = (r0 && r0.ok && r0.params) || null;
        if (!seed){ toast("✗ 读不到「" + src + "」的参数，没法复制", true); return; }
        await this.aiCreate(nm, seed);
      });
    },
    aiDel(){
      const name = this.ai.name;
      if (!name) return;
      askConfirm("删除这一组？",
                 "「" + name + "」的参数会从 config.toml 里删掉（只是配置，别的东西不动）。",
                 async () => {
        const r = await pywebview.api.ai_delete(name);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没删掉"), true); return; }
        await this.aiLoad("");
        toast("删了「" + name + "」");
      });
    },
    async aiUse(){
      const name = this.ai.name;
      if (!name || name === this.ai.active) return;
      const r = await pywebview.api.ai_set_active(name);
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没切成"), true); return; }
      this.ai.active = name;
      toast("当前那组 = " + name + "（下次跑包注入的就是它）");
    },
    async aiEye(){
      if (this.ai.revealed){ this.ai.revealed = false; this.ai.draft = {}; return; }
      const r = await pywebview.api.ai_config(this.ai.name, true);
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读明文失败"), true); return; }
      this.ai.revealed = true;
      const real = (r.params || {}).api_key || "";
      this.ai.params = Object.assign({}, this.ai.params, {api_key: real});
      if (Object.prototype.hasOwnProperty.call(this.ai.draft, "api_key")) delete this.ai.draft.api_key;
    },
    async aiSave(){
      const name = this.ai.name;
      if (!name) return;
      const fields = Object.assign({}, this.ai.draft);
      if (!Object.keys(fields).length){ toast("没有改动"); return; }
      this.ai.busy = true;
      const r = await pywebview.api.ai_save(name, fields);
      this.ai.busy = false;
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没存上"), true); return; }
      await this.aiLoad(name);
      toast("已保存「" + name + "」（明文写在 config.toml 里）");
    },
    async aiTest(){
      const name = this.ai.name;
      if (!name) return;
      if (this.aiDirty()){ toast("先把改的存了再测 —— 测的是存下来的那一组", true); return; }
      this.ai.busy = true;
      this.ai.status = "正在连…"; this.ai.statusOk = false;
      const r = await pywebview.api.ai_test(name);
      this.ai.busy = false;
      this.ai.statusOk = !!(r && r.ok);
      this.ai.status = (r && r.msg) || "（宿主没回话）";
    },
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
      // 切到 AI 那一页时才去问宿主（省得每次开设置都多跑一条命令）
      if (this.isAiName(gid) && !this.ai.loaded) this.aiLoad("");
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
    _settingsApp = mountVue(MossSettings, host);
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
