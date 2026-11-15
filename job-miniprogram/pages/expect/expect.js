const { request } = require('../../utils/request')

Page({
  data: {
    positionOptions: ['Python', 'Java', '前端开发', '后端开发', '产品经理', '运营', '测试', '数据分析', '算法工程师', '设计'],
    cityOptions: ['北京', '上海', '深圳', '广州', '杭州', '成都', '武汉', '南京', '西安', '长沙'],
    salaryOptions: ['8-12K', '12-15K', '15-20K', '20-30K', '30K以上', '面议'],
    industryOptions: ['互联网', '国企', '金融', '教育', '医疗', '制造业', '能源', '咨询'],
    expectPosition: '',
    expectCity: '',
    expectSalary: '',
    expectIndustry: ''
  },
  onLoad() {
    request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || []
      const r = list.find(x => x.isDefault === 1) || list[0] || null
      if (r) {
        this.setData({
          expectPosition: r.expectPosition || '',
          expectCity: r.expectCity || '',
          expectSalary: r.expectSalary || '',
          expectIndustry: r.expectIndustry || ''
        })
      }
    }).catch(() => {})
  },
  onPositionChange(e) { this.setData({ expectPosition: this.data.positionOptions[e.detail.value] }) },
  onCityChange(e) { this.setData({ expectCity: this.data.cityOptions[e.detail.value] }) },
  onSalaryChange(e) { this.setData({ expectSalary: this.data.salaryOptions[e.detail.value] }) },
  onIndustryChange(e) { this.setData({ expectIndustry: this.data.industryOptions[e.detail.value] }) },
  save() {
    const { expectPosition, expectCity, expectSalary, expectIndustry } = this.data
    if (!expectPosition || !expectCity || !expectSalary) {
      wx.showToast({ title: '请完善信息', icon: 'none' })
      return
    }
    request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || []
      const r = list.find(x => x.isDefault === 1) || list[0] || null
      const data = { expectPosition, expectCity, expectSalary, expectIndustry }
      const req = (r && r.id)
        ? { url: '/user/resume', method: 'PUT', data: Object.assign({ id: r.id }, data) }
        : { url: '/user/resume', method: 'POST', data }
      return request(req)
    }).then(() => {
      wx.showToast({ title: '保存成功' })
      setTimeout(() => wx.navigateBack(), 500)
    }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goBack() { wx.navigateBack() }
})
