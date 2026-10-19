"""区分应用存活与数据库就绪的探测接口。

作用：读取数据库及迁移检查结果，并使用状态码表达能否分配业务请求。
调用位置：第一版总路由汇入 router；部署探测或开发排查请求 /api/v1/ready。
原因：应用进程存活不代表业务所需数据库已连接、已建表，二者必须独立观察。
"""

from fastapi import APIRouter, Request, Response  # 分别提供路由注册、应用状态访问和本次响应状态码修改。

from app.db.health import database_status  # 复用数据库连通和必要业务表可查询检查，不在路由中重复实现探测语句。
from app.schemas.readiness import ReadinessResponse  # 统一返回应用就绪状态与更具体的数据库状态。

router = APIRouter(tags=["服务检查"])  # 第一版总路由汇入的就绪检查集合，与存活检查分组区分。


@router.get("/ready", response_model=ReadinessResponse)  # 注册 /api/v1/ready，用状态码和正文共同表达数据库就绪结果。
def readiness(request: Request, response: Response) -> ReadinessResponse:  # 框架注入请求与响应，使探测逻辑能访问本应用引擎并决定状态码。
    """作用：检查当前应用数据库依赖是否已达到可处理业务的状态。

    调用位置：GET /api/v1/ready 由框架调度，开发者或部署工具用于就绪探测。
    原因：数据库未配置、不可用或必要业务表缺失时，不应把该实例当作可接受业务流量。
    返回：数据库 ready 时为 200；其他状态为 503，正文保留细分数据库状态便于排查。
    边界：当前探测检查必要表及查询列，不核对迁移版本号或每项数据库约束。
    """
    status = database_status(request.app.state.db_engine)  # 由公共探测函数检查本应用引擎连通性，以及用户表和会话表的必要列能否查询。
    response.status_code = 200 if status == "ready" else 503  # 部署工具可直接用状态码判断是否将业务请求分配给此实例。
    response.headers["Cache-Control"] = "no-store"  # 就绪状态随数据库变化，不允许缓存旧结果误导探测。
    return ReadinessResponse(  # 同时保留整体就绪结论和数据库细分状态。
        status="ready" if status == "ready" else "not_ready", database=status,  # 将任何数据库未就绪结果映射为应用 not_ready，不混淆存活和就绪。
    )  # 返回模型供框架序列化，状态码沿用上面设置的本次结果。
