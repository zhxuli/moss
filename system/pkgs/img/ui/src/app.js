/* app.js —— 图片工具前端
   ---------------------------------------------------------------------------
   不引框架：骨架写在 index.html 里，JS 只做四件事 ——
   渲染选择器、接事件、轮询日志、接拖放。

   选择器交互跟资源管理器对齐：
     单击 = 选中它 / Ctrl+单击 = 加选或取消 / Shift+单击 = 连选一段
     空白处拖框 = 框选（按住 Ctrl 则并进原有选择）
     双击 = 用系统默认程序打开 / Ctrl+A 全选 / Esc 清除 / Delete 从清单去掉
   **选中的那几个就是要处理的；一个都没选 = 全部处理。**

   缩略图：≤ thumbLimit(100) 张画网格，超了画紧凑列表。
   （几千张图生成缩略图要几十秒、几十 MB 内存，而"挑几张来转"本来也不需要看几千张） */

const SAVE_LABELS = {
  separate: '保存到单独文件夹',
  source: '保存到源文件夹 (覆盖)',
  source_delete: '转换并删除源文件',
};

const QUALITY_HINT = {
  jpg: '数值越高越清晰、文件越大',
  webp: '数值越高越清晰、文件越大',
  png: 'png 下映射成压缩级别：数值越压得越少',
};

const MODE_LABELS = { folder: '文件夹', files: '文件清单' };
const MODE_TITLES = { folder: '处理一个文件夹里的图片', files: '只处理手挑出来的这几个文件' };

const DEFAULTS = { save_mode: 'separate', output_format: 'jpg', quality: 80, width: '', ico_sizes: [] };

const THUMB_CHUNK = 20;
const DRAG_THRESHOLD = 4;

const $ = (id) => document.getElementById(id);

const state = {
  api: null, cfg: null, meta: null,
  history: [],
  mode: 'folder',
  scan: null,                  // 文件夹扫描结果 {ok, exts, count, files, message}
  dir: '',
  items: [],                   // 当前网格里的全部条目
  selected: new Set(),         // 选中的 path（小写）
  anchor: null,
  showThumbs: false,
  thumbDone: 0,
  running: false,
  jobId: null,
  outputDir: '',
  dropTimer: null,
  logOpen: false,
};

/* ------------------------------------------------------------------ 桥 */
function apiReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
    window.addEventListener('pywebviewready', () => resolve(window.pywebview.api), { once: true });
  });
}

/* ------------------------------------------------------------------ 小工具 */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function humanSize(n) {
  if (n == null) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

function toast(message, bad) {
  if (!message) return;
  const node = el('div', 'toast' + (bad ? ' bad' : ''), message);
  $('toasts').appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity .2s';
    node.style.opacity = '0';
    setTimeout(() => node.remove(), 220);
  }, 2600);
}

function applyAppearance(r) {
  if (r.theme) document.documentElement.dataset.theme = r.theme;
  const a = r.accent || {};
  for (const k of ['accent', 'accent-fg', 'accent-press', 'ring', 'field-focus']) {
    if (a[k]) document.documentElement.style.setProperty('--' + k, a[k]);
  }
}

const key = (p) => String(p).toLowerCase();

/* ------------------------------------------------------------------ 静态块 */
function renderMode() {
  const box = $('segMode');
  box.textContent = '';
  for (const m of ['folder', 'files']) {
    const b = el('button', null, MODE_LABELS[m]);
    b.type = 'button';
    b.title = MODE_TITLES[m];
    b.setAttribute('aria-selected', String(state.mode === m));
    b.onclick = () => {
      if (state.mode === m) return;
      state.mode = m;
      if (m === 'files' && !state.items.length) { renderMode(); pickFiles(); return; }
      renderMode();
      rebuild();
    };
    box.appendChild(b);
  }
  /* 模式决定这一行显示哪些控件：文件夹模式给路径+选择，文件清单模式给加/清 */
  const folder = state.mode === 'folder';
  $('src').hidden = !folder;
  $('btnPick').hidden = !folder;
  $('history').hidden = !folder;
  $('btnAddFiles').hidden = folder;
  $('btnClearFiles').hidden = folder || !state.items.length;
}

function renderFormat() {
  const box = $('segFormat');
  box.textContent = '';
  for (const fmt of state.meta.formats) {
    const b = el('button', null, fmt.toUpperCase());
    b.type = 'button';
    b.setAttribute('aria-selected', String(state.cfg.output_format === fmt));
    b.onclick = () => { state.cfg.output_format = fmt; renderFormat(); renderConditional(); };
    box.appendChild(b);
  }
}

function renderSaveMode() {
  const box = $('segSave');
  box.textContent = '';
  for (const mode of state.meta.saveModes) {
    const b = el('button', mode === 'source_delete' ? 'warn' : null, SAVE_LABELS[mode] || mode);
    b.type = 'button';
    b.title = SAVE_LABELS[mode] || mode;
    b.setAttribute('aria-selected', String(state.cfg.save_mode === mode));
    b.onclick = () => { state.cfg.save_mode = mode; renderSaveMode(); renderConditional(); };
    box.appendChild(b);
  }
}

