"""后端配置与维护入口测试，由 pytest 自动发现并执行。

作用：覆盖缺配置、就绪判断、敏感错误保护、交互创建用户和过期会话清理。
原因：维护命令可能写入或删除数据，因此既检查退出结果，也核对真实持久化；
工具调用全部注入隔离库配置，不读取开发者个人数据库。
"""

from pathlib import Path  # 标注临时目录类型，保证测试配置只指向隔离文件。
import time  # 读取当前时间，构造已过期和仍有效的会话。

from alembic import command  # 使用真实迁移命令，覆盖部署必须执行的建表流程。
from alembic.config import Config  # 加载迁移配置对象，注入本项测试的数据库设置。
from fastapi.testclient import TestClient  # 进程内执行正式请求链路，不依赖另行启动的服务器。
from pydantic import ValidationError  # 捕获配置校验异常，验证不允许的数据库类型被拒绝。
import pytest  # 提供夹具、参数化与异常断言，重复验证维护风险。
from sqlalchemy import select  # 构造正式查询语句，检查工具实际写入结果。
from sqlalchemy.exc import SQLAlchemyError  # 模拟数据库异常，验证对外响应保护内部信息。
from sqlalchemy.orm import Session  # 用独立会话读取命令执行后的持久化数据。

from app import cli  # 导入正式终端入口，测试真实建用户和维护命令。
from app.core.config import BACKEND_ROOT, Settings  # 读取项目根路径和设置类型，复用正式迁移位置。
from app.main import create_app  # 使用正式工厂，覆盖中间件和异常处理的整体行为。
from app.models import AuthSession, User  # 复用账户及会话模型，核对落库而非仅检查终端文字。


@pytest.fixture  # 注册设置夹具，为依赖它的测试准备已迁移临时库。
def database_settings(tmp_path: Path) -> Settings:  # 为终端工具测试提供隔离配置，避免操作真实账户。
    """作用：操作临时文件库验证操作工具，避免测试建账号时误连开发者的真实数据库。

    调用位置：本文件请求 database_settings 参数的测试使用；pytest 每项测试独立创建 tmp_path。
    原因：账户创建和会话清理会修改数据，不能借用开发者数据库；每项测试用独立临时文件并执行正式迁移，能安全验证命令与结构是否衔接。
    """
    settings = Settings(  # 创建测试设置，迁移和工具使用同一份配置。
        _env_file=None, environment="test",  # 关闭 .env 读取并声明测试环境，允许隔离文件库。
        database_url=f"sqlite:///{(tmp_path / 'setup.sqlite').as_posix()}",  # 数据库文件位于本项临时目录，不与其他测试共享。
    )  # 完成隔离设置对象，不自动退回个人连接信息。
    migration = Config(str(BACKEND_ROOT / "alembic.ini"))  # 加载项目迁移配置，使建表过程与部署一致。
    migration.attributes["settings"] = settings  # 直接注入测试设置，禁止迁移重新读取开发配置。
    command.upgrade(migration, "head")  # 升级到最新结构，工具调用前必须具备正式业务表。
    return settings  # 返回配置供测试调用工具，避免共享全局连接状态。


def test_missing_database_is_explicit() -> None:  # 区分缺数据库时存活、就绪和登录的行为。
    """作用：保持存活接口兼容，同时明确拒绝未配置数据库时的真实业务请求。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：部署需要分清进程存活和业务可用；缺数据库时存活仍能响应，但就绪和登录必须明确失败，避免把不具备业务能力的实例接入流量。
    """
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:  # 创建明确无数据库配置的应用，覆盖缺配置分支。
        assert client.get("/api/v1/health").status_code == 200  # 存活只说明进程可响应，缺数据库时仍应成功。
        response = client.get("/api/v1/ready")  # 访问就绪入口，核对业务依赖尚未准备好。
        assert response.status_code == 503  # 就绪应返回服务不可用，而不是误报可处理业务。
        assert response.json() == {"status": "not_ready", "database": "not_configured"}  # 响应明确缺配置状态，便于部署与排障定位。
        response = client.post("/api/v1/auth/login", json={"account": "admin", "password": "secret"})  # 调用真实登录路由，防止缺数据库时返回虚假登录结果。
        assert response.status_code == 503  # 登录依赖缺失时应拒绝处理。
        assert response.json()["detail"]["code"] == "DATABASE_NOT_CONFIGURED"  # 固定缺配置业务错误码，方便客户端准确提示。
        assert response.headers["cache-control"] == "no-store"  # 失败登录也禁止缓存，减少敏感响应被保存的风险。


