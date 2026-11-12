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
      sheet: function (s) { this.val = (s && s.input) || ''; },
    },
    mounted: function () {
      var self = this;

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
