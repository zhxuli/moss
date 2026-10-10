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
  task: "", running: false, steps: [], say: [], result: null,
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
  skillsRev: "",               // 技能状态指纹：一变就重读「技能」那一行（修 AI 改技能后界面还写已允许）
  snapNoted: "",               // `V-250`：已经通知过"快照存好了"的那一条（同上）
  /* ★ `V-251`：**会话**那三件 —— 你原话「怎么还是找不到历史会话记录，一旦重新打开 moss
     只能重新再来 …… 没法继续上一次的聊天继续沟通」。
       · `contId`   正在接着哪条记录聊（空 = 新开一条；`aiStart` 把它交给宿主）
       · `contTask` 那条记录的任务原文（界面上那一行字要显示"接着哪句"）
       · `lastId`   这个包最近跑的那条（进来就认领，摆出它的步骤/结论）
     为什么默认就"接着"：每个包一条会话，跟 agent 客户端一个心思 —— 想重开点「新开」。 */
  contId: "", contTask: "", lastId: "", lastAdopted: "",
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
  selfOpen: false, selfWho: "", selfText: "", selfTab: "pending",
  /* ★ `V-316`：**权限 = 一份清单**（每行一对「读 / 写」勾选）—— 不再有"模式"那种第二个开关。
      · `allow`    —— 清单（后端保证含 `*` 那一行 = 任意路径）
      · `wild`     —— `*` 那一行勾了写没有（= 放手）
      · `tmp`      —— 它的临时空间（按插件分）+ 一键清空 */
  allow: [], wild: false, dropHot: false, newPath: "",
  /* ★ `V-319`：**待允许的目录**（它提出、还没被勾的那一条）—— 清单里那一行据此闪烁 */
  perm: null,
  /* ★ `V-321`：权限卡**默认折起来**（只留一行摘要，日志区更大）。
     ★ `V-331`（你原话："正常情况下 hover它就显示 不hover它自动折叠 除非AI需要权限申请 才一直显示
     一旦我点了动作 又回到这个状态"）：所以折/展不是"开关"，是**三种状态的或**（见 `permOpen`）——
       · `permHover`  鼠标在卡上（放上来就展开，移开自动折）
       · `permPinned` 你点过那一条（钉住；再点一下取消）
       · 有请求（`A.perm` / 危险确认）⇒ **一直显示**，你点完动作就回到"放上来才展开" */
  permHover: false, permPinned: false,
  /* ★ `V-316`：左上角那颗**历史图标**点开才出的会话列表（原来是一个占满宽度的下拉） */
  histOpen: false,
  /* ★ `V-340`：**权限浮层**开不开（新稿子把权限从"左下角常驻卡"改成"工具栏里点开才出的浮层"） */
  permPop: false,
  /* ★ `V-308`：它现在挂着的问题（`ask` 卡片）。`askText` = 你在那张卡上打的字 */
  ask: null, askText: "", askBusy: false, answeredQids: [],
  /* ★ `V-307`：**这一步/这一轮现在烧了多少**（以前只有跑完才看得到数字） */
  liveUsage: null, killed: [], stopping: false,
  /* ★ `V-307`：**看这一条会话喂给它的完整提示词**（点「看提示词」开的那块） */
  msgOpen: false, msgWho: "", msgData: null, msgBusy: false,
  /* ★ `V-315`：**点开某一步看原始细节**（参数 + 输出）—— 不做黑箱 */
  stepOpen: null, modalTab: "detail",
  /* ★ `V-307`：聊天区**跟不跟着滚**。你往上翻的时候它不许把你拽回底部
     （你的原话："当我向上滑动聊天记录的时候 它总是自动弹回到最下面去"）。 */
  stick: true,
  /* ★ `V-328`：加目录那一格的**行内报错**（填错时贴在输入框下面那一句）。
     ★ `V-329`（你报的："怎么我瞎写一个 点添加 会出来两个错误提醒呢"）：原来这里走 `toast()`，
       而 `toast()` 是**两处一起报**（浮出来的深色胶囊 + 底部状态栏留一行）—— 一个错看两遍。
       现在这一格的错**贴在它自己下面**（行内一句红的），一次都不喊 `toast()`。 */
  newPathErr: "",
  /* ★ 附件：粘贴图片 / 拖入文件 / 大段文本转成附件。都是本机内存里的轻量元数据，
     图片用 data_url、文本直接带原文，路径附件交给宿主去读。 */
  attachments: [], pasteAsFile: true, inputDropHot: false, inputDropAt: 0,
});

/* 大段文本到多少字就转附件；图片/文件多大就别贴（避免把请求撑爆）。 */
const ATTACH_TEXT_MIN = 1000;
const ATTACH_FILE_MAX = 12 * 1024 * 1024;


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

