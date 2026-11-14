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
    panelReady: { type: Boolean, default: false },
    tab: { type: String, default: "view" },
    frameUrl: { type: String, default: "" },
    saving: { type: Boolean, default: false },
  },
  emits: ["change", "set-html-view", "set-last-args", "set-confirming", "set-code",
          "set-open-in", "set-tab", "refresh-panel",
          "pick", "save", "run", "delete", "stop", "close-run", "console", "save-run"],
  computed: {
    codeLocal: {
      get() { return this.code; },
      set(v) { this.$emit("set-code", v); },
    },
    openIn() {
      return (this.command && this.command.open_in) || "panel";
    },
    canBrowse() {
      return !!(this.command && !this.command._new
                && this.command.type === "url" && this.openIn === "panel");
    },
    browsing() {
      return this.canBrowse && this.tab === "view";
    },
    viewTitle() {
      const code = (this.code || "").trim();
      return code ? code.replace(/^https?:\/\//, "").split("/")[0] : "还没填网址";
    },
  },
  template: `
  <main class="detail">
    <section class="card" :class="{ wide: browsing }" v-if="command">
      <div class="d-head">
        <div>
          <h1 class="d-title"><span class="prefix">pa :exec </span>{{ command.alias || '（未命名）' }}</h1>
          <p class="d-sub">{{ command._new ? '尚未保存' : (dirty ? '有未保存的修改' : '') }}</p>
        </div>
        <span class="pill" :title="spec.hint">{{ spec.label }}</span>
      </div>

      <div class="d-tabs" v-if="canBrowse">
        <button :aria-selected="tab === 'view'" @click="$emit('set-tab', 'view')">浏览</button>
        <button :aria-selected="tab === 'edit'" @click="$emit('set-tab', 'edit')">设置</button>
        <div class="d-tabs-arg" v-if="tab === 'view'">
          <input :value="lastArgs" placeholder="参数（回车刷新）" spellcheck="false"
                 @input="$emit('set-last-args', $event.target.value)"
                 @keydown.enter="$emit('refresh-panel')">
          <button class="btn" @click="$emit('refresh-panel')">刷新</button>
        </div>
      </div>

      <div class="view-host" v-if="browsing">
        <iframe v-if="frameUrl" :src="frameUrl" referrerpolicy="no-referrer"></iframe>
      </div>

      <div class="card-body" v-if="!browsing">
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

        <div class="field" v-if="spec.openers">
          <div class="label">打开方式</div>
          <span class="seg fit">
            <button v-for="o in spec.openers" :key="o.id"
                    :aria-selected="openIn === o.id"
                    @click="$emit('set-open-in', o.id)">{{ o.label }}</button>
          </span>
        </div>

        <advanced-options v-if="spec.kind === 'proc'" :command="command"
                          :after-actions="afterActions"
                          @change="$emit('change')" @pick="$emit('pick', $event)"></advanced-options>
      </div>

      <output-area v-if="!browsing" :run="run" @stop="$emit('stop')"
                  @close="$emit('close-run')"></output-area>

      <action-bar v-if="!browsing" :saving="saving" :confirming="confirming" :wants-args="wantsArgs" :last-args="lastArgs"
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
