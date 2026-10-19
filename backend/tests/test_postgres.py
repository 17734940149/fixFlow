
"""真实 PostgreSQL 验证：检查实际方言结构、约束、持久化和并发仲裁。

调用位置：pytest 自动发现；只有显式设置专用验证连接时才执行数据库操作。
原因：SQLite 无法证明 PostgreSQL 的行锁、唯一约束竞争和时区字段行为；
连接前后都限制主机、库名与表范围，清理仅针对核实过的专用验证库。
"""

import os  # 只从显式测试环境变量读取连接，避免自动使用开发库。
import re  # 用完整匹配核对专用测试库命名，限制清理操作范围。
import time  # 读取当前时间，验证锁定期限仍在未来。
from collections.abc import Iterator  # 标注夹具产出类型，明确真实连接需要生命周期清理。
from concurrent.futures import ThreadPoolExecutor  # 用线程池制造并发请求和事务，验证单线程测试不能证明的竞争行为。
from dataclasses import dataclass  # 用冻结的数据类携带相同测试配置和账户，防止目标混用。
from threading import Barrier  # 通过同步屏障让线程同时行动，提高并发竞争可重复性。
from uuid import UUID, uuid4  # 标注真实用户编号，并生成不存在编号覆盖外键拒绝。

import pytest  # 提供夹具、参数化、跳过和失败入口，保护未显式开启的测试环境。
from alembic import command  # 用真实迁移准备结构，不用模型直接建表绕过迁移文件。
from alembic.autogenerate import compare_metadata  # 比较 PostgreSQL 实际结构与模型，覆盖方言差异。
from alembic.config import Config  # 读取正式迁移配置，注入已验证的专用库设置。
from alembic.migration import MigrationContext  # 用真实连接建立结构比较上下文，核对模型与迁移。
from fastapi.testclient import TestClient  # 通过完整应用请求验证持久化、重启和并发登录。
from sqlalchemy import Engine, delete, func, inspect, select, text  # 使用引擎、结构检查与真实语句核对数据库状态。
from sqlalchemy.engine import URL, make_url  # 将连接串解析为结构对象，先检查目标再建立连接。
from sqlalchemy.exc import ArgumentError, IntegrityError  # 分别捕获连接解析和完整性约束错误，保持错误边界明确。
from sqlalchemy.orm import Session  # 为每个验证事务建立独立会话，不共享可变事务状态。

from app.core.config import BACKEND_ROOT, Settings  # 读取项目根路径和正式设置模型，使用真实应用配置规则。
from app.core.security import hash_password, hash_session_token  # 复用真实密码与令牌摘要算法，不把并发测试换成简化认证。
from app.db.base import Base  # 读取完整模型元数据，作为真实建表结果的对照。
from app.db.session import create_database_engine  # 使用正式引擎工厂，覆盖 PostgreSQL 驱动和连接参数。
from app.main import create_app  # 用正式应用工厂创建两个独立生命周期，验证重启不会丢会话。
from app.models import AuthSession, User  # 复用真实用户和认证会话模型，检查存储层约束与撤销。

TEST_ACCOUNT = "postgres.verify"  # 基础账户供每项真实库测试使用，仅存在于显式专用验证库。
TEST_PASSWORD = "Postgres-test-password-123!"  # 统一公开测试密码，夹具生成真实摘要；这不是网站默认密码。
TEST_TABLES = {"users", "auth_sessions", "alembic_version"}  # 允许的测试表集合供目标校验和结构断言使用，遇到其他表即停止清理。


@dataclass(frozen=True)  # 冻结环境容器字段，防止用例将目标设置替换为其他数据库。
class PostgresEnvironment:  # 把真实库设置、引擎和账户信息交给测试，避免重复读取环境。
    """作用：把真实库设置、引擎、用户编号和密码摘要组成只读环境容器。

    调用位置：postgres_environment 夹具创建，本文件用例和内部线程任务读取。
    原因：请求、并发事务和结果断言必须落在同一个核实过的专用库；
    集中携带这些信息，减少重新读配置导致误连或目标混用的风险。
    """

    settings: Settings  # 应用工厂使用此设置，确保请求和直接数据库断言指向同一库。
    engine: Engine  # 测试引擎供结构、持久化和并发事务验证。
    user_id: UUID  # 真实账户编号供身份响应与级联删除定向核对。
    password_hash: str  # 已生成的真实摘要供并发创建账户复用，控制密码算法成本。


