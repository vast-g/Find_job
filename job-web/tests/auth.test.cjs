'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const apiSource = fs.readFileSync(path.join(root, 'js/api.js'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function storage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key)
  };
}
function response(data, status = 200) {
  return { status, ok: status >= 200 && status < 300,
    text: async () => JSON.stringify({ code: 1, data }) };
}
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}
async function settle() {
  for (let i = 0; i < 30; i++) { await Promise.resolve(); }
}
function element() {
  const listeners = new Map();
  const classes = new Set();
  return {
    value: '', textContent: '', innerHTML: '', children: [], disabled: false,
    classList: { add: x => classes.add(x), remove: x => classes.delete(x),
      toggle(x, on) { if (on) { classes.add(x); } else { classes.delete(x); } },
      contains: x => classes.has(x) },
    addEventListener(type, fn) {
      if (!listeners.has(type)) { listeners.set(type, []); }
      listeners.get(type).push(fn);
    },
    async emit(type, event = {}) {
      await Promise.all((listeners.get(type) || []).map(fn => fn({ preventDefault() {}, ...event })));
      await settle();
    },
    appendChild(child) { this.children.push(child); child.parentNode = this; },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    get firstChild() { return this.children[0]; },
    querySelector() { return null; }, querySelectorAll() { return []; }, focus() {}
  };
}
function harness(withApp = false) {
  const calls = [];
  let handler = async (url, init) => {
    if (url.endsWith('/admin/employee/login')) {
      const { username } = JSON.parse(init.body);
      return response({ id: username, name: username, token: 'server-token-' + username });
    }
    return response([]);
  };
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], element()]));
  const document = {
    readyState: 'complete', hidden: false,
    querySelector: sel => sel.startsWith('#') ? nodes.get(sel.slice(1)) || null : null,
    querySelectorAll() { return []; },
    createElement: element,
    ...element()
  };
  // element helpers above include query methods; restore the document lookup.
  document.querySelector = sel => sel.startsWith('#') ? nodes.get(sel.slice(1)) || null : null;
  const context = vm.createContext({
    console, localStorage: storage(), sessionStorage: storage(), document,
    AbortController, setTimeout: () => 1, clearTimeout() {},
    setInterval: () => 1, clearInterval() {}, requestAnimationFrame: fn => fn(),
    location: { hash: '#ai' }, history: { replaceState() {} },
    Charts: { line() {}, donut() {}, hbars() {}, columns() {} },
    fetch: async (url, init) => { calls.push({ url, init }); return handler(url, init); },
    addEventListener() {}, removeEventListener() {}
  });
  context.window = context;
  vm.runInContext(apiSource, context, { filename: 'js/api.js' });
  if (withApp) { vm.runInContext(appSource, context, { filename: 'js/app.js' }); }
  return { Api: context.Api, calls, nodes, document,
    setHandler: fn => { handler = fn; } };
}

test('AI and business require admin login; public reads remain anonymous', async () => {
  const h = harness();
  for (const operation of [() => h.Api.agentChat('hi'), () => h.Api.agentAnalyze({ id: 1 }),
    () => h.Api.agentHistory('old'), () => h.Api.agentFeedback({}),
    () => h.Api.jobPage({}), () => h.Api.request('/admin/job/page', { auth: 'none' })]) {
    await assert.rejects(operation, e => e.kind === 'unauthorized');
  }
  assert.equal((await h.Api.healthAgent()).level, 'warn');
  assert.equal(h.calls.length, 0);
  await h.Api.userStats(); await h.Api.userJobList();
  assert.ok(h.calls.every(c => !c.init.headers.token && !c.init.headers.authentication));
});

test('one server login authorizes all four AI endpoints, health and business', async () => {
  const h = harness();
  await h.Api.login('alice', 'password');
  await h.Api.agentChat('hello', 's1');
  await h.Api.agentAnalyze({ id: 42, title: 'Job' }, { private: 'must not send' });
  await h.Api.agentHistory('s1');
  await h.Api.agentFeedback({ sessionId: 's1', rating: 1 });
  const health = await h.Api.healthAgent();
  await h.Api.jobPage({});
  assert.match(health.note, /历史接口可用.*未探测 Python/);
  const ai = h.calls.filter(c => c.url.includes('/admin/agent/'));
  assert.deepEqual(new Set(ai.map(c => c.url.split('?')[0].split('/').pop())),
    new Set(['chat', 'analyze', 'history', 'feedback']));
  for (const c of h.calls.slice(1)) {
    assert.equal(c.init.headers.token, 'server-token-alice');
    assert.equal(c.init.headers.authentication, undefined);
  }
  assert.equal(h.calls[0].init.headers.token, undefined);
  assert.deepEqual(JSON.parse(ai.find(c => c.url.endsWith('/analyze')).init.body), { jobId: 42 });
  await h.Api.userStats();
  assert.equal(h.calls.at(-1).init.headers.token, undefined);
});

