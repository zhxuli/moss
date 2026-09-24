/* app.js —— 图片工具前端
   ---------------------------------------------------------------------------
   不引框架：界面骨架写在 index.html 里，JS 只做四件事 ——
   渲染选择器、接事件、轮询日志、接拖放。

   选择器（.picker）的交互模型，跟资源管理器对齐：
     · 单击        = 选中它（清掉别的）
     · Ctrl+单击   = 加选 / 取消这一个
     · Shift+单击  = 从上一个锚点连选一段
     · 空白处拖框  = 框选（按住 Ctrl 则并进原有选择）
     · 双击        = 用系统默认程序打开
     · Ctrl+A / Esc / Delete
   被选中的那些就是**要处理的**；一个都没选 = 全都处理。

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
  ico: 'ico 不用这个值',
};

const MODE_LABELS = { folder: '文件夹', files: '文件清单' };
const MODE_TITLES = {
  folder: '处理一个文件夹里的图片',
  files: '只处理手挑出来的这几个文件',
};

const DEFAULTS = {
  save_mode: 'separate', output_format: 'jpg', quality: 80,
  width: '', ico_sizes: [], source_filter: {},
};

const THUMB_CHUNK = 20;        // 一次向后端要多少张缩略图
const DRAG_THRESHOLD = 4;      // 超过这么多像素才算"框选"，否则算单击

const $ = (id) => document.getElementById(id);

const state = {
  api: null, cfg: null, meta: null,
  history: [],
  mode: 'folder',
  scan: null,                  // 文件夹扫描结果 {ok, exts, count, message}
  filters: {},                 // ext -> bool（类型过滤）
  dir: '',
  items: [],                   // 当前网格里的全部条目
  selected: new Set(),         // 选中的 path（小写）
  anchor: null,                // Shift 连选的锚点
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

/* ------------------------------------------------------------------ 渲染：静态块 */
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
      renderMode();
      if (m === 'files' && !state.items.length) { pickFiles(); return; }
      rebuild();
    };
    box.appendChild(b);
  }
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
      checkIco();
    };
    label.appendChild(cb);
    label.appendChild(document.createTextNode(String(size)));
    box.appendChild(label);
  }
}

function checkIco() {
  const note = $('fieldIco').querySelector('.field-note');
  if (!state.cfg.ico_sizes.length) {
    note.classList.add('err');
    note.textContent = '一个都没勾 —— 会按全部标准尺寸生成（16/24/32/48/64/128/256）。';
  } else {
    note.classList.remove('err');
    note.textContent = 'Windows 按场景自动挑：任务栏 32、资源管理器 16/48、预览 256。';
  }
}

function renderHistory() {
  const sel = $('history');
  sel.textContent = '';
  const head = el('option', null, state.history.length ? '最近使用…' : '（暂无历史记录）');
  head.value = '';
  sel.appendChild(head);
  for (const p of state.history) {
    const o = el('option', null, p);
    o.value = p;
    sel.appendChild(o);
  }
  sel.value = '';
}

/* 类型过滤：现在只对「文件夹」模式有意义（文件清单是你自己挑的） */
function renderTypes() {
  const box = $('types');
  box.textContent = '';
  if (state.mode !== 'folder') { box.hidden = true; return; }
  box.hidden = false;
  const exts = (state.scan && state.scan.exts) || [];
  if (!exts.length) return;
  box.appendChild(el('span', 'lead', '类型'));
  for (const item of exts) {
    const on = state.filters[item.ext] !== false;
    const chip = el('button', 'chip' + (on ? ' on' : ''));
    chip.type = 'button';
    chip.title = on ? '点一下：不看这类' : '点一下：看这类';
    chip.appendChild(el('span', null, item.ext.toUpperCase()));
    chip.appendChild(el('span', 'n', String(item.count)));
    chip.onclick = () => {
      state.filters[item.ext] = !on;
      rebuild();
    };
    box.appendChild(chip);
  }
}

/* ------------------------------------------------------------------ 渲染：选择器 */
function visiblePaths() {
  return state.items.map((f) => key(f.path));
}

