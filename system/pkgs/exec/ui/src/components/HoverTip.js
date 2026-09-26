/* 列表项悬停时补全被截断的描述。
 * 位置由父级算好（fixed 定位），这里只负责画。 */
export default {
  name: "HoverTip",
  props: {
    hover: { type: Object, default: null },
  },
  template: `
  <div class="tip" v-if="hover"
       :style="{ top: hover.y + 'px', left: hover.x + 'px' }">{{ hover.text }}</div>`,
};
