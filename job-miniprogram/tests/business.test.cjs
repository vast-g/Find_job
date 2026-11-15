const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

function loadPage(relative, requestImpl) {
  let page
  const navigations = []
  const requestModule = {
    request: requestImpl,
    onAuthChange: () => () => {},
    getAuthSnapshot: () => ({ accountId: 'test' })
  }
  const wx = {
    navigateTo: options => navigations.push(options),
    showToast: () => {},
    showModal: () => {},
    setNavigationBarTitle: () => {},
    navigateBack: () => {}
  }
  const source = fs.readFileSync(path.join(__dirname, '..', ...relative.split('/')), 'utf8')
  const context = {
    wx, Page: definition => { page = definition },
    require: id => id.includes('utils/request') ? requestModule : require(id),
    console, Promise, JSON, Number, String, Array, Object, Error, setTimeout, clearTimeout
  }
  vm.runInNewContext(source, context, { filename: relative })
  page.data = { ...page.data }
  page.setData = (patch, callback) => {
    const next = {}
    Object.keys(patch || {}).forEach(key => {
      if (key.startsWith('[')) return
      next[key] = patch[key]
    })
    page.data = { ...page.data, ...next }
    if (callback) callback()
  }
  return { page, navigations }
}

async function settle() { await new Promise(resolve => setImmediate(resolve)) }

const resume = { id: 9, isDefault: 1, experience: JSON.stringify([{ company: 'A', position: 'Dev', custom: 'keep' }, 'legacy work']), clubExperience: JSON.stringify([{ name: 'Club', role: 'Lead', custom: 3 }]) }

test('resume keeps canonical objects for display and routes structured edits by index', async () => {
  const saved = []
  const { page, navigations } = loadPage('pages/resume/resume.js', options => {
    if (options.url === '/user/resume/list') return Promise.resolve({ data: [resume] })
    saved.push(options)
    return Promise.resolve({ data: {} })
  })
  page.onShow()
  await settle()
  assert.equal(page.data.workList[0].custom, 'keep')
  assert.equal(page.data.workDisplayList[0], 'A · Dev')
  page.editEntry({ currentTarget: { dataset: { type: 'work', index: '0' } } })
  assert.equal(navigations[0].url, '/pages/workAdd/workAdd?index=0')
  await page.saveList('work', page.data.workList.slice(0, 1))
  assert.deepEqual(JSON.parse(saved[0].data.experience), [{ company: 'A', position: 'Dev', custom: 'keep' }])
})

for (const spec of [
  { page: 'workAdd', field: 'experience', original: { company: 'A', position: 'Dev', startTime: '2024-01', content: 'detail', custom: 'keep' }, edit: { position: 'Senior Dev' } },
  { page: 'clubAdd', field: 'clubExperience', original: { name: 'Club', role: 'Lead', startTime: '2023-03', description: 'detail', custom: 'keep' }, edit: { role: 'Chair' } }
]) {
  test(spec.page + ' edits only the selected object and preserves all other data', async () => {
    const saved = []
    const entries = [spec.original, 'legacy entry', { name: 'untouched', extra: 9 }]
    const record = { id: 9, isDefault: 1, [spec.field]: JSON.stringify(entries) }
    const { page } = loadPage('pages/' + spec.page + '/' + spec.page + '.js', options => {
      if (options.url === '/user/resume/list') return Promise.resolve({ data: [record] })
      saved.push(options); return Promise.resolve({ data: {} })
    })
    page.onLoad({ index: '0' }); await settle()
    assert.equal(page.data.form.custom, 'keep')
    page.data.form = { ...page.data.form, ...spec.edit }
    await page.save()
    const actual = JSON.parse(saved[0].data[spec.field])
    assert.deepEqual(actual[0], { ...page.data.form })
    assert.equal(actual[0].startTime, spec.original.startTime)
    assert.equal(actual[0].custom, 'keep')
    assert.deepEqual(actual.slice(1), entries.slice(1))
    assert.equal(saved[0].method, 'PUT')
  })
}

test('application computes status statistics and filters actual records', async () => {
  const records = [1, 2, 3, 4, 5, 3].map((status, i) => ({ id: i, status, jobTitle: 'job' + i }))
  const { page } = loadPage('pages/application/application.js', () => Promise.resolve({ data: records }))
  page.onLoad()
  page.onShow()
  await settle()
  assert.equal(page.data.totalCount, 6)
  assert.equal(page.data.activeCount, 4)
  assert.equal(page.data.acceptedCount, 1)
  page.onTab({ currentTarget: { dataset: { tab: '3' } } })
  assert.deepEqual(page.data.filteredList.map(item => item.status), [3, 3])
  assert.equal(page.statusText(5), '已拒绝')
})

for (const name of ['honorSelect', 'certSelect']) {
  test(name + ' prepares selection flags without WXML method calls', async () => {
    const record = { id: 9, honors: '["saved"]', certificates: '["saved"]' }
    const { page } = loadPage('pages/' + name + '/' + name + '.js', () => Promise.resolve({ data: [record] }))
    page.onLoad(); await settle()
    assert.equal(page.data.selectedMap.saved, true)
    page.onItemTap({ currentTarget: { dataset: { name: 'saved' } } })
    assert.equal(page.data.selectedMap.saved, undefined)
    page.onItemTap({ currentTarget: { dataset: { name: 'new' } } })
    assert.equal(page.data.selectedMap.new, true)
  })
}

test('application keeps errors distinct from an empty successful list', async () => {
  const { page } = loadPage('pages/application/application.js', () => Promise.reject(new Error('network down')))
  page.onLoad()
  page.onShow()
  await settle()
  assert.equal(page.data.error, 'network down')
  assert.equal(page.data.filteredList.length, 0)
})
