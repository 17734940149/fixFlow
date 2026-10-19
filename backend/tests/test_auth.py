
"""认证请求测试：从真实迁移、账户准备到登录、鉴权和退出验证完整闭环。

调用位置：pytest 自动发现；各测试通过 auth_environment 得到独立临时数据库。
原因：直接调用服务函数不能证明路由、输入校验、响应过滤和依赖已经连通；
本文件使用正式请求入口，再独立读取数据库核对持久化，不连接开发者个人数据库。
"""

import time  # 取得当前时间，构造过期会话和锁定到期边界。
from collections.abc import Iterator  # 标注夹具生成器，说明资源需要在测试结束后回收。
from dataclasses import dataclass  # 用只读数据类携带同一测试环境，减少配置混用。
from pathlib import Path  # 标注临时目录路径，让认证测试隔离真实数据库。
from typing import Annotated, TypedDict  # 定义依赖参数与结构化返回类型，保持辅助函数字段契约清晰。
from uuid import UUID  # 标注服务器用户编号，避免把账户名和用户编号混为一谈。

import pytest  # 提供夹具、参数化与临时替换能力，覆盖认证边界。
from alembic import command  # 用正式迁移准备测试数据库，验证实际表结构可用。
from alembic.config import Config  # 加载迁移入口，将临时配置交给正式迁移代码。
from fastapi import Depends  # 在测试路由中复用正式权限依赖，不另写管理员判断。
from fastapi.testclient import TestClient  # 通过进程内请求覆盖真实路由、依赖和响应序列化。
from httpx2 import Response  # 标注请求响应类型，集中检查状态、响应头与错误内容。
from sqlalchemy import select  # 构造正式数据库查询，核对会话摘要的实际存储。
from sqlalchemy.engine import Engine  # 标注引擎类型，环境对象明确携带连接管理入口。
from sqlalchemy.orm import Session  # 建立独立事务，准备账户并核对登录持久化结果。

from app.api.dependencies import require_admin  # 导入服务端管理员依赖，验证角色取自真实账户状态。
from app.core.config import BACKEND_ROOT, Settings  # 读取项目路径和正式设置类型，复用同一配置校验。
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, hash_session_token  # 复用真实密码算法、未知账号占位摘要和会话摘要算法。
from app.main import create_app  # 通过正式工厂创建隔离应用，包含完整中间件和生命周期。
from app.models import AuthSession, User  # 复用真实用户与会话模型，核对存储而非只相信响应。
from app.schemas.auth import UserResponse  # 使用公开用户响应模型，验证权限路由不会泄露内部字段。

TEST_PASSWORD = "Test-password-123!"  # 认证测试统一使用此公开样本密码，仅生成隔离库账户而非系统默认密码。


class LoginResult(TypedDict):  # 定义辅助函数返回结构，让测试读字段时保留明确类型。
    """作用：描述成功登录响应的令牌、期限和公开用户字段类型。

    调用位置：login 的返回类型、bearer_headers 的参数，以及使用登录结果的认证测试。
    原因：明确字典字段结构有助于检查拼写和含义，避免辅助函数隐藏接口契约变动。
    """

    access_token: str  # 客户端持有的原始令牌，仅响应返回，不应原样存数据库。
    token_type: str  # 令牌类型供辅助函数构造标准认证头。
    expires_in: int  # 有效秒数用于验证服务器返回的会话期限。
    user: dict[str, str]  # 公开用户字段集合用于验证身份与敏感字段隔离。


@dataclass(frozen=True)  # 冻结环境数据类字段，防止某项测试意外替换共享连接信息。
class AuthEnvironment:  # 把请求入口、数据库引擎与用户编号集中交给测试。
    """作用：携带一个用例的客户端、引擎与两种角色的服务器用户编号。

    调用位置：auth_environment 夹具创建，login 与本文件认证测试读取字段。
    原因：请求和数据库断言必须指向同一隔离库；冻结字段防止测试误换连接目标，
    避免接口操作一份数据、断言却读取另一份数据的假通过。
    """

    client: TestClient  # 进程内客户端负责走真实认证接口。
    engine: Engine  # 数据库引擎供测试独立读取持久化结果。
    user_id: UUID  # 普通用户编号供身份隔离与禁用测试精确查询。
    admin_id: UUID  # 管理员编号供降权测试修改正确账户。


