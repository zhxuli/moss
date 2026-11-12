const SAVE_LABELS = {
  source: '覆盖原图',
  source_delete: '删除原图',
  separate: '新文件夹',
};
const SAVE_TITLES = {
  separate: '另存到一个单独的文件夹，位置可以自选，也可以把文件夹拖到右边那格上',
  source: '直接写回源文件夹，同名文件会被覆盖',
  source_delete: '转换成功后删除源文件，无法撤销',
};
const SAVE_ORDER = ['source', 'source_delete', 'separate'];

const QUALITY_HINT = {
  jpg: '数值越高越清晰、文件越大',
  webp: '数值越高越清晰、文件越大',
  png: 'png 下映射成压缩级别：数值越压得越少',
};

const MODE_LABELS = { folder: '文件夹', files: '文件清单' };
const MODE_TITLES = { folder: '处理一个文件夹里的图片', files: '只处理手挑出来的这几个文件' };

import { svg, mountIcons } from './icons.js';

import { makeApi, isEmbedded, onHostDrop, onHostEvent } from './bridge.js';

const DEFAULTS = { save_mode: 'separate', output_format: 'jpg', quality: 80, width: '', ico_sizes: [] };

const THUMB_CHUNK = 20;
const DRAG_THRESHOLD = 4;

const $ = (id) => document.getElementById(id);

const state = {
  api: null, cfg: null, meta: null,
  history: [],
  mode: 'folder',
  scan: null,                  
  dir: '',
  items: [],                   
  selected: new Set(),         
  anchor: null,
  showThumbs: false,
  thumbDone: 0,
  running: false,
  jobId: null,
  outputDir: '',
  dropTimer: null,
  logOpen: false,
};

function apiReady() {
  return makeApi();
}

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
  const node = el('div', 'toast' + (bad ? ' bad' : ''));
  node.innerHTML = svg(bad ? 'xCircle' : 'checkCircle');
  node.appendChild(el('span', null, message));
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

function renderMode() {
  const box = $('segMode');
  box.textContent = '';
  for (const m of ['folder', 'files']) {
    const b = el('button');
    b.type = 'button';
    b.title = MODE_TITLES[m];
    b.innerHTML = svg(m === 'folder' ? 'folder' : 'file')
                + '<span>' + MODE_LABELS[m] + '</span>';
    b.setAttribute('aria-selected', String(state.mode === m));
    b.onclick = () => {
      if (state.mode === m) return;
      if (m === 'files') {
        pickFiles();
        return;
      }
      state.mode = 'folder';
      renderMode();
      rebuild();
    };
    box.appendChild(b);
  }

  const folder = state.mode === 'folder';
  $('src').hidden = !folder;
  $('btnPick').hidden = !folder;
  $('combo').hidden = !folder;   
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
  const order = SAVE_ORDER.filter((m) => state.meta.saveModes.includes(m));
  for (const m of state.meta.saveModes) if (!order.includes(m)) order.push(m);
  for (const mode of order) {
    const b = el('button', mode === 'source_delete' ? 'warn' : null, SAVE_LABELS[mode] || mode);
    b.type = 'button';
    b.title = SAVE_TITLES[mode] || SAVE_LABELS[mode] || mode;
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

let histIndex = -1;

function histMatches(filter) {
  const f = String(filter || '').trim().toLowerCase();
  if (!f) return state.history.slice();
  return state.history.filter((p) => p.toLowerCase().includes(f));
}

function renderHistory() {   
  if (!$('histMenu').hidden) openHistory($('src').value);
}

function openHistory(filter) {
  const menu = $('histMenu');
  const items = histMatches(filter);
  menu.textContent = '';
  histIndex = -1;
  if (!items.length) {
    menu.appendChild(el('div', 'empty',
      state.history.length ? '没有匹配的最近记录' : '还没有历史记录'));
  } else {
    items.forEach((p, i) => {
      const b = el('button', 'item', p);
      b.type = 'button';
      b.title = p;
      b.dataset.path = p;
      b.onmousedown = (e) => { e.preventDefault(); pickHistory(p); };   
      b.onmouseenter = () => setHistIndex(i);
      menu.appendChild(b);
    });
  }
  menu.hidden = false;
  $('combo').classList.add('open');
}

function closeHistory() {
  $('histMenu').hidden = true;
  $('combo').classList.remove('open');
  histIndex = -1;
}

function setHistIndex(i) {
  const items = [...$('histMenu').querySelectorAll('.item')];
  if (!items.length) return;
  histIndex = (i + items.length) % items.length;
  items.forEach((n, k) => n.classList.toggle('on', k === histIndex));
  items[histIndex].scrollIntoView({ block: 'nearest' });
}

function pickHistory(path) {
  closeHistory();
  if (state.mode !== 'folder') { state.mode = 'folder'; renderMode(); }
  $('src').value = path;
  loadDir(path, false);
}

function bindHistory() {
  const openIfClosed = () => {
    if ($('histMenu').hidden) {
      openHistory($('src').value === state.dir ? '' : $('src').value);
    }
  };
  $('src').onfocus = openIfClosed;
  $('src').onclick = openIfClosed;

  $('btnHist').onclick = (e) => {
    e.preventDefault();
    if ($('histMenu').hidden) { $('src').focus(); openHistory(''); }
    else closeHistory();
  };
  $('src').onkeydown = (e) => {
    if (e.key === 'Escape') { closeHistory(); $('src').blur(); return; }
    if (!$('histMenu').hidden) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setHistIndex(histIndex + 1); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setHistIndex(histIndex - 1); return; }
      if (e.key === 'Enter') {
        const items = [...$('histMenu').querySelectorAll('.item')];
        if (histIndex >= 0 && items[histIndex]) {
          e.preventDefault();
          pickHistory(items[histIndex].dataset.path);
          return;
        }
      }
    }
    if (e.key === 'Enter') { e.preventDefault(); closeHistory(); loadDir($('src').value, false); }
  };

  document.addEventListener('mousedown', (e) => {
    if (!$('combo').contains(e.target)) closeHistory();
  });
}

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

    if (state.showThumbs) {
      const box = el('div', 'thumb');
      const k = tile.dataset.path;
      if (!f.data && thumbCache.has(k)) f.data = thumbCache.get(k);   
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
    tile.appendChild(el('span', 'check-badge')).innerHTML = svg('check');
    grid.appendChild(tile);
  }
  if (state.showThumbs) loadThumbs();
  applySelectionClasses();
}

