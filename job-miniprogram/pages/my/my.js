const auth = require('../../utils/request')

Page({
  data: {
    userInfo: null, authBusy: false, serverUrl: '', stages: [], currentIndex: 1,
    functions: [{ name: '我的简历', icon: '📄' }, { name: '我的收藏', icon: '⭐' }]
  },
  onLoad() {
    this.stopAuthWatch = auth.onAuthChange(() => this.syncIdentity())
  },
  onShow() {
    this.syncIdentity()
    try { this.setData({ serverUrl: auth.getBaseUrl() }) } catch (_) { this.setData({ serverUrl: '' }) }
    this.loadTimeline()
  },
  onUnload() { if (this.stopAuthWatch) this.stopAuthWatch() },
  syncIdentity() { this.setData({ userInfo: auth.getUserInfo() }) },
  loadTimeline() {
    auth.request({ url: '/user/recruitment' }).then(res => {
      const d = res.data || {}
      this.setData({ stages: d.stages || [], currentIndex: d.currentIndex || 0 })
    }).catch(() => {})
  },
  onAuth() {
    if (this.data.authBusy) return
    if (auth.getUserInfo()) {
      auth.logout()
      this.syncIdentity()
      wx.showToast({ title: '已退出登录' })
      return
    }
    this.setData({ authBusy: true })
    auth.login().then(() => {
      this.syncIdentity()
      wx.showToast({ title: '登录成功' })
    }).catch(err => {
      if (err.kind !== 'aborted') wx.showToast({ title: err.message || '登录失败', icon: 'none' })
    }).then(() => this.setData({ authBusy: false }))
  },
  onServerInput(e) { this.setData({ serverUrl: e.detail.value }) },
  onServerSave() {
    try {
      const value = auth.setBaseUrl(this.data.serverUrl)
      this.setData({ serverUrl: value })
      this.syncIdentity()
      wx.showToast({ title: '地址已保存，请登录', icon: 'none' })
    } catch (err) { wx.showToast({ title: err.message, icon: 'none' }) }
  },
  onFunc(e) {
    const f = e.currentTarget.dataset.f
    if (f === '我的简历') wx.navigateTo({ url: '/pages/resume/resume' })
    else if (f === '我的收藏') wx.navigateTo({ url: '/pages/favorite/favorite' })
  }
})
