const auth = require('./utils/request')

App({
  globalData: { userInfo: null, token: '' },
  onLaunch() {
    const sync = () => {
      const user = auth.getUserInfo()
      this.globalData.userInfo = user
      this.globalData.token = user && user.token || ''
    }
    sync()
    auth.onAuthChange(sync)
    // 所有受保护的请求都复用这次登录，页面不再抢跑。
    this.loginPromise = auth.login().catch(() => {
      console.log('微信登录暂未成功，可浏览公开岗位；请在个人中心重试登录')
      return null
    })
  }
})