let thumbQueue = [];
let thumbBusy = false;

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

function renderNote() {
  const note = $('srcNote');
  if (note.classList.contains('err')) return;      
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

  $('startLabel').textContent = state.running ? '正在处理…'
                              : (effective ? `开始处理 (${effective})` : '开始处理');
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

  if (!state.embedded && state.api && state.api.set_title) state.api.set_title(title);
}

function renderConditional() {
  const fmt = state.cfg.output_format;
  const isIco = fmt === 'ico';

  $('qualitySlot').hidden = isIco;
  $('icoSlot').hidden = !isIco;
  renderIcoSizes();

  const width = String(state.cfg.width || '').trim();
  const bad = !!width && (!/^\d+$/.test(width) || Number(width) === 0);
  $('width').classList.toggle('invalid', bad);
  $('width').title = bad
    ? '只认正整数像素值（0 和字母会被忽略，等于保持原尺寸）'
    : '只缩不放：原图比它窄就保持原样；留空 = 保持原始尺寸';

  const separate = state.cfg.save_mode === 'separate';
  $('outDirWrap').hidden = !separate;
  if (separate) $('outDir').value = state.cfg.output_dir || '';

  $('btnOutDirReset').hidden = !(state.cfg.output_dir || '').trim();
  renderWarn();
}

function renderWarn() {
  const box = $('warnInline');
  const mode = state.cfg.save_mode;
  const byFiles = state.mode === 'files';
  if (mode === 'separate') { box.hidden = true; box.textContent = ''; return; }
  const text = mode === 'source_delete'
    ? (byFiles ? '各文件转换后，源文件会被删除' : '源文件转换后会被删除，无法撤销')
    : (byFiles ? '写回各自目录，同名文件会被覆盖' : '写回源目录，同名文件会被覆盖');
  box.hidden = false;
  box.className = 'warn-inline' + (mode === 'source_delete' ? '' : ' soft');
  box.innerHTML = svg('alert') + '<span>' + text + '</span>';
}

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
    if (e.target.closest('.tile') && e.detail > 1) return;   
    const p = local(e);
    sx = p.x; sy = p.y;
    active = true; moved = false;
    base = new Set(state.selected);

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

    hoverTimer = setTimeout(() => showCard(tile, p), 180);
  });

  grid.addEventListener('mouseleave', hide);
  $('picker').addEventListener('scroll', hide, { passive: true });
}

