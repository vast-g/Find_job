const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function loadPage(requestImpl, storage = {}) {
  let page
  const calls = []
  const wx = {
    getStorageSync: key => storage[key] || '',
    setStorageSync: (key, value) => { storage[key] = value },
    removeStorageSync: key => { delete storage[key] },
    showToast: () => {},
    showLoading: () => {},
    hideLoading: () => {}
  }
  const requestModule = {
    request: options => { calls.push(options); return requestImpl(options) },
    onAuthChange: () => () => {},
    getAuthSnapshot: () => null
  }
  const source = fs.readFileSync(path.join(__dirname, '..', 'pages', 'chat', 'chat.js'), 'utf8')
  const context = {
    wx,
    Page: definition => { page = definition },
    require: id => id.includes('utils/request') ? requestModule : require(id),
    console,
    setTimeout,
    clearTimeout,
    Promise,
    JSON,
    String,
    Number,
    Boolean,
    Error
  }
  vm.runInNewContext(source, context, { filename: 'chat.js' })
  page.data = { ...page.data }
  page.setData = patch => { page.data = { ...page.data, ...patch } }
  page.onLoad()
  return { page, calls, storage }
}

async function settle() { await new Promise(resolve => setImmediate(resolve)) }

test('duplicate sends make one request and preserve its reply', async () => {
  const chat = deferred()
  const { page, calls } = loadPage(options => options.url.endsWith('/chat') ? chat.promise : Promise.resolve({ code: 1, data: [] }))
  page.onInput({ detail: { value: 'hello' } })
  page.send()
  page.send()
  assert.equal(calls.filter(c => c.url.endsWith('/chat')).length, 1)
  chat.resolve({ code: 1, data: { sessionId: 's1', requestId: 'r1', reply: 'hi' } })
  await settle()
  assert.equal(page.data.messages.at(-1).content, 'hi')
  assert.equal(page.data.sending, false)
})

test('clear suppresses a late chat response', async () => {
  const chat = deferred()
  const { page } = loadPage(options => options.url.endsWith('/chat') ? chat.promise : Promise.resolve({ code: 1, data: [] }))
  page.onInput({ detail: { value: 'old' } })
  page.send()
  page.clearChat()
  chat.resolve({ code: 1, data: { sessionId: 's1', reply: 'late' } })
  await settle()
  assert.equal(JSON.stringify(page.data.messages), '[]')
  assert.equal(page.data.sessionId, '')
})

test('late history cannot overwrite a send', async () => {
  const history = deferred()
  const { page } = loadPage(options => options.url.endsWith('/history') ? history.promise : Promise.resolve({ code: 1, data: { sessionId: 's1', reply: 'ok' } }), { agentSessionId: 's1' })
  page.onShow()
  page.onInput({ detail: { value: 'new' } })
  page.send()
  history.resolve({ code: 1, data: [{ role: 'assistant', content: 'old history' }] })
  await settle()
  assert.equal(page.data.messages.some(message => message.content === 'old history'), false)
  assert.equal(page.data.messages[0].content, 'new')
})

test('analysis failure clears pending state and exposes timeout UX', async () => {
  const { page } = loadPage(options => options.url.endsWith('/analyze')
    ? Promise.reject(Object.assign(new Error('timeout'), { timeout: true }))
    : Promise.resolve({ code: 1, data: [] }), { pendingAnalyzeJobId: 'j1' })
  page.onShow()
  await settle()
  await settle()
  assert.equal(page.data.analyzing, false)
  assert.equal(page.data.error, '请求超时，请稍后重试')
})

test('feedback uses the assistant request id and current session', async () => {
  const { page, calls } = loadPage(() => Promise.resolve({ code: 1, data: {} }))
  page.data.messages = [{ role: 'assistant', content: 'answer', requestId: 'req-7' }]
  page.data.sessionId = 'session-2'
  page.onFeedback({ currentTarget: { dataset: { index: '0', rating: '1' } } })
  await settle()
  const feedback = calls.find(c => c.url.endsWith('/feedback'))
  assert.equal(JSON.stringify(feedback.data), JSON.stringify({ sessionId: 'session-2', requestId: 'req-7', rating: 1, comment: '' }))
})