test('current 401 removes login and session; late 401 cannot log out a new login', async () => {
  const h = harness();
  await h.Api.login('alice', 'pw'); h.Api.Store.setSessionId('alice-session');
  h.setHandler(async () => response(null, 401));
  await assert.rejects(h.Api.agentChat('hi'), e => e.kind === 'unauthorized');
  assert.equal(h.Api.isLoggedIn(), false);
  assert.equal(h.Api.Store.getSessionId(), null);
  const late = deferred();
  h.setHandler(async url => url.endsWith('/login')
    ? response({ id: 'alice', token: 'same-token' }) : late.promise);
  await h.Api.login('alice', 'pw');
  const old = h.Api.agentHistory('old');
  const rejection = assert.rejects(old, e => e.kind === 'unauthorized');
  h.Api.logout();
  await h.Api.login('alice', 'pw');
  h.Api.Store.setSessionId('new-session');
  late.resolve(response(null, 401)); await rejection;
  assert.equal(h.Api.Store.getAdminToken(), 'same-token');
  assert.equal(h.Api.Store.getSessionId(), 'new-session');
});

test('same-account login keeps session; account change, logout and base change clear it', async () => {
  const h = harness();
  await h.Api.login('alice', 'pw'); h.Api.Store.setSessionId('s');
  await h.Api.login('alice', 'pw'); assert.equal(h.Api.Store.getSessionId(), 's');
  await h.Api.login('bob', 'pw'); assert.equal(h.Api.Store.getSessionId(), null);
  h.Api.Store.setSessionId('bob-s'); h.Api.logout();
  assert.equal(h.Api.Store.getSessionId(), null);
  assert.equal(h.Api.Store.getAdminName(), null);
  await h.Api.login('bob', 'pw'); h.Api.Store.setSessionId('s');
  h.Api.Store.setApiBase('/other');
  assert.equal(h.Api.Store.getSessionId(), null); assert.equal(h.Api.isLoggedIn(), false);
});

test('DOM initializes without removed token controls; login refreshes status, health and badges', async () => {
  const h = harness(true); await settle();
  h.nodes.get('chat-input').value = 'hello';
  await h.nodes.get('btn-chat-send').emit('click');
  assert.equal(h.calls.filter(c => c.url.includes('/admin/agent/')).length, 0);
  h.nodes.get('login-user').value = 'alice'; h.nodes.get('login-pass').value = 'pw';
  await h.nodes.get('login-form').emit('submit');
  assert.match(h.nodes.get('ai-login-status').textContent, /已登录/);
  assert.equal(h.nodes.get('login-tip').classList.contains('hidden'), true);
  assert.ok(h.calls.some(c => c.url.includes('/admin/agent/history') && c.init.headers.token === 'server-token-alice'));
  assert.equal(h.nodes.has('user-token'), false);
  assert.equal(h.nodes.has('btn-demo-token'), false);
});

test('DOM drops chat response after logout and clears visible messages/session', async () => {
  const h = harness(true); await settle(); await h.Api.login('alice', 'pw');
  const late = deferred(); h.setHandler(async url => url.endsWith('/chat') ? late.promise : response([]));
  h.nodes.get('chat-input').value = 'private question';
  const sending = h.nodes.get('btn-chat-send').emit('click'); await settle();
  assert.match(h.nodes.get('chat-log').innerHTML, /private question/);
  await h.nodes.get('btn-logout').emit('click');
  late.resolve(response({ sessionId: 'old-session', reply: 'private reply' })); await sending;
  assert.doesNotMatch(h.nodes.get('chat-log').innerHTML, /private question|private reply/);
  assert.equal(h.Api.Store.getSessionId(), null);
  assert.equal(h.nodes.get('btn-chat-send').disabled, false);
});

test('DOM ignores old-session chat and history after new-session action', async () => {
  const h = harness(true); await settle(); await h.Api.login('alice', 'pw');
  const late = deferred(); h.setHandler(async url => url.endsWith('/chat') ? late.promise : response([]));
  h.nodes.get('chat-input').value = 'old question';
  const sending = h.nodes.get('btn-chat-send').emit('click'); await settle();
  await h.nodes.get('btn-chat-clear').emit('click');
  late.resolve(response({ sessionId: 'old-s', reply: 'old answer' })); await sending;
  assert.equal(h.Api.Store.getSessionId(), null);
  assert.doesNotMatch(h.nodes.get('chat-log').innerHTML, /old question|old answer/);

  h.Api.Store.setSessionId('history-s');
  const history = deferred();
  h.setHandler(async url => url.includes('/history?sessionId=history-s') ? history.promise : response([]));
  // Use the actual delegated retry event to load history.
  const historyLoad = h.document.emit('click', {
    target: { getAttribute: name => name === 'data-retry' ? 'ai-history' : null }
  });
  await settle(); await h.nodes.get('btn-chat-clear').emit('click');
  history.resolve(response([{ role: 'assistant', content: 'old history' }]));
  await historyLoad; await settle();
  assert.doesNotMatch(h.nodes.get('chat-log').innerHTML, /old history/);
});

