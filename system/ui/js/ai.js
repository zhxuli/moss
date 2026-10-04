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
  model: "",                   // `V-252`：顶栏那个模型下拉选中的（空 = 用配置里第一个）
  diskNoted: "",               // `V-249`：已经通知过"盘上变了"的那一次（免得每轮轮询都刷一遍）
  snapNoted: "",               // `V-250`：已经通知过"快照存好了"的那一条（同上）
  /* ★ `V-251`：**会话**那三件 —— 你原话「怎么还是找不到历史会话记录，一旦重新打开 moss
     只能重新再来 …… 没法继续上一次的聊天继续沟通」。
       · `contId`   正在接着哪条记录聊（空 = 新开一条；`aiStart` 把它交给宿主）
       · `contTask` 那条记录的任务原文（界面上那一行字要显示"接着哪句"）
       · `lastId`   这个包最近跑的那条（进来就认领，摆出它的步骤/结论）
     为什么默认就"接着"：每个包一条会话，跟 agent 客户端一个心思 —— 想重开点「新开」。 */
  contId: "", contTask: "", lastId: "", lastAdopted: "",
  curWhere: "",                // `V-251`：干活的"地方"也跟着包切换 —— 换地方就换会话
  /* ★ `V-253`（照稿子重排）：`sentTask` = 这次会话的那句指令（日志第一张「用户指令」卡用它）；
     `muted` = "清空"按下去时的步数（那之前的步骤不再显示，新的照常冒出来）。
     ★ `V-254`：`pickId` = 左上角那个会话下拉**现在选中的**那条（看得是哪条）。
       它和 `contId`（下一次跑要不要接着哪条）**分开** —— 老记录没有对话，能看不能接，
       以前把两个合成一个、又给选项加了 `disabled`，结果那个下拉**整个点不动**（你报的 bug）。 */
  sentTask: "", muted: 0, pickId: "",
});

function aiPackage(){ return cur && cur.id ? cur : null; }

/* `V-239`：给人看的 token 数字（32569 → 32.6k）—— 和 `ai_budget.human()` 一个口径。 */
function humanTokens(n){
  const v = Number(n || 0);
  if (v >= 1000000) return (v / 1000000).toFixed(2) + "M";
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return String(v);
}

/* ★ `V-257`：**中文单位**的 token 数（你原话："当数值比较大的时候应该变更单位为万 百万 亿这样"）——
   底栏那三个数用它；小数字照原样给。`title` 里另给精确值。 */
