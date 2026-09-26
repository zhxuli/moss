/* 底部操作栏：运行 / 参数 / 新窗口 / 保存 / 删除。
 * 删除走行内二次确认（不弹窗），确认态由父级持有，这里只抛 set-confirming。
 */
export default {
  name: "ActionBar",
  props: {
    confirming: { type: Boolean, default: false },
    wantsArgs: { type: Boolean, default: false },
    lastArgs: { type: String, default: "" },
    isNew: { type: Boolean, default: false },
    isProc: { type: Boolean, default: false },
  },
  emits: ["set-confirming", "set-last-args", "run", "save", "delete", "console", "save-run"],
  computed: {
    /* 参数框用 v-model 绑这个中转属性：直接绑 prop 会报"不能改 prop" */
    argsLocal: {
      get() { return this.lastArgs; },
      set(v) { this.$emit("set-last-args", v); },
    },
  },
  template: `
  <div class="actions">
    <template v-if="confirming">
      <span class="confirm">删除后无法撤销。</span>
      <span class="spacer"></span>
      <button class="btn ghost" @click="$emit('set-confirming', false)">取消</button>
      <button class="btn" style="background:var(--danger);color:#fff;border-color:transparent"
              @click="$emit('delete')">删除</button>
    </template>
    <template v-else>
      <button class="btn primary" @click="$emit('run')">运行 <span class="kbd">Ctrl+Enter</span></button>
      <input v-if="wantsArgs" type="text" v-model="argsLocal" placeholder="参数（可选）"
             spellcheck="false" autocomplete="off" style="max-width:210px"
             @keydown.enter.prevent="$emit('save-run')">
      <button v-if="isProc" class="btn ghost" @click="$emit('console')"
              title="在新控制台窗口中运行（适合 ping 这类需要交互的命令）">新窗口</button>
      <span class="spacer"></span>
      <button class="btn" @click="$emit('save')">保存 <span class="kbd">Ctrl+S</span></button>
      <button v-if="!isNew" class="btn danger" @click="$emit('set-confirming', true)">删除</button>
    </template>
  </div>`,
};
