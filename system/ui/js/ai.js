/* AI 工作台那一页（`V-230`~`V-233`）—— 详情页的第五个选项卡。
 *
 * 它是**宿主界面的一部分**（不是包）：贴着当前选中的包，结果直接落到
 * 文件管理 / 命令行 / 运行状态上（`V-231` 定的形态）。
 *
 * 三条设计（都在账本里）：
 *   · **先做无界面的 loop**，这一页只是它的显示器 —— 所以这里不干任何 AI 的活，
 *     只做四件事：显示信息 / 交任务 / 轮询步骤流 / 按停止。
 *   · **验收硬闸在 loop 里**（`ai_tools.Tools.verified`）：这一页不许"看它说完成了"就当完成，
 *     结果卡上直接写"✅ 验收通过"还是"✗ 没通过（为什么）"。
 *   · **每步显示 token**：把"啰嗦/费"变成看得见的数字（这是跟 DSH 对比的尺子）。
 *
 * ★ 举牌信号 `AIR.rev`：`cur` 是 core.js 里的**普通变量**（不是响应式的），
 *   所以"选中的包换了"要靠定时器比对 + 改一个响应式字段来通知 Vue 重画
 *   （和 `CONSOLER` / `DRAGR` 一个套路，见 console.js 里那段注释）。
 */
const AIR = Vue.reactive({
  rev: 0, curId: "", curDir: "", info: null, err: "",
  task: "", where: "pkg", running: false, steps: [], say: [], result: null,
  seconds: 0, busy: false, tick: null,
  maxTokens: 100000000, warnTokens: 80000000,   // `V-240`：token 上限（存 user_data/ai/budget.json）
  phase: "",                   // `V-242`：thinking / waiting / tools —— "模型在想"别看着像卡死
  context: 128000,             // `V-244`：上下文窗口（按模型猜，可在 budget.json 里改）
  compactAt: 102400,           // 到这么多输入 token 才开始折叠（DSH：窗口 × 0.8）
  promptTokens: 0,             // 上一轮实际发出去多少输入 token（= 现在上下文多长）
  runs: [],                   // `V-243`：跑过的任务（存 user_data/ai/runs/，重启 moss 还在）
  viewing: "",                // 正在看哪条历史记录（空 = 看当前/最近这次）
  maxMillions: 100,            // 界面上那一格是**百万为单位**（100 = 1 亿）
  diskNoted: "",               // `V-249`：已经通知过"盘上变了"的那一次（免得每轮轮询都刷一遍）
  snapNoted: "",               // `V-250`：已经通知过"快照存好了"的那一条（同上）
});

function aiPackage(){ return cur && cur.id ? cur : null; }

/* `V-239`：给人看的 token 数字（32569 → 32.6k）—— 和 `ai_budget.human()` 一个口径。 */
function humanTokens(n){
  const v = Number(n || 0);
  if (v >= 1000000) return (v / 1000000).toFixed(2) + "M";
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return String(v);
}

/* 给探针/预览工具看的把手（`V-233`）：这一页的状态全在 `AIR` 里，
   外面想断言"到底 ready 没有 / 是不是还 busy"就靠它 —— 不用去猜 DOM。 */
window.__AIR = AIR;

function aiWhereDir(){
  if (AIR.where === "new") return (AIR.info && AIR.info.write_root) || "";
  const p = aiPackage();
  return (p && p.dir) || "";
}

async function aiRefreshInfo(force){
  try {
    AIR.info = await window.pywebview.api.ai_info(aiWhereDir(), !!force);
    if (AIR.info && AIR.info.ok){
      if (AIR.info.max_tokens) AIR.maxTokens = AIR.info.max_tokens;
      if (AIR.info.warn_tokens) AIR.warnTokens = AIR.info.warn_tokens;
      AIR.maxMillions = Math.round((AIR.maxTokens / 1000000) * 1000) / 1000;
      if (AIR.info.context) AIR.context = AIR.info.context;
      if (AIR.info.compact_at) AIR.compactAt = AIR.info.compact_at;
    }
    AIR.err = "";
  } catch (e) {
    AIR.err = "读不到 AI 状态：" + (e && e.message ? e.message : e);
  }
  AIR.rev++;
}