function placeCard(card, tile) {
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
  if (hoverPath !== pathKey) return;                 
  const item = state.items.find((f) => key(f.path) === pathKey);
  if (!item) return;

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
    output_dir: state.cfg.save_mode === 'separate' ? (state.cfg.output_dir || '') : '',
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

let dropZone = 'source';

let pendingZone = null;

function setDropZone(zone) {
  if (dropZone === zone) return;
  dropZone = zone;
  const wrap = $('outDirWrap');
  if (zone === 'output') {
    hideVeil();
    wrap.classList.add('over');
  } else {
    wrap.classList.remove('over');
  }
}

function pollTakeDrop(zone) {
  let tries = 0;
  const tick = async () => {
    tries += 1;
    const got = await state.api.take_drop();
    if (got && got.pending) { applyDrop(got, zone); return; }
    if (tries < 25) state.dropTimer = setTimeout(tick, 120);
    else toast('没拿到拖进来的内容（拖放可能没接上）。', true);
  };
  tick();
}

function onDropEvent() {
  clearDragHint();
  const zone = dropZone;
  dropZone = 'source';
  if (isEmbedded()) { pendingZone = zone; return; }
  pollTakeDrop(zone);
}

async function applyDrop(got, zone) {
  if (got.history) { state.history = got.history; renderHistory(); }

  if (zone === 'output') {
    const first = (got.files && got.files[0] && got.files[0].path)
      || (got.folder || '');
    if (!first) { toast('没拿到拖进来的路径。', true); return; }
    const info = await state.api.check_path(first);
    const dir = (info && info.isdir) ? first : ((info && info.parent) || '');
    if (!dir) { toast('拖进来的东西不是一个文件夹。', true); return; }
    state.cfg.output_dir = dir;
    $('outDir').value = dir;
    renderConditional();
    toast('输出目录已设为：' + dir);
    return;
  }

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

function clearDragHint() {
  hideVeil();
  const wrap = $('outDirWrap');
  if (wrap) wrap.classList.remove('over');
}

function bindDrop() {
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };

  let captured = false;

  const hasFiles = (e) => !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf('Files') >= 0);
  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    stop(e);
    const wrap = $('outDirWrap');
    const overOutput = !wrap.hidden && wrap.contains(e.target);
    setDropZone(overOutput ? 'output' : 'source');
    if (!overOutput) showVeil();
  });
  window.addEventListener('dragenter', (e) => { if (hasFiles(e)) stop(e); });
  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    stop(e);
    if (captured) return;                       
    if (e.relatedTarget === null) clearDragHint();
  });
  window.addEventListener('drop', (e) => { stop(e); onDropEvent(); });

  window.addEventListener('dragend', () => { captured = false; clearDragHint(); });
  window.addEventListener('blur', () => { captured = false; clearDragHint(); });

  onHostEvent('captured', () => { captured = true; });
  onHostEvent('dragend', () => { captured = false; clearDragHint(); });
  onHostDrop(async (paths) => {
    const zone = pendingZone || 'source';
    pendingZone = null;
    clearDragHint();                            
    try {
      await state.api.push_drop(paths);
    } catch (err) {
      toast('拖进来的路径没能交给后端：' + (err && err.message ? err.message : err), true);
      return;
    }
    pollTakeDrop(zone);
  });
}

function outputTarget() {
  if (state.outputDir) return state.outputDir;
  const custom = (state.cfg.output_dir || '').trim();
  if (custom) return custom;
  if (state.mode === 'files') return state.items.length ? (state.items[0].dir || '') : '';
  return state.dir || '';
}

