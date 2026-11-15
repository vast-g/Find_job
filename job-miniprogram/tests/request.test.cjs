const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const root = path.join(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'utils/request.js'), 'utf8')
const settle = () => new Promise(resolve => setImmediate(resolve))
function harness(initial = {}, platform = 'devtools', env = 'develop') {
  const store = new Map(Object.entries(initial)), calls = [], logins = []
  const wx = {
    getStorageSync: key => store.get(key), setStorageSync: (key, value) => store.set(key, value),
    removeStorageSync: key => store.delete(key), getDeviceInfo: () => ({ platform }),
    getAccountInfoSync: () => ({ miniProgram: { envVersion: env } }),
    login: options => logins.push(options), request: options => calls.push(options), showToast() {}
  }
  const context = { wx, console, module: { exports: {} }, require: () => ({
    devtoolsBaseUrl: 'http://127.0.0.1:8080', deviceBaseUrl: 'http://192.168.100.3:8080', releaseBaseUrl: ''
  }) }
  vm.runInNewContext(source, context)
  return { api: context.module.exports, wx, store, calls, logins,
    reply: (call, data, statusCode = 200) => call.success({ statusCode, data: { code: 1, data } }) }
}
const identity = id => ({ id, token: 'token-' + id })
const cached = { token: 'old', userInfo: { id: 1, token: 'old' } }

test('protected requests share first login and wait for token; public browsing remains independent', async () => {
  const h = harness()
  const a = h.api.request({ url: '/user/resume/list' })
  const b = h.api.request({ url: '/user/agent/chat', method: 'POST', data: { message: 'hi' } })
  const publicCall = h.api.request({ url: '/user/job/list' })
  assert.equal(h.logins.length, 1)
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].header.authentication, '')
  h.reply(h.calls[0], []); await publicCall
  h.logins[0].success({ code: 'wx-code' }); await settle()
  assert.ok(h.calls[1].url.endsWith('/user/user/login'))
  h.reply(h.calls[1], identity(1)); await settle()
  assert.equal(h.calls.length, 4)
  assert.equal(h.calls[2].header.authentication, 'token-1')
  assert.equal(h.calls[3].timeout, 180000)
  h.reply(h.calls[2], []); h.reply(h.calls[3], { reply: 'hi' })
  await Promise.all([a, b])
})

test('simultaneous 401s share one re-login and retry each request only once', async () => {
  const h = harness(cached)
  const before = h.api.getAuthSnapshot()
  const a = h.api.request({ url: '/user/resume/list' })
  const b = h.api.request({ url: '/user/agent/history', data: { sessionId: 's' } })
  await settle()
  h.reply(h.calls[0], null, 401); h.reply(h.calls[1], null, 401); await settle()
  assert.equal(h.logins.length, 1)
  h.logins[0].success({ code: 'fresh' }); await settle()
  h.reply(h.calls[2], identity(1)); await settle()
  assert.equal(h.calls.length, 5)
  assert.equal(h.api.isAuthSnapshot(before), true)
  for (const c of h.calls.slice(3)) { assert.equal(c.header.authentication, 'token-1'); h.reply(c, []) }
  await Promise.all([a, b])
})

test('repeated 401 ends session without a retry loop and requires explicit login', async () => {
  const h = harness({ ...cached, agentSessionId: 's', pendingAnalyzeJobId: 8 })
  const pending = h.api.request({ url: '/user/resume/list' })
  const rejected = assert.rejects(pending, e => e.kind === 'unauthorized')
  await settle(); h.reply(h.calls[0], null, 401); await settle()
  h.logins[0].success({ code: 'fresh' }); await settle(); h.reply(h.calls[1], identity(1)); await settle()
  h.reply(h.calls[2], null, 401); await rejected
  assert.equal(h.store.has('token'), false); assert.equal(h.store.has('agentSessionId'), false)
  assert.equal(h.store.has('pendingAnalyzeJobId'), false)
  await assert.rejects(h.api.request({ url: '/user/resume/list' }), e => e.status === 401)
  assert.equal(h.logins.length, 1)
  const explicit = h.api.login(); h.logins[1].success({ code: 'manual' }); await settle()
  h.reply(h.calls[3], identity(1)); await explicit
})