/* `V-238`：那两格小输入改完立刻存（下不为例地"即时生效"，因为它们是本机设置）。 */
async function aiSaveBudget(){
  try{
    // 那一格填的是**百万**，存之前换算成 token（`V-240`）
    const tokens = Math.round(Number(AIR.maxMillions || 0) * 1000000);
    const got = await window.pywebview.api.ai_set_budget(tokens);
    if (!got || !got.ok){ toast((got && got.msg) || "预算没存上", true); await aiRefreshInfo(true); return; }
    AIR.maxTokens = got.max_tokens; AIR.warnTokens = got.warn || Math.round((got.max_tokens || 0) * 0.8);
    AIR.maxMillions = Math.round((AIR.maxTokens / 1000000) * 1000) / 1000;
    toast("token 上限 = " + humanTokens(got.max_tokens) + "（烧到 " + humanTokens(AIR.warnTokens) + " 时劝它收尾）");
  }catch(e){ toast("存预算失败：" + (e && e.message ? e.message : e), true); }
}

/* `V-243`：把跑过的任务列出来（重启 moss 也在 —— 你说"历史记录不保存是不行的"）。 */
async function aiLoadRuns(){
  try{
    const got = await window.pywebview.api.ai_runs(30);
    if (got && got.ok) AIR.runs = got.runs || [];
  }catch(e){ /* 读不到就空着，不吵人 */ }
}

/* 点「看」：把那条历史的步骤流/结论load进来（只看，不重跑）。 */
async function aiOpenRun(id){
  try{
    const got = await window.pywebview.api.ai_run(id);
    if (!got || !got.ok || !got.run){ toast("读不到这条记录", true); return; }
    const r = got.run;
    AIR.viewing = id;
    AIR.steps = r.steps || [];
    AIR.result = {ok: !!r.ok, reason: r.reason || "", summary: r.summary || "",
                  caveats: r.caveats || "", files: r.files || [], usage: r.usage || {},
                  snapshot: r.snapshot || null, run_id: r.id};
    AIR.rev++;
  }catch(e){ toast("读不到这条记录：" + (e && e.message ? e.message : e), true); }
}

async function aiForgetRun(id){
  try{
    const got = await window.pywebview.api.ai_run_forget(id || "", !id);
    if (got && got.ok){ toast(id ? "删掉那条记录了" : "历史清空了"); AIR.viewing = ""; await aiLoadRuns(); }
    else toast((got && got.msg) || "删不掉", true);
  }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
}

async function aiPollOnce(){
  try {
    const got = await window.pywebview.api.ai_poll();
    if (!got || !got.ok) return;
    AIR.running = !!got.running;
    AIR.steps = got.steps || [];
    AIR.say = got.say || [];
    AIR.seconds = got.seconds || 0;
    AIR.phase = got.phase || "";
    // 只在**正在跑**的时候才用「这次任务的」上限覆盖那一格 —— 否则你刚改完预算，
    // 下一次轮询就把它改回旧值了（预览里我先踩到）。
    if (got.running && got.max_tokens) AIR.maxTokens = got.max_tokens;
    if (got.compact_at) AIR.compactAt = got.compact_at;      // `V-244`
    if (got.context) AIR.context = got.context;
    AIR.promptTokens = got.prompt_tokens || 0;
    if (!got.idle) AIR.result = got.result || null;
    // ★ `V-249`：它干完活了、而且盘上真有文件变了 ⇒ 让「文件管理」那份缓存作废
    //   （你报的"AI 改完文件后「文件管理」页不自动刷新"，就是缺这一下）。
    //   只通知一次：结果会一直摆在 `ai_poll` 里（轮询每 700ms 一次），不认个号就会
    //   反复重列目录、反复读数。
    // ★ `V-250`：它**开工前**存的那条快照 —— 存好就刷新「版本快照」那一列。
    //   为什么不能等跑完：快照是第一步之前就存了的，而你要看的正是"它动手前是什么样"，
    //   跑完才刷出来就晚了几十秒（真机原话："没有刷新 所以我是看不到它刚刚做的快照"）。
    const snap = got.snapshot;
    if (snap && snap.id && snap.id !== AIR.snapNoted){
      AIR.snapNoted = snap.id;
      if (typeof bkRefresh === "function") bkRefresh();
    }
    const res = got.result;
    if (res && !got.running){
      const stamp = String(res.run_id || (res.files || []).join("|") || "");
      if (stamp && stamp !== AIR.diskNoted){
        AIR.diskNoted = stamp;
        if ((res.files || []).length && typeof diskChanged === "function")
          diskChanged(res.files);
      }
    }
    AIR.rev++;
  } catch (e) { /* 轮询失败不吵人：下一轮再说 */ }
}