function renderIcoSizes() {
  const box = $('icoSizes');
  box.textContent = '';
  for (const size of state.meta.icoSizes) {
    const label = el('label', 'check');
    const cb = el('input');
    cb.type = 'checkbox';
    cb.checked = state.cfg.ico_sizes.includes(size);
    cb.onchange = () => {
      const picked = new Set(state.cfg.ico_sizes);
      if (cb.checked) picked.add(size); else picked.delete(size);
      state.cfg.ico_sizes = [...picked].sort((a, b) => a - b);
    };
    label.appendChild(cb);
    label.appendChild(document.createTextNode(String(size)));
    box.appendChild(label);
  }
}

function renderHistory() {
  const sel = $('history');
  sel.textContent = '';
  const head = el('option', null, state.history.length ? '最近使用…' : '（无历史）');
  head.value = '';
  sel.appendChild(head);
  for (const p of state.history) {
    const o = el('option', null, p);
    o.value = p;
    sel.appendChild(o);
  }
  sel.value = '';
}

/* 类型芯片 = **快捷选择**：点一下把这一类全选上（不再是"过滤"）。
   这样"选中"只剩一套模型，不会和"全选/清除"打架。 */
function renderTypes() {
  const box = $('types');
  box.textContent = '';
  const exts = (state.scan && state.scan.exts) || [];
  if (state.mode !== 'folder' || !exts.length) { box.hidden = true; return; }
  box.hidden = false;
  for (const item of exts) {
    const chip = el('button', 'chip');
    chip.type = 'button';
    const picked = state.items.filter((f) => f.ext === item.ext);
    const allIn = picked.length && picked.every((f) => state.selected.has(key(f.path)));
    if (allIn) chip.classList.add('on');
    chip.title = allIn ? `取消选中全部 ${item.ext.toUpperCase()}` : `选中全部 ${item.ext.toUpperCase()}`;
    chip.appendChild(el('span', null, item.ext.replace('.', '').toUpperCase()));
    chip.appendChild(el('span', 'n', String(item.count)));
    chip.onclick = () => selectType(item.ext);
    box.appendChild(chip);
  }
}

/* ------------------------------------------------------------------ 选择器 */
function visiblePaths() { return state.items.map((f) => key(f.path)); }

function rebuild() {
  if (state.mode === 'folder') {
    state.items = (state.scan && state.scan.files) || [];
    pruneSelection();
  }
  state.showThumbs = state.items.length > 0 && state.items.length <= state.meta.thumbLimit;
  renderTypes();
  renderGrid();
  renderSelection();
}

/* 空状态。**分两种**，语气完全不同：
     · 还没选目录      → 引导（"把图片拖进来"）
     · 目录里没有图片  → 这只是"这里没东西"，不是错误，别报红、别说"失败"
   支持的格式直接列出来，省得用户猜为什么他的图不算数。 */
const SUPPORTED_TEXT = '支持 jpg / jpeg / png / webp / bmp / gif / tiff';

function renderEmpty() {
  const title = $('peTitle');
  const sub = $('peSub');
  if (state.mode === 'files') {
    title.textContent = '文件清单是空的';
    sub.textContent = '点左上角「加文件…」挑几张，或者直接把图片拖进来';
    return;
  }
  const scan = state.scan;
  if (!scan || !scan.ok) {
    title.textContent = '把图片或文件夹拖进来';
    sub.textContent = '也可以点上面的「选择…」挑一个文件夹';
  } else {
    title.textContent = '这个文件夹里没有图片';
    sub.textContent = `${SUPPORTED_TEXT}。换一个文件夹，或者直接把图片拖进来`;
  }
}

function renderGrid() {
  const grid = $('grid');
  const empty = $('pickerEmpty');
  grid.textContent = '';
  grid.classList.toggle('rows', !state.showThumbs);
  state.thumbDone = 0;
  thumbQueue = [];

  if (!state.items.length) {
    grid.hidden = true;
    empty.hidden = false;
    renderEmpty();
    return;
  }
  empty.hidden = true;
  grid.hidden = false;

  for (const f of state.items) {
    const tile = el('div', 'tile' + (f.exists === false ? ' gone' : ''));
    tile.dataset.path = key(f.path);
    /* 不用原生 title：那个要停 1 秒才出、样式也不能改。
       详情走自己的悬停卡片（见 bindHover）。 */

    if (state.showThumbs) {
      const box = el('div', 'thumb');
      const k = tile.dataset.path;
      if (!f.data && thumbCache.has(k)) f.data = thumbCache.get(k);   // 命中缓存，不闪
      if (f.data) {
        const img = el('img');
        img.src = f.data; img.alt = ''; img.draggable = false;
        box.appendChild(img);
        tile.classList.add('has-thumb');
        state.thumbDone += 1;
      } else {
        box.appendChild(el('span', 'ph', '图片'));
        queueThumb(f);
      }
      tile.appendChild(box);
      tile.appendChild(el('div', 'name', f.name));
    } else {
      tile.appendChild(el('span', 'fico', (f.ext || '').replace('.', '').toUpperCase() || '?'));
      tile.appendChild(el('span', 'name', f.name));
      tile.appendChild(el('span', 'fdir', f.dir || ''));
      tile.appendChild(el('span', 'fsize', f.exists === false ? '已不在' : humanSize(f.size)));
    }
    tile.appendChild(el('span', 'check-badge', '✓'));
    grid.appendChild(tile);
  }
  if (state.showThumbs) loadThumbs();
  applySelectionClasses();
}

