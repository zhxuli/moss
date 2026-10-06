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
  /* ★ `V-258`：**一轮一轮攒着的会话**（你原话："继续对话的时候只显示最后一次，前面的会清空，
     我需要能一直看到，并且允许我折叠某个会话"）。
     一轮 = `{key, task, at, steps: [], result: null, folded: false}`
       · `steps` 是这一轮的步骤卡（**各轮各存一份**，新一轮不会把上一轮冲掉）
       · `result` 是这一轮的结论卡（没跑完就是 null）
       · `folded` 是"这一轮折叠了"（点那一轮的「用户指令」卡切换）
     `cur` = 正在跑的那一轮的下标（`-1` = 没在跑）。 */
  turns: [], cur: -1, turnSeq: 0,
  /* ★ `V-261`：按住 **Alt** 时浮出来的"我说过的话"导航（你原话：按 alt 显示这个会话历史里
     每一条我说的话，点其中某一条就快速定位到那一轮）。 */
  altOn: false,
  /* ★ `V-280`：**它自己造的工具**（你说的是"AI 需要的能力不该塞进插件列表"那一层）。
     用户看不见它 —— 不在插件页、不是 `:别名`、不算包；只在 AI 页这儿**折叠着**露一行。
      · `selfTools` 宿主给的三堆：mine（已允许）/ pending（等你点允许）/ broken（写坏了）
      · `selfOpen`  那个小块展开没有（有"待批准"的时候自动展开一次，好让你看见）
      · `selfWho` / `selfText`  「看一眼」展开的是哪只、内容是什么 */
  selfSkills: {skills: [], from_pkgs: [], broken: []},
  selfOpen: false, selfWho: "", selfText: "",
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

/* ★ `V-260`：**把记录按"链"归并**。
   一次会话 = 一条链（第一条是链头，后面每一轮都 `continued_from` 指着上一条）。
   你原话："一个会话 3 个问题，它直接这个列表里面都有他们 —— 按说实际上就显示第一个，
   因为其他的两个不是独立会话，不应该显示才对"。
   所以：列表**只留链头**，但选项的**值取链尾**（最新那条）—— 这样"接着聊"带的是整条会话。
   返回 `[{head, tail, turns}]`（按链尾时间倒序）。 */
function aiChains(runs){
  const all = runs || [];
  const out = [];
  /* ★★ `V-262`：**链头 = 没有 `continued_from` 的那条**（没人接着它 = 它是这条会话的第一句）。
     我上一版写的是 `!hasChild[r.id]`（"没人接在它后面"）—— 那选出来的**正好是链尾**
     （最后一个问题）：于是下拉里的标题是最后那句、`turns` 永远从 1 开始数。你报的
     "当前标题是最后一个问题，而不是第一个问题"就是它。 */
  all.filter(r => !r.continued_from).forEach(head => {
    let cur = head, turns = 1, guard = 0;
    while (guard++ < 500){
      const next = all.filter(r => r.continued_from === cur.id)[0];
      if (!next) break;
      cur = next; turns++;
    }
    out.push({head: head, tail: cur, turns: turns});
  });
  // 列表按"最新那条"倒序（链头顺序不一定等于链尾顺序）
  return out.sort((a, b) => String(b.tail.id).localeCompare(String(a.tail.id)));
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
/* ★ `V-262`：**把一整条会话读回来**（链头 → 这条）—— 重启 moss 之后进这一页，
   看到的是**整段对话**（几轮都在），而不是只有最后一轮。
   （以前只调 `ai_run(最后那条)` ⇒ 标题变成最后那个问题、前面的轮次一个都不显示。）
   `quiet`：开机自动认领时用，失败别弹提示。 */
async function aiOpenThread(id, quiet){
  try{
    const got = await window.pywebview.api.ai_thread(id);
    if (!got || !got.ok || !(got.turns || []).length){
      if (!quiet) toast("读不到这条会话", true);
      return false;
    }
    AIR.turns = got.turns.map((t, i) => ({
      key: "h" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1),
      // ★ `V-279`：**每一轮自己的记录 id** 得带上 —— 抬头那两颗「编辑 / 删除」按钮
      //   要拿它去问宿主"删这一轮会删掉什么、回退到哪条镜像"。
      id: t.id || "",
      task: t.task || "", at: (t.at || "").slice(5, 16),
      steps: t.steps || [], result: t.result || null, folded: false,
      note: (t.result && t.result.continue_note) || "",
    }));
    AIR.cur = -1;
    AIR.muted = 0;
    const tail = got.tail || id;
    AIR.lastId = tail; AIR.lastAdopted = tail;
    AIR.pickId = tail;
    if (got.cont){ AIR.contId = tail; AIR.contTask = (AIR.turns[AIR.turns.length - 1] || {}).task || ""; }
    else { AIR.contId = ""; AIR.contTask = ""; }
    // 底栏那两个"最近一轮"的镜像（`A.steps` / `A.result` 还在被那几个计算属性读）
    const last = AIR.turns[AIR.turns.length - 1] || null;
    AIR.steps = (last && last.steps) || [];
    AIR.result = (last && last.result) || null;
    AIR.rev++;
    return true;
  }catch(e){
    if (!quiet) toast("读不到这条会话：" + (e && e.message ? e.message : e), true);
    return false;
  }
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
    // ★ `V-262`：认领的是**整条会话**（重启后也把前几轮摆出来），不是只有最后那一条
    await aiOpenThread(last.id, true);
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
    AIR.result = {ok: !!r.ok, kind: r.kind || "work", reason: r.reason || "", summary: r.summary || "",
                  caveats: r.caveats || "", files: r.files || [], usage: r.usage || {},
                  snapshot: r.snapshot || null, run_id: r.id};
    // ★ `V-258`：翻历史 = **一轮**（前面那些轮先收起来，别和这份记录混在一起）
    //   `V-279`：`id` 照样带上（翻历史时抬头那两颗按钮也能用）
    AIR.turns = [{key: "v" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1), id: r.id || "", task: r.task || "",
                  at: (r.started_text || "").slice(5, 16) || "历史记录",
                  steps: AIR.steps, result: AIR.result, folded: false}];
    AIR.cur = 0;
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

