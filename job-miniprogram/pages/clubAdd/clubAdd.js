const { request } = require('../../utils/request')

function parseList(value) {
  if (Array.isArray(value)) return value
  if (!value) return []
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : [] } catch (e) { return [] }
}

Page({
  data: { index: -1, form: { name: '', startTime: '', endTime: '', role: '', description: '' } },
  onLoad(options) {
    const index = options && options.index !== undefined ? Number(options.index) : -1
    this.setData({ index: Number.isFinite(index) ? index : -1 })
    if (this.data.index >= 0) this.loadExisting()
  },
  onInput(e) { this.setData({ ['form.' + e.currentTarget.dataset.key]: e.detail.value }) },
  onStartTime(e) { this.setData({ 'form.startTime': e.detail.value }) },
  onEndTime(e) { this.setData({ 'form.endTime': e.detail.value }) },
  loadExisting() {
    return request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || [], resume = list.find(x => x.isDefault === 1) || list[0]
      const entries = parseList(resume && resume.clubExperience), value = entries[this.data.index]
      if (value && typeof value === 'object') this.setData({ form: Object.assign({}, this.data.form, value) })
      else if (typeof value === 'string') this.setData({ 'form.description': value })
    }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  save() {
    const f = this.data.form
    if (!f.name) { wx.showToast({ title: '请填写社团/组织名称', icon: 'none' }); return }
    return request({ url: '/user/resume/list' }).then(res => {
      const list = res.data || [], r = list.find(x => x.isDefault === 1) || list[0] || null
      const clubList = parseList(r && r.clubExperience), index = this.data.index
      if (index >= 0 && index < clubList.length && clubList[index] && typeof clubList[index] === 'object') clubList[index] = Object.assign({}, clubList[index], f)
      else if (index >= 0 && index < clubList.length) clubList[index] = Object.assign({ description: clubList[index] }, f)
      else clubList.push(Object.assign({}, f))
      const data = { clubExperience: JSON.stringify(clubList) }
      if (r) data.id = r.id
      const req = r ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
      return request(req)
    }).then(() => { wx.showToast({ title: '保存成功' }); setTimeout(() => wx.navigateBack(), 500) }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goBack() { wx.navigateBack() }
})

if (typeof module !== 'undefined') module.exports = { parseList }
