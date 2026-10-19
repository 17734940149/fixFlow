"""应用存活检查的公开响应模型。

作用：限制健康接口返回的状态、服务名称、版本和运行环境。
调用位置：app.api.v1.routes.health 的返回值与 response_model 使用 HealthResponse。
原因：固定输出契约让前端联通检查与部署探测不依赖随意变动的字典结构。
"""

from typing import Literal  # 以字面量限制健康状态和环境名称，避免返回不受支持的拼写。

from pydantic import BaseModel  # 提供有类型约束、可生成接口文档且能序列化的响应对象。


class HealthResponse(BaseModel):  # 健康路由构造并返回本模型，框架按声明字段生成响应和文档。
    """作用：约束应用存活检查成功时的响应结构。

    调用位置：check_health 返回本模型；前端健康检查和后端测试读取其字段。
    原因：健康接口只表示应用能处理请求，不应加入数据库或具体业务资料造成依赖耦合。
    返回约定：status 仅为 ok，其他字段标识当前响应服务的名称、版本和环境。
    """

    status: Literal["ok"]  # 固定成功状态，用于简单存活判断；不代表数据库一定可用。
    service: str  # 标识当前服务，便于排查是否请求到了错误的后端地址。
    version: str  # 显示运行版本，便于核对部署内容。
    environment: Literal["development", "test", "production"]  # 明确当前环境，帮助排查开发与正式服务混用。
