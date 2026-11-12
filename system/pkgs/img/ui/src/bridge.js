const ROUTES = {
  bootstrap: [],
  scan: ['dir'],
  scan_files: ['paths'],
  thumbs: ['paths'],
  file_info: ['path'],
  check_path: ['path'],
  open_file: ['path'],
  reveal: ['target'],
  pick_dir: ['start'],
  pick_files: ['start'],
  start: ['payload'],
  poll: ['id'],
  cancel: ['id'],
  take_drop: [],
  push_drop: ['paths'],
  help: [],
  copy: ['text'],
  report_error: ['text'],
  set_title: ['title'],
  save_config: ['config'],
};

export function isEmbedded() {
  return !!(window.moss && window.moss.env && window.moss.env.embedded);
}

let readyPromise = null;

export function bridgeReady() {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      if (window.moss || (window.pywebview && window.pywebview.api)) return resolve();
      window.addEventListener('pywebviewready', resolve, { once: true });
      setTimeout(resolve, 3000);
    });
  }
  return readyPromise;
}

export async function call(method, params) {
  await bridgeReady();
  const body = params || {};
  if (window.moss && typeof window.moss.call === 'function') {
    return window.moss.call(method, body);          
  }
  const fn = window.pywebview && window.pywebview.api && window.pywebview.api[method];
  if (typeof fn !== 'function') {
    throw new Error('后端没有这个方法：' + method + '（前后端版本可能对不上）');
  }
  return fn(body);
}

export async function makeApi() {
  await bridgeReady();
  const out = {};
  for (const [method, keys] of Object.entries(ROUTES)) {
    out[method] = (...args) => {
      const params = {};
      keys.forEach((k, i) => { params[k] = args[i]; });
      return call(method, params);
    };
  }
  return out;
}

export function onHostEvent(name, fn) {
  if (!isEmbedded() || !window.moss || typeof window.moss.on !== 'function') return false;
  window.moss.on(name, fn);
  return true;
}

export function onHostDrop(fn) {
  return onHostEvent('drop', (d) => {
    const paths = ((d && d.items) || []).map((x) => String(x || '')).filter(Boolean);
    if (paths.length) fn(paths);
  });
}