async function aiStart(){
  if (AIR.busy) return;
  const task = (AIR.task || "").trim();
  if (!task) { toast("先写一句你要它干什么。", true); return; }
  const dir = aiWhereDir();
  if (!dir) { toast("先在左边选一个包（或者选「新建包」）。", true); return; }
  AIR.busy = true;
  AIR.result = null; AIR.steps = []; AIR.say = [];
  AIR.diskNoted = "";            // `V-249`：新任务 = 允许再通知一次"盘上变了"
  AIR.snapNoted = "";            // `V-250`：新任务 = 允许再通知一次"快照存好了"
  try {
    // ★ `V-237` 把 14 提到 24（读一个 395 行的文件就花了 11 步）；`V-238` 再按你的定夺改成
    //   **硬顶 200 + 每 50 步提醒一次**（都在上面那两格里，随手可改）。
    const got = await window.pywebview.api.ai_start(task, dir, AIR.maxTokens);
    if (!got || !got.ok) { toast((got && got.msg) || "起不来。", true); AIR.busy = false; return; }
    AIR.running = true;
    toast("开始干活了（模型 " + (got.model || "?") + "）—— 步骤会实时出现在下面。");
  } catch (e) {
    toast("起不来：" + (e && e.message ? e.message : e), true);
  }
  AIR.busy = false;
  AIR.rev++;
}

async function aiStop(){
  try {
    const got = await window.pywebview.api.ai_stop();
    toast((got && got.msg) || "已请求停止。");
  } catch (e) { /* 无妨 */ }
}

