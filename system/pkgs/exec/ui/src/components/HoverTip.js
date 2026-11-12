export default {
  name: "HoverTip",
  props: {
    hover: { type: Object, default: null },
  },
  template: `
  <div class="tip" v-if="hover"
       :style="{ top: hover.y + 'px', left: hover.x + 'px' }">{{ hover.text }}</div>`,
};
