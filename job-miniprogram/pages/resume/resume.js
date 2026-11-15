const auth = require('../../utils/request')
const { request } = auth

const CARDS = {
  basic: { title: '基本信息', fields: [{ key: 'name', label: '姓名' }, { key: 'age', label: '年龄' }, { key: 'education', label: '学历' }] },
  summary: { title: '个人优势', fields: [{ key: 'summary', label: '个人优势', textarea: true }] },
  education: { title: '教育经历', fields: [{ key: 'school', label: '学校' }, { key: 'major', label: '专业' }, { key: 'education', label: '学历' }, { key: 'educationExperience', label: '教育经历', textarea: true }] }
}

const LISTS = {
  work: { listKey: 'workList', displayKey: 'workDisplayList', field: 'experience', title: '工作/实习经历' },
  project: { listKey: 'projectList', displayKey: 'projectDisplayList', field: 'projectExperience', title: '项目经历' },
  club: { listKey: 'clubList', displayKey: 'clubDisplayList', field: 'clubExperience', title: '社团/组织经历' },
  honor: { listKey: 'honorList', displayKey: 'honorDisplayList', field: 'honors', title: '所获荣誉' },
  cert: { listKey: 'certList', displayKey: 'certDisplayList', field: 'certificates', title: '资格证书' }
}

function displayEntry(type, entry) {
  if (typeof entry === 'string') return entry
  if (!entry || typeof entry !== 'object') return ''
  if (type === 'work') return [entry.company, entry.position].filter(Boolean).join(' · ') || entry.content || ''
  if (type === 'club') return [entry.name, entry.role].filter(Boolean).join(' · ') || entry.description || ''
  return entry.title || entry.name || entry.content || entry.description || JSON.stringify(entry)
}

