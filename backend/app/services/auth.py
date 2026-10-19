"""登录、账号失败锁定与当前会话撤销的业务实现。

作用：在一次数据库工作单元内校验账号、维护失败状态，并保存或删除服务端会话。
调用位置：app.api.v1.routes.auth 的登录和退出接口调用本模块函数。
原因：路由不应混杂密码算法与事务规则；服务独立后更容易测试并发登录和失败持久化。
"""

import time  # 以整数时间戳记录锁定期限与会话到期时间，便于统一比较和存储。

from sqlalchemy import delete, select  # 构造参数化查询与删除语句，避免手工拼接账号或凭证摘要。
from sqlalchemy.orm import Session  # 声明调用方提供的数据库工作单元类型，不在服务内重复建连接。

from app.core.config import Settings  # 登录服务读取失败次数阈值、锁定秒数和会话有效分钟数。
from app.core.security import (  # 共享密码与凭证工具，服务层只组织规则而不重新实现算法。
    DUMMY_PASSWORD_HASH,  # 未知账号也执行一次密码验证，降低可观察的耗时差异。
    create_session_token,  # 密码通过后生成独立的高随机性登录凭证。
    hash_session_token,  # 数据库只保存会话凭证摘要，避免表中数据直接用于冒用登录。
    verify_password,  # 校验密码与保存摘要的匹配关系，不进行明文比较。
)  # 完成安全工具导入，下面的服务复用这些集中维护的实现。
from app.models import AuthSession, User  # 映射服务端会话表和用户表，承载需要事务保护的认证状态。
from app.schemas.auth import LoginResponse, UserResponse  # 显式构造对外可公开结果，避免返回整个用户数据库对象。


class AuthenticationFailed(Exception):  # 以专门异常区分预期身份失败和数据库等系统故障。
    """作用：统一表示未知账号、密码错误、账号禁用或锁定等登录失败。

    调用位置：authenticate_user 抛出；登录路由捕获并转换成统一的 401 响应。
    原因：具体账号状态不应暴露给客户端，同时服务层无需依赖框架的请求异常类型。
    边界：该异常不承载密码、凭证或细分失败消息，系统故障也不应伪装成此异常。
    """


