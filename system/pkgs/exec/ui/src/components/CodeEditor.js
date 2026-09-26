/* 代码编辑器：高亮层 + 透明 textarea 叠在一起。
 *
 * 两层（pre>code 和 textarea）的字号 / 行高 / 字距 / 内边距 / tab-size
 * 必须**完全一致**，否则光标会和字形错位 —— 这是这块最容易踩的坑。
 *
 * 对外就是一个 v-model（内容）+ language（高亮语言）。
 */
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));
}

export default {
  name: "CodeEditor",
  props: {
    modelValue: { type: String, default: "" },
    language: { type: String, default: "" },
  },
  emits: ["update:modelValue", "change"],
  computed: {
    /* 用本地中转属性 + v-model 绑 textarea，而不是 :value + @input ——
       Vue 的 v-model 在原生输入框上带输入法合成（composition）保护，
       裸 @input 会在中文输入法拼字过程中就往上抛，拼音打到一半内容就乱了。 */
    text: {
      get() { return this.modelValue; },
      set(v) { this.$emit("update:modelValue", v); },
    },
    highlighted() {
      const text = this.modelValue || "";
      if (window.hljs && this.language && hljs.getLanguage(this.language)) {
        try {
          return hljs.highlight(text, { language: this.language, ignoreIllegals: true }).value + "\n";
        } catch (_) { /* 退回纯文本 */ }
      }
      return escapeHtml(text) + "\n";
    },
  },
  watch: {
    /* 高亮层内容换了，滚动位置要重新对齐 */
    highlighted() { this.$nextTick(this.syncScroll); },
  },
  mounted() { this.syncScroll(); },
  methods: {
    insertTab(e) {
      const el = e.target, p = el.selectionStart;
      el.value = el.value.slice(0, p) + "    " + el.value.slice(el.selectionEnd);
      el.selectionStart = el.selectionEnd = p + 4;
      this.text = el.value;
      this.$emit("change");
    },
    syncScroll() {
      const ta = this.$refs.ta, hl = this.$refs.hl;
      if (!ta || !hl || !hl.parentElement) return;
      hl.parentElement.scrollTop = ta.scrollTop;
      hl.parentElement.scrollLeft = ta.scrollLeft;
    },
  },
  template: `
  <div class="editor">
    <pre aria-hidden="true"><code ref="hl" class="hljs" v-html="highlighted"></code></pre>
    <textarea ref="ta" v-model="text" spellcheck="false" wrap="off"
              @input="$emit('change')"
              @scroll="syncScroll" @keydown.tab.prevent="insertTab"></textarea>
  </div>`,
};