def _validated_test_url() -> URL:  # 在任何连接前核对驱动、主机、库名和额外参数。
    """作用：执行任何连接前限制数据库、主机和驱动，未明确开启时安全跳过测试。

    调用位置：postgres_database 夹具首先调用；任何建连接、迁移和清理之前必须通过该边界检查。
    原因：真实库用例包含迁移和删除，不能自动借用业务连接；显式变量、回环主机、专用库名和禁止额外参数共同限制操作目标，未开启时安全跳过。
    """
    raw_url = os.environ.get("FIXFLOW_POSTGRES_TEST_URL")  # 只读取专门的 PostgreSQL 验证变量，不回退到业务连接设置。
    if not raw_url:  # 未显式开启验证时不连接、不建表、不删除。
        pytest.skip("未设置 FIXFLOW_POSTGRES_TEST_URL，跳过真实 PostgreSQL 验证。")  # 跳过真实库测试，让常规测试无需安装或误用个人数据库。
    try:  # 保护连接解析阶段，格式错误时给出可操作提示。
        url = make_url(raw_url)  # 用正式连接解析器拆分驱动、主机、数据库等字段。
    except (ArgumentError, ValueError):  # 捕获格式异常，不打印可能含密码的原始连接串。
        pytest.fail("PostgreSQL 验证连接格式不正确，未执行数据库操作。", pytrace=False)  # 以脱敏提示停止测试，并关闭无关回溯输出。
    if url.drivername != "postgresql+psycopg":  # 只允许项目真实使用的 PostgreSQL 驱动组合。
        pytest.fail("验证连接只允许 postgresql+psycopg 驱动。", pytrace=False)  # 驱动不符时提前停止，不能悄悄验证另一种数据库。
    if url.host not in {"localhost", "127.0.0.1", "::1"}:  # 要求显式本机回环地址，禁止测试清理指向远端服务。
        pytest.fail("验证连接只允许显式的本机主机地址。", pytrace=False)  # 主机不是允许的本机地址就失败，不建立数据库连接。
    if not re.fullmatch(r"fixflow_verify_[a-z0-9]{8}", url.database or ""):  # 数据库名必须完全符合专用验证库前缀与随机后缀。
        pytest.fail("验证数据库必须命名为 fixflow_verify_ 加 8 位小写字母或数字。", pytrace=False)  # 命名不符立即停止，降低误清理开发库或生产库的风险。
    if url.query:  # 检查任何额外查询参数，防止参数覆盖已验证主机等字段。
        # psycopg 支持由查询参数覆盖主机，全部拒绝以免绕过前面的本机校验。
        pytest.fail("验证连接不能包含额外查询参数。", pytrace=False)  # 拒绝查询参数，保证前面的连接目标校验不能被绕过。
    return url  # 只返回通过全部检查的连接对象，供专用库夹具建立连接。


def _assert_test_database(engine: Engine, expected_database: str) -> None:  # 连接后再次核对服务器实际数据库，清理前不能只信字符串。
    """作用：再次核对服务器实际连接的库，清理只允许在指定的专用验证库内执行。

    调用位置：postgres_database 迁移前与 _clear_test_rows 每次清理前调用，二次核对真实服务器目标。
    原因：连接字符串正确还不足以证明服务器实际选中了预期库；每次清理前读取真实库名并检查表范围，发现未知数据时立即停止。
    """
    with engine.connect() as connection:  # 建立短连接读取数据库自身报告的当前库名。
        actual_database = connection.scalar(text("SELECT current_database()"))  # 执行数据库函数取得真实目标，而不是复用配置中的名称。
        assert actual_database == expected_database  # 实际库名必须与预期专用库完全一致。
        assert re.fullmatch(r"fixflow_verify_[a-z0-9]{8}", actual_database or "")  # 实际名称也需满足验证库格式，提供第二层清理边界保护。
    assert set(inspect(engine).get_table_names()) <= TEST_TABLES, "验证库含非测试表，停止操作。"  # 库中只允许测试表；发现其他表立即停止，不碰未知数据。


