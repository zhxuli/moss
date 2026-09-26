/* 新建命令：先定类型。
 * 类型定下之后就不再允许切换 —— 避免内容跟着类型乱跑。
 * 只负责选，选完把 typeId 抛给父级，建命令的逻辑留在父级。 */
import { iconFor } from "../icons.js";

export default {
  name: "NewSheet",
  props: {
    open: { type: Boolean, default: false },
    newTypes: { type: Array, default: () => [] },
  },
  emits: ["pick", "close"],
  methods: { iconFor },
  template: `
  <div class="sheet-wrap" v-if="open">
    <div class="scrim" @click="$emit('close')"></div>
    <div class="sheet">
      <h2>新建命令</h2>
      <p>先选一种执行方式。类型定下之后就固定了 —— 想换类型请新建一条，避免内容跟着类型乱跑。</p>
      <div class="tiles">
        <button v-for="t in newTypes" :key="t.id" class="tile" @click="$emit('pick', t.id)">
          <span class="tico" v-html="iconFor(t.icon)"></span>
          <span class="txt"><b>{{ t.label }}</b><i>{{ t.hint }}</i></span>
        </button>
      </div>
      <div class="sheet-foot">
        <button class="btn ghost" @click="$emit('close')">取消</button>
      </div>
    </div>
  </div>`,
};
