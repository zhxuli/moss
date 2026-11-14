import { iconFor } from "../icons.js";

export default {
  name: "SideTree",
  props: {
    groups: { type: Array, default: () => [] },
    expanded: { type: Object, default: () => ({}) },
    selectedKey: { type: String, default: null },
    filteredCount: { type: Number, default: 0 },
    commandsCount: { type: Number, default: 0 },

    searching: { type: Boolean, default: false },
  },
  emits: ["select", "toggle", "expand-all", "reveal", "hover"],
  methods: {
    iconFor,
    isOpen(g) {
      if (this.searching) return true;
      return this.expanded[g.id] !== false;
    },
    /* 窄栏只放短名字：括号补充说明去掉，开头的别名去掉（左边已经有一列），太长就截断；
       完整描述还在悬浮提示里 */
    shortDesc(c) {
      const text = (c.description || "").trim();
      let out = text
        .replace(/[（(][^）)]*[）)]/g, "")
        .replace(/[「【\[][^」】\]]*[」】\]]/g, "")
        .replace(/\s+/g, " ")
        .trim();
      const alias = (c.alias || "").trim().toLowerCase();
      if (alias && out.toLowerCase().startsWith(alias + " ")) out = out.slice(alias.length + 1).trim();
      const head = out.split(" / ")[0].trim();
      if (head.length >= 2) out = head;
      if (!out) return "";
      return out.length > 9 ? out.slice(0, 9).trimEnd() + "…" : out;
    },

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
            <span class="desc">{{ shortDesc(c) }}</span>
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