def _clear_test_rows(engine: Engine, expected_database: str) -> None:  # 集中清理专用库测试行，每次都先重新核验目标。
    """作用：只清理已核实专用验证库中的账户和会话，确保用例互不影响。

    调用位置：postgres_environment 夹具在每项测试前后调用，仅允许已核实的专用验证库。
    原因：共享模块引擎需要每用例隔离行数据，但清理必须先核实目标；先会话后账户的顺序满足外键关系，并用提交让下一用例看到干净状态。
    """
    _assert_test_database(engine, expected_database)  # 先确认真实库名和表范围，再允许进入删除事务。
    with Session(engine) as db:  # 使用独立事务清理，避免上一项失败会话状态影响本项。
        db.execute(delete(AuthSession))  # 先删除依赖账户的会话，遵循外键关联顺序。
        db.execute(delete(User))  # 再删除测试账户，让下一项用例从干净状态开始。
        db.commit()  # 提交清理结果，后续应用和并发会话才能看到空状态。


def _new_user(account: str, password_hash: str) -> User:  # 复用最小账户构造，聚焦真实约束和并发仲裁。
    """作用：复用最小账户数据，让并发测试走真实唯一约束而不引入额外业务流程。

    调用位置：postgres_environment 夹具、非法数据测试和并发账户创建辅助函数复用。
    原因：并发约束测试需要尽量少的额外条件；复用最小账户与已有真实摘要，可把冲突结果归因于数据库唯一性而不是密码准备或无关流程。
    """
    return User(account=account, display_name="PostgreSQL 验证用户", password_hash=password_hash)  # 将已生成摘要放入普通测试账户，不增加无关业务初始化。


@pytest.fixture(scope="module")  # 模块级准备专用数据库，减少重复迁移但不共享用例账户数据。
def postgres_database() -> Iterator[tuple[Engine, Settings, str]]:  # 提供真实引擎、设置与库名，并在模块结束回收连接。
    """作用：只升级显式指定的本机验证库；不创建、迁移或清空开发数据库。

    调用位置：postgres_environment 依赖此模块级夹具；pytest 管理准备与最终引擎回收。
    原因：真实方言、索引和行锁需要 PostgreSQL 本身验证；模块级引擎减少重复连接与迁移，同时每次写入前核对专用目标，不创建或清空开发库。
    """
    url = _validated_test_url()  # 先验证显式连接目标，未通过校验绝不连接。
    settings = Settings(  # 建立正式配置，让迁移和应用使用同一已验证目标。
        _env_file=None,  # 关闭 .env 读取，避免专用目标被个人设置覆盖。
        environment="test",  # 声明测试环境，清楚区分真实业务运行与验证。
        database_url=url.render_as_string(hide_password=False),  # 仅为驱动连接获取完整连接值，不把含密码的值打印到输出。
    )  # 完成设置对象，后续所有连接都来自同一验证目标。
    database_name = url.database  # 保存已验证库名，供每次清理前二次核对。
    assert database_name is not None  # 专用库名必须明确存在，禁止省略数据库依赖默认值。
    engine = create_database_engine(settings)  # 通过项目正式工厂创建 PostgreSQL 引擎。
    assert engine is not None  # 确保已创建引擎，后续真实库断言不能在空连接上运行。
    try:  # 设置资源回收边界，迁移或用例失败仍关闭连接池。
        _assert_test_database(engine, database_name)  # 迁移前再次核对真实目标与允许表，防止误改已有业务库。
        config = Config(str(BACKEND_ROOT / "alembic.ini"))  # 加载项目迁移配置，而不是使用另一套测试结构。
        config.attributes["settings"] = settings  # 把验证库设置直接交给迁移环境。
        command.upgrade(config, "head")  # 升级专用库到最新正式结构，覆盖真实方言迁移。
        yield engine, settings, database_name  # 将已准备资源交给本模块夹具，不输出连接密码。
    finally:  # 模块结束或异常后均执行清理资源。
        engine.dispose()  # 释放真实连接池；此处不删除库，不修改开发库。


@pytest.fixture(scope="module")  # 模块级复用真实密码摘要，减少并发测试额外计算负担。
def postgres_password_hash() -> str:  # 提供真实摘要，登录仍调用正式高成本验证算法。
    """作用：复用真实密码摘要以控制测试成本；登录仍执行真实算法，未替换密码校验。

    调用位置：postgres_environment 依赖此模块级夹具；pytest 仅在本模块计算一次真实摘要。
    原因：真实密码算法有意消耗计算资源，重复准备会放大并发测试耗时；只复用摘要生成结果，登录验证仍使用正式算法，保护验证真实性。
    """
    return hash_password(TEST_PASSWORD)  # 对公开测试密码运行正式摘要函数，不模拟验证返回值。


