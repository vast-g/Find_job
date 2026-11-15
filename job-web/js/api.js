/* =============================================================================
 * api.js —— 统一接口访问层（零依赖，不引 axios）
 *
 * 这一层集中处理 5 件容易到处写错的事，业务代码就不用重复关心了：
 *   1. 统一响应结构 { code, msg, data }：本项目 **code === 1 才是成功**（不是常见的 0）。
 *   2. 管理端统一使用 token，公开读取免鉴权。
 *   3. 超时：AI 20~120s、爬虫 1~3min，普通接口 15s。fetch 默认不超时，
 *      不设的话页面会一直转圈，看起来像卡死。
 *   4. 错误分类：网络失败 / 超时 / 401 / HTTP 错误 / code!==1 业务失败 / 返回体不是 JSON，
 *      每一类都给一句「人能看懂 + 能拿去排查」的中文提示。
 *   5. 分页结构兼容：PageResult 是 { total, records }，但字段名可能变成 rows / list，
 *      这里统一归一化，上层拿到的永远是 { total, records }。
 *
 * 为什么用普通 <script> + 全局命名空间，而不是 ES Module：
 *   本项目要求「零构建链、双击也能打开」。file:// 下 ES Module 会被浏览器以
 *   跨源策略拦掉，普通脚本则不受影响，容错更高。
 * ========================================================================== */