test('logout suppresses late login response and clears identity, sessions and global state', async () => {
  const h = harness()
  let app
  vm.runInNewContext(fs.readFileSync(path.join(root, 'app.js'), 'utf8'), {
    require: () => h.api, App: definition => { app = definition }, console
  })
  app.onLaunch()
  h.logins[0].success({ code: 'c' }); await settle()
  h.api.logout(); h.reply(h.calls[0], identity(1)); await app.loginPromise
  assert.equal(h.store.has('token'), false)
  assert.equal(app.globalData.token, '')
  assert.equal(app.globalData.userInfo, null)
})

test('account switch during refresh does not replay an action under the new identity', async () => {
  const h = harness({ ...cached, agentSessionId: 'private-session' })
  const pending = h.api.request({ url: '/user/application/submit', method: 'POST', data: { jobId: 4, resumeId: 5 } })
  const rejected = assert.rejects(pending, e => e.kind === 'aborted')
  await settle(); h.reply(h.calls[0], null, 401); await settle()
  h.logins[0].success({ code: 'changed' }); await settle(); h.reply(h.calls[1], identity(2))
  await rejected
  assert.equal(h.calls.length, 2)
  assert.equal(h.store.has('agentSessionId'), false)
  assert.equal(h.api.getUserInfo().id, 2)
})

test('address changes clear auth and reject old responses; phone and release addresses are validated', async () => {
  const h = harness(cached)
  const pending = h.api.request({ url: '/user/resume/list' })
  const rejected = assert.rejects(pending, e => e.kind === 'aborted')
  await settle(); h.api.setBaseUrl('http://192.168.100.5:8080/'); h.reply(h.calls[0], [])
  await rejected
  assert.equal(h.api.getBaseUrl(), 'http://192.168.100.5:8080')
  assert.equal(h.api.getUserInfo(), null)
  const phone = harness({}, 'ios')
  assert.equal(phone.api.getBaseUrl(), 'http://192.168.100.3:8080')
  assert.throws(() => phone.api.setBaseUrl('http://localhost:8080'), /真机/)
  const release = harness({}, 'ios', 'release')
  assert.throws(() => release.api.getBaseUrl(), /服务地址/)
  assert.throws(() => release.api.setBaseUrl('http://192.168.100.3:8080'), /HTTPS/)
  release.api.setBaseUrl('https://jobs.example.com')
  assert.equal(release.api.getBaseUrl(), 'https://jobs.example.com')
})

test('network timeouts and server failures stay distinct from authentication', async () => {
  const h = harness(cached)
  const timeout = h.api.request({ url: '/user/agent/chat' })
  const rejected = assert.rejects(timeout, e => e.kind === 'timeout')
  await settle(); h.calls[0].fail({ errMsg: 'request:fail timeout' }); await rejected
  const down = h.api.request({ url: '/user/agent/chat' })
  const downRejected = assert.rejects(down, e => e.kind === 'http' && e.status === 503)
  await settle(); h.reply(h.calls[1], null, 503); await downRejected
  assert.equal(h.logins.length, 0)
})

test('real chat page accepts first automatic login and clears on logout', async () => {
  const h = harness()
  let page
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages/chat/chat.js'), 'utf8'), {
    require: () => h.api, wx: h.wx, Page: definition => { page = definition }, console
  })
  page.setData = patch => Object.assign(page.data, patch)
  page.onLoad(); page.setData({ input: 'hello' }); page.send(); page.send()
  assert.equal(h.logins.length, 1)
  h.logins[0].success({ code: 'login' }); await settle(); h.reply(h.calls[0], identity(1)); await settle()
  assert.equal(h.calls.length, 2)
  h.reply(h.calls[1], { reply: 'first answer', sessionId: 's1', requestId: 'r1' }); await settle()
  assert.equal(page.data.messages.at(-1).content, 'first answer')
  assert.equal(page.data.sending, false)
  h.api.logout()
  assert.equal(page.data.messages.length, 0); assert.equal(page.data.sessionId, '')
  page.onUnload()
})