function rebuild() {
  /* 从「当前模式 + 来源 + 类型过滤」重新算出条目集合 */
  if (state.mode === 'folder') {
    const on = new Set(Object.keys(state.filters).filter((e) => state.filters[e] !== false));
    let all = (state.scan && state.scan.files) || [];
    if (on.size) all = all.filter((f) => on.has(f.ext));
    state.items = all;
    pruneSelection();
  }
  state.showThumbs = state.items.length > 0 && state.items.length <= state.meta.thumbLimit;
  renderTypes();
  renderGrid();
  renderSelection();
}

function renderGrid() {
  const grid = $('grid');
  const empty = $('pickerEmpty');
  grid.textContent = '';
  grid.classList.toggle('rows', !state.showThumbs);
  state.thumbDone = 0;

  if (!state.items.length) {
    grid.hidden = true;
    empty.hidden = false;
    empty.textContent = state.mode === 'files'
      ? '还没有文件。点「加文件…」，或者直接把图片拖进来。'
      : ((state.scan && state.scan.message) || '拖一个文件夹或几张图进来，或者点「选择…」。');
    return;
  }
  empty.hidden = true;
  grid.hidden = false;

  for (const f of state.items) {
    const tile = el('div', 'tile' + (f.exists === false ? ' gone' : ''));
    tile.dataset.path = key(f.path);
    tile.title = f.path + (f.size != null ? '\n' + humanSize(f.size) : '');

    if (state.showThumbs) {
      const box = el('div', 'thumb');
      if (f.data) {
        const img = el('img');
        img.src = f.data;
        img.alt = '';
        img.draggable = false;
        box.appendChild(img);
        tile.classList.add('has-thumb');
      } else {
        box.appendChild(el('span', 'ph', '图片'));
        queueThumb(tile, f);
      }
      tile.appendChild(box);
      tile.appendChild(el('div', 'name', f.name));
    } else {
      const ico = el('span', 'fico', (f.ext || '').replace('.', '').toUpperCase() || '?');
      tile.appendChild(ico);
      tile.appendChild(el('span', 'name', f.name));
      tile.appendChild(el('span', 'fdir', f.dir || ''));
      tile.appendChild(el('span', 'fsize', f.exists === false ? '已不在' : humanSize(f.size)));
    }

    const badge = el('span', 'check-badge');
    badge.appendChild(el('span', null, '✓'));
    tile.appendChild(badge);

    grid.appendChild(tile);
  }
  if (state.showThumbs) loadThumbs();
  applySelectionClasses();
}

/* 缩略图分批拉：界面先出来，图慢慢补齐 */
let thumbQueue = [];
let thumbBusy = false;

function queueThumb(tile, item) {
  thumbQueue.push({ path: item.path, item });
}

function loadThumbs() {
  thumbQueue = thumbQueue.filter((q) => !q.item.data);
  if (thumbBusy || !thumbQueue.length) return;
  const batch = thumbQueue.splice(0, THUMB_CHUNK);
  thumbBusy = true;
  state.api.thumbs(batch.map((b) => b.path)).then((got) => {
    thumbBusy = false;
    if (got && got.ok) {
      for (const t of got.thumbs) {
        const hit = batch.find((b) => key(b.path) === key(t.path));
        if (!hit) continue;
        hit.item.data = t.data;
        const tile = $('grid').querySelector(`.tile[data-path="${cssEscape(key(t.path))}"]`);
        if (!tile) continue;
        const box = tile.querySelector('.thumb');
        if (t.data) {
          box.textContent = '';
          const img = el('img');
          img.src = t.data;
          img.draggable = false;
          box.appendChild(img);
          tile.classList.add('has-thumb');
        }
      }
    }
    state.thumbDone += batch.length;
    renderPickerNote();
    if (thumbQueue.length) setTimeout(loadThumbs, 0);
  }).catch(() => { thumbBusy = false; });
}