@pytest.fixture  # 每项测试单独准备账户并在前后清理，避免状态串扰。
def postgres_environment(  # 为当前用例组装真实库环境，不创建额外数据库。
    postgres_database: tuple[Engine, Settings, str], postgres_password_hash: str  # 接收模块数据库与复用摘要，保持所有请求目标一致。
) -> Iterator[PostgresEnvironment]:  # 产出环境生成器，测试后继续执行限定目标清理。
    """作用：每项用例准备独立账户，前后清理仅限已核实的专用数据库。

    调用位置：本文件各真实库测试请求该参数时触发；pytest 每条用例准备基础账户并限定目标清理。
    原因：各用例会删除账户、修改权限或触发锁定，必须在前后清理并重建基础账户；集中容器保证请求、并发事务和数据库断言始终指向同一专用库。
    """
    engine, settings, database_name = postgres_database  # 拆出引擎、设置和已验证库名，供准备与回收共同使用。
    _clear_test_rows(engine, database_name)  # 准备前先清理上一项残留，目标每次都重新校验。
    with Session(engine) as db:  # 用独立事务创建当前用例基础账户。
        user = _new_user(TEST_ACCOUNT, postgres_password_hash)  # 构造统一基础账户，并使用真实密码摘要。
        db.add(user)  # 将账户加入事务，准备持久化编号。
        db.commit()  # 提交账户，使正式登录接口的其他会话能读取。
        user_id = user.id  # 保存数据库生成编号，后续核对响应身份。
    try:  # 包围测试执行，保证失败用例也执行受控回收。
        yield PostgresEnvironment(settings, engine, user_id, postgres_password_hash)  # 把同一配置、引擎和身份放进冻结容器交给用例。
    finally:  # 无论断言或请求是否成功，都进入限定目标清理。
        _clear_test_rows(engine, database_name)  # 再次验证专用库后删除测试行，不操作其他库数据。


def test_postgres_migration_matches_models(postgres_environment: PostgresEnvironment) -> None:  # 核对 PostgreSQL 真实类型、表、索引和迁移版本。
    """作用：真实 PostgreSQL 的类型、索引和模型必须一致，不能由 SQLite 结果代替。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：SQLite 无法证明 PostgreSQL 的类型、索引和带时区返回值；实际方言、版本号和模型差异都核对后，才可判断正式数据库结构已经正确建立。
    """
    engine = postgres_environment.engine  # 从测试容器取已验证引擎，避免重新解析其他配置。
    assert engine.dialect.name == "postgresql"  # 必须是真实 PostgreSQL 方言，不能用 SQLite 结果代替。
    assert set(inspect(engine).get_table_names()) == TEST_TABLES  # 实际表集合必须精确符合认证结构与版本表约定。
    with engine.connect() as connection:  # 通过真实连接读取结构与版本，避免仅检查 Python 模型。
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []  # 数据库与模型不得有差异，真实方言字段和索引也需要一致。
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261016_01"  # 版本表应记录当前正式迁移号，说明实际执行了对应结构版本。
    with Session(engine) as db:  # 独立读取基础账户，核对真实驱动返回的时间语义。
        user = db.get(User, postgres_environment.user_id)  # 按服务器编号查询当前用例账户。
        assert user is not None  # 账户必须存在，确保时间断言指向真实持久化数据。
        assert user.created_at.tzinfo is not None  # 真实 PostgreSQL 时间必须带时区，防止跨服务器时区含义错乱。


