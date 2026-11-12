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
    text: {
      get() { return this.modelValue; },
      set(v) { this.$emit("update:modelValue", v); },
    },
    highlighted() {
      const text = this.modelValue || "";
      if (window.hljs && this.language && hljs.getLanguage(this.language)) {
        try {
          return hljs.highlight(text, { language: this.language, ignoreIllegals: true }).value + "\n";
        } catch (_) {  }
      }
      return escapeHtml(text) + "\n";
    },
  },
  watch: {
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
