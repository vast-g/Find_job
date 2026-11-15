const { request } = require('../../utils/request')

Page({
  data: { list: [] },
  onShow() { this.load() },
  load() {
    request({ url: '/user/favorite/list' }).then(res => {
      this.setData({ list: res.data || [] })
    }).catch(() => {})
  },
  onJobTap(e) {
    wx.navigateTo({ url: '/pages/jobDetail/jobDetail?id=' + e.currentTarget.dataset.id })
  }
})
