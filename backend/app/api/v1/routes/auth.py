"""账号登录、当前身份与当前会话退出的请求入口。

作用：声明认证接口路径、输入输出结构和身份依赖，并把实际登录规则交给服务层。
调用位置：app.api.v1.router 汇入本模块 router 后，由 FastAPI 按请求路径调度。
原因：路由只组织请求和响应，密码、锁定与数据库事务规则集中在服务层便于复用和测试。
"""

from typing import Annotated  # 在参数类型旁声明依赖来源，便于框架注入与阅读调用关系。

from fastapi import APIRouter, Depends, Response, status  # 提供接口注册、依赖注入、无正文响应和具名状态码。
from sqlalchemy.orm import Session  # 标注由 get_db 提供的请求级数据库工作单元。

from app.api.dependencies import (  # 复用公共身份检查和缓存规则，避免认证接口各自实现不同安全约定。
    AUTH_RESPONSE_HEADERS,  # 退出显式返回 Response 时需要自己带上公共禁止缓存头。
    AuthenticatedSession,  # 表示认证后同时持有用户与当前凭证摘要的参数类型。
    authentication_error,  # 把服务层的登录失败转换成统一 401 请求异常。
    get_authenticated_session,  # 退出前验证当前凭证，并取得要撤销的会话摘要。
    get_current_user,  # 当前身份查询使用的依赖，只返回已核实用户。
    prevent_auth_cache,  # 注册为认证路由公共依赖，让正常响应禁止缓存。
)  # 完成公共认证依赖的导入，下面的路由复用同一套规则。
from app.core.config import Settings, get_settings  # 登录服务需要本应用的会话期限与失败锁定配置。
from app.db.session import get_db  # 由公共生成器依赖管理请求数据库会话，路由不自行开关连接。
from app.models import User  # 标注当前身份依赖返回的数据库用户对象。
from app.schemas.auth import LoginRequest, LoginResponse, UserResponse  # 约束认证输入与可公开输出，防止返回密码摘要等字段。
from app.services.auth import AuthenticationFailed, authenticate_user, revoke_session  # 引入登录和退出业务服务及其统一失败类型。

router = APIRouter(  # 功能路由集合由第一版总路由挂载，认证相关接口共用路径和缓存规则。
    prefix="/auth", tags=["身份认证"], dependencies=[Depends(prevent_auth_cache)]  # 添加认证子路径、文档分组，以及每次请求都执行的禁止缓存依赖。
)  # 得到认证 router 对象，下方装饰器把具体函数注册到它上面。


@router.post("/login", response_model=LoginResponse, summary="账号密码登录")  # 注册完整路径 /api/v1/auth/login，并声明返回字段的模型约束。
def login(  # 框架完成所需依赖解析与请求校验后调用的同步接口函数。
    payload: LoginRequest,  # 请求体经模型校验后提供账号和敏感文本包装的密码，不接收客户端角色。
    db: Annotated[Session, Depends(get_db)],  # 获取本请求数据库工作单元，事务是否提交由服务层明确决定。
    settings: Annotated[Settings, Depends(get_settings)],  # 使用当前应用配置而非跨应用共享全局值。
) -> LoginResponse:  # 成功返回模型交给框架序列化；认证失败通过异常形成错误响应。
    """作用：接收账号密码登录请求，并把业务结果转换成接口返回或统一失败。

    调用位置：客户端发送 POST /api/v1/auth/login 时由 FastAPI 路由调度。
    原因：请求入口与登录规则分离，服务层无需依赖请求对象，也可独立做事务与并发测试。
    参数：payload 是已规范化账号的输入模型；db 和 settings 由依赖提供。
    返回与错误：成功返回包含一次性原始凭证的 LoginResponse；业务认证失败返回统一 401。
    """
    try:  # 只把预期的认证失败转换成 401，数据库等系统故障交给应用异常处理器。
        return authenticate_user(  # 调用服务层执行密码检查、锁定计数和会话保存。
            db, settings, payload.account, payload.password.get_secret_value()  # 仅在业务校验所需位置解包密码，不将明文放进响应或日志。
        )  # 把服务层构造的登录结果交给框架按 LoginResponse 返回。
    except AuthenticationFailed:  # 账号未知、禁用、锁定或密码错误都由服务层收敛为这个异常。
        raise authentication_error(login_failed=True) from None  # 不暴露具体失败原因或原异常链，统一返回账号或密码错误。


@router.get("/me", response_model=UserResponse, summary="查询当前登录身份")  # 注册完整路径 /api/v1/auth/me，并限制只返回公开用户字段。
def current_user(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:  # 身份由凭证依赖核实，客户端不需要提交用户编号。
    """作用：返回当前有效登录凭证对应的公开用户资料。

    调用位置：客户端发送 GET /api/v1/auth/me 时，框架先取得 get_current_user 依赖结果。
    原因：按服务端会话查找本人，避免客户端把用户编号改成其他人来读取资料。
    返回：UserResponse 显式列出的编号、账号、显示名和角色，不含密码摘要或失败计数。
    """
    return UserResponse.model_validate(user)  # 根据模型的属性读取规则提取公开字段，避免直接序列化整个数据库对象。


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="退出当前会话")  # 注册退出操作，成功使用 204 表示无需返回正文。
def logout(  # 当前凭证查验成功后，框架才调用撤销会话的路由函数。
    session: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],  # 取得当前已核实会话摘要，精确撤销此次登录。
    db: Annotated[Session, Depends(get_db)],  # 默认依赖缓存让它与身份依赖中的 get_db 使用同一个请求会话。
) -> Response:  # 显式返回无正文 Response，避免给 204 状态添加多余数据。
    """作用：撤销当前请求携带的会话凭证。

    调用位置：客户端发送 POST /api/v1/auth/logout，认证依赖通过后由框架调用。
    原因：仅让前端丢弃凭证不能让被复制的凭证失效，还需删除服务端会话记录。
    返回：204 无正文响应；只影响当前会话，其他设备的独立会话保留。
    """
    revoke_session(db, session.token_hash)  # 服务层删除当前摘要对应的记录并提交，提交成功后旧凭证不能再次认证。
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=AUTH_RESPONSE_HEADERS)  # 显式返回空响应并带禁止缓存头，保持与其他认证结果一致。