function cntok(n){
  const v = Math.round(Number(n) || 0);
  const neg = v < 0 ? "-" : "", a = Math.abs(v);
  const cut = (x, d) => {
    const s = (x).toFixed(d);
    return s.replace(/\.?0+$/, "");
  };
  if (a >= 100000000) return neg + cut(a / 100000000, 2) + "亿";
  if (a >= 10000) return neg + cut(a / 10000, 1) + "万";
  return neg + String(a);
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
      // ★ `V-252`：模型那一格的初值 —— 只在"没选过 / 选的那个这家没有了"时才跟着配置走，
      //   不然你每次刷新都被拨回第一个。
      const ms = AIR.info.models || [];
      if (AIR.info.model && (!AIR.model || (ms.length && ms.indexOf(AIR.model) < 0)))
        AIR.model = AIR.info.model;
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

/* `V-243`：把跑过的任务列出来（重启 moss 也在 —— 你说"历史记录不保存是不行的"）。
   ★ `V-251`：顺手把**这个包上次那条会话**挂上 —— 你原话「怎么还是找不到历史会话记录，
     一旦重新打开 moss 只能重新再来」。所以进来就：
       ① 把上次那条的步骤流/结论摆出来（一眼看到"上次聊到哪"）；
       ② 默认**接着它聊**（`AIR.cont`）—— 想开新的点那一行右边的「新开」。 */
async function aiLoadRuns(){
  try{
    const got = await window.pywebview.api.ai_runs(30);
    if (!got || !got.ok) return;
    AIR.runs = got.runs || [];
    if (!AIR.running) aiAdoptLast();
  }catch(e){ /* 读不到就空着，不吵人 */ }
}

/* 这个包（`workdir` 相同）上一次跑的那条 —— 没有就问当前的"全部文件"那个目录。 */
function aiLastRunFor(dir){
  const d = normDir(dir);
  const mine = (AIR.runs || []).filter(r => normDir(r.workdir) === d);
  return mine[0] || null;                 // 列表本来就是按时间倒序
}
function normDir(p){
  return String(p || "").replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}
/* 认领"上次那条"：摆出它的步骤/结论，并且**默认接着它聊**
   （跟 agent 客户端一个心思：一个包一条会话，你说下一句就是接着说；
     想重开点那一行右边的「新开一条」）。`AIR.contId` 已经有了就别抢。 */
async function aiAdoptLast(){
  const last = aiLastRunFor(aiWhereDir());
  AIR.lastId = (last && last.id) || "";
  if (last && last.cont && !AIR.contId && !AIR.pickId){
    AIR.contId = last.id;
    AIR.contTask = last.task || "";
    AIR.pickId = last.id;
    await aiOpenRun(last.id, true);
  }
}

/* 点「看」：把那条历史的步骤流/结论load进来（只看，不重跑）。
   `quiet`（`V-251`）：进这一页时**自动认领**上次那条用的，别弹提示。 */
async function aiOpenRun(id, quiet){
  try{
    const got = await window.pywebview.api.ai_run(id);
    if (!got || !got.ok || !got.run){ if (!quiet) toast("读不到这条记录", true); return; }
    const r = got.run;
    AIR.viewing = id;
    AIR.pickId = id;              // `V-254`：下拉跟着指到这份记录
    AIR.steps = r.steps || [];
    // ★ `V-253`：翻历史时，日志第一张卡还是**那次的任务原文**（照稿子的"用户指令"卡）
    AIR.sentTask = r.task || "";
    AIR.muted = 0;
    AIR.result = {ok: !!r.ok, reason: r.reason || "", summary: r.summary || "",
                  caveats: r.caveats || "", files: r.files || [], usage: r.usage || {},
                  snapshot: r.snapshot || null, run_id: r.id};
    AIR.rev++;
  }catch(e){ if (!quiet) toast("读不到这条记录：" + (e && e.message ? e.message : e), true); }
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
      // ★ `V-251`：跑完这一条就是"最新的那条会话" —— 下一次默认接着它聊
      //   （`contId` 指向新记录，输入框旁边那行字跟着换）。列表也要重读一次
      //   （新记录刚落盘）。
      if (res.run_id && res.run_id !== AIR.lastAdopted){
        AIR.lastAdopted = res.run_id;
        AIR.lastId = res.run_id;
        AIR.contId = res.run_id;
        AIR.pickId = res.run_id;          // `V-254`：左上角下拉跟着指到新这条
        AIR.contTask = (AIR.task || "").trim();
        aiLoadRuns();
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
  AIR.viewing = "";              // `V-251`：这次是新跑的，结果卡不该再挂"历史记录"那块牌子
  // ★ `V-253`：日志里第一张卡是**用户指令**（照稿子：`用户指令 message-circle`），
  //   而且"清空"过的那一段不再显示。
  AIR.sentTask = task;
  AIR.muted = 0;
  AIR.diskNoted = "";            // `V-249`：新任务 = 允许再通知一次"盘上变了"
  AIR.snapNoted = "";            // `V-250`：新任务 = 允许再通知一次"快照存好了"
  const cont = AIR.contId || ""; // `V-251`：接着哪条聊（空 = 新开一条）
  try {
    // ★ `V-237` 把 14 提到 24（读一个 395 行的文件就花了 11 步）；`V-238` 再按你的定夺改成
    //   **硬顶 200 + 每 50 步提醒一次**（都在上面那两格里，随手可改）。
    const got = await window.pywebview.api.ai_start(task, dir, AIR.maxTokens, cont, AIR.model || "");
    if (!got || !got.ok) { toast((got && got.msg) || "起不来。", true); AIR.busy = false; return; }
    AIR.running = true;
    toast((cont ? "接着上次那条聊" : "开了一条新会话") +
          "（模型 " + (got.model || "?") + "）—— 步骤会实时出现在下面。");
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
  data(){ return { A: AIR, focused: false, shake: false }; },
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
    /* ★ `V-252`（照你给的稿子重做这一页）：顶上那两个下拉要的东西 ——
       ① 这一家配了哪些模型（`ai_info.models`；只有一条就只显示那一条）；
       ② 这个包上次那条（「重新跑」按钮填回它的任务原文）。 */
    models(){
      this.A.rev;
      const ms = (this.A.info && this.A.info.models) || [];
      if (ms.length) return ms;
      return this.A.model ? [this.A.model] : [];
    },
    lastRun(){
      this.A.rev;
      return aiLastRunFor(aiWhereDir());
    },
    /* 会话那一栏现在长什么样（标题那一行 + 底部状态条都要） */
    sessionTitle(){
      this.A.rev;
      if (this.A.viewing){
        const r = (this.A.runs || []).filter(x => x.id === this.A.viewing)[0];
        return (r && r.task) || this.A.contTask || "历史会话";
      }
      return (this.A.sentTask || "").trim() || (this.A.task || "").trim() ||
             "新会话 —— 在下面写你要它干什么";
    },
    /* ★ `V-253`（照稿子那个 `切换历史会话` 下拉）：
       选中那条显示成 `当前: <任务>`，别的都是 `历史: <任务>`，最后一项是 `+ 新建空白会话`。
       ★ `V-254`：**一个都不 disable** —— 老记录（没存对话）也能点开看，
         点了会自动退回"能看不能接"（见 `pickSession`）。 */
    sessCurrent(){
      this.A.rev;
      const id = this.A.pickId || "";
      if (!id) return null;
      return (this.A.runs || []).filter(r => r.id === id)[0] || null;
    },
    sessOthers(){
      this.A.rev;
      const id = this.A.pickId || "";
      return (this.A.runs || []).filter(r => r.id !== id);
    },
    /* ★ `V-253`：日志流里的卡片（照稿子：每一步一张卡 + 第一张是"用户指令"）。
       `muted` 之前的不再显示（"清空"按下去就是这个效果）。 */
    logCards(){
      this.A.rev;
      const out = [];
      const task = (this.A.sentTask || "").trim();
      if (task){
        out.push({key: "user", kind: "user", icon: "message-circle",
                  color: "var(--aib-primary)", action: "用户指令", tool: "",
                  meta: this.A.running ? "刚刚" : "这次会话", path: task});
      }
      const steps = (this.A.steps || []).slice(this.A.muted || 0);
      steps.forEach((s, i) => {
        out.push({key: "s" + (s.n || i), kind: "step", icon: this.stepIcon(s.tool),
                  color: this.kindColor(s.tool), action: this.stepTitle(s), tool: s.tool,
                  meta: this.stepMeta(s), path: this.stepPath(s)});
      });
      return out;
    },
    /* 底部状态条左半边（照稿子：`✗ 上次未通过` + `开工快照: <tag>`） */
    lastText(){
      this.A.rev;
      if (!this.A.result) return "还没跑过";
      return this.resultOk ? "上次通过" : "上次未通过";
    },
    lastIcon(){
      this.A.rev;
      if (!this.A.result) return "circle-slash";
      return this.resultOk ? "check" : "x-circle";
    },
    lastColor(){
      this.A.rev;
      if (!this.A.result) return "var(--aib-text-light)";
      return this.resultOk ? "var(--aib-success)" : "var(--aib-danger)";
    },
    snapId(){
      this.A.rev;
      const s = this.A.result && this.A.result.snapshot;
      return (s && s.id) || "";
    },
    /* 底部状态条右半边：`Token 消耗: 输入 / 输出 / 合计`（照稿子那三个数）
       ★ `V-257`：数字大了换中文单位（万/亿），精确值放 `title`。 */
    tokLine(){
      this.A.rev;
      const u = this.usage;
      if (!u) return "— / — / —";
      return cntok(u.prompt_tokens) + " / " + cntok(u.completion_tokens) + " / " +
             cntok(u.total_tokens);
    },
    tokTip(){
      this.A.rev;
      const u = this.usage;
      if (!u) return "";
      return "输入 " + (u.prompt_tokens || 0) + " · 输出 " + (u.completion_tokens || 0) +
             " · 合计 " + (u.total_tokens || 0) + " token";
    },
  },
  watch: {
    /* ★ `V-252`：步骤/结论来了就**跟着往下滚**（agent 控制台该有的样子）。
       ★ 但你自己往上翻看历史的时候不抢：只有"本来就贴着底"才跟。
       （照稿子里那个"占位符，模拟滚动到底部"的意思做的。） */
    "A.steps"(){ this.followLog(); },
    "A.result"(){ this.followLog(); },
    /* ★ `V-253`：需求被别处改过（「重跑」填回输入框 / 「清空」清掉）⇒ 文本域重新量一次高度 */
    "A.task"(){ this.$nextTick(() => this.autoGrow()); },
  },
  methods: {
    stop: aiStop,
    saveBudget: aiSaveBudget,
    refresh(){ aiRefreshInfo(true); },          // 那颗「刷新」= 重新问一次宿主（不吃缓存）
    /* 回退到"开工前"那条快照（`V-236`）。默认 `only="all"`：缺的补上、变了的回退，       多出来的**不动**（和「文件管理 → 快照」里那个「只写回」一个语义）。 */
    rollback(){
      // ★ `V-257`：这里原来写的是裸 `A` / `target` / `shortPath` —— 那是**模块级/计算属性**
      //   的东西，在方法作用域里一个都不存在 ⇒ 点底栏那个"开工快照"标签直接报
      //   `A is not defined`（你报的那个错）。方法里一律走 `this.`。
      const A = this.A, target = this.target, snap = A.result && A.result.snapshot;
      if (!snap){ toast("这次没存快照，没得退。", true); return; }
      askConfirm("回退到开工前？",
        "把 <code>" + esc(this.shortPath(target)) + "</code> 回到快照 <code>" + esc(snap.id) +
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
    /* ★ `V-253`（照稿子）：
       ① 文本域**自适应高度**（56→200，边打边长）；
       ② 「清空」把日志清掉（那之前的步骤不再显示，新的照常冒出来）；
       ③ 空着点发送 → 输入框**抖一下**（稿子里的 `error-shake`），不是只弹个提示。 */
    autoGrow(){
      this.shake = false;        // 稿子：一开始打字就把"抖"那个状态摘掉
      const ta = this.$refs.ta;
      if (!ta) return;
      ta.style.height = "56px";
      ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
    },
    resetLogs(){
      AIR.muted = (AIR.steps || []).length;
      AIR.result = null; AIR.sentTask = ""; AIR.viewing = "";
      AIR.task = "";
      AIR.rev++;
      this.$nextTick(() => this.autoGrow());
    },
    doShake(){
      this.shake = false;
      this.$nextTick(() => {
        this.shake = true;
        setTimeout(() => { this.shake = false; }, 520);
      });
    },
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
    /* ★ `V-252`：步骤卡左边那个小图标（`ico()` 的名字）—— 按工具分。
       ★★ 为什么非要做成方法：这个 Vue build 的模板**不从全局作用域取标识符**
          （`window.ico` 明明是函数也白搭 —— 实测报的是 `ico is not a function`），
          所以模板里要用的东西都得是"组件自己的方法 / 计算属性"，或者挂在
          `mountVue(..., {ico: ico})` 那种 `globalProperties` 上（文件末尾那行就是）。 */
    stepIcon(t){
      // 稿子里那几张卡用的就是这几个名字（`list_dir` → `folder-search`、`read_file` → `file-text`、
      // 写文件 → `file-code`）—— 照它来；其余工具按同一族补。
      return {list_dir: "folder-search", read_file: "file-text", grep: "search",
              edit_file: "file-code", write_file: "file-code", run_moss: "play",
              spec: "book-open", done: "check", snap_clean: "moss-camera"}[t] || "code";
    },
    runLine(r){
      const t = (r.started_text || "").slice(11, 19);
      return (r.ok ? "✅ " : "✗ ") + (r.task || "").slice(0, 42) +
             "　" + (r.steps || 0) + " 步 · " + humanTokens((r.usage || {}).total_tokens || 0) +
             (t ? " · " + t : "");
    },
    /* ★ `V-253`（照稿子）：新卡片来了就**滚到底**（稿子里是 `scrollToBottom()`，
       配合 CSS 的 `scroll-behavior:smooth` 做平滑滚动）。
       ★ 上一版我自己加了个"你往上翻就不抢"的判断 —— 稿子没这规矩，撤掉。 */
    followLog(){
      // `window.__followN`：探针的把手（无头浏览器里**平滑滚动不跑动画**，量 scrollTop 量不出来，
      // 所以断言"确实喊了跟滚"这一下 —— 真机上配合 CSS 的 scroll-behavior 就是平滑到底）。
      window.__followN = (window.__followN || 0) + 1;
      this.$nextTick(() => {
        const el = (this.$refs && this.$refs.log) ||
                   (this.$el && this.$el.querySelector(".ai-log"));
        if (!el) return;
        el.scrollTo({top: el.scrollHeight, behavior: "smooth"});
      });
    },
    openRun(id){ aiOpenRun(id); },
    forgetRun(id){ aiForgetRun(id); },
    /* ★ `V-253`：底部那颗「发送指令」—— 稿子里的行为是"空着点不给发 + 抖一下" */
    start(){
      const task = String(this.A.task || "").trim();
      if (!task){ this.doShake(); toast("先写一句你要它干什么。", true); return; }
      if (this.A.busy) return;
      aiStart();
    },
    /* ★ `V-252`：顶栏那两个下拉的处理器 —— 「会话」和「模型」都是"下一句话生效"的设置。 */
    /* ★ `V-254`（修你报的"点了点不动"）：选一条会话 = **打开看它**；能接着聊的顺手接上，
       老记录（那时候还没存对话）就明说"只能看、接不上"。
       —— 以前这里所有选项都是 `disabled`（老记录 `cont=false`），整个下拉等于死的。 */
    pickSession(){
      const id = this.A.pickId || "";
      if (!id){
        AIR.viewing = ""; AIR.sentTask = ""; AIR.steps = []; AIR.result = null;
        AIR.contId = ""; AIR.contTask = ""; AIR.lastId = ""; AIR.muted = 0;
        AIR.rev++;
        toast("新会话：下一条不带之前的对话");
        return;
      }
      const r = (AIR.runs || []).filter(x => x.id === id)[0];
      if (!r) return;
      aiOpenRun(id);
      if (r.cont){
        AIR.contId = id; AIR.contTask = r.task || "";
        toast("接着这条聊 —— 在下面写下一句，点发送");
      } else {
        AIR.contId = ""; AIR.contTask = "";
        toast("这条是更早的记录（当时还没存对话）—— 只能看，接不上", true);
      }
    },
    pickModel(){
      toast("这次用 " + (AIR.model || "?") + " 跑（换模型连带换上下文窗口）");
    },
    /* ★ `V-257`：下拉点不开是**点在了外框上**（`.custom-select` 有 6×12 内边距、还有一个图标，
       真正能弹出列表的只有里面那个 `<select>` 的文字那一小块）。补一个：点框子的任何地方
       都替你把下拉打开（Chromium 的 `showPicker()`；不支持就退化成 focus）。 */
    openSel(ev){
      const box = ev && ev.currentTarget;
      const sel = box && box.querySelector && box.querySelector("select");
      if (!sel || sel.disabled) return;
      if (ev && ev.target === sel) return;          // 点在 select 自己身上，浏览器已经弹了
      try{
        if (sel.showPicker) sel.showPicker();
        else sel.focus();
      }catch(e){ try{ sel.focus(); }catch(e2){} }
    },
    /* ★ `V-257`：token 数大了就换中文单位（万 / 亿）—— 底栏那三个数用 */
    cntok(n){ return cntok(n); },
    /* ★ `V-253`（照稿子）：步骤卡那三样 —— 人话动作 / 右边那格 meta / 里面那行等宽路径。
       工具名由模板里那个 `b` 显示，别在这儿再拼一遍（不然是"改文件 edit_file edit_file"）。 */
    stepTitle(s){
      const zh = {list_dir: "读目录", read_file: "读文件", grep: "搜内容", edit_file: "改文件",
                  write_file: "写文件", run_moss: "跑一遍", spec: "查契约", done: "收尾",
                  snap_clean: "清快照"};
      return zh[(s && s.tool) || ""] || "其它";
    },
    /* 右边那格（稿子里是"共 89 行, 这是 1-89 行"或时间）：我们的 note 就是这类信息 */
    stepMeta(s){
      const bits = [];
      if (s && s.note) bits.push(String(s.note));
      if (s && s.ms >= 500) bits.push((s.ms / 1000).toFixed(1) + "s");
      if (!bits.length && s && s.n) bits.push("第 " + s.n + " 步");
      return bits.join(" · ");
    },
    /* 动作那一行的颜色（稿子里"写文件"用绿色、别的用蓝色） */
    kindColor(t){
      const k = this.toolKind(t);
      if (k === "write") return "var(--aib-success)";
      if (k === "run") return "var(--aib-warning)";
      return "var(--aib-primary)";
    },
    /* 步骤卡第二行：把 brief 里那个 JSON 拆成人看的**路径**（`{"path": "…\\run.py"}` → `…\run.py`） */
    stepPath(s){
      const b = String((s && s.brief) || "");
      try{
        const j = JSON.parse(b);
        if (j && typeof j === "object"){
          const bits = [];
          if (j.path) bits.push(String(j.path));
          if (j.find !== undefined) bits.push("把 " + JSON.stringify(String(j.find)).slice(0, 40) + " 换掉");
          if (j.args) bits.push("moss " + String(j.args));
          if (j.section) bits.push("契约：" + String(j.section));
          if (j.id) bits.push(String(j.id));
          if (j.summary) bits.push(String(j.summary).slice(0, 80));
          if (bits.length) return bits.join("　");
        }
      }catch(e){ /* 不是 JSON 就原样显示 */ }
      return b;
    },
    /* ★ `V-251`：接着这条聊 —— 摆出它的步骤/结论，并且把「下一句」接在它后面 */
    contThis(r){
      AIR.contId = r.id; AIR.contTask = r.task || "";
      aiOpenRun(r.id);
      toast("接着这条聊（它还记着之前 " + (r.msgs || 0) + " 条对话）—— 写下一句，点开始");
    },
    /* 新开一条：下一条任务不带老对话 */
    newChat(){
      AIR.contId = ""; AIR.contTask = "";
      toast("下一条按**新会话**跑（老记录还在，随时能接着聊）");
    },
    again(r){ AIR.task = r.task || ""; AIR.contId = ""; AIR.contTask = "";
              toast("需求已填回输入框（按新会话跑）—— 改一改再点发送"); },
    /* ★ `V-253`（照稿子）：**Enter 发送、Shift+Enter 换行**（稿子的占位话就是这么写的）。
       （老写法是 Ctrl+Enter 发送、Enter 换行 —— 按稿子改了。） */
    onKey(e){
      if (e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        this.start();
      }
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
      const where = AIR.where;
      /* ★ `V-251`：**换了干活的地方 = 换了一条会话** —— 会话是"一个包一条"，
         切包时必须把接着聊那件事清掉（不然会把别的包的对话塞进这次任务），
         然后去认领新包上次跑的那条。 */
      if (id !== AIR.curId || where !== AIR.curWhere){
        AIR.curId = id; AIR.curWhere = where;
        AIR.contId = ""; AIR.contTask = ""; AIR.viewing = "";
        AIR.steps = []; AIR.result = null; AIR.lastId = ""; AIR.lastAdopted = "";
        AIR.sentTask = ""; AIR.muted = 0; AIR.pickId = "";
        aiRefreshInfo();
        aiLoadRuns();
      }
      if (AIR.running) aiPollOnce();
    }, 700);
    /* ★ `V-253`（照稿子）：刚进来时文本域是 56px，等一帧量一下（内容长的话自动长高） */
    this.$nextTick(() => this.autoGrow());
  },
  template: `
  <div class="aiwrap">
    <div class="ai-workspace">

      <!-- 顶部配置栏（照稿子：会话 / 工作区 / 上限 / 模型） -->
      <header class="top-toolbar ai-bar">
        <div class="toolbar-group">
          <div class="custom-select" title="切换历史会话" @click="openSel($event)">
            <span v-html='ico("history", "i")'></span>
            <select class="ai-sess" v-model="A.pickId" :disabled="A.running" @change="pickSession()">
              <option v-if="sessCurrent" :value="sessCurrent.id"
                      >当前: {{ (sessCurrent.task || "").slice(0, 30) }}</option>
              <option v-for="r in sessOthers" :key="r.id" :value="r.id"
                      >历史: {{ (r.task || "").slice(0, 30) }}</option>
              <option disabled>──────────</option>
              <option value="">+ 新建空白会话</option>
            </select>
          </div>

          <div class="custom-select" title="在哪干活（v1 只允许写 user_data/pkgs 下面）" @click="openSel($event)">
            <span v-html='ico("folder-tree", "i")'></span>
            <select v-model="A.where" :disabled="A.running" @change="refresh()">
              <option value="pkg" :disabled="!pkg">{{ pkg ? ("当前包 :" + pkg.id) : "（左边还没选包）" }}</option>
              <option value="new">整个项目区</option>
            </select>
          </div>
        </div>

        <div class="toolbar-group">
          <div class="token-input-group ai-bud"
               :title="'token 上限（单位：百万）。默认 100 = 1 亿 token。烧到 ' + humanTokens(A.warnTokens) + ' 时劝它收尾，到顶就停手。'">
            <span v-html='ico("gauge", "i")'></span> token 上限
            <input type="number" step="10" min="0.5" max="20000" value="100" class="ai-bud-n"
                   v-model.number="A.maxMillions" :disabled="A.running" @change="saveBudget()"> 百万
          </div>

          <div class="custom-select select-model" @click="openSel($event)"
               :title="'这次用哪个模型。这家配了 ' + models.length + ' 个；换模型连带换上下文窗口。'">
            <span v-html='ico("sparkles", "i")'></span>
            <select class="ai-model" v-model="A.model" :disabled="A.running || !models.length"
                    @change="pickModel()">
              <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
              <option v-if="!models.length" value="">（还没配 AI）</option>
            </select>
          </div>
        </div>
      </header>

      <p class="ai-warn" v-if="A.err">⚠ {{ A.err }}</p>
      <p class="ai-warn" v-else-if="!ready">⚠ {{ (info && info.why) || "还没配好 AI —— 去「设置 → AI」挑一家、把 key 填上（或 moss --ai-profile-set）。" }}</p>
      <p class="ai-warn" v-if="missing.length">⚠ 提示词文件缺了：{{ missing.join("、") }} —— 在 <code>system/ui/ai/prompts/</code> 或 <code>user_data/ai/prompts/</code> 里补上（不补也跑，只是 AI 少了那几条规矩）。</p>
      <p class="ai-warn" v-if="target && !canWrite && A.where === 'pkg'">
        ⚠ 这个包在 <code>system/</code> 下面 —— <b>它改不了</b>（v1 只许写 <code>user_data/pkgs/**</code>）。
        想让 AI 真动手：把上面「在哪干活」换成整个项目区，或者选一个装在 <code>user_data/pkgs</code> 里的包。
      </p>

      <!-- 中间日志流 -->
      <main class="log-container ai-log" ref="log">
        <div class="session-title">
          <span v-html='ico("message-square", "i")' style="color:var(--aib-primary);display:flex"></span>
          {{ sessionTitle }}
        </div>

        <div class="step-card ai-step" v-for="(c, i) in logCards" :key="c.key"
             :class="c.kind === 'user' ? '' : ('k-' + toolKind(c.tool))"
             :data-tool="c.tool || ''">
          <div class="step-icon" v-html='ico(c.icon, "i")'></div>
          <div class="step-content">
            <div class="step-header">
              <span class="step-action" :style="{color: c.color}">{{ c.action }} <b>{{ c.tool }}</b></span>
              <span class="step-meta">{{ c.meta }}</span>
            </div>
            <span class="code-path">{{ c.path }}</span>
            <span class="step-meta" v-if="c.note">{{ c.note }}</span>
          </div>
        </div>

        <!-- 结论卡（稿子里没有；这一页必须有：验收过没过 + 改了什么 + 能不能退回去） -->
        <div class="ai-result" v-if="A.result" :class="{ok: resultOk, bad: !resultOk}">
          <div class="ai-rhead"><span v-if="A.viewing" class="ai-old">历史记录</span>{{ resultOk ? "✅ 验收通过" : "✗ 没通过" }}<span
            v-if="A.result.reason && A.result.reason !== '验收通过'"> —— {{ A.result.reason }}</span></div>
          <div class="ai-rsnap" v-if="A.result.snapshot">
            <span>开工前已存快照 <code>{{ A.result.snapshot.id }}</code>（AI 存的，列表里带「AI」徽章）</span>
            <button class="btn btn-outline" @click="rollback()"
                    title="回到这次动手之前（只写回：缺的补上、变了的回退）">回退到开工前</button>
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

        <p class="ai-empty" v-if="!logCards.length && !A.result">
          还没有跑过。它会：读契约 → 改文件 → 跑一次证明能跑 → 收工。
        </p>

        <!-- 思考中指示器（永远在最下方）——照稿子：一个呼吸点 + 一行字。
             进度（秒/步/token）塞进 title，别往那行字里加东西（稿子就那一句）。 -->
        <div class="thinking-indicator" :class="{on: A.running}"
             :title="A.running ? (A.seconds + 's · 第 ' + curStep + ' 步 · 已烧 ' + humanTokens(curTokens) +
                     ' / ' + humanTokens(A.maxTokens) + ' token' +
                     (curFolded ? (' · 已折叠 ' + curFolded + ' 条旧结果') : '') +
                     (A.promptTokens ? (' · 上下文 ' + humanTokens(A.promptTokens) + ' / ' +
                                        humanTokens(A.compactAt) + '（' + ctxPct + '%）') : '')) : ''">
          <div class="pulse-dot"></div> AI 正在思考并执行...
        </div>
      </main>

      <!-- 底部输入与状态栏 -->
      <footer class="bottom-area ai-foot">
        <div class="prompt-box ai-box" :class="{focused: focused, 'error-shake': shake}">
          <textarea class="prompt-textarea ai-task" ref="ta" v-model="A.task" spellcheck="false"
            :disabled="A.running" @input="autoGrow" @focus="focused = true" @blur="focused = false"
            @keydown="onKey"
            placeholder="在此输入指令... (按 Enter 发送，Shift+Enter 换行)"></textarea>

          <div class="prompt-toolbar">
            <div class="tips">
              <span v-html='ico("lightbulb", "i")' style="color:var(--aib-warning);display:flex"></span>
              支持使用自然语言描述你需要的代码修改
            </div>
            <div style="display:flex;gap:8px" class="ai-actions">
              <button class="btn btn-outline" @click="resetLogs()"
                      v-html='ico("rotate-ccw", "i") + " 清空"'></button>
              <button class="btn btn-outline" v-if="A.running" @click="stop"
                      v-html='ico("square", "i") + " 停止"'></button>
              <button class="btn btn-primary primary ai-send" :disabled="A.running || A.busy || !ready"
                      @click="start"
                      v-html='A.running ? ico("loader-2", "i spin") + " 执行中" : ico("send", "i") + " 发送指令"'></button>
            </div>
          </div>
        </div>

        <div class="status-footer">
          <div style="display:flex;align-items:center;gap:8px">
            <span :style="{color: lastColor, fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px'}">
              <span v-html='ico(lastIcon, "i")'></span> {{ lastText }}
            </span>
            <span style="color:var(--aib-border-color)">|</span>
            <span v-if="snapId">开工快照:
              <span class="snapshot-tag" title="点击回滚到此快照" @click="rollback()">{{ snapId }}</span></span>
            <span v-else>开工快照: —</span>
          </div>
          <div :title="tokTip">
            Token 消耗: <span style="font-family:'JetBrains Mono',ui-monospace,Consolas,monospace">{{ tokLine }}</span>
          </div>
        </div>
      </footer>

    </div>
  </div>`,
};

/* ★★ `V-252`：第三个参数**不能省** —— 这一页的模板里用了 `ico(...)`（会话 / 模型 /
   步骤卡那些小图标），而这个 Vue build 编译模板时**不做 `with(this)` 回退**：模板里
   的标识符只能在"组件实例 / 计算属性 / 方法 / `globalProperties`"里找。`ico` 虽然在
   `vendor/lucide.js` 里是个全局函数（`window.ico` 查得到），模板里照样报
   `ico is not a function` —— 实测踩到，查了半天。别的页要这么干：
   `js/console.js` 也是 `mountVue(MossConsole, "#pane-console", {ico: ico})`。 */
mountVue(MossAi, "#pane-ai", {ico: ico});


