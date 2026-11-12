(function () {
  var Vue = window.Vue, FV = window.FV, U = FV.util;
  if (!Vue) return;

  var ProgressBar = {
    name: "ProgressBar",
    props: { state: Object, dark: Boolean, indeterminate: Boolean },
    computed: {
      pct: function () {
        var state = this.state || {};
        if (!state.total) return 0;
        return Math.round(Math.min(1, state.loaded / state.total) * 100);
      },
      unknown: function () {
        var state = this.state || {};
        return this.indeterminate === true || !state.total;
      }
    },
    template:
      '<div class="progress" :class="{ dark: dark }" :data-indeterminate="unknown ? \'yes\' : null">' +
      '<div class="fill" :style="unknown ? null : { width: pct + \'%\' }"></div>' +
      "</div>"
  };

  FV.loadStatsText = function (state) {
    if (!state) return "";
    var parts = [];
    if (state.total) parts.push(U.humanBytes(state.loaded || 0) + " / " + U.humanBytes(state.total));
    else if (state.loaded) parts.push("已读取 " + U.humanBytes(state.loaded));
    if (state.speed) parts.push(U.humanRate(state.speed));
    if (state.eta !== null && state.eta !== undefined) parts.push("剩余 " + U.humanEta(state.eta));
    return parts.join(" · ");
  };
  var LoadStats = {
    name: "LoadStats",
    props: { state: Object, dark: Boolean },
    computed: { text: function () { return FV.loadStatsText(this.state); } },
    template: '<div class="pstats" :class="{ dark: dark }">{{ text }}</div>'
  };

  var LoadingPanel = {
    name: "LoadingPanel",
    components: { ProgressBar: ProgressBar, LoadStats: LoadStats },
    props: {
      title: String,
      state: Object,
      cancel: Function,
      cancelLabel: { type: String, default: "取消读取" },
      dark: Boolean,
      icon: String,
      variant: { type: String, default: "card" },
      indeterminate: Boolean
    },
    template:
      '<div v-if="variant === \'inline\'" class="load-inline" :class="{ dark: dark }">' +
      "<progress-bar :state=\"state\" :dark=\"dark\" :indeterminate=\"indeterminate\"></progress-bar>" +
      "<load-stats :state=\"state\" :dark=\"dark\"></load-stats>" +
      "</div>" +
      '<div v-else class="card" :class="{ dark: dark }">' +
      '<span class="mark" v-if="icon" v-html="svg"></span>' +
      '<span class="spinner" v-else></span>' +
      '<div class="ttl" v-if="title">{{ title }}</div>' +
      "<progress-bar :state=\"state\" :dark=\"dark\" :indeterminate=\"indeterminate\"></progress-bar>" +
      "<load-stats :state=\"state\" :dark=\"dark\"></load-stats>" +
      '<button class="btn ghost" type="button" v-if="cancel" @click="cancel">{{ cancelLabel }}</button>' +
      "</div>",
    computed: { svg: function () { return FV.icon(this.icon || "doc"); } }
  };

  var StateCard = {
    name: "StateCard",
    props: { icon: { type: String, default: "unknown" }, title: String, text: String, warn: Boolean, dark: Boolean },
    template:
      '<div class="card" :class="{ dark: dark }">' +
      '<span class="mark" :class="{ warn: warn }" v-html="svg"></span>' +
      '<div class="ttl" v-if="title">{{ title }}</div>' +
      "<div v-if=\"text\">{{ text }}</div>" +
      "<slot></slot>" +
      "</div>",
    computed: { svg: function () { return FV.icon(this.icon); } }
  };

  FV.ui = { ProgressBar: ProgressBar, LoadStats: LoadStats, LoadingPanel: LoadingPanel, StateCard: StateCard };
})();
