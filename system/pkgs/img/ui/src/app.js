/* app.js —— 图片工具前端
   ---------------------------------------------------------------------------
   这里**不引框架**：这个界面是一张固定表单，静态骨架写在 index.html 里，
   JS 只做三件事 —— 填数据、接事件、轮询日志。
   （exec 用 Vue 是因为它有一颗可增删改的命令树；img 没有会变的结构。）

   后端契约见 gui_web.py 的 Api 类；长任务靠 poll(job_id) 拉输出。 */

const SAVE_LABELS = {
  separate: '保存到单独文件夹',
  source: '保存到源文件夹 (覆盖)',
  source_delete: '转换并删除源文件',
};

const QUALITY_HINT = {
  jpg: '数值越高越清晰、文件越大',
  webp: '数值越高越清晰、文件越大',
  png: 'png 下映射成压缩级别：数值越高压得越少',
  ico: 'ico 不用这个值',
};

const DEFAULTS = {
  save_mode: 'separate',
  output_format: 'jpg',
  quality: 80,
  width: '',
  ico_sizes: [],
  source_filter: {},
};

const $ = (id) => document.getElementById(id);

const state = {
  api: null,
  cfg: null,
  meta: null,          // bootstrap 里的 formats/saveModes/icoSizes 等
  history: [],
  scan: null,          // { ok, exts:[{ext,count}], count, message }
  filters: {},         // ext -> bool
  dir: '',
  jobId: null,
  timer: null,
  outputDir: '',
  running: false,
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

/* ------------------------------------------------------------------ 渲染 */
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

function renderFilters() {
  const box = $('filters');
  box.textContent = '';
  const exts = (state.scan && state.scan.exts) || [];
  if (!exts.length) {
    box.appendChild(el('span', 'field-note', (state.scan && state.scan.message) || '请选择一个有效的文件夹。'));
    $('filterNote').textContent = '';
    return;
  }
  for (const item of exts) {
    const on = state.filters[item.ext] !== false;
    const label = el('label', 'chip' + (on ? ' on' : ''));
    const cb = el('input');
    cb.type = 'checkbox';
    cb.checked = on;
    cb.onchange = () => {
      state.filters[item.ext] = cb.checked;
      label.classList.toggle('on', cb.checked);
      renderFilterNote();
    };
    label.appendChild(cb);
    label.appendChild(document.createTextNode(item.ext.toUpperCase()));
    label.appendChild(el('span', 'n', String(item.count)));
    box.appendChild(label);
  }
  renderFilterNote();
}

function renderFilterNote() {
  const picked = (state.scan.exts || []).filter((i) => state.filters[i.ext] !== false);
  const files = picked.reduce((sum, i) => sum + i.count, 0);
  $('filterNote').textContent = picked.length
    ? `将处理 ${files} 个文件（${picked.map((i) => i.ext.toUpperCase()).join(' / ')}）。`
    : '未选择任何文件类型。';
  $('pill').textContent = files ? `${files} 个文件` : '—';
  $('pill').classList.toggle('mute', !files);
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

/* 按格式切换：ico 时藏起目标宽度、露出尺寸勾选 */
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
  if (state.cfg.save_mode === 'separate') {
    saveNote.className = 'field-note';
    saveNote.textContent = '输出到源文件夹下的 compressed_output\\。';
  } else if (state.cfg.save_mode === 'source') {
    saveNote.className = 'field-note warn';
    saveNote.textContent = '直接写回源文件夹，同名文件会被覆盖。';
  } else {
    saveNote.className = 'field-note err';
    saveNote.textContent = '转换成功后永久删除源文件，无法撤销。';
  }

  $('tbPath').textContent = state.dir || '';
  $('tbPath').title = state.dir || '';
}

/* ------------------------------------------------------------------ 数据 */
function applyScan(scan, keepFilters) {
  state.scan = scan || { ok: false, exts: [], count: 0, message: '请选择一个有效的文件夹。' };
  const saved = (state.cfg && state.cfg.source_filter) || {};
  const next = {};
  for (const item of state.scan.exts || []) {
    if (keepFilters && state.filters[item.ext] !== undefined) next[item.ext] = state.filters[item.ext];
    else next[item.ext] = saved[item.ext] !== false;
  }
  state.filters = next;
  renderFilters();

  const note = $('srcNote');
  if (!state.scan.ok) {
    note.className = 'field-note err';
    note.textContent = state.scan.message;
    $('sub').textContent = '选择一个文件夹，然后开始处理。';
  } else if (!state.scan.exts.length) {
    note.className = 'field-note warn';
    note.textContent = state.scan.message;
    $('sub').textContent = state.dir;
  } else {
    note.className = 'field-note';
    note.textContent = `找到 ${state.scan.count} 张受支持的图片。`;
    $('sub').textContent = state.dir;
  }
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
  if (scan && scan.ok && !scan.exts.length) toast(scan.message, true);
}

/* ------------------------------------------------------------------ 运行 */
function setRunning(on) {
  state.running = on;
  $('spin').hidden = !on;
  $('btnStart').disabled = on;
  $('btnStart').textContent = on ? '正在处理…' : '开始处理';
  $('logHint').textContent = on ? '处理中' : '';
}

function renderLog(got) {
  const box = $('log');
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
  box.textContent = got.output || '';
  if (atBottom) box.scrollTop = box.scrollHeight;

  if (got.running) {
    $('status').textContent = '处理中…';
    return;
  }
  const s = got.summary;
  if (!s) {
    $('status').textContent = got.returncode === 0 ? '完成' : `结束（退出码 ${got.returncode}）`;
    return;
  }
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
    if (got.running) state.timer = setTimeout(pollOnce, 150);
    else { setRunning(false); state.timer = null; }
  }).catch(() => { setRunning(false); });
}

