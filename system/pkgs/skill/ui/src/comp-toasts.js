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