@pytest.fixture(scope="session")  # 会话级复用密码摘要，减少重复运行高成本算法。
def password_hash() -> str:  # 为认证环境夹具准备真实摘要，未伪造密码校验结果。
    """作用：复用真实密码摘要以减少测试耗时，所有校验仍执行实际密码算法。

    调用位置：auth_environment 夹具依赖此函数；pytest 在整个测试会话中复用一次真实密码摘要。
    原因：密码摘要算法故意消耗计算资源；复用准备阶段的摘要可以缩短测试，但每次登录仍执行真实密码验证，不会掩盖算法或业务错误。
    """
    return hash_password(TEST_PASSWORD)  # 使用正式密码函数处理公开测试密码，登录仍执行真实算法。


@pytest.fixture  # 注册每项测试独立的认证环境，防止会话与锁定计数串扰。
def auth_environment(tmp_path: Path, password_hash: str) -> Iterator[AuthEnvironment]:  # 构造临时已迁移库、两类用户和请求客户端，统一测试前置条件。
    """作用：使用仅测试环境允许的临时数据库，真实迁移不会误连本机配置文件。

    调用位置：本文件各认证测试请求 auth_environment 参数时使用；pytest 每项独立准备临时数据库。
    原因：登录会写会话和失败次数，因此每项用例必须拥有独立数据库；同时通过真实迁移建表，才能发现请求逻辑与部署结构不一致的问题。
    """
    settings = Settings(  # 建立正式配置对象，随后注入迁移与应用工厂。
        _env_file=None,  # 不读取本机 .env，避免误连开发者数据库。
        environment="test",  # 仅测试环境允许本项临时文件数据库。
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",  # 数据库文件位于当前测试临时目录，不共享其他用例数据。
    )  # 完成隔离配置，迁移与请求必须使用同一数据库。
    migration_config = Config(str(BACKEND_ROOT / "alembic.ini"))  # 加载项目迁移配置，测试通过正式建表入口准备结构。
    migration_config.attributes["settings"] = settings  # 注入临时设置，迁移过程不得重新读取个人连接信息。
    command.upgrade(migration_config, "head")  # 真实升级到最新结构，确保认证测试覆盖正式迁移。
    application = create_app(settings)  # 用相同设置创建应用，贯通表结构与请求数据库连接。
    engine = application.state.db_engine  # 从应用状态取得引擎，后续数据库断言与接口共享同一目标。
    assert engine is not None  # 引擎必须已创建，否则后续认证结果无法证明真实持久化。

    @application.get("/test/admin", response_model=UserResponse)  # 只在测试应用注册管理员路由，复用公开响应模型。
    def admin_only(user: Annotated[User, Depends(require_admin)]) -> UserResponse:  # 测试路由通过正式依赖读取管理员，避免测试另写权限逻辑。
        """作用：用测试专用入口检验服务端权限依赖，不添加未实现的生产管理接口。

        调用位置：auth_environment 只在测试应用注册 /test/admin；管理员权限测试的客户端请求触发。
        原因：项目还没有生产管理业务，但正式权限依赖需要真实请求验证；只在测试实例注册该入口，既能覆盖允许与降权拒绝，也不会暴露额外生产接口。
        """
        return UserResponse.model_validate(user)  # 按公开模型转换账户，仅允许显式公开字段返回。

    with Session(engine) as db:  # 在独立事务准备两种角色，所有测试有稳定身份对照组。
        user = User(  # 构造普通用户样本，模拟正常业务访问者。
            account="interview.user", display_name="演示用户", password_hash=password_hash,  # 固定普通账户与真实摘要，方便不同请求使用相同输入。
            role="user", is_active=True,  # 明确普通角色并启用账户，排除初始禁用造成假失败。
        )  # 完成普通用户准备，不能使用管理员权限作为默认值。
        admin = User(  # 构造管理员样本，覆盖权限依赖的成功分支。
            account="interview.admin", display_name="演示管理员", password_hash=password_hash,  # 管理员使用独立账户名，身份与普通用户不可混淆。
            role="admin", is_active=True,  # 明确管理员角色并启用，供后续降权验证。
        )  # 完成管理员样本，密码算法与普通用户保持一致。
        db.add_all([user, admin])  # 批量加入两个账户，保证两个身份存在于同一隔离库。
        db.commit()  # 提交准备数据，接口独立会话才能读取到用户。
        user_id, admin_id = user.id, admin.id  # 保存持久化编号，用于后续核对身份和定向修改。
    with TestClient(application) as client:  # 进入应用生命周期，保证请求资源按正式流程准备与回收。
        yield AuthEnvironment(client, engine, user_id, admin_id)  # 产出只读环境容器，测试结束自动关闭客户端。


