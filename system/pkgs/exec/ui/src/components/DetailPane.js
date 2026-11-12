import AdvancedOptions from "./AdvancedOptions.js";
import OutputArea from "./OutputArea.js";
import ActionBar from "./ActionBar.js";
import CodeEditor from "./CodeEditor.js";

export default {
  name: "DetailPane",
  components: { AdvancedOptions, OutputArea, ActionBar, CodeEditor },
  props: {
    command: { type: Object, default: null },
    commandsCount: { type: Number, default: 0 },
    spec: { type: Object, default: () => ({}) },
    placeholderHint: { type: String, default: "" },
    afterActions: { type: Array, default: () => [] },
    dirty: { type: Boolean, default: false },
    aliasBad: { type: Boolean, default: false },
    isHtml: { type: Boolean, default: false },
    htmlView: { type: String, default: "code" },
    wantsArgs: { type: Boolean, default: false },
    lastArgs: { type: String, default: "" },
    run: { type: Object, required: true },
    confirming: { type: Boolean, default: false },
    code: { type: String, default: "" },
  },
  emits: ["change", "set-html-view", "set-last-args", "set-confirming", "set-code",
          "pick", "save", "run", "delete", "stop", "close-run", "console", "save-run"],
  computed: {
    codeLocal: {
      get() { return this.code; },
      set(v) { this.$emit("set-code", v); },
    },
  },
  template: `
  <main class="detail">
    <section class="card" v-if="command">
      <div class="d-head">
        <div>
          <h1 class="d-title"><span class="prefix">pa :exec </span>{{ command.alias || '（未命名）' }}</h1>
          <p class="d-sub">{{ command._new ? '尚未保存' : (dirty ? '有未保存的修改' : '') }}</p>
        </div>
        <span class="pill" :title="spec.hint">{{ spec.label }}</span>
      </div>

      <div class="card-body">
        <div class="field" style="margin-top:14px">
          <div class="label">激活命令</div>
          <div class="alias-row">
            <span class="lead">pa :exec</span>
            <input ref="aliasInput" type="text" :class="{ invalid: aliasBad }" v-model="command.alias"
                   spellcheck="false" autocomplete="off" @input="$emit('change')">
          </div>
        </div>

        <div class="field">
          <div class="label">描述 <span class="hint">一句话说明它是干什么的</span></div>
          <input type="text" v-model="command.description" spellcheck="false"
                 autocomplete="off" @input="$emit('change')">
        </div>

        
        <div class="field code" v-if="spec.multiline">
          <div class="label">
            <span>{{ spec.payload }}</span>
            <span class="hint" v-if="!isHtml || htmlView === 'code'">{{ placeholderHint }}</span>
            <span class="seg mini" v-if="isHtml">
              <button :aria-selected="htmlView === 'code'"
                      @click="$emit('set-html-view', 'code')">源码</button>
              <button :aria-selected="htmlView === 'preview'"
                      @click="$emit('set-html-view', 'preview')">预览</button>
            </span>
          </div>
          <code-editor v-show="htmlView === 'code'" v-model="codeLocal"
                       :language="spec.lang" @change="$emit('change')"></code-editor>
          
          <iframe v-if="isHtml && htmlView === 'preview'" class="preview-frame"
                  :srcdoc="code" sandbox="allow-scripts allow-same-origin"></iframe>
          <div class="field-note"></div>
        </div>

        
        <div class="field" v-else>
          <div class="label">{{ spec.payload }} <span class="hint">{{ placeholderHint }}</span></div>
          <div class="alias-row">
            <input type="text" class="mono" v-model="codeLocal" spellcheck="false"
                   autocomplete="off" @input="$emit('change')">
            <template v-if="spec.pick === 'any'">
              <button class="btn" @click="$emit('pick', 'file')">选文件</button>
              <button class="btn" @click="$emit('pick', 'dir')">选文件夹</button>
            </template>
          </div>
          <div class="field-note"></div>
        </div>

        <advanced-options v-if="spec.kind === 'proc'" :command="command"
                          :after-actions="afterActions"
                          @change="$emit('change')" @pick="$emit('pick', $event)"></advanced-options>
      </div>

      <output-area :run="run" @stop="$emit('stop')" @close="$emit('close-run')"></output-area>

      <action-bar :confirming="confirming" :wants-args="wantsArgs" :last-args="lastArgs"
                  :is-new="!!command._new" :is-proc="spec.kind === 'proc'"
                  @set-confirming="$emit('set-confirming', $event)"
                  @set-last-args="$emit('set-last-args', $event)"
                  @run="$emit('run')" @save="$emit('save')" @delete="$emit('delete')"
                  @console="$emit('console')" @save-run="$emit('save-run')"></action-bar>
    </section>

    <div class="empty" v-else>
      <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="2.5" y="4" width="19" height="16" rx="3.5"></rect>
        <path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"></path>
      </svg>
      <h2>{{ commandsCount ? '选择左侧的一条命令' : '从一个命令开始' }}</h2>
      <p>{{ commandsCount ? '在这里编辑它的描述、执行方式和内容。'
                         : '点右上角「新建」，或者按 Ctrl+N。' }}</p>
    </div>
  </main>`,
};
