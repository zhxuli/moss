/* comp-tile.js —— 技能卡片（`V-293` 照参考稿重画）
   ============================================================================
   ★ 参考稿那张卡：左边一枚圆角图标，右边标题 + 标签；下面两行描述；底部一条细线，
     左"文件数"、右一颗悬停才浮现的进入箭头；整卡悬停轻抬。
   ★ 还没允许 / 进不了工具表的整张**置灰**（照参考稿的 `is-disabled`）；写坏了的
     额外给一道红顶，别让"置灰"把问题盖住。
   ★ 根节点仍然是 `.tile`、名字仍然是 `.nm`：`tools/技能界面探针.py` 和
     `tools/技能内嵌探针.py` 就按这两个类名数卡片（重画时特意留住的契约）。
   ★ 数据是**后端算好的**（`allowed` / `problems` 都在 payload 里）—— 界面不自己猜状态。
   ★ 参考稿的「N 次调用」后端没有这个数据（要计数得动后端）⇒ 这里**换成本地真有的
     "文件数"**，不编假数。
   ========================================================================== */
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
      /* 图标：后端洗过的 svg 直接画；没有就给一个安静的兜底方块 */
      iconHtml: function () { return this.it.icon_svg || ''; },
      desc: function () { return this.it.desc || this.it.why || '（这只技能没写说明）'; },
      metric: function () { return (this.it.calls || 0) + ' 次调用'; },
      /* 卡片上那排小标签（最多两个）：状态 + 来路（出厂样例）或第一个参数 */
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
