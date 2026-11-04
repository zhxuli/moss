/* moss 界面 · js/sound.js —— 音效提醒（AI 跑完 / 有事要你确认时响一下）
   ============================================================================
   真正放声音的是**界面进程**（`pywebview.api.sound_play`）：WebView2 是 Chromium，
   页面里的 `<audio>` 会被自动播放策略挡掉（"还没跟这一页交互过"就不给响、刷新之后
   就不响，而且**一句错都不报**）；放在 Python 那边用系统的 MCI / winsound 放，没这个问题。

   谁会调它（就三处）：
     · `js/ai.js`：这一跑**刚结束**（running 从 true 变 false）⇒ `finish`；
     · `js/ai.js`：它在等你动手（新冒出来的一张问话卡 / 要你放行一个目录）⇒ `warn`；
     · `js/settings.js`：那两行上的「试听」和"刚换完文件" ⇒ 同一套（`force` 不看开关）。

   ★ 开没开、放哪个文件，全由 Python 那边按 `config.toml` 的 `[sound]` 判 ——
     这里**不读配置、也不缓存状态**：两边各判一次，迟早会不一致。
   ★ 名字（`SND` / `sndNotify`）在 `js/*.js` 里必须唯一：这些文件是经典脚本、共享
     同一个全局作用域，重名会把前一个**整个盖掉**而且不报错（见 drop.js 里那段血的
     教训 / `tools/界面检查.py` 第 11 条）。 */
const SND = {at: {}};

/* 响一下。`force = true` 表示"试听"：不管开关、也不管刚才是不是刚响过。
   ★ 同一种音效 1.2 秒内只响一次：轮询 700ms 一跳，而"它在等你"那张卡会连着好几跳
     都是同一个（`AIR.ask` / `AIR.perm` 没变）—— 不去重就是一串连发。 */
function sndNotify(kind, force){
  kind = (kind === "warn") ? "warn" : "finish";
  const now = Date.now();
  if (!force && now - (SND.at[kind] || 0) < 1200) return;
  SND.at[kind] = now;
  try{
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.sound_play !== "function") return;
    const p = api.sound_play(kind, !!force);
    if (p && p.catch) p.catch(() => {});
  }catch(e){ /* 放不出来不吵人：界面上本来还有别的提示 */ }
}