/* 附件小工具：拖入 / 粘贴 / 大段文本共用同一份 AIR.attachments。 */
function aiAddAttachment(a){
  if (!a || !a.name) return null;
  const mime = String(a.mime || "");
  const key = a.kind === "path" ? ("p:" + String(a.path || ""))
            : (a.kind === "text" ? ("t:" + String(a.name || "") + ":" + String(a.text || "").length)
                                 : ("d:" + String(a.name || "") + ":" + mime + ":" +
                                    String(a.data_url || "").slice(0, 80)));
  if (AIR.attachments.some(x => x.key === key)) return null;
  a.key = key;
  a.mime = mime;
  AIR.attachments.push(a);
  AIR.rev++;
  return a;
}
function aiAttachPaths(items){
  let n = 0;
  (items || []).forEach(it => {
    if (!it || !it.path || it.isDir === true) return;
    const name = it.name || String(it.path).replace(/^.*[\\/]/, "");
    if (aiAddAttachment({kind: "path", name: name, path: String(it.path),
                         mime: it.mime || "", size: Number(it.size || 0)})) n++;
  });
  return n;
}
function aiPasteName(text){
  const first = String(text || "").trim().split(/\r?\n/)[0].slice(0, 28)
    .replace(/[\\/:*?"<>|]/g, "_");
  return (first || "粘贴文本") + ".txt";
}

/* ---- JSON 源码视图（思考过程 / 工具调用 / 对话的「查看源码」页）----------------
   参考 ZeEn JsonFormatter 的配色；长字符串/二进制默认折叠，点 summary 才展开。 */
function jsonDecodeText(v){
  let t = String(v == null ? "" : v);
  if (/\u[0-9a-fA-F]{4}/.test(t) || /%[0-9a-fA-F]{2}/.test(t)){
    try { t = JSON.parse('"' + t.replace(/"/g, '\\"') + '"'); } catch(e){}
    try { t = decodeURIComponent(t); } catch(e){}
  }
  return t;
}
function jsonDecodeDeep(v){
  if (typeof v === "string") return jsonDecodeText(v);
  if (Array.isArray(v)) return v.map(jsonDecodeDeep);
  if (v && typeof v === "object"){
    const out = {};
    Object.keys(v).forEach(k => { out[k] = jsonDecodeDeep(v[k]); });
    return out;
  }
  return v;
}
function jsonIsLongString(v){
  const t = String(v || "");
  return t.length > 1200 ||
         /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(t) ||
         /base64,[A-Za-z0-9+/=]{200,}/.test(t);
}
function jsonTreeHtml(v, key, depth, forceOpen){
  depth = Number(depth || 0);
  const k = (key === undefined || key === null || key === "") ? "" :
    '<span class="j-key">"' + esc(jsonDecodeText(String(key))) + '"</span><span class="j-punc">: </span>';
  if (v === null || v === undefined) return k + '<span class="j-null">null</span>';
  if (typeof v === "boolean") return k + '<span class="j-bool">' + (v ? "true" : "false") + '</span>';
  if (typeof v === "number") return k + '<span class="j-num">' + esc(v) + '</span>';
  if (typeof v === "string"){
    const text = jsonDecodeText(v);
    if (!forceOpen && jsonIsLongString(text)){
      const head = text.slice(0, 200).replace(/\s+/g, " ");
      return '<details class="j-node j-long"><summary>' + k +
             '<span class="j-str">"' + esc(head) + '…"</span>' +
             '<span class="j-dim">（' + text.length + ' 字，点击展开）</span></summary>' +
             '<pre class="j-pre">' + esc(text) + '</pre></details>';
    }
    return k + '<span class="j-str">"' + esc(text) + '"</span>';
  }
  if (Array.isArray(v)){
    if (!v.length) return k + '<span class="j-punc">[]</span>';
    const open = forceOpen || (depth < 2 && v.length <= 12) ? " open" : "";
    const inner = v.map(function(x){ return '<div class="j-row">' + jsonTreeHtml(x, undefined, depth + 1, false) + '</div>'; }).join("");
    return k + '<details class="j-node"' + open + '><summary><span class="j-punc">[</span> ' +
           '<span class="j-dim">' + v.length + ' 项</span><span class="j-punc">]</span></summary>' +
           '<div class="j-children">' + inner + '</div></details>';
  }
  if (typeof v === "object"){
    const keys = Object.keys(v);
    if (!keys.length) return k + '<span class="j-punc">{}</span>';
    const open = forceOpen || (depth < 2 && keys.length <= 10) ? " open" : "";
    const inner = keys.map(function(key){
      return '<div class="j-row">' + jsonTreeHtml(v[key], key, depth + 1, false) + '</div>';
    }).join("");
    return k + '<details class="j-node"' + open + '><summary><span class="j-punc">{</span> ' +
           '<span class="j-dim">' + keys.length + ' 键</span><span class="j-punc">}</span></summary>' +
           '<div class="j-children">' + inner + '</div></details>';
  }
  return k + '<span class="j-dim">' + esc(String(v)) + '</span>';
}

/* 给探针/预览工具看的把手（`V-233`）：这一页的状态全在 `AIR` 里，
   外面想断言"到底 ready 没有 / 是不是还 busy"就靠它 —— 不用去猜 DOM。 */
window.__AIR = AIR;

function aiWhereDir(){
  // ★ `V-315`：干活的地方**就是这个包**（"在哪干活"那个下拉已经去掉了）。
  //   没有选包时回空串 —— 调用方（`aiStart`）会弹一句"先在左边选一个包"。
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
      // ★ `V-316`：权限那几样（清单 / 临时空间）—— 每次问宿主都刷一遍，
      //   因为"它在跑的时候问你要不要放行"会当场改清单，界面得跟着变。
      if (AIR.info.allow) AIR.allow = AIR.info.allow;
      if (AIR.info.wildcard !== undefined) AIR.wild = !!AIR.info.wildcard;
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

/* ★ `V-316`：**没有"模式"了** —— 权限就是那份清单（读/写两个勾）。
   这一函数留着只是为了让老调用点不炸（不该再有人调它）。
   ★ `V-367`：嘴上也不再讲"以前有个模式、现在没了"这种**改版说明** —— 只说清单在哪儿。 */
async function aiSetMode(){
  toast("权限就在下面那份清单里：给哪一行勾上「读」「写」，它就能碰哪儿", true);
}

/* ★ `V-316`：**权限清单** —— 加一条 / 拨「读」「写」/ 删掉 / 用系统对话框选目录。
   ★ 为什么要"拖动"也能加：你原话"允许通过添加或者拖动的方式 增加放行的路径"。
   ★ 没有"模式"了：**读/写两个勾就是全部**（当前这个包默认就在清单里、两个都开着）。 */
/* ★ `V-328`：这一格填的东西像不像一个**目录绝对路径**（用户报的："我可以随便打字 哪怕不是
   一个路径 就可以点添加"）。这里只管"形状"（盘符 / UNC / `*`）—— 到底存不存在、是不是目录，
   由宿主 `ai_mode.path_problem()` 判（它回一句人话，弹出来给你看）。
   ★ 为什么前端也要判一道：不用等一个来回就知道自己打错了，按钮当场变灰、框当场变红。 */
function addPathOk(p){
  const s = String(p || "").trim();
  if (!s) return false;
  if (s === "*") return true;                       // 任意路径那一行
  // 盘符（`D:\x` / `D:/x`）或 UNC（`\\主机\共享`）—— 跟宿主 `Path.is_absolute()` 一个口径，
  // 别一个说行一个说不行（前端只筛形状；存不存在由宿主判）。
  return /^[a-zA-Z]:[\\/]/.test(s) || /^\\\\[^\\]/.test(s);
}
/* ★ V-344：把一条路径拆成「盘符 + 中间 + 尾巴」三段，给权限清单那行用。
   为什么要拆：清单里每条目录只写最后一级（`md5`）根本不知道它在哪儿；而整条路径塞进一格
   又会被 `text-overflow` 从**右边**截掉 —— 最要紧的最后两级全没了。
   拆完用 flex 排：盘符和「上一级\最后一级」**钉死**，中间那段**自己缩**
   （放得下就全显示，放不下才出 …）。 */
function permParts(p){
  const s = String(p || "").trim();
  if (!s || s === "*") return null;
  const norm = s.replace(/\//g, "\\").replace(/\\+$/, "");
  let head = "", rest = norm, m = null;
  m = /^([A-Za-z]:)\\?/.exec(norm);
  if (m){ head = m[1] + "\\"; rest = norm.slice(m[0].length); }
  else {
    m = /^(\\\\[^\\]+\\[^\\]+)\\?/.exec(norm);
    if (m){ head = m[1] + "\\"; rest = norm.slice(m[0].length); }
  }
  const bits = rest.split("\\").filter(Boolean);
  if (!bits.length) return {head: head, mid: "", tail: ""};
  const keep = Math.min(2, bits.length);
  const tail = bits.slice(bits.length - keep).join("\\");
  const midBits = bits.slice(0, bits.length - keep);
  return {head: head, mid: midBits.length ? (midBits.join("\\") + "\\") : "", tail: tail};
}

async function aiAllowAdd(pth, why){
  const p = String(pth || AIR.newPath || "").trim();
  AIR.newPathErr = "";
  if (!p){ AIR.newPathErr = "先填一个目录（或者把文件夹拖到这一页）"; AIR.rev++; return; }
  if (!addPathOk(p)){
    AIR.newPathErr = "要填完整的绝对路径（像 D:\\项目\\我的包 那样）——「" + p + "」不是一个路径";
    AIR.rev++;
    return;
  }
  try{
    const got = await window.pywebview.api.ai_allow(p, true, true, String(why || "你手动加的"), "add", true);
    if (got && got.ok){
      toast(got.msg || "加好了");
      AIR.newPath = "";
    } else {
      // ★ `V-329`：这一格的错**行内报**（不再 toast ⇒ 也就不会"一个错看两遍"）
      AIR.newPathErr = (got && got.msg) || "加不了";
    }
    AIR.rev++;
    await aiRefreshInfo(true);
  }catch(e){
    AIR.newPathErr = "加不了：" + (e && e.message ? e.message : e);
    AIR.rev++;
  }
}
/* 拨某一行的读 / 写（`field` = "read" / "write"）—— **一个勾管一件事**，拨完立刻生效 */
async function aiAllowSet(it, field, on){
  try{
    const args = {read: null, write: null};
    args[field] = !!on;
    const got = await window.pywebview.api.ai_allow(it.path, args.read, args.write, "", "set");
    toast((got && got.msg) || "好了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("改不了：" + (e && e.message ? e.message : e), true); }
}
async function aiAllowRm(it){
  try{
    const got = await window.pywebview.api.ai_allow(it.path, null, null, "", "rm");
    toast((got && got.msg) || "删了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
}
async function aiAllowPick(){
  try{
    const got = await window.pywebview.api.ai_allow_pick();
    if (got && got.cancel) return;
    toast((got && got.msg) || "好了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("选不了目录：" + (e && e.message ? e.message : e), true); }
}
/* ★ `V-308`：回答它的问题。答完 loop 那边立刻继续跑。 */
async function aiAnswer(choice, text, qid){
  const q = AIR.ask || {};
  const id = String(qid || q.qid || "");
  if (!id || AIR.askBusy || !q.qid || id !== String(q.qid)) return;
  AIR.askBusy = true;
  try{
    const got = await window.pywebview.api.ai_answer(id, String(text || ""), String(choice || ""));
    if (!got || !got.ok) {
      toast((got && got.msg) || "没答上", true);
    } else {
      // Keep the submitted question hidden from the active controls immediately.
      if (!AIR.answeredQids.includes(id)) AIR.answeredQids.push(id);
      AIR.ask = null;
      AIR.askText = "";
      toast("答了 —— 它继续跑了");
      await aiPollOnce();
    }
  }catch(e){ toast("没答上：" + (e && e.message ? e.message : e), true); }
  finally { AIR.askBusy = false; AIR.rev++; }
  await aiRefreshInfo(true);
}
/* ★ `V-307`：**看这条会话喂给它的完整提示词**（你原话："我可以通过点击某个会话 来查看
   这个会话喂给他的历史记录 或者叫提示词(包括我问的和它回答的 所有历史)"）。 */
async function aiOpenMessages(id){
  const rid = String(id || AIR.pickId || AIR.lastId || "");
  if (!rid){ toast("先选一条会话（左边那个下拉）", true); return; }
  AIR.msgBusy = true; AIR.msgOpen = true; AIR.msgWho = rid; AIR.msgData = null;
  document.body.style.overflow = "hidden";
  AIR.rev++;
  try{
    const got = await window.pywebview.api.ai_session_messages(rid);
    AIR.msgData = got || {ok: false, messages: [], msg: "读不到"};
  }catch(e){ AIR.msgData = {ok: false, messages: [], msg: String(e && e.message ? e.message : e)}; }
  AIR.msgBusy = false;
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
/* ★ `V-334`：从链头一路 `continued_from` 串下去，把这条会话的全部记录 id 收出来。 */
function _chainIds(all, head){
  const out = [head.id];
  let cur = head, guard = 0;
  while (guard++ < 500){
    const next = all.filter(r => r.continued_from === cur.id)[0];
    if (!next) break;
    out.push(next.id);
    cur = next;
  }
  return out;
}
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
    // ★ `V-334`：这条链上**每一条记录的 id** 都带上 —— 列表里那颗 ✕ 要按它删整条会话
    out.push({head: head, tail: cur, turns: turns, ids: _chainIds(all, head)});
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
    // ★ `V-307`：**带上"这次在哪儿干活"** —— 历史按包分桶了，你原话"我在 github 可视化助手
    //   这里使用了 ai 那么在历史这里 按说 它应该只要显示这个模块下的历史就可以了"。
    const got = await window.pywebview.api.ai_runs(30, aiWhereDir());
    if (!got || !got.ok) return;
    AIR.runs = got.runs || [];
    AIR.scope = got.scope || null;
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
      steps: t.steps || [], result: t.result || null,
      folded: !!t.result, autoFolded: !!t.result,
      note: (t.result && t.result.continue_note) || "",
    }));
    AIR.cur = -1;
    AIR.muted = 0;
    AIR.stick = true;                 // `V-307`：换会话 = 回到"跟着看"的状态
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
  // ★ `V-334`：兜底 —— 这个桶里**最新那条**也算"上次那条"（桶本来就是按包分的）。
  //   以前只认 `workdir` 字符串完全一致的那条；一旦录进去的 workdir 写法差一点
  //   （盘符大小写 / 尾部分隔符 / 换过包目录），重启后同一句就变成"新会话"了
  //   （用户报的："明明前面很多聊天记录 它变成了这个是一个新的聊天"）。
  const mine = aiLastRunFor(aiWhereDir());
  const last = mine || (AIR.runs || [])[0] || null;
  AIR.lastId = (last && last.id) || "";
  if (!last || AIR.contId || AIR.pickId) return;
  AIR.contId = last.id;
  AIR.contTask = last.task || "";
  AIR.pickId = last.id;
  // ★ 只有"确实是这个包的那条"才把前文摆出来；兜底认领**不摆** ——
  //   不然一进页面就把别人的结果卡摆上来（预览里那两场"跑完自动刷新"就是这么被搅黄的）。
  if (last.cont && mine){
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
                  steps: AIR.steps, result: AIR.result,
                  folded: !!AIR.result, autoFolded: !!AIR.result}];
    AIR.cur = 0;
    AIR.rev++;
  }catch(e){ if (!quiet) toast("读不到这条记录：" + (e && e.message ? e.message : e), true); }
}

async function aiForgetRun(id){
  try{
    // ★ `V-307`：全清**只清这个桶**（这个包的会话），不会顺手把别的包的记录删掉
    const got = await window.pywebview.api.ai_run_forget(id || "", !id, aiWhereDir());
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
    if (skillPend(got).length) { AIR.selfOpen = true; AIR.selfTab = "pending"; }
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
async function aiOpenSkills(){
  // ★ 用 `DATA`（宿主给的那份包表），**不是 `state`** —— 界面里没有 `state` 这个全局，
  //   之前 `typeof state !== "undefined"` 恒为假 ⇒ 包表为空 ⇒ 误报"找不到技能管理器"。
  const ps = (typeof DATA !== "undefined" && DATA && DATA.packages) || [];
  const p = ps.filter(x => x.id === "skill" ||
                           (x.aliases || []).indexOf("skill") >= 0)[0];
  if (!p){ toast("找不到技能管理器 —— 先在插件列表里跑一次 skill", true); return; }
  // ★ 先把"当前这个包"切成 skill，再进它的「界面」选项卡：
  //   只 embedOpen 不 select 的话，embed 页渲染的还是 cur，不是 skill 那一帧。
  try { if (typeof select === "function") select(p.id, true); } catch(e){}
  if (typeof embedOpen === "function" && typeof embedSupported === "function" && embedSupported(p)){
    await embedOpen(p, {});
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
  if (!id){ toast("这条是更早的记录，改不了", true); return null; }
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
    out.push("<b>先回退到快照</b> <code>" + esc(p.target.id) + "</code>" +
             (p.fallback ? "（**不是这一轮自己的**，是更早那条）" : "") +
             " —— 那一刻的包目录。<br>也就是：这一轮改的东西**会被撤掉**" +
             (p.fallback ? "，连同它那之后的改动" : "") + "。");
  }else if (!p.chat_only){
    out.push("<b>没有可回退的快照</b> —— 删掉之后代码回不到那一刻，**只是记录没了**。");
  }
  (p.warnings || []).forEach(w => out.push("⚠ " + esc(String(w))));
  out.push('<span class="dim">回退要用的那条快照**保留**；你自己存的快照一条都不动；覆盖前会留 ' +
           '<code>.bak</code>。</span>');
  return out.join("<br>");
}
/* ★ `V-367`：**这里不再 toast** —— 这个动作的收尾话在 `aiAfterTruncate()` 末尾一次说完
   （以前这里先弹"删好了"，紧接着那边再弹一句"接不上"，一个动作两条不一样的话）。 */
async function aiDoTruncate(id){
  try{
    const r = await window.pywebview.api.ai_session_truncate(id, true);
    if (!r || !r.ok){ toast("没删成：" + ((r && r.msg) || "?"), true); return null; }
    return r;
  }catch(e){ toast("没删成：" + (e && e.message ? e.message : e), true); return null; }
}
/* 删完了之后收场：把记录列表重读一遍，把**剩下的那半条会话**重新摆出来，
   并且让"下一次跑"接着 `p.prev_id`（删掉的那轮已经没了，不能再接它）。
   `fill` = 编辑那一支：把这句原话填回输入框（改好再发一次就是"重来"）。
   `done` = 宿主那句结果（`aiDoTruncate` 的 `r.msg`）—— 和下面的结论**拼成一条**再说。
   ★ `V-367`：一个动作只留一条提示（以前"删好了"+"接不上"= 两条）。 */
async function aiAfterTruncate(p, task, fill, done){
  AIR.viewing = "";
  await aiLoadRuns();
  let tail = "";
  if (p.prev_id){
    await aiOpenThread(p.prev_id, true);
    if (AIR.contId){ AIR.contTask = (AIR.turns[AIR.turns.length - 1] || {}).task || "";
                     tail = "，下一条接着上一轮聊"; }
    else { tail = "（前面那条是更早的记录、没存对话 —— 接不上，下一条按新会话跑）"; }
  }else{
    // 删的就是链头 ⇒ 这条会话没了：日志清空，输入框回到"新会话"
    AIR.turns = []; AIR.cur = -1; AIR.steps = []; AIR.result = null; AIR.answeredQid = "";
    AIR.sentTask = ""; AIR.lastId = ""; AIR.pickId = "";
    AIR.contId = ""; AIR.contTask = ""; AIR.muted = 0;
    tail = "，这条会话没了（下一条按新会话跑）";
  }
  if (fill){ AIR.task = String(task || ""); }
  AIR.rev++;
  toast((done || "删好了") + tail);
}

async function aiPollOnce(){
  try {
    const got = await window.pywebview.api.ai_poll();
    if (!got || !got.ok) return;
    // ★ `V-280`：**这一跑刚结束**（true → false）就重读一次"它自己的工具" —— 它很可能
    //   刚给自己造了一只，那条「等你允许」得立刻冒出来（不然你要等下次进这一页才看见）。
    const _wasRunning = AIR.running;
    AIR.running = !!got.running;
    if (_wasRunning && !AIR.running){
      aiLoadSkills();
      aiRefreshInfo(true);      // `V-319`：这一跑里它可能问过权限，跑完把清单重读一次
    }
    // ★ 技能状态一变（AI 造了/改了、用户点了允许/撤销）立刻重读技能那一行 ——
    //   不然它改完技能，界面上还写着「已允许」（用户报的这个 bug）。
    const _skRev = String(got.skills_rev || "");
    if (_skRev && _skRev !== AIR.skillsRev){
      AIR.skillsRev = _skRev;
      aiLoadSkills();
    }
    AIR.steps = got.steps || [];
    // Poll payload is authoritative for the live turn: refresh the matching turn snapshot
    // so answered ask cards stop showing controls and remain readable in history.
    const liveTurn = (AIR.turns || [])[AIR.cur];
    if (liveTurn) liveTurn.steps = AIR.steps;
    AIR.say = got.say || [];
    AIR.seconds = got.seconds || 0;
    AIR.phase = got.phase || "";
    // ★ `V-307`：**活的账**（不用等跑完才看得到 token 数字）+ 停止状态 + 杀掉过哪些进程
    AIR.liveUsage = got.usage || null;
    AIR.stopping = !!got.stopping;
    // ★ `V-319`：**待允许的目录**（左下角清单里那一行要闪烁）。状态一变（出现 / 消失）
    //   就重读一次权限 —— 勾完那一刻那一行要立刻变成正式条目。
    const permNow = got.perm || null;
    const permKey = permNow ? String(permNow.path || "") : "";
    const permKeyOld = AIR.perm ? String(AIR.perm.path || "") : "";
    AIR.perm = permNow;
    if (permKey !== permKeyOld) aiRefreshInfo(true);
    if ((got.killed || []).length) AIR.killed = got.killed;
    if (got.mode && got.mode !== AIR.mode) AIR.mode = got.mode;
    // ★ `V-308`：它问你的话（那张卡片）。★ 你正在那张卡上打字时**别把你的字冲掉**。
    const ask = got.ask || null;
    const sameAsk = ask && AIR.ask && ask.qid === AIR.ask.qid;
    AIR.ask = (ask && AIR.answeredQids.includes(ask.qid)) ? null : ask;
    if (!sameAsk) AIR.askText = "";
    if (!ask && !got.running) AIR.askText = "";
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
        // ★ 用户要的 DSH 手感：跑的过程中步骤/思考全展开；**最终结果一到，中间过程自动折起来**。
        //   `autoFolded` 只自动折一次 —— 之后用户自己展开，轮询不会又给折回去。
        if (!got.running && !cur.autoFolded){
          cur.folded = true;
          cur.autoFolded = true;
        }
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
  const atts = (AIR.attachments || []).slice();
  const typed = (AIR.task || "").trim();
  const task = typed || (atts.length ? "请分析我发来的附件。" : "");
  if (!task) { toast("先写一句你要它干什么，或者加个附件。", true); return; }
  const dir = aiWhereDir();
  if (!dir) { toast("先在左边选一个包（或者选「新建包」）。", true); return; }
  AIR.busy = true;
  AIR.result = null; AIR.steps = []; AIR.say = []; AIR.answeredQid = "";
  AIR.killed = []; AIR.liveUsage = null; AIR.ask = null; AIR.askText = "";   // `V-307`/`V-308`
  AIR.stick = true;                                                          // `V-307`：新指令跟着滚
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
                  attachments: atts.map(a => ({name: a.name, kind: a.kind, size: a.size})),
                  at: (cont ? "接着聊" : "新会话") + " · " +
                      new Date().toTimeString().slice(0, 8),
                  steps: [], result: null, folded: false, autoFolded: false, note: ""});
  AIR.cur = AIR.turns.length - 1;
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
    const got = await window.pywebview.api.ai_start(task, dir, AIR.maxTokens, cont, AIR.model || "", atts);
    if (!got || !got.ok) { toast((got && got.msg) || "起不来。", true); AIR.busy = false; return; }
    AIR.running = true;
    AIR.task = "";
    AIR.attachments = [];
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
    AIR.stopping = true;
    AIR.rev++;
    const got = await window.pywebview.api.ai_stop();
    toast((got && got.msg) || "已停止。", !(got && got.ok));
    // ★ `V-307`：立刻把"执行中"那颗按钮摘掉（宿主那边被杀的子进程 + 掐断的请求都会让
    //   loop 尽快收工；下次轮询拿到 running=false 就彻底一致了）。
    if (got && got.done) { AIR.running = false; AIR.stopping = false; }
  } catch (e) { /* 无妨 */ }
  AIR.rev++;
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
    selfPendList(){ this.A.rev; return skillPend(this.A.selfSkills || {}); },
    selfOkList(){ this.A.rev; return skillOk(this.A.selfSkills || {}); },
    selfBrokenList(){ this.A.rev;
      return skillAll(this.A.selfSkills).filter(w => (w.problems || []).length); },
    selfBrokenNames(){ this.A.rev; return this.selfBrokenList.map(w => w.id).join("、"); },
    selfTotal(){ this.A.rev;
      return this.selfPendList.length + this.selfOkList.length + this.selfBrokenList.length; },
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
    /* 这个目标**写不写得了**（`V-347`：用户包 / 出厂包一视同仁 —— 打开哪个包点 AI，
       就是"我要改它"）。
       ★ 判据就是那份权限清单，次序跟后端 `ai_mode.can_write()` 对齐：先看清单里有没有
         **勾了「写」且盖住这个目录**的行（含 `*` 那条"放手"），再看"当前这个包"那一行
         （用户把它的「写」关掉 = 只想咨询）。两边次序不一致的话，界面说"能写"、它一动
         又被拒 —— 那种假象最难查。
       ★ 只提示、不禁用：只读的任务（"讲讲这个包怎么写的"）照样能跑。 */
    canWrite(){
      this.A.rev;
      const t = aiWhereDir();
      if (!t) return false;
      const norm = s => String(s).replace(/[\\/]+$/, "").toLowerCase();
      const inside = (p, r) => !!r && (p === r || p.indexOf(r + "\\") === 0 ||
                                       p.indexOf(r + "/") === 0);
      const rows = this.A.allow || [];
      if (rows.some(x => x.write && (x.path === "*" || inside(norm(t), norm(x.path))))) return true;
      const own = rows.filter(x => norm(x.path) === norm(t)).pop();
      if (own) return !!own.write;                      // 「当前这个包」那一行的勾
      return inside(norm(t), norm((this.A.info && this.A.info.write_root) || ""));
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
        out.push({key: "s" + i, kind: "step", icon: this.stepIcon(s.tool),
                  color: this.kindColor(s.tool), action: this.stepTitle(s), tool: s.tool,
                  meta: this.stepMeta(s), path: this.stepPath(s)});
      });
      return out;
    },
    /* ★ 底部状态条（`lastText` / `lastIcon` / `lastColor` / `tokLine`）整段删了 ——
       那条状态条已并进输入区工具行（token 进度条 + 快照在聊天记录里回退），界面上不再有它。 */
    tokenUsedMillions(){
      this.A.rev;
      const u = this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage);
      const n = Number((u && u.total_tokens) || 0) / 1000000;
      return (u && u.estimated ? "≈" : "") + (n < 10 ? n.toFixed(2) : n.toFixed(1));
    },
    tokenLimitMillions(){
      this.A.rev;
      const n = Number(this.A.maxTokens || 0) / 1000000;
      return n < 10 ? n.toFixed(2) : n.toFixed(1);
    },
    tokenPct(){
      this.A.rev;
      const u = this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage);
      const limit = Number(this.A.maxTokens || 0);
      return limit > 0 ? Math.max(0, Math.min(100, Math.round(Number((u && u.total_tokens) || 0) * 100 / limit))) : 0;
    },
    tokTip(){
      this.A.rev;
      const u = (this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage));
      if (!u) return "这一轮还没烧 token（或者还没跑）";
      return (u.estimated ? "≈ " : "") + "输入 " + (u.prompt_tokens || 0) + " · 输出 " +
             (u.completion_tokens || 0) + " · 合计 " + (u.total_tokens || 0) + " token" +
             (u.estimated ? "（网关没回 usage，这是按字数估的）" : "");
    },
    /* ★ `V-319`：**待允许那一行**显示什么（目录尾巴 + 它要读还是要写） */
    permPendingLabel(){
      this.A.rev;
      const p = this.A.perm;
      if (!p) return "";
      const bits = String(p.path || "").split(/[\\/]/).filter(Boolean);
      const tail = bits.length ? bits[bits.length - 1] : String(p.path || "");
      return tail + (p.need === "read" ? "（读）" : "");
    },
    /* ★ `V-316`/`V-320`：权限那一块的显示（照稿子）。
       · `permBadge` = 标题旁边那颗小胶囊（「可写 N 处」；放手时写「已放手」）
       · `wild`      = 「任意路径」那一行勾了写（放手：危险操作也不再问）
       · `confirmAsk`= `kind=confirm` 的那张卡 —— 它渲染在**权限卡上半段**（不另弹卡片） */
    allowOn(){ this.A.rev; return (this.A.allow || []).filter(x => x.write).length; },
    permBadge(){
      this.A.rev;
      if (this.A.wild) return "已放手";
      const n = (this.A.allow || []).filter(x => x.write).length;
      return n ? ("可写 " + n + " 处") : "只读";
    },
    confirmAsk(){
      this.A.rev;
      const a = this.A.ask;
      return (a && a.kind === "confirm") ? a : null;
    },
    /* ★ `V-333`：那三个"请求条上显示什么"的 computed（`reqWait` / `reqWhy` / `reqText`）
       跟着那条请求段一起删了 —— 请求现在长在聊天记录的气泡里，文字直接用步骤行自己的
       `brief` / `why`（宿主插的那条记录行）。 */
    /* ★ `V-323`：清单里**只画已经批过的**那一份（`pending` 是宿主给闸用的登记，
       不往界面上摆 —— 请求在聊天记录那条气泡里问）。 */
    allowRows(){
      this.A.rev;
      // ★ V-344：每行预先把路径拆成三段（盘符 / 中间 / 尾巴），模板直接用
      return (this.A.allow || []).filter(x => !x.pending)
                                .map(x => Object.assign({}, x, {_p: permParts(x.path)}));
    },
    /* ★ `V-307`：历史下拉里那几条 —— 正在跑的 / 上次没跑完的要能一眼看出来。 */
    runLabel(){
      return r => {
        const mark = r.interrupted ? "⚠ 上次没跑完 · " : (r.ok ? "✅ " : "✗ ");
        return mark + String(r.task || "（没写任务）").slice(0, 60) +
               (r.interrupted ? "（记录还在，能接着聊）" : "");
      };
    },
    /* ★ `V-328`：加目录那一格 —— 填的不是路径就**当场标红、按钮变灰**（别等点了才报错）。
       ★★ `V-329` 的血：这三个**必须放 computed**。`V-328` 我一时顺手写进了 `methods`，
       而模板里是**不带括号**用的（`addPathBad` / `canAddPath` / `addPathHint`）——
       取到的是**函数本身**（永远真值）⇒ 那行红字永远显示，而它渲染出来就是
       `function () { [native code] }`（你截图里看到的那一句）。
       规矩：**computed 在模板里不带括号；methods 必须带括号**（写错就是今天这样）。 */
    addPathBad(){
      this.A.rev;
      const s = String(this.A.newPath || "").trim();
      return !!s && !addPathOk(s);
    },
    canAddPath(){ this.A.rev; return addPathOk(this.A.newPath); },
    /* 这句提示**写在脚本里**（不塞进模板）—— 模板是模板字符串，
       里面写 `\\` 要数好几层转义，很容易渲染成少一个反斜杠的样子。 */
    addPathHint(){ return "要填完整的绝对路径（像 D:\\项目\\我的包 那样）"; },
    /* ★ `V-331`：权限卡开不开 = **有请求 或 你钉住了 或 鼠标在它上面**（三种状态的或）。
       `permFolded` 保留这个名字（预览/探针都在读它），但它现在是**算出来的**
       —— 所以 `window.__AIR.permFolded` 读不到了，改读 DOM 的 `.folded` 类（预览那边已经改）。 */
    permAsk(){ this.A.rev; return !!(this.A.perm || this.confirmAsk); },
    /* ★ `V-334`：`permOpen` **不再看有没有请求** —— `V-333` 起请求长在聊天记录里，
       卡片只认"鼠标放上来 / 你点过钉住"（用户要的就是这个：请求别再把这张卡顶开）。 */
    permOpen(){ this.A.rev; return !!this.A.permPinned || !!this.A.permHover; },
    permFolded(){ this.A.rev; return !this.permOpen; },
  },
  watch: {
    /* ★ `V-252`：步骤/结论来了就**跟着往下滚**（agent 控制台该有的样子）。
       ★ 但你自己往上翻看历史的时候不抢：只有"本来就贴着底"才跟。
       （照稿子里那个"占位符，模拟滚动到底部"的意思做的。） */
    "A.steps"(){ this.followLog(); },
    "A.result"(){ this.followLog(); },
    /* ★ `V-258`：新起一轮、翻历史、清空 —— 日志内容变了就跟着滚到底 */
    "A.turns"(){ this.followLog(); },
    /* ★ `V-321`：**它一要权限就自动展开**（你原话：折叠以后显示一行最重要的信息，
       要跟我们要权限就自动展开提示）。
       ★ `V-331`：现在"展开"不是靠改一个开关，而是 `permOpen` 把"有请求"算进去 ——
       所以这里只要**把钉子拔掉**：请求处理完（`A.perm` 变空）它就自然回到"放上来才展开"。 */
    "A.perm"(v){ if (v && AIR.permPinned){ AIR.permPinned = false; AIR.rev++; } },
    /* ★ `V-331`：**出现别的问答**（那张带选项的卡）时，权限卡**折起来**（你说："这个也要给他折叠起来"） */
    "A.ask"(v){
      if (v && (AIR.permPinned || AIR.permHover)){ AIR.permPinned = false; AIR.permHover = false; AIR.rev++; }
    },
    /* ★ `V-253`：需求被别处改过（「重跑」填回输入框 / 「清空」清掉）⇒ 文本域重新量一次高度 */
    "A.task"(){ this.$nextTick(() => this.autoGrow()); },
  },
  methods: {
      stop: aiStop,
      async openDir(path){
        if (!path) return;
        const rel = "abs/" + path.replace(/\\/g, "/");
        const r = await window.pywebview.api.fs_open_default(rel);
        if (r && !r.ok) toast(r.msg, true);
      },
      /* ★ V-344：复制路径（hover 才出的那颗按钮） */
      async copyPath(it){
        const p = String((it && it.path) || "");
        if (!p || p === "*") return;
        try{ await navigator.clipboard.writeText(p); toast("路径已复制"); }
        catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
      },
    saveBudget: aiSaveBudget,
    refresh(){ aiRefreshInfo(true); },          // 那颗「刷新」= 重新问一次宿主（不吃缓存）
    /* ---- ★ V-316：权限清单（读 / 写 两个勾，没有"模式"了） ---- */
    toggleAllow(){ /* `V-316`：清单现在**常驻**在左边那一栏，没有"展开/收起"了 */ },
    /* ★ `V-321`/`V-331`：折 / 展那一行 —— 现在平时是"鼠标放上来就展开"，
       点一下 = **钉住**（再点一下取消）；它在等你点头的时候不给折（那就没法点允许了）。 */
    togglePerm(){
      if (this.permAsk) return;
      AIR.permPinned = !AIR.permPinned;
      AIR.rev++;
    },
    permHoverIn(){ if (!AIR.permHover){ AIR.permHover = true; AIR.rev++; } },
    permHoverOut(){ if (AIR.permHover){ AIR.permHover = false; AIR.rev++; } },
    allowAdd(){ aiAllowAdd(null, "你手动加的"); },
    allowSet(it, field, on){ aiAllowSet(it, field, on); },
    /* ★ `V-323`：上面那一条请求的「允许 / 拒绝」：
       · 危险确认（kind=confirm）⇒ 把选择交回宿主（它那边阻塞等着）
       · 要目录权限（`A.perm`）⇒ 允许 = 当场把这条加进清单（要写就读写一起给）；
         拒绝 = 把宿主登记的 `pending` 那条删掉（闸那边就判"拒绝"）
       ★ 顺序照用户说的：**允许 ⇒ 这条请求消失、目录出现在下面的清单里；
         拒绝 ⇒ 这条请求消失，清单里什么都不加**（闸会如实体回它"不许"）。 */
    async reqAllow(){
      if (this.confirmAsk){ return this.answer("允许", ""); }
      const p = this.A.perm;
      if (!p) return;
      return this.grantPerm(p.need === "read" ? "read" : "write", true);
    },
    async reqDeny(){
      if (this.confirmAsk){ return this.answer("拒绝", ""); }
      if (this.A.perm){ return this.denyPerm(); }
      return undefined;
    },
    /* ★ `V-319`：**允许**它用这个目录（请求条上那颗「允许」走这里） */
    async grantPerm(field, on){
      const p = this.A.perm;
      if (!p || !on) return;                       // 取消勾选在这条上没意义（那条还没批）
      try{
        const got = await window.pywebview.api.ai_allow(p.path, true, field === "write", "", "add");
        toast((got && got.msg) || "放行了", !(got && got.ok));
      }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
    },
    /* ★ `V-319`/`V-325`：**拒绝那一条请求** —— `action="deny"` 只在宿主那边记一笔
       （清单**一个字都不动**：用户之前批过的读还得留着），闸当场就判"拒绝"。
       以前是"把那一行删掉"—— 第二次来要写权限时那一行本来就存在，删了等于把读也一起收了。 */
    async denyPerm(){
      const p = this.A.perm;
      if (!p) return;
      try{
        const got = await window.pywebview.api.ai_allow(p.path, null, null, "", "deny");
        toast((got && got.msg) || "拒绝了", !(got && got.ok));
      }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
    },
    allowRm(it){ aiAllowRm(it); },
    allowPick(){ aiAllowPick(); },
    /* 清单里那一行怎么显示：当前那个包 → `:包名 当前这个包`；`*` → 任意路径；别的按路径尾巴 */
    permLabel(it){
      if (!it) return "";
      if (it.path === "*") return "任意路径";
      const t = this.target;
      const norm = s => String(s || "").replace(/[\\/]+$/, "").toLowerCase();
      // ★ 符号走 `this.pSym()`（`mountVue` 的 globalProperties）—— 方法体里**读不到**
      //   模板那种全局（`V-252` 的血：这一页不做 `with(this)` 回退）
      if (t && norm(it.path) === norm(t)) return this.pSym() + ((aiPackage() || {}).id || "") + "　当前这个包";
      const bits = String(it.path).split(/[\\/]/).filter(Boolean);
      return bits.length ? bits[bits.length - 1] : it.path;
    },
    permWhy(it){ return (it && it.why) || ""; },
    /* 路径下面那行小字（稿子里是「当前工作包」/「默认安全策略」那种说明）
       ★ 这是 **methods**（带参数）—— computed 不收参数，写错就是「xxx is not a function」 */
    permDesc(it){
      if (!it) return "";
      if (it.pending) return "它想用这里" + (it.why ? ("：" + it.why) : "");
      if (it.path === "*") return "默认安全策略";
      const t = this.target;
      const norm = s => String(s || "").replace(/[\\/]+$/, "").toLowerCase();
      /* ★ `V-347`：出厂包多说四个字（宿主升级时 `system/` 会被整体替换）—— 只提示、不拦 */
      if (t && norm(it.path) === norm(t))
        return "当前工作包" + (it.factory ? " · 出厂件" : "");
      if (it.by === "ai") return "它请求的" + (it.why ? ("：" + it.why) : "");
      return it.why || "你加的";
    },
    /* ---- ★ V-316：历史会话（点图标才开的那一份列表） ---- */
    toggleHist(){
      AIR.histOpen = !AIR.histOpen;
      if (AIR.histOpen){
        AIR.permPop = false; aiLoadRuns();
        this.$nextTick(() => this.fitPop("hist"));      // ★ V-345：不许出窗
      }
      AIR.rev++;
    },
    /* ★ V-345：浮层**不许跑出窗口**。
       触发按钮在工具栏左边，而浮层死定 `left:0` ⇒ 窗口一窄右边缘就出屏
       （你报的“右侧超过了屏幕 看不全”）。开的时候量一下：
         ① 宽度先夹进窗口（真放不下就缩窄）；
         ② 再把整个浮层往左挪，让右边缘不超窗；
         ③ 最后连左边边也夹住（不让它从左边跑出去）。
       窗口改大改小的时候会重量（见 `mounted` 里那个 resize）。 */
    fitPop(which){
      const panel = which === "hist" ? this.$refs.histPanel : this.$refs.permPanel;
      const host  = which === "hist" ? this.$refs.histBtn : this.$refs.permBtn;
      if (!panel || !host) return;
      const vw = document.documentElement.clientWidth || window.innerWidth || 0;
      if (!vw) return;
      const hr0 = host.getBoundingClientRect();
      // ★ 位置没变就别白算（这个函数会被 700ms 那一跳顺手叫一下）—— 省掉强制重排
      const key = vw + "|" + Math.round(hr0.left) + "|" + Math.round(hr0.right);
      if (!this._fitKeys) this._fitKeys = {};
      if (this._fitKeys[which] === key) return;
      this._fitKeys[which] = key;
      const pad = 10;
      panel.style.left = "";
      panel.style.width = "";
      const avail = Math.max(260, vw - pad * 2);
      let w = panel.offsetWidth || 0;
      if (w > avail){ w = avail; panel.style.width = w + "px"; }
      const hr = host.getBoundingClientRect();
      let left = 0;                                     // 相对 .popover-wrapper
      if (hr.left + w > vw - pad) left = (vw - pad) - (hr.left + w);   // 往左挪
      if (hr.left + left < pad) left = pad - hr.left;   // 左边也夹住
      panel.style.left = Math.round(left) + "px";
    },
    /* V-340: permission popover (opened from the toolbar button) */
    togglePermPop(){
      AIR.permPop = !AIR.permPop;
      if (AIR.permPop){
        AIR.histOpen = false;
        this.$nextTick(() => this.fitPop("perm"));      // ★ V-345：不许出窗
      }
      AIR.rev++;
    },
    pickChain(c){ AIR.histOpen = false; AIR.pickId = (c && c.tail && c.tail.id) || ""; this.pickSession(); },
    pickNewChat(){ AIR.histOpen = false; AIR.pickId = ""; this.pickSession(); },
          /* ★ V-334：删掉**整条会话**（这条链上每一条记录）—— 直接删除，不弹二次确认（用户要求）。 */
      async delChain(c){
        const n = (c && c.turns) || 0;
        const ids = (c && c.ids) || [];
        if (!ids.length) return;
        
        let bad = 0;
        for (const id of ids){
          try{
            const got = await window.pywebview.api.ai_run_forget(id, false, aiWhereDir());
            if (!got || !got.ok) bad++;
          }catch(e){ bad++; }
        }
        toast(bad ? ("有 " + bad + " 条没删掉") : ("删掉了这条会话（" + n + " 轮）"), !!bad);
          // AIR.histOpen = false; // 用户要求：连续删除时不要关闭下拉列表
        // 删掉的正好是现在看的这条 ⇒ 视图清空，重新认领
        if (ids.indexOf(AIR.pickId) >= 0 || ids.indexOf(AIR.lastId) >= 0){
          AIR.viewing = ""; AIR.pickId = ""; AIR.contId = ""; AIR.contTask = "";
          AIR.lastId = ""; AIR.lastAdopted = "";
          AIR.turns = []; AIR.steps = []; AIR.result = null; AIR.cur = -1;
        }
        await aiLoadRuns();
        AIR.rev++;
      },
    chainTitle(c){
      const t = (c && c.head && c.head.task) || "（没写任务）";
      return t.length > 34 ? (t.slice(0, 34) + "…") : t;
    },
    chainMeta(c){
      const bits = [];
      if (c && c.turns > 1) bits.push(c.turns + " 轮");
      if (c && c.tail && c.tail.interrupted) bits.push("⚠ 上次没跑完");
      else if (c && c.tail && c.tail.ok) bits.push("✅");
      const at = (c && c.tail && c.tail.started_text) || "";
      if (at) bits.push(String(at).slice(5, 16));
      return bits.join(" · ");
    },
    dropEnter(){ if (!AIR.dropHot){ AIR.dropHot = true; AIR.rev++; } },
    dropLeave(e){
      // 在子元素之间挪动也会发 dragleave —— 只有真离开这一页才灭掉高亮
      const to = e && e.relatedTarget;
      if (to && this.$el && this.$el.contains(to)) return;
      if (AIR.dropHot){ AIR.dropHot = false; AIR.rev++; }
    },
    /* ---- ★ V-308：回答它 / 看提示词 ---- */
    answer(choice, text, qid){ aiAnswer(choice, text, qid); },
    openMessages(id){ aiOpenMessages(id); },
    roleName(r){
      return {system: "系统提示（它每次开工都收到这一份）", user: "用户 / 工具结果",
              assistant: "它的回复", tool: "工具结果"}[r] || String(r || "?");
    },
    /* 每条消息的抬头那点小信息（工具调用名 / 花了多少字） */
    msgHead(m){
      const bits = [];
      if (m.tool_calls && m.tool_calls.length)
        bits.push("调用 " + m.tool_calls.map(c => (c.function || {}).name).join("、"));
      if (m.tool_call_id) bits.push("回给 " + m.tool_call_id);
      bits.push(((m.content || "").length) + " 字");
      return bits.join(" · ");
    },
    msgText(m){
      const c = m.content;
      if (typeof c === "string" && c) return c;
      if (m.tool_calls && m.tool_calls.length)
        return m.tool_calls.map(x => (x.function || {}).name + "(" +
                 String((x.function || {}).arguments || "").slice(0, 800) + ")").join("\n");
      return "（空）";
    },
    async copyMessages(){
      try{
        const data = AIR.msgData || {};
        const text = (data.messages || []).map(m =>
          "===== " + (m.role || "?") + " =====\n" + this.msgText(m)).join("\n\n");
        await navigator.clipboard.writeText(text);
        toast("复制了 " + (data.messages || []).length + " 条");
      }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
    },
    /* ---- ★ V-307：滚动条不抢你的（你报的"往上滑就被弹回最下面"） ---- */
    onLogScroll(){
      const el = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
      if (!el) return;
      const near = (el.scrollHeight - el.scrollTop - el.clientHeight) < 48;
      if (near !== AIR.stick){ AIR.stick = near; AIR.rev++; }
    },
    toBottom(){ AIR.stick = true; this.followLog(true); },
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
      ta.style.height = "40px";
      ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
    },
    resetLogs(){
      // ★ `V-258`：清空 = 把**所有轮**清掉（原来只是"从这一轮之后不再显示"，看不到效果）
      AIR.turns = []; AIR.cur = -1;
      AIR.muted = 0;
      AIR.result = null; AIR.steps = []; AIR.sentTask = ""; AIR.viewing = ""; AIR.pickId = ""; AIR.answeredQid = "";
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
    /* ★ `V-334`：把那条记录行的 `args`（JSON 文本）安全地变成对象。 */
    talkArgs(s){
        const v = s && s.args;
        let a = null;
        if (v && typeof v === "object") a = v;
        else {
          try { a = JSON.parse(v || "{}"); } catch(e) { a = {}; }
        }
        if (a && typeof a === "object" && Array.isArray(a.options)) {
          // 修复选项为空：Python 后端 options 数组是字符串数组，但前端模板写了 o.label
          a.options = a.options.map(o => {
            if (typeof o === "string") return { label: o, value: o };
            return o;
          });
        }
        return (a && typeof a === "object") ? a : {};
      },
    turnCards(t){
      // Render each ask/permission step as an interactive bubble only while its qid is live.
      return this.visSteps(t.steps).map((s, i) => {
        const isTalk = s.tool === "ask" || s.tool === "perm";
        const ta = isTalk ? this.talkArgs(s) : {};
        const answered = !!s.done || (!!ta.qid && this.A.answeredQids.includes(ta.qid));
        if (isTalk) return {key: "s" + (s.n || i), type: "talk", tool: s.tool,
                            step: Object.assign({}, s, {done: answered}), ta};
        return {key: "s" + i, type: "step",
                icon: this.stepIcon(s.tool), color: this.kindColor(s.tool),
                action: this.stepTitle(s), tool: s.tool, meta: this.stepMeta(s),
                path: this.stepPath(s), step: s};
      });
    },    /* ---- ★ V-315：点开某一步（原始参数 + 原始输出） ---------------------------
       ★ 为什么要它（你原话）："它的动作 产出的日志 或者文本 我希望我能点击查看 这样我能更进一步
         观察它在干什么 对于我来说 它不应该是黑箱操作 应该让我有办法或者工具观察每个细枝末节"。
       ★ 两处细节都在：`args` 是它填给工具的完整参数（格式化过的 JSON）、`out` 是**它当时看到的
         那一份结果**（长内容在我们这边截过，卡片里会写明；**没截断的在「提示词」那一层**）。 */
    openStep(c){
      const s = (c && (c.step || c)) || null;
      if (!s) return;
      AIR.stepOpen = s;
      AIR.modalTab = "detail";
      document.body.style.overflow = "hidden";
      AIR.rev++;
    },
    openTurn(t, ti){
      if (!t) return;
      AIR.stepOpen = {
        n: Number(ti || 0) + 1,
        tool: "(对话)",
        brief: String(t.task || ""),
        note: String(t.note || ""),
        at: String(t.at || ""),
        why: "",
        turn: {
          task: String(t.task || ""),
          at: String(t.at || ""),
          note: String(t.note || ""),
          attachments: t.attachments || [],
          steps: t.steps || [],
          result: t.result || null,
        },
      };
      AIR.modalTab = "detail";
      document.body.style.overflow = "hidden";
      AIR.rev++;
    },
    setModalTab(tab){
      AIR.modalTab = String(tab || "detail");
      AIR.rev++;
    },
    closeModal(){
      AIR.stepOpen = null;
      AIR.msgOpen = false;
      document.body.style.overflow = "";
      AIR.rev++;
    },
    closeStep(){ this.closeModal(); },
    closeMessages(){ this.closeModal(); },
    stepHead(s){
      const bits = [];
      if (s && s.at) bits.push(s.at);
      if (s && s.ms) bits.push((s.ms / 1000).toFixed(1) + "s");
      if (s && s.tokens) bits.push((s.est ? "≈" : "") + cntok(s.tokens) + " token");
      if (s && s.note) bits.push(String(s.note).slice(0, 60));
      return bits.join(" · ");
    },
    async copyStep(){
      const s = AIR.stepOpen || {};
      const asText = v => (typeof v === "string") ? v : JSON.stringify(v, null, 2);
      let text = "";
      if (s.tool === "(对话)"){
        const t = s.turn || {};
        text = "第 " + s.n + " 轮 · 对话\n" + (t.task || "") +
               "\n\n【结果】\n" + JSON.stringify(t.result || {}, null, 2);
      } else {
        text = "第 " + s.n + " 步 · " + s.tool + "\n目的：" + (s.why || "") +
               "\n\n【参数】\n" + asText(s.args || "") +
               "\n\n【输出】\n" + asText(s.out || "");
      }
      try{
        await navigator.clipboard.writeText(text);
        toast("复制了这一步的原文");
      }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
    },
    modalSource(){ return jsonDecodeDeep(AIR.stepOpen || {}); },
    modalSourceHtml(){ return jsonTreeHtml(this.modalSource(), undefined, 0, true); },
    async copyModal(){
      if (AIR.modalTab === "source"){
        try{
          await navigator.clipboard.writeText(JSON.stringify(this.modalSource(), null, 2));
          toast("复制了源码 JSON");
        }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
        return;
      }
      await this.copyStep();
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
      if (t === "(思考)") return "think";
      if (["web_search", "web_fetch", "github_api"].indexOf(t) >= 0) return "web";
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
              spec: "book-open", done: "check", snap_clean: "moss-camera",
              web_search: "search", web_fetch: "globe", github_api: "git-branch",
              "(思考)": "lightbulb"}[t] || "code";
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
       ★★ `V-307` 改回来一条 —— 用户 2026-10-07 报："当我向上滑动聊天记录的时候
          它总是自动弹回到最下面去"。上一版我按稿子撤掉了"你往上翻就不抢"的判断，
          结果就是你一边看历史、它一边把你拽回底部。
       现在的规矩：**只在你本来就贴着底的时候跟滚**；你往上翻了就按住不动，
       右下角浮一颗「回到最新」，点它才回去（`A.stick`）。
       `force=true`：你主动点「回到最新」/ 新发一条指令时，无条件滚到底。 */
    followLog(force){
      // `window.__followN`：探针的把手（无头浏览器里**平滑滚动不跑动画**，量 scrollTop 量不出来，
      // 所以断言"确实喊了跟滚"这一下 —— 真机上配合 CSS 的 scroll-behavior 就是平滑到底）。
      if (!force && !AIR.stick) return;
      window.__followN = (window.__followN || 0) + 1;
      this.$nextTick(() => {
        const el = (this.$refs && this.$refs.log) ||
                   (this.$el && this.$el.querySelector(".ai-log"));
        if (!el) return;
        el.scrollTo({top: el.scrollHeight, behavior: force ? "auto" : "smooth"});
      });
    },
    openRun(id){ aiOpenRun(id); },
    forgetRun(id){ aiForgetRun(id); },
    /* ★ `V-280`：那个折叠块的三颗按钮 */
    selfToggle(){ AIR.selfOpen = !AIR.selfOpen; AIR.rev++; },
    setSelfTab(t){ AIR.selfTab = t; AIR.rev++; },
    async refreshSkills(){ await aiLoadSkills(); toast("技能列表已刷新"); },
    async toggleFullAccess(){
      const want = !this.A.wild;
      try{
        const got = await window.pywebview.api.ai_allow("*", !!want, !!want,
          want ? "完全权限（无人值守）" : "", "set");
        if (!got || !got.ok){ toast((got && got.msg) || "切不了完全权限", true); return; }
        toast(want ? "完全权限已开启：无人值守，不再弹权限 / 覆盖确认"
                   : "完全权限已关闭：恢复按清单来");
      }catch(e){ toast("切不了完全权限：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
    },
    skillOrigin(w){
      if (!w) return "";
      if (w.kind === "pkg") return "【插件】";
      if (w.origin === "seed" || w.layer === "system") return "【⚙️ 出厂样例】";
      return "【✨ 自身生成】";
    },
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
          await aiAfterTruncate(p, t.task, true, r.msg);
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
          await aiAfterTruncate(p, "", false, r.msg);
        }});
    },
    /* ★ `V-253`：底部那颗「发送指令」—— 稿子里的行为是"空着点不给发 + 抖一下" */
    start(){
      const task = String(this.A.task || "").trim();
      if (!task && !(this.A.attachments || []).length){
        this.doShake(); toast("先写一句你要它干什么，或者加个附件。", true); return;
      }
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
      // ★ `V-367`：读不回来就**到此为止** —— 以前照样往下走，会再弹一句"接着这条聊"，
      //   和"读不到这条会话"两句互相打脸（一个动作两条提示）。
      if (!(await aiOpenThread(tail))) return;
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
       工具名由模板里那个 `b` 显示，别在这儿再拼一遍（不然是"改文件 edit_file edit_file"）。
       ★ `V-307`：**模型自己写的 `why`（这一步的目的）优先** —— 你原话"跑一遍 run_moss
          我仅凭这个 无法判断它的目的"。它没写就退回按工具名翻译的那句。 */
    stepTitle(s){
      const why = String((s && s.why) || "").trim();
      if (why) return why;
      const zh = {list_dir: "读目录", read_file: "读文件", grep: "搜内容", edit_file: "改文件",
                  write_file: "写文件", run_moss: "跑一遍", spec: "查契约", done: "收尾",
                  snap_clean: "清快照", ask: "问了你一句", allow_path: "请求放行目录",
                  web_search: "搜网页", web_fetch: "抓网页", github_api: "访问 GitHub",
                  "(思考)": "思考过程"};
      const name = (s && s.tool) || "";
      if (zh[name]) return zh[name];
      // ★ `V-280`：它自己造的手 —— 认出来就明说，别混进"其它"
      if (this.selfNames[name]) return "用自制工具";
      return "其它";
    },
    /* 右边那格（稿子里是"共 89 行, 这是 1-89 行"或时间）。
       ★ `V-307`：**每一步的时间点**（你原话"它没有显示每个步骤的时间点"）+ 耗时 + 烧的 token。 */
    stepMeta(s){
      const bits = [];
      if (s && s.at) bits.push(String(s.at));
      if (s && s.ms >= 300) bits.push((s.ms / 1000).toFixed(1) + "s");
      if (s && s.note) bits.push(String(s.note));
      if (s && s.tokens) bits.push((s.est ? "≈" : "") + cntok(s.tokens) + " tok");
      if (!bits.length && s && s.n) bits.push("第 " + s.n + " 步");
      return bits.join(" · ");
    },
    /* 动作那一行的颜色（稿子里"写文件"用绿色、别的用蓝色） */
    kindColor(t){
      const k = this.toolKind(t);
      if (k === "write") return "var(--aib-success)";
      if (k === "run") return "var(--aib-warning)";
      if (k === "think") return "#8b5cf6";
      if (k === "web") return "#0891b2";
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
      toast("下一条按新会话跑（老记录还在，随时能接着聊）");
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
    attachmentIcon(a){
      const mime = String((a && a.mime) || "").toLowerCase();
      const name = String((a && a.name) || "").toLowerCase();
      if (mime.indexOf("image/") === 0 ||
          /\.(png|jpe?g|gif|webp|bmp|svg|ico|avif)$/.test(name)) return "file-image";
      return "file-text";
    },
    attachmentSize(a){
      const n = Number((a && a.size) || 0);
      if (!n) return "";
      if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
      if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
      return n + " B";
    },
    removeAttachment(i){
      if (i < 0 || i >= AIR.attachments.length) return;
      AIR.attachments.splice(i, 1);
      AIR.rev++;
    },
    pasteAsText(a){
      if (!a || !a.text) return;
      const body = String(a.text);
      AIR.task = (AIR.task ? (AIR.task.replace(/\s*$/, "") + "\n\n") : "") + body;
      const i = AIR.attachments.indexOf(a);
      if (i >= 0) AIR.attachments.splice(i, 1);
      AIR.rev++;
      this.$nextTick(() => this.autoGrow());
    },
    togglePasteAsFile(){
      AIR.pasteAsFile = !AIR.pasteAsFile;
      AIR.rev++;
      toast(AIR.pasteAsFile ? "大段文本会收成附件" : "大段文本会直接粘进输入框");
    },
    onPaste(e){
      if (AIR.running) return;
      const dt = e && e.clipboardData;
      if (!dt) return;
      const files = [];
      const items = dt.items || [];
      for (let i = 0; i < items.length; i++){
        const it = items[i] || {};
        if (it.kind === "file"){
          try { const f = it.getAsFile(); if (f) files.push(f); } catch(err){}
        }
      }
      if (files.length){
        e.preventDefault();
        files.forEach(f => this.readClipboardFile(f));
        return;
      }
      const text = dt.getData ? String(dt.getData("text/plain") || "") : "";
      if (AIR.pasteAsFile && text.length >= ATTACH_TEXT_MIN){
        e.preventDefault();
        aiAddAttachment({kind: "text", source: "paste", name: aiPasteName(text),
                         text: text, size: text.length});
        toast("已把 " + text.length + " 字的大段文本收成附件");
      }
    },
    readClipboardFile(f){
      if (!f) return;
      if (f.size > ATTACH_FILE_MAX){
        toast("附件太大（超过 " + Math.round(ATTACH_FILE_MAX / 1048576) + " MB），先别贴进来了", true);
        return;
      }
      const r = new FileReader();
      r.onload = () => {
        aiAddAttachment({kind: "data", name: f.name || ("粘贴图片." + ((f.type || "image/png").split("/")[1] || "png")),
                         mime: f.type || "image/png", data_url: String(r.result || ""), size: f.size});
        toast("已添加附件：" + (f.name || "图片"));
      };
      r.onerror = () => toast("这个附件读不出来", true);
      r.readAsDataURL(f);
    },
    inputDragEnter(){
      if (!AIR.inputDropHot){ AIR.inputDropHot = true; AIR.rev++; }
    },
    inputDragOver(){ this.inputDragEnter(); },
    inputDragLeave(e){
      const cur = e && e.currentTarget;
      const to = e && e.relatedTarget;
      if (cur && to && cur.contains(to)) return;
      if (AIR.inputDropHot){ AIR.inputDropHot = false; AIR.rev++; }
    },
    inputDrop(){
      // 不在事件里清输入框高亮：真实路径要等宿主回调 `__mossAiDrop` 才到。
      // 另记一个时间戳，兜底 `dragleave` 比 `drop` 先到（那样 inputDropHot 会被清掉）。
      AIR.inputDropAt = Date.now();
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
      /* ★ `V-251`：**换了干活的地方 = 换了一条会话** —— 会话是"一个包一条"，
         切包时必须把接着聊那件事清掉（不然会把别的包的对话塞进这次任务），
         然后去认领新包上次跑的那条。
         ★ `V-315`：干活的地方**就是选中的那个包**（"在哪干活"那个下拉去掉了）——
         所以这里只看 `id` 变没变。 */
      if (id !== AIR.curId){
        AIR.curId = id;
        AIR.contId = ""; AIR.contTask = ""; AIR.viewing = "";
        AIR.steps = []; AIR.result = null; AIR.lastId = ""; AIR.lastAdopted = "";
        AIR.sentTask = ""; AIR.muted = 0; AIR.pickId = "";
        AIR.turns = []; AIR.cur = -1;                 // `V-258`：换了包 = 换一条会话，日志清空
        aiRefreshInfo();
        aiLoadRuns();
      }
      if (AIR.running) aiPollOnce();
      /* ★ `V-345`：浮层开着的时候顺手复算一次位置 —— 左侧栏 hover 展开/收起会让整页横移，
         那不是 window 的 resize（上面那个监听收不到）。fitPop 自己有“没变就跳过”。 */
      if (AIR.permPop) this.fitPop("perm");
      if (AIR.histOpen) this.fitPop("hist");
    }, 700);
    /* ★ V-345：窗口改大改小时重量浮层（不然刚才计算好的位置就过时了） */
    this._rs = () => {
      if (AIR.permPop) this.fitPop("perm");
      if (AIR.histOpen) this.fitPop("hist");
    };
    window.addEventListener("resize", this._rs);
    /* ★ `V-253`（照稿子）：刚进来时文本域是 56px，等一帧量一下（内容长的话自动长高） */
    this.$nextTick(() => this.autoGrow());
    /* ★ `V-307`：滚动监听 —— 判"你是不是贴着底"，决定跟不跟滚（你往上翻就不许抢） */
    this._sc = () => this.onLogScroll();
    this.$nextTick(() => {
      const el = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
      if (el) el.addEventListener("scroll", this._sc, {passive: true});
      this.onLogScroll();
    });
    /* ★ `V-307`/`V-316`：**拖一个文件夹到这一页 = 加进权限清单（读+写都开）**。
       为什么走 `__mossAiDrop` 这个新钩子、不用 `__mossDropHook`：那个是**全局唯一**的，
       已经被「版本快照 → 导出到」占着（草稿里记着这个坑）—— 共用一个就是看谁后挂。
       `drop.js` 里多插了一行调它（见那边的注释）。 */
    window.__mossAiDrop = (items) => {
      if (typeof tab !== "undefined" && tab !== "ai") return false;
      const list = items || [];
      // ★ 拖到输入框上：文件当附件；文件夹不进输入框（提示一句，让它去空白处放行）。
      const _inputHit = AIR.inputDropHot || (Date.now() - Number(AIR.inputDropAt || 0) < 2000);
      if (_inputHit){
        const files = list.filter(x => x && x.path && x.isDir !== true);
        if (files.length){
          const n = aiAttachPaths(files);
          if (n) toast("已添加 " + n + " 个附件");
          AIR.inputDropHot = false; AIR.inputDropAt = 0;
          AIR.rev++;
          return true;
        }
        if (list.some(x => x && x.path)){
          toast("文件夹不能作为附件；想放行目录，请拖到页面空白处。", true);
          AIR.inputDropHot = false; AIR.inputDropAt = 0;
          AIR.rev++;
          return true;
        }
      }
      const it = list.filter(x => x && x.path && x.isDir !== false)[0] ||
                 list.filter(x => x && x.path)[0];
      if (!it) return false;
      // 拖的是**文件** ⇒ 放行**它所在的目录**（放行一个文件本身没意义）
      const p = String(it.path || "");
      const use = (it.isDir === false) ? p.replace(/[\\/][^\\/]*$/, "") : p;
      if (!use) return false;
      AIR.dropHot = false;
      aiAllowAdd(use, "你拖进来的");
      return true;
    };
    /* ★ `V-261`：Alt 那座"我说过的话"导航 —— 监听挂在 window 上（键盘焦点不一定在这一页里） */
    this._kd = e => this.altDown(e);
    this._ku = e => this.altUp(e);
    window.addEventListener("keydown", this._kd, true);
    window.addEventListener("keyup", this._ku, true);
    /* ★ V-265：面板开着的时候，**点别处**也收起来（不然它一直挡着日志）
       ★ V-316：历史那一下拉同样处理 */
    this._md = e => {
      const t = e.target;
      if (AIR.histOpen && !(t && t.closest && t.closest(".ai-hist-wrap"))) AIR.histOpen = false;
      if (AIR.permPop && !(t && t.closest && t.closest(".ai-perm-wrap"))) AIR.permPop = false;
      if (!AIR.altOn) return;
      if (t && t.closest && t.closest(".ai-jump")) return;
      AIR.altOn = false;
    };
    document.addEventListener("mousedown", this._md, true);
  },
  beforeUnmount(){
    window.removeEventListener("keydown", this._kd, true);
    window.removeEventListener("keyup", this._ku, true);
    if (this._rs) window.removeEventListener("resize", this._rs);
    document.removeEventListener("mousedown", this._md, true);
    // ★ `V-307`：把这一页自己挂的东西摘干净（不然换页之后拖放还会去改放行清单）
    try{
      const el = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
      if (el && this._sc) el.removeEventListener("scroll", this._sc);
    }catch(e){}
    if (window.__mossAiDrop) window.__mossAiDrop = null;
    if (AIR.tick){ clearInterval(AIR.tick); AIR.tick = null; }
  },
  template: `
  <div class="aiwrap" @dragover.prevent="dropEnter()" @dragleave="dropLeave($event)">
    <div class="ai-workspace">



      <p class="ai-warn" v-if="A.err">⚠ {{ A.err }}</p>
      <p class="ai-warn" v-else-if="!ready">⚠ {{ (info && info.why) || "还没配好 AI —— 去「设置 → AI」挑一家、把 key 填上。" }}</p>
      <p class="ai-warn" v-if="missing.length">⚠ 提示词文件缺了：{{ missing.join("、") }}（不补也能跑，只是少了那几条规矩）。</p>
      <p class="ai-warn" v-if="target && !canWrite">
        ⚠ 这个包现在<b>只读</b> —— 权限清单里它那一行的<b>「写」没勾</b>。想让它动手：
        在下面那份「目录权限控制」清单里，把这一行的<b>「写」勾上</b>。
      </p>

      <!-- ★ V-280/V-281：**技能** —— 用户平时看不到这一层（不在插件页、不是 :别名、不算包），
           只在 AI 页这儿折叠着露一行；有待批准的时候那行变黄并自动展开。
           技能 = 一个包（pkg.json + 入口 + icon.svg），id 必须用两个短横开头，本体住在
           :skill 插件的数据目录里（user_data/state/skill/）。第一次要你点「允许」，
           而且允许绑指纹 —— 它事后改了 pkg.json / 入口 / 图标就自动退回待批准。
           「管理技能」把 :skill 那个界面嵌出来（图标墙 / 详情 / 转为插件 / 删除都在那边）。 -->
      <section class="ai-skill-widget" v-if="selfTotal">
        <div class="ai-skill-head">
          <div class="ai-skill-tabs">
            <button class="ai-skill-tab" :class="{active: A.selfTab === 'pending'}"
                    type="button" @click="setSelfTab('pending')">
              待批准
              <span class="ai-skill-badge" v-if="selfPendList.length">{{ selfPendList.length }}</span>
            </button>
            <button class="ai-skill-tab" :class="{active: A.selfTab === 'active'}"
                    type="button" @click="setSelfTab('active')">
              已启用
              <span class="ai-skill-count">({{ selfOkList.length }})</span>
            </button>
          </div>
          <div class="ai-skill-actions">
            <button class="ai-skill-iconbtn" type="button" title="管理技能"
                    @click="manageSkills()" v-html='ico("wrench", "i")'></button>
            <button class="ai-skill-iconbtn" type="button" title="刷新列表"
                    @click="refreshSkills()" v-html='ico("refresh-cw", "i")'></button>
          </div>
        </div>

        <div class="ai-skill-list" v-show="A.selfTab === 'pending'">
          <div class="ai-skill-alert" v-if="selfPendList.length">
            <span v-html='ico("alert-triangle", "i")'></span>
            <span>它给自己造了 <strong>{{ selfPendList.length }} 只技能</strong>，你点「允许」它下一次跑才能用。</span>
          </div>
          <div class="ai-skill-row" v-for="w in selfPendList" :key="w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn primary" type="button"
                      v-if="w.layer !== 'system' && !(w.problems || []).length"
                      @click="allowTool(w)">
                <span v-html='ico("check", "i")'></span><span class="txt">允许</span>
              </button>
              <button class="ai-skill-btn" type="button" @click="lookTool(w)">
                <span v-html='ico("eye", "i")'></span><span class="txt">{{ A.selfWho === w.id ? "收起" : "审查" }}</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
            <pre class="ai-skill-pre" v-if="A.selfWho === w.id">{{ A.selfText }}</pre>
          </div>
          <div class="ai-skill-empty" v-if="!selfPendList.length">没有待批准的技能。</div>
        </div>

        <div class="ai-skill-list" v-show="A.selfTab === 'active'">
          <div class="ai-skill-row" v-for="w in selfOkList" :key="w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn" type="button"
                      v-if="w.layer !== 'system'" @click="allowTool(w)">
                <span v-html='ico("corner-up-left", "i")'></span><span class="txt">撤销</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
          </div>
          <div class="ai-skill-row" v-for="w in selfBrokenList" :key="'b' + w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
                · {{ (w.problems || []).join("；") }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn" type="button" @click="lookTool(w)">
                <span v-html='ico("eye", "i")'></span><span class="txt">{{ A.selfWho === w.id ? "收起" : "审查" }}</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
            <pre class="ai-skill-pre" v-if="A.selfWho === w.id">{{ A.selfText }}</pre>
          </div>
          <div class="ai-skill-broken" v-if="selfBrokenList.length">
            <span v-html='ico("alert-triangle", "i")'></span>
            这几只进不了工具表（先修好再说）：{{ selfBrokenNames }}
          </div>
          <div class="ai-skill-empty" v-if="!selfOkList.length && !selfBrokenList.length">还没有已启用的技能。</div>
        </div>
      </section>

      <!-- ★ V-316：**放行清单那一块搬到下面左栏去了**（你原话：「左侧放这个放行这里」）——
           这里不再有独立的「放行」面板，也没有「展开/收起」：权限就是下面左栏那份清单。 -->

      <!-- ★ 「V-333」：**原来那张浮在输入框上面的问答卡整张删了** —— 你原话："申请权限 和复选框
           和用户交互的部分 直接在聊天记录上进行渲染交互 … 那些弹窗就没了 也没有和聊天记录的重叠
           问题了"。现在：问题 / 选项 / 「就这么回」/ 允许·拒绝，全部长在**聊天记录里那条气泡**上
           （见上面 「ai-turn」 里 「type === 'talk'」 那一段），答完那条记录里就写着你的选择。 -->

      <!-- 中间日志流（V-263：**不再重复显示会话名** —— 顶栏那个下拉已经写着当前会话了）
           ★ 「V-333」：原来那层"给聊天区盖遮罩"（「V-332」）**撤了** —— 交互已经搬进聊天记录里，
             再压暗就等于把要点的东西一起压暗了。 -->
      <main class="log-container ai-log" ref="log">
        <!-- ★ V-258/263：日志按轮排 —— 一轮 = 我说的那句 + 它的动作 + 它的结论。
             ★ 「V-333」（你原话："整体改成那种微信气泡泡的风格 把我说的 和ai说的 以及 其他内容信息
               分开 且给各自不同的图标 … 那些弹窗就没了 也没有和聊天记录的重叠问题了 我选择以后
               后续我翻看聊天记录 也能看我之前的选择"）：
               · **我说的** = 右边蓝色气泡（「moss-user」 图标）；
               · **它说的**（问题 / 请求放行 / 结论）= 左边白气泡（「sparkles」 图标），
                 要你点头的那种气泡里**直接带按钮 / 选项 / 输入框**；
               · **其他信息**（它调了什么工具）= 整宽的淡底小条（各自的工具图标）。
               权限请求和问答现在**都是聊天记录里的一条**（宿主把它记进步骤流，答完写回同一条）。 -->
        <div class="ai-turn" v-for="(t, ti) in A.turns" :key="t.key">
          <div class="ai-bub me">
            <span class="ai-bub-ic" v-html='ico("moss-user", "i")'></span>
            <div class="ai-bub-b">
              <div class="ai-bub-h">
                <b class="ai-th-n">#{{ ti + 1 }}</b>
                <span class="ai-th-a" :title="t.note || t.at"
                      :class="{bad: /接不上/.test(t.note || '')}"
                      >{{ t.folded ? ("已折叠 · " + (t.note || "点一下展开")) : (t.note || t.at || "") }}</span>
                <!-- ★ V-279：这一轮的「改」和「删」（带 @click.stop，不然会顺手折叠掉） -->
                <span class="ai-th-x">
                  <button @click.stop="openTurn(t, ti)"
                          title="查看这一轮的详情，或看它和 AI 交互的完整源码 JSON">源码</button>
                  <template v-if="t.id && !A.running">
                    <button @click.stop="editTurn(t)"
                            title="改这一轮：回到它开工前的快照（撤销它改的东西），并把这句话填回输入框 —— 改好再发一次">编辑</button>
                    <button class="danger" @click.stop="delTurn(t)"
                            title="删这一轮：从这一轮到会话末尾的记录一起删掉，并按快照回退">删除</button>
                  </template>
                </span>
              </div>
              <div class="ai-bub-t" @click="toggleTurn(ti)"
                   :title="t.folded ? '点一下展开中间过程' : '点一下折叠中间过程'">{{ t.task }}</div>
              <div class="ai-bub-atts" v-if="(t.attachments || []).length">
                <span v-for="a in t.attachments" :key="a.name">📎 {{ a.name }}</span>
              </div>
            </div>
          </div>

          <template v-if="!t.folded">
            <template v-for="c in turnCards(t)" :key="c.key">
              <!-- ① 它说的（问 / 求放行）：**按钮就长在这条气泡里** -->
              <div class="ai-bub ai talk" v-if="c.type === 'talk'" :class="{waiting: !c.step.done}">
                <span class="ai-bub-ic"
                      v-html='ico(c.step.tool === "perm" ? "file-lock" : (c.ta.kind === "confirm" ? "alert-triangle" : "message-circle"), "i")'></span>
                <div class="ai-bub-b">
                  <div class="ai-bub-h">
                    <b>{{ c.step.tool === "perm" ? "它想放行一个目录" : (c.ta.kind === "confirm" ? "危险操作" : "它在问你") }}</b>
                    <span class="dim" v-if="!c.step.done && c.ta.qid && A.ask && A.ask.qid === c.ta.qid">
                      已经等了 {{ A.ask.asking }} 秒</span>
                    <span class="dim" v-else-if="!c.step.done && c.ta.path && A.perm && A.perm.path === c.ta.path">
                      已经等了 {{ A.perm.asking }} 秒</span>
                  </div>
                                      <p class="ai-bub-q" v-if="c.step.tool === 'perm'">
                      请求放行目录：<br>
                      <span @click="openDir(c.ta.path)" style="cursor: pointer; text-decoration: underline; color: var(--accent); word-break: break-all;" title="在资源管理器中打开">{{ c.ta.path }}</span>
                    </p>
                    <p class="ai-bub-q" v-else>{{ c.step.brief }}</p>
                  <p class="ai-bub-w" v-if="c.step.why">为什么：{{ c.step.why }}</p>
                  <p class="ai-bub-w" v-if="c.ta.detail">{{ c.ta.detail }}</p>

                  <!-- 还没答：给动作（和以前那张卡一模一样的三条路：选项 / 打字 / 允许拒绝） -->
                  <div class="ai-bub-a" v-if="!c.step.done">
                    <template v-if="c.step.tool === 'perm'">
                      <button class="btn btn-primary" :disabled="A.askBusy" @click="reqAllow()"
                              v-html='ico("check", "i") + " 允许"'></button>
                      <button class="btn btn-danger" :disabled="A.askBusy" @click="reqDeny()"
                              v-html='ico("x", "i") + " 拒绝"'></button>
                    </template>
                    <template v-else>
                      <button class="ai-ask-opt" v-for="o in (c.ta.options || [])" :key="o.value"
                              :disabled="A.askBusy" @click="answer(o.value, A.askText, c.ta.qid)">
                        <span class="ai-ask-opt-t">{{ o.label }}</span>
                        <span class="ai-ask-opt-d" v-if="o.desc">{{ o.desc }}</span>
                      </button>
                      <div class="ai-ask-t" v-if="c.ta.allow_text">
                        <input v-model="A.askText" spellcheck="false" :disabled="A.askBusy"
                               placeholder="也可以直接打字回它（回车发送）"
                               @keydown.enter.prevent="answer('', A.askText, c.ta.qid)">
                        <button class="ai-ask-send" :disabled="A.askBusy"
                                @click="answer('', A.askText, c.ta.qid)">就这么回</button>
                      </div>
                    </template>
                  </div>

                  <!-- 答完了：这条记录里写着**你当时选了什么**（翻旧会话照样看得见） -->
                  <!-- 答完了：候选项照稿子排成胶囊（选中的那颗高亮打勾），回答跟在后面 -->
                  <div class="ai-bub-ans" v-else>
                    <div class="ai-ask-history" v-if="c.step.tool === 'ask' && c.ta.options && c.ta.options.length">
                      <span class="ai-ask-history-label">全部候选项：</span>
                      <span class="ai-ask-history-opt" v-for="o in c.ta.options" :key="o.value"
                            :class="{chosen: String(o.value) === String(c.step.answer)}">
                        {{ o.label }}
                      </span>
                    </div>
                    <span class="ai-bub-mine" v-if="c.step.answer">{{ c.step.answer }}</span>
                    <span class="ai-bub-note">{{ c.step.out || "（答完了）" }}</span>
                  </div>
                </div>
              </div>

              <!-- ② 其他信息：它调了什么工具（整宽淡底一条，图标各自不同） -->
              <div class="step-card ai-step" v-else
                   :class="'k-' + toolKind(c.tool)" :data-tool="c.tool || ''"
                   @click="openStep(c)"
                   :title="c.tool === '(思考)' ? '点一下展开思考过程（默认折叠）' : ('点一下看这一步的原始参数与输出（工具：' + (c.tool || '?') + '）')">
                <div class="step-icon" v-html='ico(c.icon, "i")'></div>
                <div class="step-content">
                  <div class="step-header">
                    <span class="step-action" :style="{color: c.color}">{{ c.action }} <b>{{ c.tool }}</b></span>
                    <span class="step-meta">{{ c.meta }}</span>
                  </div>
                  <span class="code-path" v-if="c.path">{{ c.path }}</span>
                </div>
                <span class="ai-step-x" v-html='ico("eye", "i")'
                      :title="c.tool === '(思考)' ? '展开思考过程' : '点一下看这一步的原始参数与输出'"></span>
              </div>
            </template>

          </template>

            <!-- ③ 它说的（结论）：左边白气泡 -->
            <div class="ai-bub ai" v-if="t.result">
              <span class="ai-bub-ic" v-html='ico("sparkles", "i")'></span>
              <div class="ai-bub-b">
                <div class="ai-result" :class="{ok: !!t.result.ok, bad: !t.result.ok}">
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
              </div>
            </div>
        </div>

        <p class="ai-empty" v-if="!A.turns.length">
          还没有跑过。写下你要它做什么 —— 它会读代码、动手改、跑一遍验证，然后把结果摆在这儿。
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

        <!-- ★ V-307：**你往上翻的时候它不许把你拽回底部**（你报的那条）。
             不跟滚的时候右下角浮一颗「回到最新」，点它才回去、并且重新跟上。 -->
        <button class="ai-tobottom" v-if="!A.stick" @click="toBottom()"
                :title="'有新内容 —— 点一下回到最新（你往上翻的时候它不会抢你的滚动条）'"
                v-html='ico("chevron-down", "i") + " 回到最新"'></button>
      </main>

      <!-- ★ V-340：**所有按钮和信息都收进下面这一条工具栏**（照新稿子重排）——
           顶上那条"历史图标"栏、左下角那张常驻权限卡都撤了，改成两个**点开才出的浮层**：
             · 历史会话（点一条切过去；行尾垃圾篓直接删）
             · 目录权限（粘路径 / 选目录 / 读·写开关 / 删）
           中间日志流因此拿回整幅宽度，整页只剩「聊天 + 一条输入工具栏」两层。 -->
      <footer class="bottom-area ai-foot ai-split">
        <div class="chat-input-container ai-box ai-right"
             :class="{focused: focused, 'error-shake': shake, 'drop-hot': A.inputDropHot}"
             @dragover.prevent="inputDragOver"
             @dragenter.prevent="inputDragEnter"
             @dragleave="inputDragLeave($event)"
             @drop="inputDrop">
          <div class="ai-atts" v-if="A.attachments.length">
            <div class="ai-at" v-for="(a, i) in A.attachments" :key="a.key"
                 :class="{img: attachmentIcon(a) === 'file-image'}">
              <span class="ai-at-ic" v-html='ico(attachmentIcon(a), "i")'></span>
              <span class="ai-at-n" :title="a.path || a.name">{{ a.name }}</span>
              <span class="ai-at-s" v-if="a.size">{{ attachmentSize(a) }}</span>
              <button class="ai-at-act" type="button" v-if="a.kind === 'text' && a.source === 'paste'"
                      @click="pasteAsText(a)" title="把这段原文放回输入框，按普通粘贴发出去">粘贴原文至输入框</button>
              <button class="ai-at-x" type="button" @click="removeAttachment(i)" title="移除附件"
                      v-html='ico("x", "i")'></button>
            </div>
          </div>
          <div class="input-area">
            <textarea class="prompt-textarea ai-task" ref="ta" v-model="A.task" spellcheck="false"
              :disabled="A.running" @input="autoGrow" @focus="focused = true" @blur="focused = false"
              @keydown="onKey" @paste="onPaste"
              placeholder="在此输入指令... (按 Enter 发送，Shift+Enter 换行)"></textarea>
          </div>

          <div class="toolbar">
            <div class="toolbar-left">
              <!-- Token：消耗 / 上限（单位一律"百万"），进度条当背景；上限数字可直接改 -->
              <span class="tool-text ai-bud token-pill" role="progressbar"
                    :aria-valuenow="tokenPct" aria-valuemin="0" aria-valuemax="100"
                    :title="tokTip + '；点击上限数字可编辑（单位：百万）'">
                <span class="token-pill-fill" :style="{width: tokenPct + '%'}"></span>
                <span class="token-pill-text">{{ tokenUsedMillions }} /
                  <input class="ai-token-limit ai-bud-n" type="number" min="0.5" max="20000" step="10"
                         v-model.number="A.maxMillions" :disabled="A.running" @change="saveBudget()"
                         title="token 上限（单位：百万）：这次任务最多烧多少 token。烧到 80% 时劝它收尾，到顶就停手。" aria-label="token 上限（百万）"> 百万</span>
              </span>

              <!-- 提示词：只留图标 -->
              <button class="trigger-btn ai-mini ai-messages-icon" @click="openMessages()"
                      title="查看这条会话的完整提示词历史"
                      v-html='ico("file-text", "i")'></button>
              <button class="trigger-btn ai-mini ai-paste-file" :class="{active: A.pasteAsFile}"
                      @click="togglePasteAsFile()"
                      :title="A.pasteAsFile ? '大段文本粘贴：收成附件（点击改成直接粘进输入框）' : '大段文本粘贴：直接粘进输入框（点击改成收成附件）'"
                      v-html='ico("clipboard-paste", "i")'></button>

              <!-- 历史会话（点开才出） -->
              <div class="popover-wrapper ai-hist-wrap">
                <button ref="histBtn" class="trigger-btn ai-hist" :class="{active: A.histOpen}" @click.stop="toggleHist()"
                        :title="'历史会话（只列这个包的）。现在：' + ((sessCurrent && sessCurrent.head && sessCurrent.head.task) || '新会话')">
                  <span v-html='ico("history", "i")'></span> 历史会话
                  <span class="badge" v-if="sessChains.length">{{ sessChains.length }}</span>
                </button>
                <div ref="histPanel" class="popover-panel ai-hist-list" :class="{show: A.histOpen}" v-if="A.histOpen" @click.stop>
                  <div class="popover-title">当前包的历史<span class="popover-hint">点一条就切过去</span></div>
                  <div class="history-list">
                    <div class="history-item ai-hist-i" v-for="c in sessChains" :key="c.head.id"
                         :class="{active: sessCurrent && (sessCurrent.head.id === c.head.id)}"
                         :title="(c.head.task || '') + '　' + chainMeta(c)"
                         @click="pickChain(c)">
                      <div class="history-item-left">
                        <span class="status-dot"></span>
                        <span class="history-item-title ai-hist-t">{{ chainTitle(c) }}</span>
                      </div>
                      <div class="history-item-right">
                        <span class="ai-hist-m">{{ chainMeta(c) }}</span>
                        <button class="btn-delete ai-hist-x" @click.stop="delChain(c)" title="删除这次会话（它下面所有轮次）"
                                v-html='ico("trash-2", "i")'></button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 完全权限（无人值守）：一键把「任意路径」读写都打开，不再弹权限 /
                   危险操作 / 覆盖确认。关掉就恢复成按清单来。 -->
              <button class="trigger-btn ai-mini ai-fullperm" :class="{active: A.wild}"
                      type="button" @click="toggleFullAccess()"
                      :title="A.wild ? '完全权限已开启：无人值守，不再弹权限 / 覆盖确认。点一下关掉。'
                                     : '开启完全权限：任意路径可读写，危险操作 / 覆盖也不再问。'">
                <span v-html='ico(A.wild ? "shield-check" : "shield", "i")'></span>
                {{ A.wild ? "完全权限 · 开" : "完全权限" }}
              </button>
              <!-- 目录权限（点开才出） -->
              <div class="popover-wrapper ai-perm-wrap ai-perm" :class="{folded: !A.permPop}">
                <button ref="permBtn" class="trigger-btn ai-perm-fold" :class="{active: A.permPop}" @click.stop="togglePermPop()"
                        title="管理它读写哪些目录（点开看清单）">
                  <span v-html='ico("file-lock", "i")'></span> 目录权限控制
                  <span class="badge ai-perm-badge">{{ permBadge }}</span>
                  <span class="dim ai-perm-foldw" v-if="A.perm">· 它想用「{{ permPendingLabel }}」</span>
                </button>
                <div ref="permPanel" class="popover-panel ai-perm-body" :class="{show: A.permPop}" v-if="A.permPop" @click.stop>
                  <div class="popover-header ai-perm-add" :class="{hot: A.dropHot, bad: addPathBad || !!A.newPathErr}">
                    <input v-model="A.newPath" spellcheck="false"
                           placeholder="粘一个目录路径（或把文件夹拖到这一页）"
                           :title="addPathBad ? ('这不是一个路径 —— ' + addPathHint) : '粘一个目录的完整路径'"
                           @input="A.newPathErr = ''" @keydown.enter.prevent="allowAdd()">
                    <button class="btn" @click="allowPick()" title="用系统对话框选一个目录加进来"
                            v-html='ico("folder-open", "i") + " 选目录"'></button>
                    <button class="btn" @click="allowAdd()" :disabled="!canAddPath"
                            :title="canAddPath ? '把这个目录加进清单（读 + 写都开）' : '先填一个存在的目录的完整路径'"
                            v-html='ico("moss-plus", "i") + " 添加"'></button>
                  </div>
                  <p class="ai-perm-err" v-if="addPathBad || A.newPathErr">
                    <span v-html='ico("circle-alert", "i")'></span>
                    {{ addPathBad ? addPathHint : A.newPathErr }}
                  </p>
                  <div class="path-list">
                    <div class="path-item ai-perm-i" v-for="it in allowRows" :key="it.path"
                         :class="{star: it.path === '*'}">
                      <div class="path-info ai-perm-info" :title="it.path">
                        <!-- ★ V-344：盘符 + 上一级\最后一级钉死，中间那段自己缩（够就不省） -->
                        <div class="path-title ai-perm-p">
                          <template v-if="it._p && it._p.tail">
                            <span class="pp-head" v-if="it._p.head">{{ it._p.head }}</span>
                            <span class="pp-mid" v-if="it._p.mid">{{ it._p.mid }}</span>
                            <span class="pp-tail">{{ it._p.tail }}</span>
                          </template>
                          <template v-else>{{ permLabel(it) }}</template>
                        </div>
                        <div class="path-desc ai-perm-d">{{ permDesc(it) }}</div>
                      </div>
                      <div class="path-controls ai-perm-togs">
                        <label class="switch-group ai-sw" :title="'读：勾上它才能看 ' + it.path">读
                          <span class="switch"><input type="checkbox" :checked="!!it.read"
                            @change="allowSet(it, 'read', $event.target.checked)"><span class="slider"></span></span>
                        </label>
                        <label class="switch-group ai-sw" :title="'写：勾上它才能改 ' + it.path + '（关掉 = 只让它看）'">写
                          <span class="switch"><input type="checkbox" :checked="!!it.write"
                            @change="allowSet(it, 'write', $event.target.checked)"><span class="slider"></span></span>
                        </label>
                        <!-- ★ V-344：hover 才出的两颗：复制路径 / 打开文件夹 -->
                        <button class="btn-delete ai-perm-act" v-if="it.path !== '*'" @click="copyPath(it)"
                                title="复制这个路径" v-html='ico("copy", "i")'></button>
                        <button class="btn-delete ai-perm-act" v-if="it.path !== '*'" @click="openDir(it.path)"
                                title="在资源管理器里打开" v-html='ico("folder-open", "i")'></button>
                        <button class="btn-delete ai-perm-x" v-if="it.path !== '*' && !it.current" @click="allowRm(it)"
                                title="从清单里删掉（它就读不了也写不了这里）" v-html='ico("trash-2", "i")'></button>
                        <span class="ai-perm-lock" v-else v-html='ico("file-lock", "i")'
                              title="系统默认那一行 / 当前这个包，删不掉（把开关关掉就行）"></span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="toolbar-right ai-actions">
              <div class="custom-select select-model btn-model" @click="openSel($event)"
                   :title="'这次用哪个模型。这家配了 ' + models.length + ' 个；换模型连带换上下文窗口。'">
                <span v-html='ico("sparkles", "i")'></span>
                <select class="ai-model" v-model="A.model" :disabled="A.running || !models.length"
                        @change="pickModel()">
                  <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
                  <option v-if="!models.length" value="">（还没配 AI）</option>
                </select>
              </div>
              <button class="btn btn-outline" v-if="A.running" @click="stop"
                      v-html='ico("square", "i") + " 停止"'></button>
              <div class="action-group">
                <button class="action-group-btn btn-new-chat" @click="pickNewChat()"
                        title="新建空白会话（下一条不带之前的对话）"
                        v-html='ico("moss-plus", "i")'></button>
                <button class="action-group-btn btn-send-main btn primary"
                        :disabled="A.running || A.busy || !ready" @click="start"
                        title="发送 (Enter)"
                        v-html='A.running ? ico("loader-2", "i spin") : ico("send", "i")'></button>
              </div>
            </div>
          </div>
        </div>
      </footer>

      <!-- ★ V-315 / 重设计：点开某一步看原始细节 —— 思考过程/工具/对话都有「详情 + 源码」两个页签。 -->
      <div class="ai-modal-overlay" v-if="A.stepOpen" @click.self="closeStep()">
        <div class="ai-modal-box">
          <div class="ai-modal-header">
            <div class="ai-modal-title-group">
              <h3 class="ai-modal-title">
                <span v-html='ico(A.stepOpen.tool === "(思考)" ? "lightbulb" : (A.stepOpen.tool === "(对话)" ? "message-square" : "search"), "i")'></span>
                {{ A.stepOpen.tool === "(思考)" ? "模型思考过程" : (A.stepOpen.tool === "(对话)" ? ("第 " + A.stepOpen.n + " 轮 · 对话") : ("第 " + A.stepOpen.n + " 步 · " + A.stepOpen.tool)) }}
              </h3>
              <span class="ai-modal-meta">{{ stepHead(A.stepOpen) }}</span>
            </div>
            <button class="ai-modal-close" type="button" title="关闭"
                    @click="closeStep()">&times;</button>
          </div>
          <div class="ai-modal-tabs">
            <button class="ai-modal-tab" type="button"
                    :class="{active: A.modalTab === 'detail'}"
                    @click="setModalTab('detail')">查看详情</button>
            <button class="ai-modal-tab" type="button"
                    :class="{active: A.modalTab === 'source'}"
                    @click="setModalTab('source')">查看源码</button>
          </div>
          <div class="ai-modal-body">
            <template v-if="A.modalTab === 'detail'">
              <template v-if="A.stepOpen.tool === '(思考)'">
                <div class="ai-thought-content">
                  <span class="ai-thought-hint">原始思考记录（展开）：</span>
                  <p class="ai-thought-text">{{ A.stepOpen.out || "（这次没有思考过程）" }}</p>
                </div>
              </template>
              <template v-else-if="A.stepOpen.tool === '(对话)'">
                <div class="ai-modal-sec">
                  <h4>用户指令</h4>
                  <p class="ai-thought-text">{{ (A.stepOpen.turn || {}).task || "（空）" }}</p>
                </div>
                <div class="ai-modal-sec" v-if="((A.stepOpen.turn || {}).attachments || []).length">
                  <h4>附件</h4>
                  <p class="ai-thought-text">共 {{ ((A.stepOpen.turn || {}).attachments || []).length }} 个附件</p>
                </div>
                <div class="ai-modal-sec">
                  <h4>中间过程</h4>
                  <p class="ai-thought-text">共 {{ (((A.stepOpen.turn || {}).steps) || []).length }} 个步骤</p>
                </div>
                <div class="ai-modal-sec" v-if="(A.stepOpen.turn || {}).result">
                  <h4>最终结果</h4>
                  <p class="ai-thought-text">{{ ((A.stepOpen.turn || {}).result || {}).summary || (((A.stepOpen.turn || {}).result || {}).reason || "（没写总结）") }}</p>
                </div>
              </template>
              <template v-else>
                <p class="ai-detail-w" v-if="A.stepOpen.why">它说这一步是为了：{{ A.stepOpen.why }}</p>
                <div class="ai-modal-sec">
                  <h4>参数</h4>
                  <pre class="ai-msg-t">{{ A.stepOpen.args || "（这一步没有参数）" }}</pre>
                </div>
                <div class="ai-modal-sec">
                  <h4>输出</h4>
                  <pre class="ai-msg-t">{{ A.stepOpen.out || "（这一步没有输出）" }}</pre>
                </div>
              </template>
            </template>
            <div class="ai-json-view" v-show="A.modalTab === 'source'"
                 v-html="modalSourceHtml()"></div>
          </div>
          <div class="ai-modal-footer">
            <button class="ai-modal-btn" type="button" @click="copyModal()">复制</button>
            <button class="ai-modal-btn primary" type="button" @click="closeStep()">关闭</button>
          </div>
        </div>
      </div>

      <!-- ★ V-307：**看这条会话喂给它的完整提示词**（系统提示 + 每一问 + 每一答 + 工具结果）。
           同样收进模态框，长内容不再把聊天区挤变形。 -->
      <div class="ai-modal-overlay" v-if="A.msgOpen" @click.self="closeMessages()">
        <div class="ai-modal-box">
          <div class="ai-modal-header">
            <div class="ai-modal-title-group">
              <h3 class="ai-modal-title">
                <span v-html='ico("file-text", "i")'></span>
                完整提示词历史
              </h3>
              <span class="ai-modal-meta" v-if="A.msgData">
                {{ A.msgData.count || 0 }} 条 · {{ A.msgData.bytes || 0 }} 字节
                <template v-if="A.msgData.model"> · 模型 {{ A.msgData.model }}</template>
              </span>
            </div>
            <button class="ai-modal-close" type="button" title="关闭"
                    @click="closeMessages()">&times;</button>
          </div>
          <div class="ai-modal-body">
            <p class="ai-msgs-note dim" v-if="A.msgBusy">正在读…</p>
            <p class="ai-msgs-note" v-else-if="A.msgData && !A.msgData.ok">{{ A.msgData.msg || A.msgData.note }}</p>
            <div class="ai-msgs-b" v-else>
              <div class="ai-msg" v-for="(m, i) in ((A.msgData && A.msgData.messages) || [])" :key="i"
                   :class="'r-' + (m.role || '?')">
                <div class="ai-msg-h">
                  <b>{{ roleName(m.role) }}</b>
                  <span class="dim">{{ msgHead(m) }}</span>
                </div>
                <pre class="ai-msg-t">{{ msgText(m) }}</pre>
              </div>
            </div>
          </div>
          <div class="ai-modal-footer">
            <button class="ai-modal-btn" type="button" @click="copyMessages()">复制</button>
            <button class="ai-modal-btn primary" type="button" @click="closeMessages()">关闭</button>
          </div>
        </div>
      </div>

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
mountVue(MossAi, "#pane-ai", {ico: ico, pSym: () => PSYM});   // `pSym()`：跑包符号（`V-305`，别硬编码 `:`）




