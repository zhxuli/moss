(function () {
  'use strict';

  var I = window.SKILL_ICONS;

  window.SKILL_COMPONENTS = window.SKILL_COMPONENTS || {};
  window.SKILL_COMPONENTS.SkillTile = {
    name: 'skill-tile',
    props: {
      it: { type: Object, required: true },
      open: { type: Boolean, default: false },
    },
    emits: ['open'],
    computed: {
      broken: function () { return !!(this.it.problems && this.it.problems.length); },
      pending: function () { return !this.broken && !this.it.allowed; },
      label: function () {
        if (this.broken) return '要修一下';
        if (this.pending) return '等你允许';
        if ((this.it.warns || []).length) return '能用 · 有提醒';
        return '可以用';
      },

      iconHtml: function () { return this.it.icon_svg || ''; },
      desc: function () { return this.it.desc || this.it.why || '（这只技能没写说明）'; },
      metric: function () { return (this.it.calls || 0) + ' 次调用'; },

      tags: function () {
        var t = [], it = this.it;
        if (this.broken) t.push({ label: '要修', tone: 'bad' });
        else if (this.pending) t.push({ label: '等待允许', tone: 'warn' });
        else t.push({ label: '可用', tone: 'ok' });
        if (it.origin === 'seed') t.push({ label: '出厂样例', tone: 'violet' });
        else if ((it.params || []).length) t.push({ label: it.params[0], tone: 'plain' });
        return t;
      },
    },
    methods: {
      ico: I.of,
    },
    template: [
      '<button type="button" class="tile" :class="{ \'is-disabled\': !it.allowed, \'is-broken\': broken, \'is-open\': open }"',
      '        :title="it.name + \'（\' + label + \'）\'"',
      '        :aria-label="it.name + \'（\' + label + \'）\'" @click="$emit(\'open\')">',
      '  <span class="card-header">',
      '    <span class="skill-icon-wrap">',
      '      <span v-if="iconHtml" v-html="iconHtml"></span>',
      '      <span v-else class="icon-fallback" v-html="ico(\'spark\')"></span>',
      '    </span>',
      '    <span class="card-head-text">',
      '      <span class="nm">{{ it.name }}</span>',
      '      <span class="tag-list">',
      '        <span class="tag" :class="t.tone" v-for="t in tags" :key="t.label">{{ t.label }}</span>',
      '      </span>',
      '    </span>',
      '  </span>',
      '  <span class="skill-desc">{{ desc }}</span>',
      '  <span class="card-footer">',
      '    <span class="metric"><span v-html="ico(\'fire\')"></span>{{ metric }}</span>',
      '    <span class="enter-arrow" aria-hidden="true" v-html="ico(\'arrowRight\')"></span>',
      '  </span>',
      '</button>',
    ].join('\n'),
  };
})();
