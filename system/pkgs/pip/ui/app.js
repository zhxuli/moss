(function () {
  'use strict';

  const $ = function (s) { return document.querySelector(s); };
  const $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function esc(s) { return String(s == null ? '' : s); }

  const state = {
    env: null,
    installed: [],
    filter: '',
    outdated: null,
    found: null,
    exportPath: '',
    exportDir: '',
    targets: [],
    job: null,
    jobTimer: null,
  };

  // ─────────────────────────────────────────────── 小工具

  function toast(text, bad) {
    const n = el('div', 'toast' + (bad ? ' bad' : ''), text);
    $('#toasts').appendChild(n);
    setTimeout(function () {
      n.style.transition = 'opacity 140ms ease';
      n.style.opacity = '0';
      setTimeout(function () { n.remove(); }, 160);
    }, bad ? 4200 : 2000);
  }

  /* 忙的时候只压暗、让图标转起来，**不动按钮内容**。
     早先是把 textContent 改成「…」，那会把按钮里的 SVG 图标一起冲掉，
     松手时又只恢复文字 —— 图标就再也回不来了（刷新按钮就是这么坏的）。 */
  function busy(btn, on, label) {
    if (!btn) return;
    if (on) {
      btn.disabled = true;
      btn.classList.add('busy');
      if (label) {
        if (!btn.dataset.label) btn.dataset.label = btn.textContent;
        btn.textContent = label;
      }
    } else {
      btn.disabled = false;
      btn.classList.remove('busy');
      if (btn.dataset.label != null) {
        btn.textContent = btn.dataset.label;
        delete btn.dataset.label;
      }
    }
  }

  // WebView2 里 window.confirm 不一定弹得出来：用「再点一下」当确认
  function confirmTwice(btn, label, run) {
    let armed = false;
    let timer = null;
    function reset() {
      armed = false;
      if (btn.dataset.label) btn.textContent = btn.dataset.label;
      btn.classList.remove('armed');
    }
    btn.addEventListener('click', function () {
      if (!armed) {
        armed = true;
        if (!btn.dataset.label) btn.dataset.label = btn.textContent;
        btn.textContent = label;
        btn.classList.add('armed');
        timer = setTimeout(reset, 3200);
        return;
      }
      clearTimeout(timer);
      reset();
      run();
    });
  }

  function call(m, p) { return window.moss.call(m, p || {}); }

  // ─────────────────────────────────────────────── 表格

    /* 给定列定义，造表和行。列固定是「序号 / 包名 / …业务列… / 空白 / 操作」，
     空白那列吃掉剩余宽度。 */
  function makeTable(opts) {
    const box = el('section', 'grp');
    const h = el('h2', 'grp-title', opts.title || '');
    if (opts.count != null) h.appendChild(el('span', 'grp-count', opts.count));
    box.appendChild(h);

    const tbl = el('table', 'tbl');
    const thead = el('thead');
    const head = el('tr');
    head.appendChild(el('th', 'num', '#'));
    head.appendChild(el('th', 'nm', '包名'));
    opts.cols.forEach(function (c) { head.appendChild(el('th', c[1] || null, c[0])); });
    head.appendChild(el('th', 'gap'));
    head.appendChild(el('th', 'op'));
    thead.appendChild(head);
    tbl.appendChild(thead);

    const body = el('tbody');
    tbl.appendChild(body);
    box.appendChild(tbl);
    return { box: box, body: body };
  }

  function row(cells) {
    const tr = el('tr');
    cells.forEach(function (c) { tr.appendChild(c); });
    return tr;
  }

  function numCell(i) { return el('td', 'num', String(i)); }

  function nameCell(name, guarded, tag) {
    const td = el('td', 'nm', name);
    if (tag) td.appendChild(el('span', 'tag', tag));
    if (guarded) {
      const t = el('span', 'tag', '保护');
      t.title = '它是这套环境装东西的工具，不给卸';
      td.appendChild(t);
    }
    return td;
  }

  function verCell(oldV, newV) {
    const td = el('td', 'ver');
    if (newV == null) {
      td.textContent = oldV;
      return td;
    }
    td.appendChild(el('span', 'old', oldV));
    td.appendChild(el('span', 'to', '→'));
    td.appendChild(el('span', 'new', newV));
    return td;
  }

  function gapCell() { return el('td', 'gap'); }

  function opCell(buttons) {
    const td = el('td', 'op');
    buttons.forEach(function (b) {
      if (b) td.appendChild(b);
    });
    return td;
  }

  function emptyCard(title, text, actionLabel, action) {
    const box = el('section', 'grp');
    const st = el('div', 'state');
    if (title) st.appendChild(el('p', 'state-title', title));
    if (text) st.appendChild(el('p', 'state-text', text));
    if (actionLabel) {
      const b = el('button', 'btn ghost sm', actionLabel);
      b.addEventListener('click', action);
      st.appendChild(b);
    }
    box.appendChild(st);
    return box;
  }

  function skeletonCard(rows) {
    const box = el('section', 'grp');
    box.appendChild(el('div', 'sk-title'));
    for (let i = 0; i < (rows || 8); i++) {
      const r = el('div', 'sk-row');
      r.append(el('div', 'sk-bar n'), el('div', 'sk-bar'), el('div', 'sk-bar v'));
      box.appendChild(r);
    }
    return box;
  }

  // ─────────────────────────────────────────────── 环境

  /* 顶栏那条：两行文字 + 右侧一组版本信息，把整条右侧用满
     （早先挤在角落一个窄按钮里，路径都被截掉了）。 */
  function renderEnv() {
    const e = state.env;
    if (!e) return;
    const rt = e.runtime || {};

    $('#env-path').textContent = rt.site_packages || '';
    $('#env-path').title = rt.site_packages || '';

    const meta = $('#env-meta');
    meta.textContent = '';
    [
      ['Python', e.python_version],
      ['pip', (e.pip || {}).version || '未安装'],
      ['包', e.count == null ? '?' : String(e.count)],
    ].forEach(function (pair) {
      const s = el('span');
      s.appendChild(el('em', null, pair[0]));
      s.appendChild(el('strong', null, esc(pair[1])));
      meta.appendChild(s);
    });

    if (rt.multi) {
      const s = el('span');
      s.appendChild(el('em', null, '只动'));
      s.appendChild(el('strong', null, esc(rt.version_dir || '')));
      s.title = '多个版本并存（' + (rt.versions || []).join('、') + '），只动这一个';
      meta.appendChild(s);
    }

    $('#n-installed').textContent = e.count == null ? '' : e.count;
    renderSource();
  }

  // ─────────────────────────────────────────────── 环境清单

  /* 页头那个下拉：当前是哪一套 + 切到别的 + 加新的 + 删记录。
     自身那套永远排第一，带星标，不给删。 */
  function activeTarget() {
    const cur = state.env && state.env.runtime;
    const want = cur && cur.id;
    return state.targets.find(function (t) { return t.id === want; })
      || state.targets[0] || null;
  }

  function renderEnvPicker() {
    const t = activeTarget();
    $('#env-name').textContent = t ? t.label : '—';
    $('#env-star').hidden = !(t && t.own);
    $('#envbtn').title = t
      ? (t.path + (t.own ? '\n这是 moss 自身的运行时' : '') + '\n点开切换 / 添加环境')
      : '';

    const list = $('#env-list');
    list.textContent = '';
    state.targets.forEach(function (it) {
      const on = t && it.id === t.id;
      const row = el('button', 'menu-row' + (on ? ' on' : '')
        + (it.ok ? '' : ' bad'));
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', on ? 'true' : 'false');

      const nm = el('span', 'menu-name');
      if (it.own) {
        const s = el('span', 'star on');
        s.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.1l1.9 3.9 4.2.6-3 3 .7 4.3L8 11.8 4.2 13.9l.7-4.3-3-3 4.2-.6z"/></svg>';
        s.title = 'moss 自身的运行时';
        nm.appendChild(s);
      }
      nm.appendChild(document.createTextNode(it.label));
      row.appendChild(nm);
      row.appendChild(el('span', 'menu-path', it.ok ? it.path : (it.error || it.path)));

      const tick = el('span', 'menu-tick');
      if (on) tick.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.4 8.4l3 3 6.2-6.6"/></svg>';
      row.appendChild(tick);

      row.addEventListener('click', function () { useTarget(it); });

      const wrap = el('div', 'menu-item');
      wrap.appendChild(row);
      if (!it.own) {
        const del = el('button', 'menu-del', '移除');
        del.title = '只是从列表里去掉，硬盘上那个环境不动';
        confirmTwice(del, '确认移除', function () { removeTarget(it); });
        wrap.appendChild(del);
      }
      list.appendChild(wrap);
    });
  }

  async function loadTargets() {
    try {
      const got = await call('targets');
      state.targets = got.items || [];
      renderEnvPicker();
    } catch (e) {
      state.targets = [];
    }
  }

  async function useTarget(it) {
    closeMenu();
    if (!it.ok) {
      toast('这套环境用不了：' + (it.error || '找不到解释器'), true);
      return;
    }
    const cur = activeTarget();
    if (cur && cur.id === it.id) return;
    try {
      await call('use_env', { id: it.id });
      state.outdated = null;            // 换环境了，之前查的更新结果不作数
      $('#n-outdated').textContent = '';
      $('#btn-upgrade-all').disabled = true;
      await loadTargets();
      await loadEnv();
      toast('已切换到 ' + it.label);
    } catch (e) {
      toast('切不过去：' + e.message, true);
    }
  }

  async function addEnv(path) {
    if (!path) return;
    try {
      const got = await call('add_env', { path: path });
      await loadTargets();
      toast('已添加 ' + got.item.label + '，正在切过去…');
      await call('use_env', { id: got.item.id });
      await loadTargets();
      await loadEnv();
    } catch (e) {
      toast('加不进来：' + e.message, true);
    }
  }

  async function removeTarget(it) {
    try {
      await call('remove_env', { id: it.id });
      const cur = activeTarget();
      const wasCur = cur && cur.id === it.id;
      await loadTargets();
      if (wasCur) await loadEnv();
      toast('已从列表移除：' + it.label);
    } catch (e) {
      toast('移除不了：' + e.message, true);
    }
  }

  function openMenu() {
    $('#envmenu').hidden = false;
    $('#envbtn').setAttribute('aria-expanded', 'true');
    $('#envpick').classList.add('open');
  }
  function closeMenu() {
    $('#envmenu').hidden = true;
    $('#envbtn').setAttribute('aria-expanded', 'false');
    $('#envpick').classList.remove('open');
  }

  async function pickDir(title) {
    const got = await call('choose_dir', { title: title || '选一个目录' });
    if (got.ok) return got.path;
    if (!got.cancelled) toast(got.error || '选不了', true);
    return '';
  }

  /* env 一次就把环境和已装列表都带回来了 —— 启动只发一个请求。 */
  async function loadEnv() {
    try {
      const e = await call('env');
      state.env = e;
      if (Array.isArray(e.items)) {
        state.installed = e.items;
        renderInstalled();
      }
      renderEnv();
      return e;
    } catch (err) {
      $('#env-name').textContent = '读不出环境';
      $('#env-path').textContent = err.message;
      toast('读不出环境：' + err.message, true);
      return null;
    }
  }

  function renderSource() {
    const sel = $('#sel-source');
    const e = state.env || {};
    const cur = e.source || {};
    const list = e.sources || {};
    const keys = ['auto'].concat(Object.keys(list));
    if (sel.options.length !== keys.length) {
      sel.textContent = '';
      keys.forEach(function (k) {
        const o = document.createElement('option');
        o.value = k;
        o.textContent = k === 'auto' ? '源：pip.ini'
          : '源：' + ((list[k] || {}).name || k);
        sel.appendChild(o);
      });
    }
    sel.value = cur.use || 'auto';
    sel.title = cur.url ? (cur.name + '\n' + cur.url) : (cur.name || '');
  }

  // ─────────────────────────────────────────────── 已装

  function byName(a, b) {
    const x = String(a.name || '').toLowerCase();
    const y = String(b.name || '').toLowerCase();
    return x < y ? -1 : (x > y ? 1 : 0);
  }

  function renderInstalled() {
    const box = $('#list-installed');
    box.textContent = '';
    const f = state.filter.trim().toLowerCase();
    const all = state.installed.slice().sort(byName);
    const rows = f ? all.filter(function (r) {
      return (r.name || '').toLowerCase().indexOf(f) >= 0;
    }) : all;

    if (!rows.length) {
      box.appendChild(f
        ? emptyCard('没有对上的', '「' + f + '」在已装的 ' + all.length + ' 个包里找不到。')
        : emptyCard('这个环境还是空的', '去「装新包」里装第一个。'));
      return;
    }

    /* 按首字母分组：A 一张表、B 一张表。一屏分组比一条长龙好扫得多。 */
    const groups = new Map();
    rows.forEach(function (it) {
      const k = String(it.name || '?').charAt(0).toUpperCase();
      const key = /[A-Z]/.test(k) ? k : '#';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(it);
    });

    const frag = document.createDocumentFragment();
    groups.forEach(function (list, key) {
      const t = makeTable({
        title: key, count: list.length,
        cols: [['版本', 'ver']],
      });
      t.box.dataset.letter = key;   // 字母索引靠它找到这一组
      list.forEach(function (it, i) {
        const guarded = (it.name || '').toLowerCase() === 'pip';
        const up = el('button', 'act', '升级');
        up.addEventListener('click', function () { runJob('upgrade', [it.name], up); });
        const rm = el('button', 'act drop', '卸载');
        rm.disabled = guarded;
        confirmTwice(rm, '确认卸载', function () { runJob('uninstall', [it.name], rm); });
        t.body.appendChild(row([
          numCell(i + 1), nameCell(it.name, guarded), verCell(it.version),
          gapCell(), opCell([up, rm]),
        ]));
      });
      frag.appendChild(t.box);
    });
    box.appendChild(frag);

    renderLetters(Array.from(groups, function (pair) {
      return { key: pair[0], count: pair[1].length };
    }));
  }

  /* ── 首字母索引 ────────────────────────────────────────────────
     侧栏一列字母，点一下直接跳到那一组；滚动时自动高亮「当前这一屏
     是哪个字母」，于是它同时也是进度条 —— 不用一路滚下去找。 */
  let letterBoxes = [];
  let letterBtns = new Map();
  let lettersRaf = 0;

  function renderLetters(groups) {
    const wrap = $('#letters-wrap');
    const box = $('#letters');
    box.textContent = '';
    letterBtns = new Map();
    letterBoxes = [];

    const onInstalled = document.querySelector('.app').dataset.tab === 'installed';
    wrap.hidden = !(onInstalled && groups.length > 1);
    if (wrap.hidden) return;

    groups.forEach(function (g) {
      const b = el('button', 'letter');
      b.dataset.letter = g.key;
      b.appendChild(el('span', 'letter-ch', g.key));
      if (g.count > 1) b.appendChild(el('em', 'letter-n', String(g.count)));
      b.title = g.key + ' · ' + g.count + ' 个包';
      b.addEventListener('click', function () { jumpToLetter(g.key); });
      letterBtns.set(g.key, b);
      box.appendChild(b);
    });

    letterBoxes = $$('#list-installed .grp[data-letter]');
    syncLetterHighlight();
  }

  function jumpToLetter(key) {
    const stage = document.querySelector('.stage');
    const target = letterBoxes.find(function (b) { return b.dataset.letter === key; });
    if (!target) return;
    // 让这一组的顶边贴到滚动区顶边（留 8px 余量）
    const delta = target.getBoundingClientRect().top - stage.getBoundingClientRect().top;
    stage.scrollTo({ top: stage.scrollTop + delta - 8, behavior: 'smooth' });
    if (letterBtns.has(key)) letterBtns.get(key).classList.add('on');
  }

  /* 滚动时算出「最后一组已经越过顶边的」就是当前组，跟手机通讯录一个道理 */
  function syncLetterHighlight() {
    if (!letterBoxes.length) return;
    const stage = document.querySelector('.stage');
    const top = stage.getBoundingClientRect().top + 12;
    let cur = letterBoxes[0].dataset.letter;
    for (let i = 0; i < letterBoxes.length; i++) {
      if (letterBoxes[i].getBoundingClientRect().top <= top) {
        cur = letterBoxes[i].dataset.letter;
      } else break;
    }
    letterBtns.forEach(function (b, k) {
      b.classList.toggle('on', k === cur);
    });
  }

  function onStageScroll() {
    if (lettersRaf) return;
    lettersRaf = requestAnimationFrame(function () {
      lettersRaf = 0;
      syncLetterHighlight();
    });
  }

  async function loadInstalled() {
    const box = $('#list-installed');
    if (!state.installed.length) box.replaceChildren(skeletonCard(10));
    try {
      const got = await call('installed');
      state.installed = got.items || [];
      renderInstalled();
    } catch (e) {
      box.replaceChildren(emptyCard('读不出来', e.message));
    }
  }

  // ─────────────────────────────────────────────── 装新包

  async function webSearch(q) {
    try {
      const r = await call('web_search', { q: q || '' });
      if (!r.ok) toast(r.error || ('浏览器没起来：' + r.url), true);
      else toast('已在浏览器里打开');
    } catch (e) { toast(e.message, true); }
  }

  function renderFound() {
    const box = $('#list-search');
    box.textContent = '';
    const got = state.found;
    if (!got) return;

    const items = got.items || [];
    if (!items.length) {
      const miss = (got.missing || []).filter(Boolean);
      box.appendChild(emptyCard(
        'PyPI 上没有这个名字',
        (miss.length ? miss.join('、') + '。' : '') +
        '拼写对不对？不知道叫什么就去官方网页按关键词找。',
        '去网页搜', function () { webSearch(got.q); }));
      return;
    }

    $('#search-hint').textContent = '查到 ' + items.length + ' 个。';

    const t = makeTable({
      title: got.q ? '「' + got.q + '」' : '结果', count: items.length,
      cols: [['说明', 'desc'], ['版本', 'ver']],
    });
    items.forEach(function (it, i) {
      const desc = el('td', 'desc', it.summary || '—');
      desc.title = [it.summary, it.requires_python ? '需要 Python ' + it.requires_python : '']
        .filter(Boolean).join(' · ');
      const tag = it.installed
        ? (it.installed === it.version ? '已是最新' : '已装 ' + it.installed)
        : null;
      const btn = el('button', 'act', it.installed ? '重装' : '安装');
      btn.addEventListener('click', function () { runJob('install', [it.name], btn); });
      t.body.appendChild(row([
        numCell(i + 1), nameCell(it.name, false, tag), desc,
        verCell(it.version || ''), gapCell(), opCell([btn]),
      ]));
    });
    box.appendChild(t.box);
  }

  async function doLookup() {
    const q = $('#q').value.trim();
    const box = $('#list-search');
    if (!q) {
      box.textContent = '';
      state.found = null;
      $('#search-hint').textContent = '按名字精确查，走 pip 自己的索引。';
      return;
    }
    box.replaceChildren(skeletonCard(4));
    try {
      state.found = await call('lookup', { q: q });
      renderFound();
    } catch (e) {
      box.replaceChildren(emptyCard('查不到', e.message));
    }
  }

  // ─────────────────────────────────────────────── 可升级

  function renderOutdated() {
    const box = $('#list-outdated');
    box.textContent = '';
    const rows = state.outdated;

    if (rows === null) {
      box.replaceChildren(emptyCard(
        '还没查',
        '点「现在查」看有哪些包出了新版。查一次要连 PyPI 逐个比对，几十秒。'));
      return;
    }

    if (!rows.length) {
      box.replaceChildren(emptyCard(
        '全都是最新的', '这套环境里 ' + state.installed.length + ' 个包都不用动。'));
      return;
    }

    const t = makeTable({ title: '能升的包', count: rows.length, cols: [['版本', 'ver']] });
    rows.forEach(function (it, i) {
      const guarded = (it.name || '').toLowerCase() === 'pip';
      const b = el('button', 'act', '升级');
      b.addEventListener('click', function () { runJob('upgrade', [it.name], b); });
      t.body.appendChild(row([
        numCell(i + 1), nameCell(it.name, guarded), verCell(it.version, it.latest),
        gapCell(), opCell([b]),
      ]));
    });
    box.appendChild(t.box);
  }

  async function loadOutdated(btn) {
    const box = $('#list-outdated');
    box.replaceChildren(skeletonCard(6));
    busy(btn, true, '查着…');
    try {
      const got = await call('outdated');
      state.outdated = got.items || [];
      renderOutdated();
      $('#n-outdated').textContent = state.outdated.length || '';
      $('#n-outdated').classList.toggle('warn', state.outdated.length > 0);
      $('#btn-upgrade-all').disabled = !state.outdated.length;
      $('#outdated-hint').textContent = state.outdated.length
        ? '有 ' + state.outdated.length + ' 个包能升级。'
        : '全都是最新的。';
    } catch (e) {
      state.outdated = null;
      box.replaceChildren(emptyCard('查不出来', e.message,
        '再试一次', function () { loadOutdated(btn); }));
    } finally {
      busy(btn, false);
    }
  }

  // ─────────────────────────────────────────────── 任务

  function consoleLine(text) {
    const cls = /^!!/.test(text) ? 'e' : (/^\[完\]|^\[好\]/.test(text) ? 'o' : '');
    $('#console').appendChild(el('div', cls, text));
  }

  function openDrawer(title) {
    $('#drawer').hidden = false;
    $('#drawer-title').textContent = title || '任务';
    $('#console').textContent = '';
    $('#drawer-dot').className = 'dot';
    $('#drawer-state').textContent = '正在跑…';
  }

  async function runJob(action, names, btn) {
    busy(btn, true, '…');
    try {
      const got = await call('start', { action: action, names: names });
      openDrawer(got.label || action);
      state.job = got.job;
      pollJob(btn);
    } catch (e) {
      busy(btn, false);
      toast(e.message, true);
    }
  }

  function pollJob(btn) {
    clearTimeout(state.jobTimer);
    const jid = state.job;
    if (!jid) return;
    let seen = 0;

    const tick = async function () {
      let snap;
      try {
        snap = await call('job', { id: jid });
      } catch (e) {
        $('#drawer-state').textContent = '取不到进度：' + e.message;
        return;
      }
      if (snap.error) {
        $('#drawer-state').textContent = snap.error;
        return;
      }
      const lines = snap.lines || [];
      for (let i = seen; i < lines.length; i++) consoleLine(lines[i]);
      seen = lines.length;
      const box = $('#console');
      box.scrollTop = box.scrollHeight;

      if (snap.done) {
        if (btn) busy(btn, false);
        $('#drawer-dot').className = 'dot' + (snap.ok ? ' done' : ' fail');
        $('#drawer-state').textContent = (snap.ok ? '完成' : '失败') +
          ' · 退出码 ' + snap.rc + ' · ' + snap.elapsed + ' 秒';
        toast(snap.ok ? (snap.label + ' 完成') : (snap.label + ' 失败，看下方输出'), !snap.ok);
        state.job = null;
        refreshAfterJob();
        return;
      }
      $('#drawer-state').textContent = '正在跑… ' + snap.elapsed + ' 秒';
      state.jobTimer = setTimeout(tick, 600);
    };
    tick();
  }

  async function refreshAfterJob() {
    await loadEnv();                      // env 带列表，不用再单独问一遍
    if (state.outdated !== null) loadOutdated(null);
  }

  // ─────────────────────────────────────────────── 导出

  function showExportResult(got) {
    state.exportPath = got.path;
    $('#export-result').hidden = false;
    $('#export-path-out').textContent = got.path;
    $('#export-path-out').title = got.path;
    $('#export-meta').textContent = got.count + ' 行';
    $('#export-out').textContent = got.text;
  }

  async function doExport() {
    const btn = $('#btn-export');
    busy(btn, true, '导出中…');
    try {
      /* 给的是目录就往里放 requirements.txt；留空就落到插件数据目录 */
      const got = await call('export', { path: state.exportDir || '' });
      showExportResult(got);
      toast('已写 ' + got.count + ' 行到 ' + got.path);
    } catch (e) {
      toast('导出失败：' + e.message, true);
    } finally {
      busy(btn, false);
    }
  }

  function setExportDir(dir) {
    state.exportDir = dir || '';
    $('#export-path').value = state.exportDir;
    $('#export-path').title = state.exportDir;
  }

  async function doDeleteExport() {
    const btn = $('#btn-delete-export');
    if (!state.exportPath) return;
    busy(btn, true, '删除中…');
    try {
      const got = await call('delete_export', { path: state.exportPath });
      $('#export-result').hidden = true;
      $('#export-out').textContent = '';
      state.exportPath = '';
      toast(got.missing ? '文件本来就不在了' : '已删除 ' + got.path);
    } catch (e) {
      toast('删不掉：' + e.message, true);
    } finally {
      busy(btn, false);
    }
  }

  async function doCopy() {
    const text = $('#export-out').textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制 ' + text.split('\n').filter(Boolean).length + ' 行');
    } catch (e) {
      toast('复制不了，手动选中吧', true);
    }
  }

  // ─────────────────────────────────────────────── 绑定

  const TITLES = { installed: '已装包', search: '装新包', outdated: '可升级', export: '导出清单' };

  function switchTab(name) {
    document.querySelector('.app').dataset.tab = name;
    $('#page-title').textContent = TITLES[name] || 'Pip 管理器';
    $$('.tab').forEach(function (t) {
      const on = t.dataset.tab === name;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $$('.panel').forEach(function (p) {
      p.classList.toggle('on', p.id === 'panel-' + name);
    });
    // 字母索引只对「已装包」有意义，换页签就收起来
    $('#letters-wrap').hidden = !(name === 'installed' && letterBtns.size > 1);
    if (name === 'installed') syncLetterHighlight();
    if (name === 'search') setTimeout(function () { $('#q').focus(); }, 30);
  }

  function bind() {
    $$('.tab').forEach(function (t) {
      t.addEventListener('click', function () { switchTab(t.dataset.tab); });
    });

    $('#filter').addEventListener('input', function (e) {
      state.filter = e.target.value;
      renderInstalled();
    });

    // 滚动内容区时高亮「现在这一屏是哪个字母」
    document.querySelector('.stage').addEventListener('scroll', onStageScroll, { passive: true });
    window.addEventListener('resize', onStageScroll);

    $('#btn-env').addEventListener('click', async function () {
      const b = this;
      busy(b, true);
      await loadEnv();
      busy(b, false);
      toast('已刷新');
    });



    $('#lookup-form').addEventListener('submit', function (e) {
      e.preventDefault();
      doLookup();
    });
    $('#export-path').addEventListener('input', function (e) {
      state.exportDir = e.target.value.trim();
    });
    $('#btn-web').addEventListener('click', function () {
      webSearch($('#q').value.trim());
    });

    $('#btn-check').addEventListener('click', function () {
      switchTab('outdated');
      loadOutdated($('#btn-outdated'));
    });
    $('#btn-outdated').title =
      '一次性交给 pip：一条 pip list --outdated，它自己并发问 PyPI，' +
      '不是我们逐个包去查';
    $('#btn-outdated').addEventListener('click', function () { loadOutdated(this); });

    confirmTwice($('#btn-upgrade-all'), '确认全部升级', function () {
      runJob('upgrade-all', [], $('#btn-upgrade-all'));
    });

    $('#btn-export').addEventListener('click', doExport);
    $('#btn-pick-export').addEventListener('click', async function () {
      const p = await pickDir('选一个放 requirements.txt 的目录');
      if (p) setExportDir(p);
    });
    $('#btn-copy').addEventListener('click', doCopy);
    confirmTwice($('#btn-delete-export'), '确认删除', doDeleteExport);

    // ── 环境：下拉、添加、打开目录
    $('#envbtn').addEventListener('click', function (e) {
      e.stopPropagation();
      if ($('#envmenu').hidden) { renderEnvPicker(); openMenu(); } else closeMenu();
    });
    $('#envmenu').addEventListener('click', function (e) { e.stopPropagation(); });
    document.addEventListener('click', closeMenu);

    $('#btn-add-env').addEventListener('click', async function () {
      const p = await pickDir('选一个虚拟环境目录（venv / conda / Python 安装目录都行）');
      if (p) addEnv(p);
    });
    $('#btn-open-env').addEventListener('click', async function () {
      const t = activeTarget();
      closeMenu();
      const r = await call('open_path', { path: (t && t.path) || '' });
      if (!r.ok) toast(r.error || '打不开', true);
    });

    // ── 拖放：拖一个文件夹进来 = 加一套环境（在「导出清单」页 = 选导出目录）
    // 真路径只有宿主拿得到（Chromium 不给页面 File.path），所以路径一律走
    // moss.on('drop')，页面自己的 drop 事件只用来兜底提示。
    let captured = false;
    const hasFiles = function (e) {
      return !!(e.dataTransfer && (e.dataTransfer.types || []) &&
        Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0);
    };
    function showHint() { $('#dropzone').classList.add('on'); }
    function hideHint() { $('#dropzone').classList.remove('on'); }

    window.addEventListener('dragover', function (e) {
      if (hasFiles(e)) { e.preventDefault(); showHint(); }
    });
    window.addEventListener('dragenter', function (e) {
      if (hasFiles(e)) e.preventDefault();
    });
    window.addEventListener('dragleave', function (e) {
      // 宿主铺了罩子之后会收到一次假 dragleave，别信它
      if (!captured && e.relatedTarget === null) hideHint();
    });
    window.addEventListener('dragend', function () {
      captured = false;
      hideHint();
    });
    window.addEventListener('blur', function () {
      captured = false;
      hideHint();
    });

    function useDropped(paths) {
      hideHint();
      const p = (paths || [])[0];
      if (!p) return;
      if (document.querySelector('.app').dataset.tab === 'export') {
        setExportDir(p);
        toast('导出目录：' + p);
        return;
      }
      addEnv(p);
    }

    // 内嵌这条路：三件事都听宿主的（captured → 松手 dragend → drop）
    try {
      window.moss.on('captured', function () { captured = true; });
      window.moss.on('dragend', function () { captured = false; hideHint(); });
      window.moss.on('drop', function (d) { useDropped((d && d.items) || []); });
    } catch (e) {
      // 老宿主没有这几个事件：拖放就用不了，选目录那条路照常
    }

    $('#btn-close-drawer').addEventListener('click', function () {
      $('#drawer').hidden = true;
      clearTimeout(state.jobTimer);
    });

    $('#sel-source').addEventListener('change', async function () {
      const sel = this;
      sel.classList.add('busy');
      try {
        const got = await call('source', { use: sel.value });
        toast('装包源：' + got.source.name);
      } catch (e) {
        toast('切不了：' + e.message, true);
      } finally {
        sel.classList.remove('busy');
        await loadEnv();
      }
    });

    window.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') $('#drawer').hidden = true;
    });
  }

  // ─────────────────────────────────────────────── 启动

  window.moss.on('ready', function () {
    bind();
    loadTargets();      // 先把环境清单读出来，「当前是哪一套」才有名字可显示
    loadEnv();          // 列表跟着 env 一起回来，不用再单独问一遍
  });

  /* loadInstalled 留着给「装完之后不想重问 env」的场景用，暂时没绑上去 */
  void loadInstalled;
})();
