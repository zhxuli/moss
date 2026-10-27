/* moss 界面 · js/settings.js —— ★ 设置面板（`V-60` ✅ / `V-63` ✅ / `V-66` ✅ / `V-67` ✅）
   ============================================================================
   这是**第一个 Vue 3 组件**（`V-67`：原来它是一大段命令式 DOM 代码，散在 index.html 里）。

   它自己带：模板（写在这个文件里）、状态、校验、保存、hover 提示 —— 外面只管两件事：
     · `<div id="settings-host"></div>` 这么个挂载点；
     · 齿轮点一下调 `openSettings()`。

   ★ 数据全是宿主给的（`moss --settings` / `--settings-check` / `--settings-set`）：
     分组 / 图标 / 标签 / 说明 / 控件类型 / 当前值 / 「现在这样」/ 冲突原因。
     这个组件**不认识任何设置项，也不自己实现校验规则** —— 规则只有 `core/config.py` 那一份。
   ★ 为什么是"经典脚本 + 全局组件"而不是 .vue 单文件：页面是 pywebview 从 `file://`
     打开的，`file://` 下的 ES module 会被 CORS 拦掉（见 index.html 里的说明）。
     `vue.global.prod.js` 自带模板编译器，所以 `template:` 字符串在这里能用。 */
/* ★ `V-358`：**自动启动那一组从这里搬走了** —— 用户说「把那个自动启动放在详情里面去设置
   而不是放到设置里面去 那样很不直观」。现在它在「详情」页（包详情 / 历史详情各一块），
   实现在 `js/autostart.js`，设置面板里一个字都不留。 */