def login(  # 通过正式登录接口获取令牌，供后续受保护请求复用。
    environment: AuthEnvironment, account: str = "interview.user", password: str = TEST_PASSWORD  # 接收隔离环境与可覆盖账户密码，支持角色和失败场景。
) -> LoginResult:  # 返回有字段定义的结果，避免辅助函数退化为任意对象。
    """作用：通过正式接口取得凭证，让后续测试同时覆盖数据库会话的真实创建过程。

    调用位置：本文件成功登录、会话、权限和身份隔离测试调用，令牌始终来自正式 /api/v1/auth/login。
    原因：后续测试必须使用服务器实际签发的令牌，否则直接插入会话会跳过输入校验、密码验证和登录结果的禁止缓存策略。
    """
    response = environment.client.post(  # 发起真实登录请求，不绕过服务层直接插入会话。
        "/api/v1/auth/login", json={"account": account, "password": password}  # 把账户和密码放入约定请求体，覆盖输入模型与业务逻辑。
    )  # 取得完整响应，随后核对成功状态和敏感缓存策略。
    assert response.status_code == 200, response.text  # 正常登录必须成功，失败时附响应便于定位测试准备问题。
    assert response.headers["cache-control"] == "no-store"  # 含令牌的登录结果不得被浏览器或代理保存。
    return response.json()  # 返回响应结构，让测试实际使用服务器签发的令牌。


def bearer_headers(result: LoginResult) -> dict[str, str]:  # 统一构造认证头，所有受保护测试走服务端真实读取路径。
    """作用：统一构建请求认证头，避免测试绕过服务器实际读取凭证的路径。

    调用位置：本文件受保护接口请求调用，把 login 返回的真实令牌装入标准认证头。
    原因：服务端只应从正式认证头读取客户端凭证；集中构造该头可以避免测试以私有状态或查询参数意外绕过真实身份校验。
    """
    return {"Authorization": f"Bearer {result['access_token']}"}  # 把登录令牌放在标准 Bearer 头，而不是查询参数或伪造身份字段。


def assert_authentication_failure(response: Response, *, login_failed: bool = False) -> None:  # 统一验证认证失败响应，避免不同失败分支泄露账户状态。
    """作用：验证统一错误与禁止缓存，避免不同失败类型泄露账号状态。

    调用位置：错误凭据、非法令牌、退出、过期、禁用和锁定测试复用；login_failed 决定公开错误类别。
    原因：只比较状态码无法发现账号枚举或缓存泄露；这里一并固定认证挑战、禁止缓存和公开错误码，使各失败分支遵循同一安全契约。
    """
    assert response.status_code == 401  # 认证失败必须使用未认证状态码。
    assert response.headers["www-authenticate"] == "Bearer"  # 认证挑战说明当前接口需要 Bearer 凭证。
    assert response.headers["cache-control"] == "no-store"  # 失败响应也禁止缓存，避免遗留敏感身份状态。
    assert response.json()["detail"]["code"] == (  # 核对稳定错误码，区分登录凭据错误与会话不可用。
        "INVALID_CREDENTIALS" if login_failed else "UNAUTHENTICATED"  # 按调用场景选择约定代码，不把账号存在、禁用或锁定状态外泄。
    )  # 完成错误码比较，确保所有认证失败分支使用统一结构。