(function (global) {
  'use strict';

  /** 后端 com.job.result.Result：1 成功、0 失败。写成常量，避免有人手滑写成 0。 */
  var SUCCESS_CODE = 1;

  /** 各类请求的超时（毫秒）。区分开是因为 AI/爬虫的耗时和普通查询不在一个量级。 */
  var TIMEOUT = {
    normal: 15000,    // 普通查询：毫秒级就该回来，15s 已经非常宽松
    chat: 180000,     // AI 对话：实测 20~120s，留到 3 分钟
    analyze: 180000,  // 岗位分析：走一次大模型，同对话量级
    crawl: 300000     // 手动爬虫：实测 1~3 分钟，给到 5 分钟
  };

  /** localStorage：跨刷新保留（接口地址、管理端 token） */
  var LS = {
    apiBase: 'jobweb.apiBase',
    adminToken: 'jobweb.adminToken',
    adminName: 'jobweb.adminName',
    adminAccount: 'jobweb.adminAccount'
  };

  var SS = { sessionId: 'jobweb.agentSessionId' };
  var revision = 0;
  var listeners = [];
  function changed() { revision++; listeners.forEach(function (fn) { fn(); }); }

  /* ---------------------------------------------------------------------------
   * 存储小工具：localStorage 在隐私模式下可能直接抛异常，所以全部 try 包住。
   * ------------------------------------------------------------------------ */
  function safeGet(store, key) {
    try { return store.getItem(key); } catch (e) { return null; }
  }
  function safeSet(store, key, val) {
    try {
      if (val === null || val === undefined) { store.removeItem(key); }
      else { store.setItem(key, val); }
    } catch (e) { /* 存不进去不影响功能，忽略 */ }
  }

  var Store = {
    /** 接口地址前缀。默认 '/api'：与部署约定一致（nginx 把 /api/ 反代到 8080）。 */
    getApiBase: function () {
      var v = safeGet(global.localStorage, LS.apiBase);
      return v === null ? '/api' : v;
    },
    setApiBase: function (v) {
      if (v === Store.getApiBase()) { return; }
      safeSet(global.localStorage, LS.apiBase, v);
      Api.logout();
    },

    getAdminToken: function () { return safeGet(global.localStorage, LS.adminToken); },
    setAdminToken: function (v) { safeSet(global.localStorage, LS.adminToken, v); },
    getAdminName: function () { return safeGet(global.localStorage, LS.adminName); },
    setAdminName: function (v) { safeSet(global.localStorage, LS.adminName, v); },

    getSessionId: function () { return safeGet(global.sessionStorage, SS.sessionId); },
    setSessionId: function (v) {
      if (v === Store.getSessionId()) { return; }
      safeSet(global.sessionStorage, SS.sessionId, v);
      // Session changes do not change the authenticated identity.
    }
  };

  /* ---------------------------------------------------------------------------
   * ApiError：把「技术错误」翻译成「可展示、可排查」的结构。
   *   kind  —— 机器判断用，UI 可按类型决定颜色/是否提示重新登录
   *   title —— 一句人话
   *   hint  —— 排查建议（面向部署者，不是面向终端用户，面试演示时很有用）
   * ------------------------------------------------------------------------ */
  function ApiError(kind, title, opt) {
    opt = opt || {};
    this.name = 'ApiError';
    this.kind = kind;                 // network | timeout | unauthorized | http | business | parse | aborted
    this.title = title || '请求失败';
    this.detail = opt.detail || '';   // 原始错误/后端 msg/HTTP 状态
    this.hint = opt.hint || '';       // 怎么排查
    this.status = opt.status || 0;
    this.url = opt.url || '';
    this.message = this.title + (this.detail ? '：' + this.detail : '');
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /* ---------------------------------------------------------------------------
   * URL 组装
   * ------------------------------------------------------------------------ */
  function buildUrl(path, query) {
    var base = Store.getApiBase() || '';
    // 去掉 base 末尾多余的 '/'，避免拼出 //user/stats
    base = base.replace(/\/+$/, '');
    var url = base + path;

    if (query) {
      var parts = [];
      Object.keys(query).forEach(function (k) {
        var v = query[k];
        // 空值不发：后端 DTO 是 int 类型时，传空字符串会 400，不如不发让其走默认分支
        if (v === null || v === undefined || v === '') { return; }
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
      });
      if (parts.length) { url += (url.indexOf('?') === -1 ? '?' : '&') + parts.join('&'); }
    }
    return url;
  }

  /** 管理端统一鉴权，公开读取不附带凭证。 */
  function pickAuthHeaders(path, auth) {
    var needAdmin = path.indexOf('/admin/') === 0 && path !== '/admin/employee/login';
    if (needAdmin && !Store.getAdminToken()) {
      throw new ApiError('unauthorized', '请先登录管理员账号', { status: 401 });
    }
    return needAdmin || auth === 'admin' ? { token: Store.getAdminToken() } : {};
  }

  /* ---------------------------------------------------------------------------
   * 核心请求
   * opts: { method, query, body, auth, timeout, allowRaw }
   * 返回值：data 字段本身（已剥离 Result 外壳）；无 data 时返回 null。
   * ------------------------------------------------------------------------ */
  async function request(path, opts) {
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();
    var timeout = opts.timeout || TIMEOUT.normal;
    var url = buildUrl(path, opts.query);

    var snapshot = Api.getAuthSnapshot();
    var headers = pickAuthHeaders(path, opts.auth || 'auto');
    var init = { method: method, headers: headers };

    if (opts.body !== undefined && opts.body !== null) {
      headers['Content-Type'] = 'application/json;charset=utf-8';
      init.body = JSON.stringify(opts.body);
    }

    // 自己实现超时：fetch 没有 timeout 选项，AbortController 是唯一干净的做法
    var controller = new AbortController();
    var timedOut = false;
    var timer = setTimeout(function () { timedOut = true; controller.abort(); }, timeout);
    init.signal = controller.signal;

    var res;
    try {
      res = await fetch(url, init);
    } catch (e) {
      clearTimeout(timer);
      if (timedOut) {
        throw new ApiError('timeout', '请求超时（已等待 ' + Math.round(timeout / 1000) + ' 秒）', {
          detail: method + ' ' + url,
          hint: 'AI 对话与手动爬虫本身就要 20~180 秒。若这类接口经常超时，检查 nginx 的 proxy_read_timeout（默认 60s 会 504）。',
          url: url
        });
      }
      if (e && e.name === 'AbortError') {
        throw new ApiError('aborted', '请求已取消', { url: url });
      }
      throw new ApiError('network', '网络请求失败', {
        detail: (e && e.message) || String(e),
        hint: '1) Java 后端是否已在 8080 启动；2) 当前页面与接口是否同源（后端没有 CORS 配置，跨源会被浏览器拦截）；3) 接口地址前缀是否正确。',
        url: url
      });
    }
    clearTimeout(timer);

    // 401 单独识别：拦截器里 JwtTokenAdminInterceptor / JwtTokenUserInterceptor 失败就是 401
    if (res.status === 401) {
      if (headers.token && Api.isAuthSnapshot(snapshot)) { Api.logout(); }
      throw new ApiError('unauthorized', '未授权（401）', {
        detail: method + ' ' + url,
        hint: '请重新登录管理员账号，业务和 AI 功能共用该登录。',
        status: 401,
        url: url
      });
    }

    var text = '';
    try { text = await res.text(); } catch (e) { text = ''; }

    if (!res.ok) {
      // 502/503/504 是反向代理层的错误，语义和 500（后端自己抛异常）完全不同，
      // 分开提示能省掉大量"到底是前端还是后端"的排查时间。
      var httpHint;
      if (res.status === 404) {
        httpHint = '路径不存在：确认接口前缀。本后端控制器映射是 /user/**、/admin/**，没有 context-path；若通过 nginx 用 /api/ 前缀访问，proxy_pass 指向上游时末尾必须带一个斜杠，才会把 /api/ 前缀替换掉。';
      } else if (res.status === 502 || res.status === 503) {
        httpHint = '反向代理连不上后端：确认 Java 是否已在 8080 启动（nginx 返回 502/503 就代表上游不可达）。';
      } else if (res.status === 504) {
        httpHint = '上游超时：AI（20~120s）与手动爬虫（1~3min）这类长请求，需要把 nginx 的 proxy_read_timeout 调大（默认只有 60s）。';
      } else if (res.status === 500) {
        httpHint = '后端抛异常了，去看 Java 控制台日志（controller/service 已开 info 级日志）。';
      } else {
        httpHint = '检查后端与反向代理状态。';
      }
      throw new ApiError('http', '接口返回 HTTP ' + res.status, {
        detail: method + ' ' + url + (text ? ' · ' + text.slice(0, 160) : ''),
        hint: httpHint,
        status: res.status,
        url: url
      });
    }

    // 空响应体是合法的：后端很多接口是 Result.success()，只有 code 没有 data
    if (!text) { return null; }

    var json;
    try {
      json = JSON.parse(text);
    } catch (e) {
      // 走到这里通常意味着「拿到的其实是 HTML」——典型原因是代理配置不对，
      // 把接口请求兜到了前端 index.html（try_files 的兜底行为）。
      throw new ApiError('parse', '返回内容不是合法 JSON', {
        detail: text.slice(0, 120).replace(/\s+/g, ' '),
        hint: '常见原因：反向代理把 /api/ 请求交给了静态站点，返回了 index.html。检查 nginx 的 proxy_pass 是否去掉了 /api 前缀。',
        url: url
      });
    }

    // 有 code 字段就按统一结构校验收；没有 code 视为「非包装返回」，原样交回。
    if (json && typeof json === 'object' && !Array.isArray(json) && 'code' in json) {
      if (json.code !== SUCCESS_CODE) {
        throw new ApiError('business', json.msg || '业务处理失败', {
          detail: 'code=' + json.code + ' ' + (json.msg || ''),
          hint: '这是后端主动返回的失败（code!==1）。msg 就是后端给的原因。',
          url: url
        });
      }
      return json.data === undefined ? null : json.data;
    }

    // 容错：万一后端某天直接返回裸数组/裸对象，也不至于让页面白屏
    return json;
  }

  /* ---------------------------------------------------------------------------
   * 分页归一化：data 形如 { total, records }，但兼容 rows / list / items。
   * 后端 PageResult 是 (long total, List records)，不同分支/版本字段名会有出入。
   * ------------------------------------------------------------------------ */
  function normalizePage(data) {
    if (!data) { return { total: 0, records: [] }; }
    if (Array.isArray(data)) { return { total: data.length, records: data }; }

    var records = data.records || data.rows || data.list || data.items || [];
    if (!Array.isArray(records)) { records = []; }

    var total = data.total;
    if (typeof total !== 'number') { total = data.totalCount; }
    if (typeof total !== 'number') { total = data.count; }
    if (typeof total !== 'number') { total = data.totalElements; }
    if (typeof total !== 'number') { total = records.length; }

    return { total: total, records: records };
  }

  /** 列表归一化：接口可能返回数组，也可能返回分页对象，统一成数组。 */
  function normalizeList(data) {
    if (!data) { return []; }
    if (Array.isArray(data)) { return data; }
    return normalizePage(data).records;
  }

  /* ===========================================================================
   * 具体接口
   * 每个方法都注明「路径依据」——路径是照着 Java 控制器核对的，不是照抄文档。
   * ======================================================================== */
  var Api = {
    Store: Store,
    ApiError: ApiError,
    TIMEOUT: TIMEOUT,
    request: request,
    onAuthChange: function (fn) { listeners.push(fn); },
    getAuthSnapshot: function () {
      return { token: Store.getAdminToken(), base: Store.getApiBase(), revision: revision };
    },
    isAuthSnapshot: function (s) {
      return s.token === Store.getAdminToken() && s.base === Store.getApiBase() && s.revision === revision;
    },
    normalizePage: normalizePage,
    normalizeList: normalizeList,

    /* ---------------------------- 鉴权 ---------------------------- */

    /** 管理端登录：POST /admin/employee/login（该路径在拦截器白名单里，无需 token） */
    login: async function (username, password) {
      var snapshot = Api.getAuthSnapshot();
      var data = await request('/admin/employee/login', {
        method: 'POST',
        auth: 'none',
        body: { username: username, password: password }
      });
      if (!Api.isAuthSnapshot(snapshot)) {
        throw new ApiError('aborted', '登录状态已改变，请重新登录');
      }
      if (data && data.token) {
        var account = String(data.id === undefined || data.id === null ? username : data.id);
        var previous = safeGet(global.localStorage, LS.adminAccount);
        if (previous !== account || !Store.getAdminToken()) { Store.setSessionId(null); }
        Store.setAdminToken(data.token);
        safeSet(global.localStorage, LS.adminAccount, account);
        Store.setAdminName(data.name || data.userName || username);
        changed();
      }
      return data;
    },

    logout: function () {
      Store.setAdminToken(null);
      Store.setAdminName(null);
      safeSet(global.localStorage, LS.adminAccount, null);
      Store.setSessionId(null);
      changed();
    },

    isLoggedIn: function () { return !!Store.getAdminToken(); },

    /* ------------------------ 管理端接口 ------------------------ */

    /**
     * 岗位分页：GET /admin/job/page
     * 注意：JobPageQueryDTO 的模糊查询字段名是 **title**（JobMapper.xml 里是
     * `and j.title like concat('%',#{title},'%')`），不是任务书里写的 name。
     * 这里两个都发：后端只认识 title，多发的 name 会被忽略；万一以后后端改名也能兼容。
     */
    jobPage: async function (params) {
      params = params || {};
      var data = await request('/admin/job/page', {
        auth: 'admin',
        query: {
          page: params.page || 1,
          pageSize: params.pageSize || 10,
          title: params.name || '',
          name: params.name || '',
          status: (params.status === '' || params.status === undefined || params.status === null) ? '' : params.status
        }
      });
      return normalizePage(data);
    },

    /**
     * 岗位上下架：POST /admin/job/status/{status}?id=xxx
     * 依据：admin/JobController#startOrStop(@PathVariable Integer status, Long id)
     * —— id 没有 @RequestBody，是普通请求参数，所以必须放在 query 上，放 body 无效。
     */
    jobStatus: function (id, status) {
      return request('/admin/job/status/' + status, {
        method: 'POST',
        auth: 'admin',
        query: { id: id }
      });
    },

    /** 企业分页：GET /admin/company/page（CompanyPageQueryDTO 确实叫 name） */
    companyPage: async function (params) {
      params = params || {};
      var data = await request('/admin/company/page', {
        auth: 'admin',
        query: {
          page: params.page || 1,
          pageSize: params.pageSize || 10,
          name: params.name || ''
        }
      });
      return normalizePage(data);
    },

    companyList: async function () {
      return normalizeList(await request('/admin/company/list', { auth: 'admin' }));
    },

    categoryList: async function () {
      return normalizeList(await request('/admin/category/list', { auth: 'admin' }));
    },

    /** 投递分页：GET /admin/application/page（ApplicationPageQueryDTO: page/pageSize/jobId/status） */
    applicationPage: async function (params) {
      params = params || {};
      var data = await request('/admin/application/page', {
        auth: 'admin',
        query: {
          page: params.page || 1,
          pageSize: params.pageSize || 10,
          status: (params.status === '' || params.status === undefined || params.status === null) ? '' : params.status
        }
      });
      return normalizePage(data);
    },

    announcementList: async function () {
      return normalizeList(await request('/admin/announcement/list', { auth: 'admin' }));
    },

    /**
     * 手动爬虫：POST /admin/crawl/run → data 是抓到的条数（Result<Integer>）
     * 超时给 5 分钟：JobCrawlerService 会逐个数据源翻页抓取，实测 1~3 分钟。
     */
    crawlRun: function () {
      return request('/admin/crawl/run', { method: 'POST', auth: 'admin', timeout: TIMEOUT.crawl });
    },

    /* ------------------------ 用户端接口 ------------------------ */

    /**
     * 首页统计：GET /user/stats（在 JwtTokenUserInterceptor 白名单里，免鉴权）
     * 实际返回键名以 StatsController 为准：companyCount / jobCount / announcementCount /
     * applyTotal / applyProgress / applyRemind。任务书里提到的 userCount、applicationCount
     * 这个版本并不返回 —— 所以下面用别名兜底，取不到就显示「—」，绝不拿 0 冒充。
     */
    userStats: function () {
      return request('/user/stats', { auth: 'none' });
    },

    /** 岗位列表：GET /user/job/list（免鉴权），可带 name / categoryId */
    userJobList: async function (params) {
      params = params || {};
      var data = await request('/user/job/list', {
        auth: 'none',
        query: { name: params.name || '', categoryId: params.categoryId || '' }
      });
      return normalizeList(data);
    },

    userJobDetail: function (id) {
      return request('/user/job/' + id, { auth: 'none' });
    },

    userCompanyDetail: function (id) {
      return request('/user/company/' + id, { auth: 'none' });
    },

    /** AI 和业务共用管理员登录。 */
    agentChat: function (message, sessionId) {
      return request('/admin/agent/chat', {
        method: 'POST',
        timeout: TIMEOUT.chat,
        body: { message: message, sessionId: sessionId || '' }
      });
    },

    /** 对话历史：GET /admin/agent/history?sessionId=xxx */
    agentHistory: function (sessionId) {
      return request('/admin/agent/history', {
        query: { sessionId: sessionId }
      });
    },

    /** 分析岗位要求，不读取候选人个人简历。 */
    agentAnalyze: function (job) {
      return request('/admin/agent/analyze', {
        method: 'POST',
        timeout: TIMEOUT.analyze,
        body: { jobId: job && job.id }
      });
    },

    agentFeedback: function (body) {
      return request('/admin/agent/feedback', { method: 'POST', body: body });
    },

    /** Java 后端探针：/user/stats 免鉴权，能通就说明 Java 活着 */
    healthJava: async function () {
      var t0 = Date.now();
      try {
        await request('/user/stats', { auth: 'none', timeout: 6000 });
        return { ok: true, ms: Date.now() - t0, level: 'up' };
      } catch (e) {
        return { ok: false, ms: Date.now() - t0, level: 'down', error: e };
      }
    },

    /** 历史接口可用不代表 Python 或模型健康。 */
    healthAgent: async function () {
      var t0 = Date.now();
      if (!Api.isLoggedIn()) { return { ok: false, level: 'warn', note: '请先登录管理员账号' }; }
      try {
        await request('/admin/agent/history', {
          auth: 'admin',
          query: { sessionId: 'health' },
          timeout: 10000
        });
        return { ok: true, ms: Date.now() - t0, level: 'up', note: '已鉴权历史接口可用（未探测 Python）' };
      } catch (e) {
        if (e.kind === 'unauthorized') {
          return { ok: false, ms: Date.now() - t0, level: 'warn', error: e, note: '管理员登录已失效' };
        }
        return { ok: false, ms: Date.now() - t0, level: 'down', error: e, note: e.kind === 'timeout' ? '探测超时' : '不可达' };
      }
    }
  };

  global.Api = Api;

  // 便于在浏览器控制台里手工排查：Api.request('/user/stats', {auth:'none'})
})(window);
