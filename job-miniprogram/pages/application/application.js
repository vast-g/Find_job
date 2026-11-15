const auth = require('../../utils/request')
const { request } = auth

const STATUS = { 1: '已投递', 2: '已查看', 3: '面试', 4: '已录用', 5: '已拒绝' }
const TAB_STATUS = [null, 1, 2, 3, 4, 5]

Page({
  data: {
    list: [], filteredList: [], tab: 0,
    tabs: ['全部', '已投递', '已查看', '面试', '已录用', '已拒绝'],
    totalCount: 0, activeCount: 0, acceptedCount: 0,
    loading: false, error: ''
  },
  onLoad() {
    if (typeof auth.onAuthChange === 'function') {
      this._authOff = auth.onAuthChange(() => {
        this._loadGeneration = (this._loadGeneration || 0) + 1
        this.setData({ list: [], filteredList: [], totalCount: 0, activeCount: 0, acceptedCount: 0, error: '' })
        this.load()
      })
    }
  },
  onUnload() { if (this._authOff) this._authOff() },
  onShow() { this.load() },
  load() {
    const generation = (this._loadGeneration || 0) + 1
    this._loadGeneration = generation
    this.setData({ loading: true, error: '' })
    return request({ url: '/user/application/my' }).then(res => {
      if (generation !== this._loadGeneration) return
      const list = (Array.isArray(res.data) ? res.data : []).map(item => Object.assign({}, item, { statusText: STATUS[Number(item.status)] || '未知状态' }))
      const activeCount = list.filter(item => [1, 2, 3].indexOf(Number(item.status)) >= 0).length
      const acceptedCount = list.filter(item => Number(item.status) === 4).length
      this.setData({ list, totalCount: list.length, activeCount, acceptedCount, loading: false })
      this.applyFilter()
    }).catch(err => {
      if (generation !== this._loadGeneration) return
      this.setData({ loading: false, error: err.message || '加载失败', list: [], filteredList: [], totalCount: 0, activeCount: 0, acceptedCount: 0 })
    })
  },
  applyFilter() {
    const wanted = TAB_STATUS[this.data.tab]
    const filteredList = wanted === null ? this.data.list : this.data.list.filter(item => Number(item.status) === wanted)
    this.setData({ filteredList })
  },
  onTab(e) { const tab = Number(e.currentTarget.dataset.tab); this.setData({ tab }, () => this.applyFilter()) },
  goPc() { wx.showToast({ title: '请前往 PC 端', icon: 'none' }) },
  statusText(s) { return STATUS[Number(s)] || '未知状态' }
})

if (typeof module !== 'undefined') module.exports = { STATUS, TAB_STATUS }
