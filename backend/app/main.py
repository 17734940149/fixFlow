"""应用组装与请求异常处理。

作用：把配置、数据库连接池、跨域规则、异常处理和业务路由组装成可启动的应用。
调用位置：开发启动命令导入本模块的 app；测试通过 create_app 建立互不干扰的应用。
原因：集中配置应用边界，避免接口各自创建数据库连接池或返回不一致的错误结构。
"""

from collections.abc import AsyncIterator  # 为生命周期的异步生成器标注产出类型，帮助阅读和类型检查。
from contextlib import asynccontextmanager  # 把带 yield 的异步函数转换成应用可使用的启动与关闭上下文。

from fastapi import FastAPI, Request, Response  # 分别表示应用、进入的请求和返回的响应，用于组装与异常处理。
from fastapi.exception_handlers import http_exception_handler  # 复用框架默认异常格式，保留状态码和认证响应头约定。
from fastapi.exceptions import RequestValidationError  # 捕获框架对请求参数或请求体校验失败产生的异常。
from fastapi.middleware.cors import CORSMiddleware  # 为前端与后端端口不同的开发方式提供受配置约束的跨域响应。
from fastapi.responses import JSONResponse  # 构造有明确状态码、响应头和结构化错误内容的响应。
from sqlalchemy.exc import SQLAlchemyError  # 统一识别数据库工具产生的异常，避免泄露驱动内部错误。
from starlette.concurrency import run_in_threadpool  # 把同步的连接池释放操作交给线程执行，避免阻塞异步关闭流程。
from starlette.exceptions import HTTPException as StarletteHTTPException  # 捕获框架和业务主动抛出的请求错误，并沿用框架的异常类型。

from app.api.v1.router import api_router  # 引入已汇总的第一版接口，应用只需挂载一次统一入口。
from app.core.config import Settings  # 读取经校验的应用配置，也允许测试显式传入隔离配置。
from app.db.session import create_database_engine  # 复用数据库引擎工厂，让连接参数集中维护。


@asynccontextmanager  # 将下面的 yield 前后阶段交给 FastAPI 管理应用生命周期。
async def lifespan(application: FastAPI) -> AsyncIterator[None]:  # 接收正在运行的应用，关闭时使用它保存的数据库引擎。
    """作用：在应用关闭阶段释放连接池及其中的空闲数据库连接。

    调用位置：create_app 把本函数传给 FastAPI 的 lifespan 参数；框架负责进入和退出。
    原因：开发自动重启和多应用测试都会反复创建引擎，明确释放可避免连接遗留。
    参数：application 是本次运行的应用；它的 state.db_engine 可能为空。
    产出：yield 不携带业务数据，只把控制权交回框架供应用处理请求。
    """
    try:  # 把应用运行阶段置于保护结构中，保证正常关闭或异常退出时都进入清理阶段。
        yield  # 暂停生命周期函数，让框架在此期间持续处理请求。
    finally:  # 框架结束应用生命周期后执行清理，不依赖某个接口主动调用。
        engine = application.state.db_engine  # 取得本应用独享的连接池管理对象，避免误关其他测试应用的引擎。
        if engine is not None:  # 未配置数据库时没有引擎，无需执行释放操作。
            await run_in_threadpool(engine.dispose)  # 在线程中释放同步引擎管理的连接，并等待清理结束。


def database_error_response(request: Request, error: SQLAlchemyError) -> JSONResponse:  # 保留框架异常处理器签名，接收请求和数据库异常。
    """作用：把数据库工具异常转换成不包含内部细节的服务暂不可用响应。

    调用位置：create_app 注册后，框架在请求执行中出现 SQLAlchemyError 时调用。
    原因：直接返回驱动错误可能暴露连接地址、密码或语句，统一错误也方便前端提示重试。
    参数：request 与 error 由框架传入；本实现刻意不把 error 文本写入响应。
    返回：状态码 503 的 JSONResponse，且禁止缓存这次临时故障结果。
    """
    return JSONResponse(  # 显式构造错误响应，避免数据库异常进入默认的内部错误页面。
        status_code=503,  # 说明服务当前无法完成请求，客户端可以稍后再试。
        headers={"Cache-Control": "no-store"},  # 不让浏览器或中间代理保存这次数据库故障响应。
        content={"detail": {  # 沿用 detail 外层结构，便于接口调用方统一读取错误。
            "code": "DATABASE_UNAVAILABLE",  # 给前端提供稳定错误标识，避免按中文提示判断分支。
            "message": "数据库暂不可用，请检查数据库连接及迁移是否完成。",  # 仅提供可操作的排查方向，不回显数据库驱动细节。
        }},  # 完成数据库错误内容，让序列化器得到完整的 detail 对象。
    )  # 返回包含指定状态码、响应头和错误内容的数据库故障响应。