const MossSettings = {
  name: "moss-settings",
  template: `
<div id="settings" :class="{on: show}" @click.self="close">
  <div class="card wide">
    <div class="set-head">
      <h3>设置</h3>
      <!-- 整条路径**每一段**都能点（V-198）：点哪一段就打开"到那一级"的路径，一直能点到根目录。
           最后一段没有分隔符 ⇒ 那是个文件，点它就是打开文件（上一版只拆了目录 / 文件名两段，V-160）。 -->
      <span class="set-sub" id="set-path" :title="path"><span
        v-for="(s, i) in segs" :key="i" class="set-link" :data-path="s.path"
        :id="i === segs.length - 1 ? 'set-open-file' : null"
        role="button" tabindex="0"
        :title="(s.isFile ? '打开这个文件：' : '打开这一级：') + s.path"
        @click="openSeg(s)">{{ s.text }}</span></span>
      <button class="set-x" id="set-close" title="关闭（Esc）" aria-label="关闭"
              @click="close" v-html="icon('x')"></button>
    </div>

    <div class="set-main">
      <div class="set-nav" id="set-nav">
        <button v-for="g in groups" :key="g.name" type="button" class="set-navitem"
                :class="{on: g.name === active, 'has-bad': badGroups[g.name] === 'bad',
                         'has-warn': badGroups[g.name] === 'warn'}"
                :data-group="g.name" :title="navTitle(g.name)" @click="setActive(g.name)">
          <span v-html="isAi(g) ? aiSvg('deepseek') : icon(g.icon || 'settings')"></span><span
            class="set-navname">{{ g.name }}</span>
          <span class="set-dot"></span>
        </button>
      </div>

      <div class="set-body" id="set-body" @mouseleave="hideTip" @scroll="hideTip">
        <div v-for="g in groups" :key="g.name" class="set-pane"
             :class="{on: g.name === active, 'is-ai': isAi(g)}" :data-group="g.name">

          <!-- 通用标题 + 说明：AI 那一页自己有稿子的 view-header，这里让开（V-146） -->
          <template v-if="!isAi(g)">
            <h3 class="set-ptitle">{{ g.name }}</h3>
            <p class="set-pdesc" v-if="g.blurb">{{ g.blurb }}</p>
          </template>

          <!-- ★ AI（V-143）：照那份 UI 稿子抄的 —— 三张"视图"（列表 / 选服务商 / 编辑）**常驻 DOM**，
               靠 .active 做「淡入 + 上移 15px」的切换（稿子的 .view / .view.active 那套），
               卡片 / 虚线空框 / 九宫格 / 结果横幅 / 底部动作条的大小间距也按稿子来。
               ★ 唯一没照抄的：稿子里的次要按钮是 1px 描边的，咱这边有「按钮不许有描边」那条通用闸
                 （V-92 你定的），所以换成浅底色 —— 形状、尺寸、字重照旧。 -->
          <div class="set-ai" v-if="isAi(g)">
            <!-- 视图 1：列表 -->
            <div class="ai-view active" id="ai-view-list" v-if="ai.mode === 'list'">
              <div class="ai-scroll">
              <div class="ai-vhead">
                <h3 class="ai-vtitle">AI 配置</h3>
              </div>

              <div class="ai-empty" id="ai-empty" v-if="!ai.profiles.length">
                <span class="ai-eico" v-html="aiSvg('user')"></span>
                <h4>暂无配置</h4>
              </div>

              <div class="ai-list" id="ai-list" v-else>
                <div v-for="n in ai.profiles" :key="n" class="ai-card" :data-group="n">
                  <div class="ai-cinfo">
                    <div class="ai-cname">
                      <span class="ai-cdot" v-if="n === ai.active"
                            title="当前用的就是这一组"></span>{{ n }}
                    </div>
                    <div class="ai-cmeta">{{ aiSummary(n) }}</div>
                  </div>
                  <div class="ai-cacts">
                    <button class="ai-btn" type="button" v-if="n !== ai.active"
                            :data-use="n" @click="aiUse(n)">设为当前</button>
                    <button class="ai-btn" type="button" :data-edit="n"
                            @click="aiEdit(n)">编辑</button>
                    <button class="ai-btn danger" type="button" :data-del="n"
                            @click="aiDel(n)">删除</button>
                  </div>
                </div>
              </div>

              <div class="ai-add" id="ai-new" @click="aiTemplates()">
                <span v-html="aiSvg('plus')"></span>
                <span>添加新的 AI 配置</span>
              </div>
              </div>
            </div>

            <!-- 视图 2：选服务商 -->
            <div class="ai-view active" id="ai-view-tpl" v-else-if="ai.mode === 'tpl'">
              <div class="ai-scroll">
              <button class="ai-back" id="ai-back" type="button" title="返回列表"
                      aria-label="返回列表" @click="aiList()"
                      v-html="aiSvg('back')"></button>
              <div class="ai-vhead"><h3 class="ai-vtitle">服务商</h3></div>
              <div class="ai-tplgrid" id="ai-tplgrid">
                <div v-for="p in ai.presets" :key="p.name" class="ai-tpl" :data-preset="p.name"
                     @click="aiUsePreset(p)">
                  <span class="ai-tico">{{ p.name.slice(0, 1) }}</span>
                  <span class="ai-tinfo"><b>{{ p.name }}</b><i>{{ p.desc || aiHost(p.base_url) }}</i></span>
                </div>
                <div class="ai-tpl" data-preset="自定义" id="ai-blank" @click="aiBlank()">
                  <span class="ai-tico">＋</span>
                  <span class="ai-tinfo"><b>自定义</b></span>
                </div>
              </div>
              </div>
            </div>

            <!-- 视图 3：编辑 -->
            <div class="ai-view active" id="ai-view-form" v-else>
              <div class="ai-scroll">
              <button class="ai-back" id="ai-back2" type="button" title="放弃修改，返回列表"
                      aria-label="放弃修改，返回列表" @click="aiCancel()"
                      v-html="aiSvg('back')"></button>
              <div class="ai-vhead" style="margin-bottom:16px">
                <h3 class="ai-vtitle" id="ai-ttl">{{ ai.creating
                  ? (ai.from === "自定义" ? "新建自定义配置" : ("配置 " + (ai.from || "AI")))
                  : ("编辑: " + ai.name) }}</h3>
              </div>

              <div class="ai-frow">
                <div class="ai-fgroup" data-ai="name">
                  <label class="ai-flabel" for="ai-in-name"
                         title="改了名字保存 = 给这一组改名。">名称</label>
                  <input class="ai-input" id="ai-in-name" :data-ai="'name'" type="text"
                         spellcheck="false" autocomplete="off" placeholder="例如：主用 DeepSeek"
                         :value="aiVal('name')" @input="aiSet('name', $event.target.value)">
                </div>
                <div class="ai-fgroup" data-ai="base_url">
                  <label class="ai-flabel" for="ai-in-url"
                         title="OpenAI 兼容地址，填到 /v1。">Base URL</label>
                  <input class="ai-input" id="ai-in-url" type="text" spellcheck="false"
                         autocomplete="off" placeholder="https://api..."
                         :value="aiVal('base_url')" @input="aiSet('base_url', $event.target.value)">
                </div>
              </div>

              <div class="ai-fgroup" data-ai="api_key">
                <label class="ai-flabel" for="ai-in-key"
                       title="留空 = 不修改">API Key</label>
                <div class="ai-keywrap" :class="{nokey: !aiVal('api_key')}">
                  <input class="ai-input" id="ai-in-key" :type="ai.showKey ? 'text' : 'password'"
                         spellcheck="false" autocomplete="off" :placeholder="aiKeyPh()"
                         :value="aiVal('api_key')" @input="aiSet('api_key', $event.target.value)">
                  <!-- 框里那只小眼睛：悬停/聚焦 + 框里有内容才出现（悬停、有字才看得见） -->
                  <button class="ai-eye" id="ai-eye" type="button"
                          :title="ai.showKey ? '藏起来' : '看明文'"
                          @click="aiToggleKey()"
                          v-html="icon(ai.showKey ? 'eye-off' : 'eye')"></button>
                </div>
              </div>

              <div class="ai-fgroup ai-query" data-ai="query" v-if="aiCanQuery()">
                <div class="ai-query-btns">
                  <button class="ai-query-btn" id="ai-fetch-models" type="button"
                          :disabled="ai.busy" @click="aiFetchModels"
                          title="从接口的 /models 获取可用模型，自动填入下面的列表（不用先保存）">
                    <span v-html="icon('refresh-cw')"></span><span>获取可用模型</span>
                  </button>
                  <button class="ai-query-btn" id="ai-fetch-balance" type="button"
                          :disabled="ai.busy" @click="aiFetchBalance"
                          title="查询这个接口的账户余额（DeepSeek / Kimi / OpenRouter / 硅基流动等已知接口）">
                    <span v-html="icon('gauge')"></span><span>查询余额</span>
                  </button>
                </div>
              </div>

              <div class="ai-fgroup" data-ai="model">
                <label class="ai-flabel" for="ai-in-models"
                       title="一行一个，第一个当默认">模型</label>
                <textarea class="ai-input ai-textarea" id="ai-in-models" spellcheck="false"
                          placeholder="输入模型名称..." :value="aiVal('model')"
                          @input="aiSet('model', $event.target.value)"></textarea>
              </div>

              <div class="ai-banner" id="ai-banner" v-if="ai.status"
                   :class="ai.statusOk ? 'ok' : 'bad'">
                <span class="ai-bico"
                      v-html="icon(ai.statusOk ? 'check' : 'circle-alert')"></span>
                <span class="ai-btxt">
                  <span id="ai-state">{{ ai.status }}</span>
                  <!-- 原始报文（那一大串）折起来，点了才看 —— 普通用户不需要看到代码 -->
                  <button class="ai-more" id="ai-more" type="button" v-if="ai.detail"
                          @click="ai.open = !ai.open">{{ ai.open ? "收起" : "详情" }}</button>
                  <code class="ai-detail" id="ai-detail" v-if="ai.open && ai.detail">{{ ai.detail }}</code>
                </span>
              </div>

              </div>

            </div>
          </div>

          <!-- 通用那套（一个键一行）：AI / 短名设置 / 命令接入这三组自己有界面，所以用 v-if 让开 -->
          <template v-if="!isAi(g) && !isShortcut(g) && !isAccess(g)">
          <!-- 输入类：标签在上、控件在下（两列网格） -->
          <div class="set-fields" v-if="fieldsOf(g).length">
            <div v-for="it in fieldsOf(g)" :key="it.key" class="set-field" :data-key="it.key"
                 :class="rowClass(it.key)">
              <div class="set-lbl">
                <span>{{ it.label }}</span>
                <span v-if="it.hint" class="set-info" :data-tip-key="it.key"
                      @mouseover="showTip(it.key, $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <div v-if="it.type === 'int'" class="step">
                <button type="button" title="减一" :disabled="Number(values[it.key]) <= 0"
                        @click="bump(it.key, -1)">−</button>
                <input class="num" :data-key="it.key" :value="values[it.key]" inputmode="numeric"
                       @change="setVal(it.key, clampNum($event.target.value))">
                <button type="button" title="加一" :disabled="Number(values[it.key]) >= 20"
                        @click="bump(it.key, 1)">+</button>
              </div>
              <input v-else class="inp" :data-key="it.key" spellcheck="false" autocomplete="off"
                     :placeholder="it.placeholder || (it.type === 'symbol' ? '空' : '留空 = 不打印')"
                     :value="values[it.key]"
                     @input="setVal(it.key, $event.target.value)">
              <div class="set-prob" data-role="prob">{{ probText(it.key) }}</div>
            </div>
          </div>

          <!-- 开关类：名字在左、开关在右 -->
          <div class="set-list" v-if="rowsOf(g).length" :style="fieldsOf(g).length ? 'margin-top:16px' : ''">
            <div v-for="it in rowsOf(g)" :key="it.key" class="set-item" :data-key="it.key"
                 :class="rowClass(it.key)">
              <div class="set-lbl">
                <span>{{ it.label }}</span>
                <span v-if="it.hint" class="set-info" :data-tip-key="it.key"
                      @mouseover="showTip(it.key, $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <button type="button" class="sw" :data-key="it.key" role="switch"
                      :aria-checked="values[it.key] ? 'true' : 'false'"
                      :title="values[it.key] ? '开 —— 点一下关掉' : '关 —— 点一下打开'"
                      @click="setVal(it.key, !values[it.key])"></button>
              <div class="set-prob" data-role="prob">{{ probText(it.key) }}</div>
            </div>
          </div>

          <!-- 快捷命令那页：底下一条预览行（宿主算的那句话） -->
          <div v-if="g.live" class="set-live" id="set-live" :class="{bad: /^⚠/.test(live || '')}">
            {{ live }}
          </div>

          </template>

          <!-- ★ V-299：命令接入那一组（照你给的那份清爽稿子）—— 一张卡片两行设置（PATH / CD 增强），
               CD 下面挂一个"受控子环境列表"的子面板；关掉 CD 时子面板整块置灰。 -->
          <div class="acc-card" id="set-acc" v-if="isAccess(g)">
            <div class="acc-row">
              <div class="acc-info">
                <h4 class="acc-title">系统 PATH</h4>
              </div>
              <div class="acc-ctrl">
                <span class="acc-state" :class="{on: !!values['path.moss']}">{{ values['path.moss'] ? "已开启" : "未开启" }}</span>
                <button type="button" class="sw" data-key="path.moss" role="switch"
                        :aria-checked="values['path.moss'] ? 'true' : 'false'"
                        @click="setVal('path.moss', !values['path.moss'])"></button>
              </div>
            </div>

            <div class="acc-row">
              <div class="acc-info">
                <h4 class="acc-title">终端 CD 增强
                  <span class="set-info" title="用 PowerShell 函数无痕切换目录"
                        v-html="icon('info')"></span>
                </h4>
              </div>
              <div class="acc-ctrl">
                <span class="acc-state" :class="{on: cd.any}">{{ cd.busy ? "处理中…" : (cd.any ? "已开启" : "未开启") }}</span>
                <button type="button" class="sw" id="acc-cd-sw" role="switch"
                        :aria-checked="cd.any ? 'true' : 'false'" :disabled="cd.busy"
                        @click="cdToggle()"></button>
              </div>
            </div>

            <div class="acc-sub" id="acc-cd-sub" :class="{off: !cd.any}">
              <div class="acc-warn">
                <span class="acc-wico" v-html="icon('circle-alert')"></span>
                <span>卸载前先关掉这里，清掉终端配置。</span>
              </div>
              <div class="acc-subtitle">环境</div>
              <div class="acc-env" v-for="p in cd.profiles" :key="p.path">
                <span>{{ p.label }}</span>
                <span class="acc-envstat" :class="{on: p.installed}">{{ p.installed ? "已注入" : "未注入" }}</span>
              </div>
              <div class="acc-env" v-if="!cd.profiles.length">
                <span class="dim">（还没读到环境状态）</span>
              </div>
            </div>
          </div>

          <!-- ★ V-298：短名设置那一组（照那份稿子）—— 前缀 + 三段选择（不启用 / 仅前缀 / 前缀+包名）
               + **一直显示**的左右对比预览（左=原来、右=现在；改前缀、切模式它立刻跟着变）。
               ★ 为什么用三段而不是两个独立开关：这是一件事的三种程度，做成一条线才一眼看懂。 -->
          <div class="set-sc" v-if="isShortcut(g)">
            <div class="set-field sc-field" :class="rowClass('shortcut.prefix')">
              <div class="set-lbl">
                <span>前缀</span>
                <span class="set-info" data-tip-key="shortcut.prefix"
                      @mouseover="showTip('shortcut.prefix', $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <input class="inp" data-key="shortcut.prefix" spellcheck="false" autocomplete="off"
                     placeholder="如 mo" :value="values['shortcut.prefix']"
                     @input="setVal('shortcut.prefix', $event.target.value)">
              <div class="set-prob" data-role="prob">{{ probText("shortcut.prefix") }}</div>
            </div>

            <div class="sc-mode">
              <div class="set-lbl">
                <span>短命令模式</span>
                <span class="set-info" @mouseover="showTip('shortcut.pkg', $event)" @mouseleave="hideTip"
                      v-html="icon('info')"></span>
              </div>
              <div class="sc-seg" id="set-sc-seg">
                <button type="button" data-mode="off" :class="{on: scMode === 0}"
                        @click="setScMode(0)">不启用</button>
                <button type="button" data-mode="prefix" :class="{on: scMode === 1}"
                        @click="setScMode(1)">仅替换前缀</button>
                <button type="button" data-mode="fused" :class="{on: scMode === 2}"
                        @click="setScMode(2)">前缀 + 包名融合</button>
              </div>
            </div>

            <div class="sc-preview" id="set-sc-preview">
              <div class="sc-ph">新开终端后生效</div>
              <div class="sc-cols">
                <div class="sc-col">
                  <div class="sc-coltitle">原来</div>
                  <pre>{{ scBeforeText }}</pre>
                </div>
                <div class="sc-col">
                  <div class="sc-coltitle">现在</div>
                  <pre id="set-sc-now" v-html="scNowHtml"></pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ★ 底栏**所有页共用一条**（V-155）：AI 不做特殊化。
         左边状态字 + 右边按钮：AI 页是「测试连接 / 保存」，别的页是「取消 / 保存」。 -->
    <div class="set-foot">
      <span class="set-state" id="set-state" :class="footClass">{{ aiPane ? aiFootText() : footText }}</span>
      <button class="btn-quiet" id="set-ai-test" v-if="aiPane && ai.mode === 'edit'"
              :disabled="ai.busy || !aiFilled()"
              :title="aiFilled() ? '发一个最小请求试试（不用先保存）'
                                 : '接口地址 / 密钥 / 模型 都填了才能测'"
              @click="aiTest(ai.name)">测试连接</button>
      <button class="btn primary" id="set-save"
              :disabled="aiPane ? (!aiFilled() || !aiDirty() || ai.busy) : !canSave"
              :title="aiPane && !aiFilled() ? '接口地址 / 密钥 / 模型 都填了才能保存' : ''"
              @click="aiPane ? aiSave() : save()">{{ ai.busy ? "保存中…" : "保存" }}</button>
    </div>
  </div>

  <!-- hover 提示：挂在组件里（原来那个全局 #tip 已经不需要了）。fixed 定位 —— 
       放进滚动层里会被裁掉。 -->
  <div id="tip" v-if="tip.show" :style="{left: tip.x + 'px', top: tip.y + 'px'}">
    <b>{{ tip.title }}</b>
    <div v-if="tip.hint">{{ tip.hint }}</div>
    <div class="tip-now" v-if="tip.now">{{ tip.now }}</div>
    <div v-for="(p, i) in tip.problems" :key="i" class="tip-prob"
         :class="p.level === 'warn' ? 'warn' : 'bad'">
      {{ (p.level === 'warn' ? '提醒：' : '') + p.why }}
    </div>
  </div>
</div>`,
  data(){
    return {
      show: false,
      path: "",
      groups: [],
      items: {},          // key -> 定义（标签 / 类型 / 说明）
      values: {},         // key -> 现在的值
      orig: {},           // key -> 打开时的值（判断"改了没有"）
      problems: [],
      notes: {},
      live: "",
      active: "",
      msg: "",            // 宿主顺带说的话（首次运行建了配置文件之类）
      saving: false,
      tip: {show: false, x: 0, y: 0, title: "", hint: "", now: "", problems: []},
      // ★ AI 那一组（`V-138`）：界面**不解析 TOML**，全都问宿主（`pywebview.api.ai_*`）。
      //   `params` = 宿主给的那一组（key **打码**）；`draft` = 用户改过、还没保存的字段
      //   （存的时候**只送这几个**，不会把打码那串当值写回去）。
      ai: {loaded: false, busy: false, name: "", active: "", profiles: [], presets: [],
           summary: {},
           params: {}, draft: {}, status: "", statusOk: false, from: "", showKey: false,
           keyReal: false,
           detail: "", open: false,
           // ★ `V-140`：两张脸 —— `list`（默认，一组一行）/ `edit`（点新建或某行编辑才进来）。
           //   一打开就摊开四个输入框（上一版）会让人以为"已经配好了"，你的原话：
           //   「还没有设置过的时候 它不应该是显示列表吗」。
           mode: "list",
           // ★ 正在**新建**一组（点了「常用」里某家或「自定义」）：这时候保存 = 加一组；
           //   不然「名字框和当前那组不一样」就一律当成**改名** —— 点个预制参数再保存会把
           //   原来那组改掉（第一版就这么错的，场景里"假库少了一组"才发现）。
           creating: false},
      // ★ `V-299`：「命令接入」页里的 cd 增强状态（走宿主 `--cd-status` / `cd --install`）
      cd: {loaded: false, busy: false, any: false, profiles: []},
      _timer: null,
      _seq: 0,
    };
  },
  computed: {
    // ★ `V-198`：整条路径拆成**每一段**（每段自带它后面那个分隔符），每段都记着"到这一级"的完整路径。
    //   上一版只拆两段（目录 / 文件名，`V-160`）—— 中间那几级点不动。
    //   ★ 切法是"段 + 分隔符交替"，好处有三：① 拼回去**一字不差**（原来是 `/` 还是 `\` 都照原样）；
    //     ② 盘符 `D:\` / UNC 头 `\\server\share\` / 根 `/` 单独当第一段；③ **最后一段没有分隔符**
    //     正好就等于"这是个文件"（路径以分隔符结尾 ⇒ 最后那段是目录）。
    segs(){
      const raw = String(this.path || "");
      const out = [];
      if (!raw) return out;
      const m = raw.match(/^([A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+[\\/]|[\\/])/);
      const head = m ? m[1] : "";
      if (head) out.push({text: head, path: head, isFile: false});
      const parts = raw.slice(head.length).split(/([\\/]+)/);
      let cur = head;
      for (let i = 0; i < parts.length; i += 2){
        const name = parts[i];
        if (!name) continue;
        const sep = parts[i + 1] || "";
        cur += name + sep;
        out.push({text: name + sep, path: cur, isFile: !sep});
      }
      return out;
    },
    shortPath(){
      const s = String(this.path || "").replace(/\\/g, "/");
      const parts = s.split("/").filter(Boolean);
      return parts.length <= 2 ? s : "…/" + parts.slice(-2).join("/");
    },
    changed(){
      return Object.keys(this.values).filter(k => String(this.values[k]) !== String(this.orig[k]));
    },
    errs(){
      return this.problems.filter(p => p.level !== "warn").length;
    },
    canSave(){
      // ★ `V-275`：**只看"改没改"**（纯前端），不再要求"宿主说没问题" —— 那样才能做到
      //   "点保存才校验"。真有问题的话，保存那趟会把 problems 带回来并标红。
      return this.changed.length > 0 && !this.saving;
    },
    footText(){
      if (this.saving) return "正在保存…";
      // 上一次保存被打回留下的那些冲突（改的时候还留着，方便照着改；存成功就清掉）
      if (this.errs) return "✗ " + this.errs + " 处冲突 —— 改好再点一次保存";
      if (this.changed.length){
        return "改了 " + this.changed.length + " 项 · 点保存写入 config.toml（下次启动 moss 生效）"
               + (this.msg ? "（" + this.msg + "）" : "");
      }
      // ★ `V-164`：没改动不是状态、更不是错，什么都不显示（只留宿主顺带说的话）
      return this.msg ? ("（" + this.msg + "）") : "";
    },
    footClass(){
      if (this.errs) return "bad";
      return this.changed.length ? "moved" : "";
    },
    // 哪一组里有红/黄 —— 要在左边分类上点一个小圆点（不然切走了看不见）
    badGroups(){
      const out = {};
      (this.problems || []).forEach(p => {
        [p.key].concat(p.also || []).forEach(k => {
          const g = this.groupOf(k);
          if (!g) return;
          if (out[g] !== "bad") out[g] = (p.level === "warn") ? "warn" : "bad";
        });
      });
      return out;
    },
    // 现在这一页是不是 AI 那一组（是的话底部那颗全局「保存」就不摆 —— 见模板里的注释）
    aiPane(){ return this.isAiName(this.active); },
    // ★ `V-298`：短名设置那一组 —— 前缀 / 三段模式 / 对比预览（都跟着当前编辑值即时变）
    scPrefix(){ return (String(this.values["shortcut.prefix"] || "").replace(/[^A-Za-z0-9_-]/g, "")) || "mo"; },
    scMode(){ return this.values["shortcut.pkg"] ? 2 : (this.values["shortcut.mo"] ? 1 : 0); },
    // ★ `V-305`：这一页"现在的写法"要用**真的跑包符号**（设置→符号 里那个），别写死 `:`
    scSym(){ const s = this.values["symbols.plugin_mode"]; return s === undefined ? ":" : String(s); },
    scBeforeText(){ return "moss " + this.scSym + "img\nmoss " + this.scSym + "img webp 60% *.png"; },
    // ★ V-298：右列要**把前缀高亮**（`mo` 亮、`img` 正常）—— 照那份稿子的视觉引导。
    //   `scPrefix` 已经洗过（只剩字母/数字/-/_），拼进 HTML 安全。
    scNowHtml(){
      const p = this.scPrefix, m = this.scMode;
      const hl = s => '<span class="sc-hl">' + s + '</span>';
      if (m === 1) return hl(p) + " " + esc(this.scSym) + "img\n" + hl(p) + " " + esc(this.scSym) + "img webp 60% *.png";
      if (m === 2) return hl(p) + "img\n" + hl(p) + "img webp 60% *.png";
      return hl("moss") + " " + esc(this.scSym) + "img\n" + hl("moss") + " " + esc(this.scSym) + "img webp 60% *.png";
    },

  },
  methods: {
    icon(name){ return ico(name, "i"); },
    isAi(g){ return this.isAiName(g && g.name); },
    // 短名设置那一组（`V-298`）—— 模板里要给它单画一块（前缀 + 三段模式 + 对比预览）
    isShortcut(g){ return !!(g && (g.items || []).some(it => it.key === "shortcut.prefix")); },
    // 命令接入那一组（`V-299`）—— 除通用开关外，再画一块 cd 增强
    isAccess(g){ return this.isAccessName(g && g.name); },
    isAccessName(name){
      const g = (this.groups || []).find(x => x.name === name);
      return !!(g && (g.items || []).some(it => it.key === "path.moss"));
    },
    async cdLoad(){
      try {
        const r = await pywebview.api.cd_state();
        this.cd.any = !!(r && r.any);
        this.cd.profiles = (r && r.profiles) || [];
      } catch(e){ /* 拿不到就当未装 */ }
      this.cd.loaded = true;
    },
    async cdToggle(){
      if (this.cd.busy) return;
      if (this.cd.any) await this.cdUninstall(); else await this.cdInstall();
    },
    async cdInstall(){
      this.cd.busy = true;
      const r = await pywebview.api.cd_install();
      this.cd.busy = false;
      await this.cdLoad();
      toast(r && r.ok ? "已装上 cd 增强 —— 新开一个 PowerShell 窗口才生效" : "没装上", !(r && r.ok));
    },
    async cdUninstall(){
      this.cd.busy = true;
      const r = await pywebview.api.cd_uninstall();
      this.cd.busy = false;
      await this.cdLoad();
      toast(r && r.ok ? "已卸掉 cd 增强" : "没卸掉", !(r && r.ok));
    },
    setScMode(m){
      // 三种程度互斥：1 = 仅前缀（生成 `<前缀>`，= moss）；2 = 前缀+包名（生成 `<前缀><包名>`）；0 = 都关
      this.setVal("shortcut.mo", m === 1);
      this.setVal("shortcut.pkg", m === 2);
    },
    isAiName(name){
      const g = (this.groups || []).find(x => x.name === name);
      return !!(g && (g.items || []).some(it => it.key === "ai.active"));
    },
    /* ---- AI 那一组（`V-139`：名字 / 接口地址 / 密钥 / 模型）—— 全走宿主，界面不解析 TOML ---- */
    // 接口地址 / 密钥 / 模型 **三样都齐**才让保存和测试（V-151）。
    // ★ 密钥：这一组已经存过一把（列表摘要里的 has_key）也算齐 —— 不然"编辑旧配置"时
    //   输入框是空的（占位写着"已保存，留空不改"），会被判成没填、按钮永远灰着。
    aiFilled(){
      if (!String(this.aiVal("base_url") || "").trim()) return false;
      if (!this.aiModelList().length) return false;
      if (String(this.aiVal("api_key") || "").trim()) return true;
      if (this.ai.creating) return false;
      return !!(((this.ai.summary || {})[this.ai.name] || {}).has_key);
    },
    aiVal(k){
      if (Object.prototype.hasOwnProperty.call(this.ai.draft, k)) return this.ai.draft[k];
      if (k === "name") return this.ai.name;
      // 打码的那串**不当值填进框里** —— 不然保存时会把 "sk-a…7890" 存成真 key
      // 打码那串永远不当值填进框；只有"进编辑时真去读过明文"（`V-159`）才显示
      if (k === "api_key") return this.ai.keyReal ? (this.ai.params.api_key || "") : "";
      // 模型在库里是**列表**，在框里是「一行一个」的文本
      if (k === "model"){
        const m = this.ai.params.model;
        return (Array.isArray(m) ? m : (m ? [m] : [])).join("\n");
      }
      const v = this.ai.params[k];
      return v == null ? "" : v;
    },
    aiModelList(){
      return String(this.aiVal("model") || "").split(/[\r\n,]+/)
        .map(s => s.trim()).filter(Boolean);
    },
    aiKeyPh(){
      if (this.ai.keyReal) return "";
      // 新建的时候**没有"已保存的密钥"这回事**（`ai.params` 还留着上一组读出来的东西）
      if (this.ai.creating) return "sk-xxxxxxxxxxxxxxxx";
      return this.ai.params.api_key ? "已保存，留空不改" : "sk-xxxxxxxxxxxxxxxx";
    },
    aiSet(k, v){
      this.ai.draft[k] = v;
      this.ai.status = "";            // 改了参数，上次那个测试结果就不算数了
    },
    aiDirty(){ return Object.keys(this.ai.draft).length > 0; },
    // 列表里那一行的小字：地址 · 第一个模型（+N）—— 就这些，别的交给高亮标签
    aiSummary(n){
      return String(((this.ai.summary || {})[n] || {}).base_url || "")
        .replace(/^https?:\/\//, "");
    },
    aiNewName(base){
      // 名字撞了就在后面加 -2 / -3…（点预制参数时用）
      let n = String(base || "").trim() || "我的AI", i = 2;
      while (this.ai.profiles.indexOf(n) >= 0){ n = base + "-" + i; i++; }
      return n;
    },
    async aiLoad(name){
      const r = await pywebview.api.ai_config(name || "", false);
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读不到"), true); return false; }
      this.ai.loaded = true;
      this.ai.active = r.active || "";
      this.ai.profiles = r.profiles || [];
      this.ai.summary = r.summary || {};
      this.ai.name = r.name || "";
      this.ai.params = r.params || {};
      this.ai.draft = {};
      this.ai.status = "";
      this.ai.creating = false;      // 从库里读出来的这一组：不是"新建"
      this.ai.showKey = false;
      this.ai.keyReal = false;
      return true;
    },
    async aiLoadPresets(){
      if (this.ai.presets.length) return;
      const r = await pywebview.api.ai_presets();
      this.ai.presets = (r && r.presets) || [];
    },
    // 稿子里的几个内联图标（人物 / 加号 / 左箭头）—— 我们的图标库（lucide）里没有一样的，
    // 所以照抄它的 path 存成图标文件（`system/icon/svg/moss-*.svg`）。
    // ★ `V-257`：AI 那一组的标记**搬进 `system/icon/svg/` 了** ——
    //   顶层「AI」选项卡也要用同一个标记，两处各抄一段 path 迟早漂移。
    // ★ `V-386`：那枚标记从 OpenAI 换成 **DeepSeek**（`moss-deepseek.svg`，官方 mark）。
    // ★ `V-267`：那三条 path 也搬进文件了（`moss-user` / `moss-plus` / `moss-back`）——
    //   这一处代码从 15 行缩成 1 行，画笔（1.5 描边那套）跟别的图标一样写在文件里。
    aiSvg(name){
      // ★ `V-386`：名字**先拼进变量**再传 —— 直接在调用里拼前缀会被 `tools/界面检查.py`
      //   当成"用了一个叫 moss- 的图标"（它扫的是字面量，连注释里的也算）。
      const key = "moss-" + name;
      return ico(key, "i");
    },
    // 点路径里的任意一段（`V-198`）：用系统默认方式打开"到这一段为止"的那个路径
    async openSeg(s){ if (s && s.path) await pywebview.api.open_path(s.path); },
    // AI 页在底栏左边显示什么（V-155）—— 和别的页一个位置、一个样式
    aiFootText(){
      if (this.ai.mode !== "edit") return "";
      if (!this.aiFilled()) return "把接口地址 / 密钥 / 模型 填全";
      if (!this.aiDirty()) return "";        // `V-159`：没改动不是错，别在左下角挂一句
      return "改动还没保存";
    },
    // 框里那只眼睛：只切「明文 / 圆点」，**不碰 draft / 不问宿主**（V-149）
    aiToggleKey(){ this.ai.showKey = !this.ai.showKey; },
    // ---- 三张脸之间走：列表 ⇄ 选服务商 ⇄ 编辑（`V-142`，照那份 UI 稿子）----
    // 模板格子上那行小字：把地址里的协议头去掉，只留主机名（短、认得出来就行）
    aiHost(url){
      return String(url || "").replace(/^https?:\/\//, "").replace(/\/.*$/, "");
    },
    // 「添加 AI 配置」：去选服务商那一步（不在列表里直接摊开表单）
    async aiTemplates(){
      await this.aiLoadPresets();
      this.ai.mode = "tpl";
      this.ai.status = "";
    },
    // 选服务商那一步的「返回」
    aiList(){
      this.ai.mode = "list";
      this.ai.creating = false;
      this.ai.draft = {};
      this.ai.status = "";
      this.aiLoad("");
    },
    // 编辑那一步的「返回 / 取消」：没保存的改动先问一句
    aiCancel(){
      const go = () => {
        this.ai.mode = "list";
        this.ai.creating = false;
        this.ai.draft = {};
        this.ai.showKey = false;
        this.ai.keyReal = false;
          this.ai.status = "";
        this.aiLoad("");
      };
      // ★ V-146：返回**不再二次确认**（你说的）—— 直接回去，改动丢掉就丢掉
      go();
    },
    // 列表里某一张卡片的「编辑」：进编辑态，表单就是这一组现在的样子
    // ★ `V-159`：顺便把**已存的密钥读成明文填进去**（你说的"编辑以后 API KEY 应该显示"）——
    //   这是本机自己的配置、明文就存在 config.toml 里，显示出来才改得动。
    async aiEdit(n){
      if (this.aiDirty() && this.ai.name === n && this.ai.mode === "edit") return;
      const r = await this.aiLoad(n);
      if (!r) return;
      this.ai.mode = "edit";
      this.ai.status = "";
      const rr = await pywebview.api.ai_config(n, true);
      if (rr && rr.ok){
        this.ai.params = Object.assign({}, this.ai.params,
                                       {api_key: (rr.params || {}).api_key || ""});
        this.ai.keyReal = true;
      }
    },
    // 选服务商里点某一家：把名字 / 地址 / 模型填进表单，只等你粘 key（**不写盘**）
    aiUsePreset(p){
      this.ai.draft = {name: this.aiNewName(p.name), base_url: p.base_url || "",
                       model: (p.model || []).join("\n"), api_key: ""};
      this.ai.creating = true;
      this.ai.from = p.name;                       // 标题要写「配置 DeepSeek」（照稿子）
      this.ai.mode = "edit";
      this.ai.status = "";
      this.$nextTick(() => {
        const box = document.querySelector('.ai-fgroup[data-ai="api_key"] input');
        if (box) box.focus();
      });
    },
    // 「自定义」= 名字之外都空着，自己填
    aiBlank(){
      this.ai.draft = {name: this.aiNewName("我的AI"), base_url: "", model: "", api_key: ""};
      this.ai.creating = true;
      this.ai.from = "自定义";
      this.ai.mode = "edit";
      this.ai.status = "";
      this.$nextTick(() => {
        const box = document.querySelector('.ai-fgroup[data-ai="base_url"] input');
        if (box) box.focus();
      });
    },
    aiNameNow(){
      const v = Object.prototype.hasOwnProperty.call(this.ai.draft, "name")
        ? this.ai.draft.name : this.ai.name;
      return String(v || "").trim();
    },
    async aiSave(){
      const name = this.aiNameNow();
      if (!name){ toast("先起个名字", true); return; }
      let old = this.ai.name;
      const d = this.ai.draft;
      // 新建（点了预制参数 / 自定义）⇒ 全新一组；否则才可能是在给**当前这组改名**
      const creating = !old || this.ai.creating;
      const fields = {};
      // 全新的一组：三个字段都给（哪怕是空的，也算"我有这一组了"）
      if (creating || Object.prototype.hasOwnProperty.call(d, "base_url"))
        fields.base_url = String(this.aiVal("base_url") || "").trim();
      if (creating || Object.prototype.hasOwnProperty.call(d, "model"))
        fields.model = this.aiModelList();
      // ★ 密钥**只在你真填过的时候才送**：没填就一个字都别动（不然会把已有的 key 抹成空）
      if (creating || Object.prototype.hasOwnProperty.call(d, "api_key")) fields.api_key = d.api_key;
      if (!creating && !Object.keys(fields).length && name === old){ toast("没有改动"); return; }
      this.ai.busy = true;
      // 改名 = 换一组：**让宿主整块搬**（`--ai-rename`）—— 不搬的话密钥拿不到，
      // 面板上只有打码那串，按新名字再存一遍就等于把 key 丢了。
      if (!creating && name !== old){
        const rn = await pywebview.api.ai_rename(old, name);
        if (!rn || !rn.ok){
          this.ai.busy = false;
          toast("✗ " + ((rn && rn.msg) || "改不了名字"), true);
          return;
        }
      }
      let r = {ok: true, msg: ""};
      if (Object.keys(fields).length) r = await pywebview.api.ai_save(name, fields);
      this.ai.busy = false;
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没存上"), true); return; }
      await this.aiLoad(name);
      this.ai.mode = "list";          // 存完回列表（照那份 UI 稿子的手感）
      toast("已保存「" + name + "」");
    },
    // ---- 列表里那三颗（都带组名：列表一屏好几行，不能只认"当前那组"）----
    aiDel(name){
      name = name || this.ai.name;
      if (!name) return;
      askConfirm("删除这一组？", "只删配置，不影响别的东西。",
                 async () => {
        const r = await pywebview.api.ai_delete(name);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没删掉"), true); return; }
        // ★ 删完一律重新读"当前那组 / 第一组"（传名字的话，删掉的正好是它 ⇒ 读不到 ⇒ 列表不刷新，
        //   表现就是"点了删除没反应"，V-143 的 bug）
        if (this.ai.mode === "edit" && this.ai.name === name){
          this.ai.mode = "list"; this.ai.creating = false; this.ai.draft = {};
        }
        await this.aiLoad("");
        toast("删了「" + name + "」");
      });
    },
    async aiUse(name){
      name = name || this.ai.name;
      if (!name || name === this.ai.active) return;
      const r = await pywebview.api.ai_set_active(name);
      if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没切成"), true); return; }
      this.ai.active = name;
      toast("当前：" + name);
    },
    // 测连接：**不用先保存**（V-147）—— 把表里现在的值一起送过去，宿主拿它们当临时覆盖。
    // 密钥只在你这次真填了 / 点过「眼睛」时才送（不然送的是打码那串，等于测不了）。
    async aiTest(name){
      name = name || this.ai.name;
      const fields = {};
      fields.base_url = String(this.aiVal("base_url") || "").trim();
      fields.model = this.aiModelList();
      const k = String(this.aiVal("api_key") || "");
      if (k) fields.api_key = k;
      this.ai.busy = true;
      this.ai.status = "正在连…"; this.ai.statusOk = false;
      const r = await pywebview.api.ai_test(name || "", fields);
      this.ai.busy = false;
      this.ai.statusOk = !!(r && r.ok);
      const raw = String((r && r.msg) || "").trim();
      this.ai.status = this.aiShort(raw, this.ai.statusOk);
      // 原始报文只在跟前那句"不一样"的时候才给「详情」（免得重复一遍废话）
      this.ai.detail = (raw && raw !== this.ai.status) ? raw : "";
      this.ai.open = false;
    },
    aiCanQuery(){
      const base = String(this.aiVal("base_url") || "").trim();
      if (!base) return false;
      const k = String(this.aiVal("api_key") || "").trim();
      if (k) return true;
      if (!this.ai.creating && (((this.ai.summary || {})[this.ai.name] || {}).has_key)) return true;
      return /^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?(\/|$)/i.test(base);
    },
    aiQueryFields(){
      const f = {base_url: String(this.aiVal("base_url") || "").trim()};
      const k = String(this.aiVal("api_key") || "").trim();
      if (k) f.api_key = k;
      return f;
    },
    aiQueryDone(r){
      const ok = !!(r && r.ok);
      this.ai.busy = false;
      this.ai.statusOk = ok;
      this.ai.status = (r && r.msg) || (ok ? "完成" : "没成");
      this.ai.detail = (r && r.detail) || "";
      this.ai.open = false;
      return r;
    },
    async aiFetchModels(){
      if (this.ai.busy) return;
      this.ai.busy = true;
      this.ai.status = "正在获取模型…";
      this.ai.statusOk = false;
      this.ai.detail = "";
      let r = null;
      try {
        r = await pywebview.api.ai_models(this.ai.name || "", this.aiQueryFields());
      } catch(e){ r = {ok: false, msg: "获取模型失败：" + (e && e.message ? e.message : e)}; }
      this.aiQueryDone(r);
      const models = (r && r.models) || [];
      if (r && r.ok && models.length){
        this.aiSet("model", models.join("\n"));
        this.ai.status = "已获取 " + models.length + " 个模型，已填入列表";
        this.ai.statusOk = true;
      } else if (r && r.ok) {
        this.ai.status = "接口通了，但没拿到模型名";
        this.ai.statusOk = false;
      }
      this.$forceUpdate();
    },
    async aiFetchBalance(){
      if (this.ai.busy) return;
      this.ai.busy = true;
      this.ai.status = "正在查询余额…";
      this.ai.statusOk = false;
      this.ai.detail = "";
      let r = null;
      try {
        r = await pywebview.api.ai_balance(this.ai.name || "", this.aiQueryFields());
      } catch(e){ r = {ok: false, msg: "查余额失败：" + (e && e.message ? e.message : e)}; }
      this.aiQueryDone(r);
      this.$forceUpdate();
    },
    // 把宿主那一行文本变成人话：成功 = 「连接成功（HTTP 200 · 模型 xxx）」；
    // 失败 = 「连接失败：<原因>」。原始报文另存（上面那个 detail）。
    aiShort(raw, ok){
      const s = String(raw || "").replace(/^\[错误\]\s*/, "").trim();
      if (ok){
        const http = (s.match(/HTTP\s*(\d+)/) || [])[1] || "";
        const model = (s.match(/模型\s*([^）)\s]+)/) || [])[1] || "";
        const bits = [http ? ("HTTP " + http) : "", model].filter(Boolean).join(" · ");
        return "连接成功" + (bits ? ("（" + bits + "）") : "");
      }
      const why = s.replace(/^没连上\s*\/\s*报错：/, "").replace(/^没连上\s*\/\s*报错:/, "").trim();
      const short = why.length > 60 ? (why.slice(0, 60) + "…") : why;
      return "连接失败" + (short ? ("：" + short) : "");
    },
    fieldsOf(g){ return (g.items || []).filter(it => it.type !== "bool"); },
    rowsOf(g){ return (g.items || []).filter(it => it.type === "bool"); },
    groupOf(key){
      const g = this.groups.find(x => (x.items || []).some(it => it.key === key));
      return g ? g.name : "";
    },
    rowClass(key){
      const mine = (this.problems || []).filter(p => p.key === key || (p.also || []).indexOf(key) >= 0);
      if (mine.some(p => p.level !== "warn")) return "bad";
      if (mine.length) return "warn";
      return "";
    },
    probText(key){
      // ★ 原因只写在**主**那一项上；被牵连的那项只标色（同一句话不必说两遍）
      return (this.problems || []).filter(p => p.key === key)
        .map(p => (p.level === "warn" ? "提醒：" : "") + p.why).join(" ");
    },
    navTitle(name){
      const st = this.badGroups[name];
      if (st === "bad") return "这一组里有冲突";
      if (st === "warn") return "这一组里有提醒";
      return "";
    },
    clampNum(v){
      const n = parseInt(v, 10);
      return isFinite(n) ? Math.max(0, Math.min(20, n)) : 0;   // `V-159`：0 也允许（只看当前目录）
    },

    /* ---- 打开 / 关闭 / 切换分类 ---- */
    async open(){
      const r = await pywebview.api.settings();
      if (!r || !r.ok){ toast("✗ 读设置失败：" + ((r && r.msg) || ""), true); return; }
      this.path = r.path || "";
      this.groups = r.groups || [];
      this.items = {}; this.values = {}; this.orig = {};
      this.groups.forEach(g => (g.items || []).forEach(it => {
        this.items[it.key] = it;
        this.values[it.key] = it.value;
        this.orig[it.key] = it.value;
      }));
      this.msg = r.msg || "";
      this.problems = []; this.notes = {}; this.live = "";
      this.saving = false;
      this.setActive((this.groups[0] || {}).name || "");
      this.show = true;
      if (this.msg) toast(this.msg);
      this.scheduleCheck(0);          // 立刻问一次：把 hover 里那些「现在这样」填上
    },
    close(){
      if (this._timer) clearTimeout(this._timer);
      this._seq++;                    // 关掉之后飞回来的检查结果一律作废
      this.hideTip();
      this.show = false;
    },
    setActive(gid){
      this.active = gid;
      this.hideTip();
      // 切到 AI 那一页时才去问宿主（省得每次开设置都多跑两条命令）
      if (this.isAiName(gid)){ this.aiLoadPresets(); if (!this.ai.loaded) this.aiLoad(""); }
      // 切到「命令接入」时才问一次 cd 增强的状态
      if (this.isAccessName(gid)) this.cdLoad();
    },
    setVal(key, v){
      this.values[key] = v;
      /* ★ `V-275`（你定的）：**打字不再问宿主**。以前这里调 `scheduleCheck()` —— 停手 250ms
         就去起一个 `moss.exe`（真机 ≈1 秒）只为标个红。现在改成：
           · 有没有改动 = **纯前端**算（`changed` 比 values 和 orig）；
           · 「保存」按钮亮不亮只看"改没改"（不看宿主回的 problems）；
           · 校验留到**点保存那一次**（`--settings-set` 本来就一次往返，顺带把
             problems / notes / live 一起带回来）—— 也就是"点下去才告诉你哪儿不行"。
         代价：丢掉"边改边标红 + 组底部那段预览实时更新"（预览会标成"按已保存的值算的"）。 */
      this.$forceUpdate();
    },
    bump(key, d){
      this.setVal(key, this.clampNum((parseInt(this.values[key], 10) || 1) + d));
    },

    /* ---- 校验（问宿主：规则只有 core 那一份）---- */
    scheduleCheck(delay){
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this.check(), delay == null ? 250 : delay);
    },
    async check(){
      this._timer = null;
      const seq = ++this._seq;
      const r = await pywebview.api.settings_check(Object.assign({}, this.values));
      if (seq !== this._seq) return;   // 慢的那次回来了也别盖掉新的
      this.problems = (r && r.problems) || [];
      this.notes = (r && r.notes) || {};
      this.live = (r && r.live) || "";
      if (r && r.msg) this.msg = r.msg;
      if (this.tip.show && this.tip.key) this.showTip(this.tip.key);
    },

    /* ---- 保存 / 只送改过的那几项 ---- */
    pairs(){
      const out = {};
      this.changed.forEach(k => { out[k] = this.values[k]; });
      return out;
    },
    async save(){
      const pairs = this.pairs();
      if (!Object.keys(pairs).length){ toast("没有改动"); this.close(); return; }
      this.saving = true;
      const r = await pywebview.api.settings_save(pairs);
      this.saving = false;
      const list = (r && r.problems) || [];
      // ★ `V-275`：这一趟的返回里**还带着 notes / live**（宿主 `--settings-set` 是
      //   `with_notes=True`）—— 存成功就直接用它们刷新，**不再多跑一趟 `--settings-check`**。
      if (r && r.notes) this.notes = r.notes;
      if (r && r.live) this.live = r.live;
      if (!r || !r.ok || list.some(p => p.level !== "warn")){
        this.problems = list.length ? list
          : [{key: "", why: (r && r.msg) || "没拿到失败原因", level: "error", also: []}];
        toast("没保存 —— 看标红的地方", true);
        return;
      }
      // ★ `V-275`：成功也可能带着 warn（"提醒，不拦保存"）—— **留着**，不然那条提醒白算了。
      this.problems = list;
      Object.keys(pairs).forEach(k => { this.orig[k] = this.values[k]; });
      // ★ `V-305`：**符号改了** ⇒ 界面立刻跟着变（列表行 / 详情 / 标题…都照它拼），
      //   不用重启（重启也行 —— payload 里也带着）。空串就照空串显示（那是"裸名跑包"档）。
      if (this.values["symbols.plugin_mode"] !== undefined){
        PSYM = this.values["symbols.plugin_mode"];
        renderList(); renderHist(); renderDetail();
      }
      // ★ `V-298`：宿主存完会回"具体做了什么"（加/删 PATH、生成/删哪些短命令）。
      //   **有具体的就别再弹那句泛泛的「已保存」** —— 否则一次保存冒两个弹窗（你报的）。
      // ★ `V-367`：现在**连那些具体回执也并进同一条** —— 以前除了"已保存"还会连着弹最多
      //   4 颗胶囊（改 PATH 一条、生成短命令一条…），一次点保存满屏提示。
      const scMsgs = (r && r.shortcut) || [];
      const head = list.length ? ("已保存（有 " + list.length + " 条提醒）")
                               : "已保存到 config.toml";
      const det = scMsgs.slice(0, 4).join("；") + (scMsgs.length > 4 ? ("；…还有 " + (scMsgs.length - 4) + " 条") : "");
      toast(det ? (head + "；" + det) : (head + "（下一次启动 moss 生效）"));
      // ★ `V-275`：**不关面板** —— 按钮自己变灰（没有改动了）、提醒 / 预览留在眼前，
      //   这就是你描述的那个状态："点保存 → 灰一下 → 干完回到没编辑过的样子"。
    },

    /* ---- hover 提示（`?` 上悬停）---- */
    showTip(key, ev){
      const it = this.items[key];
      if (!it) return;
      const anchor = (ev && ev.target) ||
        document.querySelector('#set-body .set-info[data-tip-key="' + key + '"]');
      const r = anchor ? anchor.getBoundingClientRect() : {left: 40, bottom: 40, top: 40};
      this.tip = {
        show: true, key: key, title: it.label || key, hint: it.hint || "",
        now: this.notes[key] || "",
        problems: (this.problems || []).filter(p => p.key === key || (p.also || []).indexOf(key) >= 0),
        x: 0, y: 0,
      };
      this.$nextTick(() => {
        const t = document.getElementById("tip");
        const w = t ? t.offsetWidth : 300;
        const h = t ? t.offsetHeight : 80;
        let x = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
        let y = r.bottom + 8;
        if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
        this.tip.x = Math.round(x); this.tip.y = Math.round(y);
      });
    },
    hideTip(){ this.tip.show = false; },
  },
};

/* ---- 挂载 + 给外面的几个门面（别的地方只认这几个名字）---- */
let _settingsApp = null;

function settingsApp(){
  if (!_settingsApp){
    const host = document.getElementById("settings-host");
    if (!host) return null;
    _settingsApp = mountVue(MossSettings, host);
  }
  return _settingsApp;
}
function openSettings(){ const a = settingsApp(); return a ? a.open() : null; }
function closeSettings(){ const a = settingsApp(); if (a) a.close(); }
function saveSettings(){ const a = settingsApp(); return a ? a.save() : null; }
function setActive(gid){ const a = settingsApp(); if (a) a.setActive(gid); }
function showTip(key, ev){ const a = settingsApp(); if (a) a.showTip(key, ev); }
function hideTip(){ const a = settingsApp(); if (a) a.hideTip(); }
function collectSettings(){ const a = settingsApp(); return a ? a.pairs() : {}; }
