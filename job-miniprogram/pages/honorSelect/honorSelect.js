const { request } = require('../../utils/request')

Page({
  data: {
    categories: [
      { name: '艺术类竞赛', items: ['舞蹈大赛', '体育竞赛', '歌唱大赛', '微电影大赛', '配音大赛', '摄影大赛', '视频制作大赛', '金犊奖', '大广赛', '大广节'] },
      { name: '职业技能竞赛', items: ['职业技能大赛', '行业技能竞赛'] },
      { name: '奖学金/任职称号', items: ['国家奖学金', '优秀学生干部', '三好学生', '优秀毕业生'] },
      { name: '学科竞赛', items: ['数学建模竞赛', '英语竞赛', '物理竞赛'] },
      { name: '创业/商业竞赛', items: ['互联网+大赛', '挑战杯'] },
      { name: '科技类竞赛', items: ['电子设计大赛', '机器人大赛', '程序设计竞赛'] }
    ],
    activeCategory: 0,
    selected: [],
    selectedMap: {},
    keyword: ''
  },
  onLoad() {
    request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || []
      const r = list.find(x => x.isDefault === 1) || list[0] || null
      if (r && r.honors) { try { this.setSelection(JSON.parse(r.honors) || []) } catch (e) {} }
    }).catch(() => {})
  },
  onCategoryTap(e) { this.setData({ activeCategory: Number(e.currentTarget.dataset.index) }) },
  onSearch(e) { this.setData({ keyword: e.detail.value }) },
  onItemTap(e) {
    const name = e.currentTarget.dataset.name
    const selected = this.data.selected.slice()
    const i = selected.indexOf(name)
    if (i >= 0) selected.splice(i, 1)
    else {
      if (selected.length >= 30) { wx.showToast({ title: '最多选30个', icon: 'none' }); return }
      selected.push(name)
    }
    this.setSelection(selected)
  },
  setSelection(value) {
    const selected = Array.isArray(value) ? value : []
    const selectedMap = {}
    selected.forEach(name => { selectedMap[name] = true })
    this.setData({ selected, selectedMap })
  },
  save() {
    request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || []
      const r = list.find(x => x.isDefault === 1) || list[0] || null
      const data = { honors: JSON.stringify(this.data.selected) }
      if (r) data.id = r.id
      const req = r ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
      return request(req)
    }).then(() => { wx.showToast({ title: '保存成功' }); setTimeout(() => wx.navigateBack(), 500) })
      .catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goBack() { wx.navigateBack() }
})