function cssEscape(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

function applySelectionClasses() {
  for (const tile of $('grid').children) {
    const on = state.selected.has(tile.dataset.path);
    tile.classList.toggle('sel', on);
  }
}

function renderSelection() {
  const total = state.items.length;
  const n = state.selected.size;
  $('selCount').textContent = total ? `已选 ${n} / ${total}` : '';
  applySelectionClasses();
  renderPickerNote();
  renderSource();
}

function renderPickerNote() {
  const total = state.items.length;
  const n = state.selected.size;
  const parts = [];
  if (!total) parts.push('—');
  else if (!n) parts.push(`不选 = 全部 ${total} 个`);
  else parts.push(`将处理 ${n} 个`);
  if (state.showThumbs && state.thumbDone < total) parts.push(`缩略图 ${state.thumbDone}/${total}`);
  if (total > state.meta.thumbLimit) parts.push('文件较多，用列表显示');
  $('pickerNote').textContent = parts.join(' · ');
}

function renderSource() {
  const total = state.items.length;
  const n = state.selected.size;
  const effective = n || total;
  $('pill').textContent = total ? `${effective} 个` : '—';
  $('pill').classList.toggle('mute', !total);
  const where = state.mode === 'files'
    ? (total ? `文件清单：${total} 个` : '还没有文件')
    : (state.dir || '');
  $('tbPath').textContent = where;
  $('tbPath').title = where;
  $('sub').textContent = total
    ? (n ? `已选 ${n} / ${total}，将处理这 ${n} 个` : `将处理全部 ${total} 个`)
    : (state.mode === 'files' ? '点「加文件…」或把图片拖进来。' : '拖一个文件夹或几张图进来，或者点「选择…」。');

  const note = $('srcNote');
  const gone = state.items.filter((f) => f.exists === false).length;
  if (gone) {
    note.className = 'field-note err';
    note.textContent = `有 ${gone} 个文件已经不在了（灰掉的那些）—— 处理前会被拦下，点「刷新」清掉。`;
  } else if (state.mode === 'files') {
    note.className = 'field-note';
    note.textContent = '文件可以来自不同文件夹；「保存到源文件夹」会写回各自所在的目录。';
  } else {
    note.className = 'field-note';
    note.textContent = '';
  }
}

function renderConditional() {
  const fmt = state.cfg.output_format;
  $('fieldWidth').hidden = fmt === 'ico';
  $('fieldIco').hidden = fmt !== 'ico';
  $('qualityHint').textContent = QUALITY_HINT[fmt] || '';
  checkIco();

  const width = String(state.cfg.width || '').trim();
  const note = $('widthNote');
  if (width && !/^\d+$/.test(width)) {
    note.className = 'field-note err';
    note.textContent = '只认整数像素值，非数字会被忽略。';
  } else if (width && Number(width) === 0) {
    note.className = 'field-note err';
    note.textContent = '0 不是有效宽度。';
  } else {
    note.className = 'field-note';
    note.textContent = '只缩不放：原图比它窄就保持原样。';
  }

  const saveNote = $('saveNote');
  const byFiles = state.mode === 'files';
  if (state.cfg.save_mode === 'separate') {
    saveNote.className = 'field-note';
    saveNote.textContent = byFiles
      ? '输出到「第一个文件所在目录」下的 compressed_output\\。'
      : '输出到源文件夹下的 compressed_output\\。';
  } else if (state.cfg.save_mode === 'source') {
    saveNote.className = 'field-note warn';
    saveNote.textContent = byFiles
      ? '每个文件写回它自己所在的目录，同名会被覆盖。'
      : '直接写回源文件夹，同名文件会被覆盖。';
  } else {
    saveNote.className = 'field-note err';
    saveNote.textContent = byFiles
      ? '转换成功后永久删除源文件（各删各的），无法撤销。'
      : '转换成功后永久删除源文件，无法撤销。';
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

/* 单击 / Ctrl / Shift —— 跟资源管理器一致 */
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
    picker.focus({ preventScroll: true });
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
    renderPickerNote();
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

  // 双击打开
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

/* ------------------------------------------------------------------ 数据 */
function scanSig(scan) {
  if (!scan) return '';
  return JSON.stringify([scan.ok, scan.count, (scan.exts || []).map((i) => [i.ext, i.count])]);
}

function applyScan(scan, keepFilters) {
  state.scan = scan || { ok: false, exts: [], count: 0, files: [], message: '请选择一个有效的文件夹。' };
  const saved = (state.cfg && state.cfg.source_filter) || {};
  const next = {};
  for (const item of state.scan.exts || []) {
    if (keepFilters && state.filters[item.ext] !== undefined) next[item.ext] = state.filters[item.ext];
    else next[item.ext] = saved[item.ext] !== false;
  }
  state.filters = next;
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

function setFileItems(files, replace) {
  if (replace) state.items = [];
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
  if (scan && scan.ok && !(scan.exts || []).length) toast(scan.message, true);
}

async function pickFiles() {
  const got = await state.api.pick_files(state.items.length ? state.items[0].dir : state.dir);
  if (!got || !got.ok) { toast((got && got.message) || '打开选择框失败。', true); return; }
  if (!got.files || !got.files.length) return;
  if (state.mode !== 'files') { state.mode = 'files'; renderMode(); state.items = []; }
  const added = setFileItems(got.files, false);
  rebuild();
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
    applyScan(scan, true);
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
/* 日志默认折着：没内容就不占地方。一开工自动展开，标题行可手动收放。 */
function setLogOpen(open) {
  state.logOpen = !!open;
  $('logBox').hidden = !state.logOpen;
  $('logField').classList.toggle('open', state.logOpen);
}

function setRunning(on) {
  state.running = on;
  $('spin').hidden = !on;
  $('btnStart').disabled = on;
  $('btnStart').textContent = on ? '正在处理…' : '开始处理';
  $('logHint').textContent = on ? '处理中' : '';
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
  /* 文件夹模式 + 没勾选 → 交回后端扫目录（几千张也不会被前端的名单上限截断）；
     只要动了选择，就按"明确的一批文件"来跑。 */
  const explicit = state.mode === 'files' || state.selected.size > 0;
  const payload = {
    mode: explicit ? 'files' : 'folder',
    source_dir: state.dir,
    files: explicit ? picked.map((f) => ({ path: f.path })) : [],
    output_format: state.cfg.output_format,
    quality: Number($('quality').value),
    width: String($('width').value || '').trim(),
    save_mode: state.cfg.save_mode,
    ico_sizes: state.cfg.ico_sizes,
    source_filter: { ...state.filters },
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
  if (state.mode !== 'files') { state.mode = 'files'; renderMode(); state.items = []; }
  const added = setFileItems(got.files || [], false);
  rebuild();
  if (got.note) toast(got.note, true);
  else toast(added ? `已加入 ${added} 个文件。` : '这些文件已经在清单里了。');
  renderConditional();
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
    $('tbPath').textContent = state.dir;
    clearTimeout(scanTimer);
    scanTimer = setTimeout(async () => {
      if (state.mode !== 'folder') return;
      const scan = await state.api.scan(state.dir);
      applyScan(scan, true);
      if (scan && scan.history) { state.history = scan.history; renderHistory(); }
    }, 350);
  };
  $('src').onfocus = () => { if (state.mode !== 'folder') { state.mode = 'folder'; renderMode(); } };

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
    state.filters = {};
    for (const item of (state.scan && state.scan.exts) || []) state.filters[item.ext] = true;
    $('quality').value = state.cfg.quality;
    $('qualityNum').textContent = state.cfg.quality + '%';
    $('width').value = '';
    renderFormat(); renderSaveMode(); renderIcoSizes();
    rebuild(); renderConditional();
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
async function boot() {
  state.api = await apiReady();
  const r = await state.api.bootstrap();
  if (!r || !r.ok) { toast('后端没有就绪。', true); return; }

  applyAppearance(r);
  state.cfg = r.config;
  state.history = r.history || [];
  state.meta = { formats: r.formats, saveModes: r.saveModes, icoSizes: r.icoSizes,
                 thumbLimit: r.thumbLimit || 100 };
  state.dir = r.sourceDir || '';

  renderMode();
  renderFormat();
  renderSaveMode();
  renderIcoSizes();
  $('quality').value = state.cfg.quality;
  $('qualityNum').textContent = state.cfg.quality + '%';
  $('width').value = state.cfg.width || '';
  $('src').value = state.dir;
  renderHistory();
  applyScan(r.scan);
  renderConditional();
  bind();
  bindMarquee();
  bindDrop();

  $('status').textContent = '待命';
  if (r.log) $('logHint').textContent = r.log;
  setLogOpen(false);
}

boot().catch((e) => toast('界面初始化失败：' + e, true));

/* 脚本一出错就显出来。WebView 里没有控制台，静默失败最难查
   （踩过：绑事件时抛异常 → 点哪儿都没反应，界面上却看不出任何异常）。 */
window.addEventListener('error', (e) => {
  toast('界面脚本出错：' + (e.message || e.type), true);
});

/* 调试口子：开 MOSS_IMG_DEBUG=1 起窗口后，可以在 devtools 里
   直接看状态、调选择函数。日常不影响任何东西。 */
window.__img = {
  get state() { return state; },
  selectAll, clearSelection, rebuild, refresh, start,
  clickItem, targets,
};
