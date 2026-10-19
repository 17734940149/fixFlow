"""数据库连接管理与每个请求的工作会话。

这里的 Session 是一次数据库操作的工作上下文，负责跟踪对象和事务；它不是
AuthSession 所表示的用户登录凭证。连接管理器被多个请求共享，工作会话不共享。
"""
from collections.abc import Iterator  # 标注 yield 依赖的生成器类型，让框架管理资源申请与释放。
from sqlite3 import Connection as SQLiteConnection  # 为隔离测试专用的 SQLite 连接事件提供准确类型。
from typing import Any  # 连接池事件的记录对象和引擎参数具有不同类型，用 Any 接纳库定义的通用接口。

from fastapi import HTTPException, Request, status  # 请求提供应用共享状态，标准异常与状态码表达数据库未配置。
from sqlalchemy import Engine, create_engine, event  # Engine 管理连接池，工厂创建它，事件钩子为测试连接启用约束。
from sqlalchemy.engine import make_url  # 将保密连接字符串解析为结构化地址，可靠识别驱动和数据库名称。
from sqlalchemy.orm import Session  # 引入数据库工作会话，为单次请求追踪查询对象并管理事务。
from sqlalchemy.pool import StaticPool  # 内存测试库需要复用一个连接，防止切换连接后表结构消失。

from app.core.config import Settings  # 连接地址、运行环境及连接池上限统一由已有配置模块提供。


def _enable_sqlite_foreign_keys(  # 注册为测试引擎的新连接回调，在任何业务查询前启用外键检查。
    connection: SQLiteConnection, connection_record: Any  # 第一个参数是底层连接；第二个由连接池事件传入，本函数无需读取。
) -> None:  # 事件回调只设置连接属性，不向调用方返回业务数据。
    """作用：为每个新建的 SQLite 测试连接开启外键约束检查。

    调用位置：create_database_engine 的 SQLite 分支通过 event.listen 注册，
    SQLAlchemy 真正创建底层连接时调用；生产 PostgreSQL 不走此回调。
    使用原因：SQLite 默认不检查外键，若不启用，测试可能接受生产数据库会拒绝的
    无效 user_id。connection 是底层连接，connection_record 为事件协议必需参数。
    生命周期：只暂时创建游标；无论设置是否成功都关闭游标，连接仍由连接池管理。
    """
    cursor = connection.cursor()  # 向底层测试连接申请执行设置语句的游标，不创建第二个数据库连接。
    try:  # 把设置和清理分开，保证执行失败也不会遗留游标资源。
        cursor.execute("PRAGMA foreign_keys=ON")  # SQLite 专用连接设置，使测试验证外键和级联删除规则。
    finally:  # 清理步骤必定执行，不把设置异常吞掉。
        cursor.close()  # 关闭临时游标；不关闭由连接池持有的底层连接。


def create_database_engine(settings: Settings) -> Engine | None:  # 根据统一配置创建连接管理器，供服务、命令行和迁移复用。
    """作用：创建数据库引擎及连接池配置，不执行查询、不自动建表。

    调用位置：app/main.py 创建应用时、app/cli.py 的管理命令、migrations/env.py
    的在线迁移，以及隔离数据库测试。
    使用原因：统一驱动、超时、连接池及敏感参数保护，避免各调用方使用不同连接策略。
    参数 settings 包含保密连接地址和容量设置；返回 Engine 或未配置时的 None。
    创建 Engine 不立即建立 PostgreSQL 网络连接，首次借连接执行操作时才实际连接。
    SQLite 仅供显式 test 环境隔离验证；生产和开发不会缺配置后静默换成 SQLite。
    生命周期：服务停机、命令行 finally 或迁移 finally 负责 dispose 释放连接池。
    不支持的驱动或环境配置会抛 ValueError，要求调用方修正配置后再启动。
    """
    if settings.database_url is None:  # 缺配置时保留无数据库的存活检查能力，而不是偷偷创建其他数据库。
        return None  # 让就绪检查和 get_db 明确报告未配置。
    database_url = make_url(settings.database_url.get_secret_value())  # 在真正交给连接库时取出保密字符串并解析，避免手工拆分密码。
    if database_url.drivername == "sqlite":  # 只有明确指定 SQLite 的隔离测试才进入轻量测试分支。
        if settings.environment != "test":  # 防止开发或生产误把内存测试库当成持久数据库。
            raise ValueError("SQLite 仅允许用于隔离测试，请配置 PostgreSQL。")  # 拒绝不合规配置，避免表面运行但数据丢失。
        options: dict[str, Any] = {  # 当前测试引擎的局部参数对象，与生产连接池设置分开。
            "connect_args": {"check_same_thread": False},  # 允许测试客户端使用不同工作线程访问测试连接。
            "pool_pre_ping": True,  # 借用已有连接前探测可用性，减少失效连接导致的误报。
            "hide_parameters": True,  # 异常和语句日志隐藏绑定参数，避免测试形成泄露密码的坏示例。
        }  # 完成测试引擎的公共选项配置。
        if database_url.database in (None, "", ":memory:"):  # 内存库只存在于当前连接中，必须特殊处理连接复用。
            # 内存数据库随连接销毁，测试需要共享同一个连接才能保留迁移后的表。
            options["poolclass"] = StaticPool  # 整个测试引擎复用同一底层连接，保持内存表和数据可见。
        engine = create_engine(database_url, **options)  # 按测试地址和选项建立连接管理器，此行不会执行建表。
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)  # 在每个新底层连接建立时启用 SQLite 外键约束。
        return engine  # 返回测试连接管理器，让测试依旧通过相同的 Session 和模型访问。
    if database_url.drivername != "postgresql+psycopg":  # 正式运行只支持 PostgreSQL 与既定 psycopg 驱动组合。
        raise ValueError("请使用 PostgreSQL 的 psycopg 数据库驱动。")  # 提前指出不支持的驱动，避免运行时出现不可预期差异。
    return create_engine(  # 创建生产或开发引擎，具体连接由连接池在需要时建立并复用。
        database_url,  # 使用已解析的保密连接地址，包含数据库账号、目标服务器与库名。
        pool_pre_ping=True,  # 每次取复用连接前检测存活，数据库重启后可淘汰失效连接。
        pool_size=settings.database_pool_size,  # 限制连接池常驻连接容量，避免每个请求无限占用数据库资源。
        max_overflow=settings.database_max_overflow,  # 允许有限的临时额外连接，应对短时并发峰值。
        pool_timeout=settings.database_pool_timeout_seconds,  # 连接池用满时只等待指定时长，避免请求无限阻塞。
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},  # 限制新建网络连接的等待时长，与借池超时分别控制。
        hide_parameters=True,  # 隐藏数据库语句绑定参数，减少密码哈希、令牌哈希等进入异常日志的风险。
    )  # 将引擎交给调用方管理生命周期；不会在这里自动迁移表结构。