test('DOM ignores previous-account history and analysis, diagnostics never log in', async () => {
  const h = harness(true); await settle(); await h.Api.login('alice', 'pw');
  h.Api.Store.setSessionId('alice-s');
  const oldHistory = deferred(), oldAnalysis = deferred();
  h.setHandler(async (url, init) => {
    if (url.endsWith('/login')) { return response({ id: 'bob', token: 'server-token-bob' }); }
    if (url.includes('/history?sessionId=alice-s')) { return oldHistory.promise; }
    if (url.endsWith('/analyze')) { return oldAnalysis.promise; }
    return response([]);
  });
  await h.document.emit('click', { target: { getAttribute: k => k === 'data-retry' ? 'ai-history' : null } });
  h.nodes.get('analyze-job-id').value = '42';
  await h.nodes.get('analyze-job-id-form').emit('submit');
  await h.Api.login('bob', 'pw');
  oldHistory.resolve(response([{ content: 'alice private history' }]));
  oldAnalysis.resolve(response({ reply: 'alice old analysis' })); await settle();
  assert.doesNotMatch(h.nodes.get('chat-log').innerHTML, /alice private/);
  assert.doesNotMatch(h.nodes.get('analyze-body').innerHTML, /alice old/);
  const logins = h.calls.filter(c => c.url.endsWith('/login')).length;
  await h.nodes.get('btn-diag').emit('click');
  assert.equal(h.calls.filter(c => c.url.endsWith('/login')).length, logins);
  assert.equal(h.Api.Store.getAdminToken(), 'server-token-bob');
  assert.ok(h.calls.filter(c => c.url.includes('/admin/') && !c.url.endsWith('/login')).every(c => c.init.headers.token));
});

test('a login response from before logout or API base change cannot restore credentials', async () => {
  for (const change of [api => api.logout(), api => api.Store.setApiBase('/new')]) {
    const h = harness(); const late = deferred();
    h.setHandler(async () => late.promise);
    const login = h.Api.login('alice', 'pw');
    const rejected = assert.rejects(login, e => e.kind === 'aborted');
    change(h.Api);
    late.resolve(response({ id: 'alice', token: 'old-server-token' }));
    await rejected;
    assert.equal(h.Api.isLoggedIn(), false);
    assert.equal(h.Api.Store.getSessionId(), null);
  }
});

test('DOM stores successful chat, sends admin feedback, and clears rendered content on current 401', async () => {
  const h = harness(true); await settle(); await h.Api.login('alice', 'pw');
  h.setHandler(async url => url.endsWith('/chat')
    ? response({ sessionId: 's1', requestId: 'r1', reply: 'current reply' }) : response([]));
  h.nodes.get('chat-input').value = 'hello';
  await h.nodes.get('btn-chat-send').emit('click');
  assert.equal(h.Api.Store.getSessionId(), 's1');
  assert.match(h.nodes.get('chat-log').innerHTML, /current reply/);
  assert.equal(h.nodes.get('btn-chat-send').disabled, false);
  await h.document.emit('click', { target: { getAttribute: k =>
    ({ 'data-rate': '1', 'data-idx': '1' })[k] || null } });
  const feedback = h.calls.find(c => c.url.endsWith('/feedback'));
  assert.equal(feedback.init.headers.token, 'server-token-alice');
  assert.deepEqual(JSON.parse(feedback.init.body),
    { sessionId: 's1', requestId: 'r1', rating: 1, comment: '' });
  h.setHandler(async () => response(null, 401));
  await h.nodes.get('btn-chat-send').emit('click');
  assert.equal(h.Api.isLoggedIn(), false);
  assert.equal(h.Api.Store.getSessionId(), null);
  assert.doesNotMatch(h.nodes.get('chat-log').innerHTML, /current reply|hello/);
  assert.equal(h.nodes.get('btn-chat-send').disabled, false);
  assert.equal(h.nodes.get('login-tip').classList.contains('hidden'), false);
});

test('first chat creating a session does not discard concurrent job analysis', async () => {
  const h = harness(true); await settle(); await h.Api.login('alice', 'pw');
  const analysis = deferred();
  h.setHandler(async url => {
    if (url.endsWith('/analyze')) { return analysis.promise; }
    if (url.endsWith('/chat')) { return response({ sessionId: 'new-session', reply: 'chat finished' }); }
    return response([]);
  });
  h.nodes.get('analyze-job-id').value = '42';
  await h.nodes.get('analyze-job-id-form').emit('submit');
  h.nodes.get('chat-input').value = 'hello';
  await h.nodes.get('btn-chat-send').emit('click');
  assert.equal(h.Api.Store.getSessionId(), 'new-session');
  analysis.resolve(response({ reply: 'completed job analysis' })); await settle();
  assert.match(h.nodes.get('analyze-body').innerHTML, /completed job analysis/);
  assert.match(h.nodes.get('chat-log').innerHTML, /chat finished/);
  assert.equal(h.nodes.get('btn-chat-send').disabled, false);
});

test('frontend contains no token minting, embedded secret, or manual user credentials', () => {
  assert.doesNotMatch(apiSource + appSource + html,
    /DEMO_USER_SECRET|itcast|crypto\.subtle|HS256|demoLogin|verifyUserToken|getUserToken|setUserToken|jobweb\.userToken|id="user-token"|auth:\s*'user'/);
});
