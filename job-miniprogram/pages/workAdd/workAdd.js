const { request } = require('../../utils/request')

function parseList(value) {
  if (Array.isArray(value)) return value
  if (!value) return []
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : [] } catch (e) { return [] }
}

Page({
  data: {
    index: -1,
    industryOptions: ['互联网', '国企', '金融', '教育', '医疗', '制造业', '能源', '咨询'],
    form: { company: '', industry: '', startTime: '', endTime: '', position: '', content: '', achievement: '', department: '' }
  },
  onLoad(options) {
    const index = options && options.index !== undefined ? Number(options.index) : -1
    this.setData({ index: Number.isFinite(index) ? index : -1 })
    if (this.data.index >= 0) this.loadExisting()
  },
  onInput(e) { this.setData({ ['form.' + e.currentTarget.dataset.key]: e.detail.value }) },
  onIndustryChange(e) { this.setData({ 'form.industry': this.data.industryOptions[e.detail.value] }) },
  onStartTime(e) { this.setData({ 'form.startTime': e.detail.value }) },
  onEndTime(e) { this.setData({ 'form.endTime': e.detail.value }) },
  loadExisting() {
    return request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || [], resume = list.find(x => x.isDefault === 1) || list[0]
      const entries = parseList(resume && resume.experience), value = entries[this.data.index]
      if (value && typeof value === 'object') this.setData({ form: Object.assign({}, this.data.form, value) })
      else if (typeof value === 'string') this.setData({ 'form.content': value })
      this._resume = resume
      this._entries = entries
    }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  save() {
    const f = this.data.form
    if (!f.company || !f.position) { wx.showToast({ title: '请填写公司和职位', icon: 'none' }); return }
    return request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || [], r = list.find(x => x.isDefault === 1) || list[0] || null
      const workList = parseList(r && r.experience)
      const index = this.data.index
      if (index >= 0 && index < workList.length && workList[index] && typeof workList[index] === 'object') workList[index] = Object.assign({}, workList[index], f)
      else if (index >= 0 && index < workList.length) workList[index] = Object.assign({ content: workList[index] }, f)
      else workList.push(Object.assign({}, f))
      const data = { experience: JSON.stringify(workList) }
      if (r) data.id = r.id
      const req = r ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
      return request(req)
    }).then(() => { wx.showToast({ title: '保存成功' }); setTimeout(() => wx.navigateBack(), 500) }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goBack() { wx.navigateBack() }
})

if (typeof module !== 'undefined') module.exports = { parseList }