/* ---------------------------------------------------------------- 技能（`V-280`/`V-281`）
   ★ 这一层的来由（你 2026-10-05 的话）：AI 干活时缺一只手（比如"给某个界面截屏"），
     这种事**用户自己不需要**（他直接看屏幕就行），可 AI 需要、还要频繁调。
     塞进 `user_data/pkgs/` 会让插件列表变得很乱 —— 所以：
       · **技能 = 一个包**（`pkg.json` + 入口 + `icon.svg`），id **必须 `--` 开头**；
       · 本体住在 **`:skill` 插件的数据目录**里（`user_data/state/skill/<--名字>/`）——
         跟 exec 把命令放 `state/exec/cmds/` 一个道理，只是技能是**一个目录**不是塞进 JSON；
       · 插件列表里**一个都不多**（这一页只露一行灰字，管理在 `:skill` 那个界面里）。
   ★ 规矩：`pkg.json` 里的 `ai.expose` 只是**声明**；**授权**在
     `user_data/ai/skills_allow.json`（它写不到那个文件）而且**绑指纹** ——
     它事后改了 pkg.json / 入口 / 图标，授权作废、退回"待批准"。
   ★ 它这一次新造的技能**这一次跑用不上**（工具表是开工那一刻定死的）—— 这不是不方便，
     是"人点同意"这道闸本来就该在两次跑之间。 */
async function aiLoadSkills(){
  try{
    const got = await window.pywebview.api.ai_skills();
    if (!got || !got.ok) return;
    AIR.selfSkills = got;
    // 有待批准的：**自动展开一次**（好让你看见），别指望你自己去点开
    if (skillPend(got).length) AIR.selfOpen = true;
    AIR.rev++;
  }catch(e){ /* 读不到就不显示那一块，不吵人 */ }
}
/* 这几条小工具在组件和模块两边都要用，就放模块级（`selfXxx` 那些计算属性调它们）。
   ★ 为什么还要并上 `broken`：宿主给的 `broken` 本来就是 `skills`/`from_pkgs` 的子集，
     但"只给 broken 不给 skills"这种形状也得能吃（探针/预览就造过这种），所以按 id 去重并一下。 */
function skillAll(got){
  got = got || {};
  const out = [], seen = {};
  (got.skills || []).concat(got.from_pkgs || []).concat(got.broken || []).forEach(w => {
    if (!w || !w.id || seen[w.id]) return;
    seen[w.id] = 1;
    out.push(w);
  });
  return out;
}
function skillPend(got){ return skillAll(got).filter(w => !(w.problems || []).length && !w.allowed); }
function skillOk(got){ return skillAll(got).filter(w => !(w.problems || []).length && w.allowed); }

async function aiSkillLook(w){
  if (!w) return;
  if (AIR.selfWho === w.id){ AIR.selfWho = ""; AIR.rev++; return; }   // 再点一下 = 收起
  try{
    const got = await window.pywebview.api.ai_skill_read(w.id);
    if (!got || !got.ok){ toast((got && got.msg) || "读不出来", true); return; }
    AIR.selfWho = w.id;
    AIR.selfText = Object.keys(got.text || {}).map(
      rel => "=== " + rel + " ===\n" + got.text[rel]).join("\n\n");
    AIR.rev++;
  }catch(e){ toast("读不出来：" + (e && e.message ? e.message : e), true); }
}
async function aiSkillAllow(w, yes){
  if (!w) return;
  try{
    const got = await window.pywebview.api.ai_skill_allow(w.id, !!yes);
    toast((got && got.msg) || ((got && got.ok) ? "好了" : "没成"), !(got && got.ok));
    await aiLoadSkills();
  }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
}
function aiSkillRm(w){
  if (!w) return;
  askConfirm("删掉这只技能？",
    "删掉 <code>" + esc(w.id) + "</code> 的整个目录（<code>" + esc(w.dir) +
    "</code>，" + (w.files_n || 0) + " 个文件）？它写的东西一起没。",
    async () => {
      try{
        const got = await window.pywebview.api.ai_skill_rm(w.id, true);
        toast((got && got.msg) || "删了", !(got && got.ok));
        await aiLoadSkills();
      }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
    });
}
/* 「管理技能」= 把 `:skill` 那个插件的界面嵌出来（图标墙 + 详情 + 转为插件 / 删除都在那边） */
function aiOpenSkills(){
  // ★ 用 `DATA`（宿主给的那份包表），**不是 `state`** —— 界面里没有 `state` 这个全局，
  //   之前 `typeof state !== "undefined"` 恒为假 ⇒ 包表为空 ⇒ 误报"找不到技能管理器"。
  const ps = (typeof DATA !== "undefined" && DATA && DATA.packages) || [];
  const p = ps.filter(x => x.id === "skill" ||
                           (x.aliases || []).indexOf("skill") >= 0)[0];
  if (!p){ toast("找不到技能管理器（system/pkgs/skill）", true); return; }
  if (typeof embedOpen === "function" && typeof embedSupported === "function" && embedSupported(p)){
    embedOpen(p, {});
    return;
  }
  toast("这个包没法内嵌 —— 去插件列表里运行它", true);
}

/* ---------------------------------------------------------------- 改 / 删一轮（`V-279`）
   ★ 你要的是"会话能改、能删"。规矩是你定的三条：
     ① 改 N = 回到 **N 自己的开工快照**（撤销它改的东西）；快照没了就退到**再往前最近那条**
        （并且明确告警"那之后的改动会一起撤掉"）；
     ② 删镜像只删 `by=ai` 的，**回退要用的那条保留**，你自己存的一条不碰；
     ③ **只允许从链尾往回连续删** —— 也就是删 N = 删 `N..链尾`（中间那条不许单独删）。
   ★ 所以界面上这两颗按钮**都不是"直接动手"**：先让宿主算一份**只算不改**的计划
     （`ai_session_plan`），把"删哪几条 / 回退到哪条镜像 / 有什么坑"摆进确认框，
     确认了才 `ai_session_truncate(id, true)`。
     —— 破坏性动作先把事实亮出来，这规矩和「清空历史」那类按钮一致。 */