let thumbQueue = [];
let thumbBusy = false;

/* 缩略图缓存，按路径存。
   ★ 为什么必须有：后端每次 scan 返回的都是**全新的对象**，
     旧对象上挂着的缩略图 data 会跟着一起丢掉。没有这层缓存的话，
     每次刷新 / 窗口重新获得焦点，整个网格都会**先清空再一张张补回来**
     （看着就像"图没了"）。 */
const thumbCache = new Map();
const THUMB_CACHE_MAX = 1200;

function queueThumb(item) { thumbQueue.push(item); }

function cacheThumb(pathKey, data) {
  if (!data) return;
  if (thumbCache.size > THUMB_CACHE_MAX) thumbCache.clear();
  thumbCache.set(pathKey, data);
}

function loadThumbs() {
  thumbQueue = thumbQueue.filter((q) => !q.data && !thumbCache.has(key(q.path)));
  if (thumbBusy || !thumbQueue.length) return;
  const batch = thumbQueue.splice(0, THUMB_CHUNK);
  thumbBusy = true;
  state.api.thumbs(batch.map((b) => b.path)).then((got) => {
    thumbBusy = false;
    if (got && got.ok) {
      for (const t of got.thumbs) {
        const hit = batch.find((b) => key(b.path) === key(t.path));
        if (!hit) continue;
        hit.data = t.data;
        cacheThumb(key(t.path), t.data);
        const tile = $('grid').querySelector(`.tile[data-path="${cssEscape(key(t.path))}"]`);
        if (!tile) continue;
        const box = tile.querySelector('.thumb');
        if (t.data && box) {
          box.textContent = '';
          const img = el('img');
          img.src = t.data; img.draggable = false;
          box.appendChild(img);
          tile.classList.add('has-thumb');
        }
      }
    }
    state.thumbDone += batch.length;
    renderNote();
    if (thumbQueue.length) setTimeout(loadThumbs, 0);
  }).catch(() => { thumbBusy = false; });
}

