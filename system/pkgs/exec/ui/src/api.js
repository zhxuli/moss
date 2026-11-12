export const API_VERSION = 2;

const BACKEND = {
  cmd: { list: "cmd_list", save: "cmd_save", remove: "cmd_remove" },
  run: { start: "run_start", poll: "run_poll", stop: "run_stop", console: "run_console" },
  sys: { reveal: "sys_reveal", copy: "sys_copy", pickPath: "sys_pick_path" },
};

let readyPromise = null;

export function bridgeReady() {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      if (window.moss || (window.pywebview && window.pywebview.api)) return resolve();

      window.addEventListener("pywebviewready", resolve, { once: true });
      setTimeout(resolve, 3000);            
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
    return window.moss.call(name, body);            
  }
  const fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
  if (typeof fn !== "function") {
    throw new Error("后端没有这个方法：" + name + "（前后端版本可能对不上）");
  }
  return fn(body);
}

export const api = {
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
        } catch (e) {  }
      }
      return call(BACKEND.sys.pickPath, { kind: want });
    },
  },
};
