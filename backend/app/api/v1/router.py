"""第一版接口的统一装配入口。

作用：给健康、数据库就绪与认证接口统一增加 /api/v1 前缀。
调用位置：app.main.create_app 导入并挂载本模块的 api_router。
原因：版本路径集中管理，功能路由只关心本领域路径，后续新增接口无需修改应用组装细节。
"""

from fastapi import APIRouter  # 使用框架路由集合，将不同功能接口组合成一个可挂载入口。

from app.api.v1.routes import auth, health, readiness  # 导入各功能模块已声明的路由对象，执行导入时完成各自接口注册。

api_router = APIRouter(prefix="/api/v1")  # 应用工厂挂载的统一路由对象；版本前缀让接口演进时可保留旧入口。
api_router.include_router(health.router)  # 汇入 /health 存活检查，完整路径变为 /api/v1/health。
api_router.include_router(readiness.router)  # 汇入 /ready 数据库就绪检查，完整路径变为 /api/v1/ready。
api_router.include_router(auth.router)  # 汇入 /auth 下的登录、身份查询与退出接口。