function cssEscape(s) { return String(s).replace(/["\\]/g, '\\$&'); }

function applySelectionClasses() {
  for (const tile of $('grid').children) {
    tile.classList.toggle('sel', state.selected.has(tile.dataset.path));
  }
}

function renderSelection() {
  const total = state.items.length;
  $('selCount').textContent = total ? `已选 ${state.selected.size} / ${total}` : '';
  applySelectionClasses();
  renderNote();
  renderSource();
  renderTypes();
}

/* 网格下面那行提示：**只在真有话说的时候出现**。
   「不选 = 全部 N 个 / 将处理 N 个」不写了 —— 右上角有「已选 x / y」，
   右下按钮上写着「开始处理 (N)」，说三遍是啰嗦。 */
function renderNote() {
  const note = $('srcNote');
  if (note.classList.contains('err')) return;      // 出错信息优先，别被进度顶掉
  const total = state.items.length;
  const parts = [];
  if (state.showThumbs && state.thumbDone < total) parts.push(`缩略图 ${state.thumbDone}/${total}`);
  if (total > state.meta.thumbLimit) parts.push('文件较多，用列表显示');
  note.textContent = parts.join(' · ');
}

function renderSource() {
  const total = state.items.length;
  const n = state.selected.size;
  const effective = n || total;
  $('btnStart').textContent = state.running ? '正在处理…' : (effective ? `开始处理 (${effective})` : '开始处理');
  $('btnClearFiles').hidden = state.mode !== 'files' || !total;

  const note = $('srcNote');
  const gone = state.items.filter((f) => f.exists === false).length;
  if (gone) {
    note.className = 'field-note err';
    note.textContent = `有 ${gone} 个文件已经不在了（灰掉的那些）—— 处理前会被拦下，点「刷新」清掉。`;
  } else {
    note.className = 'field-note';
    note.textContent = '';
    renderNote();
  }
  syncTitle();
}

/* 标题栏写"图片工具 — 目录"：原来顶栏那一行整条去掉之后，
   目录信息就靠系统标题栏承载（用户提的） */
let lastTitle = '';
function syncTitle() {
  const total = state.items.length;
  const n = state.selected.size;
  let where;
  if (state.mode === 'files') where = total ? `文件清单（${total} 个）` : '文件清单（空）';
  else where = state.dir || '未选择目录';
  const count = n ? ` · 选 ${n}` : '';
  const title = `图片工具 — ${where}${count}`;
  if (title === lastTitle) return;
  lastTitle = title;
  document.title = title;
  if (state.api && state.api.set_title) state.api.set_title(title);
}

/* 格式 / 保存模式一变，整块跟着更新 */
function renderConditional() {
  const fmt = state.cfg.output_format;
  const isIco = fmt === 'ico';
  /* 质量在 ico 下完全没用 —— 直接把那一格**换成 ico 尺寸**，不白占地方 */
  $('qualitySlot').hidden = isIco;
  $('icoSlot').hidden = !isIco;
  renderIcoSizes();

  /* 宽度非法就直接把输入框标红，不再单独占一行提示 */
  const width = String(state.cfg.width || '').trim();
  const bad = !!width && (!/^\d+$/.test(width) || Number(width) === 0);
  $('width').classList.toggle('invalid', bad);
  $('width').title = bad
    ? '只认正整数像素值（0 和字母会被忽略，等于保持原尺寸）'
    : '只缩不放：原图比它窄就保持原样；留空 = 保持原始尺寸';

  /* 保存模式那一行右边直接写清"会输出到哪" */
  const saveNote = $('saveNote');
  const byFiles = state.mode === 'files';
  if (state.cfg.save_mode === 'separate') {
    saveNote.className = 'hint';
    saveNote.textContent = byFiles ? '→ 第一个文件所在目录\\compressed_output\\'
                                   : '→ 源目录\\compressed_output\\';
  } else if (state.cfg.save_mode === 'source') {
    saveNote.className = 'hint';
    saveNote.textContent = byFiles ? '→ 每个文件各自所在的目录（同名覆盖）'
                                   : '→ 源目录（同名覆盖）';
  } else {
    saveNote.className = 'hint';
    saveNote.textContent = byFiles ? '→ 每个文件各自所在的目录，转换后删源文件'
                                   : '→ 源目录，转换后删源文件';
  }

  renderWarn();
}

/* 危险模式常驻警告：藏起来的是**设置**，不是**警告** */
function renderWarn() {
  const bar = $('warnBar');
  const mode = state.cfg.save_mode;
  if (mode === 'source_delete') {
    bar.hidden = false;
    bar.className = 'warnbar';
    bar.textContent = '⚠ 转换成功后源文件会被删除，无法撤销。';
  } else if (mode === 'source') {
    bar.hidden = false;
    bar.className = 'warnbar soft';
    bar.textContent = '⚠ 直接写回源文件夹，同名文件会被覆盖。';
  } else {
    bar.hidden = true;
  }
}

/* ------------------------------------------------------------------ 选择 */
function setSelection(paths, additive) {
  if (!additive) state.selected = new Set();
  for (const p of paths) state.selected.add(p);
  renderSelection();
}

function toggleSelection(p) {
  if (state.selected.has(p)) state.selected.delete(p);
  else state.selected.add(p);
  renderSelection();
}

function selectAll() { setSelection(visiblePaths(), false); }
function clearSelection() { setSelection([], false); }

function selectType(ext) {
  const hit = state.items.filter((f) => f.ext === ext).map((f) => key(f.path));
  const allIn = hit.length && hit.every((p) => state.selected.has(p));
  if (allIn) { for (const p of hit) state.selected.delete(p); renderSelection(); }
  else setSelection(hit, true);
}

function clickItem(pathKey, e) {
  if (e.shiftKey && state.anchor) {
    const all = visiblePaths();
    const a = all.indexOf(state.anchor);
    const b = all.indexOf(pathKey);
    if (a >= 0 && b >= 0) {
      const [lo, hi] = a <= b ? [a, b] : [b, a];
      setSelection(all.slice(lo, hi + 1), e.ctrlKey || e.metaKey);
      return;
    }
  }
  if (e.ctrlKey || e.metaKey) { toggleSelection(pathKey); state.anchor = pathKey; return; }
  setSelection([pathKey], false);
  state.anchor = pathKey;
}

/* ------------------------------------------------------------------ 框选 */
function bindMarquee() {
  const picker = $('picker');
  const box = $('marquee');
  let sx = 0, sy = 0, active = false, base = new Set(), moved = false;

  const local = (e) => {
    const r = picker.getBoundingClientRect();
    return { x: e.clientX - r.left + picker.scrollLeft, y: e.clientY - r.top + picker.scrollTop };
  };

  picker.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.tile') && e.detail > 1) return;   // 双击的第二下不参与
    const p = local(e);
    sx = p.x; sy = p.y;
    active = true; moved = false;
    base = new Set(state.selected);
    /* 不主动 focus：键盘快捷键都挂在 document 上，不需要焦点。
       主动 focus 会让整个网格套上一圈焦点环（看着像选中了全部）。
       原生点击带来的焦点不会触发 :focus-visible，键盘 Tab 进来仍然有环。 */
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!active) return;
    const p = local(e);
    const dx = p.x - sx, dy = p.y - sy;
    if (!moved && Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
    moved = true;
    box.hidden = false;
    const l = Math.min(sx, p.x), t = Math.min(sy, p.y);
    const w = Math.abs(dx), h = Math.abs(dy);
    box.style.left = l + 'px'; box.style.top = t + 'px';
    box.style.width = w + 'px'; box.style.height = h + 'px';

    const pickerRect = picker.getBoundingClientRect();
    const hit = [];
    for (const tile of $('grid').children) {
      const r = tile.getBoundingClientRect();
      const tl = { x: r.left - pickerRect.left + picker.scrollLeft, y: r.top - pickerRect.top + picker.scrollTop };
      const br = { x: tl.x + r.width, y: tl.y + r.height };
      if (br.x >= l && tl.x <= l + w && br.y >= t && tl.y <= t + h) hit.push(tile.dataset.path);
    }
    state.selected = e.ctrlKey || e.metaKey ? new Set([...base, ...hit]) : new Set(hit);
    applySelectionClasses();
    $('selCount').textContent = state.items.length ? `已选 ${state.selected.size} / ${state.items.length}` : '';
    renderNote();
  });

  window.addEventListener('mouseup', (e) => {
    if (!active) return;
    active = false;
    box.hidden = true;
    if (moved) { renderSelection(); return; }
    const tile = e.target.closest && e.target.closest('.tile');
    if (tile && picker.contains(tile)) clickItem(tile.dataset.path, e);
    else if (!e.ctrlKey && !e.metaKey) clearSelection();
  });

  picker.addEventListener('dblclick', (e) => {
    const tile = e.target.closest && e.target.closest('.tile');
    if (!tile) return;
    const item = state.items.find((f) => key(f.path) === tile.dataset.path);
    if (item) openFile(item.path);
  });
}

async function openFile(path) {
  const got = await state.api.open_file(path);
  if (!got || !got.ok) toast((got && got.message) || '打不开这个文件。', true);
}

/* ------------------------------------------------------------------ 悬停详情 */
let hoverTimer = null;
let hoverPath = null;

function bindHover() {
  const grid = $('grid');
  const card = $('hoverCard');

  const hide = () => {
    clearTimeout(hoverTimer);
    hoverPath = null;
    card.hidden = true;
  };

  grid.addEventListener('mousemove', (e) => {
    const tile = e.target.closest && e.target.closest('.tile');
    if (!tile) { hide(); return; }
    const p = tile.dataset.path;
    if (p === hoverPath) { placeCard(card, tile); return; }

    hoverPath = p;
    card.hidden = true;
    clearTimeout(hoverTimer);
    /* 停一下才查：鼠标扫过一排时不要每张都去问后端 */
    hoverTimer = setTimeout(() => showCard(tile, p), 180);
  });

  grid.addEventListener('mouseleave', hide);
  $('picker').addEventListener('scroll', hide, { passive: true });
}

function placeCard(card, tile) {
  /* 默认贴在瓦片右边，出界就翻到左边 / 收进窗口内 */
  const r = tile.getBoundingClientRect();
  const w = card.offsetWidth || 380;
  const h = card.offsetHeight || 100;
  let x = r.right + 10;
  if (x + w > window.innerWidth - 8) x = r.left - w - 10;
  if (x < 8) x = Math.min(window.innerWidth - w - 8, Math.max(8, r.left));
  let y = r.top;
  if (y + h > window.innerHeight - 8) y = window.innerHeight - h - 8;
  if (y < 8) y = 8;
  card.style.left = Math.round(x) + 'px';
  card.style.top = Math.round(y) + 'px';
}

async function showCard(tile, pathKey) {
  if (hoverPath !== pathKey) return;                 // 期间鼠标已经移开了
  const item = state.items.find((f) => key(f.path) === pathKey);
  if (!item) return;

  /* 先把已知的画出来（缩略图 + 名字），别等后端 */
  const thumb = $('hcThumb');
  thumb.textContent = '';
  if (item.data) {
    const img = el('img');
    img.src = item.data; img.draggable = false;
    thumb.appendChild(img);
  }
  $('hcName').textContent = item.name;
  $('hcPath').textContent = item.dir || '';
  $('hcMeta').textContent = item.exists === false ? '文件已经不在了' : humanSize(item.size);
  $('hcTime').textContent = '';
  $('hoverCard').hidden = false;
  placeCard($('hoverCard'), tile);

  const got = await state.api.file_info(item.path);
  if (hoverPath !== pathKey || !got || !got.ok) return;
  const i = got.info || {};
  $('hcName').textContent = i.name || item.name;
  $('hcPath').textContent = i.dir || item.dir || '';
  if (i.exists === false) {
    $('hcMeta').textContent = '文件已经不在了（点「刷新」清掉）';
  } else {
    const bits = [];
    if (i.width && i.height) bits.push(`${i.width} × ${i.height}`);
    if (i.format) bits.push(i.format + (i.mode && i.mode !== 'RGB' ? ` ${i.mode}` : ''));
    bits.push(humanSize(i.size));
    $('hcMeta').textContent = bits.join(' · ');
    $('hcTime').textContent = i.mtime_text ? '修改于 ' + i.mtime_text : '';
  }
  placeCard($('hoverCard'), tile);
}

/* ------------------------------------------------------------------ 数据 */
function scanSig(scan) {
  if (!scan) return '';
  return JSON.stringify([scan.ok, scan.count, (scan.exts || []).map((i) => [i.ext, i.count])]);
}

function applyScan(scan) {
  state.scan = scan || { ok: false, exts: [], count: 0, files: [], message: '请选择一个有效的文件夹。' };
  if (state.mode === 'folder') {
    state.items = state.scan.files || [];
    pruneSelection();
  }
  rebuild();
}

function pruneSelection() {
  const alive = new Set(visiblePaths());
  for (const p of [...state.selected]) if (!alive.has(p)) state.selected.delete(p);
}

function setFileItems(files) {
  const seen = new Set(state.items.map((f) => key(f.path)));
  let added = 0;
  for (const f of files) {
    if (seen.has(key(f.path))) continue;
    seen.add(key(f.path));
    state.items.push(f);
    added += 1;
  }
  return added;
}

async function loadDir(dir, useDialog) {
  let path = dir;
  if (useDialog) {
    const picked = await state.api.pick_dir(state.dir);
    if (!picked || !picked.ok) { toast((picked && picked.message) || '打开选择框失败。', true); return; }
    if (!picked.path) return;
    path = picked.path;
  }
  state.dir = path || '';
  $('src').value = state.dir;
  const scan = await state.api.scan(state.dir);
  applyScan(scan);
  if (scan && scan.history) { state.history = scan.history; renderHistory(); }
  /* 目录里没有图片**不是错误** —— 空状态里已经好好说了，不再弹红字 */
}

async function pickFiles() {
  const got = await state.api.pick_files(state.items.length ? state.items[0].dir : state.dir);
  if (!got || !got.ok) { toast((got && got.message) || '打开选择框失败。', true); return; }
  if (!got.files || !got.files.length) return;
  if (state.mode !== 'files') { state.mode = 'files'; state.items = []; }
  const added = setFileItems(got.files);
  renderMode();
  rebuild();
  renderConditional();
  toast(added ? `已加入 ${added} 个文件。` : '这些文件已经在清单里了。');
}

/* ------------------------------------------------------------------ 刷新 */
async function refresh(quiet) {
  if (state.mode === 'files') {
    if (!state.items.length) { if (!quiet) toast('清单是空的。'); return; }
    const got = await state.api.scan_files(state.items.map((f) => f.path));
    if (!got || !got.ok) { toast((got && got.message) || '刷新失败。', true); return; }
    const byPath = new Map(got.files.map((f) => [key(f.path), f]));
    let gone = 0;
    state.items = state.items.map((f) => {
      const fresh = byPath.get(key(f.path));
      if (!fresh) return f;
      if (fresh.exists === false) gone += 1;
      return Object.assign(f, { size: fresh.size, exists: fresh.exists });
    });
    rebuild();
    if (!quiet) toast(gone ? `刷新完成：${gone} 个文件已经不在了。` : '刷新完成。', !!gone);
    return;
  }

  const scan = await state.api.scan(state.dir);
  const same = scanSig(scan) === scanSig(state.scan);
  const before = (state.scan && state.scan.count) || 0;
  if (!same) {
    applyScan(scan);
    if (scan && scan.history) { state.history = scan.history; renderHistory(); }
  }
  if (!quiet) {
    if (!scan || !scan.ok) toast((scan && scan.message) || '刷新失败。', true);
    else if (same) toast('没有变化。');
    else {
      const d = scan.count - before;
      toast(`文件夹已更新：${d >= 0 ? '+' : ''}${d}，现在 ${scan.count} 个文件。`);
    }
  }
}

/* ------------------------------------------------------------------ 运行 */
function setLogOpen(open) {
  state.logOpen = !!open;
  $('logBox').hidden = !state.logOpen;
  document.querySelector('.card').classList.toggle('log-open', state.logOpen);
}

function setRunning(on) {
  state.running = on;
  $('spin').hidden = !on;
  $('btnStart').disabled = on;
  $('logHint').textContent = on ? '处理中' : '';
  renderSource();
  if (on) setLogOpen(true);
}

function renderLog(got) {
  const box = $('log');
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
  box.textContent = got.output || '';
  if (atBottom) box.scrollTop = box.scrollHeight;
  if (got.running) { $('status').textContent = '处理中…'; return; }
  const s = got.summary;
  if (!s) { $('status').textContent = got.returncode === 0 ? '完成' : `结束（退出码 ${got.returncode}）`; return; }
  state.outputDir = s.output_dir || state.outputDir;
  if (s.cancelled) $('status').textContent = `已取消（完成 ${s.done}/${s.total}）`;
  else if (s.failed) $('status').textContent = `完成（成功 ${s.done}，失败 ${s.failed}）`;
  else $('status').textContent = `全部完成（${s.done} 个，用时 ${s.elapsed.toFixed(1)} 秒）`;
}

function pollOnce() {
  if (!state.jobId) return;
  state.api.poll(state.jobId).then((got) => {
    if (!got || !got.ok) { setRunning(false); return; }
    renderLog(got);
    if (got.running) setTimeout(pollOnce, 150);
    else { setRunning(false); $('logHint').textContent = ''; }
  }).catch(() => setRunning(false));
}

function targets() {
  if (state.selected.size) return state.items.filter((f) => state.selected.has(key(f.path)));
  return state.items;
}

async function start() {
  if (state.running) return;
  const picked = targets();
  if (!picked.length) { toast('没有可处理的文件。', true); return; }
  /* 文件夹模式 + 没勾选 → 交回后端扫目录（几千张也不会被前端的名单上限截断），
     过滤条件用"当前目录里出现的类型"（界面上已经没有类型过滤了）。
     只要动了选择，就按"明确的一批文件"来跑。 */
  const explicit = state.mode === 'files' || state.selected.size > 0;
  const exts = ((state.scan && state.scan.exts) || []).map((i) => i.ext);
  const payload = {
    mode: explicit ? 'files' : 'folder',
    source_dir: state.dir,
    files: explicit ? picked.map((f) => ({ path: f.path })) : [],
    output_format: state.cfg.output_format,
    quality: Number($('quality').value),
    width: String($('width').value || '').trim(),
    save_mode: state.cfg.save_mode,
    ico_sizes: state.cfg.ico_sizes,
    source_filter: exts,
  };
  const res = await state.api.start(payload);
  if (!res || !res.ok) { toast((res && res.message) || '启动失败。', true); return; }
  if (res.history) { state.history = res.history; renderHistory(); }
  state.outputDir = res.outputDir || '';
  state.jobId = res.job;
  $('log').textContent = '';
  setRunning(true);
  $('status').textContent = '处理中…';
  pollOnce();
}

/* ------------------------------------------------------------------ 拖放 */
function onDropEvent() {
  hideVeil();
  let tries = 0;
  const tick = async () => {
    tries += 1;
    const got = await state.api.take_drop();
    if (got && got.pending) { applyDrop(got); return; }
    if (tries < 25) state.dropTimer = setTimeout(tick, 120);
    else toast('没拿到拖进来的内容（拖放可能没接上）。', true);
  };
  tick();
}

function applyDrop(got) {
  if (got.history) { state.history = got.history; renderHistory(); }
  if (got.mode === 'folder') {
    state.mode = 'folder';
    renderMode();
    state.dir = got.folder;
    $('src').value = got.folder;
    state.api.scan(got.folder).then((scan) => {
      state.items = [];
      applyScan(scan);
      if (scan && scan.history) { state.history = scan.history; renderHistory(); }
      renderConditional();
    });
    toast('已切到「文件夹」：' + got.folder);
    return;
  }
  if (state.mode !== 'files') { state.mode = 'files'; state.items = []; }
  const added = setFileItems(got.files || []);
  renderMode();
  rebuild();
  renderConditional();
  if (got.note) toast(got.note, true);
  else toast(added ? `已加入 ${added} 个文件。` : '这些文件已经在清单里了。');
}

function showVeil() { $('dropVeil').hidden = false; }
function hideVeil() { $('dropVeil').hidden = true; }

function bindDrop() {
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  window.addEventListener('dragover', (e) => { stop(e); showVeil(); });
  window.addEventListener('dragenter', (e) => { stop(e); showVeil(); });
  window.addEventListener('dragleave', (e) => { stop(e); if (e.relatedTarget === null) hideVeil(); });
  window.addEventListener('drop', (e) => { stop(e); onDropEvent(); });
}

/* ------------------------------------------------------------------ 事件 */
function bind() {
  $('btnLogToggle').onclick = () => setLogOpen(!state.logOpen);
  $('btnPick').onclick = () => loadDir(state.dir, true);
  $('btnAddFiles').onclick = () => pickFiles();
  $('btnClearFiles').onclick = () => { state.items = []; renderMode(); rebuild(); renderConditional(); };
  $('btnRefresh').onclick = () => refresh(false);
  $('btnSelAll').onclick = () => selectAll();
  $('btnSelNone').onclick = () => clearSelection();
  $('btnReveal').onclick = async () => {
    const res = await state.api.reveal(state.outputDir);
    if (!res || !res.ok) toast((res && res.message) || '还不知道输出目录。', true);
  };
  $('btnStart').onclick = start;

  $('quality').oninput = () => {
    state.cfg.quality = Number($('quality').value);
    $('qualityNum').textContent = state.cfg.quality + '%';
  };
  $('width').oninput = () => {
    state.cfg.width = $('width').value;
    renderConditional();
  };

  let scanTimer = null;
  $('src').oninput = () => {
    state.dir = $('src').value;
    syncTitle();
    clearTimeout(scanTimer);
    scanTimer = setTimeout(async () => {
      if (state.mode !== 'folder') return;
      const scan = await state.api.scan(state.dir);
      applyScan(scan);
      if (scan && scan.history) { state.history = scan.history; renderHistory(); }
    }, 350);
  };

  $('history').onchange = (e) => {
    const p = e.target.value;
    e.target.value = '';
    if (!p) return;
    if (state.mode !== 'folder') { state.mode = 'folder'; renderMode(); }
    loadDir(p, false);
  };

  $('btnReset').onclick = () => {
    state.cfg.output_format = DEFAULTS.output_format;
    state.cfg.quality = DEFAULTS.quality;
    state.cfg.width = DEFAULTS.width;
    state.cfg.save_mode = DEFAULTS.save_mode;
    state.cfg.ico_sizes = [...state.meta.icoSizes];
    $('quality').value = state.cfg.quality;
    $('qualityNum').textContent = state.cfg.quality + '%';
    $('width').value = '';
    renderFormat(); renderSaveMode(); renderConditional();
    toast('已重置为默认设置。');
  };

  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'select' || tag === 'textarea';
    if (mod && e.key === 'Enter') { e.preventDefault(); start(); return; }
    if (mod && e.key.toLowerCase() === 'r') { e.preventDefault(); refresh(false); return; }
    if (typing) return;
    if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); selectAll(); return; }
    if (e.key === 'Escape') { clearSelection(); return; }
    if (e.key === 'Delete' && state.mode === 'files' && state.selected.size) {
      state.items = state.items.filter((f) => !state.selected.has(key(f.path)));
      state.selected.clear();
      rebuild();
    }
  });

  window.addEventListener('focus', () => { if (!state.running) refresh(true); });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !state.running) refresh(true);
  });
}

