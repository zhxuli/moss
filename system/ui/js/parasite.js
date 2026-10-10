/* moss 界面 · parasite.js —— **寄生模式**（`V-379`）
   ============================================================================
   你 2026-10-10 原话：「有时候 我希望某个插件 当我点击它的时候 直接显示界面或者命令行
   相当于点击以后 自己点运行按钮；而切换到其他插件以后 这个插件自动停止 相当于又点了停止
   按钮 这样的话 就感觉这个插件 本身就是这个软件的一部分 融合的更紧密了 无感运行」。
   ⇒ 名字**是你定的**：叫「寄生模式」（我原本建议"选中即运行"，你说要寄生 —— 那就寄生。
     跟 moss 自己的那个词「宿主」正好配成一对：宿主 + 寄生。）

   一句话：**点它就运行、离开它就停**。
     · 进（你在左边点了这个包）⇒ 没在跑就跑一次 —— 走的是右上角那颗「运行」按钮
       **同一条路**（`embed.js::clickRun`）：有界面的包 ⇒ 切到「界面」；有输出的包 ⇒ 输出
       进「命令行」（`maybeAutoSwitch` 那条规矩照旧）；纯 GUI 又没输出的 ⇒ 留在原地（`U-16`，
       不抢你正在看的那一页）。
     · 出（你点了别的包）⇒ 还在跑就停掉，走的也是那颗「停止」按钮同一条路。
   ★ 只认**你亲手点左边列表**（`list.js::pick`）。程序自己调 `select()` 的那些（更名跟随 /
     刷新 / 自动运行…）**不算"你切走了"**，不会把东西停掉。
   ★ **你手动按了停止，它不会自己又爬起来**：这一套只在"你换了选择"那一刻动作，按停止不产生
     新的选择事件。（再点一下这个包 = 你又要它跑，那就跑 —— 这正是"点它就运行"。）
   ★ 和「自动运行」互不干扰：开机那一批照旧跑，只有**你手动切走**时才停。
   ★ 开关存 `user_data/state/_ui_parasite.json`（**不进 `pkg.json`**：那是你的用法选择，
     不是包的属性 —— 清单会被升级整体替换，AI 也不该能替你打开它）。

   ★ 这一页是**经典脚本**（和别的 js 一样共享全局）：顶层名字不许重名（`界面检查.py` 第 11 条）。
*/
const PARA = {ids: [], loaded: false};

/* 名单里有没有它。名单还没读回来时先当"没有"（详情页那一行先画成未启用，读完再重画一次）。 */
function parasiteHas(id){ return (PARA.ids || []).indexOf(String(id)) >= 0; }

/* 读一次（`force` = 不管缓存重读，比如刚存完）。读不到**不抛**：详情页少一行，别的照旧。 */
async function parasiteLoad(force){
  if (PARA.loaded && !force) return PARA.ids;
  let r = null;
  try{ r = await pywebview.api.parasite_get(); }catch(e){ r = null; }
  if (r && r.ok){
    PARA.ids = (r.ids || []).map(x => String(x));
    PARA.loaded = true;
  }
  return PARA.ids;
}

/* 名单变了就**整份**存回去（和插件列表排序一个路子：不会有"存漏一半"）。成功回 true。 */
async function parasitePersist(){
  let r = null;
  try{ r = await pywebview.api.parasite_set(PARA.ids || []); }catch(e){ r = null; }
  if (!r || !r.ok){
    toast("✗ 没存上寄生模式：" + ((r && r.msg) || "宿主没回话"), true);
    return false;
  }
  PARA.ids = (r.ids || []).map(x => String(x));
  PARA.loaded = true;
  return true;
}

/* 改名时跟着搬（`list.js::pkgFollowId` 调它）—— 名单是按**包 id** 记的，不搬就两头不着。 */
async function parasiteRename(oldId, newId){
  if (!oldId || !newId || String(oldId) === String(newId)) return 0;
  await parasiteLoad(true);
  let n = 0;
  PARA.ids = (PARA.ids || []).map(x => {
    if (String(x) === String(oldId)){ n++; return String(newId); }
    return x;
  });
  if (n) await parasitePersist();
  return n;
}

