"""仅判断应用是否存活的健康接口。

作用：返回当前应用名称、版本和环境，不查询数据库。
调用位置：第一版总路由汇入 router 后，前端联通检查与健康探测请求使用此接口。
原因：数据库故障与应用进程不可用是不同问题，需要保留独立存活检查入口。
"""

from typing import Annotated  # 在配置参数上声明依赖关系，同时保留 Settings 类型信息。

from fastapi import APIRouter, Depends  # 使用公共路由集合与框架依赖注入，而不手工读取全局配置。

from app.core.config import Settings, get_settings  # 从当前应用获取名称、版本和环境字段。
from app.schemas.health import HealthResponse  # 固定健康检查返回结构，便于前端和部署工具稳定读取。

router = APIRouter(tags=["健康检查"])  # 总路由挂载的健康接口集合，文档按健康检查分组展示。


@router.get("/health", response_model=HealthResponse, summary="检查服务是否可访问")  # 注册 /api/v1/health，不将数据库可用性作为此接口成功条件。
def check_health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:  # 配置由当前应用依赖注入，无需查询业务表。
    """作用：证明应用可以接收请求并返回符合约定的数据。

    调用位置：GET /api/v1/health 由框架调度，前端连通检查和测试读取返回值。
    原因：存活探测应避免依赖数据库，数据库就绪状态由 /api/v1/ready 单独表达。
    返回：固定 ok 状态和当前服务的名称、版本、环境。
    """
    return HealthResponse(  # 构造受模型约束的返回值，避免手工字典字段拼写不一致。
        status="ok",  # 能执行到此说明应用本身可以处理这次健康请求。
        service=settings.app_name,  # 告知调用方正在响应的是哪个服务。
        version=settings.app_version,  # 便于排查部署后是否仍运行旧版本。
        environment=settings.environment,  # 帮助区分开发、测试和正式环境。
    )  # 把健康数据交给框架序列化，不触发数据库连接。