@pytest.mark.parametrize("violation", ["duplicate_account", "invalid_role", "missing_user"])  # 分别覆盖重复账户、非法角色和不存在用户的会话外键。
def test_postgres_rejects_invalid_data(  # 检验绕过接口写库时，真实 PostgreSQL 仍守住最终约束。
    postgres_environment: PostgresEnvironment, violation: str  # 接收专用库环境与本项违规类别，逐项隔离验证。
) -> None:  # 用数据库断言确认拒绝与回滚，不向其他测试返回状态。
    """作用：让真实数据库拒绝重复账号、非法角色和孤立会话，验证最终数据防线。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：测试库方言可能对约束的执行不同；必须让真实 PostgreSQL 拒绝重复账户、非法角色与孤立会话，并确认失败事务未改变基础数据。
    """
    with Session(postgres_environment.engine) as db:  # 建立独立事务，故意非法写入仅影响验证库。
        record: User | AuthSession  # 声明本项记录可能是账户或会话，让两个表共享同一约束测试。
        if violation == "missing_user":  # 不存在用户场景专门构造孤立会话。
            record = AuthSession(  # 创建真实会话模型，模拟绕过业务服务写入。
                token_hash="c" * 64, user_id=uuid4(), expires_at=200, created_at=100  # 随机父用户不存在，固定摘要与时间只服务于约束验证。
            )  # 完成孤立会话样本，等待提交时触发数据库外键。
        else:  # 其他场景构造账户记录，以验证唯一性和角色检查。
            account = TEST_ACCOUNT if violation == "duplicate_account" else "postgres.invalid"  # 重复样本复用基础账户名，非法角色样本使用不同账户避免触发错误约束。
            record = _new_user(account, postgres_environment.password_hash)  # 先构造合法账户，确保非法角色场景只改变目标字段。
            if violation == "invalid_role":  # 仅当本项验证角色限制时修改角色。
                record.role = "root"  # 使用不支持的角色值，触发正式数据库检查约束。
        db.add(record)  # 把样本加入事务，准备真正写入存储层。
        with pytest.raises(IntegrityError):  # 所有违规类别都必须由数据库抛出完整性异常。
            db.commit()  # 提交触发真实约束，不能只靠实例化对象证明数据库保护。
        db.rollback()  # 回滚失败事务，使后续查询可执行并释放数据库状态。
        assert db.scalar(select(func.count()).select_from(User)) == 1  # 基础账户应仍只有一条，失败写入不能留下部分数据。


def test_postgres_deleting_user_cascades_sessions(postgres_environment: PostgresEnvironment) -> None:  # 验证删用户由数据库级联撤销会话，不靠前端主动清理。
    """作用：真实外键应在账户删除时撤销关联会话，防止遗留可用凭证。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：账户删除后的会话清理不能只靠应用内存或某个接口分支；直接向真实库删用户，可以证明外键级联在任何合法删除入口都生效。
    """
    with Session(postgres_environment.engine) as db:  # 在专用库独立事务中准备会话并执行删除。
        db.add(AuthSession(  # 添加真实关联会话，作为级联删除的可观察样本。
            token_hash="d" * 64, user_id=postgres_environment.user_id,  # 摘要关联当前基础用户，保证外键父记录确实存在。
            expires_at=200, created_at=100,  # 固定创建和到期时间，本项聚焦关联删除而非认证有效期。
        ))  # 完成会话对象并加入事务，稍后真正提交。
        db.commit()  # 先提交会话，防止删除断言只是清除了尚未落库对象。
        db.execute(delete(User).where(User.id == postgres_environment.user_id))  # 直接执行用户删除，验证数据库外键自身的级联功能。
        db.commit()  # 提交删除后才核对会话数量，证明撤销持久生效。
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0  # 会话表应为空，不能留下账户已删但凭证仍存的记录。


