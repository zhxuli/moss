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