def test_login_and_current_user_do_not_expose_secrets(auth_environment: AuthEnvironment) -> None:  # 验证登录规范化、公开响应以及数据库只保存令牌摘要。
    """作用：账号格式统一后可登录，公开资料只包含明确允许的字段。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：登录成功不等于秘密安全；必须同时检查返回字段白名单与数据库摘要，防止密码或可直接使用的原始令牌被多余地保存或返回。
    """
    result = login(auth_environment, account="  INTERVIEW.USER  ")  # 用带空格的大写账户登录，证明规范化在查询前执行。
    assert result["token_type"] == "bearer"  # 响应声明标准 Bearer 类型，调用方可正确构造认证头。
    assert result["expires_in"] == 3600  # 默认有效期应为一小时，与本项隔离配置一致。
    assert len(result["access_token"]) == 43  # 随机令牌长度应符合生成规则，防止意外截断或弱化。
    assert set(result["user"]) == {"id", "account", "display_name", "role"}  # 用户对象只能返回白名单字段，密码和内部状态不应泄露。
    assert result["user"]["id"] == str(auth_environment.user_id)  # 登录结果必须属于普通测试用户，不能串到管理员身份。
    response = auth_environment.client.get("/api/v1/auth/me", headers=bearer_headers(result))  # 用刚签发令牌访问当前用户接口，覆盖完整会话验证链。
    assert response.status_code == 200  # 有效会话应该被接受。
    assert response.json() == result["user"]  # 当前用户响应应与登录公开资料一致。
    assert response.headers["cache-control"] == "no-store"  # 公开资料响应也禁止缓存，避免身份数据在共享代理留存。
    assert "password" not in response.text  # 当前用户正文不能出现密码字段或摘要内容。
    assert "token" not in response.text  # 当前用户正文也不应重复暴露会话令牌。
    with Session(auth_environment.engine) as db:  # 另起数据库会话，独立核对认证服务实际持久化。
        session = db.scalar(select(AuthSession))  # 读取保存的会话记录，确认登录真的创建了服务器状态。
        assert session is not None  # 成功登录后必须有持久化会话，不能只返回客户端令牌。
        assert session.token_hash == hash_session_token(result["access_token"])  # 数据库摘要必须与响应令牌计算出的摘要一致。
        assert result["access_token"] != session.token_hash  # 原始令牌不得等于数据库保存值，降低数据库泄露后凭证可直接使用的风险。
        assert session.user_id == auth_environment.user_id  # 会话必须绑定服务器普通用户编号，而非客户端传入身份。


def test_wrong_and_unknown_credentials_share_error(  # 验证未知账户与密码错误使用一致外部错误。
    auth_environment: AuthEnvironment, monkeypatch: pytest.MonkeyPatch  # 接收隔离环境和临时替换夹具，记录校验路径但保留真实算法。
) -> None:  # 本测试只断言保护行为，不返回共享账户状态。
    """作用：未知账号也计算密码摘要校验，且不能通过错误正文确认账号是否存在。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：账号不存在与密码错误若提示不同，会允许外部枚举有效账号；未知账号也应做占位摘要校验，减少跳过密码计算造成的明显路径差异。
    """
    from app.services import auth  # 导入实际认证服务模块，临时包装其正式密码校验入口。

    verified_hashes: list[str] = []  # 记录参与校验的摘要，证明未知账户也执行了同类计算。
    original_verify = auth.verify_password  # 保存原始校验函数，包装时仍运行真实密码算法。

    def capture_verification(password: str, stored_hash: str) -> bool:  # 包装密码校验，只观察摘要来源而不伪造成功或失败。
        """作用：记录校验目标而不改动算法，确认未知账号不会跳过高成本密码校验。

        调用位置：test_wrong_and_unknown_credentials_share_error 临时包装认证服务的 verify_password；真实登录请求间接触发。
        原因：仅看错误正文无法证明未知账号执行了密码算法；包装函数记录摘要后继续调用原实现，使观察路径不会把真实校验替换为模拟结果。
        """
        verified_hashes.append(stored_hash)  # 记录本次摘要，后续核对是否包含未知账户占位摘要。
        return original_verify(password, stored_hash)  # 把输入交回真实算法，测试不会绕过密码保护。

    monkeypatch.setattr(auth, "verify_password", capture_verification)  # 仅本用例临时替换入口，测试结束恢复正式函数。
    responses = [  # 收集两类失败请求，比较服务端公开行为是否一致。
        auth_environment.client.post(  # 通过真实登录路由执行每个失败样本。
            "/api/v1/auth/login", json={"account": account, "password": "Wrong-password"}  # 已知和未知账户都使用相同错误密码，隔离账户存在性这一变量。
        )  # 取得当前账户样本的实际响应，不直接调用业务函数。
        for account in ("interview.user", "unknown.user")  # 分别覆盖存在账户密码错和账户不存在。
    ]  # 完成两类响应收集，接下来逐项核对统一契约。
    for response in responses:  # 逐条检查失败状态、挑战头、禁止缓存和错误码。
        assert_authentication_failure(response, login_failed=True)  # 登录失败应走同一公开响应结构。
    assert responses[0].json() == responses[1].json()  # 两类正文必须完全一致，不能通过提示枚举账户。
    assert DUMMY_PASSWORD_HASH in verified_hashes  # 未知账户占位摘要必须被真实校验，避免明显跳过高成本算法的差异。


