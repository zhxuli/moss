const MossSettings = {
  name: "moss-settings",
  template: `
<div id="settings" :class="{on: show}" @click.self="close">
  <div class="card wide">
    <div class="set-head">
      <h3>设置</h3>
      

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

          
          <template v-if="!isAi(g)">
            <h3 class="set-ptitle">{{ g.name }}</h3>
            <p class="set-pdesc" v-if="g.blurb">{{ g.blurb }}</p>
          </template>

          




          <div class="set-ai" v-if="isAi(g)">
            
            <div class="ai-view active" id="ai-view-list" v-if="ai.mode === 'list'">
              <div class="ai-scroll">
              <div class="ai-vhead">
                <h3 class="ai-vtitle">AI 服务配置</h3>
                <p class="ai-vdesc">管理你接入的各个大语言模型服务，支持多组配置切换。</p>
              </div>

              <div class="ai-empty" id="ai-empty" v-if="!ai.profiles.length">
                <span class="ai-eico" v-html="aiSvg('user')"></span>
                <h4>暂无 AI 配置</h4>
                <p>请点击下方按钮，添加并配置你的第一个 AI 引擎</p>
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

              




              <div class="ai-snd" id="ai-snd">
                



                <div class="ai-snd-title">
                  <a class="ai-snd-site" href="https://sounddino.com/zh/" target="_blank"
                     rel="noopener" title="去 sounddino 找音效"
                     @click.prevent="sndSite()">音效提醒</a>
                </div>
                <div class="ai-snd-grid">
                  <div v-for="k in sndKinds" :key="k.key" class="ai-snd-item"
                       :class="{over: snd.hot === k.key, off: !sndOn(k.key)}" :data-snd="k.key"
                       @dragover.prevent="sndHot(k.key)" @drop.prevent>
                    <div class="ai-snd-text" :title="sndPickTip(k.key)" @click="sndPick(k.key)">
                      <span class="ai-snd-name">{{ k.title }}</span>
                      <span class="ai-snd-file">{{ sndFile(k.key) }}</span>
                    </div>
                    <div class="ai-snd-right">
                      <button v-if="!sndBuiltin(k.key)" class="ai-snd-reset" type="button"
                              :data-snd-reset="k.key" title="回到出厂自带的那一个"
                              @click.stop="sndReset(k.key)">恢复</button>
                      <button class="ai-snd-play" type="button" :data-snd-try="k.key"
                              title="试听"
                              @click.stop="sndTry(k.key)" v-html="icon('play')"></button>
                      <label class="ai-snd-switch" :data-snd-sw="k.key"
                             :title="sndOn(k.key) ? '开 —— 点一下关掉' : '关 —— 点一下打开'">
                        <input type="checkbox" :checked="sndOn(k.key)"
                               @change="sndToggle(k.key, $event)">
                        <span class="ai-snd-slider"></span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
              </div>
            </div>

            
            <div class="ai-view active" id="ai-view-tpl" v-else-if="ai.mode === 'tpl'">
              <div class="ai-scroll">
              <button class="ai-back" id="ai-back" type="button" title="返回列表"
                      aria-label="返回列表" @click="aiList()"
                      v-html="aiSvg('back')"></button>
              <div class="ai-vhead">
                <h3 class="ai-vtitle">选择服务商</h3>
                <p class="ai-vdesc">选择一个预设模板以快速填入接口信息，或选择自定义。</p>
              </div>
              <div class="ai-tplgrid" id="ai-tplgrid">
                <div v-for="p in ai.presets" :key="p.name" class="ai-tpl" :data-preset="p.name"
                     @click="aiUsePreset(p)">
                  <span class="ai-tico">{{ p.name.slice(0, 1) }}</span>
                  <span class="ai-tinfo"><b>{{ p.name }}</b><i>{{ p.desc || aiHost(p.base_url) }}</i></span>
                </div>
                <div class="ai-tpl" data-preset="自定义" id="ai-blank" @click="aiBlank()">
                  <span class="ai-tico">＋</span>
                  <span class="ai-tinfo"><b>自定义</b><i>手动填写基地址</i></span>
                </div>
              </div>
              </div>
            </div>

            
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
                         title="只给自己看。改了名字保存 = 给这一组改名。">配置名称别名</label>
                  <input class="ai-input" id="ai-in-name" :data-ai="'name'" type="text"
                         spellcheck="false" autocomplete="off" placeholder="例如：主用 DeepSeek"
                         :value="aiVal('name')" @input="aiSet('name', $event.target.value)">
                </div>
                <div class="ai-fgroup" data-ai="base_url">
                  <label class="ai-flabel" for="ai-in-url"
                         title="OpenAI 兼容的地址，填到 /v1 为止。">接口地址 (Base URL)</label>
                  <input class="ai-input" id="ai-in-url" type="text" spellcheck="false"
                         autocomplete="off" placeholder="https://api..."
                         :value="aiVal('base_url')" @input="aiSet('base_url', $event.target.value)">
                </div>
              </div>

              <div class="ai-fgroup" data-ai="api_key">
                <label class="ai-flabel" for="ai-in-key"
                       title="明文存在 user_data/config.toml；留空 = 不修改。">API Key (密钥)</label>
                <div class="ai-keywrap" :class="{nokey: !aiVal('api_key')}">
                  <input class="ai-input" id="ai-in-key" :type="ai.showKey ? 'text' : 'password'"
                         spellcheck="false" autocomplete="off" :placeholder="aiKeyPh()"
                         :value="aiVal('api_key')" @input="aiSet('api_key', $event.target.value)">
                  
                  <button class="ai-eye" id="ai-eye" type="button"
                          :title="ai.showKey ? '藏起来' : '看明文'"
                          @click="aiToggleKey()"
                          v-html="icon(ai.showKey ? 'eye-off' : 'eye')"></button>
                </div>
              </div>

              <div class="ai-fgroup ai-query" data-ai="query" v-if="aiCanQuery()">
                <label class="ai-flabel">快捷操作</label>
                <div class="ai-query-btns">
                  <button class="ai-query-btn" id="ai-fetch-models" type="button"
                          :disabled="ai.busy || aiPingBusy" @click="aiFetchModels"
                          title="从接口的 /models 获取可用模型，自动填入下面的列表（不用先保存）">
                    <span v-html="icon('refresh-cw')"></span><span>获取可用模型</span>
                  </button>
                  <button class="ai-query-btn" id="ai-fetch-balance" type="button"
                          :disabled="ai.busy || aiPingBusy" @click="aiFetchBalance"
                          title="查询这个接口的账户余额（DeepSeek / Kimi / OpenRouter / 硅基流动等已知接口）">
                    <span v-html="icon('gauge')"></span><span>查询余额</span>
                  </button>
                  

                  <button class="ai-query-btn" id="ai-ping" type="button"
                          :disabled="ai.busy || aiPingBusy" @click="aiPingAll()"
                          :title="aiPingTip">
                    <span v-html="icon('plug')"></span>
                    <span>{{ aiPingBusy ? ("测试中 " + aiPingDone + "/" + aiPingTotal) : "测试可用性" }}</span>
                  </button>
                </div>
                

                <div class="ai-ping" id="ai-ping-box" v-if="ai.ping.rows.length">
                  <div class="ai-ping-head">
                    <span>可用 <b class="ok-n">{{ aiPingOkN }}</b> 个 · 不通
                      <b class="bad-n">{{ aiPingBad.length }}</b> 个</span>
                    <button class="ai-ping-clear" id="ai-ping-clear" type="button"
                            v-if="aiPingBad.length && !aiPingBusy"
                            title="把不通的那些从「可用模型列表」里删掉（列表还没保存，点保存才写进配置）"
                            @click="aiPingDropBad()">清掉不通的（{{ aiPingBad.length }}）</button>
                  </div>
                  <div v-for="r in ai.ping.rows" :key="r.model" class="ai-ping-row"
                       :class="r.state === 'done' ? (r.ok ? 'ok' : 'bad') : 'wait'">
                    <span class="ai-ping-dot"></span>
                    <span class="ai-ping-name" :title="r.model">{{ r.model }}</span>
                    <span class="ai-ping-ms" v-if="r.state === 'done' && r.ok">{{ r.ms }}ms</span>
                    <span class="ai-ping-msg" :title="r.msg">{{ aiPingRowText(r) }}</span>
                  </div>
                </div>
              </div>

              <div class="ai-fgroup" data-ai="model">
                <label class="ai-flabel" for="ai-in-models"
                       title="一行一个，第一个当默认；跑包时注入 MOSS_AI_MODEL / MOSS_AI_MODELS。">可用模型列表 (换行分割)</label>
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
                  
                  <button class="ai-more" id="ai-more" type="button" v-if="ai.detail"
                          @click="ai.open = !ai.open">{{ ai.open ? "收起" : "详情" }}</button>
                  <code class="ai-detail" id="ai-detail" v-if="ai.open && ai.detail">{{ ai.detail }}</code>
                </span>
              </div>

              </div>

            </div>
          </div>

          
          <template v-if="!isAi(g) && !isShortcut(g) && !isAccess(g)">
          
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

          
          <div v-if="g.live" class="set-live" id="set-live" :class="{bad: /^⚠/.test(live || '')}">
            <b>预览：</b> {{ live }}
            

            <span v-if="changed.length" style="opacity:.65">（改动还没保存，预览还是上一次的）</span>
          </div>

          </template>

          

          <div class="acc-card" id="set-acc" v-if="isAccess(g)">
            <div class="acc-row">
              <div class="acc-info">
                <h4 class="acc-title">加入系统 PATH</h4>
                <p class="acc-desc">开启后，可在任何终端直接通过 <code>moss</code> 命令唤起本程序。</p>
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
                  <span class="set-info" title="子进程不能改父 shell 的目录（系统限制）。不装：moss 用注入按键，屏幕上会显示那条 cd 命令、还会进历史；装了（推荐）：往 PowerShell 配置写个小函数，moss 只把路径交给 shell 自己切，屏幕无回显、不进历史。"
                        v-html="icon('info')"></span>
                </h4>
                <p class="acc-desc">实现原生级别的无痕目录切换，终端屏幕不留多余回显。</p>
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
                <span><b>卸载必读：</b>若准备彻底删除本软件，请务必先在这里<b>关掉这个开关（执行卸载）</b>，清掉终端里留下的配置。</span>
              </div>
              <div class="acc-subtitle">受控子环境列表</div>
              <div class="acc-env" v-for="p in cd.profiles" :key="p.path">
                <span>{{ p.label }}</span>
                <span class="acc-envstat" :class="{on: p.installed}">{{ p.installed ? "已注入" : "未注入" }}</span>
              </div>
              <div class="acc-env" v-if="!cd.profiles.length">
                <span class="dim">（还没读到环境状态）</span>
              </div>
            </div>
          </div>

          


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
              <div class="sc-ph">开启后长这样（新开一个终端才生效）</div>
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
      items: {},          
      values: {},         
      orig: {},           
      problems: [],
      notes: {},
      live: "",
      active: "",
      msg: "",            
      saving: false,
      tip: {show: false, x: 0, y: 0, title: "", hint: "", now: "", problems: []},

      ai: {loaded: false, busy: false, name: "", active: "", profiles: [], presets: [],
           summary: {},
           params: {}, draft: {}, status: "", statusOk: false, from: "", showKey: false,
           keyReal: false,
           detail: "", open: false,

           mode: "list",

           creating: false,

           ping: {running: false, rows: [], seq: 0}},

      cd: {loaded: false, busy: false, any: false, profiles: []},

      snd: {loaded: false, busy: false, hot: "", at: 0, items: {}},
      _timer: null,
      _seq: 0,
      _sndT: null,          
    };
  },
  computed: {
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
      return this.changed.length > 0 && !this.saving;
    },
    footText(){
      if (this.saving) return "正在保存…";

      if (this.errs) return "✗ " + this.errs + " 处冲突 —— 改好再点一次保存";
      if (this.changed.length){
        return "改了 " + this.changed.length + " 项 · 点保存写入 config.toml（下次启动 moss 生效）"
               + (this.msg ? "（" + this.msg + "）" : "");
      }

      return this.msg ? ("（" + this.msg + "）") : "";
    },
    footClass(){
      if (this.errs) return "bad";
      return this.changed.length ? "moved" : "";
    },

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

    aiPane(){ return this.isAiName(this.active); },

    scPrefix(){ return (String(this.values["shortcut.prefix"] || "").replace(/[^A-Za-z0-9_-]/g, "")) || "mo"; },
    scMode(){ return this.values["shortcut.pkg"] ? 2 : (this.values["shortcut.mo"] ? 1 : 0); },

    scSym(){ const s = this.values["symbols.plugin_mode"]; return s === undefined ? ":" : String(s); },
    scBeforeText(){ return "moss " + this.scSym + "img\nmoss " + this.scSym + "img webp 60% *.png"; },

    scNowHtml(){
      const p = this.scPrefix, m = this.scMode;
      const hl = s => '<span class="sc-hl">' + s + '</span>';
      if (m === 1) return hl(p) + " " + esc(this.scSym) + "img\n" + hl(p) + " " + esc(this.scSym) + "img webp 60% *.png";
      if (m === 2) return hl(p) + "img\n" + hl(p) + "img webp 60% *.png";
      return hl("moss") + " " + esc(this.scSym) + "img\n" + hl("moss") + " " + esc(this.scSym) + "img webp 60% *.png";
    },

    sndKinds(){
      return [
        {key: "finish", title: "任务结束"},
        {key: "warn", title: "需要你确认"},
      ];
    },

    aiPingBusy(){ return !!this.ai.ping.running; },
    aiPingTotal(){ return (this.ai.ping.rows || []).length; },
    aiPingDone(){ return (this.ai.ping.rows || []).filter(r => r.state === "done").length; },
    aiPingBad(){ return (this.ai.ping.rows || []).filter(r => r.state === "done" && !r.ok); },
    aiPingOkN(){ return (this.ai.ping.rows || []).filter(r => r.state === "done" && r.ok).length; },
    aiPingTip(){
      const n = this.aiModelList().length;
      if (!n) return "先在上面「可用模型列表」里填模型名（一行一个），再来测";
      return "挨个问一遍列表里的 " + n + " 个模型能不能用 —— 每个只花几个 token（只让它回两个字）";
    },

  },

  mounted(){
    window.__mossSndDrop = (items) => {
      if (!this.show || !this.snd.hot) return false;
      if (Date.now() - Number(this.snd.at || 0) > 3000) return false;
      const kind = this.snd.hot;
      const one = (items || []).filter(x => x && x.path && x.isDir !== true)[0] || null;
      this.snd.hot = ""; this.snd.at = 0;
      if (!one){
        toast("要拖一个音频文件进来（mp3 / wav / m4a …）", true);
        return true;
      }
      this.sndUsePath(kind, one.path);
      return true;
    };
  },
  beforeUnmount(){
    if (window.__mossSndDrop) window.__mossSndDrop = null;
    if (this._sndT) clearTimeout(this._sndT);
  },
  methods: {
    icon(name){ return ico(name, "i"); },
    isAi(g){ return this.isAiName(g && g.name); },

    isShortcut(g){ return !!(g && (g.items || []).some(it => it.key === "shortcut.prefix")); },

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
      } catch(e){  }
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

    sndOn(kind){ return !!((this.snd.items || {})[kind] || {}).on; },
    sndBuiltin(kind){ return ((this.snd.items || {})[kind] || {}).builtin !== false; },

    sndFile(kind){
      const it = (this.snd.items || {})[kind] || {};
      return it.name || "还没有音频";
    },
    sndPickTip(kind){
      const it = (this.snd.items || {})[kind] || {};
      return (it.path ? (it.path + " · ") : "")
        + "点一下换一个音频，也可以把音频文件拖到这一行上";
    },
    async sndLoad(){
      try{
        const r = await pywebview.api.sound_state();
        if (r && r.ok){ this.snd.items = r.items || {}; this.snd.loaded = true; }
      }catch(e){  }
    },

    sndApply(r){
      this.snd.busy = false;
      if (r && r.items) this.snd.items = r.items;
      this.$forceUpdate();
    },

    async sndToggle(kind, ev){
      if (this.snd.busy) return;
      const box = (ev && ev.target && ev.target.type === "checkbox") ? ev.target : null;
      const want = box ? !!box.checked : !this.sndOn(kind);
      this.snd.busy = true;
      let r = null;
      try{ r = await pywebview.api.sound_set(kind, want); }
      catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
      if (!r || !r.ok){
        this.snd.busy = false;
        if (box) box.checked = !want;
        toast("✗ " + ((r && r.msg) || "没改成"), true);
        return;
      }
      this.sndApply(r);
      toast(want ? "音效已打开" : "音效已关闭（这一类以后不再响）");
    },
    async sndPick(kind){
      if (this.snd.busy) return;
      this.snd.busy = true;
      let r = null;
      try{ r = await pywebview.api.sound_pick(kind); }
      catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
      if (r && r.cancelled){ this.snd.busy = false; return; }
      if (!r || !r.ok){
        this.snd.busy = false;
        toast("✗ " + ((r && r.msg) || "没换成"), true);
        return;
      }
      this.sndApply(r);
      toast(r.msg || "换好了");
      sndNotify(kind, true);        
    },
    async sndReset(kind){
      if (this.snd.busy) return;
      this.snd.busy = true;
      let r = null;
      try{ r = await pywebview.api.sound_reset(kind); }
      catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
      if (!r || !r.ok){
        this.snd.busy = false;
        toast("✗ " + ((r && r.msg) || "没恢复成"), true);
        return;
      }
      this.sndApply(r);
      toast(r.msg || "已回到出厂自带的那个");
      sndNotify(kind, true);
    },

    async sndUsePath(kind, path){
      if (this.snd.busy) return;
      this.snd.busy = true;
      let r = null;
      try{ r = await pywebview.api.sound_use(kind, String(path || "")); }
      catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
      if (!r || !r.ok){
        this.snd.busy = false;
        toast("✗ " + ((r && r.msg) || "换不成"), true);
        return;
      }
      this.sndApply(r);
      toast(r.msg || "换好了");
      sndNotify(kind, true);
    },
    sndTry(kind){ sndNotify(kind, true); },

    async sndSite(){
      let r = null;
      try{ r = await pywebview.api.open_url("https://sounddino.com/zh/"); }
      catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
      if (!r || !r.ok) toast("✗ 浏览器没能打开：" + ((r && r.msg) || "未知原因"), true);
    },

    sndHot(kind){
      this.snd.hot = kind;
      this.snd.at = Date.now();
      if (this._sndT) clearTimeout(this._sndT);
      this._sndT = setTimeout(() => {
        if (Date.now() - Number(this.snd.at || 0) > 900){ this.snd.hot = ""; this.snd.at = 0; }
      }, 1000);
    },
    setScMode(m){
      this.setVal("shortcut.mo", m === 1);
      this.setVal("shortcut.pkg", m === 2);
    },
    isAiName(name){
      const g = (this.groups || []).find(x => x.name === name);
      return !!(g && (g.items || []).some(it => it.key === "ai.active"));
    },

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

      if (k === "api_key") return this.ai.keyReal ? (this.ai.params.api_key || "") : "";

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

      if (this.ai.creating) return "sk-xxxxxxxxxxxxxxxx";
      return this.ai.params.api_key ? "已保存，留空不改" : "sk-xxxxxxxxxxxxxxxx";
    },
    aiSet(k, v){
      this.ai.draft[k] = v;
      this.ai.status = "";            

      if (k === "model") this.aiPingReset();
    },
    aiDirty(){ return Object.keys(this.ai.draft).length > 0; },

    aiSummary(n){
      return String(((this.ai.summary || {})[n] || {}).base_url || "")
        .replace(/^https?:\/\//, "");
    },
    aiNewName(base){
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
      this.ai.creating = false;      
      this.ai.showKey = false;
      this.ai.keyReal = false;

      this.aiPingReset();
      return true;
    },
    async aiLoadPresets(){
      if (this.ai.presets.length) return;
      const r = await pywebview.api.ai_presets();
      this.ai.presets = (r && r.presets) || [];
    },

    aiSvg(name){
      const key = "moss-" + name;
      return ico(key, "i");
    },

    async openSeg(s){ if (s && s.path) await pywebview.api.open_path(s.path); },

    aiFootText(){
      if (this.ai.mode !== "edit") return "";
      if (!this.aiFilled()) return "把接口地址 / 密钥 / 模型 填全";
      if (!this.aiDirty()) return "";        
      return "改动还没保存";
    },

    aiToggleKey(){ this.ai.showKey = !this.ai.showKey; },

    aiHost(url){
      return String(url || "").replace(/^https?:\/\//, "").replace(/\/.*$/, "");
    },

    async aiTemplates(){
      await this.aiLoadPresets();
      this.ai.mode = "tpl";
      this.ai.status = "";
    },

    aiList(){
      this.ai.mode = "list";
      this.ai.creating = false;
      this.ai.draft = {};
      this.ai.status = "";
      this.aiLoad("");
    },

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

      go();
    },

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

    aiUsePreset(p){
      this.ai.draft = {name: this.aiNewName(p.name), base_url: p.base_url || "",
                       model: (p.model || []).join("\n"), api_key: ""};
      this.ai.creating = true;
      this.ai.from = p.name;                       
      this.ai.mode = "edit";
      this.ai.status = "";
      this.$nextTick(() => {
        const box = document.querySelector('.ai-fgroup[data-ai="api_key"] input');
        if (box) box.focus();
      });
    },

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

      const creating = !old || this.ai.creating;
      const fields = {};

      if (creating || Object.prototype.hasOwnProperty.call(d, "base_url"))
        fields.base_url = String(this.aiVal("base_url") || "").trim();
      if (creating || Object.prototype.hasOwnProperty.call(d, "model"))
        fields.model = this.aiModelList();

      if (creating || Object.prototype.hasOwnProperty.call(d, "api_key")) fields.api_key = d.api_key;
      if (!creating && !Object.keys(fields).length && name === old){ toast("没有改动"); return; }
      this.ai.busy = true;

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
      this.ai.mode = "list";          
      toast("已保存「" + name + "」");
    },

    aiDel(name){
      name = name || this.ai.name;
      if (!name) return;
      askConfirm("删除这一组？", "只删配置，不影响别的东西。",
                 async () => {
        const r = await pywebview.api.ai_delete(name);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "没删掉"), true); return; }

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

    aiPingReset(){
      this.ai.ping.seq = (this.ai.ping.seq || 0) + 1;
      this.ai.ping.rows = [];
      this.ai.ping.running = false;
    },
    async aiPingAll(){
      if (this.ai.busy || this.ai.ping.running) return;
      const list = this.aiModelList();
      if (!list.length){ toast("先把「可用模型列表」填上（一行一个模型名）", true); return; }

      const seq = this.ai.ping.seq;
      this.ai.ping.running = true;
      this.ai.ping.rows = list.map(m => ({model: m, state: "wait", ok: false, ms: 0, msg: ""}));
      const fields = this.aiQueryFields();
      const name = this.ai.name || "";
      for (let i = 0; i < this.ai.ping.rows.length; i++){
        if (seq !== this.ai.ping.seq) return;          
        const row = this.ai.ping.rows[i];
        if (!row) return;
        row.state = "run";
        this.$forceUpdate();
        let r = null;
        try{ r = await pywebview.api.ai_ping(name, row.model, fields); }
        catch(e){ r = {ok: false, msg: String(e && e.message ? e.message : e)}; }
        if (seq !== this.ai.ping.seq) return;          
        row.ok = !!(r && r.ok);
        row.ms = (r && r.ms) || 0;
        row.msg = String((r && (r.ok ? r.sample : r.msg)) || "").trim();
        if (!row.msg) row.msg = row.ok ? "能通" : "不通";
        row.state = "done";
        this.$forceUpdate();
      }
      this.ai.ping.running = false;
      const bad = this.aiPingBad.length;
      toast(bad ? ("测试完：" + (this.ai.ping.rows.length - bad) + " 个可用 · " + bad + " 个不通")
                : ("测试完：" + this.ai.ping.rows.length + " 个模型都能用"));
    },
    aiPingRowText(r){
      if (r && r.state === "done") return r.msg || (r.ok ? "能通" : "不通");
      return (r && r.state === "run") ? "正在测…" : "排队中…";
    },

    aiPingDropBad(){
      const bad = this.aiPingBad.map(r => r.model);
      if (!bad.length) return;
      const keep = this.aiModelList().filter(m => bad.indexOf(m) < 0);
      this.ai.draft.model = keep.join("\n");
      this.ai.ping.rows = this.ai.ping.rows.filter(r => r.ok);
      this.ai.status = "";
      toast(keep.length
        ? ("已删掉 " + bad.length + " 个不通的（点保存才写进配置）")
        : "全都不通 —— 列表清空了，点「获取可用模型」重新拉一份，或者手动填");
    },

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
      return isFinite(n) ? Math.max(0, Math.min(20, n)) : 0;   
    },

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

      this.aiPingReset();
      this.setActive((this.groups[0] || {}).name || "");
      this.show = true;
      if (this.msg) toast(this.msg);
      this.scheduleCheck(0);          
    },
    close(){
      if (this._timer) clearTimeout(this._timer);
      this._seq++;                    
      this.hideTip();
      this.show = false;
    },
    setActive(gid){
      this.active = gid;
      this.hideTip();

      if (this.isAiName(gid)){ this.aiLoadPresets(); if (!this.ai.loaded) this.aiLoad(""); this.sndLoad(); }

      if (this.isAccessName(gid)) this.cdLoad();
    },
    setVal(key, v){
      this.values[key] = v;

      this.$forceUpdate();
    },
    bump(key, d){
      this.setVal(key, this.clampNum((parseInt(this.values[key], 10) || 1) + d));
    },

    scheduleCheck(delay){
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this.check(), delay == null ? 250 : delay);
    },
    async check(){
      this._timer = null;
      const seq = ++this._seq;
      const r = await pywebview.api.settings_check(Object.assign({}, this.values));
      if (seq !== this._seq) return;   
      this.problems = (r && r.problems) || [];
      this.notes = (r && r.notes) || {};
      this.live = (r && r.live) || "";
      if (r && r.msg) this.msg = r.msg;
      if (this.tip.show && this.tip.key) this.showTip(this.tip.key);
    },

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

      if (r && r.notes) this.notes = r.notes;
      if (r && r.live) this.live = r.live;
      if (!r || !r.ok || list.some(p => p.level !== "warn")){
        this.problems = list.length ? list
          : [{key: "", why: (r && r.msg) || "没拿到失败原因", level: "error", also: []}];
        toast("没保存 —— 看标红的地方", true);
        return;
      }

      this.problems = list;
      Object.keys(pairs).forEach(k => { this.orig[k] = this.values[k]; });

      if (this.values["symbols.plugin_mode"] !== undefined){
        PSYM = this.values["symbols.plugin_mode"];
        renderList(); renderHist(); renderDetail();
      }

      const scMsgs = (r && r.shortcut) || [];
      const head = list.length ? ("已保存（有 " + list.length + " 条提醒）")
                               : "已保存到 config.toml";
      const det = scMsgs.slice(0, 4).join("；") + (scMsgs.length > 4 ? ("；…还有 " + (scMsgs.length - 4) + " 条") : "");
      toast(det ? (head + "；" + det) : (head + "（下一次启动 moss 生效）"));

    },

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