def authenticate_user(  # 登录业务入口，调用方提供已规范化账号、原始密码和请求数据库工作单元。
    db: Session, settings: Settings, account: str, password: str  # db 管事务，settings 给策略，账号用于定位用户，密码只用于本次验证。
) -> LoginResponse:  # 成功返回对外模型；预期失败抛出不泄露账号状态的业务异常。
    """作用：验证登录条件，提交失败计数或新会话，并返回公开的登录成功结果。

    调用位置：POST /api/v1/auth/login 的 login 路由调用；认证测试也直接验证它。
    原因：锁定与会话是服务端状态，只有写入数据库并提交后，其他请求和设备才能看到。
    参数：db 是请求级工作单元；account 已由 LoginRequest 规范化；password 不保存明文。
    返回与错误：成功返回 LoginResponse；预期身份失败抛出 AuthenticationFailed；数据库错误上抛。
    并发：PostgreSQL 的行锁让同一账号的并发尝试按顺序更新，避免多个请求读到相同旧计数。
    事务：失败次数必须先提交再抛认证异常，否则回滚会撤销计数，账号锁定就无法生效。
    边界：账号行锁保护单账号计数，并不替代上线后对来源、全站请求量的限流。
    """
    user = db.scalar(select(User).where(User.account == account).with_for_update())  # 查询用户并锁住已有账号行，事务结束前同账号修改需等待；未知账号没有可锁定的行。
    if user is None:  # 对外不能明确提示账号不存在，但仍需要走接近真实密码校验的计算步骤。
        verify_password(password, DUMMY_PASSWORD_HASH)  # 验证虚拟摘要以减少未知账号快速返回造成的耗时差异，不使用其校验结果。
        db.rollback()  # 结束查询开启的事务并归还连接资源；未知账号没有可持久化的失败计数。
        raise AuthenticationFailed  # 服务层只抛统一业务异常，由路由决定对外 401 结构。

    password_matches = verify_password(password, user.password_hash)  # 使用密码库验证摘要，禁用或锁定账号也不直接跳过这一步计算。
    # 行锁等待和密码计算完成后再计时，避免排队消耗锁定期或新凭证的有效期。
    now = int(time.time())  # 在行锁等待和密码计算之后取时间，后续用此刻检查账号锁定是否仍有效。
    if not user.is_active or (user.locked_until is not None and user.locked_until > now):  # 禁用账号以及尚在锁定期的账号都不能签发新会话。
        db.rollback()  # 此分支不改变账号状态，回滚结束事务并释放账号行锁。
        raise AuthenticationFailed  # 使用同一种失败结果，避免暴露账号被禁用或锁定的具体状态。

    if user.locked_until is not None:  # 运行到此且仍有锁定时间，说明之前的锁定已经到期。
        # 锁定期结束后重新计数，避免恢复登录后的第一次输错马上再次锁定。
        user.failed_login_attempts = 0  # 重新开始失败计数，给锁定结束后的用户完整尝试次数。
        user.locked_until = None  # 清除已结束的锁定标记，后续成功或失败分支会统一提交变化。

    if not password_matches:  # 只有账号可用且不在有效锁定期时，才累计本次错误密码。
        user.failed_login_attempts += 1  # 在行锁保护下更新计数，防止并发请求相互覆盖失败次数。
        if user.failed_login_attempts >= settings.login_max_attempts:  # 达到配置阈值后，停止继续签发该账号会话。
            user.locked_until = now + settings.login_lock_seconds  # 把绝对解锁时刻保存到数据库，其他应用实例也能执行相同规则。
        db.commit()  # 先持久化失败和锁定状态，再结束事务释放行锁，不能被后续异常回滚撤销。
        raise AuthenticationFailed  # 写入失败状态后抛出统一失败，客户端仍只看到账号或密码错误。

    user.failed_login_attempts = 0  # 登录成功后清除之前累计的失败次数，不让旧失败影响下一轮正常登录。
    user.locked_until = None  # 成功分支确保不存在残留锁定标记，并与新会话在同一事务提交。
    token = create_session_token()  # 为本次登录生成独立原始凭证，避免不同设备共用一个无法单独撤销的值。
    issued_at = int(time.time())  # 在签发阶段重新取时间，避免密码计算消耗新凭证的有效期。
    ttl_seconds = settings.session_ttl_minutes * 60  # 将配置的分钟转换为数据库时间戳和响应统一使用的秒。
    response = LoginResponse(  # 在提交前校验并构造公开响应；尚未提交成功时不会向客户端发送凭证。
        access_token=token,  # 原始凭证只在本次登录响应中交给客户端，数据库不保存此值。
        expires_in=ttl_seconds,  # 告知客户端有效时长，实际能否使用仍由服务端到期检查决定。
        user=UserResponse.model_validate(user),  # 仅复制允许公开的用户字段，避免把密码摘要或锁定计数返回给前端。
    )  # 得到完整登录结果，接下来仍必须成功持久化会话才能返回。
    db.add(AuthSession(  # 把新会话对象加入工作单元；真正写入通常由后续 commit 触发刷新。
        token_hash=hash_session_token(token),  # 保存凭证的单向摘要，后续认证用同算法计算后匹配。
        user_id=user.id,  # 绑定数据库核实的用户，不允许客户端指定会话所属身份。
        expires_at=issued_at + ttl_seconds,  # 保存绝对到期时间，身份依赖每次查询时据此拒绝过期凭证。
        created_at=issued_at,  # 保留签发时间，便于后续维护会话和审计设计。
    ))  # 完成会话对象入队，与用户失败计数清理一起作为本事务的写入内容。
    db.commit()  # 原子提交用户状态和新会话，结束事务释放行锁；失败时不会返回成功结果。
    return response  # 只有会话已保存后才把原始凭证交给路由和客户端。


def revoke_session(db: Session, token_hash: str) -> None:  # 接收已认证当前会话的摘要，不接受任意用户编号来批量退出。
    """作用：删除指定摘要对应的服务端会话，并提交撤销结果。

    调用位置：POST /api/v1/auth/logout 的 logout 路由在身份依赖通过后调用。
    原因：前端丢弃凭证不能阻止其副本继续使用，删除服务端记录才能撤销后续认证能力。
    参数：db 为本次请求工作单元，token_hash 来自已核实会话，不是原始凭证。
    返回：无业务数据；数据库异常上抛，路由只有提交成功才返回退出成功。
    边界：撤销后新发起的认证查询会失败；已经通过认证并执行中的请求不会被追溯取消。
    """
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))  # 精确删除当前会话记录，其他设备独立凭证的记录不受影响。
    db.commit()  # 提交后其他请求才能稳定看到撤销结果，同时结束当前数据库事务。
