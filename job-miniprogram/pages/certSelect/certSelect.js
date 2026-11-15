const { request } = require('../../utils/request')

Page({
  data: {
    categories: [
      { name: '推荐证书', items: ['大学英语四级', '大学英语六级', '计算机等级考试', '机动车驾驶证', '普通话水平测试', '计算机中级专业技术资格', '华为认证', '教师资格证', '健康证', '计算机初级专业技术资格', '高等学校英语应用能力考试'] },
      { name: '英语类', items: ['专业英语四级', '专业英语八级', '雅思', '托福'] },
      { name: 'IT类', items: ['软件设计师', '网络工程师', '系统集成项目管理工程师'] },
      { name: '项目管理类', items: ['PMP', '信息系统项目管理师'] },
      { name: '会计类', items: ['初级会计职称', '中级会计职称', '注册会计师'] },
      { name: '金融类', items: ['证券从业资格', '基金从业资格', '银行从业资格'] },
      { name: '法律类', items: ['法律职业资格'] },
      { name: '教育类', items: ['教师资格证', '普通话水平测试'] }
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
      if (r && r.certificates) { try { this.setSelection(JSON.parse(r.certificates) || []) } catch (e) {} }
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
      const data = { certificates: JSON.stringify(this.data.selected) }
      if (r) data.id = r.id
      const req = r ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
      return request(req)
    }).then(() => { wx.showToast({ title: '保存成功' }); setTimeout(() => wx.navigateBack(), 500) })
      .catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goBack() { wx.navigateBack() }
})
