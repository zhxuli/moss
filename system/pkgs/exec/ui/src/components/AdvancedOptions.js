export default {
  name: "AdvancedOptions",
  props: {
    command: { type: Object, required: true },
    afterActions: { type: Array, default: () => [] },
  },
  emits: ["change", "pick"],
  template: `
  <details class="advanced">
    <summary>高级选项</summary>

    <div class="field">
      <div class="label">工作目录 <span class="hint">留空 = 继承你敲 pa 时所在的目录</span></div>
      <div class="alias-row">
        <input type="text" class="mono" v-model="command.cwd" placeholder="留空 = 继承当前目录"
               spellcheck="false" autocomplete="off" @input="$emit('change')">
        <button class="btn" @click="$emit('pick', 'cwd')">选择…</button>
      </div>
    </div>

    <div class="field">
      <div class="label">环境变量 <span class="hint">每行一个 KEY=VALUE</span></div>
      <textarea class="small" v-model="command.env" spellcheck="false"
                placeholder="HTTP_PROXY=http://127.0.0.1:7890" @input="$emit('change')"></textarea>
    </div>

    <div class="field">
      <div class="label">运行后 <span class="hint">对命令输出做什么</span></div>
      <select v-model="command.after" @change="$emit('change')">
        <option v-for="a in afterActions" :key="a.id" :value="a.id">{{ a.label }}</option>
      </select>
    </div>

    <div class="field">
      <label class="check">
        <input type="checkbox" v-model="command.elevated" @change="$emit('change')">
        以管理员身份运行（会弹 UAC，且输出无法被捕获）
      </label>
    </div>
  </details>`,
};
