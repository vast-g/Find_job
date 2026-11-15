const config = require('../config')
const listeners = []
let revision = 0
let loginPromise = null
let automaticLogin = true

function read(key) { try { return wx.getStorageSync(key) } catch (_) { return null } }
function put(key, value) {
  if (value === null || value === undefined) wx.removeStorageSync(key)
  else wx.setStorageSync(key, value)
}
function error(kind, message, status) {
  const e = new Error(message)
  e.kind = kind
  e.status = status || 0
  return e
}
function release() {
  try { return wx.getAccountInfoSync().miniProgram.envVersion === 'release' } catch (_) { return false }
}
function devtools() {
  try {
    const info = typeof wx.getDeviceInfo === 'function' ? wx.getDeviceInfo() : wx.getSystemInfoSync()
    return info.platform === 'devtools'
  } catch (_) { return true }
}
function normalizeBaseUrl(value) {
  const url = String(value || '').trim().replace(/\/+$/, '')
  if (!/^https?:\/\/[^\s/?#]+(?:\/[^\s?#]*)?$/.test(url) || /@/.test(url)) {
    throw error('config', '请填写完整的 HTTP 或 HTTPS 服务地址')
  }
  const host = url.replace(/^https?:\/\//, '').split('/')[0].split(':')[0]
  if (!devtools() && /^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?)$/i.test(host)) {
    throw error('config', '真机请填写电脑的局域网地址，不能使用 localhost')
  }
  if (release() && (!/^https:\/\//.test(url) || /^(localhost|\d+\.\d+\.\d+\.\d+)$/.test(host))) {
    throw error('config', '正式版请配置微信允许的 HTTPS 服务域名')
  }
  return url
}
function getBaseUrl() {
  const value = read('apiBaseUrl') || (release() ? config.releaseBaseUrl
    : devtools() ? config.devtoolsBaseUrl : config.deviceBaseUrl)
  if (!value) throw error('config', '请先在个人中心设置服务地址')
  return normalizeBaseUrl(value)
}
function getUserInfo() { return read('token') ? read('userInfo') || null : null }
function notify(type, previousUser) {
  const state = { type, previousUser: previousUser || null, user: getUserInfo(), revision }
  listeners.slice().forEach(fn => { try { fn(state) } catch (e) { console.error('登录状态更新失败', e) } })
}
function onAuthChange(fn) {
  listeners.push(fn)
  return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1) }
}
function clearIdentity(type, allowAutomatic) {
  const previous = getUserInfo()
  revision++
  automaticLogin = !!allowAutomatic
  loginPromise = null
  ;['token', 'userInfo', 'agentSessionId', 'pendingAnalyzeJobId'].forEach(k => put(k, null))
  notify(type, previous)
}
function logout() { clearIdentity('logout', false) }
function setBaseUrl(value) {
  const url = normalizeBaseUrl(value)
  let previousUrl = ''
  try { previousUrl = getBaseUrl() } catch (_) {}
  if (url === previousUrl) return url
  put('apiBaseUrl', url)
  clearIdentity('base', true)
  return url
}
function getAuthSnapshot() { return { revision, base: getBaseUrl() } }
function isAuthSnapshot(snapshot) {
  try { return !!snapshot && snapshot.revision === revision && snapshot.base === getBaseUrl() } catch (_) { return false }
}
function check(snapshot) {
  if (!isAuthSnapshot(snapshot)) throw error('aborted', '登录状态已改变，请重新操作')
}
function publicPath(path) {
  return path === '/user/user/login' || path === '/user/stats' || path === '/user/recruitment'
    || path === '/user/category/list' || /^\/user\/(job|company|announcement)\//.test(path)
    || path === '/user/resume/parseFile'
}
function raw(options, token, snapshot) {
  return new Promise((resolve, reject) => {
    const path = options.url
    const timeout = options.timeout || (path.indexOf('/user/agent/') === 0 ? 180000 : 15000)
    wx.request({
      url: snapshot.base + path,
      method: options.method || 'GET',
      data: options.data || {},
      timeout,
      header: Object.assign({}, options.header, { 'content-type': 'application/json', authentication: token || '' }),
      success(res) {
        if (!isAuthSnapshot(snapshot)) { reject(error('aborted', '登录状态已改变，请重新操作')); return }
        if (res.statusCode === 401) { reject(error('unauthorized', '登录已过期，请重新登录', 401)); return }
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(error('http', '服务返回异常（' + res.statusCode + '）', res.statusCode)); return
        }
        if (res.data && res.data.code === 1) resolve(res.data)
        else reject(error('business', res.data && res.data.msg || '请求失败'))
      },
      fail(err) {
        if (!isAuthSnapshot(snapshot)) { reject(error('aborted', '登录状态已改变，请重新操作')); return }
        const timedOut = /timeout/i.test(err && err.errMsg || '')
        reject(error(timedOut ? 'timeout' : 'network', timedOut ? '请求超时，请稍后重试' : '无法连接服务，请检查网络和服务地址'))
      }
    })
  })
}
function wxCode() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) resolve(res.code)
        else reject(error('unauthorized', '未能取得微信登录凭证，请重试', 401))
      },
      fail() { reject(error('unauthorized', '微信登录失败，请重试', 401)) }
    })
  })
}
function login(options) {
  options = options || {}
  if (loginPromise) return loginPromise
  if (options.automatic && !automaticLogin) return Promise.reject(error('unauthorized', '请先在个人中心登录', 401))
  automaticLogin = true
  const cached = getUserInfo()
  if (!options.force && cached && read('token')) return Promise.resolve(Object.assign({}, cached, { token: read('token') }))
  let snapshot
  try { snapshot = getAuthSnapshot() } catch (e) { return Promise.reject(e) }
  const previous = read('userInfo') || null
  const pending = wxCode().then(code => {
    check(snapshot)
    return raw({ url: '/user/user/login', method: 'POST', data: { code } }, '', snapshot)
  }).then(response => {
    check(snapshot)
    const user = response.data
    if (!user || !user.token || user.id === undefined || user.id === null) throw error('parse', '登录返回信息不完整')
    const accountChanged = previous && String(previous.id) !== String(user.id)
    if (accountChanged) {
      revision++
      put('agentSessionId', null)
      put('pendingAnalyzeJobId', null)
    }
    put('token', user.token)
    put('userInfo', user)
    notify(accountChanged ? 'account' : previous ? 'refresh' : 'login', previous)
    return user
  }).catch(e => {
    if (isAuthSnapshot(snapshot)) clearIdentity('logout', false)
    throw e
  })
  loginPromise = pending
  pending.then(() => { if (loginPromise === pending) loginPromise = null },
    () => { if (loginPromise === pending) loginPromise = null })
  return pending
}
async function request(options) {
  options = options || {}
  const snapshot = getAuthSnapshot()
  const protectedRequest = !publicPath(options.url)
  if (!protectedRequest) return raw(options, '', snapshot)
  await login({ automatic: true })
  check(snapshot)
  const token = read('token')
  try {
    return await raw(options, token, snapshot)
  } catch (e) {
    if (e.kind !== 'unauthorized') throw e
    check(snapshot)
    if (read('token') === token) {
      // A 401 is returned before the controller executes, so one retry is safe.
      put('token', null)
      await login({ force: true, automatic: true })
    } else if (loginPromise) {
      await loginPromise
    }
    check(snapshot)
    const replacement = read('token')
    if (!replacement) throw error('unauthorized', '请先在个人中心登录', 401)
    try { return await raw(options, replacement, snapshot) }
    catch (retryError) {
      if (retryError.kind === 'unauthorized' && isAuthSnapshot(snapshot) && read('token') === replacement) logout()
      throw retryError
    }
  }
}

module.exports = { request, login, logout, getUserInfo, getBaseUrl, setBaseUrl,
  getAuthSnapshot, isAuthSnapshot, onAuthChange }
Object.defineProperty(module.exports, 'baseUrl', { enumerable: true, get: getBaseUrl })
