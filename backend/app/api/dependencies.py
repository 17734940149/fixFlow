"""认证接口共用的身份、权限与响应缓存依赖。

作用：从请求头取得会话凭证，通过数据库核实当前用户，并提供管理员权限检查入口。
调用位置：app.api.v1.routes.auth 的路由依赖和接口参数引用这些函数。
原因：身份与权限必须由服务端核实，不能相信客户端传入的用户编号、角色或按钮状态。
"""

import re  # 在数据库查询前限制凭证长度和字符，拒绝明显不符合生成规则的输入。
import time  # 取得当前时间，用于判定数据库会话是否已经超过有效期。
from dataclasses import dataclass  # 以轻量数据对象把已核实用户和当前凭证摘要一起传给后续依赖。
from typing import Annotated  # 把普通参数类型与 FastAPI 的依赖声明关联，保持类型信息清晰。

from fastapi import Depends, HTTPException, Response, status  # 提供依赖装配、可控请求错误、响应头修改和具名状态码。
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # 使用框架解析 Authorization 头，并在接口文档中声明凭证输入方式。
from sqlalchemy import select  # 构造参数化的会话与用户关联查询，避免手工拼接用户输入。
from sqlalchemy.orm import Session  # 标明数据库工作单元类型，依赖负责提供和清理它。

from app.core.security import hash_session_token  # 使用与登录保存时相同的摘要算法，才能找到凭证对应的记录。
from app.db.session import get_db  # 按请求提供数据库会话，避免认证依赖自行管理连接生命周期。
from app.models import AuthSession, User  # 查询服务端会话和用户状态，数据库记录才是认证依据。

bearer_scheme = HTTPBearer(auto_error=False)  # 身份依赖调用的请求头解析对象；关闭自动报错后由本模块统一返回认证失败格式。
AUTH_RESPONSE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}  # 认证路由、错误构造和退出响应共用，防止凭证与用户资料进入缓存。


@dataclass(frozen=True)  # 自动生成初始化方法，并禁止替换容器字段，减少后续流程误改已核实身份的机会。
class AuthenticatedSession:  # 把同一次认证查询得到的用户与凭证摘要作为一个明确对象传递。
    """作用：保存本次请求已核实的用户对象与当前会话凭证摘要。

    调用位置：get_authenticated_session 创建；get_current_user 和退出接口读取。
    原因：退出需要精确撤销当前会话，其他接口需要当前用户，合并保存可复用一次认证结果。
    边界：frozen 约束容器字段赋值，不表示里面的数据库 User 对象也自动变成不可变对象。
    """

    user: User  # 服务端按会话关联查出的用户，供身份查询和后续权限规则使用。
    token_hash: str  # 当前凭证的摘要，退出服务用它删除对应记录而不用保存原始凭证。


def prevent_auth_cache(response: Response) -> None:  # 作为认证路由的公共依赖修改框架提供的响应对象。
    """作用：为正常认证响应设置禁止缓存的响应头。

    调用位置：认证 APIRouter 的 dependencies 引用它，由框架解析路由依赖时执行。
    原因：登录结果含凭证，身份查询含用户资料，共用浏览器或中间代理不应保存这些内容。
    返回：不返回业务数据；通过 response.headers 影响路由最终响应。
    """
    response.headers.update(AUTH_RESPONSE_HEADERS)  # 将统一缓存规则合并到响应，避免各认证接口重复声明。


def authentication_error(*, login_failed: bool = False) -> HTTPException:  # 使用仅可命名传入的开关区分登录失败与已有凭证失效。
    """作用：构造统一的身份认证失败异常，不直接发送响应。

    调用位置：登录路由捕获 AuthenticationFailed 后调用；身份依赖拒绝凭证时也调用。
    原因：未知、禁用和锁定账号应使用同一登录错误，避免通过提示猜测账号状态。
    参数：login_failed 为 True 表示本次密码登录失败；默认表示已有登录凭证无效。
    返回：带 401 状态码和认证响应头的 HTTPException，调用方使用 raise 交给框架处理。
    """
    detail = (  # 为两种交互场景选择稳定错误标识，同时隐藏更细的服务端账号状态。
        {"code": "INVALID_CREDENTIALS", "message": "账号或密码错误"}  # 密码登录失败统一使用该提示，不说明是否存在或锁定。
        if login_failed  # 仅由登录路由明确选择此分支。
        else {"code": "UNAUTHENTICATED", "message": "登录已失效，请重新登录"}  # 凭证缺失、过期或失效时提示重新登录。
    )  # 得到完整错误内容，供下方异常对象携带。
    return HTTPException(  # 返回异常对象，让当前调用方决定何时中断执行。
        status_code=status.HTTP_401_UNAUTHORIZED,  # 说明客户端尚未提供当前可接受的身份凭证。
        detail=detail,  # 将上面选好的错误结构交给框架异常处理器序列化。
        headers={**AUTH_RESPONSE_HEADERS, "WWW-Authenticate": "Bearer"},  # 既禁止缓存，也声明接口要求持有者凭证认证。
    )  # 完成可供登录路由与身份依赖复用的认证异常。