/* ---------------------------------------------------------------- 详情页那一行
   和「自动运行」那一行同一套壳（`.dp-item`）：图标 + 标题 + 一句大白话 + 一颗 启用/禁用。
   ★ 文案按家规（`V-367`）：只说"会发生什么"，不写我们内部怎么实现的。 */
function parasiteSectionHTML(id){
  const on = parasiteHas(id);
  return '<div class="dp-item" id="para-sec">' +
      '<div class="dp-item-info">' +
        '<span class="dp-item-ico">' + ico("plug", "i") + '</span>' +
        '<div class="dp-item-text">' +
          '<h4>寄生模式' +
            '<span class="dp-tip dp-tip-ico" data-tip="与moss合体，点它自动运行、切到别的插件它自动停">' +
              ico("info", "i") + '</span>' +
          '</h4>' +
          '<p>与系统结合更加紧密</p>' +
        '</div>' +
      '</div>' +
      '<div class="dp-item-acts">' +
        '<button type="button" class="dp-ghost' + (on ? " on" : "") + '" id="para-sw"' +
          ' role="switch" aria-checked="' + (on ? "true" : "false") + '" title="' +
          (on ? "现在开着 —— 点一下关掉（关掉之后点它不再自动运行）"
              : "点一下打开：以后选中这个插件就自动运行、切走自动停") + '">' +
          ico(on ? "circle-slash" : "circle-check", "i") +
          '<span>' + (on ? "禁用" : "启用") + '</span></button>' +
      '</div>' +
    '</div>';
}

/* 接线（`wireDetail` 里调一次）。
   ★ 第一次读回来跟刚才画的不一样（缓存里本来没有）⇒ 重画一次，让"启用/禁用"对上。 */
async function parasiteWire(id){
  const before = PARA.loaded;
  await parasiteLoad();
  if (!before && PARA.loaded && typeof renderDetail === "function") renderDetail();
  const sw = $("#para-sw");
  if (!sw) return;
  sw.onclick = async () => {
    const was = parasiteHas(id);
    if (was) PARA.ids = (PARA.ids || []).filter(x => String(x) !== String(id));
    else PARA.ids = (PARA.ids || []).concat([String(id)]);
    if (!await parasitePersist()) { renderDetail(); return; }
    renderDetail();                       // 重画：按钮的字、图标、颜色都要跟着翻
    setTimeout(() => autoSavedHint($("#para-sw"), was ? "已关掉" : "已打开"), 60);
  };
}

/* ---------------------------------------------------------------- 编排：点它就运行、离开就停
   `pick()`（你亲手点左边列表）会调这个；程序自己调 `select()` **不走这儿**。
   `prev` = "点之前选中的是谁" —— 由 `pick` 在 `select()` 之前抓下来（`select` 会把 `cur` 换掉）。 */
async function parasiteOnPick(id, prev){
  await parasiteLoad();
  const now = String(id || "");
  if (!now) return;
  // ① 出：上一个开着寄生、又不是现在这个 ⇒ 停掉
  if (prev && String(prev) !== now && parasiteHas(prev)) await parasiteStop(String(prev));
  // ② 进：这个开着寄生 ⇒ 确保它在跑
  if (parasiteHas(now)) await parasiteEnsureRunning(now);
}

/* 确保这个包**跑着**：没在跑才动手，走 `clickRun`（和那颗「运行」按钮一模一样）。
   ★ 为什么要等一拍：`select()` 刚把详情页重画过，Vue 下一拍才换 DOM —— 立刻点运行会拿着
     **上一个包**的参数框内容去跑（那颗按钮是从 `#args` 里读参数的）。 */
async function parasiteEnsureRunning(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  if (!p || pkgRunning(p)) return;
  await new Promise(r => setTimeout(r, 0));
  if (pkgRunning(p)) return;              // 这一拍里它自己起来了（别起两次）
  await clickRun(p);
}

/* 确保这个包**停掉**：没在跑就什么都不做（走的也是那颗「停止」按钮）。 */
async function parasiteStop(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  if (!p || !pkgRunning(p)) return;
  await clickRun(p);
}
