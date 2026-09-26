/* 后端桥的**唯一入口**。
 *
 * pywebview 暴露的方法是平铺的（list / save / run …），功能一多就会变成一坨。
 * 这里按分区包一层：cmd_* / run_* / sys_*，UI 层永远不直接碰 window.pywebview。
 * 以后加功能、改后端名字、加错误兜底、做版本握手，都只改这一个文件。
 */

export const API_VERSION = 2;

/* JS 里的分区名 -> 后端实际方法名（后端也是这套分区命名） */
const BACKEND = {
  cmd: { list: "cmd_list", save: "cmd_save", remove: "cmd_remove" },
  run: { start: "run_start", poll: "run_poll", stop: "run_stop", console: "run_console" },
  sys: { reveal: "sys_reveal", copy: "sys_copy", pickPath: "sys_pick_path" },
};

let readyPromise = null;

/* pywebview 的桥不一定在 mounted 时就绪，等它一下（只等一次，之后直接复用） */
export function bridgeReady() {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      if (window.pywebview && window.pywebview.api) return resolve();
      window.addEventListener("pywebviewready", resolve, { once: true });
    });
  }
  return readyPromise;
}

async function call(name, ...args) {
  await bridgeReady();
  const fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
  if (typeof fn !== "function") {
    throw new Error("后端没有这个方法：" + name + "（前后端版本可能对不上）");
  }
  return fn(...args);
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
    save: (item, originalAlias) => call(BACKEND.cmd.save, item, originalAlias),
    remove: (alias) => call(BACKEND.cmd.remove, alias),
  },

  run: {
    start: (alias, args) => call(BACKEND.run.start, alias, args),
    poll: (id) => call(BACKEND.run.poll, id),
    stop: (id) => call(BACKEND.run.stop, id),
    console: (alias, args) => call(BACKEND.run.console, alias, args),
  },

  sys: {
    reveal: () => call(BACKEND.sys.reveal),
    copy: (text) => call(BACKEND.sys.copy, text),
    pickPath: (kind) => call(BACKEND.sys.pickPath, kind),
  },
};