def get_db(request: Request) -> Iterator[Session]:  # FastAPI 的 yield 依赖，为一次请求提供独立数据库工作会话。
    """作用：从当前应用取得共享引擎，为请求提供 Session，并负责异常回滚和最终关闭。

    调用位置：app/api/v1/routes/auth.py 的登录和退出接口，以及
    app/api/dependencies.py 的登录凭证校验，通过 Depends(get_db) 请求本依赖。
    使用原因：数据库工作会话不能跨请求共享，否则事务和对象状态会相互影响；同一个
    请求内默认依赖缓存可复用本次 Session。这里的 Session 与用户登录 AuthSession 不同。
    参数 request 提供应用状态；yield 交付工作会话，不等于返回登录凭证。
    创建 Session 本身不立即连接 PostgreSQL；首次数据库操作需要时向引擎借连接。
    事务成功与否由业务显式 commit 决定，本依赖不自动提交；commit 会结束当前事务，
    通常即归还所借连接。发生异常时 rollback 清理未提交事务，再保留原异常向外传播。
    当前 Depends 默认采用 request 作用域，yield 后的最终 close 通常在响应发送后执行；
    close 释放剩余事务资源，不能将已 commit 的失败计数或登录凭证撤回。
    """
    engine: Engine | None = getattr(request.app.state, "db_engine", None)  # 读取 main.py 存入应用状态的引擎，缺失时安全视为未配置。
    if engine is None:  # 无可用连接管理器时直接拒绝依赖数据库的请求。
        raise HTTPException(  # 交给全局异常处理器输出统一错误结构，路由业务不会继续执行。
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,  # 服务暂不具备数据库能力，返回标准不可用状态。
            detail={  # 提供稳定错误代码和易懂消息，不把连接地址或密码暴露给客户端。
                "code": "DATABASE_NOT_CONFIGURED",  # 前端可用稳定代码识别配置缺失，不依赖中文文案匹配。
                "message": "数据库尚未配置，请先配置数据库连接。",  # 提示运维或开发先完成配置。
            },  # 结束业务错误说明对象。
        )  # 抛出异常后依赖解析中断，不创建数据库工作会话。
    session = Session(engine, expire_on_commit=False)  # 建立请求专属工作上下文，提交后保留已加载属性供响应序列化读取。
    try:  # yield 之前申请资源，之后捕捉路由或后续依赖抛回的异常并执行清理。
        yield session  # 将同一次请求的数据库工作会话交给路由或鉴权依赖使用。
    except Exception:  # 下游查询、验证或业务操作出错时处理尚未提交的事务。
        session.rollback()  # 撤销本会话未提交的修改并结束失败事务，已提交内容不受此操作影响。
        raise  # 继续传播原异常，由应用既有的错误处理规则决定响应。
    finally:  # 无论请求正常返回还是异常退出，都保证执行会话资源清理。
        session.close()  # 关闭工作上下文并释放仍占用的连接，不关闭整个应用共享连接池。