/* ------------------------------------------------------------------ 启动 */
/* 记录走到哪一步炸的。原来只报一句"界面初始化失败：<英文>"，
   既不知道哪一步、也看不到细节 —— 用户没法贴给我，窗口一关线索就没了。 */
let bootStage = '启动';

/* 出错时：中文说清哪一步 + 原文附在后面，并且**写进后端日志** */
function reportFailure(where, e) {
  const raw = (e && e.message) ? e.message : String(e);
  toast(`界面初始化失败（${where}）：${raw}`, true);
  try {
    if (state.api && state.api.report_error) {
      state.api.report_error(`${where}: ${raw}\n${(e && e.stack) || ''}`);
    }
  } catch (_) { /* 报错通道本身不能再抛 */ }
}

async function boot() {
  bootStage = '连接界面桥';
  state.api = await apiReady();

  bootStage = '读取后端数据';
  const r = await state.api.bootstrap();
  if (!r || !r.ok) { toast('后端没有就绪。', true); return; }

  bootStage = '应用外观';
  applyAppearance(r);
  state.cfg = r.config;
  state.history = r.history || [];
  state.meta = { formats: r.formats, saveModes: r.saveModes, icoSizes: r.icoSizes,
                 thumbLimit: r.thumbLimit || 100 };
  state.dir = r.sourceDir || '';

  bootStage = '渲染界面';
  renderFormat();
  renderSaveMode();
  $('quality').value = state.cfg.quality;
  $('qualityNum').textContent = state.cfg.quality + '%';
  $('width').value = state.cfg.width || '';
  $('src').value = state.dir;
  renderHistory();
  applyScan(r.scan);
  renderMode();
  renderConditional();

  bootStage = '绑定交互';
  bind();
  bindMarquee();
  bindHover();
  bindDrop();

  bootStage = '';
  $('status').textContent = '待命';
  if (r.log) $('logHint').textContent = r.log;
  setLogOpen(false);
}

boot().catch((e) => reportFailure(bootStage, e));

/* 任何脚本错误都显出来并记档。WebView 里没有控制台，静默失败最难查
   （踩过：绑事件时抛异常 → 点哪儿都没反应，界面上却看不出任何异常）。 */
window.addEventListener('error', (e) => {
  const where = '脚本运行时';
  toast(`界面脚本出错：${e.message || e.type}`, true);
  try {
    if (state.api && state.api.report_error) {
      state.api.report_error(`${where}: ${e.message || e.type}\n${e.filename || ''}:${e.lineno || 0}`);
    }
  } catch (_) { /* ignore */ }
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e && e.reason;
  const raw = (r && r.message) ? r.message : String(r);
  toast(`界面有个异步操作失败了：${raw}`, true);
  try {
    if (state.api && state.api.report_error) {
      state.api.report_error(`未处理的 Promise 拒绝: ${raw}\n${(r && r.stack) || ''}`);
    }
  } catch (_) { /* ignore */ }
});

/* 调试口子：开 MOSS_IMG_DEBUG=1 起窗口后，可以在 devtools 里直接看状态。 */
window.__img = {
  get state() { return state; },
  selectAll, clearSelection, selectType, rebuild, refresh, start, clickItem, targets,
};