async function aiTurnPlan(id){
  if (!id){ toast("这一轮没有记录 id（老记录）—— 改不了", true); return null; }
  try{
    const p = await window.pywebview.api.ai_session_plan(id);
    if (!p || !p.ok){ toast("算不出这一轮要删什么：" + ((p && p.msg) || "?"), true); return null; }
    return p;
  }catch(e){ toast("算不出这一轮要删什么：" + (e && e.message ? e.message : e), true); return null; }
}
/* 把计划写成确认框里那段话（`askConfirm2` 认 `**粗体**` 和 `<br>`）。 */
function aiPlanHtml(p){
  const out = [];
  const head = (p.delete_ids || []).length;
  out.push("<b>会删掉 " + head + " 条记录</b>（这一轮" +
           (head > 1 ? "，以及它**之后**那 " + (head - 1) + " 轮" : "") + "）：<br>" +
           (p.delete_tasks || []).map((t, i) =>
             "　#" + (p.index + 1 + i) + " " + esc(String(t || "（没写任务）").slice(0, 40))).join("<br>"));
  if (p.target){
    out.push("<b>先回退到镜像</b> <code>" + esc(p.target.id) + "</code>" +
             (p.fallback ? "（**不是这一轮自己的**，是更早那条）" : "") +
             " —— 那一刻的包目录。<br>也就是：这一轮改的东西**会被撤掉**" +
             (p.fallback ? "，连同它那之后的改动" : "") + "。");
  }else if (!p.chat_only){
    out.push("<b>没有可回退的镜像</b> —— 删掉之后代码回不到那一刻，**只是记录没了**。");
  }
  (p.warnings || []).forEach(w => out.push("⚠ " + esc(String(w))));
  out.push('<span class="dim">回退要用的那条快照**保留**；你自己存的快照一条都不动；覆盖前会留 ' +
           '<code>.bak</code>。</span>');
  return out.join("<br>");
}
async function aiDoTruncate(id){
  try{
    const r = await window.pywebview.api.ai_session_truncate(id, true);
    if (!r || !r.ok){ toast("没删成：" + ((r && r.msg) || "?"), true); return null; }
    toast(r.msg || "删好了");
    return r;
  }catch(e){ toast("没删成：" + (e && e.message ? e.message : e), true); return null; }
}
/* 删完了之后收场：把记录列表重读一遍，把**剩下的那半条会话**重新摆出来，
   并且让"下一次跑"接着 `p.prev_id`（删掉的那轮已经没了，不能再接它）。
   `fill` = 编辑那一支：把这句原话填回输入框（改好再发一次就是"重来"）。 */
async function aiAfterTruncate(p, task, fill){
  AIR.viewing = "";
  await aiLoadRuns();
  if (p.prev_id){
    await aiOpenThread(p.prev_id, true);
    if (AIR.contId){ AIR.contTask = (AIR.turns[AIR.turns.length - 1] || {}).task || ""; }
    else { toast("前面那条是更早的记录（没存对话）—— 只能看，接不上了", true); }
  }else{
    // 删的就是链头 ⇒ 这条会话没了：日志清空，输入框回到"新会话"
    AIR.turns = []; AIR.cur = -1; AIR.steps = []; AIR.result = null;
    AIR.sentTask = ""; AIR.lastId = ""; AIR.pickId = "";
    AIR.contId = ""; AIR.contTask = ""; AIR.muted = 0;
  }
  if (fill){ AIR.task = String(task || ""); }
  AIR.rev++;
}