def test_postgres_session_survives_application_restart_and_logout(  # 用两次独立应用生命周期验证会话持久化与退出撤销。
    postgres_environment: PostgresEnvironment,  # 接收相同真实库配置，重启应用只更换进程内对象。
) -> None:  # 只用公开请求与存储断言验证，不共享客户端内存状态。
    """作用：两次独立应用生命周期验证会话持久化，退出后数据库撤销必须立即生效。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：只用一个应用实例无法区分持久化会话与进程内缓存；两次独立生命周期复用令牌，再检查退出后数据库记录删除，才能证明重启和撤销行为。
    """
    with TestClient(create_app(postgres_environment.settings)) as first_client:  # 首次创建独立应用和客户端，模拟服务启动。
        response = first_client.post(  # 通过正式登录路由建立真实数据库会话。
            "/api/v1/auth/login", json={"account": TEST_ACCOUNT, "password": TEST_PASSWORD}  # 使用基础账户和真实测试密码，不直接插入可用令牌。
        )  # 取得登录响应，之后保留客户端令牌跨应用使用。
        assert response.status_code == 200  # 首次登录必须成功，建立重启验证的有效前提。
        token = response.json()["access_token"]  # 只保存公开原始令牌，测试数据库仍只应保留摘要。
        headers = {"Authorization": f"Bearer {token}"}  # 构造标准认证头，两个应用实例使用同一客户端凭证。
        assert first_client.get("/api/v1/auth/me", headers=headers).status_code == 200  # 首次应用应能用新会话查询当前用户。
    with TestClient(create_app(postgres_environment.settings)) as restarted_client:  # 关闭首个生命周期后创建新应用，模拟服务器重启。
        response = restarted_client.get("/api/v1/auth/me", headers=headers)  # 用原令牌请求新实例，检验认证状态不依赖旧进程内存。
        assert response.status_code == 200  # 新应用仍应接受未到期会话，证明真实数据库持久化。
        assert response.json()["id"] == str(postgres_environment.user_id)  # 重启后身份必须仍绑定原用户，不能复用错账户。
        assert restarted_client.post("/api/v1/auth/logout", headers=headers).status_code == 204  # 通过新实例退出，服务器应立即完成当前会话撤销。
        response = restarted_client.get("/api/v1/auth/me", headers=headers)  # 退出后再用相同令牌请求，检验撤销不是只清理客户端。
        assert response.status_code == 401  # 旧令牌必须被拒绝。
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"  # 拒绝使用统一未认证错误码，不能泄露会话内部状态。
    with Session(postgres_environment.engine) as db:  # 独立读取数据库，核对退出确实删除了持久化记录。
        assert db.get(AuthSession, hash_session_token(token)) is None  # 按令牌摘要查会话应不存在，证明重启实例执行了真实撤销。


def test_postgres_concurrent_failed_logins_persist_count_and_lock(  # 用真实并发请求验证失败计数不会互相覆盖，锁定阈值可靠。
    postgres_environment: PostgresEnvironment,  # 接收专用真实库环境，只有 PostgreSQL 能证明本项行锁行为。
) -> None:  # 通过数据库最终状态判定结果，不用请求数量代替计数验证。
    """作用：五个同时到达的请求不能覆盖失败次数，以真实行锁验证锁定保护。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：多个请求可能同时读取相同失败次数后互相覆盖更新；同步五个真实请求并核对最终计数、锁定期限和零会话，才能证明行锁保护确实有效。
    """
    barrier = Barrier(5)  # 创建五方同步屏障，让五个线程尽量同时进入登录竞争。
    with TestClient(create_app(postgres_environment.settings)) as client:  # 在同一正式应用中并发请求，覆盖共享连接池和独立事务。
        def attempt_login(_attempt: int) -> tuple[int, str]:  # 每个线程执行一次登录，并只返回可公开的状态和错误码。
            """作用：同步起跑制造同账号竞争，返回公开错误码而不输出凭证或连接配置。

            调用位置：test_postgres_concurrent_failed_logins_persist_count_and_lock 中的线程池调用，每线程一次真实登录请求。
            原因：同步起跑让同账户请求真实竞争数据库行，超时防止死等；返回公开状态和错误码便于核对结果，同时避免输出密码或数据库配置。
            """
            barrier.wait(timeout=15)  # 等待五个线程到齐再同时出发，超时防止测试无限挂起。
            response = client.post(  # 通过正式路由提交错误密码，触发真实账户行锁与失败计数。
                "/api/v1/auth/login", json={"account": TEST_ACCOUNT, "password": "Wrong-password"}  # 固定同一账户和错误密码，保证五次争抢同一行状态。
            )  # 得到当前线程实际响应，不在辅助函数中吞掉异常。
            return response.status_code, response.json()["detail"]["code"]  # 返回公开字段供主线程核对，不输出密码、令牌或连接配置。

        with ThreadPoolExecutor(max_workers=5) as executor:  # 启动五个工作线程，与屏障参与方数量保持一致。
            results = list(executor.map(attempt_login, range(5)))  # 等待全部请求结束并收集结果，确保随后读取的是最终提交状态。
        assert results == [(401, "INVALID_CREDENTIALS")] * 5  # 五次都应使用统一失败契约，不能因竞争导致异常或意外成功。
        with Session(postgres_environment.engine) as db:  # 另起事务查询五个并发请求提交后的账户状态。
            user = db.get(User, postgres_environment.user_id)  # 按基础账户编号读取，保证检查的是竞争中的同一记录。
            assert user is not None  # 账户必须仍存在，竞争不能破坏身份记录。
            assert user.failed_login_attempts == 5  # 失败次数必须精确等于五，证明没有更新覆盖造成漏计。
            assert user.locked_until is not None and user.locked_until > int(time.time())  # 锁定期限必须位于未来，证明并发阈值累加实际触发保护。
        locked_response = client.post(  # 达到锁定后再尝试正确密码，验证锁定确实阻止继续登录。
            "/api/v1/auth/login", json={"account": TEST_ACCOUNT, "password": TEST_PASSWORD}  # 使用正确密码排除普通密码错误，拒绝只能来自有效锁定。
        )  # 取得锁定期间请求结果，接下来核对状态与会话。
        assert locked_response.status_code == 401  # 有效锁定期间也必须拒绝正确密码。
        with Session(postgres_environment.engine) as db:  # 独立会话核对锁定请求有没有错误修改状态。
            user = db.get(User, postgres_environment.user_id)  # 读取同一账户，验证锁定期间计数不会被清零。
            assert user is not None and user.failed_login_attempts == 5  # 账户仍在且次数维持五次，正确密码不能绕过锁定清状态。
            assert db.scalar(select(func.count()).select_from(AuthSession)) == 0  # 会话表应为空，所有失败与锁定请求都不能签发登录会话。