Page({
  data: {
    resume: null, showEdit: false, editTitle: '', fields: [], form: {},
    jobStatusOptions: ['离校-随时到岗', '在校-月内到岗', '在校-考虑机会', '在校-暂不考虑'], jobStatusIndex: -1,
    workList: [], workDisplayList: [], projectList: [], projectDisplayList: [], clubList: [], clubDisplayList: [],
    honorList: [], honorDisplayList: [], certList: [], certDisplayList: [],
    showEntry: false, entryType: 'work', entryIndex: -1, entryText: ''
  },
  onLoad() {
    this._authOff = auth.onAuthChange(event => {
      if (['logout', 'account', 'base'].indexOf(event.type) < 0) return
      this._loadGeneration = (this._loadGeneration || 0) + 1
      const cleared = { resume: null, form: {}, showEdit: false, showEntry: false, jobStatusIndex: -1 }
      Object.keys(LISTS).forEach(type => { cleared[LISTS[type].listKey] = []; cleared[LISTS[type].displayKey] = [] })
      this.setData(cleared)
    })
  },
  onUnload() { if (this._authOff) this._authOff(); this._loadGeneration = (this._loadGeneration || 0) + 1 },
  onShow() { this.loadResume() },
  loadResume() {
    const generation = (this._loadGeneration || 0) + 1
    this._loadGeneration = generation
    return request({ url: '/user/resume/list' }).then(res => {
      if (generation !== this._loadGeneration) return
      const list = res.data || []
      const r = list.find(x => x.isDefault === 1) || list[0] || null
      const lists = {}
      Object.keys(LISTS).forEach(type => {
        const cfg = LISTS[type]
        const arr = this.parseList(r ? r[cfg.field] : null)
        lists[cfg.listKey] = arr
        lists[cfg.displayKey] = arr.map(item => displayEntry(type, item))
      })
      let jobStatusIndex = -1
      if (r && r.jobStatus) jobStatusIndex = this.data.jobStatusOptions.indexOf(r.jobStatus)
      this.setData(Object.assign({ resume: r, jobStatusIndex }, lists))
      return r
    }).catch(() => {})
  },
  parseList(value) {
    if (Array.isArray(value)) return value
    if (!value) return []
    try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : [] } catch (e) { return [] }
  },
  openEdit(e) {
    const cfg = CARDS[e.currentTarget.dataset.card]
    if (!cfg) return
    const r = this.data.resume || {}
    const form = {}
    cfg.fields.forEach(f => { form[f.key] = r[f.key] || '' })
    this.setData({ showEdit: true, editTitle: cfg.title, fields: cfg.fields, form })
  },
  onInput(e) { this.setData({ ['form.' + e.currentTarget.dataset.key]: e.detail.value }) },
  closeEdit() { this.setData({ showEdit: false }) },
  save() {
    const r = this.data.resume || {}
    const data = Object.assign({ id: r.id }, this.data.form)
    const req = r.id ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
    request(req).then(() => { this.setData({ showEdit: false }); wx.showToast({ title: '保存成功' }); this.loadResume() }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  onJobStatusChange(e) {
    const idx = Number(e.detail.value), jobStatus = this.data.jobStatusOptions[idx], r = this.data.resume || {}
    const data = { id: r.id, jobStatus }, req = r.id ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
    request(req).then(() => { this.setData({ jobStatusIndex: idx }); wx.showToast({ title: '已更新' }); this.loadResume() }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  addEntry(e) {
    const type = e.currentTarget.dataset.type
    const routes = { work: '/pages/workAdd/workAdd', club: '/pages/clubAdd/clubAdd', honor: '/pages/honorSelect/honorSelect', cert: '/pages/certSelect/certSelect' }
    if (routes[type]) { wx.navigateTo({ url: routes[type] }); return }
    this.setData({ showEntry: true, entryType: type, entryIndex: -1, entryText: '' })
  },
  editEntry(e) {
    const type = e.currentTarget.dataset.type, index = Number(e.currentTarget.dataset.index)
    if (type === 'work' || type === 'club') {
      wx.navigateTo({ url: '/pages/' + type + 'Add/' + type + 'Add?index=' + index })
      return
    }
    const cfg = LISTS[type], list = this.data[cfg.listKey] || []
    this.setData({ showEntry: true, entryType: type, entryIndex: index, entryText: displayEntry(type, list[index]) })
  },
  deleteEntry(e) {
    const type = e.currentTarget.dataset.type, cfg = LISTS[type], list = (this.data[cfg.listKey] || []).slice()
    list.splice(Number(e.currentTarget.dataset.index), 1)
    this.saveList(type, list)
  },
  onEntryInput(e) { this.setData({ entryText: e.detail.value }) },
  closeEntry() { this.setData({ showEntry: false }) },
  saveEntry() {
    const t = this.data.entryText.trim()
    if (!t) { wx.showToast({ title: '内容不能为空', icon: 'none' }); return }
    const type = this.data.entryType, cfg = LISTS[type], list = (this.data[cfg.listKey] || []).slice()
    if (this.data.entryIndex >= 0) list[this.data.entryIndex] = t
    else list.push(t)
    this.saveList(type, list); this.setData({ showEntry: false })
  },
  saveList(type, list) {
    const r = this.data.resume || {}, cfg = LISTS[type], data = { id: r.id }
    data[cfg.field] = JSON.stringify(list)
    const req = r.id ? { url: '/user/resume', method: 'PUT', data } : { url: '/user/resume', method: 'POST', data }
    return request(req).then(() => { const up = {}; up[cfg.listKey] = list; up[cfg.displayKey] = list.map(item => displayEntry(type, item)); this.setData(up); return this.loadResume() }).catch(err => wx.showToast({ title: err.message, icon: 'none' }))
  },
  goExpect() { wx.navigateTo({ url: '/pages/expect/expect' }) },
  goBack() { wx.navigateBack() }
})

if (typeof module !== 'undefined') module.exports = { displayEntry, LISTS }