async function aiPollOnce(){
  try {
    const got = await window.pywebview.api.ai_poll();
    if (!got || !got.ok) return;
    // ★ `V-280`：**这一跑刚结束**（true → false）就重读一次"它自己的工具" —— 它很可能
    //   刚给自己造了一只，那条「等你允许」得立刻冒出来（不然你要等下次进这一页才看见）。
    const _wasRunning = AIR.running;
    AIR.running = !!got.running;
    if (_wasRunning && !AIR.running) aiLoadSkills();
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
    // ★ `V-258`：这一轮的步骤/结论**落在它自己身上**（`AIR.steps` 还是"现在这轮"的镜像，
    //   底下那几个计算属性照旧读它）—— 关键：**前几轮的 steps 数组不被碰**。
    const cur = (AIR.turns || [])[AIR.cur];
    if (cur){
      cur.steps = AIR.steps;
      if (got.result){
        cur.result = got.result;
        // ★ `V-259`：这一次到底**接着没有** —— 宿主把话说清楚，界面照实显示在那一轮上
        cur.note = got.result.continue_note || "";
      }
    }
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
  /* ★ `V-259`：**接着哪条** —— 这是"一个会话一直聊"的关键，之前只有 `contId` 一个来源，
     它一旦被清掉（切包 / 切会话 / 兜底的竞态），下一次发送就**静默**变成新会话（你报的
     "我每次输入它都当新的指令"）。现在三层兜底：
       ① `contId`   —— 明确的"接着这条"（刚跑完那条 / 下拉里挑的那条）
       ② `lastId`   —— **这个包最近跑的那条**（`aiAdoptLast` 从服务端列表认领，切包也认得回来）
       ③ 都没有 → 新会话
     ★ 例外：正在**翻历史记录**（`viewing`）时别自动接 —— 那只是"看看"。
     ★★ 这行**必须在下面那个 push 之前**（它要用来写"接着聊 / 新会话"）——
        `V-258`/`V-259` 我连着两次插在它前面，`cont` 进 TDZ，一按发送就报
        `Cannot access 'cont' before initialization`（探针两次都当场抓住）。 */
  const cont = AIR.contId || (AIR.viewing ? "" : (AIR.lastId || ""));
  // ★ `V-258`：**新起一轮** —— 前面几轮原样留着（这样接着聊时还看得到上文）；
  //   输入框发出去就清空（照稿子的 `handleInput.value = ""`）。
  AIR.turns.push({key: "t" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1), task: task,
                  at: (cont ? "接着聊" : "新会话") + " · " +
                      new Date().toTimeString().slice(0, 8),
                  steps: [], result: null, folded: false, note: ""});
  AIR.cur = AIR.turns.length - 1;
  AIR.task = "";
  AIR.diskNoted = "";            // `V-249`：新任务 = 允许再通知一次"盘上变了"
  AIR.snapNoted = "";            // `V-250`：新任务 = 允许再通知一次"快照存好了"
  /* ★ `V-259`：**接着哪条** —— 这是"一个会话一直聊"的关键，之前只有 `contId` 一个来源，
     它一旦被清掉（切包 / 切会话 / 兜底的竞态），下一次发送就**静默**变成新会话（你报的
     "我每次输入它都当新的指令"）。现在三层兜底：
       ① `contId`   —— 明确的"接着这条"（刚跑完那条 / 下拉里挑的那条）
       ② `lastId`   —— **这个包最近跑的那条**（`aiAdoptLast` 从服务端列表认领，切包也认得回来）
       ③ 都没有 → 新会话
     ★ 例外：正在**翻历史记录**（`viewing`）时别自动接 —— 那只是"看看"。 */
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
    /* ★ `V-280`：它自己造的工具（折叠那一块用）。
       顺序 = **待批准的在最前面**（那才是要你动手的），然后正在用的，最后是写坏了的。 */
    selfList(){
      this.A.rev;
      // **待批准的在最前面**（那才是要你动手的），然后能用的，最后写坏了的
      const t = this.A.selfSkills || {};
      return [].concat(skillPend(t), skillOk(t),
                       skillAll(t).filter(w => (w.problems || []).length));
    },
    selfN(){ this.A.rev; return (((this.A.selfSkills || {}).skills) || []).length; },
    selfPend(){ this.A.rev; return skillPend(this.A.selfSkills).length; },
    selfBroken(){ this.A.rev;
      return skillAll(this.A.selfSkills).filter(w => (w.problems || []).length).map(w => w.id); },
    /* 正在用的那几只的名字（步骤卡上"用自制工具"那个标签靠它认人） */
    selfNames(){
      this.A.rev;
      const o = {};
      skillOk(this.A.selfSkills).forEach(w => { o[w.name] = 1; });
      return o;
    },
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
    /* ★ `V-258`：**最后一轮的结论** —— 底栏（上一次 ✅/✗、快照号、token 统计）用的就是它。
       `A.result` 只表示"现在这轮跑出结果没有"，所以另起一个"最近一次有结果的那轮"。 */
    lastRes(){
      this.A.rev;
      const ts = this.A.turns || [];
      for (let i = ts.length - 1; i >= 0; i--) if (ts[i] && ts[i].result) return ts[i].result;
      return null;
    },
    usage(){ this.A.rev; return (this.lastRes && this.lastRes.usage) || null; },
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
    files(){ this.A.rev; return (this.lastRes && this.lastRes.files) || []; },
    resultOk(){ this.A.rev; return !!(this.lastRes && this.lastRes.ok); },
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
    /* 会话那一栏现在长什么样（标题那一行 + 底部状态条都要）
       ★ `V-258`：看的是**这一串对话的第一句**（第一轮的指令），翻历史时是那条记录的原文。 */
    sessionTitle(){
      this.A.rev;
      if (this.A.viewing){
        const r = (this.A.runs || []).filter(x => x.id === this.A.viewing)[0];
        return (r && r.task) || this.A.contTask || "历史会话";
      }
      const ts = this.A.turns || [];
      if (ts.length){
        const head = (ts[0].task || "").trim();
        return ts.length > 1 ? (head + "（" + ts.length + " 轮）") : head;
      }
      return (this.A.task || "").trim() || "新会话 —— 在下面写你要它干什么";
    },
    /* ★ `V-253`（照稿子那个 `切换历史会话` 下拉）：
       选中那条显示成 `当前: <任务>`，别的都是 `历史: <任务>`，最后一项是 `+ 新建空白会话`。
       ★ `V-254`：**一个都不 disable** —— 老记录（没存对话）也能点开看，
         点了会自动退回"能看不能接"（见 `pickSession`）。
       ★ `V-260`：**按"链"归并** —— 一个会话（几轮问答）在下拉里只占一条，
         值取链尾（最新那条）⇒ 接着聊带的是整条会话；多轮的标出「N 轮」。 */
    sessChains(){
      this.A.rev;
      return aiChains(this.A.runs);
    },
    sessCurrent(){
      this.A.rev;
      const id = this.A.pickId || "";
      if (!id) return null;
      return this.sessChains.filter(c => c.head.id === id || c.tail.id === id)[0] || null;
    },
    sessOthers(){
      this.A.rev;
      const id = this.A.pickId || "";
      return this.sessChains.filter(c => c.head.id !== id && c.tail.id !== id);
    },
    /* ★ `V-253`/`V-258`：日志现在是**按轮**渲染的（见模板里的 `A.turns` 那一段），
       这个 `logCards` 留着只为兼容老场景 —— 它把**最后一轮**拍平。 */
    logCards(){
      this.A.rev;
      const out = [];
      const t = (this.A.turns || [])[this.A.turns.length - 1];
      if (!t) return out;
      out.push({key: "user", kind: "user", icon: "message-circle",
                color: "var(--aib-primary)", action: "用户指令", tool: "",
                meta: t.at || "", path: t.task || ""});
      (this.visSteps(t.steps)).forEach((s, i) => {
        out.push({key: "s" + (s.n || i), kind: "step", icon: this.stepIcon(s.tool),
                  color: this.kindColor(s.tool), action: this.stepTitle(s), tool: s.tool,
                  meta: this.stepMeta(s), path: this.stepPath(s)});
      });
      return out;
    },
    /* 底部状态条左半边（照稿子：`✗ 上次未通过` + `开工快照: <tag>`）
       ★ `V-258`：看的是"**最近一次有结果的那轮**"（`lastRes`），不是"正在跑这轮"
       ★ `V-269`：纯问答那轮（`kind="chat"`）措辞跟着换 —— 它没"验收"这回事。 */
    lastText(){
      this.A.rev;
      if (!this.lastRes) return "还没跑过";
      if (this.lastRes.kind === "chat") return this.resultOk ? "上次已回答" : "上次没通过";
      return this.resultOk ? "上次通过" : "上次未通过";
    },
    lastIcon(){
      this.A.rev;
      if (!this.lastRes) return "circle-slash";
      return this.resultOk ? "check" : "x-circle";
    },
    lastColor(){
      this.A.rev;
      if (!this.lastRes) return "var(--aib-text-light)";
      return this.resultOk ? "var(--aib-success)" : "var(--aib-danger)";
    },
    snapId(){
      this.A.rev;
      const s = this.lastRes && this.lastRes.snapshot;
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
    /* ★ `V-258`：新起一轮、翻历史、清空 —— 日志内容变了就跟着滚到底 */
    "A.turns"(){ this.followLog(); },
    /* ★ `V-253`：需求被别处改过（「重跑」填回输入框 / 「清空」清掉）⇒ 文本域重新量一次高度 */
    "A.task"(){ this.$nextTick(() => this.autoGrow()); },
  },
  methods: {
    stop: aiStop,
    saveBudget: aiSaveBudget,
    refresh(){ aiRefreshInfo(true); },          // 那颗「刷新」= 重新问一次宿主（不吃缓存）
    /* 回退到"开工前"那条快照（`V-236`）。默认 `only="all"`：缺的补上、变了的回退，       多出来的**不动**（和「文件管理 → 快照」里那个「只写回」一个语义）。 */
    rollback(snapIn){
      // ★ `V-257`：这里原来写的是裸 `A` / `target` / `shortPath` —— 那是**模块级/计算属性**
      //   的东西，在方法作用域里一个都不存在 ⇒ 点底栏那个"开工快照"标签直接报
      //   `A is not defined`（你报的那个错）。方法里一律走 `this.`。
      // ★ `V-258`：参数是**哪一轮**的快照（每轮结论卡上都有自己的那颗回退按钮）。
      const A = this.A, target = this.target;
      const snap = snapIn || (this.lastRes && this.lastRes.snapshot);
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
      // ★ `V-258`：清空 = 把**所有轮**清掉（原来只是"从这一轮之后不再显示"，看不到效果）
      AIR.turns = []; AIR.cur = -1;
      AIR.muted = 0;
      AIR.result = null; AIR.steps = []; AIR.sentTask = ""; AIR.viewing = ""; AIR.pickId = "";
      AIR.task = "";
      AIR.rev++;
      this.$nextTick(() => this.autoGrow());
    },
    /* ★ V-261：**Alt 键当"我说过的话"导航用**。
       按住 Alt → 浮出一张表（这一串会话里我说过的每一句）→ 点哪条就滚到哪一轮。
       ★★ V-265 修你报的"得按两下才出来"：**松手不再收起**（原来 keydown 浮出、keyup 立刻收起，
          一次正常的"按一下"就变成闪一下 ⇒ 你只能按住不放，或者按第二次才看见）。
          现在是个**开关**：按一下浮出并**留着**，再按一下 / 点某一条 / Esc / 点别处才收。 */
    altDown(e){
      if (e.key === "Escape"){ AIR.altOn = false; return; }
      if (e.key !== "Alt") return;
      if (typeof tab !== "undefined" && tab !== "ai") return;   // 不在 AI 这一页就别管
      if (!(this.A.turns || []).length) return;
      /* ★★ V-266 修你报的"按两下才显示"：**Alt 的默认动作必须拦掉**。
         在 WebView2/Chromium 里，单独按 Alt 会去激活**窗口菜单栏** ——
         那一下就"喂给菜单了"，页面要等第二下才收到 ⇒ 现象正好是"按两下才出来、
         再按两下才隐藏"。`preventDefault()` 之后第一下就归页面。
         ★ V-273（你指出的）：这里**不是"防抖"** —— 键盘的机械抖动在硬件/驱动那一层就
           滤掉了，页面收不到那种东西。代码里原来还留着一句"120ms 内只算一次"的**猜测**，
           现在删掉：真正会重复的是这两件有据可依的事 ——
             ① `e.repeat`：按住不放时 **OS 故意连发** `keydown`（合法事件，要去重）；
             ② 同一次按键有**两个入口**（`keydown` / `keyup`），两个都翻转就会自己抵消成
                "按了没反应" —— 那件事由 `_altDownSeen` 管（下面 `altUp` 里看它）。
           ★ 换句话说：这里**没有任何"猜出来的时间数字"**了。要是将来真机出现"按一下没反应"，
             那说明有环境会 keydown 双发 —— 到时候拿现场证据再加判断，别现在先猜。 */
      try{ e.preventDefault(); }catch(e2){}
      this._altDownSeen = true;        // `altUp` 靠它判断"这一按的 keydown 收到没有"
      if (e.repeat) return;            // 长按连发：只算第一下
      AIR.altOn = !AIR.altOn;          // 再按一下 = 收起（开关）
    },
    /* ★ V-266 的兜底：万一 `keydown` 还是被窗口菜单吃掉，就用**同一次按键的 `keyup`** 顶上
       （两发都收到也只算一次：`_altDownSeen` 为真就跳过）。松手本身**不收起** ✓ */
    altUp(e){
      if (e.key !== "Alt") return;
      const seen = this._altDownSeen;
      this._altDownSeen = false;
      if (seen) return;                                  // 这一按已经处理过了
      if (typeof tab !== "undefined" && tab !== "ai") return;
      if (!(this.A.turns || []).length) return;
      AIR.altOn = !AIR.altOn;
    },
    jumpTurn(ti){
      const t = (AIR.turns || [])[ti];
      if (!t) return;
      if (t.folded) t.folded = false;        // 折叠着的先展开，不然滚过去是空的
      AIR.rev++;
      this.$nextTick(() => {
        const els = this.$el ? this.$el.querySelectorAll(".ai-turn") : [];
        const el = els[ti];
        if (!el) return;
        el.scrollIntoView({block: "start", behavior: "smooth"});
        el.classList.add("ai-flash");
        setTimeout(() => el.classList.remove("ai-flash"), 1400);
      });
      AIR.altOn = false;
    },
    /* ★ `V-258`：折叠 / 展开**某一轮**（点那一轮的「用户指令」卡，或卡右边那行字） */
    toggleTurn(ti){
      const t = (AIR.turns || [])[ti];
      if (!t) return;
      t.folded = !t.folded;
      AIR.rev++;
    },
    /* ★ `V-269` 补：某一轮的步骤卡（`t.steps` 是那一轮自己的，不会互相冲掉）
       `mute` 的不画：目前只有一种 —— 纯问答那轮里"它先说了一句、被催之后才 answer"的
       那张 `(说话)` 卡，它和下面的「回答」卡是**同一段话**，画出来就是同一段话出现两遍。
       数据仍在记录里（`steps` 一条不少），只是不摆到脸上。 */
    visSteps(steps){ return (steps || []).filter(s => !s.mute); },
    turnCards(t){
      return this.visSteps(t.steps).map((s, i) => ({
        key: "s" + (s.n || i), icon: this.stepIcon(s.tool), color: this.kindColor(s.tool),
        action: this.stepTitle(s), tool: s.tool, meta: this.stepMeta(s), path: this.stepPath(s),
      }));
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
    /* ★ `V-269`：结论卡的抬头分两种 —— 干活那次是「验收通过/没通过」，
       纯问答那次是「回答」（没动文件、也就没有"验收"这回事）。 */
    rhead(r){
      if (!r) return "";
      if (r.kind === "chat") return r.ok ? "💬 回答" : "✗ 没能回答";
      return r.ok ? "✅ 验收通过" : "✗ 没通过";
    },
    /* 抬头后面那截" —— 原因"：干活那次除了"验收通过"以外都值得写；
       问答那次只有失败才写（成功时原因就是"问答收工…"，写出来是废话）。 */
    rshowReason(r){
      if (!r || !r.reason || r.reason === "验收通过") return false;
      return r.kind === "chat" ? !r.ok : true;
    },
    stepIcon(t){
      // 稿子里那几张卡用的就是这几个名字（`list_dir` → `folder-search`、`read_file` → `file-text`、
      // 写文件 → `file-code`）—— 照它来；其余工具按同一族补。
      // ★ `V-280`：它自己造的手给个认得出的图标（别混进"写文件/跑一遍"那一族）
      if (this.selfNames[t]) return "moss-plus";
      return {list_dir: "folder-search", read_file: "file-text", grep: "search",
              edit_file: "file-code", write_file: "file-code", run_moss: "play",
              spec: "book-open", done: "check", snap_clean: "moss-camera"}[t] || "code";
    },
    runLine(r){
      const t = (r.started_text || "").slice(11, 19);
      // ★ `V-269`：纯问答那次（`kind="chat"`）不是"验收通过"，图标也换成对话
      const mark = r.kind === "chat" ? (r.ok ? "💬 " : "✗ ") : (r.ok ? "✅ " : "✗ ");
      return mark + (r.task || "").slice(0, 42) +
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
    /* ★ `V-280`：那个折叠块的三颗按钮 */
    selfToggle(){ AIR.selfOpen = !AIR.selfOpen; AIR.rev++; },
    lookTool(w){ aiSkillLook(w); },
    allowTool(w){ aiSkillAllow(w, !w.allowed); },
    rmTool(w){ aiSkillRm(w); },
    manageSkills(){ aiOpenSkills(); },
    /* ★ `V-279`：改这一轮 —— 回退到它开工前 + 删掉它和它之后的 + 把这句原话填回输入框。
       填回去之后 `contId` 指的是**前一轮**，所以你改好那句话再点发送，
       等于"从上一轮接着重跑一遍"，而不是接在已经作废的那轮后面。 */
    async editTurn(t){
      const p = await aiTurnPlan(t.id);
      if (!p) return;
      askConfirm2("改这一轮？", aiPlanHtml(p) +
        "<br>改完**这句话会填回下面那个输入框**（你可以把它改成你想要的样子），" +
        "接着从**上一轮**往下走 —— 改好再点一次「发送指令」。",
        {label: "回退并填回输入框", danger: true, cb: async () => {
          const r = await aiDoTruncate(p.id);
          if (!r) return;
          await aiAfterTruncate(p, t.task, true);
        }});
    },
    /* ★ `V-279`：删这一轮 —— 记录删 `N..链尾`（只允许从链尾往回连续删），并按快照回退。 */
    async delTurn(t){
      const p = await aiTurnPlan(t.id);
      if (!p) return;
      askConfirm2("删这一轮？", aiPlanHtml(p) +
        "<br>删掉之后**这条会话就从上一轮往后重新开始**（这条记录本身看不回来了）。",
        {label: "删掉并回退", danger: true, cb: async () => {
          const r = await aiDoTruncate(p.id);
          if (!r) return;
          await aiAfterTruncate(p, "", false);
        }});
    },
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
    async pickSession(){
      const id = this.A.pickId || "";
      if (!id){
        AIR.viewing = ""; AIR.sentTask = ""; AIR.steps = []; AIR.result = null;
        AIR.turns = []; AIR.cur = -1;                    // `V-258`：换会话 = 清空日志
        AIR.contId = ""; AIR.contTask = ""; AIR.lastId = ""; AIR.muted = 0;
        AIR.rev++;
        toast("新会话：下一条不带之前的对话");
        return;
      }
      const c = this.sessChains.filter(x => x.head.id === id || x.tail.id === id)[0];
      const tail = (c && c.tail.id) || id;
      const r = (AIR.runs || []).filter(x => x.id === tail)[0] ||
                (AIR.runs || []).filter(x => x.id === id)[0];
      // ★ `V-262`：先**把整条会话读回来**（几轮都在），再决定"能不能接着聊" ——
      //   顺序不能反：`aiOpenThread` 自己也会根据链尾设 `contId`，得让它先落定。
      await aiOpenThread(tail);
      AIR.viewing = tail;                 // 标一下"这是翻出来的历史"（结论卡上会带牌子）
      if (r && r.cont){
        AIR.contId = tail; AIR.contTask = r.task || "";
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
      const name = (s && s.tool) || "";
      if (zh[name]) return zh[name];
      // ★ `V-280`：它自己造的手 —— 认出来就明说，别混进"其它"
      if (this.selfNames[name]) return "用自制工具";
      return "其它";
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
    /* 步骤卡第二行：**给人看的那一行**。
       ★ `V-260`：优先用宿主给的 `disp`（完整的路径 / 完整的 summary，`done` 那种一整段回答
         一个字不截）—— 原来直接拆 `brief`，而 `brief` 是 `brief[:70]` 截过的 JSON，
         `JSON.parse` 必然失败，于是屏幕上就是 `{"summary": "……` 这种原始串（你报的那条）。
       下面的 JSON 拆法留着当兜底（老记录 / 没有 `disp` 时）。
       ★ `V-269` 补：宿主给 `nodisp` 的步骤（`done` / `answer`）**没有正文可摆** ——
         它们的正文归下面那张结论卡，这里别再拿 `brief` 去反解（那正是"同一段话又贴一遍"）。
         ★ 为什么不用"`disp` 是空串"当信号：`(说话)` / `(打回)` / `(重试)` 这几张**本来就
           没有 `disp`、正文是从 `brief` 反解出来的**（老记录也这样）—— 拿空串当信号会把它们的
           正文一起弄没。所以另给一个明确的键。 */
    stepPath(s){
      if (s && s.nodisp) return "";
      if (s && s.disp) return String(s.disp);
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
          if (j.summary) bits.push(String(j.summary));
          if (bits.length) return bits.join("　");
        }
      }catch(e){ /* 不是 JSON（多半是被截断的老记录）—— 下面那句把它救回来 */ }
      // 截断的 JSON 也尽量把 summary / content 捞出来，别原样摆 JSON 给人看
      const m = b.match(/"(?:summary|content|text)"\s*:\s*"((?:[^"\\]|\\.)*)/);
      if (m){
        let t = m[1];
        try{ t = JSON.parse('"' + t + '"'); }catch(e){}
        return t;
      }
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
    aiLoadSkills();
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
        AIR.turns = []; AIR.cur = -1;                 // `V-258`：换了包 = 换一条会话，日志清空
        aiRefreshInfo();
        aiLoadRuns();
      }
      if (AIR.running) aiPollOnce();
    }, 700);
    /* ★ `V-253`（照稿子）：刚进来时文本域是 56px，等一帧量一下（内容长的话自动长高） */
    this.$nextTick(() => this.autoGrow());
    /* ★ `V-261`：Alt 那座"我说过的话"导航 —— 监听挂在 window 上（键盘焦点不一定在这一页里） */
    this._kd = e => this.altDown(e);
    this._ku = e => this.altUp(e);
    window.addEventListener("keydown", this._kd, true);
    window.addEventListener("keyup", this._ku, true);
    /* ★ V-265：面板开着的时候，**点别处**也收起来（不然它一直挡着日志）*/
    this._md = e => {
      if (!AIR.altOn) return;
      const t = e.target;
      if (t && t.closest && t.closest(".ai-jump")) return;
      AIR.altOn = false;
    };
    document.addEventListener("mousedown", this._md, true);
  },
  beforeUnmount(){
    window.removeEventListener("keydown", this._kd, true);
    window.removeEventListener("keyup", this._ku, true);
    document.removeEventListener("mousedown", this._md, true);
  },
  template: `
  <div class="aiwrap">
    <div class="ai-workspace">

      <!-- 顶部配置栏（V-263 精简）：只留**切换会话**（吃掉剩下的宽度）+ **在哪干活**。
           上限 / 模型都挪到下面输入框那一行了 —— 上面这一条不再换行。 -->
      <header class="top-toolbar ai-bar">
        <div class="custom-select grow" title="切换历史会话（一个会话几轮问答只占一条）"
             @click="openSel($event)">
          <span v-html='ico("history", "i")'></span>
          <select class="ai-sess" v-model="A.pickId" :disabled="A.running" @change="pickSession()">
            <option v-if="sessCurrent" :value="sessCurrent.tail.id"
                    >当前: {{ (sessCurrent.head.task || "").slice(0, 60) }}{{ sessCurrent.turns > 1 ? ("（" + sessCurrent.turns + " 轮）") : "" }}</option>
            <option v-for="c in sessOthers" :key="c.head.id" :value="c.tail.id"
                    >历史: {{ (c.head.task || "").slice(0, 60) }}{{ c.turns > 1 ? ("（" + c.turns + " 轮）") : "" }}</option>
            <option disabled>──────────</option>
            <option value="">+ 新建空白会话</option>
          </select>
        </div>

        <div class="custom-select" title="在哪干活（v1 只允许写 user_data/pkgs 下面）"
             @click="openSel($event)">
          <span v-html='ico("folder-tree", "i")'></span>
          <select v-model="A.where" :disabled="A.running" @change="refresh()">
            <option value="pkg" :disabled="!pkg">{{ pkg ? ("当前包 :" + pkg.id) : "（左边还没选包）" }}</option>
            <option value="new">整个项目区</option>
          </select>
        </div>
      </header>

      <p class="ai-warn" v-if="A.err">⚠ {{ A.err }}</p>
      <p class="ai-warn" v-else-if="!ready">⚠ {{ (info && info.why) || "还没配好 AI —— 去「设置 → AI」挑一家、把 key 填上（或 moss --ai-profile-set）。" }}</p>
      <p class="ai-warn" v-if="missing.length">⚠ 提示词文件缺了：{{ missing.join("、") }} —— 在 <code>system/ui/ai/prompts/</code> 或 <code>user_data/ai/prompts/</code> 里补上（不补也跑，只是 AI 少了那几条规矩）。</p>
      <p class="ai-warn" v-if="target && !canWrite && A.where === 'pkg'">
        ⚠ 这个包在 <code>system/</code> 下面 —— <b>它改不了</b>（v1 只许写 <code>user_data/pkgs/**</code>）。
        想让 AI 真动手：把上面「在哪干活」换成整个项目区，或者选一个装在 <code>user_data/pkgs</code> 里的包。
      </p>

      <!-- ★ V-280/V-281：**技能** —— 用户平时看不到这一层（不在插件页、不是 :别名、不算包），
           只在 AI 页这儿折叠着露一行；有待批准的时候那行变黄并自动展开。
           技能 = 一个包（pkg.json + 入口 + icon.svg），id 必须用两个短横开头，本体住在
           :skill 插件的数据目录里（user_data/state/skill/）。第一次要你点「允许」，
           而且允许绑指纹 —— 它事后改了 pkg.json / 入口 / 图标就自动退回待批准。
           「管理技能」把 :skill 那个界面嵌出来（图标墙 / 详情 / 转为插件 / 删除都在那边）。 -->
      <section class="ai-selft" v-if="selfN || selfPend || selfBroken.length">
        <div class="ai-selft-h" :class="{bad: selfPend > 0}" @click="selfToggle()"
             title="它给自己造的能力（技能 = 一个包，但不在插件页里）">
          <span v-html='ico("sparkles", "i")'></span>
          <span>技能 · {{ selfN }}</span>
          <span v-if="selfPend">· {{ selfPend }} 只等你允许</span>
          <span v-if="selfBroken.length">· {{ selfBroken.length }} 只写坏了</span>
          <span class="ai-selft-x">{{ A.selfOpen ? "收起" : "展开" }}</span>
        </div>
        <div class="ai-selft-b" v-if="A.selfOpen">
          <p class="ai-warn" v-if="selfPend">
            ⚠ 它给自己造了 {{ selfPend }} 只技能，<b>你点「允许」它下一次跑才能用</b>
            （不放心就先点「看一眼」，看它到底写了什么）。
          </p>
          <div class="ai-selft-i" v-for="w in selfList" :key="w.id">
            <code>{{ w.id }}</code>
            <span class="ai-selft-d" :title="w.desc || w.why">{{ w.desc || w.why || "（没写说明）" }}</span>
            <span class="ai-selft-t">
              {{ w.kind === "pkg" ? "插件" : (w.origin === "seed" ? "出厂样例" : "它自己造的") }} ·
              {{ w.problems.length ? w.problems.join("；") : (w.allowed ? "已允许" : "待批准") }}
            </span>
            <span class="ai-selft-a">
              <button @click="lookTool(w)">{{ A.selfWho === w.id ? "收起" : "看一眼" }}</button>
              <button v-if="w.layer !== 'system' && !w.problems.length"
                      @click="allowTool(w)">{{ w.allowed ? "撤销" : "允许" }}</button>
              <button v-if="w.layer !== 'system'" class="danger" @click="rmTool(w)">删除</button>
            </span>
            <pre class="ai-selft-pre" v-if="A.selfWho === w.id">{{ A.selfText }}</pre>
          </div>
          <p class="ai-selft-p" v-if="selfBroken.length">
            这几只进不了工具表（先修好再说）：{{ selfBroken.join("、") }}
          </p>
          <p class="ai-selft-p">
            <button class="btn btn-outline" @click="manageSkills()"
                    title="图标墙 / 详情 / 文件列表 / 转为插件 / 删除 —— 都在技能界面里">管理技能…</button>
          </p>
        </div>
      </section>

      <!-- 中间日志流（V-263：**不再重复显示会话名** —— 顶栏那个下拉已经写着当前会话了） -->
      <main class="log-container ai-log" ref="log">
        <!-- ★ V-258/263：日志按轮排 —— 一轮 = 一行「#N 用户对话 + 那句话」+ 它的步骤卡 + 它的结论卡。
             点这一行就把这一轮折叠/展开。★ 这一行**做成一行的细条**（不再占两行）。 -->
        <div class="ai-turn" v-for="(t, ti) in A.turns" :key="t.key">
          <!-- V-264：这一行不写「用户对话」（白占宽度）——靠底色说明这是用户说的 -->
          <div class="ai-th" @click="toggleTurn(ti)"
               :title="t.folded ? '点一下展开这一轮' : '点一下折叠这一轮'">
            <b class="ai-th-n">#{{ ti + 1 }}</b>
            <span class="ai-th-t">{{ t.task }}</span>
            <span class="ai-th-a" :title="t.note || t.at"
                  :class="{bad: /接不上/.test(t.note || '')}"
                  >{{ t.folded ? "已折叠 · 点一下展开" : (t.note || t.at || "") }}</span>
            <!-- ★ V-279：这一轮的「改」和「删」。
                 · 都带 @click.stop —— 不然会顺手把这一轮折叠掉（父层是折叠开关）。
                 · 「改」= 回到**这一轮自己的开工快照**（撤销它的改动），并把这句原话填回输入框；
                   填好之后发出去 = 从上一轮接着重跑（contId 指向前一轮）—— 这就是改了再来一遍。
                 · 「删」= 删掉**这一轮以及它之后**的记录（只允许从链尾往回连续删），并按快照回退。
                 · 跑着的时候不给点（改一半把地基抽了，那才叫乱）。 -->
            <span class="ai-th-x" v-if="t.id && !A.running">
              <button @click.stop="editTurn(t)"
                      title="改这一轮：回到它开工前的快照（撤销它改的东西），并把这句话填回输入框 —— 改好再发一次">编辑</button>
              <button class="danger" @click.stop="delTurn(t)"
                      title="删这一轮：从这一轮到会话末尾的记录一起删掉，并按快照回退">删除</button>
            </span>
          </div>

          <template v-if="!t.folded">
            <div class="step-card ai-step" v-for="c in turnCards(t)" :key="c.key"
                 :class="'k-' + toolKind(c.tool)" :data-tool="c.tool || ''">
              <div class="step-icon" v-html='ico(c.icon, "i")'></div>
              <div class="step-content">
                <div class="step-header">
                  <span class="step-action" :style="{color: c.color}">{{ c.action }} <b>{{ c.tool }}</b></span>
                  <span class="step-meta">{{ c.meta }}</span>
                </div>
                <span class="code-path" v-if="c.path">{{ c.path }}</span>
              </div>
            </div>

            <div class="ai-result" v-if="t.result" :class="{ok: !!t.result.ok, bad: !t.result.ok}">
              <div class="ai-rhead"><span v-if="A.viewing" class="ai-old">历史记录</span>{{ rhead(t.result) }}<span
                v-if="rshowReason(t.result)"> —— {{ t.result.reason }}</span></div>
              <div class="ai-rsnap" v-if="t.result.snapshot">
                <span>开工前已存快照 <code>{{ t.result.snapshot.id }}</code>（AI 存的，列表里带「AI」徽章）</span>
                <button class="btn btn-outline" @click.stop="rollback(t.result.snapshot)"
                        title="回到这次动手之前（只写回：缺的补上、变了的回退）">回退到开工前</button>
              </div>
              <p v-if="t.result.summary" class="ai-rsum">{{ t.result.summary }}</p>
              <p v-if="t.result.caveats" class="ai-rcav">它自己标的不确定：{{ t.result.caveats }}</p>
              <div v-if="(t.result.files || []).length" class="ai-rfiles">动过的文件：<span
                v-for="f in t.result.files" :key="f">{{ shortPath(f) }}　</span></div>
              <div class="ai-rtok" v-if="t.result.usage">
                token：输入 {{ t.result.usage.prompt_tokens }} / 输出 {{ t.result.usage.completion_tokens }} / 合计 {{ t.result.usage.total_tokens }}
                （上限 {{ humanTokens(A.maxTokens) }}）
                <span v-if="t.result.folded">· 折叠了 {{ t.result.folded }} 条旧结果</span>
              </div>
            </div>
          </template>
        </div>

        <p class="ai-empty" v-if="!A.turns.length">
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
            <!-- ★ V-263：**token 上限靠左**（原来在顶栏）；提示语那句去掉了 -->
            <div class="token-input-group ai-bud"
                 :title="'token 上限（单位：百万）。默认 100 = 1 亿 token。烧到 ' + humanTokens(A.warnTokens) + ' 时劝它收尾，到顶就停手。'">
              <span v-html='ico("gauge", "i")'></span> token 上限
              <input type="number" step="10" min="0.5" max="20000" value="100" class="ai-bud-n"
                     v-model.number="A.maxMillions" :disabled="A.running" @change="saveBudget()"> 百万
            </div>
            <span class="sp"></span>
            <div class="ai-actions">
              <!-- ★ V-263：**切换模型也挪到这一行**（在清空 / 发送指令左边） -->
              <div class="custom-select select-model" @click="openSel($event)"
                   :title="'这次用哪个模型。这家配了 ' + models.length + ' 个；换模型连带换上下文窗口。'">
                <span v-html='ico("sparkles", "i")'></span>
                <select class="ai-model" v-model="A.model" :disabled="A.running || !models.length"
                        @change="pickModel()">
                  <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
                  <option v-if="!models.length" value="">（还没配 AI）</option>
                </select>
              </div>
              <!-- ★ V-270：**重新跑** —— 网络断了 / 跑挂了之后，一句原话不用重打。
                   只在"这个包有跑过的记录"时出现（lastRun 就是干这个用的）。 -->
              <button class="btn btn-outline" v-if="lastRun && !A.running" @click="again(lastRun)"
                      :title="'把这句原话填回输入框（' + ((lastRun.task || '').slice(0, 24)) + '…）'"
                      v-html='ico("refresh-cw", "i") + " 重新跑"'></button>
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

    <!-- ★ V-261：按住 Alt 浮出来的"我说过的话"（点一条就跳到那一轮）。
         鼠标停在上面时不收（按住 Alt 再去点的动作才做得完）。 -->
    <div class="ai-jump" v-if="A.altOn && A.turns.length"
         @mouseenter="this._overJump = true" @mouseleave="this._overJump = false">
      <div class="ai-jump-h">这个会话里我说过的（{{ A.turns.length }}）<span>点一条跳过去</span></div>
      <div class="ai-jump-list">
        <div class="ai-jump-i" v-for="(t, ti) in A.turns" :key="t.key"
             :title="t.task" @click="jumpTurn(ti)">
          <b>#{{ ti + 1 }}</b>
          <span class="ai-jump-t">{{ t.task }}</span>
          <span class="ai-jump-a">{{ (t.at || "").split(" · ").pop() }}</span>
        </div>
      </div>
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