def test_readiness_checks_migrations(tmp_path: Path, database_settings: Settings) -> None:  # 验证能连接和已迁移的区别，防止过早宣告就绪。
    """作用：可建立连接不等于业务表已可用，就绪检查必须区分未迁移与已迁移数据库。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：连接成功只能证明服务器可访问，不能证明业务表已经建立；分别验证空库和已迁移库，能防止未执行迁移的实例被误报为就绪。
    """
    unmigrated = Settings(  # 创建另一个空数据库，覆盖尚未建表的情况。
        _env_file=None, environment="test",  # 隔离个人设置，并只在测试环境使用文件数据库。
        database_url=f"sqlite:///{(tmp_path / 'empty.sqlite').as_posix()}",  # 使用不同临时路径，确保没有夹具准备的业务表。
    )  # 完成空库配置，连接可用但结构尚不具备。
    with TestClient(create_app(unmigrated)) as client:  # 启动空库应用，验证就绪检查确实读取结构状态。
        assert client.get("/api/v1/ready").json()["database"] == "unavailable"  # 未建业务表时必须报告不可用。
    with TestClient(create_app(database_settings)) as client:  # 再启动已迁移库应用，覆盖就绪成功分支。
        assert client.get("/api/v1/ready").json() == {"status": "ready", "database": "ready"}  # 连接与表结构都可用时，才报告业务准备完成。


@pytest.mark.parametrize("environment", ["development", "production"])  # 分别验证开发与生产环境，确保限制无遗漏。
def test_sqlite_is_rejected_outside_tests(environment: str) -> None:  # 确认 SQLite 只用于测试，不成为真实部署存储。
    """作用：测试数据库不能静默进入开发或部署环境，确保实际运行仍必须连接 PostgreSQL。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：测试使用文件数据库是隔离手段，不能静默扩散成正式运行方案；开发与生产都应按 PostgreSQL 的方言、并发和运维条件运行。
    """
    with pytest.raises(ValidationError):  # 正式配置模型应明确抛错，不能静默接受误配。
        Settings(_env_file=None, environment=environment, database_url="sqlite:///local.sqlite")  # 尝试非测试环境的文件库，触发正确拒绝逻辑。


def test_configuration_redacts_connection_password() -> None:  # 检查配置展示和异常文本均保护连接密码。
    """作用：配置展示和错误文本不回显连接密码，降低排查配置时复制日志的泄露风险。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：配置对象和校验异常经常被复制到日志或问题单；即使设置错误也不能显示密码，因此成功展示和失败展示两条路径都必须校验。
    """
    value = "postgresql+psycopg://fixflow:private-password@127.0.0.1/fixflow"  # 固定测试专用密码样本，便于检测输出中是否泄露。
    settings = Settings(_env_file=None, database_url=value)  # 通过真实配置模型解析，覆盖正式展示规则。
    assert "private-password" not in repr(settings)  # 对象表示不能出现连接密码，降低调试信息泄露风险。
    assert Settings(_env_file=None, database_url="").database_url is None  # 空连接值转换成未配置状态，避免创建含糊的空连接。
    with pytest.raises(ValidationError) as error:  # 捕获不支持驱动的异常，覆盖失败路径的脱敏。
        Settings(_env_file=None, database_url="mysql://fixflow:private-password@localhost/fixflow")  # 传入不支持的连接类型，确保真实触发配置失败。
    assert "private-password" not in str(error.value)  # 异常文本也不得回显密码。


