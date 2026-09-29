/* BMI 计算器 —— 界面（Vue 3）。
   ★ 这里**不做任何业务判断**：BMI 怎么算、分级怎么定、时间是多少，全在 Python 那边。
     这一层只干两件事：把输入交给后端（`moss.call`），把后端回来的东西显示出来。
     垫片保证"内嵌"和"独立窗口"两种环境下这段代码一模一样。 */
const { createApp, reactive, ref, onMounted } = Vue;

createApp({
  setup() {
    const env = reactive({ embedded: !!(window.moss && window.moss.env.embedded) });
    const info = reactive({ who: '', python: '', cwd: '' });
    const clock = reactive({ text: '', date: '', week: '' });
    const form = reactive({ height: 175, weight: 70 });
    const result = ref(null);
    const busy = ref(false);
    const ticks = ref(0);

    const levelKey = Vue.computed(() => {
      const m = { '偏瘦': 'thin', '正常': 'ok', '超重': 'over', '肥胖': 'fat' };
      return m[(result.value && result.value.level) || ''] || 'ok';
    });

    async function calc() {
      busy.value = true;
      try {
        result.value = await window.moss.call('bmi', {
          height: form.height, weight: form.weight,
        });
      } catch (e) {
        result.value = { ok: false, why: '调后端失败：' + e.message };
      } finally {
        busy.value = false;
      }
    }

    onMounted(async () => {
      // 后端主动推的时间（`moss.on` 是垫片给的事件口子）
      window.moss.on('time', (d) => {
        clock.text = d.text; clock.date = d.date; clock.week = d.week;
        ticks.value += 1;
        if (!info.who) info.who = d.who;
      });
      // 宿主发来的事件（内嵌时才有）
      window.moss.on('invoke', () => calc());
      window.moss.on('visible', (d) => {
        // 切走不关、切回来接着显示 —— 这里只是顺手记一下（不打断后端）
        if (d && d.visible) window.moss.call('now', {}).then((n) => {
          clock.text = n.text; clock.date = n.date; clock.week = n.week;
        }).catch(() => {});
      });

      try { Object.assign(info, await window.moss.call('info', {})); } catch (e) { /* 无妨 */ }
      try {
        Object.assign(clock, await window.moss.call('now', {}));
        await window.moss.call('subscribe', { event: 'time' });   // 让它开始推
      } catch (e) { /* 无妨 */ }
      env.embedded = !!(window.moss && window.moss.env.embedded);
      calc();                                  // 一进来就先按默认值算一次，省得空着
    });

    return { env, info, clock, form, result, busy, ticks, levelKey, calc };
  },
}).mount('#app');
