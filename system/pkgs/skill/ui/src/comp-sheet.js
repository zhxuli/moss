/* comp-sheet.js —— 自己画的确认框（居中弹层）
   ============================================================================
   ★ 为什么不用 `window.confirm`：内嵌在 moss 的 iframe 里时它可能被宿主挡掉
     （老版 `app.js` 顶上那句注释就是这么写的）—— 所以确认框得自己画。
   ★ 它只管"摆出来 + 收回去"：按哪个键、要什么数据，都由根组件给（`sheet`）。
     三种用法：确认（删除）、确认 + 一个输入框（转插件的新 id）、纯提示。
   ========================================================================== */
(function () {
  'use strict';

  var I = window.SKILL_ICONS;

  window.SKILL_COMPONENTS = window.SKILL_COMPONENTS || {};
  window.SKILL_COMPONENTS.ConfirmSheet = {
    name: 'confirm-sheet',
    props: {
      sheet: { type: Object, default: null },
      closing: { type: Boolean, default: false },
    },
    emits: ['ok', 'cancel'],
    data: function () {
      return { val: '' };
    },
    computed: {
      hasInput: function () { return !!(this.sheet && this.sheet.input !== undefined); },
      danger: function () { return !!(this.sheet && this.sheet.danger); },
    },
    watch: {
      /* 每次换一张单子，把输入框重置成它给的那个初值 */
      sheet: function (s) { this.val = (s && s.input) || ''; },
    },
    mounted: function () {
      var self = this;
      /* 让键盘直接落在该落的地方：有输入框就落进去，没有就落「确定」 */
      this.$nextTick(function () {
        if (self.hasInput && self.$refs.inp) { self.$refs.inp.focus(); self.$refs.inp.select(); }
        else if (self.$refs.ok) { self.$refs.ok.focus(); }
      });
    },
    methods: { ico: I.of, fil: I.fill },
    template: [
      '<div class="sheet-wrap">',
      '  <div class="scrim" @click="$emit(\'cancel\')"></div>',
      '  <div class="sheet" role="dialog" aria-modal="true">',
      '    <h3>{{ sheet.title }}</h3>',
      '    <div class="mbody" v-html="sheet.body"></div>',
      '    <template v-if="hasInput">',
      '      <label for="m-input">{{ sheet.label || \'新 id（小写字母开头，只用小写字母/数字/_/-）\' }}</label>',
      '      <input id="m-input" ref="inp" type="text" spellcheck="false" autocomplete="off"',
      '             v-model="val" @keydown.enter.prevent="$emit(\'ok\', val)">',
      '      <p class="hint" v-if="sheet.hint">{{ sheet.hint }}</p>',
      '    </template>',
      '    <div class="mfoot">',
      '      <button type="button" class="btn" id="m-cancel" @click="$emit(\'cancel\')">取消</button>',
      '      <button type="button" class="btn" :class="danger ? \'danger\' : \'ink\'" id="m-ok"',
      '              ref="ok" @click="$emit(\'ok\', val)">',
      '        <span v-html="fil(danger ? \'warn\' : \'check\')"></span>{{ sheet.ok || \'确定\' }}',
      '      </button>',
      '    </div>',
      '  </div>',
      '</div>',
    ].join('\n'),
  };
})();
