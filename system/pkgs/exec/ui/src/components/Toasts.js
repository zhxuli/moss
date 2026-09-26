/* 右下角的轻提示。纯展示，只吃一个 toasts 数组。 */
export default {
  name: "Toasts",
  props: {
    toasts: { type: Array, default: () => [] },
  },
  template: `
  <div class="toast-wrap">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="{ bad: t.bad }">
      {{ t.bad ? '⚠︎ ' : '✓ ' }}{{ t.text }}
    </div>
  </div>`,
};
