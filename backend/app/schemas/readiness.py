"""业务依赖就绪检查的响应模型。

作用：同时表达整体就绪结果与数据库更具体的检查状态。
调用位置：app.api.v1.routes.readiness 构造模型并将它声明为接口响应结构。
原因：部署工具可按整体状态决策，开发者仍能区分数据库未配置与连接或业务表不可用。
"""

from typing import Literal  # 限制整体就绪状态，避免出现部署工具无法识别的自由文本。

from pydantic import BaseModel  # 提供响应数据校验和接口描述生成能力。

from app.db.health import DatabaseStatus  # 复用数据库探测定义的状态类型，避免探测与响应模型状态集合不一致。


class ReadinessResponse(BaseModel):  # 就绪路由返回的结构化结果，不与仅表明存活的 HealthResponse 混用。
    """作用：约束数据库依赖就绪检查的接口返回结构。

    调用位置：readiness 路由构造本类，并结合 ready 或 not_ready 设置 200 或 503 状态码。
    原因：应用存活但数据库不可用时不能正常处理业务，需要让部署工具作出不同决策。
    边界：当前只检查数据库连接及必要表列可查询，不核对迁移版本号；未来增加依赖时还需扩展探测。
    """

    status: Literal["ready", "not_ready"]  # 给部署工具提供整体结论，任何数据库未就绪状态都对应 not_ready。
    database: DatabaseStatus  # 保留未配置或不可用等公共状态；连接故障和表缺失目前都归为不可用。