def test_database_errors_do_not_expose_driver_details() -> None:  # 验证数据库异常转换成稳定响应，不透传内部细节。
    """作用：驱动异常统一成可恢复错误，客户端不能从响应取得数据库地址、语句或密码。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：驱动错误可能包含连接信息和语句；通过真实异常处理链路验证统一响应，可以避免将内部地址、密码和查询细节直接返回给浏览器。
    """
    application = create_app(Settings(_env_file=None, database_url=None))  # 创建测试实例，模拟错误路由仅在本实例注册。

    @application.get("/test-database-error")  # 注册测试错误路由，不给生产应用添加调试入口。
    def fail_query() -> None:  # 供测试客户端触发异常，检验正式异常处理器。
        """作用：只在测试应用模拟数据库失败，验证异常处理不会透传内部错误内容。

        调用位置：test_database_errors_do_not_expose_driver_details 注册该函数；测试客户端访问 /test-database-error 时调用。
        原因：人为构造含模拟秘密的异常，才能确认真实处理器确实移除了内部细节；仅检查普通数据库失败可能看不到敏感文本泄露风险。
        """
        raise SQLAlchemyError("postgresql://private-password@internal-host private query")  # 抛出含模拟密码和内网主机的错误，检验实际脱敏效果。

    with TestClient(application) as client:  # 进入应用生命周期，让异常经过真实请求处理。
        response = client.get("/test-database-error")  # 请求模拟路由，触发数据库异常转换逻辑。
        assert response.status_code == 503  # 数据库不可用应得到可识别的服务不可用状态。
        assert response.json()["detail"]["code"] == "DATABASE_UNAVAILABLE"  # 客户端只收到稳定业务错误码，不得到驱动原文。
        assert "private-password" not in response.text  # 测试密码不能出现在响应中。
        assert "internal-host" not in response.text  # 内部主机名不能出现在响应中。


def test_cli_creates_user_without_default_password(  # 验证创建账户命令的规范化、权限与密码保护。
    database_settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],  # 接收隔离配置、临时替换和输出捕获夹具，控制数据和交互。
) -> None:  # 以断言判定创建结果，不向其他测试返回可变状态。
    """作用：建账号使用交互密码并拒绝覆盖，避免默认密码和重复执行意外提升账号权限。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：创建管理员是高权限维护动作，不能依赖默认密码或重复命令覆盖旧账户；本项同时验证规范化、明确角色、真实摘要和终端输出保护。
    """
    monkeypatch.setattr(cli, "Settings", lambda: database_settings)  # 替换工具设置为临时库，避免读取真实连接信息。
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "Unique-passphrase-2026")  # 模拟隐藏输入，测试无需交互终端也不使用默认密码。
    arguments = ["create-user", "--account", "Admin", "--display-name", "管理员", "--role", "admin"]  # 以大写账户和明确角色验证规范化及受控创建。
    assert cli.main(arguments) == 0  # 首次创建应成功，说明校验、摘要和写库链路完整。
    assert cli.main(arguments) == 1  # 重复创建应失败，不能覆盖密码或提升已有账户权限。
    assert cli.main(["check-db"]) == 0  # 检查数据库命令应在迁移完成后成功。
    engine = cli.create_database_engine(database_settings)  # 从同一临时配置创建独立引擎，核对实际持久化。
    with Session(engine) as database:  # 新会话读取落库数据，避免看到未提交对象造成误判。
        user = database.scalar(select(User).where(User.account == "admin"))  # 按标准化后的账户名查询，证明规范化发生在保存前。
        assert user.role == "admin"  # 指定管理员角色应实际保存。
        assert user.password_hash.startswith("$argon2id$")  # 数据库密码必须是 Argon2id 摘要格式。
        assert user.password_hash != "Unique-passphrase-2026"  # 摘要不得等于输入密码，防止误存明文。
    engine.dispose()  # 释放验证引擎，避免临时文件仍被连接占用。
    assert "Unique-passphrase-2026" not in capsys.readouterr().out  # 终端输出也不能打印密码，保护日志和录屏内容。


