const { request } = require('../../utils/request')

Page({
  data: {
    categories: [],
    categoryId: null,
    education: '',
    city: '',
    keyword: '',
    jobs: [],
    loading: false,
    tab: 0,
    showFilter: false,
    educationOptions: ['不限', '大专', '本科', '硕士', '博士'],
    cityOptions: ['不限', '北京', '上海', '深圳', '广州', '杭州', '成都', '武汉', '南京', '西安', '长沙'],
    educationIndex: 0,
    cityIndex: 0,
    stats: [],
    announcements: []
  },
  onLoad() {
    this.loadCategories()
    this.loadStats()
    this.loadAnnouncements()
  },
  loadCategories() {
    request({ url: '/user/category/list' }).then(res => {
      this.setData({ categories: res.data || [] })
      this.loadJobs()
    }).catch(() => this.loadJobs())
  },
  loadJobs() {
    this.setData({ loading: true })
    const data = {}
    if (this.data.categoryId) data.categoryId = this.data.categoryId
    if (this.data.education && this.data.education !== '不限') data.education = this.data.education
    if (this.data.city && this.data.city !== '不限') data.city = this.data.city
    if (this.data.keyword) data.keyword = this.data.keyword
    request({ url: '/user/job/list', data }).then(res => {
      const jobs = (res.data || []).map(job => {
        job.tags = job.tags ? job.tags.split(',') : []
        job.salaryText = (job.salaryMin || job.salaryMax) ? Math.round(job.salaryMin / 1000) + '-' + Math.round(job.salaryMax / 1000) + 'k' : '面议'
        return job
      })
      this.setData({ jobs, loading: false })
    }).catch(err => {
      this.setData({ jobs: [], loading: false })
      wx.showToast({ title: err.message, icon: 'none' })
    })
  },
  loadStats() {
    request({ url: '/user/stats' }).then(res => {
      const d = res.data || {}
      this.setData({
        stats: [
          { num: d.companyCount || 0, label: '追踪企业' },
          { num: d.jobCount || 0, label: '校招岗位' },
          { num: d.announcementCount || 0, label: '招聘公告' }
        ]
      })
    }).catch(() => {})
  },
  loadAnnouncements() {
    request({ url: '/user/announcement/list' }).then(res => {
      this.setData({ announcements: res.data || [] })
    }).catch(() => {})
  },
  onSearchInput(e) { this.setData({ keyword: e.detail.value }) },
  onSearchConfirm() { this.loadJobs() },
  toggleFilter() { this.setData({ showFilter: !this.data.showFilter }) },
  onEducationTap(e) { this.setData({ educationIndex: Number(e.currentTarget.dataset.index) }) },
  onCityTap(e) { this.setData({ cityIndex: Number(e.currentTarget.dataset.index) }) },
  resetFilter() {
    this.setData({ educationIndex: 0, cityIndex: 0, education: '', city: '', showFilter: false })
    this.loadJobs()
  },
  applyFilter() {
    this.setData({
      education: this.data.educationOptions[this.data.educationIndex],
      city: this.data.cityOptions[this.data.cityIndex],
      showFilter: false
    })
    this.loadJobs()
  },
  onCategoryTap(e) {
    const id = Number(e.currentTarget.dataset.id)
    this.setData({ categoryId: id || null }, () => this.loadJobs())
  },
  switchTab(e) { this.setData({ tab: Number(e.currentTarget.dataset.tab) }) },
  onJobTap(e) { wx.navigateTo({ url: '/pages/jobDetail/jobDetail?id=' + e.currentTarget.dataset.id }) },
  onApply(e) { wx.navigateTo({ url: '/pages/jobDetail/jobDetail?id=' + e.currentTarget.dataset.id }) },
  onAi(e) {
    wx.setStorageSync('pendingAnalyzeJobId', e.currentTarget.dataset.id)
    wx.switchTab({ url: '/pages/chat/chat' })
  },
  onAnnoTap(e) {
    const a = this.data.announcements.find(x => String(x.id) === String(e.currentTarget.dataset.id))
    if (a) wx.showModal({ title: a.title, content: a.content || '', showCancel: false })
  }
})