@pytest.mark.parametrize(  # 用参数化覆盖多种不合法或不可用的认证头。
    "authorization", [None, "Basic abc", "Bearer invalid", "Bearer " + "a" * 43]  # 分别测试缺头、错误认证方案、错误长度和格式正确但不存在的令牌。
)  # 完成认证头样本定义，每类单独运行后续验证。
def test_missing_or_invalid_session_is_rejected(  # 验证未持有合法会话不能进入受保护接口。
    auth_environment: AuthEnvironment, authorization: str | None  # 接收隔离环境和当前认证头样本，避免不同失败原因混在一次请求。
) -> None:  # 此用例通过统一失败断言检查边界，不返回任何令牌。
    """作用：缺失、错误格式和不存在的会话都不能进入受保护的资料接口。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：接口不能仅判断认证头存在；还要拒绝错误方案、错误格式和根本不存在的会话，否则伪造头字段就可能读取受保护资料。
    """
    headers = {"Authorization": authorization} if authorization else {}  # 按样本构造头；缺头场景保持请求没有认证字段。
    response = auth_environment.client.get("/api/v1/auth/me", headers=headers)  # 请求当前用户接口，触发正式会话依赖校验。
    assert_authentication_failure(response)  # 所有不合法或不存在会话均应返回统一未认证错误。


def test_logout_revokes_only_current_session(auth_environment: AuthEnvironment) -> None:  # 验证退出只撤销当前会话，不误伤同账户其他设备。
    """作用：退出后旧凭证立即失效，但同一账号其他设备的独立会话仍可使用。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：退出返回成功不能证明凭证失效；还必须重用原令牌验证即时撤销，并确认同账户其他设备的独立会话未被误伤。
    """
    first = login(auth_environment)  # 首次登录模拟第一台设备的独立会话。
    second = login(auth_environment)  # 再次登录模拟同账户第二台设备的独立会话。
    assert first["access_token"] != second["access_token"]  # 两次令牌必须不同，证明服务器没有复用单一账户令牌。
    response = auth_environment.client.post("/api/v1/auth/logout", headers=bearer_headers(first))  # 用第一会话退出，走真实会话撤销逻辑。
    assert response.status_code == 204  # 退出成功使用无正文状态码，客户端无需解析资料。
    assert response.content == b""  # 无正文状态不得夹带额外令牌或用户信息。
    assert response.headers["cache-control"] == "no-store"  # 退出响应也禁止缓存，避免旧身份状态被保留。
    assert_authentication_failure(  # 再次访问第一个会话，要求立即得到认证失败。
        auth_environment.client.get("/api/v1/auth/me", headers=bearer_headers(first))  # 用已经退出的原始令牌请求当前用户，验证服务端撤销真正生效。
    )  # 完成已撤销会话断言，而不是仅核对退出返回码。
    assert auth_environment.client.get(  # 继续用第二会话请求，确认独立会话未被一起撤销。
        "/api/v1/auth/me", headers=bearer_headers(second)  # 第二令牌仍属于同一账户，但其持久化会话应保留。
    ).status_code == 200  # 未退出的设备仍成功访问，证明撤销范围是当前会话。


def test_expired_session_is_rejected(auth_environment: AuthEnvironment) -> None:  # 验证服务器检查到期时间，而不信任客户端仍持有令牌。
    """作用：即使客户端仍持有凭证，服务器也必须检查数据库中的有效期限。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：客户端可能长期保留或重发令牌，服务器不能依赖客户端主动删除；每次受保护请求都应检查数据库中的会话有效期限。
    """
    result = login(auth_environment)  # 先通过正式登录建立可用会话，随后只改变有效期限。
    with Session(auth_environment.engine) as db:  # 从数据库直接调整到期值，模拟时间已经推进。
        session = db.get(AuthSession, hash_session_token(result["access_token"]))  # 按原令牌摘要定位正确会话，避免改到其他设备记录。
        assert session is not None  # 准备阶段必须确有会话，排除登录失败造成的假通过。
        session.expires_at = int(time.time()) - 1  # 把到期设为当前时间之前一秒，固定过期边界。
        db.commit()  # 提交到期变更，让下一请求的独立会话读取新状态。
    assert_authentication_failure(  # 要求持有旧令牌也得到未认证响应。
        auth_environment.client.get("/api/v1/auth/me", headers=bearer_headers(result))  # 再次请求真实受保护接口，触发服务端到期判断。
    )  # 完成过期拒绝契约验证，不修改客户端令牌内容。