def test_cli_rejects_short_password(database_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:  # 验证弱密码拒绝发生在持久化之前。
    """作用：弱密码不能通过受控操作入口创建，校验失败时数据库中不留下半个账号。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：弱密码必须在保存账户前拒绝；独立查询空表可以发现只返回失败码却已经留下半条账户的事务边界问题。
    """
    monkeypatch.setattr(cli, "Settings", lambda: database_settings)  # 固定工具只连接本项临时库，失败测试也隔离真实数据。
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "short")  # 模拟过短输入，覆盖密码长度边界。
    assert cli.main(["create-user", "--account", "tester", "--display-name", "测试用户"]) == 1  # 创建应返回失败退出码，终端调用者可识别未完成。
    engine = cli.create_database_engine(database_settings)  # 建立独立验证引擎，不仅依赖命令返回码。
    with Session(engine) as database:  # 读取账户表，检查拒绝操作有没有产生部分记录。
        assert database.scalar(select(User.id)) is None  # 弱密码被拒后应没有用户，保证操作完整性。
    engine.dispose()  # 释放验证连接，保持测试资源清理完整。


def test_cli_cleanup_preserves_active_sessions(  # 验证维护任务只清除过期会话，保留有效登录。
    database_settings: Settings, monkeypatch: pytest.MonkeyPatch,  # 接收临时设置和替换夹具，禁止维护操作触及真实库。
) -> None:  # 此用例只核对删除边界，不共享账户状态。
    """作用：清理任务只删除到期凭证，不能因为例行维护让正在使用的登录状态全部失效。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：过期数据需要定期回收，但维护不能把所有用户踢下线；同一库准备到期和未到期对照组，能准确验证删除条件而不只验证任务成功。
    """
    monkeypatch.setattr(cli, "Settings", lambda: database_settings)  # 替换维护工具配置为当前隔离数据库。
    engine = cli.create_database_engine(database_settings)  # 建立用于准备和读取会话的测试引擎。
    now = int(time.time())  # 固定当前秒数，构造一项过期、一项仍有效数据。
    with Session(engine) as database:  # 在同一事务准备账户和会话，保证样本条件一致。
        user = User(account="tester", display_name="测试", password_hash="not-used-in-this-test")  # 构造维护所需账户，占位摘要不会用于真实登录。
        database.add(user)  # 先加入父账户，满足会话外键前置条件。
        database.flush()  # 写出账户并取得编号，暂不独立提交事务。
        database.add_all([  # 批量加入过期与有效样本，形成同一任务的对照组。
            AuthSession(token_hash="a" * 64, user_id=user.id, created_at=now - 100, expires_at=now - 1),  # 到期在当前时间之前，预期应被清理。
            AuthSession(token_hash="b" * 64, user_id=user.id, created_at=now, expires_at=now + 3600),  # 到期在当前时间后一小时，预期必须保留。
        ])  # 完成两类会话样本准备，接下来统一提交。
        database.commit()  # 提交样本，使维护命令的独立会话能够看到它们。
    assert cli.main(["cleanup-sessions"]) == 0  # 执行正式维护入口，要求正确完成清理。
    with Session(engine) as database:  # 重新读取数据库最终状态，避免依赖缓存对象。
        assert list(database.scalars(select(AuthSession.token_hash))) == ["b" * 64]  # 只允许有效摘要留下，同时证明正确删除和未误删。
    engine.dispose()  # 释放引擎，不遗留连接或文件句柄。