def validation_error_response(request: Request, error: RequestValidationError) -> JSONResponse:  # 接收框架在请求校验阶段收集的异常。
    """作用：返回请求校验失败的位置与原因，并移除可能包含密码的原始输入。

    调用位置：create_app 注册为 RequestValidationError 处理器，由框架调度。
    原因：密码错误或类型错误时，默认校验详情可能包含用户提交值，不能直接回显。
    返回：状态码 422 的结构化校验错误；每项只保留错误类型、字段位置和提示。
    """
    errors = [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()]  # 只提取客户端排查必要字段，丢弃原始输入及附加上下文。
    return JSONResponse(  # 手动返回过滤后的错误，而不是使用包含完整输入的默认内容。
        status_code=422, content={"detail": errors}, headers={"Cache-Control": "no-store"},  # 保持请求不符合约定的状态码，并禁止缓存可能涉及个人字段的校验提示。
    )  # 完成校验错误响应，交由框架发送给请求方。


async def authentication_error_response(request: Request, error: StarletteHTTPException) -> Response:  # 同时处理业务和框架抛出的请求异常。
    """作用：沿用框架请求错误响应，并为认证接口错误补充禁止缓存的响应头。

    调用位置：create_app 注册后，框架处理 StarletteHTTPException 时调用。
    原因：认证依赖可能在路由函数执行前失败，不能只依赖正常接口返回时设置缓存头。
    返回：框架生成的 Response；认证路径额外带 Cache-Control: no-store。
    """
    response = await http_exception_handler(request, error)  # 复用框架处理器，保留原状态码、detail 和异常自带响应头。
    if request.url.path.startswith("/api/v1/auth/"):  # 只为当前认证接口前缀补充规则，避免修改其他接口的缓存语义。
        response.headers["Cache-Control"] = "no-store"  # 即使认证依赖失败，也不缓存涉及身份状态的响应。
    return response  # 把保留框架约定并补充安全响应头的错误返回给客户端。


def create_app(settings: Settings | None = None) -> FastAPI:  # 应用工厂允许测试注入配置，生产启动则自动读取环境。
    """作用：创建并完整配置一个 FastAPI 应用实例。

    调用位置：模块末尾创建启动入口 app；测试也直接调用以构造独立应用。
    原因：把组装过程收敛为工厂，可隔离测试配置、数据库和状态，避免修改全局环境。
    参数：settings 可显式传入；为 None 时读取环境变量和后端目录中的 .env。
    返回：已挂载接口、跨域中间件、异常处理器和生命周期函数的应用。
    """
    settings = settings if settings is not None else Settings()  # 优先使用调用方配置，避免测试意外连接开发数据库。
    application = FastAPI(  # 创建本次应用实例，并在构造阶段声明接口文档与生命周期规则。
        title=settings.app_name,  # 接口文档显示配置中的服务名称，避免页面和实际服务身份不同。
        version=settings.app_version,  # 将当前版本写入接口描述，方便调用方核对运行版本。
        description="FixFlow：健康检查、数据库就绪检查与服务端身份认证。",  # 在接口文档中明确当前已实现的后端能力。
        lifespan=lifespan,  # 让框架负责关闭时的数据库连接池清理。
        docs_url="/docs" if settings.docs_enabled else None,  # 根据配置决定是否开放交互式接口文档。
        redoc_url="/redoc" if settings.docs_enabled else None,  # 同步控制另一种接口文档页面，避免关闭不完整。
        openapi_url="/openapi.json" if settings.docs_enabled else None,  # 同步控制机器可读的接口描述入口。
    )  # 完成应用基础对象，后续继续挂载依赖资源和接口。
    application.state.settings = settings  # 把配置绑定到当前应用，get_settings 依赖据此取得对应实例。
    application.state.db_engine = create_database_engine(settings)  # 创建数据库连接管理器；真正连接通常在首次执行数据库操作时建立。
    application.add_exception_handler(SQLAlchemyError, database_error_response)  # 统一数据库异常的对外错误结构，避免内部细节泄露。
    application.add_exception_handler(RequestValidationError, validation_error_response)  # 统一过滤请求校验错误中的敏感输入。
    application.add_exception_handler(StarletteHTTPException, authentication_error_response)  # 覆盖认证依赖提前失败时的缓存头处理。
    application.add_middleware(  # 以应用级中间件集中声明允许前端跨来源调用的规则。
        CORSMiddleware,  # 使用框架提供的跨域实现，避免各路由手工处理预检请求。
        allow_origins=list(settings.cors_origins),  # 仅允许配置列出的来源，开发时对应前端两个本机地址。
        allow_credentials=False,  # 当前认证依赖显式 Authorization 头，不开启浏览器跨域凭证模式。
        allow_methods=["*"],  # 对已获准来源放行接口使用的请求方法。
        allow_headers=["*"],  # 允许前端发送内容类型和 Authorization 等请求头。
    )  # 完成跨域中间件配置，框架会按该规则处理响应和预检请求。
    application.include_router(api_router)  # 挂载统一的 /api/v1 接口集合，让框架能够匹配业务路径。
    return application  # 将完成组装的实例交给启动服务器或测试客户端。


app = create_app()  # 作为启动命令 app.main:app 的应用入口；导入模块时按当前环境创建实例。
