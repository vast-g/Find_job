const { request, onAuthChange } = require('../../utils/request')

function messages(list) {
  return (Array.isArray(list) ? list : []).map(m => ({
    role: m.role === 'user' ? 'user' : 'assistant', content: m.content, requestId: m.requestId
  }))
}
function errorText(err, fallback) {
  if (err && (err.kind === 'unauthorized' || err.status === 401)) return '请在个人中心重新登录后再试'
  if (err && err.kind === 'timeout' || /timeout|超时/i.test(err && err.message || '')) return '请求超时，请稍后重试'
  return err && err.message || fallback
}

Page({
  data: {
    messages: [], input: '', sessionId: '', sending: false, analyzing: false, error: '',
    quickQuestions: ['如何准备面试？', '央国企面试有哪些常见问题？', '简历中的项目经历怎么写？']
  },
  onLoad() {
    this._generation = 0
    this._historyKey = ''
    this._historyLoading = false
    this._analyzePromise = null
    this._authUnsubscribe = onAuthChange(event => {
      // Initial login and same-account token refresh may complete the current request.
      if (event.type === 'logout' || event.type === 'account' || event.type === 'base') {
        this.clearChat()
        if (event.type === 'logout') this.setData({ error: '请在个人中心登录后使用智能问答' })
      }
    })
    const sessionId = wx.getStorageSync('agentSessionId') || ''
    if (sessionId) {
      this.setData({ sessionId })
      this._loadHistory(sessionId, this._generation)
    }
  },
  onShow() {
    if (this.data.sending || this.data.analyzing || this._analyzePromise) return
    const jobId = wx.getStorageSync('pendingAnalyzeJobId')
    if (!jobId) {
      if (this.data.sessionId && !this.data.messages.length) this._loadHistory(this.data.sessionId, this._generation)
      return
    }
    wx.removeStorageSync('pendingAnalyzeJobId')
    const generation = ++this._generation
    this._historyKey = ''
    this._historyLoading = false
    this.setData({ messages: [], error: '', analyzing: true })
    this._analyzePromise = request({ url: '/user/agent/analyze', method: 'POST', data: { jobId } }).then(res => {
      if (generation !== this._generation) return
      const result = res.data || {}
      if (!result.sessionId) throw new Error('分析结果为空')
      wx.setStorageSync('agentSessionId', result.sessionId)
      this.setData({ sessionId: result.sessionId })
      if (result.reply) {
        this.setData({ messages: [{ role: 'assistant', content: result.reply }] })
      } else return this._loadHistory(result.sessionId, generation)
    }).catch(err => {
      if (generation === this._generation) this.setData({ error: errorText(err, '分析失败') })
    }).then(() => {
      if (generation !== this._generation) return
      this._analyzePromise = null
      this.setData({ analyzing: false })
      this.onShow()
    })
  },
  _loadHistory(sessionId, generation) {
    const key = sessionId + ':' + generation
    if (this._historyLoading || this._historyKey === key) return Promise.resolve()
    this._historyLoading = true
    this._historyKey = key
    return request({ url: '/user/agent/history', data: { sessionId } }).then(res => {
      if (generation !== this._generation || this.data.sending || sessionId !== this.data.sessionId) return
      this.setData({ messages: messages(res.data) })
    }).catch(err => {
      if (generation === this._generation) {
        this._historyKey = ''
        this.setData({ error: errorText(err, '历史记录加载失败') })
      }
    }).then(() => {
      if (generation === this._generation || this._historyKey === key) this._historyLoading = false
    })
  },
  onInput(e) { this.setData({ input: e.detail.value }) },
  fillQuestion(e) { this.setData({ input: e.currentTarget.dataset.q }) },
  clearChat() {
    this._generation += 1
    this._historyKey = ''
    this._historyLoading = false
    this._analyzePromise = null
    this.setData({ messages: [], sessionId: '', input: '', sending: false, analyzing: false, error: '' })
    wx.removeStorageSync('agentSessionId')
  },
  send() {
    const text = String(this.data.input || '').trim()
    if (!text || this.data.sending || this.data.analyzing) return
    const generation = ++this._generation
    const sessionId = this.data.sessionId
    this.setData({ messages: this.data.messages.concat([{ role: 'user', content: text }]), input: '', sending: true, error: '' })
    request({ url: '/user/agent/chat', method: 'POST', data: { sessionId, message: text } }).then(res => {
      if (generation !== this._generation) return
      const result = res.data || {}
      const next = result.sessionId || sessionId
      if (next) wx.setStorageSync('agentSessionId', next)
      this.setData({ sessionId: next, messages: this.data.messages.concat([
        { role: 'assistant', content: result.reply || '（无回复）', requestId: result.requestId }
      ]) })
    }).catch(err => {
      if (generation === this._generation) this.setData({ error: errorText(err, 'AI服务暂不可用，请稍后重试') })
    }).then(() => {
      if (generation !== this._generation) return
      this.setData({ sending: false })
      this.onShow()
    })
  },
  onFeedback(e) {
    const msg = this.data.messages[Number(e.currentTarget.dataset.index)]
    if (!msg || msg.role !== 'assistant') return
    const generation = this._generation
    request({ url: '/user/agent/feedback', method: 'POST', data: {
      sessionId: this.data.sessionId, requestId: msg.requestId, rating: Number(e.currentTarget.dataset.rating), comment: ''
    } }).then(() => {
      if (generation === this._generation) wx.showToast({ title: Number(e.currentTarget.dataset.rating) === 1 ? '已点赞' : '已反馈', icon: 'none' })
    }).catch(err => {
      if (generation === this._generation) this.setData({ error: errorText(err, '反馈失败') })
    })
  },
  onUnload() {
    if (this._authUnsubscribe) this._authUnsubscribe()
    this._generation += 1
  }
})
