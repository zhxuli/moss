(function () {
  'use strict';

  var PAT = /(?:[A-Za-z]:[\\/]|\\\\|user_data[\\/]|system[\\/])[^\s"'<>|?*，。；：！？、　]+/g;

  var SENT_TAIL = /[.,;:!?，。；：！？、"'\u2018\u2019\u201c\u201d]+$/;

  var EXT_TAIL = /\.[A-Za-z0-9]{1,5}$/;
  var PAIR = { ')': '(', '）': '（', ']': '[', '】': '【' };

  function cutTailGroup(s) {
    var open = PAIR[s.charAt(s.length - 1)];
    if (!open) return s;
    var i = s.lastIndexOf(open, s.length - 2);
    if (i <= 0) return s;
    var before = s.slice(0, i);
    return EXT_TAIL.test(before) ? before : s;
  }

  var ICON_DIR =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>' +
    '</svg>';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function trimTail(raw) {
    var s = String(raw);
    var depth = 0, cut = -1, i, c;
    for (i = s.length - 1; i >= 0; i--) {
      c = s.charAt(i);
      if (c === ')' || c === '）' || c === ']' || c === '】') depth++;
      else if (c === '(' || c === '（' || c === '[' || c === '【') {
        if (depth > 0) depth--;
        else { cut = i; break; }
      }
    }
    if (cut >= 0) s = s.slice(0, cut);
    else if (depth > 0) s = s.slice(0, s.length - depth);
    for (i = 0; i < 4; i++) {                           
      c = cutTailGroup(s);
      if (c === s) break;
      s = c;
    }
    return s.replace(SENT_TAIL, '');
  }

  function toFileUrl(p) {
    var s = String(p).replace(/\\/g, '/');
    var unc = s.slice(0, 2) === '//';
    if (!unc && !/^[A-Za-z]:\//.test(s)) return '';
    var body = s.split('/').map(function (x) {
      return encodeURIComponent(x).replace(/%3A/gi, ':');        
    }).join('/');
    return unc ? 'file:' + body : 'file:///' + body;
  }

  function linkify(text) {
    text = String(text == null ? '' : text);
    var out = '', last = 0, m;
    PAT.lastIndex = 0;
    while ((m = PAT.exec(text)) !== null) {
      var p = trimTail(m[0]);
      if (!p) continue;
      var enc = encodeURIComponent(p);
      var url = toFileUrl(p);

      var dat = ' data-p="' + enc + '" data-r="' + encodeURIComponent(m[0]) + '"';
      out += esc(text.slice(last, m.index));
      out += '<a class="plink" role="link" tabindex="0"' + dat + ' data-act="open"' +
             (url ? ' href="' + esc(url) + '"' : '') +
             ' title="直接打开：' + esc(p) + '">' + esc(p) + '</a>';
      out += '<button type="button" class="plink-dir"' + dat + ' data-act="reveal"' +
             ' title="在资源管理器里打开它所在的文件夹：' + esc(p) + '"' +
             ' aria-label="打开所在文件夹">' + ICON_DIR + '</button>';
      last = m.index + p.length;
    }
    out += esc(text.slice(last));
    return out;
  }

  function fire(el) {
    var p = '', r = '';
    try { p = decodeURIComponent(el.getAttribute('data-p') || ''); } catch (e) { p = ''; }
    try { r = decodeURIComponent(el.getAttribute('data-r') || ''); } catch (e) { r = ''; }
    if (!p || !window.SKILL_API) return;
    var how = el.getAttribute('data-act') === 'reveal' ? 'reveal' : 'open';
    window.SKILL_API.openPath(p, how, r).then(function (res) {
      if (res && res.ok === false && window.__skillToast) window.__skillToast(res.msg || '打不开', 'bad');
    }).catch(function () {  });
  }

  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest && ev.target.closest('.plink, .plink-dir');
    if (!el) return;
    ev.preventDefault();
    fire(el);
  });

  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var el = ev.target && ev.target.closest && ev.target.closest('a.plink');
    if (!el) return;
    ev.preventDefault();
    fire(el);
  });

  window.SKILL_PATHS = { linkify: linkify };
})();