def test_disabling_user_rejects_login_and_existing_session(auth_environment: AuthEnvironment) -> None:  # 验证禁用账户同时影响已有会话与新登录。
    """作用：禁用状态必须从数据库实时读取，不能只在签发会话时检查一次。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：禁用必须同时控制新的登录和已经签发的会话；若只在签发时检查，用户被禁用后仍可凭旧令牌访问业务。
    """
    result = login(auth_environment)  # 先在启用状态获得会话，覆盖禁用前签发的旧凭证。
    with Session(auth_environment.engine) as db:  # 独立修改账户状态，模拟管理员在服务端禁用用户。
        user = db.get(User, auth_environment.user_id)  # 按服务器用户编号查找目标，避免依赖客户端身份字段。
        assert user is not None  # 目标账户必须存在，确保状态变更确实作用于正确记录。
        user.is_active = False  # 将账户设为禁用，保留原会话以检验每次请求重新查状态。
        db.commit()  # 提交禁用变更，使后续请求读取持久化结果。
    assert_authentication_failure(  # 旧会话请求必须被拒绝，不能只在登录时检查一次。
        auth_environment.client.get("/api/v1/auth/me", headers=bearer_headers(result))  # 用禁用前签发的令牌读取资料，验证实时账户状态生效。
    )  # 完成已有会话拒绝断言。
    response = auth_environment.client.post(  # 继续尝试新的真实登录，验证另一条入口同样拒绝禁用账户。
        "/api/v1/auth/login", json={"account": "interview.user", "password": TEST_PASSWORD}  # 提供正确密码，排除密码错误掩盖禁用判断。
    )  # 取得新登录实际结果，核对禁用信息未外泄。
    assert_authentication_failure(response, login_failed=True)  # 禁用登录与普通凭据失败使用相同公开错误。


def test_admin_permission_comes_from_database(auth_environment: AuthEnvironment) -> None:  # 验证管理权限来自数据库，降权后旧令牌不能保留特权。
    """作用：普通用户不能伪造角色，管理员被降权后旧凭证也不能保留管理权限。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：权限变更应由服务器数据库即时决定，不能依赖客户端提交角色或令牌签发时的旧角色；降权后重用旧令牌才能发现过期权限缓存问题。
    """
    user = login(auth_environment)  # 先以普通用户登录，覆盖权限拒绝分支。
    response = auth_environment.client.get("/test/admin", headers=bearer_headers(user))  # 访问复用正式管理员依赖的测试路由。
    assert response.status_code == 403  # 认证通过但权限不足时应返回禁止访问。
    admin = login(auth_environment, account="interview.admin")  # 以真正管理员账户登录，覆盖相同依赖的允许分支。
    assert auth_environment.client.get(  # 请求管理员路由，确认当前权限确实可使用。
        "/test/admin", headers=bearer_headers(admin)  # 传入管理员的真实会话令牌，不伪造角色字段。
    ).status_code == 200  # 管理员初始访问应成功，保证后续降权对照有效。
    with Session(auth_environment.engine) as db:  # 独立修改服务器角色，模拟受控后台降权操作。
        current_admin = db.get(User, auth_environment.admin_id)  # 按管理员编号查询，防止误修改普通用户。
        assert current_admin is not None  # 确认管理员存在后才变更角色。
        current_admin.role = "user"  # 把角色改为普通用户，原令牌保持不变。
        db.commit()  # 提交角色变更，验证下一请求重新读取权限。
    assert auth_environment.client.get(  # 再次请求同一管理入口，检验旧会话不能缓存过时特权。
        "/test/admin", headers=bearer_headers(admin)  # 仍使用之前管理员令牌，隔离服务端角色变化这一条件。
    ).status_code == 403  # 降权后必须立即禁止访问，证明权限不由客户端凭据决定。


