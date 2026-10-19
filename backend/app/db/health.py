"""供就绪接口和命令行共用的数据库检查，避免两处给出不同的可用性结论。"""
from typing import Literal  # 用限定字符串类型声明检查结果，提醒调用方处理所有状态。

from sqlalchemy import Engine, select  # Engine 提供连接入口，select 用统一表达式生成只读查询。
from sqlalchemy.exc import SQLAlchemyError  # 统一捕获驱动连接或执行查询时经 SQLAlchemy 包装的异常。

from app.models import AuthSession, User  # 导入两张必要业务表的映射，检查连接时同时核对表是否存在。

DatabaseStatus = Literal["ready", "not_configured", "unavailable"]  # 就绪路由和命令行共享的结果类型，不携带连接密码或数据库报错。


def database_status(engine: Engine | None) -> DatabaseStatus:  # 接收可选连接管理器，给调用方返回三种稳定的数据库状态。
    """作用：验证数据库能连接，并确认用户表和登录凭证表可以被查询。

    调用位置：app/api/v1/routes/readiness.py 的就绪接口、app/cli.py 的数据库
    检查与管理命令，以及相关数据库测试。
    使用原因：仅能连接不代表迁移已完成；缺少业务表时不能承接登录请求。使用同一
    函数可避免接口显示可用而命令行发现不可用。参数 engine 为 None 时不尝试连接。
    返回：ready 表示本次检查通过；not_configured 表示未配置；unavailable 表示
    连接或必要表查询失败。检查不验证全部列约束，也不能保证后续请求永远成功。
    生命周期：连接上下文结束即归还连接；这里只读，不提交或更改业务数据。
    """
    if engine is None:  # 缺少连接配置时直接区分为未配置，避免把配置问题伪装成服务器故障。
        return "not_configured"  # 让就绪接口或命令行提示先补充数据库连接配置。
    try:  # 将连接和两张表的可访问性作为一次检查，任一失败都不报告就绪。
        with engine.connect() as connection:  # 此处才向连接池借用连接，需要时建立真实网络连接，并在退出时归还。
            connection.execute(select(1))  # 执行最小查询，确认服务器可以接受并完成数据库操作。
            connection.execute(select(User).limit(0))  # 以零行查询核对用户表及所选列可访问，不读取真实用户内容。
            connection.execute(select(AuthSession).limit(0))  # 核对登录凭证表可访问，避免只检查用户表而漏掉迁移缺失。
    except SQLAlchemyError:  # 连接失败、权限不足或表缺失等数据库错误统一转成安全的检查状态。
        return "unavailable"  # 对外仅报告不可用，不泄露驱动错误、连接地址或密码。
    return "ready"  # 所有只读检查通过后返回本次就绪结论。