def test_postgres_concurrent_account_creation_has_one_winner(  # 用两个独立事务同时创建同账户，验证真实唯一约束仲裁。
    postgres_environment: PostgresEnvironment,  # 接收真实库环境，只在专用验证库构造并发写入。
) -> None:  # 用最终提交结果和记录数量共同判断，不依赖线程执行顺序。
    """作用：两个独立事务同时创建同账号时，数据库唯一约束必须只允许一个提交成功。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：接口预查无法阻止同时通过检查的同名创建；两个独立事务同步提交并验证恰一成功、库中恰一条记录，证明唯一约束完成最终仲裁。
    """
    barrier = Barrier(2)  # 两个线程在提交前同步，让两份插入同时争夺唯一值。
    account = "postgres.concurrent"  # 使用独立的新账户名，避免基础账户干扰并发仲裁。

    def create_same_account(_attempt: int) -> str:  # 每个线程持有自己的事务，返回成功或重复结果。
        """作用：等待两项事务就绪后再提交，让测试覆盖唯一约束的并发仲裁行为。

        调用位置：test_postgres_concurrent_account_creation_has_one_winner 中的线程池调用，每线程一个独立数据库事务。
        原因：每线程必须使用独立会话，否则只会测到共享对象问题；在提交前同步并对唯一冲突回滚，能直接观察真实数据库并发仲裁而不留下失败事务。
        """
        with Session(postgres_environment.engine) as db:  # 每个线程单独建立会话，避免共享会话造成非数据库层错误。
            db.add(_new_user(account, postgres_environment.password_hash))  # 添加同名账户且使用真实摘要，准备真实唯一约束竞争。
            barrier.wait(timeout=15)  # 等待两项事务都准备好再提交，覆盖并发而非顺序重复写。
            try:  # 捕获唯一约束失败，为竞争落败事务提供明确回滚。
                db.commit()  # 尝试真实提交，数据库决定哪个事务先获得唯一值。
            except IntegrityError:  # 只处理预期的完整性冲突，其他问题继续暴露测试失败。
                db.rollback()  # 失败事务必须回滚，释放连接和事务错误状态。
                return "duplicate"  # 返回重复标志，供主线程确认恰有一个失败者。
            return "created"  # 成功提交返回创建标志，不能仅因对象加入会话就算成功。

    with ThreadPoolExecutor(max_workers=2) as executor:  # 启动两个独立工作线程，与同步屏障参与数对应。
        results = list(executor.map(create_same_account, range(2)))  # 等两个事务完成，收集成功和冲突的实际结果。
    assert sorted(results) == ["created", "duplicate"]  # 排序后必须一成功一重复，不能都成功或都失败。
    with Session(postgres_environment.engine) as db:  # 独立读取数据库最终状态，排除返回文字与落库结果不一致。
        assert db.scalar(select(func.count()).select_from(User).where(User.account == account)) == 1  # 同名账户最终只能一条，证明真实唯一约束守住并发数据完整性。