def test_lockout_persists_and_recovers(auth_environment: AuthEnvironment) -> None:  # 验证失败计数落库、到期恢复以及成功后清零。
    """作用：失败计数必须落库，锁定到期后重新计数，成功登录后清除失败状态。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：失败保护需要跨请求持久化；本项同时验证达到阈值、锁定期间正确密码仍被拒、到期重计数及成功清零，避免永久锁死或轻易绕过。
    """
    for _ in range(5):  # 连续执行五次错误密码，达到配置中的锁定阈值。
        response = auth_environment.client.post(  # 每次都通过真实登录路由，覆盖计数提交而非手改值。
            "/api/v1/auth/login", json={"account": "interview.user", "password": "Wrong"}  # 同一账户使用固定错误密码，确保失败累加到同一记录。
        )  # 取得当前失败请求响应，再核对统一对外表现。
        assert_authentication_failure(response, login_failed=True)  # 每次失败均使用统一凭据错误，不泄露当前累计次数。
    with Session(auth_environment.engine) as db:  # 另起数据库会话验证计数确实持久化。
        user = db.get(User, auth_environment.user_id)  # 按服务器账户编号读取锁定状态。
        assert user is not None  # 账户必须存在，防止未查到记录导致错误推断。
        assert user.failed_login_attempts == 5  # 五次错误应准确累积五次，不能漏记或只保存在内存。
        assert user.locked_until is not None and user.locked_until > int(time.time())  # 锁定期限必须存在且位于未来，证明阈值触发有效。
    locked_response = auth_environment.client.post(  # 锁定期间再尝试登录，验证正确密码也不能提前解锁。
        "/api/v1/auth/login", json={"account": "interview.user", "password": TEST_PASSWORD}  # 这次使用正确密码，使拒绝只能来自锁定状态。
    )  # 取得锁定期间请求结果，检查不会意外创建会话。
    assert_authentication_failure(locked_response, login_failed=True)  # 锁定失败仍使用统一错误，不能暴露账户是否存在。
    with Session(auth_environment.engine) as db:  # 独立修改到期时间，模拟锁定等待已经结束。
        user = db.get(User, auth_environment.user_id)  # 读取同一账户，保持计数和到期状态验证的连续性。
        assert user is not None  # 确认目标仍存在，保证到期模拟真实作用于账户。
        user.locked_until = int(time.time()) - 1  # 把锁定时间改为过去，触发下一请求的到期恢复分支。
        db.commit()  # 提交到期状态，让下一请求读到已到期锁定。
    response = auth_environment.client.post(  # 锁定到期后再做一次失败登录，检查计数重新开始。
        "/api/v1/auth/login", json={"account": "interview.user", "password": "Wrong"}  # 继续使用错误密码，使本项专门覆盖到期后的首次失败。
    )  # 取得该失败响应，后续对照数据库新计数。
    assert_authentication_failure(response, login_failed=True)  # 公开失败契约仍应一致，不暴露内部恢复过程。
    with Session(auth_environment.engine) as db:  # 独立查询到期恢复后的数据库状态。
        user = db.get(User, auth_environment.user_id)  # 读取目标账户，检查失败计数和锁定时间。
        assert user is not None  # 确保账户存在后再验证状态字段。
        assert user.failed_login_attempts == 1  # 新一轮只有一次失败，应从一计数而不是延续原五次。
        assert user.locked_until is None  # 未重新达到阈值时锁定期限应清空。
    login(auth_environment)  # 再用正确密码登录，覆盖成功清理失败状态。
    with Session(auth_environment.engine) as db:  # 重新查询持久化结果，保证清零不是仅内存修改。
        user = db.get(User, auth_environment.user_id)  # 定位同一账户，核对成功登录后的最终状态。
        assert user is not None  # 账户应仍存在，成功不能误删或重建身份。
        assert user.failed_login_attempts == 0  # 成功登录后失败次数必须归零。
        assert user.locked_until is None  # 成功后不应残留锁定期限，避免下次正常登录被误拒。


@pytest.mark.parametrize(  # 分别尝试客户端注入角色、用户编号与归属编号。
    "extra", [{"role": "admin"}, {"user_id": "other-user"}, {"owner_id": "other-user"}]  # 这些额外身份字段均不属于登录契约，应由输入模型拒绝。
)  # 完成恶意额外字段参数化，每种独立验证。
def test_client_cannot_select_identity_or_role(  # 验证客户端不能通过请求体或查询参数决定身份和角色。
    auth_environment: AuthEnvironment, extra: dict[str, str]  # 接收隔离环境与本次注入字段，复用同一正式路由。
) -> None:  # 测试只检查拒绝与身份归属，不写入客户端指定权限。
    """作用：拒绝额外身份字段，防止后续重构意外把客户端角色写入服务器用户记录。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：账户归属和角色属于服务器可信状态；测试主动注入身份字段和其他账户查询参数，防止重构后误把客户端声明当作授权依据。
    """
    response = auth_environment.client.post(  # 发起含额外字段的真实登录请求，触发输入模型保护。
        "/api/v1/auth/login",  # 沿用正式登录入口，避免测试专用逻辑掩盖风险。
        json={"account": "interview.user", "password": TEST_PASSWORD, **extra},  # 合法账户密码之外附加身份字段，验证服务端严格输入契约。
    )  # 取得输入拒绝结果，随后检查密码是否被回显。
    assert response.status_code == 422  # 额外身份字段必须被判为输入不合法，而非默默接受。
    assert TEST_PASSWORD not in response.text  # 校验错误响应不得包含输入密码。
    result = login(auth_environment)  # 再正常登录，验证真实账户仍可用且身份未被污染。
    response = auth_environment.client.get(  # 请求当前用户时附带其他账户名查询参数，测试身份来源边界。
        "/api/v1/auth/me?account=interview.admin", headers=bearer_headers(result)  # 认证头属于普通用户，查询参数不能切换成管理员。
    )  # 取得实际当前用户响应，核对服务器绑定身份。
    assert response.json()["id"] == str(auth_environment.user_id)  # 用户编号必须仍为当前令牌绑定的普通用户。
    assert response.json()["role"] == "user"  # 角色也必须保持普通用户，不能由查询参数提升。


