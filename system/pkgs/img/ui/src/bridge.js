/* 后端桥的**唯一入口**（`V-225`）。
 *
 * ★ 一份页面两种跑法，都从这里出去（走 `ui/moss-embed.js` 垫片）：
 *   · 内嵌在 moss 的「界面」选项卡里 → `moss.call()` → postMessage → 宿主 → 后端进程的 stdin；
 *   · 独立窗口（包自己开的 pywebview）→ `moss.call()` → `window.pywebview.api.<方法>(params)`。
 *
 * ★ 两条路的**参数形状是一样的：一个对象**（后端 `gui_web.Api` 每个方法都只收一个 dict）。
 *   所以这里按"字段名"发参数 —— 谁改后端签名，同步改下面这张表。
 *   （以前页面是直接 `state.api.scan(dir)` 那种位置参数，只有独立窗口那条路能用；
 *     内嵌时后端收到的是一个 dict，就散架了。）
 */

/* JS 这边一直用的老签名（位置参数）→ 后端要的字段名，顺序一一对应 */
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

/* 桥不一定在最前面就绪：垫片是经典脚本、比这个 module 先执行；独立窗口那条要等
   `pywebviewready`。只等一次，之后复用。等不到也别把界面卡死（3 秒后照样往下走）。 */
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
    return window.moss.call(method, body);          // 垫片：两种环境它自己分流
  }
  const fn = window.pywebview && window.pywebview.api && window.pywebview.api[method];
  if (typeof fn !== 'function') {
    throw new Error('后端没有这个方法：' + method + '（前后端版本可能对不上）');
  }
  return fn(body);
}

/* 给页面用的 api：**方法名和签名跟以前一模一样**，所以 app.js 那边的调用点不用改 */
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

/* 宿主送来的一条事件（内嵌才有；独立窗口没有宿主，一律返回 false）。
   现在用到的三个（`V-204` / `V-205` / `V-226`）：
     · `drop`     真路径（拖放落地）—— 只有宿主拿得到 `File.path`
     · `captured` 宿主铺了罩子接住这一拖 —— 这期间**别信 `dragleave`**（那是罩子盖上来引起的假离开）
     · `dragend`  这一拖结束了 —— 把你自己的拖放提示收掉
   ★ 少了 `captured` / `dragend` 这两个，页面画的提示在"松手"之后就**永远挂在那儿**。 */
export function onHostEvent(name, fn) {
  if (!isEmbedded() || !window.moss || typeof window.moss.on !== 'function') return false;
  window.moss.on(name, fn);
  return true;
}

/* 宿主把"真实路径"送进来的那条路（内嵌时的拖放，`V-225`）。
   独立窗口没有宿主，靠 pywebview 把路径塞进后端、页面再 `take_drop` 轮询。 */
export function onHostDrop(fn) {
  return onHostEvent('drop', (d) => {
    const paths = ((d && d.items) || []).map((x) => String(x || '')).filter(Boolean);
    if (paths.length) fn(paths);
  });
}