def get_authenticated_session(  # 认证公共依赖由框架解析请求头并注入本次请求的数据库工作单元。
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],  # 凭证来自 Authorization 头；解析失败时允许为空，交给本函数统一报错。
    db: Annotated[Session, Depends(get_db)],  # 与同请求其他 get_db 使用者共享默认依赖缓存，避免退出时再建一个数据库会话。
) -> AuthenticatedSession:  # 返回已核实的身份容器，路由无需再信任客户端提交的用户信息。
    """作用：验证凭证格式、有效期和用户启用状态，并返回对应用户及当前会话摘要。

    调用位置：退出路由直接声明本依赖；当前身份接口通过 get_current_user 间接使用。
    原因：服务端保存会话才能在退出或禁用用户后立即拒绝旧凭证。
    过程：框架先解析声明的依赖；本函数执行查询时数据库工作单元才需要取得连接。
    返回与错误：成功返回 AuthenticatedSession；任何无效身份统一抛出 401 请求异常。
    """
    if credentials is None or credentials.scheme.lower() != "bearer":  # 拒绝未提供凭证或不属于当前认证方式的请求。
        raise authentication_error()  # 用统一响应中止处理，不让未认证请求继续进入受保护路由。
    token = credentials.credentials  # 只提取原始凭证部分，后续不把它保存到数据库。
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:  # 仅允许当前 32 随机字节生成方式对应的 43 字符地址安全文本。
        raise authentication_error()  # 明显错误的凭证无需查询会话表，仍返回相同认证失败结构。
    token_hash = hash_session_token(token)  # 与登录保存时采用相同摘要，使数据库能定位凭证而无需存明文。
    row = db.execute(  # 执行关联查询；首次数据库操作通常在此从连接池借出真实连接。
        select(AuthSession, User)  # 同时读取会话与用户，避免分别查询造成重复往返。
        .join(User, AuthSession.user_id == User.id)  # 根据服务端外键关联用户，不接受客户端提供的用户编号。
        .where(  # 在同一次数据库查询中限制凭证、有效期与用户启用状态。
            AuthSession.token_hash == token_hash,  # 只查找当前请求凭证的摘要记录。
            AuthSession.expires_at > int(time.time()),  # 已到期的会话即使记录还在表中也不能通过认证。
            User.is_active.is_(True),  # 用户被停用后，其尚未到期的会话也不再有效。
        )  # 完成身份查询条件，交给参数化查询执行。
    ).one_or_none()  # 取得唯一匹配行或空值；凭证摘要唯一约束使多行匹配不是正常结果。
    if row is None:  # 不区分不存在、过期或用户停用，避免向客户端泄露内部身份状态。
        raise authentication_error()  # 没有有效会话就中止请求，由应用异常处理器生成响应。
    return AuthenticatedSession(user=row[1], token_hash=token_hash)  # 关联查询第二列是 User，把它与当前摘要传给后续依赖或退出路由。


def get_current_user(  # 在完整会话认证之后只暴露业务需要的用户对象。
    session: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],  # 要求先完成凭证查验，由框架注入认证结果。
) -> User:  # 路由拿到的是数据库核实的用户，不是请求体中自称的身份。
    """作用：从已核实会话中取出当前用户，形成更易复用的用户依赖。

    调用位置：当前身份路由使用它；require_admin 在此基础上继续检查角色。
    原因：多数业务只需要用户资料，不应再次解析凭证或自行信任客户端用户编号。
    返回：同一次认证关联查询得到的 User 对象，不额外执行数据库查询。
    """
    return session.user  # 复用身份依赖已查出的用户，保持本次请求身份来源一致。


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:  # 先取得真实当前用户，再做管理员权限判断。
    """作用：对已认证用户增加管理员角色限制。

    调用位置：权限测试已覆盖；当前尚无实际管理路由挂载，后续管理接口可声明此依赖。
    原因：隐藏前端按钮只能影响显示，服务端仍必须拒绝普通用户直接调用管理接口。
    返回与错误：管理员返回原 User；已登录但角色不符时抛出 403，与未登录的 401 区分。
    """
    if user.role != "admin":  # 以数据库中的角色为准，不接受客户端声称自己是管理员。
        raise HTTPException(  # 身份已确认而权限不足，使用明确的禁止操作异常。
            status_code=status.HTTP_403_FORBIDDEN,  # 说明当前身份无权执行操作，重复登录不一定能解决。
            detail={"code": "FORBIDDEN", "message": "当前账号没有操作权限"},  # 提供稳定权限错误标识与可展示提示。
            headers=AUTH_RESPONSE_HEADERS,  # 权限结果涉及身份状态，同样不应被浏览器或代理缓存。
        )  # 中止受保护操作，让框架返回权限失败。
    return user  # 继续传递已核实的管理员用户，供后续业务记录操作身份。