@pytest.mark.parametrize(  # 为输入校验建立边界样本表，每项独立运行。
    "payload",  # 将各样本注入请求体参数，覆盖账户与密码限制。
    [  # 开始列出非法输入组合，保持其他字段有效以定位原因。
        {"account": "ab", "password": TEST_PASSWORD},  # 账户过短，应在业务查询前拒绝。
        {"account": "name@example.com", "password": TEST_PASSWORD},  # 当前账户规则不允许邮箱格式，不能误当成已有支持的登录方式。
        {"account": ".account", "password": TEST_PASSWORD},  # 账户不能以句点开头，验证格式边界。
        {"account": "中文账号", "password": TEST_PASSWORD},  # 账户不接受中文字符，按当前明确输入契约验证。
        {"account": "a" * 65, "password": TEST_PASSWORD},  # 账户超过最大长度，应拒绝不受控输入。
        {"account": "interview.user", "password": ""},  # 密码为空应拒绝，避免进入没有意义的高成本校验。
        {"account": "interview.user", "password": "Secret" * 22},  # 密码过长应拒绝，控制异常计算与请求负担。
    ],  # 完成非法输入样本列表，不对测试字符串内容添加注释字符。
)  # 完成参数化声明，每一类失败都执行统一安全断言。
def test_invalid_login_input_is_rejected_without_password_echo(  # 验证输入失败响应不会把原始密码返回客户端。
    auth_environment: AuthEnvironment, payload: dict[str, str]  # 接收本项请求体与隔离环境，不通过私有服务函数绕过校验。
) -> None:  # 以真实请求结果验证输入限制，不返回共享数据。
    """作用：校验错误也不能回显密码，输入长度限制用于控制不必要的计算与异常数据。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：账户格式和密码长度应在高成本校验前受控；默认参数错误可能回显输入，因此每个边界样本都同时检查密码不出现在响应正文。
    """
    response = auth_environment.client.post("/api/v1/auth/login", json=payload)  # 发送样本到正式登录路由，覆盖请求模型和错误处理器。
    assert response.status_code == 422  # 非法输入应返回参数校验失败状态。
    assert response.headers["cache-control"] == "no-store"  # 校验失败也禁止缓存，避免敏感请求内容被保存。
    if payload["password"]:  # 仅非空密码才做正文包含性检查，空字符串天然存在于任何文本中。
        assert payload["password"] not in response.text  # 输入密码不能出现在校验错误正文，避免默认错误回显泄露秘密。


def test_different_accounts_have_isolated_sessions(auth_environment: AuthEnvironment) -> None:  # 验证不同账户令牌互不影响且始终绑定各自用户编号。
    """作用：会话绑定服务器中的用户编号，管理员凭证不会改变普通用户凭证的归属。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：只用一个账户无法发现全局会话或错误用户绑定；普通用户与管理员交替请求可以证明各令牌始终返回自身资料。
    """
    user, admin = login(auth_environment), login(auth_environment, account="interview.admin")  # 分别登录普通用户和管理员，为同一接口建立两种身份对照。
    assert user["access_token"] != admin["access_token"]  # 两账户令牌必须不同，不能把会话错误绑定为全局状态。
    for result, expected_id in (  # 逐一用令牌和预期用户编号验证身份归属。
        (user, auth_environment.user_id), (admin, auth_environment.admin_id)  # 建立普通用户及管理员对应关系，由服务器持久化编号作为基准。
    ):  # 完成身份对照序列，后面请求分别独立验证。
        response = auth_environment.client.get("/api/v1/auth/me", headers=bearer_headers(result))  # 每个令牌调用当前用户接口，触发正式会话验证和用户查询。
        assert response.status_code == 200  # 两个合法身份都应成功访问自己的公开资料。
        assert response.json()["id"] == str(expected_id)  # 每份返回编号必须匹配该令牌用户，防止跨账户数据串读。
