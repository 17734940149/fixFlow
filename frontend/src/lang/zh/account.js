export default {
  // 登录与个人资料设置共同使用的界面文案。
  account: {
    login: '登录', logout: '退出', loginTitle: '登录 FixFlow', loginHint: '登录后即可继续提问，当前输入已保留。',
    account: '账号', password: '密码',
    accountPlaceholder: '请输入账号', passwordPlaceholder: '请输入密码', requiredAccount: '请填写账号',
    requiredPassword: '请填写密码', invalidCredentials: '账号或密码不正确',
    settings: '用户设置', profile: '个人资料', avatar: '头像', chooseAvatar: '选择头像',
    avatarHint: 'JPG / PNG / WebP · 最大 20M', invalidAvatar: '请选择 JPG、PNG 或 WebP 图片',
    avatarTooLarge: '头像文件不能超过 20M', invalidImage: '图片无法读取，请重新选择',
    displayName: '显示名称', namePlaceholder: '请输入显示名称', requiredName: '请填写显示名称',
    identity: '账号 / 身份', admin: '管理员', user: '普通用户',
    theme: '主题配色', jade: '清透白', mono: '云灰', blue: '海盐蓝', graphite: '石墨黑',
    language: '系统语言', chinese: '简体中文', english: 'English', profileSaved: '用户资料已保存',
    // 真实身份认证使用后端账号；问答历史与个人资料仍按当前阶段在本机演示。
    realLoginHint: '请使用已创建的应用账号登录，数据库账号不能用于网页登录。',
    restoringSession: '正在确认登录状态…', loggingOut: '正在退出…',
    serverUnavailable: '后端服务暂不可用，请确认服务和数据库已启动后重试。',
    networkError: '网络连接失败或请求超时，请检查连接后重试。',
    invalidInput: '账号或密码格式不正确，请检查后重试。',
    requestFailed: '请求未能完成，请稍后重试。',
    sessionExpired: '登录已失效，请重新登录，当前问题已保留。',
    sessionCheckFailed: '暂时无法确认登录状态，请重试；确认前无法继续提问。',
    logoutFailed: '尚未确认服务端退出，请恢复连接后重试退出。',
    retryLogout: '重试退出',
    localProfileHint: '显示名称和头像当前仅用于本机演示，不会修改服务器账号资料。',
  },
}