async function start() {
  if (state.running) return;
  const payload = {
    source_dir: state.dir,
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

/* ------------------------------------------------------------------ 事件 */
function bind() {
  $('btnPick').onclick = () => loadDir(state.dir, true);
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
      const scan = await state.api.scan(state.dir);
      applyScan(scan, true);
      if (scan && scan.history) { state.history = scan.history; renderHistory(); }
    }, 350);
  };

  $('history').onchange = (e) => {
    const p = e.target.value;
    e.target.value = '';
    if (p) loadDir(p, false);
  };

  $('btnAll').onclick = () => setAllFilters(true);
  $('btnNone').onclick = () => setAllFilters(false);

  $('btnReset').onclick = () => {
    state.cfg.output_format = DEFAULTS.output_format;
    state.cfg.quality = DEFAULTS.quality;
    state.cfg.width = DEFAULTS.width;
    state.cfg.save_mode = DEFAULTS.save_mode;
    state.cfg.ico_sizes = [...state.meta.icoSizes];
    state.filters = {};
    for (const item of (state.scan && state.scan.exts) || []) state.filters[item.ext] = true;
    syncForm();
    renderFormat(); renderSaveMode(); renderIcoSizes(); renderFilters(); renderConditional();
    toast('已重置为默认设置。');
  };

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); start(); }
  });
}

function setAllFilters(on) {
  for (const item of (state.scan && state.scan.exts) || []) state.filters[item.ext] = on;
  renderFilters();
}

/* 把 state.cfg 写回表单控件 */
function syncForm() {
  $('quality').value = state.cfg.quality;
  $('qualityNum').textContent = state.cfg.quality + '%';
  $('width').value = state.cfg.width || '';
  $('src').value = state.dir;
}

/* ------------------------------------------------------------------ 启动 */
async function boot() {
  state.api = await apiReady();
  const r = await state.api.bootstrap();
  if (!r || !r.ok) { toast('后端没有就绪。', true); return; }

  applyAppearance(r);
  state.cfg = r.config;
  state.history = r.history || [];
  state.meta = {
    formats: r.formats,
    saveModes: r.saveModes,
    icoSizes: r.icoSizes,
  };
  state.dir = r.sourceDir || '';

  renderFormat();
  renderSaveMode();
  renderIcoSizes();
  syncForm();
  renderHistory();
  applyScan(r.scan);
  renderConditional();

  $('status').textContent = '待命';
  if (r.log) $('logHint').textContent = r.log;
  bind();
}

boot().catch((e) => toast('界面初始化失败：' + e, true));
