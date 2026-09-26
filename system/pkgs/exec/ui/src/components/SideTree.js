/* 左侧：分类 + 命令合成的一棵可折叠树（等价于 macOS 的大纲视图）。
 *
 * 纯粹"读 props + 抛 events"，自己**不持有任何状态**：
 * 展开态 expanded 也留在父级，这里只按它算 isOpen。
 * 这样树怎么折、怎么选，父级说了算，组件本身可以独立测。
 */
import { iconFor } from "../icons.js";

export default {
  name: "SideTree",
  props: {
    groups: { type: Array, default: () => [] },
    expanded: { type: Object, default: () => ({}) },
    selectedKey: { type: String, default: null },
    filteredCount: { type: Number, default: 0 },
    commandsCount: { type: Number, default: 0 },
    /* 正在搜索时强制全展开，否则命中的结果看不见 */
    searching: { type: Boolean, default: false },
  },
  emits: ["select", "toggle", "expand-all", "reveal", "hover"],
  methods: {
    iconFor,
    isOpen(g) {
      if (this.searching) return true;
      return this.expanded[g.id] !== false;
    },
    /* 悬停时顺手把行位置算好抛给父级 —— 定位要读 DOM，留在组件里更合适 */
    onEnter(e, c) {
      if (!c.description) { this.$emit("hover", null); return; }
      const r = e.currentTarget.getBoundingClientRect();
      this.$emit("hover", { text: c.description, x: r.left + 12, y: r.bottom + 6 });
    },
  },
  template: `
  <aside class="sidebar">
    <div class="tree-head">
      <span class="title">全部命令</span>
      <span class="n">{{ filteredCount }}</span>
      <span style="flex:1"></span>
      <button class="icon-btn" title="全部展开" v-html="iconFor('expand')"
              @click="$emit('expand-all', true)"></button>
      <button class="icon-btn" title="全部收起" v-html="iconFor('collapse')"
              @click="$emit('expand-all', false)"></button>
    </div>

    <div class="tree">
      <template v-for="g in groups" :key="g.id">
        <button class="grp" @click="$emit('toggle', g.id)">
          <svg class="tri" :class="{ open: isOpen(g) }" viewBox="0 0 10 10" fill="none"
               stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
               stroke-linejoin="round"><path d="M3 1.5 6.5 5 3 8.5"/></svg>
          <span v-html="iconFor(g.icon)"></span>
          <span class="lbl">{{ g.label }}</span>
          <span class="n">{{ g.items.length }}</span>
        </button>
        <template v-if="isOpen(g)">
          <div v-for="c in g.items" :key="c._key" class="row"
               :class="{ sel: c._key === selectedKey }"
               @click="$emit('select', c._key)"
               @mouseenter="onEnter($event, c)" @mouseleave="$emit('hover', null)">
            <span class="dot" :class="c.type"></span>
            <span class="alias">{{ c.alias || '（未命名）' }}</span>
            <span class="desc">{{ c.description || '' }}</span>
          </div>
        </template>
      </template>

      <div v-if="!filteredCount" class="empty">
        <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"
             stroke-linecap="round" stroke-linejoin="round">
          <rect x="2.5" y="4" width="19" height="16" rx="3.5"></rect>
          <path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"></path>
        </svg>
        <h2>{{ commandsCount ? '没有匹配的命令' : '还没有命令' }}</h2>
        <p>{{ commandsCount ? '换个关键词试试。' : '点右上角「新建」，或者按 Ctrl+N。' }}</p>
      </div>
    </div>

    <div class="side-foot"><button @click="$emit('reveal')">数据目录</button></div>
  </aside>`,
};
