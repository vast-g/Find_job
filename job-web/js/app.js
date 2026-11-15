/* =============================================================================
 * app.js —— 控制台页面逻辑（零依赖，原生 DOM）
 *
 * 组织方式：
 *   [1] 格式化工具      —— 时间/薪资/状态这些「后端给的是裸值」的东西集中在这里翻译
 *   [2] UI 基元         —— Toast / 弹窗 / 加载态 / 错误态 / 分页
 *   [3] 全局状态        —— State 一个对象装完，方便排查
 *   [4] 各视图渲染      —— 概览 / 岗位 / 投递 / 企业 / AI / 系统
 *   [5] 初始化与路由
 *
 * 一条贯穿全文件的原则：**后端不可用时也必须渲染出东西**。
 * 所以所有 load* 函数都是 try/catch 包住 + 渲染「错误卡片 + 重试按钮」，
 * 绝不把异常抛到顶层（那会白屏）。
 * ========================================================================== */
(function () {
  'use strict';

  /* ==========================================================================
   * [0] 极简 DOM 工具
   * ======================================================================= */
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /** 多别名取值：同一个语义在不同版本里字段名可能不同，取第一个非空值。 */
  function pick(obj, keys) {
    if (!obj) { return undefined; }
    for (var i = 0; i < keys.length; i++) {
      var v = obj[keys[i]];
      if (v !== undefined && v !== null && v !== '') { return v; }
    }
    return undefined;
  }

  /* ==========================================================================
   * [1] 格式化工具
   * ======================================================================= */

  /**
   * 解析后端时间。
   * 为什么不用 new Date(str)：JacksonObjectMapper 固定输出 "yyyy-MM-dd HH:mm:ss"，
   * 这不是 ISO 格式，Safari/iOS 上 new Date('2026-01-01 10:00:00') 会得到 Invalid Date。
   * 手工拆字段最稳。
   */
  function parseServerTime(v) {
    if (v === null || v === undefined || v === '') { return null; }
    if (typeof v === 'number') { return new Date(v); }
    var s = String(v).trim();
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (m) { return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)); }
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) { return new Date(+m[1], +m[2] - 1, +m[3]); }
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }

  function pad2(n) { return n < 10 ? '0' + n : String(n); }

  /** 相对时间：控制台上「3 天前」比绝对时间更容易扫读 */
  function relativeTime(d) {
    var diff = Date.now() - d.getTime();
    if (diff < 0) { return '未来'; }
    var min = Math.floor(diff / 60000);
    if (min < 1) { return '刚刚'; }
    if (min < 60) { return min + ' 分钟前'; }
    var h = Math.floor(min / 60);
    if (h < 24) { return h + ' 小时前'; }
    var day = Math.floor(h / 24);
    if (day < 30) { return day + ' 天前'; }
    return Math.floor(day / 30) + ' 个月前';
  }

  function fmtTime(v, withRelative) {
    var d = parseServerTime(v);
    if (!d) { return '<span class="muted">—</span>'; }
    var text = d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    if (!withRelative) { return esc(text); }
    return '<span title="' + esc(d.toString()) + '">' + esc(text) +
      ' <em class="muted">(' + esc(relativeTime(d)) + ')</em></span>';
  }

  /**
   * 薪资格式化。
   * 依据 schema.sql：salary_min/salary_max 是「月薪/元」；JobCrawlerService 抓取时
   * 也把 K/万 统一乘成了元（1000 / 10000），所以这里按元处理 → 显示为 K。
   * 兜底：极小的值（<1000）不硬套 K，原样显示元，避免把 8 显示成 0.008K。
   */
  function fmtSalary(job) {
    if (!job) { return '<span class="muted">面议</span>'; }
    var min = Number(job.salaryMin);
    var max = Number(job.salaryMax);
    var hasMin = job.salaryMin !== null && job.salaryMin !== undefined && !isNaN(min) && min > 0;
    var hasMax = job.salaryMax !== null && job.salaryMax !== undefined && !isNaN(max) && max > 0;

    if (!hasMin && !hasMax) { return '<span class="muted">面议</span>'; }

    var unit = (Math.max(hasMin ? min : 0, hasMax ? max : 0) >= 1000) ? 'K' : '元';
    var div = unit === 'K' ? 1000 : 1;
    var f = function (n) {
      var x = n / div;
      return (Math.round(x * 10) / 10).toString();
    };

    if (hasMin && hasMax) {
      if (min === max) { return '<span class="salary">' + esc(f(min)) + unit + '</span>'; }
      return '<span class="salary">' + esc(f(min)) + '-' + esc(f(max)) + unit + '</span><em class="unit">/月</em>';
    }
    if (hasMin) { return '<span class="salary">' + esc(f(min)) + unit + ' 起</span>'; }
    return '<span class="salary">最高 ' + esc(f(max)) + unit + '</span>';
  }

  /**
   * 岗位状态。
   * 依据 schema.sql / Job 实体注释：1 在招、2 已结束、0 下架
   * （任务书只写了 0/1，这里把 2 也覆盖到，否则「已结束」的岗位会显示成未知）。
   */
  var JOB_STATUS = {
    0: { text: '已下架', cls: 'tag-danger' },
    1: { text: '在招', cls: 'tag-success' },
    2: { text: '已结束', cls: 'tag-warn' }
  };
  function jobStatusTag(s) {
    var meta = JOB_STATUS[Number(s)];
    if (!meta) { return '<span class="tag tag-muted">未知(' + esc(s) + ')</span>'; }
    return '<span class="tag ' + meta.cls + '">' + meta.text + '</span>';
  }

  /**
   * 投递状态。
   * 依据 schema.sql 的列注释（与任务书一致）：1已投递 2已查看 3面试邀请 4已录用 5已拒绝。
   * 已知冲突：ApplicationStatusConstant.java 里是另一套 7 值（0待投递 2笔试 3面试
   * 4长期无进展 5Offer 6已拒绝）。数据库实际写入遵循的是 schema，所以以 schema 为准，
   * 同时把 0 和 6 也映射上，保证历史/异常值不会显示成空白。
   */
  var APP_STATUS = {
    0: { text: '待投递', cls: 'tag-muted' },
    1: { text: '已投递', cls: 'tag-info' },
    2: { text: '已查看', cls: 'tag-primary' },
    3: { text: '面试邀请', cls: 'tag-warn' },
    4: { text: '已录用', cls: 'tag-success' },
    5: { text: '已拒绝', cls: 'tag-danger' },
    6: { text: '已拒绝', cls: 'tag-danger' }
  };
  function appStatusTag(s) {
    var meta = APP_STATUS[Number(s)];
    if (!meta) { return '<span class="tag tag-muted">未知(' + esc(s) + ')</span>'; }
    return '<span class="tag ' + meta.cls + '">' + meta.text + '</span>';
  }

  /** 企业状态：company.status 1 正常 0 停用 */
  function companyStatusTag(s) {
    return Number(s) === 0
      ? '<span class="tag tag-danger">已停用</span>'
      : '<span class="tag tag-success">正常</span>';
  }

  function text(v, fallback) {
    if (v === null || v === undefined || v === '') { return '<span class="muted">' + esc(fallback || '—') + '</span>'; }
    return esc(v);
  }

  /* ==========================================================================
   * [2] UI 基元
   * ======================================================================= */

  /** 轻提示：所有操作反馈走这里，避免用 alert 打断演示节奏 */
  var Toast = {
    show: function (msg, type, ms) {
      var root = $('#toast-root');
      if (!root) { return; }
      var el = document.createElement('div');
      el.className = 'toast toast-' + (type || 'info');
      el.innerHTML = '<span class="toast-dot"></span><span class="toast-msg">' + esc(msg) + '</span>';
      root.appendChild(el);
      // 入场动画后再移除，超过 5 条自动清最旧的，防止堆满屏幕
      requestAnimationFrame(function () { el.classList.add('in'); });
      while (root.children.length > 5) { root.removeChild(root.firstChild); }
      setTimeout(function () {
        el.classList.remove('in');
        setTimeout(function () { if (el.parentNode) { el.parentNode.removeChild(el); } }, 260);
      }, ms || 3600);
    },
    ok: function (m) { Toast.show(m, 'ok'); },
    err: function (m) { Toast.show(m, 'error', 6000); },
    warn: function (m) { Toast.show(m, 'warn', 5000); }
  };

  /** 统一的错误展示：标题 + 细节 + 排查建议。kind 决定配色，hint 才是真正省时间的东西。 */
  function errorCard(e, retryLabel, retryAction) {
    var kind = (e && e.kind) || 'network';
    var title = (e && e.title) || '请求失败';
    var detail = (e && e.detail) || '';
    var hint = (e && e.hint) || '';
    var actions = '';

    if (retryAction) {
      actions = '<button class="btn btn-ghost btn-sm" data-retry="' + esc(retryAction) + '">' + esc(retryLabel || '重试') + '</button>';
    }
    // 401 且是管理端 → 直接给登录入口，比让用户自己找顶部登录框友好
    if (kind === 'unauthorized') {
      actions += ' <button class="btn btn-primary btn-sm" data-goto="login">去登录</button>';
    }


    return '<div class="state state-error">' +
      '<div class="state-icon">!</div>' +
      '<div class="state-title">' + esc(title) + '</div>' +
      (detail ? '<div class="state-detail">' + esc(detail) + '</div>' : '') +
      (hint ? '<div class="state-hint">排查：' + esc(hint) + '</div>' : '') +
      (actions ? '<div class="state-actions">' + actions + '</div>' : '') +
      '</div>';
  }

  function loadingCard(msg) {
    return '<div class="state state-loading"><div class="spinner"></div><div class="state-title">' +
      esc(msg || '加载中…') + '</div></div>';
  }

  function emptyCard(msg, sub) {
    return '<div class="state state-empty"><div class="state-icon">∅</div><div class="state-title">' +
      esc(msg || '暂无数据') + '</div>' + (sub ? '<div class="state-detail">' + esc(sub) + '</div>' : '') + '</div>';
  }

  function needLoginCard(what) {
    return '<div class="state state-empty"><div class="state-icon">🔒</div>' +
      '<div class="state-title">未登录，无法读取' + esc(what || '该数据') + '</div>' +
      '<div class="state-detail">管理端接口需要请求头 token。用右上角的 admin / 123456 登录后自动加载。</div>' +
      '<div class="state-actions"><button class="btn btn-primary btn-sm" data-goto="login">去登录</button></div></div>';
  }

  /**
   * 分页控件。
   * 页码做窗口化（最多 7 个），否则数据量大时页码会把整行撑爆。
   */
  function renderPagination(container, state, onJump) {
    var el = typeof container === 'string' ? $(container) : container;
    if (!el) { return; }
    var total = state.total || 0;
    var pageSize = state.pageSize || 10;
    var page = state.page || 1;
    var pages = Math.max(1, Math.ceil(total / pageSize));

    if (total === 0) { el.innerHTML = ''; return; }

    var html = '<div class="pager">';
    html += '<span class="pager-info">共 <b>' + total + '</b> 条 · 第 ' + page + '/' + pages + ' 页</span>';
    html += '<div class="pager-btns">';
    html += '<button class="btn btn-ghost btn-sm" data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>';

    var start = Math.max(1, Math.min(page - 3, pages - 6));
    var end = Math.min(pages, start + 6);
    if (start > 1) { html += '<button class="btn btn-ghost btn-sm" data-page="1">1</button><span class="pager-gap">…</span>'; }
    for (var i = start; i <= end; i++) {
      html += '<button class="btn btn-sm ' + (i === page ? 'btn-primary' : 'btn-ghost') + '" data-page="' + i + '">' + i + '</button>';
    }
    if (end < pages) { html += '<span class="pager-gap">…</span><button class="btn btn-ghost btn-sm" data-page="' + pages + '">' + pages + '</button>'; }

    html += '<button class="btn btn-ghost btn-sm" data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + '>下一页</button>';
    html += '</div></div>';
    el.innerHTML = html;

    $$('[data-page]', el).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var p = Number(btn.getAttribute('data-page'));
        if (!p || p < 1 || p > pages || p === page) { return; }
        onJump(p);
      });
    });
  }

  /* ==========================================================================
   * [3] 全局状态
   * ======================================================================= */
  var State = {
    view: 'overview',
    health: { java: null, agent: null },
    // 各表格的查询条件与数据；page 从 1 开始（与后端约定一致）
    jobs: { page: 1, pageSize: 10, name: '', status: '', total: 0, records: [], loading: false, error: null },
    apps: { page: 1, pageSize: 10, status: '', total: 0, records: [], loading: false, error: null },
    companies: { page: 1, pageSize: 10, name: '', total: 0, records: [], loading: false, error: null },
    chat: { messages: [], sending: false, tick: null, startedAt: 0, requestId: null, sessionId: '' },
    crawl: { running: false, startedAt: 0, timer: null, hintTimer: null, logs: [], result: null },
    latencyHistory: [],   // 用折线图展示每次 AI 调用的耗时
    diag: []
  };

  function isLoggedIn() { return Api.isLoggedIn(); }

  /* ==========================================================================
   * [4] 顶部栏：健康灯 / 登录 / 接口地址
   * ======================================================================= */

  function renderHealth() {
    var paint = function (id, h, label) {
      var el = $('#' + id);
      if (!el) { return; }
      var level = h ? h.level : 'unknown';
      el.className = 'health health-' + level;
      var right = $('.health-text', el);
      if (right) {
        var note = h ? (h.note || (h.ok ? '正常' : (h.error && h.error.title) || '不可用')) : '未探测';
        var ms = h && h.ms ? ' · ' + h.ms + 'ms' : '';
        right.textContent = note + ms;
      }
      el.title = h && h.error
        ? (h.error.title + (h.error.hint ? '\n排查：' + h.error.hint : ''))
        : (label + ' 探测结果');
    };
    paint('health-java', State.health.java, 'Java 后端');
    paint('health-agent', State.health.agent, 'AI 历史接口');
  }

  /** Java 公开探针和管理员历史接口可用性。 */
  async function probeHealth(silent) {
    var snapshot = Api.getAuthSnapshot();
    var r = await Promise.all([Api.healthJava(), Api.healthAgent()]);
    if (!Api.isAuthSnapshot(snapshot)) { return r; }
    State.health.java = r[0];
    State.health.agent = r[1];
    renderHealth();
    if (!silent) {
      Toast.show('健康探测完成：Java ' + (r[0].ok ? '正常' : '异常') + '、历史接口 ' + (r[1].level === 'up' ? '可用' : r[1].level === 'warn' ? '待授权' : '异常'),
        r[0].ok && r[1].level !== 'down' ? 'ok' : 'warn');
    }
    return r;
  }

  function renderLoginState() {
    var logged = isLoggedIn();
    // 注意：登录表单的 id 是 login-form（class 才叫 login-box），这里必须按 id 取
    var box = $('#login-form');
    var who = $('#login-who');
    var status = $('#ai-login-status');
    if (status) { status.textContent = logged ? '已登录：业务与 AI 助手均可使用' : '请在顶部登录一次，即可使用业务与 AI 助手'; }
    if (!box || !who) { return; }
    box.classList.toggle('hidden', logged);
    who.classList.toggle('hidden', !logged);
    if (logged) {
      $('#who-name').textContent = Api.Store.getAdminName() || 'admin';
    }
  }

  async function doLogin(ev) {
    if (ev) { ev.preventDefault(); }
    var u = $('#login-user').value.trim();
    var p = $('#login-pass').value;
    var btn = $('#btn-login');
    if (!u || !p) { Toast.warn('请填写账号与密码'); return; }

    btn.disabled = true;
    btn.textContent = '登录中…';
    try {
      var data = await Api.login(u, p);
      Toast.ok('登录成功：' + ((data && (data.name || data.userName)) || u));
      renderLoginState();
      // 登录后把需要权限的视图都刷新一遍
      loadView(State.view);
      updateAdminBadges();
      probeHealth(true);
    } catch (e) {
      Toast.err(e.title + (e.detail ? '（' + e.detail + '）' : ''));
    } finally {
      btn.disabled = false;
      btn.textContent = '登录';
    }
  }

  function doLogout() {
    Api.logout();
    renderLoginState();
    updateAdminBadges();
    probeHealth(true);
    Toast.show('已退出登录');
    loadView(State.view);
  }

  function updateAdminBadges() {
    // 未登录时在概览页给一条提示条，而不是等用户点到表格才发现
    var bar = $('#login-tip');
    if (!bar) { return; }
    bar.classList.toggle('hidden', isLoggedIn());
  }

  function applyApiBase() {
    var v = $('#api-base').value.trim();
    // 允许留空 = 同源根路径（后端直连且没有 /api 前缀时用）
    Api.Store.setApiBase(v);
    Toast.ok('接口地址已设为：' + (v || '（同源根路径）'));
    probeHealth(true);
    loadView(State.view);
  }

  /* ==========================================================================
   * [5] 概览
   * ======================================================================= */

  /**
   * 统计卡片。
   * 注意：这个版本的 /user/stats（StatsController）返回的是
   * companyCount / jobCount / announcementCount / applyTotal / applyProgress / applyRemind，
   * **没有** userCount 和 applicationCount。取不到就显示「—」并说明，
   * 不能拿 0 冒充（0 会被误解为「真的没有用户」）。
   */
  function renderStats(stats, err) {
    var defs = [
      { label: '用户数', aliases: ['userCount', 'userTotal', 'users'], icon: '👤', hint: '本版本 /user/stats 未返回该字段' },
      { label: '岗位数', aliases: ['jobCount', 'jobTotal'], icon: '💼' },
      { label: '投递数', aliases: ['applyTotal', 'applicationCount', 'applyCount'], icon: '📮', hint: '取 applyTotal' },
      { label: '企业数', aliases: ['companyCount', 'companyTotal'], icon: '🏢' }
    ];
    var extra = [
      { label: '进行中投递', aliases: ['applyProgress'], icon: '⏳' },
      { label: '公告数', aliases: ['announcementCount'], icon: '📢' }
    ];

    var card = function (d) {
      var v = pick(stats, d.aliases);
      var missing = v === undefined;
      var shown = missing ? '—' : v;
      return '<div class="stat-card' + (missing ? ' stat-missing' : '') + '"' +
        (missing && d.hint ? ' title="' + esc(d.hint) + '"' : '') + '>' +
        '<div class="stat-icon">' + d.icon + '</div>' +
        '<div class="stat-body"><div class="stat-value">' + esc(shown) + '</div>' +
        '<div class="stat-label">' + esc(d.label) + (missing ? ' <em class="muted">(接口未返回)</em>' : '') + '</div></div>' +
        '</div>';
    };

    var html = defs.map(card).join('') + extra.map(card).join('');
    if (err) {
      html = '<div class="stat-card stat-error-full">' + errorCard(err, '重新加载统计', 'overview') + '</div>';
    }
    $('#stat-cards').innerHTML = html || '';
  }

  /** 概览页的图表：全部先用免鉴权接口（/user/job/list）算出来，未登录也能演示 */
  async function loadOverview() {
    $('#stat-cards').innerHTML = loadingCard('正在读取统计数据…').replace('state state-loading', 'stat-card');

    var stats = null, statErr = null, jobs = [], jobErr = null, announcements = null, annErr = null;
    try {
      stats = await Api.userStats();
    } catch (e) { statErr = e; }
    renderStats(stats, statErr);

    // 岗位列表：免鉴权，用来做城市/薪资/状态三个图
    try {
      jobs = await Api.userJobList({});
    } catch (e) { jobErr = e; }

    if (jobErr) {
      var msg = errorCard(jobErr, '重新加载图表', 'overview');
      ['#chart-job-status', '#chart-city', '#chart-salary'].forEach(function (id) {
        var el = $(id);
        if (el) { el.innerHTML = msg; }
      });
      $('#latest-jobs').innerHTML = '';
    } else if (!jobs.length) {
      ['#chart-job-status', '#chart-city', '#chart-salary'].forEach(function (id) {
        var el = $(id);
        if (el) { el.innerHTML = '<div class="chart-empty">暂无岗位数据</div>'; }
      });
    } else {
      renderJobCharts(jobs);
      renderLatestJobs(jobs);
    }

    // 公告：管理端接口，未登录就显示登录提示（不算错误）
    if (!isLoggedIn()) {
      $('#announcement-list').innerHTML = needLoginCard('公告');
    } else {
      $('#announcement-list').innerHTML = loadingCard('正在读取公告…');
      try {
        announcements = await Api.announcementList();
        renderAnnouncements('#announcement-list', announcements, false);
      } catch (e) {
        annErr = e;
        $('#announcement-list').innerHTML = errorCard(annErr, '重新加载公告', 'overview');
      }
    }
  }

  /** 用 /user/job/list 的全量结果算三种分布，避免为图表再要一个后端接口 */
  function renderJobCharts(jobs) {
    // 1) 岗位状态分布
    var byStatus = {};
    jobs.forEach(function (j) {
      var meta = JOB_STATUS[Number(j.status)];
      var key = meta ? meta.text : '未知';
      byStatus[key] = (byStatus[key] || 0) + 1;
    });
    var statusColors = { '在招': '#38d39f', '已结束': '#f7b955', '已下架': '#f2637b', '未知': '#64748b' };
    Charts.donut('#chart-job-status', Object.keys(byStatus).map(function (k) {
      return { label: k, value: byStatus[k], color: statusColors[k] || Charts.colorAt(0) };
    }), { centerLabel: '岗位总数', centerValue: jobs.length });

    // 2) 城市 TOP8
    var byCity = {};
    jobs.forEach(function (j) {
      var c = j.city || '未标注';
      byCity[c] = (byCity[c] || 0) + 1;
    });
    var cityItems = Object.keys(byCity).map(function (k) { return { label: k, value: byCity[k] }; })
      .sort(function (a, b) { return b.value - a.value; }).slice(0, 8);
    Charts.hbars('#chart-city', cityItems, { limit: 8 });

    // 3) 薪资区间分布：以「千元」为刻度分桶，招聘场景下这个粒度最有意义
    var buckets = [
      { label: '<6K', min: 0, max: 6000, value: 0 },
      { label: '6-9K', min: 6000, max: 9000, value: 0 },
      { label: '9-12K', min: 9000, max: 12000, value: 0 },
      { label: '12-18K', min: 12000, max: 18000, value: 0 },
      { label: '18-25K', min: 18000, max: 25000, value: 0 },
      { label: '≥25K', min: 25000, max: Infinity, value: 0 }
    ];
    var noSalary = 0;
    jobs.forEach(function (j) {
      var min = Number(j.salaryMin), max = Number(j.salaryMax);
      if (!min && !max) { noSalary++; return; }
      // 用区间中值分桶：只有单边时用另一边的值，避免把它错误地塞进最低桶
      var v = (min && max) ? (min + max) / 2 : (min || max);
      for (var i = 0; i < buckets.length; i++) {
        if (v >= buckets[i].min && v < buckets[i].max) { buckets[i].value++; break; }
      }
    });
    Charts.columns('#chart-salary', buckets.map(function (b) { return { label: b.label, value: b.value }; }), {});
    var note = $('#chart-salary-note');
    if (note) {
      note.textContent = noSalary > 0
        ? '共 ' + jobs.length + ' 个岗位，其中 ' + noSalary + ' 个未标注薪资（按区间中值分桶）'
        : '共 ' + jobs.length + ' 个岗位（按薪资区间中值分桶）';
    }
  }

  function renderLatestJobs(jobs) {
    var latest = jobs.slice().sort(function (a, b) {
      var ta = parseServerTime(a.createTime), tb = parseServerTime(b.createTime);
      return (tb ? tb.getTime() : 0) - (ta ? ta.getTime() : 0);
    }).slice(0, 6);

    $('#latest-jobs').innerHTML = latest.map(function (j) {
      return '<li class="mini-item" data-job="' + esc(j.id) + '">' +
        '<div class="mini-main"><span class="mini-title">' + esc(j.title || '未命名岗位') + '</span>' +
        '<span class="mini-sub">' + text(j.companyName) + ' · ' + text(j.city) + '</span></div>' +
        '<div class="mini-side">' + fmtSalary(j) + '</div></li>';
    }).join('');
  }

  function renderAnnouncements(sel, list, compact) {
    var el = $(sel);
    if (!el) { return; }
    if (!list || !list.length) { el.innerHTML = emptyCard('暂无公告'); return; }
    el.innerHTML = list.slice(0, compact ? 3 : 20).map(function (a) {
      return '<li class="mini-item"><div class="mini-main">' +
        '<span class="mini-title">' + esc(a.title || '（无标题）') + '</span>' +
        '<span class="mini-sub">' + text(a.content, '无正文') + '</span></div>' +
        '<div class="mini-side">' + fmtTime(a.publishTime || a.createTime) + '</div></li>';
    }).join('');
  }

  /* ==========================================================================
   * [6] 岗位管理
   * ======================================================================= */

  async function loadJobs() {
    var box = $('#job-table-wrap');
    if (!isLoggedIn()) {
      box.innerHTML = needLoginCard('岗位列表');
      $('#job-pagination').innerHTML = '';
      return;
    }
    box.innerHTML = loadingCard('正在加载岗位…');
    State.jobs.loading = true;
    try {
      var res = await Api.jobPage({
        page: State.jobs.page, pageSize: State.jobs.pageSize,
        name: State.jobs.name, status: State.jobs.status
      });
      State.jobs.records = res.records;
      State.jobs.total = res.total;
      State.jobs.error = null;
      renderJobsTable();
    } catch (e) {
      State.jobs.error = e;
      box.innerHTML = errorCard(e, '重新加载', 'jobs');
    } finally {
      State.jobs.loading = false;
    }
  }

  function renderJobsTable() {
    var box = $('#job-table-wrap');
    var list = State.jobs.records;
    if (!list.length) {
      box.innerHTML = emptyCard('没有匹配的岗位', State.jobs.name ? '当前搜索词：' + State.jobs.name : '可以试试清空搜索条件');
      $('#job-pagination').innerHTML = '';
      return;
    }

    var rows = list.map(function (j) {
      var st = Number(j.status);
      // 上架按钮：仅在 0(下架) 时显示上架；其余显示下架
      var toggle = st === 0
        ? '<button class="btn btn-mini btn-success" data-job-up="' + esc(j.id) + '">上架</button>'
        : '<button class="btn btn-mini btn-ghost" data-job-down="' + esc(j.id) + '">下架</button>';

      return '<tr>' +
        '<td class="col-title"><div class="cell-title">' + esc(j.title || '未命名岗位') + '</div>' +
        '<div class="cell-sub">' + text(j.categoryName, '未分类') + ' · ID ' + esc(j.id) + '</div></td>' +
        '<td>' + text(j.companyName) + '</td>' +
        '<td>' + text(j.city) + '</td>' +
        '<td>' + fmtSalary(j) + '</td>' +
        '<td>' + text(j.education) + '</td>' +
        '<td><span class="num">' + esc(j.viewCount || 0) + '</span> / <span class="num">' + esc(j.applyCount || 0) + '</span></td>' +
        '<td>' + jobStatusTag(j.status) + '</td>' +
        '<td class="col-actions">' + toggle +
        ' <button class="btn btn-mini btn-primary" data-job-ai="' + esc(j.id) + '">AI 分析</button></td>' +
        '</tr>';
    }).join('');

    box.innerHTML = '<table class="data-table"><thead><tr>' +
      '<th>标题 / 分类</th><th>企业</th><th>城市</th><th>薪资</th><th>学历</th><th>浏览/投递</th><th>状态</th><th>操作</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';

    renderPagination('#job-pagination', State.jobs, function (p) {
      State.jobs.page = p;
      loadJobs();
    });
  }

  /** 上下架。后端校验：上架时若企业被停用会抛 JobBusinessException，msg 会带回来，照原样提示即可。 */
  async function toggleJobStatus(id, status) {
    try {
      await Api.jobStatus(id, status);
      Toast.ok(status === 1 ? '已上架' : '已下架');
      loadJobs();
      loadOverviewSilently();
    } catch (e) {
      Toast.err(e.title + (e.detail ? '（' + e.detail + '）' : ''));
    }
  }

  /* ==========================================================================
   * [7] 投递记录
   * ======================================================================= */

  async function loadApplications() {
    var box = $('#app-table-wrap');
    if (!isLoggedIn()) {
      box.innerHTML = needLoginCard('投递记录');
      $('#app-pagination').innerHTML = '';
      return;
    }
    box.innerHTML = loadingCard('正在加载投递记录…');
    try {
      var res = await Api.applicationPage({
        page: State.apps.page, pageSize: State.apps.pageSize, status: State.apps.status
      });
      State.apps.records = res.records;
      State.apps.total = res.total;
      renderAppsTable();
    } catch (e) {
      box.innerHTML = errorCard(e, '重新加载', 'apps');
    }
  }

  function renderAppsTable() {
    var box = $('#app-table-wrap');
    var list = State.apps.records;
    if (!list.length) {
      box.innerHTML = emptyCard('没有投递记录');
      $('#app-pagination').innerHTML = '';
      return;
    }
    var rows = list.map(function (a) {
      return '<tr>' +
        '<td class="col-title"><div class="cell-title">' + esc(a.jobTitle || '（岗位已删除）') + '</div>' +
        '<div class="cell-sub">投递 ID ' + esc(a.id) + '</div></td>' +
        '<td>' + text(a.userName) + ' <span class="muted">#' + esc(a.userId) + '</span></td>' +
        '<td>' + text(a.companyName) + '</td>' +
        '<td>' + text(a.resumeName, '未关联简历') + '</td>' +
        '<td>' + appStatusTag(a.status) + '</td>' +
        '<td>' + fmtTime(a.interviewTime) + '</td>' +
        '<td>' + fmtTime(a.createTime, true) + '</td>' +
        '</tr>';
    }).join('');

    box.innerHTML = '<table class="data-table"><thead><tr>' +
      '<th>岗位</th><th>投递人</th><th>企业</th><th>简历</th>' +
      '<th title="状态映射依据 schema.sql；项目里 ApplicationStatusConstant.java 是另一套 7 值，注意区分">状态 ⓘ</th>' +
      '<th>面试时间</th><th>投递时间</th></tr></thead><tbody>' + rows + '</tbody></table>';

    renderPagination('#app-pagination', State.apps, function (p) {
      State.apps.page = p;
      loadApplications();
    });
  }

  /* ==========================================================================
   * [8] 企业管理
   * ======================================================================= */

  async function loadCompanies() {
    var box = $('#company-table-wrap');
    if (!isLoggedIn()) {
      box.innerHTML = needLoginCard('企业列表');
      $('#company-pagination').innerHTML = '';
      return;
    }
    box.innerHTML = loadingCard('正在加载企业…');
    try {
      var res = await Api.companyPage({
        page: State.companies.page, pageSize: State.companies.pageSize, name: State.companies.name
      });
      State.companies.records = res.records;
      State.companies.total = res.total;
      renderCompaniesTable();
    } catch (e) {
      box.innerHTML = errorCard(e, '重新加载', 'companies');
    }
  }

  function renderCompaniesTable() {
    var box = $('#company-table-wrap');
    var list = State.companies.records;
    if (!list.length) {
      box.innerHTML = emptyCard('没有匹配的企业');
      $('#company-pagination').innerHTML = '';
      return;
    }
    var rows = list.map(function (c) {
      return '<tr>' +
        '<td class="col-title"><div class="cell-title">' + esc(c.name || '未命名企业') + '</div>' +
        '<div class="cell-sub">ID ' + esc(c.id) + '</div></td>' +
        '<td>' + text(c.type) + '</td>' +
        '<td>' + text(c.city) + '</td>' +
        '<td>' + companyStatusTag(c.status) + '</td>' +
        '<td class="col-desc">' + text(c.description, '暂无简介') + '</td>' +
        '<td>' + fmtTime(c.createTime) + '</td>' +
        '</tr>';
    }).join('');

    box.innerHTML = '<table class="data-table"><thead><tr>' +
      '<th>企业名称</th><th>类型</th><th>城市</th><th>状态</th><th>简介</th><th>创建时间</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';

    renderPagination('#company-pagination', State.companies, function (p) {
      State.companies.page = p;
      loadCompanies();
    });
  }

  /* ==========================================================================
   * [9] AI 智能问答
   * ======================================================================= */

  var CHAT_PHASES = [
    '正在解析你的意图…',
    '正在检索知识库（RAG）…',
    '正在调用大模型推理（ReAct）…',
    '正在整理答案…'
  ];

  /** AI 与业务共用管理员登录。 */
  function ensureAdminLogin(action) {
    if (Api.Store.getAdminToken()) { return true; }
    Toast.warn('该功能需要先登录（右上角 admin / 123456）');
    return false;
  }

  var chatGeneration = 0;
  var historyGeneration = 0;
  var analyzeGeneration = 0;
  function resetAgentUi() {
    chatGeneration++;
    historyGeneration++;
    analyzeGeneration++;
    clearInterval(State.chat.tick);
    State.chat.tick = null;
    State.chat.sending = false;
    State.chat.messages = [];
    State.chat.sessionId = Api.Store.getSessionId() || '';
    State.latencyHistory = [];
    setComposerBusy(false);
    $('#chat-session').textContent = State.chat.sessionId || '（尚未创建）';
    $('#analyze-head').innerHTML = '';
    $('#analyze-body').innerHTML = '';
    renderChat();
    renderLatencyChart();
  }

  function renderChat() {
    var box = $('#chat-log');
    if (!State.chat.messages.length) {
      box.innerHTML = '<div class="chat-empty">还没有对话。可以点下面的示例问题，或直接输入。<br>' +
        '<em class="muted">AI 请求要跑 ReAct + RAG，实测 20~120 秒，请耐心等待进度提示。</em></div>';
      return;
    }
    box.innerHTML = State.chat.messages.map(function (m, i) {
      if (m.role === 'user') {
        return '<div class="msg msg-user"><div class="bubble">' + esc(m.content) + '</div></div>';
      }
      if (m.pending) {
        return '<div class="msg msg-ai"><div class="bubble bubble-pending">' +
          '<div class="dots"><span></span><span></span><span></span></div>' +
          '<div class="pending-phase">' + esc(m.phase || CHAT_PHASES[0]) + '</div>' +
          '<div class="pending-meta">已等待 <b>' + esc(m.elapsed || 0) + '</b> 秒' +
          '<em class="muted"> · AI 通常需要 20~120 秒，长回答会更久</em></div>' +
          '</div></div>';
      }
      if (m.error) {
        return '<div class="msg msg-ai"><div class="bubble bubble-error">' +
          '<div class="bubble-title">' + esc(m.errorTitle || 'AI 请求失败') + '</div>' +
          (m.errorDetail ? '<div class="bubble-detail">' + esc(m.errorDetail) + '</div>' : '') +
          (m.errorHint ? '<div class="bubble-hint">排查：' + esc(m.errorHint) + '</div>' : '') +
          '</div></div>';
      }
      var meta = [];
      if (m.intent) {
        meta.push('<span class="chip chip-intent">意图：' + esc(m.intent) + '</span>');
      } else {
        meta.push('<span class="chip chip-muted" title="Java 转发层（AgentServiceImpl.chat）目前只回传 sessionId/reply/sources/requestId，没有透出 Python 的 intent">意图：未返回</span>');
      }
      if (m.latencyText) {
        meta.push('<span class="chip chip-time" title="' + esc(m.latencyTitle || '') + '">' + esc(m.latencyText) + '</span>');
      }
      if (m.source) { meta.push('<span class="chip">来源：' + esc(m.source) + '</span>'); }
      if (m.requestId) { meta.push('<span class="chip chip-muted">请求 ' + esc(String(m.requestId).slice(0, 8)) + '</span>'); }

      var sources = '';
      if (m.sources && m.sources.length) {
        sources = '<div class="bubble-sources">引用：' + m.sources.map(function (s) {
          var label = (typeof s === 'string') ? s : (s.title || s.name || s.source || JSON.stringify(s));
          return '<span class="chip">' + esc(label) + '</span>';
        }).join('') + '</div>';
      }

      var feedback = m.requestId
        ? '<div class="bubble-actions"><button class="btn btn-mini btn-ghost" data-rate="1" data-idx="' + i + '">👍 有用</button>' +
        '<button class="btn btn-mini btn-ghost" data-rate="0" data-idx="' + i + '">👎 没用</button></div>'
        : '';

      return '<div class="msg msg-ai"><div class="bubble">' + richText(m.content) + sources +
        '<div class="bubble-meta">' + meta.join('') + '</div>' + feedback + '</div></div>';
    }).join('');
    box.scrollTop = box.scrollHeight;
  }

  /** 轻量「类 Markdown」渲染：只支持标题/列表/加粗/【小标题】，够用且零依赖 */
  function richText(raw) {
    var lines = esc(raw || '').split(/\r?\n/);
    var out = [], list = null;
    var flush = function () { if (list) { out.push('<ul>' + list.join('') + '</ul>'); list = null; } };
    lines.forEach(function (line) {
      var t = line.trim();
      if (!t) { flush(); return; }
      // AI 回答里常见 "---" 分隔线，不处理会被当成普通段落渲染出一个孤零零的 ---
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { flush(); out.push('<hr class="ai-hr">'); return; }
      var li = t.match(/^[-•*]\s+(.*)$/);
      if (li) { (list = list || []).push('<li>' + inline(li[1]) + '</li>'); return; }
      flush();
      var h = t.match(/^#{1,6}\s*(.*)$/);
      if (h) { out.push('<h5>' + inline(h[1]) + '</h5>'); return; }
      out.push('<p>' + inline(t) + '</p>');
    });
    flush();
    return out.join('');
  }
  function inline(s) {
    return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/【(.+?)】/g, '<span class="tag-inline">【$1】</span>');
  }

  /** 把一条用户消息发出去；期间维护「pending 气泡 + 秒表 + 阶段提示」 */
  async function sendChat(text) {
    if (State.chat.sending) { Toast.warn('上一条还在分析中，请稍候'); return; }
    text = (text || '').trim();
    if (!text) { return; }
    if (!ensureAdminLogin('chat')) { return; }
    var snapshot = Api.getAuthSnapshot();
    var generation = ++chatGeneration;
    historyGeneration++;

    State.chat.messages.push({ role: 'user', content: text });
    var pending = { role: 'assistant', pending: true, elapsed: 0, phase: CHAT_PHASES[0] };
    State.chat.messages.push(pending);
    State.chat.sending = true;
    setComposerBusy(true);
    renderChat();

    var t0 = Date.now();
    var phaseIdx = 0;
    // 秒表 + 阶段轮播：这是"不显得卡死"的关键。AI 要 20~120s，没有反馈用户会以为崩了。
    State.chat.tick = setInterval(function () {
      var sec = Math.floor((Date.now() - t0) / 1000);
      pending.elapsed = sec;
      var idx = Math.min(CHAT_PHASES.length - 1, Math.floor(sec / 6));
      if (idx !== phaseIdx) { phaseIdx = idx; }
      pending.phase = CHAT_PHASES[idx];
      var live = $('.bubble-pending');
      if (live) {
        var phaseEl = $('.pending-phase', live);
        var metaEl = $('.pending-meta', live);
        if (phaseEl) { phaseEl.textContent = pending.phase; }
        if (metaEl) {
          metaEl.innerHTML = '已等待 <b>' + sec + '</b> 秒<em class="muted"> · AI 通常需要 20~120 秒，长回答会更久</em>';
        }
      }
    }, 1000);

    try {
      var resp = await Api.agentChat(text, Api.Store.getSessionId() || '');
      if (generation !== chatGeneration || !Api.isAuthSnapshot(snapshot)) { return; }
      var ms = Date.now() - t0;
      var data = resp || {};

      // sessionId 必须存下来：后续 history 拉取、多轮上下文都依赖它
      if (data.sessionId) {
        Api.Store.setSessionId(data.sessionId);
        snapshot = Api.getAuthSnapshot();
        State.chat.sessionId = data.sessionId;
        $('#chat-session').textContent = data.sessionId;
      }

      var msg = {
        role: 'assistant',
        content: data.reply || '（AI 没有返回内容）',
        requestId: data.requestId || null,
        intent: pick(data, ['intent', 'intentType', 'intentName']),
        // Java 转发层目前不透出 latencyMs，所以退回前端实测值，并在 tooltip 里说明是谁计时的
        latency: pick(data, ['latencyMs', 'latency_ms', 'elapsedMs', 'costMs']),
        source: pick(data, ['source', 'sources']),
        sources: data.sources || null
      };
      if (typeof msg.source !== 'string') { msg.source = null; }
      if (msg.latency !== undefined && msg.latency !== null) {
        msg.latencyText = '耗时 ' + (Number(msg.latency) / 1000).toFixed(1) + 's';
        msg.latencyTitle = '后端返回的 latencyMs';
        State.latencyHistory.push(Number(msg.latency));
      } else {
        msg.latencyText = '前端实测 ' + (ms / 1000).toFixed(1) + 's';
        msg.latencyTitle = '后端未返回 latencyMs（Java 转发层未透出），此处为浏览器端计时';
        State.latencyHistory.push(ms);
      }
      renderLatencyChart();

      // 用真实回复替换掉 pending 气泡
      State.chat.messages[State.chat.messages.length - 1] = msg;
      renderChat();
    } catch (e) {
      if (generation !== chatGeneration || !Api.isAuthSnapshot(snapshot)) { return; }
      State.chat.messages[State.chat.messages.length - 1] = {
        role: 'assistant', error: true,
        errorTitle: e.title || 'AI 请求失败',
        errorDetail: e.detail || '',
        errorHint: e.hint || ''
      };
      renderChat();
    } finally {
      if (generation !== chatGeneration || !Api.isAuthSnapshot(snapshot)) { return; }
      clearInterval(State.chat.tick);
      State.chat.tick = null;
      State.chat.sending = false;
      setComposerBusy(false);
    }
  }

  function setComposerBusy(busy) {
    var btn = $('#btn-chat-send');
    if (btn) {
      btn.disabled = busy;
      btn.textContent = busy ? '分析中…' : '发送';
    }
    var input = $('#chat-input');
    if (input) { input.disabled = busy; }
  }

  function renderLatencyChart() {
    var el = $('#chart-latency');
    if (!el) { return; }
    if (!State.latencyHistory.length) {
      el.innerHTML = '<div class="chart-empty">发送一次对话后，这里会显示每次调用的耗时</div>';
      return;
    }
    Charts.line(el, State.latencyHistory, {
      height: 130, color: '#22d3ee', unit: 'ms',
      labels: State.latencyHistory.map(function (_, i) { return '第 ' + (i + 1) + ' 次'; })
    });
  }

  /** 历史属于当前管理员与会话；忽略旧登录和旧会话的响应。 */
  async function loadChatHistory() {
    if (State.chat.sending) { return; }
    var snapshot = Api.getAuthSnapshot();
    var generation = ++historyGeneration;
    var box = $('#chat-log');
    var sessionId = Api.Store.getSessionId();
    $('#chat-session').textContent = sessionId || '（尚未创建）';
    if (!sessionId) {
      State.chat.messages = [];
      renderChat();
      return;
    }
    if (!isLoggedIn()) {
      State.chat.messages = [];
      renderChat();
      return;
    }
    try {
      var list = Api.normalizeList(await Api.agentHistory(sessionId));
      if (generation !== historyGeneration || !Api.isAuthSnapshot(snapshot) || sessionId !== Api.Store.getSessionId() || State.chat.sending) { return; }
      State.chat.messages = list.map(function (m) {
        return {
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content || '',
          requestId: m.requestId || null
        };
      });
      renderChat();
    } catch (e) {
      if (generation !== historyGeneration || !Api.isAuthSnapshot(snapshot) || sessionId !== Api.Store.getSessionId()) { return; }
      // 历史拉不到不算致命：允许用户直接开始新对话
      box.innerHTML = errorCard(e, '重试拉取历史', 'ai-history');
    }
  }

  async function rateMessage(idx, rating) {
    var m = State.chat.messages[idx];
    if (!m || !ensureAdminLogin('feedback')) { return; }
    var snapshot = Api.getAuthSnapshot();
    try {
      await Api.agentFeedback({ sessionId: Api.Store.getSessionId(), requestId: m.requestId, rating: rating, comment: '' });
      if (!Api.isAuthSnapshot(snapshot)) { return; }
      Toast.ok(rating === 1 ? '已点赞' : '已记录反馈');
    } catch (e) {
      if (!Api.isAuthSnapshot(snapshot)) { return; }
      Toast.err('反馈失败：' + e.title);
    }
  }

  function clearChat() {
    Api.Store.setSessionId(null);
    resetAgentUi();
    Toast.show('已开启新会话');
  }

  /* ---------- 岗位 AI 分析（五部分） ---------- */

  /** 岗位要求分析的常见标题；兼容模型返回其他结构。 */
  var ANALYZE_SECTIONS = ['【岗位要求】', '【核心技能】', '【任职条件】', '【准备建议】', '【面试准备】'];

  function renderAnalyze(job, reply) {
    var body = $('#analyze-body');
    var head = $('#analyze-head');
    head.innerHTML = job
      ? '<div class="analyze-job"><span class="mini-title">' + esc(job.title || '岗位 #' + job.id) + '</span>' +
      '<span class="mini-sub">' + text(job.companyName) + ' · ' + text(job.city) + ' · ' + fmtSalary(job) + '</span></div>'
      : '';

    var text2 = String(reply || '').trim();
    if (!text2) {
      body.innerHTML = emptyCard('AI 没有返回分析内容', '后端可能返回了空 reply，可查看 Java 日志确认 Python Agent 是否超时');
      return;
    }

    // 优先按五个固定小标题切分；万一模型没按格式输出，就退化成整段落展示
    var marks = ANALYZE_SECTIONS.map(function (name) {
      return { name: name, idx: text2.indexOf(name) };
    }).filter(function (m) { return m.idx >= 0; }).sort(function (a, b) { return a.idx - b.idx; });

    if (!marks.length) {
      body.innerHTML = '<div class="analyze-fallback">' +
        '<div class="analyze-note">岗位要求分析：</div>' +
        '<div class="ai-rich">' + richText(text2) + '</div></div>';
      return;
    }

    body.innerHTML = marks.map(function (m, i) {
      var start = m.idx + m.name.length;
      var end = (i + 1 < marks.length) ? marks[i + 1].idx : text2.length;
      var content = text2.slice(start, end).trim();
      return '<section class="analyze-part">' +
        '<h4><span class="part-no">' + (i + 1) + '</span>' + esc(m.name.replace(/[【】]/g, '')) + '</h4>' +
        '<div class="ai-rich">' + richText(content) + '</div></section>';
    }).join('');
  }

  /** 管理员按岗位要求进行通用分析，不读取个人简历。 */
  async function runAnalyze(job) {
    if (!ensureAdminLogin('analyze')) { return; }
    var snapshot = Api.getAuthSnapshot();
    var generation = ++analyzeGeneration;
    switchView('ai');

    var body = $('#analyze-body');
    var head = $('#analyze-head');
    head.innerHTML = job ? '<div class="analyze-job"><span class="mini-title">' + esc(job.title) + '</span></div>' : '';

    var t0 = Date.now();
    body.innerHTML = '<div class="state state-loading"><div class="spinner"></div>' +
      '<div class="state-title">正在分析岗位要求…</div>' +
      '<div class="state-detail">岗位：' + esc(job && job.title || '') + '</div>' +
      '<div class="state-hint" id="analyze-elapsed">已等待 0 秒 · 该接口要跑一次大模型，通常 20~120 秒</div></div>';

    var timer = setInterval(function () {
      if (generation !== analyzeGeneration || !Api.isAuthSnapshot(snapshot)) { clearInterval(timer); return; }
      var el = $('#analyze-elapsed');
      if (el) {
        el.textContent = '已等待 ' + Math.floor((Date.now() - t0) / 1000) + ' 秒 · 该接口要跑一次大模型，通常 20~120 秒';
      }
    }, 1000);

    try {
      var resp = await Api.agentAnalyze(job);
      if (generation !== analyzeGeneration || !Api.isAuthSnapshot(snapshot)) { return; }
      var data = resp || {};
      renderAnalyze(job, data.reply);
      Toast.ok('分析完成，用时 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's');
    } catch (e) {
      if (generation !== analyzeGeneration || !Api.isAuthSnapshot(snapshot)) { return; }
      body.innerHTML = errorCard(e, null, null);
    } finally {
      clearInterval(timer);
    }
  }

  /* ==========================================================================
   * [10] 系统与爬虫
   * ======================================================================= */

  var CRAWL_HINTS = [
    '正在连接数据源（国聘网 / 国家大学生就业服务平台等）…',
    '正在按国企/央企条件过滤岗位…',
    '正在解析岗位详情并去重…',
    '正在写入数据库…',
    '数据源响应较慢属于正常现象，请勿关闭页面…'
  ];

  function renderCrawl() {
    var c = State.crawl;
    var btn = $('#btn-crawl');
    var status = $('#crawl-status');
    var bar = $('#crawl-progress');
    var hint = $('#crawl-hint');

    btn.disabled = c.running;
    btn.textContent = c.running ? '爬取中…' : '手动触发爬取';

    if (c.running) {
      var sec = Math.floor((Date.now() - c.startedAt) / 1000);
      status.innerHTML = '<span class="tag tag-warn">爬取中</span> 已用时 <b>' + fmtDuration(sec) + '</b>' +
        '<em class="muted"> · 实测 1~3 分钟，超时上限 5 分钟</em>';
      bar.classList.remove('hidden');
      bar.classList.add('indeterminate');
    } else {
      bar.classList.add('hidden');
      bar.classList.remove('indeterminate');
      status.innerHTML = c.result === null
        ? '<span class="tag tag-muted">空闲</span> 点击右侧按钮立即触发一次抓取'
        : c.result;
    }
    if (hint) { hint.textContent = c.hintText || ''; }

    $('#crawl-log').innerHTML = c.logs.map(function (l) {
      return '<li class="log-line"><span class="log-time">' + esc(l.time) + '</span>' + esc(l.text) + '</li>';
    }).join('');
  }

  function fmtDuration(sec) {
    var m = Math.floor(sec / 60), s = sec % 60;
    return (m > 0 ? m + ' 分 ' : '') + s + ' 秒';
  }

  function crawlLog(text) {
    var d = new Date();
    State.crawl.logs.push({ time: pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()), text: text });
    if (State.crawl.logs.length > 40) { State.crawl.logs.shift(); }
    renderCrawl();
  }

  async function runCrawl() {
    if (State.crawl.running) { return; }
    if (!isLoggedIn()) { Toast.warn('手动爬虫是管理端接口，请先登录'); return; }

    State.crawl.running = true;
    State.crawl.startedAt = Date.now();
    State.crawl.result = null;
    State.crawl.logs = [];
    State.crawl.hintText = CRAWL_HINTS[0];
    crawlLog('已发起 POST /admin/crawl/run，等待后端返回…');

    var hintIdx = 0;
    // 秒表：1~3 分钟的接口，没有计时用户会以为页面死了
    State.crawl.timer = setInterval(function () {
      var sec = Math.floor((Date.now() - State.crawl.startedAt) / 1000);
      var st = $('#crawl-status');
      if (st) {
        st.innerHTML = '<span class="tag tag-warn">爬取中</span> 已用时 <b>' + fmtDuration(sec) + '</b>' +
          '<em class="muted"> · 实测 1~3 分钟，超时上限 5 分钟</em>';
      }
    }, 1000);

    State.crawl.hintTimer = setInterval(function () {
      hintIdx = (hintIdx + 1) % CRAWL_HINTS.length;
      State.crawl.hintText = CRAWL_HINTS[hintIdx];
      var h = $('#crawl-hint');
      if (h) { h.textContent = State.crawl.hintText; }
      crawlLog(State.crawl.hintText);
    }, 12000);

    // 爬取期间关页面要拦一下：否则用户会以为"点了没反应"
    window.addEventListener('beforeunload', beforeUnloadGuard);

    try {
      var count = await Api.crawlRun();
      var sec2 = Math.floor((Date.now() - State.crawl.startedAt) / 1000);
      var n = (count === null || count === undefined) ? 0 : Number(count);
      State.crawl.result = '<span class="tag tag-success">完成</span> 本次抓到 <b>' + esc(n) + '</b> 条岗位' +
        '<em class="muted"> · 用时 ' + fmtDuration(sec2) + '</em>';
      crawlLog('爬取完成：新增/更新 ' + n + ' 条，用时 ' + fmtDuration(sec2));
      Toast.ok('爬取完成，抓到 ' + n + ' 条岗位');
      // 抓完数据变了，顺手刷新概览与岗位表
      loadOverviewSilently();
      if (State.view === 'jobs') { loadJobs(); }
    } catch (e) {
      State.crawl.result = errorCard(e, '重新触发爬取', 'crawl');
      crawlLog('失败：' + e.title + (e.detail ? '（' + e.detail + '）' : ''));
      if (e.kind === 'timeout') {
        Toast.warn('前端等待超时，但后端可能仍在爬取。可稍后刷新查看结果。');
      } else {
        Toast.err(e.title);
      }
    } finally {
      State.crawl.running = false;
      clearInterval(State.crawl.timer);
      clearInterval(State.crawl.hintTimer);
      State.crawl.hintText = '';
      window.removeEventListener('beforeunload', beforeUnloadGuard);
      renderCrawl();
    }
  }

  function beforeUnloadGuard(ev) {
    if (!State.crawl.running && !State.chat.sending) { return; }
    ev.preventDefault();
    ev.returnValue = '还有请求正在执行，确定离开吗？';
    return ev.returnValue;
  }

  /**
   * 接口自检：把每个端点的真实结果摊开。
   * 这是给「部署后打不通」准备的——比逐个 F12 快得多，也顺便证明了
   * 「后端不可用时页面不会白屏」。
   */
  async function runDiag() {
    var box = $('#diag-table');
    box.innerHTML = loadingCard('正在逐个探测接口…');

    var tests = [
      { name: 'Java 存活探针', method: 'GET', path: '/user/stats', auth: 'none', need: null,
        note: '免鉴权。能通即说明 Java 后端正常。' },
      { name: '岗位列表（用户端）', method: 'GET', path: '/user/job/list', auth: 'none', need: null,
        note: '免鉴权。概览页图表的数据源。' },
      { name: '首页统计', method: 'GET', path: '/user/stats', auth: 'none', need: null,
        note: '本版本返回 companyCount/jobCount/applyTotal 等。' },
      { name: 'AI 对话历史（Agent 探针）', method: 'GET', path: '/admin/agent/history?sessionId=health', auth: 'admin', need: 'adminToken',
        note: '验证管理员鉴权及历史接口；不探测 Python。' },
      { name: '岗位分页', method: 'GET', path: '/admin/job/page?page=1&pageSize=1', auth: 'admin', need: 'adminToken',
        note: '管理端接口，需要 token 头。' },
      { name: '企业分页', method: 'GET', path: '/admin/company/page?page=1&pageSize=1', auth: 'admin', need: 'adminToken', note: '' },
      { name: '投递分页', method: 'GET', path: '/admin/application/page?page=1&pageSize=1', auth: 'admin', need: 'adminToken', note: '' },
      { name: '分类列表', method: 'GET', path: '/admin/category/list', auth: 'admin', need: 'adminToken', note: '' },
      { name: '公告列表', method: 'GET', path: '/admin/announcement/list', auth: 'admin', need: 'adminToken', note: '' }
    ];

    var rows = [];
    for (var i = 0; i < tests.length; i++) {
      var t = tests[i];
      var result;
      if (t.need === 'adminToken' && !isLoggedIn()) {
        result = { cls: 'skip', label: '跳过', detail: '未登录，无法验证' };
      } else {
        try {
          var t0 = Date.now();
          var data = await Api.request(t.path, { method: t.method, auth: t.auth, timeout: 12000 });
          var size = Array.isArray(data) ? data.length + ' 条' : (data ? '有数据' : '空 data');
          result = { cls: 'ok', label: '通过 ' + (Date.now() - t0) + 'ms', detail: size };
        } catch (e) {
          var code = e.kind === 'unauthorized' ? '401' : (e.status || e.kind);
          result = { cls: 'fail',
            label: '失败 ' + code, detail: e.title + (e.hint ? ' · ' + e.hint : '') };
        }
      }
      rows.push('<tr><td>' + esc(t.name) + '</td>' +
        '<td><code>' + esc(t.method + ' ' + t.path) + '</code></td>' +
        '<td><span class="tag tag-' + (result.cls === 'ok' ? 'success' : result.cls === 'warn' ? 'warn' : result.cls === 'skip' ? 'muted' : 'danger') + '">' +
        esc(result.label) + '</span></td>' +
        '<td class="col-desc">' + esc(result.detail || '') + (t.note ? '<div class="muted">' + esc(t.note) + '</div>' : '') + '</td></tr>');
    }

    box.innerHTML = '<table class="data-table"><thead><tr><th>检测项</th><th>请求</th><th>结果</th><th>说明</th></tr></thead><tbody>' +
      rows.join('') + '</tbody></table>';
    Toast.ok('自检完成');
  }

  /* ==========================================================================
   * [11] 视图路由与初始化
   * ======================================================================= */

  var VIEW_LOADERS = {
    overview: loadOverview,
    jobs: loadJobs,
    applications: loadApplications,
    companies: loadCompanies,
    ai: function () { loadChatHistory(); renderLatencyChart(); },
    system: loadSystem
  };

  function switchView(view) {
    State.view = view;
    $$('.view').forEach(function (el) { el.classList.toggle('active', el.getAttribute('data-view') === view); });
    $$('.tab').forEach(function (el) { el.classList.toggle('active', el.getAttribute('data-view') === view); });
    if (location.hash !== '#' + view) { history.replaceState(null, '', '#' + view); }
    loadView(view);
  }

  function loadView(view) {
    var fn = VIEW_LOADERS[view];
    if (fn) { fn(); }
  }

  /** 概览静默刷新：失败不弹错，因为它只是"顺手更新" */
  function loadOverviewSilently() {
    Api.userStats().then(function (s) { renderStats(s, null); }).catch(function () { });
  }

  async function loadSystem() {
    renderCrawl();

    // 分类列表
    var catBox = $('#category-list');
    if (!isLoggedIn()) {
      catBox.innerHTML = needLoginCard('分类列表');
      $('#system-announcement-list').innerHTML = needLoginCard('公告列表');
    } else {
      catBox.innerHTML = loadingCard('正在加载分类…');
      try {
        var cats = await Api.categoryList();
        catBox.innerHTML = cats.length
          ? '<ul class="chip-list">' + cats.map(function (c) {
            return '<li class="chip chip-lg">' + esc(c.name || '未命名') +
              (Number(c.status) === 0 ? ' <em class="muted">(停用)</em>' : '') + '</li>';
          }).join('') + '</ul>'
          : emptyCard('暂无分类');
      } catch (e) { catBox.innerHTML = errorCard(e, '重新加载', null); }

      $('#system-announcement-list').innerHTML = loadingCard('正在加载公告…');
      try {
        renderAnnouncements('#system-announcement-list', await Api.announcementList(), false);
      } catch (e) { $('#system-announcement-list').innerHTML = errorCard(e, '重新加载', null); }
    }

    // 企业总数（用 list 接口，顺带验证 /admin/company/list）
    var cBox = $('#system-company-count');
    if (isLoggedIn()) {
      try {
        var cl = await Api.companyList();
        cBox.innerHTML = '<span class="big-num">' + cl.length + '</span> 家企业（/admin/company/list）';
      } catch (e) { cBox.innerHTML = '<span class="muted">企业列表读取失败：' + esc(e.title) + '</span>'; }
    } else {
      cBox.innerHTML = '<span class="muted">登录后显示</span>';
    }
  }

  /* ---------- 全局事件委托 ----------
   * 用委托而不是给每个按钮单独绑定：表格是反复重绘的，
   * 逐个绑定既啰嗦又容易漏（重绘后监听器就没了）。
   * ------------------------------------ */
  function bindEvents() {
    $$('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () { switchView(tab.getAttribute('data-view')); });
    });

    // 只监听 form 的 submit：登录按钮是 type="submit"，再单独绑 click 会触发两次登录请求
    $('#login-form').addEventListener('submit', doLogin);
    $('#btn-logout').addEventListener('click', doLogout);
    $('#btn-api-base').addEventListener('click', applyApiBase);
    $('#btn-refresh-health').addEventListener('click', function () { probeHealth(false); });

    $('#btn-job-search').addEventListener('click', function () {
      State.jobs.name = $('#job-search').value.trim();
      State.jobs.status = $('#job-status-filter').value;
      State.jobs.page = 1;
      loadJobs();
    });
    $('#job-search').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { $('#btn-job-search').click(); }
    });
    $('#btn-job-reset').addEventListener('click', function () {
      $('#job-search').value = '';
      $('#job-status-filter').value = '';
      State.jobs.name = ''; State.jobs.status = ''; State.jobs.page = 1;
      loadJobs();
    });
    $('#btn-job-refresh').addEventListener('click', loadJobs);

    $('#btn-app-search').addEventListener('click', function () {
      State.apps.status = $('#app-status-filter').value;
      State.apps.page = 1;
      loadApplications();
    });
    $('#btn-app-reset').addEventListener('click', function () {
      $('#app-status-filter').value = '';
      State.apps.status = ''; State.apps.page = 1;
      loadApplications();
    });

    $('#btn-company-search').addEventListener('click', function () {
      State.companies.name = $('#company-search').value.trim();
      State.companies.page = 1;
      loadCompanies();
    });
    $('#company-search').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { $('#btn-company-search').click(); }
    });
    $('#btn-company-reset').addEventListener('click', function () {
      $('#company-search').value = '';
      State.companies.name = ''; State.companies.page = 1;
      loadCompanies();
    });

    // AI 面板
    $('#btn-chat-send').addEventListener('click', function () { sendChat($('#chat-input').value); });
    $('#chat-input').addEventListener('keydown', function (e) {
      // Enter 发送、Shift+Enter 换行：聊天框的既定习惯
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat($('#chat-input').value); }
    });
    $('#btn-chat-clear').addEventListener('click', clearChat);
    $$('.quick-q').forEach(function (b) {
      b.addEventListener('click', function () { $('#chat-input').value = b.textContent.trim(); $('#chat-input').focus(); });
    });
    $('#analyze-job-id-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var id = $('#analyze-job-id').value.trim();
      if (!id) { return; }
      runAnalyze({ id: id, title: '岗位 #' + id });
    });

    // 系统页
    $('#btn-crawl').addEventListener('click', runCrawl);
    $('#btn-diag').addEventListener('click', runDiag);

    // 表格内的按钮：统一委托到 document
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.getAttribute) { return; }

      var up = t.getAttribute('data-job-up');
      var down = t.getAttribute('data-job-down');
      var ai = t.getAttribute('data-job-ai');
      var rate = t.getAttribute('data-rate');
      var retry = t.getAttribute('data-retry');
      var goto = t.getAttribute('data-goto');
      if (up) { toggleJobStatus(up, 1); }
      else if (down) { toggleJobStatus(down, 0); }
      else if (ai) {
        // 从已加载的记录里找完整对象，AI 分析只用到 id，但展示头部信息需要 title 等
        var job = State.jobs.records.filter(function (j) { return String(j.id) === String(ai); })[0] || { id: ai };
        runAnalyze(job);
      }
      else if (rate) { rateMessage(Number(t.getAttribute('data-idx')), Number(rate)); }
      else if (retry) {
        if (retry === 'overview') { loadOverview(); }
        else if (retry === 'jobs') { loadJobs(); }
        else if (retry === 'apps') { loadApplications(); }
        else if (retry === 'companies') { loadCompanies(); }
        else if (retry === 'crawl') { runCrawl(); }
        else if (retry === 'ai-history') { loadChatHistory(); }
      }
      else if (goto === 'login') {
        $('#login-user').focus();
        Toast.show('账号 admin，密码 123456');
      }
      else if (goto === 'ai') {
        switchView('ai');

      }
    });

    $('#login-user').value = 'admin';
    $('#login-pass').value = '123456';
  }

  /* ---------- 启动 ---------- */
  function init() {
    Api.onAuthChange(function () {
      resetAgentUi();
      renderLoginState();
      updateAdminBadges();
      State.health.agent = { level: 'warn', ok: false, note: isLoggedIn() ? '等待探测历史接口' : '请先登录管理员账号' };
      renderHealth();
    });
    $('#api-base').value = Api.Store.getApiBase();
    renderLoginState();
    updateAdminBadges();
    renderChat();
    renderLatencyChart();
    renderCrawl();
    bindEvents();

    // 首屏不阻塞在网络上：先把空壳渲染出来，再异步填数据，
    // 这样后端全挂时用户看到的也是有信息的界面，而不是白屏。
    probeHealth(true);
    var initial = (location.hash || '').replace('#', '') || 'overview';
    switchView(VIEW_LOADERS[initial] ? initial : 'overview');

    // 60 秒轮询一次健康状态；页面在后台时不轮询（省资源，也避免无意义报错刷屏）
    setInterval(function () {
      if (document.hidden) { return; }
      probeHealth(true);
    }, 60000);

    // 全局兜底：任何漏网的异常都提示一下，绝不静默
    window.addEventListener('error', function (ev) {
      if (ev && ev.message) { console.error('[job-web] 未捕获异常：', ev.message); }
    });
    window.addEventListener('unhandledrejection', function (ev) {
      console.error('[job-web] 未处理的 Promise 拒绝：', ev && ev.reason);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
