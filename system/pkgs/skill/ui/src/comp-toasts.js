/* comp-toasts.js —— 提示条（Toast）
   ============================================================================
   ★ 一次只干一件事：把 `toasts` 画在底部居中，下边那条细线是倒计时
     （`--toast-ms` 由根组件按存活时长给，两边用的是同一个数）。
   ========================================================================== */
(function () {
  'use strict';

  var I = window.SKILL_ICONS;

  window.SKILL_COMPONENTS = window.SKILL_COMPONENTS || {};
  window.SKILL_COMPONENTS.SkillToasts = {
    name: 'skill-toasts',
    props: { toasts: { type: Array, default: function () { return []; } } },
    methods: {
      ico: I.of,
      fil: I.fill,
      /* 长句子多停一会儿（读得完），短句子 2.6 秒就够 */
      ms: function (t) { return Math.min(5200, 1900 + String(t.text || '').length * 55); },
      cls: function (t) { return 'toast ' + (t.kind || 'ok') + (t.closing ? ' out' : ''); },
      ic: function (t) {
        if (t.kind === 'bad') return this.fil('warn');
        if (t.kind === 'info') return this.fil('info');
        return this.fil('check');
      },
    },
    template: [
      '<div class="toasts" role="status" aria-live="polite">',
      '  <div v-for="t in toasts" :key="t.id" :class="cls(t)"',
      '       :style="{ \'--toast-ms\': ms(t) + \'ms\' }">',
      '    <span v-html="ic(t)"></span>',
      '    <span>{{ t.text }}</span>',
      '    <span class="bar"></span>',
      '  </div>',
      '</div>',
    ].join('\n'),
  };
})();
