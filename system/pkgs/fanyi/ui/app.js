/* 快捷翻译工具 —— 界面逻辑（原生 JS）。
   ★ 这里不做翻译/缓存/热键，那些全在 Python（main.py）。本文件只干两件事：
     ① 把后端推来的 `hotkey` 事件翻译成微型步骤条 / 日志 / 焦点卡片 / 历史；
     ② 顶部状态（可点击）调 `hotkey_start` / `hotkey_stop`。
   垫片（moss-embed.js）保证内嵌和独立窗口两种环境下这段代码一模一样。 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var EMBEDDED = !!(window.moss && window.moss.env.embedded);

  var statusEl = $('status'), statusDot = $('statusDot'), statusText = $('statusText');
  var sourceBox = $('source-box'), targetBox = $('target-box');
  var historyList = $('history-list'), historyTitle = $('history-title');
  var historyClear = $('history-clear'), keepSwitch = $('keep-switch');
  var consoleEl = $('console'), langIndicator = $('lang-indicator');
  var steps = [1, 2, 3, 4].map(function (i) { return $('step-' + i); });
  var dividers = [1, 2, 3].map(function (i) { return $('div-' + i); });

  var LANG = { auto: '自动', 'zh-CN': '中文', zh: '中文', 'zh-TW': '繁中', en: '英文',
               ja: '日文', ko: '韩文', fr: '法文', de: '德文', es: '西语', ru: '俄语' };
  function langName(c) {
    c = String(c || 'auto');
    return LANG[c] || c.split('-')[0].toUpperCase() || '自动';
  }

  var running = false;

  /* ---------------------------------------------------------------- 视图更新 */
  function setRunning(on) {
    running = !!on;
    statusDot.className = 'status-dot' + (running ? ' running' : '');
    statusText.textContent = running ? '正在监听' : '已停止';
    statusText.style.color = running ? 'var(--success)' : 'var(--text-muted)';
  }

  function setStep(current) {
    for (var i = 1; i <= 4; i++) {
      var el = steps[i - 1];
      var icon = el.querySelector('.step-icon');
      if (i < current) {
        el.className = 'step-item done';
        icon.innerHTML = '✓';
      } else if (i === current) {
        el.className = 'step-item active';
        icon.innerHTML = i;
      } else {
        el.className = 'step-item';
        icon.innerHTML = i;
      }
      var div = dividers[i - 1];
      if (div) div.className = 'step-divider' + (i < current ? ' done' : '');
    }
  }
  function resetStep() { setStep(0); }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  var SKELETON = '<div class="skeleton-text"></div>'
               + '<div class="skeleton-text"></div>'
               + '<div class="skeleton-text short"></div>';

  function log(tag, msg) {
    var line = document.createElement('div');
    line.className = 'log-line';
    line.innerHTML = '<span class="tag ' + tag.toLowerCase() + '">[' + tag + ']</span> '
                   + escapeHtml(msg);
    consoleEl.appendChild(line);
    while (consoleEl.childElementCount > 200) consoleEl.removeChild(consoleEl.firstChild);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function idleTask() {
    targetBox.style.display = 'none';
    targetBox.textContent = '';
    sourceBox.innerHTML = '<div class="empty-hint">请选中文本后双击 Ctrl 键，等待任务触发...</div>';
    langIndicator.innerHTML = '自动检测 &rarr; 英文';
  }

  function addHistory(source, target, targetLang) {
    var item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = '<div class="history-source">' + escapeHtml(source) + '</div>'
                   + '<div class="history-target">' + escapeHtml(target) + '</div>';
    item.title = '点击复制译文';
    item.addEventListener('click', function () {
      window.moss.call('copy', { text: target }).then(function () {
        log('OK', '已复制译文到剪贴板');
      }).catch(function () {});
    });

    /* 单条删除：这条历史对应的缓存也一起删（重启不会再冒出来）。
       ★ 按 (原文, 目标语言) 定位 —— 后端就是照这个找缓存的。 */
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'history-del';
    del.textContent = '×';
    del.title = '删除这条历史（连带它的缓存）';
    del.addEventListener('click', function (e) {
      e.stopPropagation();                 // 别触发外层的"点击复制"
      del.disabled = true;
      window.moss.call('history_remove', { src: source, target: targetLang || '' })
        .then(function (r) {
          refresh(r);
          log('SYS', '已删除 1 条历史记录');
        })
        .catch(function (err) {
          del.disabled = false;
          log('SYS', '删除失败：' + err.message);
        });
    });
    item.appendChild(del);

    historyList.insertBefore(item, historyList.firstChild);
    while (historyList.childElementCount > 50) historyList.removeChild(historyList.lastChild);
  }

  function renderHistory(items) {
    historyList.innerHTML = '';
    if (!items || !items.length) {
      var hint = document.createElement('div');
      hint.className = 'history-empty';
      hint.textContent = '还没有历史记录';
      historyList.appendChild(hint);
      return;
    }
    /* ★ 倒着插：addHistory 是往最上面插的（新发生的排最前），
       后端给的顺序本来就是"新的在前"，照原序插会把列表整个翻过来。
       倒序插一遍 → 页面上就是后端给的顺序（最新的在最上面）。 */
    items.slice().reverse().forEach(function (h) { addHistory(h.src, h.dst, h.target); });
  }

  /* 后端每个"改历史"的方法都回一份现成载荷 → 这里一处收口刷新界面 */
  function refresh(r) {
    if (!r || !r.ok) return;
    renderHistory(r.history);
    if (typeof r.count === 'number') {
      historyTitle.textContent = '历史记录 (共 ' + r.count + ' 条)';
    }
    if (typeof r.keep === 'boolean') setKeep(r.keep);
  }

  function setKeep(on) {
    keepSwitch.classList.toggle('on', !!on);
    keepSwitch.title = on
      ? '当前：保留历史记录（点一下 → 不保留）'
      : '当前：不保留历史记录（点一下 → 保留）';
  }

  /* ---------------------------------------------------------------- 交互 */
  function toggle() {
    var method = running ? 'hotkey_stop' : 'hotkey_start';
    window.moss.call(method, {}).then(function (r) {
      if (r) { setRunning(r.running); log('SYS', r.msg || ''); }
    }).catch(function (e) { log('SYS', '热键操作失败：' + e.message); });
  }
  statusEl.addEventListener('click', toggle);

  /* 清空全部历史：点第一次只是"上膛"，3 秒内再点一次才真删
     （★ 不用 confirm —— 内嵌 iframe 里 confirm 可能被挡，点了没反应） */
  var armedAt = 0;
  function disarmClear() {
    armedAt = 0;
    historyClear.textContent = '清空';
    historyClear.classList.remove('armed');
  }
  if (historyClear) {
    historyClear.addEventListener('click', function () {
      var now = Date.now();
      if (!armedAt || now - armedAt > 3000) {
        armedAt = now;
        historyClear.textContent = '再点一次确认';
        historyClear.classList.add('armed');
        setTimeout(function () { if (armedAt && Date.now() - armedAt >= 3000) disarmClear(); }, 3200);
        return;
      }
      disarmClear();
      window.moss.call('cache_clear', {}).then(function (r) {
        refresh(r);
        log('SYS', '已清空历史记录（' + ((r && r.removed) || 0) + ' 条，缓存一起删了）');
      }).catch(function (e) { log('SYS', '清空失败：' + e.message); });
    });
  }

  /* 保留历史：开 = 翻译完记历史（也能命中缓存）；关 = 新翻译不落盘、每次都联网翻 */
  if (keepSwitch) {
    keepSwitch.addEventListener('click', function () {
      var next = !keepSwitch.classList.contains('on');
      setKeep(next);
      window.moss.call('keep_history', { on: next }).then(function (r) {
        refresh(r);
        log('SYS', next ? '已开启：翻译结果会记进历史（同样的句子走缓存）'
                        : '已关闭：新翻译不再记入历史（每次都重新联网翻）');
      }).catch(function (e) {
        setKeep(!next);
        log('SYS', '切换失败：' + e.message);
      });
    });
  }

  /* 左右拖动分隔线：调整右侧面板宽度（左侧自适应） */
  (function initSplitter() {
    var main = document.querySelector('.main-content');
    var right = $('right-panel');
    var bar = $('splitter');
    if (!main || !right || !bar) return;
    var MIN_LEFT = 240, MIN_RIGHT = 160, drag = false;
    bar.addEventListener('mousedown', function (e) {
      drag = true;
      bar.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!drag) return;
      var r = main.getBoundingClientRect();
      var w = r.right - e.clientX;                 // 右栏 = 指针到右边缘的距离
      if (r.width - w < MIN_LEFT) w = r.width - MIN_LEFT;
      if (w < MIN_RIGHT) w = MIN_RIGHT;
      right.style.flexBasis = w + 'px';
    });
    window.addEventListener('mouseup', function () {
      if (!drag) return;
      drag = false;
      bar.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  })();

  /* ---------------------------------------------------------------- 后端事件 */
  window.moss.on('hotkey', function (d) {
    if (!d) return;

    if (d.phase === 'state') {
      setRunning(d.running);
      if (d.text) log('SYS', d.text);
      return;
    }

    if (d.phase === 'step') {
      if (d.step === 1) {
        setStep(1);
        targetBox.style.display = 'none';
        targetBox.textContent = '';
        sourceBox.innerHTML = '<div class="empty-hint">读取中...</div>';
        log('INFO', '检测到双击，提取剪贴板文本...');
      } else if (d.step === 2) {
        setStep(2);
        if (d.source_text != null) sourceBox.textContent = d.source_text;
        targetBox.style.display = 'block';
        targetBox.innerHTML = SKELETON;
        log('NET', '调用翻译 API...');
      } else if (d.step === 3) {
        setStep(3);
        if (d.translated != null) targetBox.textContent = d.translated;
        log('INFO', '翻译完成，准备回填剪贴板。');
      }
      return;
    }

    if (d.phase === 'done') {
      var res = d.result || {};
      setStep(4);
      if (res.original != null) sourceBox.textContent = res.original;
      targetBox.style.display = 'block';
      targetBox.textContent = res.translated || d.text || '';
      langIndicator.textContent = langName(res.source) + ' → ' + langName(res.target);
      log('OK', '粘贴成功！' + (res.provider_name ? '（' + res.provider_name + '）' : '') + '任务结束。');
      if (keepSwitch && !keepSwitch.classList.contains('on')) {
        log('INFO', '「不保留历史」已开启：这条结果没记进历史。');
      } else {
        addHistory(res.original || '', res.translated || d.text || '', res.target);
      }
      setTimeout(resetStep, 2500);
      return;
    }

    if (d.phase === 'fail') {
      log('NET', '失败：' + (d.text || ''));
      if (targetBox.style.display !== 'none' && targetBox.querySelector('.skeleton-text')) {
        targetBox.textContent = '翻译失败';
      }
      setTimeout(resetStep, 1500);
    }
  });

  /* ---------------------------------------------------------------- 初始化 */
  (function init() {
    resetStep();
    try {
      window.moss.call('hotkey_status', {}).then(function (h) {
        if (h) setRunning(h.running);
      }).catch(function () {});
    } catch (e) { /* 无妨 */ }
    try {
      window.moss.call('cache_info', {}).then(function (c) {
        if (!c || !c.ok) return;
        refresh(c);                       // 历史列表 + 条数 + 开关状态，一次画好
        if (c.keep === false) log('SYS', '当前是「不保留历史」：新翻译不会记进历史');
      }).catch(function () {});
    } catch (e) { /* 无妨 */ }
    window.moss.on('ready', function () {
      EMBEDDED = !!(window.moss && window.moss.env.embedded);
    });
    log('SYS', EMBEDDED ? '已内嵌进 moss，等待操作...' : '独立窗口模式，等待操作...');
  })();
})();
