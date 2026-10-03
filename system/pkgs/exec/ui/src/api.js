/* 后端桥的**唯一入口**。
 *
 * 后端把方法平铺在 `Api` 上（cmd_* / run_* / sys_*），这里按分区包一层 ——
 * UI 层永远不直接碰 `window.pywebview` / `window.moss`，
 * 以后加功能、改后端名字、加错误兜底、做版本握手，都只改这一个文件。
 *
 * ★ `V-222`：**一份页面两种跑法**都从这里出去（走 `moss-embed.js` 垫片）：
 *   · 内嵌在 moss 的「界面」选项卡里 → `moss.call()` → postMessage → 宿主 → 后端进程的 stdin；
 *   · 独立窗口（包自己开的 pywebview）→ `moss.call()` → `window.pywebview.api.<方法>(params)`。
 *   两条路的**参数形状是一样的：一个对象**（`{alias: …}`、`{item: …, original_alias: …}`），
 *   所以这里只管把 JS 侧好用的签名翻译成那个对象 —— 别写成分区位置参数，内嵌那条路会散架。
 */

export const API_VERSION = 2;

/* JS 里的分区名 -> 后端实际方法名（后端也是这套分区命名） */
const BACKEND = {
  cmd: { list: "cmd_list", save: "cmd_save", remove: "cmd_remove" },
  run: { start: "run_start", poll: "run_poll", stop: "run_stop", console: "run_console" },
  sys: { reveal: "sys_reveal", copy: "sys_copy", pickPath: "sys_pick_path" },
};

let readyPromise = null;

/* 垫片不一定在最前面跑到（老宿主 / 探针里直接调 api.js 时也没有），等它一下（只等一次） */
export function bridgeReady() {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      if (window.moss || (window.pywebview && window.pywebview.api)) return resolve();
      // 垫片是经典脚本、比这个 module 先执行；真没有就等 pywebview（独立窗口那条路）
      window.addEventListener("pywebviewready", resolve, { once: true });
      setTimeout(resolve, 3000);            // 谁都没来也别把界面卡死
    });
  }
  return readyPromise;
}

export function isEmbedded() {
  return !!(window.moss && window.moss.env && window.moss.env.embedded);
}

async function call(name, params) {
  await bridgeReady();
  const body = params || {};
  if (window.moss && typeof window.moss.call === "function") {
    return window.moss.call(name, body);            // 垫片：两种环境它自己分流
  }
  const fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
  if (typeof fn !== "function") {
    throw new Error("后端没有这个方法：" + name + "（前后端版本可能对不上）");
  }
  return fn(body);
}

export const api = {
  /* 握手：拿命令列表 + 外观 + 类型目录。顺便校验协议版本 */
  async bootstrap() {
    const r = await call("bootstrap");
    if (r && r.apiVersion && r.apiVersion !== API_VERSION) {
      console.warn("[api] 协议版本不一致：前端 %s / 后端 %s", API_VERSION, r.apiVersion);
    }
    return r;
  },

  cmd: {
    list: () => call(BACKEND.cmd.list),
    save: (item, originalAlias) =>
      call(BACKEND.cmd.save, { item: item, original_alias: originalAlias }),
    remove: (alias) => call(BACKEND.cmd.remove, { alias: alias }),
  },

  run: {
    start: (alias, args) => call(BACKEND.run.start, { alias: alias, args: args || "" }),
    poll: (id) => call(BACKEND.run.poll, { id: id }),
    stop: (id) => call(BACKEND.run.stop, { id: id }),
    console: (alias, args) =>
      call(BACKEND.run.console, { alias: alias, args: args || "" }),
  },

  sys: {
    reveal: () => call(BACKEND.sys.reveal),
    copy: (text) => call(BACKEND.sys.copy, { text: text }),
    /* 选文件 / 选目录：**内嵌时先问 moss 主界面**（那扇窗才有正规的系统对话框），
       问不到才退回后端自己那条（独立窗口是 pywebview 对话框，内嵌是 tkinter 兜底）。
       ★ "用户点了取消"（cancelled）**不是**"问不到" —— 别再往下兜底弹第二个框（`V-212`）。 */
    async pickPath(kind) {
      const want = kind === "dir" ? "dir" : "file";
      if (isEmbedded()) {
        try {
          const top = window.parent && window.parent !== window ? window.parent : null;
          const hp = top && top.pywebview && top.pywebview.api;
          if (hp) {
            const r = want === "dir" ? await (hp.pick_dir ? hp.pick_dir("") : null)
                                     : await (hp.pick_file ? hp.pick_file("") : null);
            if (r && r.ok && r.path) return { ok: true, path: r.path };
            if (r && (r.cancelled || /取消|没有选/.test(r.msg || ""))) {
              return { ok: true, path: "", cancelled: true };
            }
          }
        } catch (e) { /* 跨源 / 没桥：往下走后端那条 */ }
      }
      return call(BACKEND.sys.pickPath, { kind: want });
    },
  },
};