function bind() {
  $('btnLogToggle').onclick = () => setLogOpen(!state.logOpen);
  $('btnPick').onclick = () => loadDir(state.dir, true);
  $('btnAddFiles').onclick = () => pickFiles();
  $('btnClearFiles').onclick = () => {
    state.items = [];

    state.mode = 'folder';
    renderMode();
    rebuild();
    renderConditional();
  };
  $('btnRefresh').onclick = () => refresh(false);
  $('btnSelAll').onclick = () => selectAll();
  $('btnSelNone').onclick = () => clearSelection();
  $('btnReveal').onclick = async () => {
    const target = outputTarget();
    if (!target) { toast('还没有能打开的目录。', true); return; }
    const res = await state.api.reveal(target);
    if (!res || !res.ok) { toast((res && res.message) || '打开失败。', true); return; }
    if (res.fellBack) toast('这个目录还没生成，已打开上层：' + res.opened);
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
  $('outDir').oninput = () => {
    state.cfg.output_dir = $('outDir').value.trim();
    renderConditional();
  };
  $('btnOutDir').onclick = async () => {
    const picked = await state.api.pick_dir(state.cfg.output_dir || state.dir);
    if (!picked || !picked.ok) { toast((picked && picked.message) || '打开选择框失败。', true); return; }
    if (!picked.path) return;
    state.cfg.output_dir = picked.path;
    $('outDir').value = picked.path;
    renderConditional();
  };

  $('btnOutDirReset').onclick = () => {
    state.cfg.output_dir = '';
    $('outDir').value = '';
    state.outputDir = '';          
    renderConditional();
    toast('输出目录已恢复默认。');
  };

  let scanTimer = null;
  $('src').oninput = () => {
    state.dir = $('src').value;
    syncTitle();

    if (!$('histMenu').hidden) {
      const hit = histMatches(state.dir);
      if (hit.length) openHistory(state.dir); else closeHistory();
    }
    clearTimeout(scanTimer);
    scanTimer = setTimeout(async () => {
      if (state.mode !== 'folder') return;
      const scan = await state.api.scan(state.dir);
      applyScan(scan);
      if (scan && scan.history) { state.history = scan.history; renderHistory(); }
    }, 350);
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
    state.cfg.output_dir = '';
    $('outDir').value = '';
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

async function openHelp() {
  const sheet = $('helpSheet');
  sheet.hidden = false;
  if (!$('helpUsage').textContent) {
    const got = await state.api.help();
    $('helpUsage').textContent = (got && got.usage) || '（取不到用法文本）';
  }
}

function closeHelp() { $('helpSheet').hidden = true; }

function bindHelp() {
  $('btnHelp').onclick = () => openHelp();
  $('btnHelpClose').onclick = () => closeHelp();
  $('helpScrim').onclick = () => closeHelp();
  $('btnHelpCopy').onclick = async () => {
    const res = await state.api.copy($('helpUsage').textContent);
    if (!res || !res.ok) { toast((res && res.message) || '复制失败。', true); return; }
    toast('用法已复制到剪贴板。');
  };
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('helpSheet').hidden) closeHelp();
  });
}

let bootStage = '启动';

function reportFailure(where, e) {
  const raw = (e && e.message) ? e.message : String(e);
  toast(`界面初始化失败（${where}）：${raw}`, true);
  reportToBackend(`${where}: ${raw}\n${(e && e.stack) || ''}`);
}

function reportToBackend(text) {
  if (state.reportBroken) return;
  try {
    if (!state.api || !state.api.report_error) return;
    const p = state.api.report_error(text);
    if (p && typeof p.catch === 'function') p.catch(() => { state.reportBroken = true; });
  } catch (_) {
    state.reportBroken = true;      
  }
}

async function boot() {
  bootStage = '连接界面桥';
  state.api = await apiReady();

  bootStage = '读取后端数据';
  const r = await state.api.bootstrap();
  if (!r || !r.ok) { toast('后端没有就绪。', true); return; }

  bootStage = '应用外观';
  applyAppearance(r);
  state.embedded = !!r.embedded;      
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
  $('outDir').value = state.cfg.output_dir || '';
  $('src').value = state.dir;
  renderHistory();
  applyScan(r.scan);
  renderMode();
  renderConditional();

  bootStage = '绑定交互';
  bind();
  bindHistory();
  bindMarquee();
  bindHover();
  bindDrop();
  bindHelp();

  bootStage = '装图标';
  mountIcons();

  bootStage = '';
  $('status').textContent = '待命';
  if (r.log) $('logHint').textContent = r.log;
  setLogOpen(false);
}

boot().catch((e) => reportFailure(bootStage, e));

window.addEventListener('error', (e) => {
  const where = '脚本运行时';
  toast(`界面脚本出错：${e.message || e.type}`, true);
  reportToBackend(`${where}: ${e.message || e.type}\n${e.filename || ''}:${e.lineno || 0}`);
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e && e.reason;
  const raw = (r && r.message) ? r.message : String(r);
  toast(`界面有个异步操作失败了：${raw}`, true);
  reportToBackend(`未处理的 Promise 拒绝: ${raw}\n${(r && r.stack) || ''}`);
});

window.__img = {
  get state() { return state; },
  selectAll, clearSelection, selectType, rebuild, refresh, start, clickItem, targets,
  openHistory, closeHistory, histMatches, renderHistory,
};
