const { request } = require('../../utils/request')

Page({
  data: { job: null, id: null, isExternal: false },
  onLoad(options) {
    this.setData({ id: options.id })
    this.loadDetail()
  },
  loadDetail() {
    request({ url: '/user/job/' + this.data.id }).then(res => {
      const job = res.data
      if (job) {
        job.tags = job.tags ? job.tags.split(',') : []
        job.salaryText = (job.salaryMin || job.salaryMax) ? '￥' + job.salaryMin + '-' + job.salaryMax + '/月' : '面议'
      }
      this.setData({ job, isExternal: !!(job && job.sourceUrl) })
      wx.setNavigationBarTitle({ title: job ? job.title : '岗位详情' })
    })
  },
  onFavorite() {
    request({ url: '/user/favorite/' + this.data.id, method: 'POST' }).then(() => {
      wx.showToast({ title: '已收藏' })
    }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  onApply() {
    const job = this.data.job
    const url = job && job.sourceUrl
    if (url) {
      wx.setClipboardData({
        data: url,
        success() {
          wx.showModal({
            title: '前往官网投递',
            content: '已复制该岗位官网链接，请在浏览器中打开并自行投递',
            showCancel: false,
            confirmText: '知道了'
          })
        }
      })
      return
    }
    request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || []
      if (list.length === 0) {
        wx.showModal({
          title: '提示',
          content: '请先创建简历',
          confirmText: '去创建',
          success(r) {
            if (r.confirm) {
              wx.navigateTo({ url: '/pages/resume/resume' })
            }
          }
        })
        return
      }
      const resume = list.find(r => r.isDefault === 1) || list[0]
      request({
        url: '/user/application/submit',
        method: 'POST',
        data: { jobId: Number(this.data.id), resumeId: resume.id }
      }).then(() => {
        wx.showToast({ title: '投递成功' })
      }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
    }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  }
})
