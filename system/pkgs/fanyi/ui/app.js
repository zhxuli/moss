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
  var historyList = $('history-list'), historyHeader = $('history-header');
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

  function addHistory(source, target) {
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
    historyList.insertBefore(item, historyList.firstChild);
    while (historyList.childElementCount > 50) historyList.removeChild(historyList.lastChild);
  }

  function renderHistory(items) {
    historyList.innerHTML = '';
    (items || []).forEach(function (h) { addHistory(h.src, h.dst); });
  }

  /* ---------------------------------------------------------------- 交互 */
  function toggle() {
    var method = running ? 'hotkey_stop' : 'hotkey_start';
    window.moss.call(method, {}).then(function (r) {
      if (r) { setRunning(r.running); log('SYS', r.msg || ''); }
    }).catch(function (e) { log('SYS', '热键操作失败：' + e.message); });
  }
  statusEl.addEventListener('click', toggle);

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
      log('OK', '粘贴成功！任务结束。');
      addHistory(res.original || '', res.translated || d.text || '');
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
        if (c && c.ok) {
          renderHistory(c.history);
          if (typeof c.count === 'number') {
            historyHeader.textContent = '历史记录 (共 ' + c.count + ' 条)';
          }
        }
      }).catch(function () {});
    } catch (e) { /* 无妨 */ }
    window.moss.on('ready', function () {
      EMBEDDED = !!(window.moss && window.moss.env.embedded);
    });
    log('SYS', EMBEDDED ? '已内嵌进 moss，等待操作...' : '独立窗口模式，等待操作...');
  })();
})();
