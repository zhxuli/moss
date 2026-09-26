/* 运行输出的抽屉。
 * "输出变长自动跟到底"的 watch 原来挂在根组件上，现在跟着它自己走。 */
export default {
  name: "OutputArea",
  props: {
    run: { type: Object, required: true },
  },
  emits: ["stop", "close"],
  watch: {
    "run.output"() {
      this.$nextTick(() => {
        const el = this.$refs.out;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
  },
  template: `
  <div class="run-area" :class="{ on: run.output !== null }">
    <div class="output" v-if="run.output !== null">
      <div class="output-head">
        <span class="spinner" v-if="run.running"></span>
        <span class="label" style="margin:0">输出</span>
        <span style="flex:1"></span>
        <button class="btn ghost" v-if="run.running" @click="$emit('stop')">停止</button>
        <button class="btn ghost" @click="$emit('close')">收起</button>
      </div>
      <pre ref="out">{{ run.output }}</pre>
    </div>
  </div>`,
};