const MossAi = {
  name: "moss-ai",
  data(){ return { A: AIR }; },
  computed: {
    pkg(){ this.A.rev; return aiPackage(); },
    info(){ this.A.rev; return this.A.info; },
    target(){ this.A.rev; return aiWhereDir(); },
    missing(){ this.A.rev; return (this.A.info && this.A.info.missing_prompts) || []; },
    model(){ this.A.rev; return (this.A.info && this.A.info.model) || "（还没配 AI）"; },
    ready(){ this.A.rev; return !!(this.A.info && this.A.info.ok && this.A.info.model && this.A.info.has_key); },
    /* 这个目标**写不写得了**（v1 只许写 `user_data/pkgs/**`）。
       ★ 出厂包（`system/pkgs/*`）在左边就能选到，但它**改不了** —— 与其让用户白等一轮，
         不如当场说清。只提示、不禁用：只读的任务（"讲讲这个包怎么写的"）照样能跑。 */
    canWrite(){
      this.A.rev;
      const t = aiWhereDir(), root = (this.A.info && this.A.info.write_root) || "";
      if (!t || !root) return false;
      const norm = s => String(s).replace(/[\\/]+$/, "").toLowerCase();
      return norm(t) === norm(root) || norm(t).indexOf(norm(root) + "\\") === 0 ||
             norm(t).indexOf(norm(root) + "/") === 0;
    },
    usage(){ this.A.rev; return (this.A.result && this.A.result.usage) || null; },
    /* `V-237`：把"用了几步"显示出来 —— 上次"步数用完了"你根本不知道它第几步停的。
       （`V-239` 起主闸是 token，这行只当参考。） */
    curStep(){ this.A.rev; return (this.A.steps || []).reduce((m, s) => Math.max(m, s.n || 0), 0); },
    maxTokens(){ this.A.rev; return this.A.maxTokens || 200000; },
    /* 已经烧了多少 token（每个步骤行都带"此刻的累计值"）—— 比步数更贴"花了多少钱"。 */
    curTokens(){
      this.A.rev;
      const ss = this.A.steps || [];
      return ss.length ? (ss[ss.length - 1].tokens || 0) : 0;
    },
    /* `V-244`：上下文用量百分比（对着「到 80% 才折」那条线看，一眼知道离压缩还有多远）。 */
    ctxPct(){
      this.A.rev;
      if (!this.A.compactAt) return 0;
      return Math.min(100, Math.round((this.A.promptTokens || 0) * 100 / this.A.compactAt));
    },
    /* `V-241`：历史压缩的累计条数（不再作为一步刷屏，只在这儿安静地报一个数）。 */
    curFolded(){
      this.A.rev;
      const ss = this.A.steps || [];
      return ss.length ? (ss[ss.length - 1].folded || 0) : 0;
    },
    files(){ this.A.rev; return (this.A.result && this.A.result.files) || []; },
    resultOk(){ this.A.rev; return !!(this.A.result && this.A.result.ok); },
  },
  methods: {
    start: aiStart,
    stop: aiStop,
    saveBudget: aiSaveBudget,
    refresh(){ aiRefreshInfo(true); },          // 那颗「刷新」= 重新问一次宿主（不吃缓存）
    /* 回退到"开工前"那条快照（`V-236`）。默认 `only="all"`：缺的补上、变了的回退，       多出来的**不动**（和「文件管理 → 快照」里那个「只写回」一个语义）。 */
    rollback(){
      const snap = A.result && A.result.snapshot;
      if (!snap){ toast("这次没存快照，没得退。", true); return; }
      askConfirm("回退到开工前？",
        "把 <code>" + esc(shortPath(target)) + "</code> 回到快照 <code>" + esc(snap.id) +
        "</code> 那一刻（AI 动手之前）。<br>只写回：缺的补上、改过的退回去，<b>多出来的不动</b>；" +
        "覆盖前会留 <code>.bak</code>。",
        async () => {
          try{
            const r = await window.pywebview.api.backup_restore(snap.id, null, "all", false,
                                                               snap.group || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "回退失败"), true); return; }
            toast(r.msg || "回退好了");
          }catch(e){ toast("回退失败：" + (e && e.message ? e.message : e), true); }
        });
    },
    shortPath(p){ return String(p || "").replace(/^.*[\\/]pkgs[\\/]/, ""); },
    stepLine(s){ return "#" + s.n + " " + s.tool + " " + (s.brief || "") + (s.note ? "  → " + s.note : ""); },
    tokens(u){ return u ? (u.total_tokens || 0) : 0; },
    humanTokens(n){ return humanTokens(n); },
    /* 工具分类（`V-243`：一眼看出这一步是"读"还是"写"还是"跑"）—— 只影响配色和图标 */
    toolKind(t){
      if (["read_file", "grep", "list_dir"].indexOf(t) >= 0) return "read";
      if (["edit_file", "write_file"].indexOf(t) >= 0) return "write";
      if (t === "run_moss") return "run";
      if (t === "spec") return "spec";
      if (t === "done") return "done";
      if (t === "snap_clean") return "snap";
      return "misc";
    },
    toolIcon(t){
      return {read: "读", write: "写", run: "跑", spec: "约", done: "完",
              snap: "照", misc: "提"}[this.toolKind(t)] || "·";
    },
    runLine(r){
      const t = (r.started_text || "").slice(11, 19);
      return (r.ok ? "✅ " : "✗ ") + (r.task || "").slice(0, 42) +
             "　" + (r.steps || 0) + " 步 · " + humanTokens((r.usage || {}).total_tokens || 0) +
             (t ? " · " + t : "");
    },
    openRun(id){ aiOpenRun(id); },
    forgetRun(id){ aiForgetRun(id); },
    again(r){ AIR.task = r.task || ""; toast("需求已填回输入框 —— 改一改再点开始"); },
    useExample(t){ AIR.task = t; },
    /* Ctrl+Enter 发送（Enter 留给换行 —— 需求常常要写好几行） */
    onKey(e){
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter"){ e.preventDefault(); aiStart(); }
    },
    /* `V-242`：把"现在在干什么"说清楚 —— 等模型回话可能要十几秒，不说清楚就像卡死了。 */
    phaseText(){
      this.A.rev;
      if (this.A.phase === "thinking") return "等模型回话";
      if (this.A.phase === "waiting") return "模型还没回（网络慢或这次问得长）";
      if (this.A.phase === "tools") return "执行工具";
      return "跑着";
    },
  },
  mounted(){
    aiRefreshInfo();
    aiLoadRuns();
    aiPollOnce();
    /* 700ms 一跳：① 选中的包换了就重读信息；② 正在跑就拉步骤流。
       要不要改成事件驱动？不用 —— 命令行那一页也是轮询（run_poll 200ms），
       而且 loop 一步可能几秒，这个频率足够"看着它在动"。 */
    AIR.tick = setInterval(() => {
      const p = aiPackage();
      const id = (p && p.id) || "";
      if (id !== AIR.curId){ AIR.curId = id; aiRefreshInfo(); }
      if (AIR.running) aiPollOnce();
    }, 700);
  },
  template: `
  <div class="aiwrap">
    <div class="ai-head">
      <span class="ai-model" :class="{bad: !ready}">模型：{{ model }}</span>
      <span class="ai-where" v-if="target">干活的地方：{{ shortPath(target) || target }}</span>
      <span class="sp"></span>
      <!-- ★ V-240：预算就**一格**，而且**单位是百万**（token 本来就是这个量级，
           写 100000000 又长又容易数错；「宽度不够」也是这个原因）。
           默认 100（= 1 亿）：DeepSeek 闲时 + 缓存命中 99% 时 1 亿也就几块钱，
           上限设小了纯属给自己添堵 —— 要防的是"失控"，不是"正常干活"。 -->
      <span class="ai-bud" :title="'token 上限（百万）：默认 100 = 1 亿。烧到 ' + humanTokens(A.warnTokens) + ' 时劝它收尾，到顶就停手。'">
        上限<input type="number" min="0.5" max="20000" step="10" class="ai-bud-n"
                    v-model.number="A.maxMillions" :disabled="A.running" @change="saveBudget()">百万
      </span>
      <button class="btn" @click="refresh" title="重读模型 / 提示词 / 预算">刷新</button>
    </div>

    <p class="ai-warn" v-if="A.err">⚠ {{ A.err }}</p>
    <p class="ai-warn" v-else-if="!ready">⚠ {{ (info && info.why) || "还没配好 AI —— 去「设置 → AI」挑一家、把 key 填上（或 moss --ai-profile-set）。" }}</p>
    <p class="ai-warn" v-if="missing.length">⚠ 提示词文件缺了：{{ missing.join("、") }} —— 在 <code>system/ui/ai/prompts/</code> 或 <code>user_data/ai/prompts/</code> 里补上（不补也跑，只是 AI 少了那几条规矩）。</p>

    <div class="ai-target" v-if="pkg || A.where === 'new'">
      <label>在哪干活：</label>
      <select v-model="A.where" @change="refresh()">
        <option value="pkg" :disabled="!pkg">{{ pkg ? ("当前包 :" + pkg.id) : "（左边还没选包）" }}</option>
        <option value="new">新建包（user_data/pkgs）</option>
      </select>
      <span class="hint">v1 只允许写 <code>user_data/pkgs/**</code>；出厂件和宿主它碰不到。</span>
    </div>
    <p class="ai-warn" v-if="target && !canWrite && A.where === 'pkg'">
      ⚠ 这个包在 <code>system/</code> 下面 —— **它改不了**（v1 只许写 <code>user_data/pkgs/**</code>）。
      想让 AI 真动手：用「新建包」，或者选一个装在 <code>user_data/pkgs</code> 里的包。
    </p>
    <p class="ai-warn" v-else>左边先选一个包（或者选「新建包」）。</p>

    <textarea class="ai-task" v-model="A.task" spellcheck="false" :disabled="A.running"
      @keydown="onKey"
      placeholder="要它干什么？例如：给这个包加一个 --dry-run 参数，只打印不落盘。&#10;（它会自己读契约、改文件、跑一遍证明能跑，最后把改动和验收结果给你）&#10;Ctrl+Enter 开始，Enter 换行"></textarea>
    <!-- 空着的时候给几个例子（点一下填进去）—— 比一句干巴巴的占位话好用 -->
    <div class="ai-egs" v-if="!A.task && !A.running">
      <span>试试：</span>
      <span class="ai-eg" v-for="t in ['给这个包加一个 --dry-run 参数',
                                       '把这个包的错误提示改成中文人话',
                                       '看看这个包怎么用，总结成 5 行']"
            :key="t" @click="useExample(t)">{{ t }}</span>
    </div>

    <div class="ai-actions">
      <button class="btn primary" :disabled="A.running || A.busy || !ready" @click="start">开始</button>
      <button class="btn" :disabled="!A.running" @click="stop">停止</button>
      <span class="hint" v-if="A.running">{{ phaseText }} · {{ A.seconds }}s · 第 {{ curStep }} 步
        · 已烧 <b>{{ humanTokens(curTokens) }}</b> / {{ humanTokens(A.maxTokens) }} token
        <span v-if="curFolded" class="ai-folded"
              title="历史里较早的工具结果被折成一行（本地整理，不花模型调用）。DSH 的参数：上下文用到窗口的 80% 才开始压、最新的 16% 逐字保留。"
              >· 已折叠 {{ curFolded }} 条旧结果</span>
        <span v-if="A.promptTokens" class="ai-ctx"
              :title="'现在发出去的上下文 = ' + A.promptTokens + ' token；到 ' + A.compactAt + '（窗口 ' + A.context + ' 的 80%）才开始折叠旧结果'"
              >· 上下文 {{ humanTokens(A.promptTokens) }} / {{ humanTokens(A.compactAt) }}（{{ ctxPct }}%）</span></span>
      <span class="hint" v-else-if="A.result">上一次：{{ resultOk ? "✅ 验收通过" : "✗ 没通过" }}</span>
    </div>

    <div class="ai-steps" v-if="A.steps.length">
      <div class="ai-step" v-for="(s, i) in A.steps" :key="i" :class="'k-' + toolKind(s.tool)">
        <span class="ai-n">{{ s.n }}</span>
        <span class="ai-ico">{{ toolIcon(s.tool) }}</span>
        <b>{{ s.tool }}</b>
        <span class="ai-brief">{{ s.brief }}</span>
        <span class="ai-ms" v-if="s.ms >= 500">{{ (s.ms / 1000).toFixed(1) }}s</span>
        <span class="ai-note" v-if="s.note">{{ s.note }}</span>
      </div>
    </div>
    <p class="hint" v-else-if="!A.running">还没有跑过。它会：读契约 → 改文件 → 跑一次证明能跑 → 收工。<br>
      ★ 读文件：**一次最多 20000 字符（约 400 行）**，整个源文件一次读完就行（同一个文件读到第三回，它会把整篇给出来）。<br>
      ★ 历史折叠（**照 DSH 的参数**）：上下文用到**窗口的 80%** 才开始把较早的工具结果折成一行，
        最新的 **16%** 逐字保留；不到这条线一条都不折。折早了它看不见早先读过的内容，反而会重读。</p>

    <!-- V-243：跑过的任务 —— 存盘的，重启 moss 还在。点「看」翻出来，点「再跑」填回输入框 -->
    <div class="ai-runs" v-if="A.runs.length">
      <div class="ai-runs-h">
        <b>最近跑过（{{ A.runs.length }}）</b>
        <span class="sp"></span>
        <span class="ai-eg" @click="forgetRun('')" title="清空全部任务记录（只是回顾用的记录，不影响包）">清空</span>
      </div>
      <div class="ai-run" v-for="r in A.runs" :key="r.id" :class="{on: r.id === A.viewing}">
        <span class="ai-run-t" :title="r.task">{{ runLine(r) }}</span>
        <span class="sp"></span>
        <span class="ai-eg" @click="openRun(r.id)">看</span>
        <span class="ai-eg" @click="again(r)">再跑</span>
        <span class="ai-eg" @click="forgetRun(r.id)" title="删掉这一条记录">删</span>
      </div>
    </div>

    <div class="ai-result" v-if="A.result" :class="{ok: resultOk, bad: !resultOk}">
      <div class="ai-rhead"><span v-if="A.viewing" class="ai-old">历史记录</span>{{ resultOk ? "✅ 验收通过" : "✗ 没通过" }}<span
        v-if="A.result.reason && A.result.reason !== '验收通过'"> —— {{ A.result.reason }}</span></div>
      <!-- ★ V-236：开工前那条快照存了没、能不能一键回去。
           快照在「文件管理 → 快照」里带「AI」徽章（by=ai），跟你自己存的能分开。
           （★ 这条注释里不许有反引号 —— 模板字符串会被它截断，契约 §8 第 9 条。） -->
      <div class="ai-rsnap" v-if="A.result.snapshot">
        <span>开工前已存快照 <code>{{ A.result.snapshot.id }}</code>（AI 存的，列表里带「AI」徽章）</span>
        <button class="btn" @click="rollback()" title="回到这次动手之前（只写回：缺的补上、变了的回退）">回退到开工前</button>
      </div>
      <p v-if="A.result.summary" class="ai-rsum">{{ A.result.summary }}</p>
      <p v-if="A.result.caveats" class="ai-rcav">它自己标的不确定：{{ A.result.caveats }}</p>
      <div v-if="files.length" class="ai-rfiles">动过的文件：<span v-for="f in files" :key="f">{{ shortPath(f) }}　</span></div>
      <div class="ai-rtok" v-if="usage">
        token：输入 {{ usage.prompt_tokens }} / 输出 {{ usage.completion_tokens }} / 合计 {{ usage.total_tokens }}
        （上限 {{ humanTokens(A.maxTokens) }}）
        <span v-if="A.result.folded">· 折叠了 {{ A.result.folded }} 条旧结果</span>
      </div>
    </div>
  </div>`,
};

mountVue(MossAi, "#pane-ai");
