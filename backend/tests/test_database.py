"""数据库基础测试，由 pytest 自动发现并在临时文件数据库中执行。

作用：验证迁移一致性、存储约束、请求事务回滚、会话隔离和离线语句脱敏。
原因：应用返回成功不能单独证明数据已正确保存；从正式迁移和连接工厂进入，
再用独立会话检查实际结果，可以固定这些保护且不操作开发者数据库。
"""

from collections.abc import Iterator  # 标注夹具生成器返回类型，明确资源在测试后需要回收。
from io import StringIO  # 在内存接收离线建表语句，避免为审查额外生成文件。
from pathlib import Path  # 表示临时目录与迁移配置路径，减少平台差异。
from uuid import uuid4  # 创建不存在的随机用户编号，测试会话外键保护。

import pytest  # 提供夹具、参数化与异常断言，自动检验数据库规则。
from alembic import command  # 执行正式迁移命令，不用测试私自建表替代部署流程。
from alembic.autogenerate import compare_metadata  # 比较真实表结构与模型，发现修改模型却漏写迁移。
from alembic.config import Config  # 加载正式迁移配置，并注入隔离数据库设置。
from alembic.migration import MigrationContext  # 建立迁移比较上下文，让工具读取真实数据库结构。
from fastapi import FastAPI, HTTPException  # 构造真实应用和请求错误，检验会话依赖边界。
from pydantic import ValidationError  # 捕获正式配置校验错误，验证部署不能使用测试文件库。
from sqlalchemy import Engine, delete, func, inspect, select  # 导入引擎、查询和检查工具，核对实际持久化及表结构。
from sqlalchemy.exc import IntegrityError  # 捕获数据库约束异常，证明保护最终由存储层执行。
from sqlalchemy.orm import Session  # 独立管理数据库事务，测试提交、回滚和隔离。
from starlette.requests import Request  # 构造正式请求对象，覆盖依赖读取应用状态的真实路径。

from app.core.config import BACKEND_ROOT, Settings  # 读取项目迁移路径和设置类型，复用正式配置约定。
from app.db.base import Base  # 获取全部正式模型的结构信息，作为迁移一致性基准。
from app.db.session import create_database_engine, get_db  # 复用正式引擎工厂和请求依赖，不在测试中另写连接管理。
from app.models import AuthSession, User  # 使用正式用户和会话模型，覆盖其字段、索引和约束。


def _migration_config(settings: Settings) -> Config:  # 集中生成迁移配置，避免各用例错误读取开发者数据库。
    """作用：把测试配置直接交给迁移入口，避免读取或修改开发者的真实连接配置。

    调用位置：migrated_database 夹具、离线迁移测试及缺配置测试复用。
    原因：迁移程序通常会自行读取配置；直接传入测试设置可防止它误读 .env 连接开发库，也使夹具和离线生成复用完全相同的入口。
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))  # 加载项目实际迁移入口，保证验证部署使用的文件。
    config.attributes["settings"] = settings  # 显式注入测试设置，迁移不得改读真实 .env。
    return config  # 返回配置供夹具和离线迁移测试复用。


def _user(account: str = "database-test") -> User:  # 构造最小账户样本，聚焦数据库约束而非密码算法。
    """作用：构造仅供数据库约束验证的账户，测试不会生成或使用真实登录凭据。

    调用位置：账户默认值、检查约束、外键级联和回滚测试使用；只创建测试样本。
    原因：约束测试不需要登录算法；最小固定样本能让失败只指向唯一性、字段限制或事务行为，而不是密码强度等无关条件。
    """
    return User(account=account, display_name="数据库测试", password_hash="test-only-hash")  # 使用固定占位摘要；该样本只测试存储，不允许真实登录。


def _request(engine: Engine | None) -> Request:  # 构造带应用状态的请求，直接驱动正式会话依赖。
    """作用：提供真实请求对象，使会话依赖测试覆盖应用状态读取而无需启动服务器。

    调用位置：缺数据库、请求回滚和请求会话隔离测试调用，供正式 get_db 依赖读取。
    原因：数据库会话依赖从请求的应用状态取引擎；真实请求对象可以覆盖这个读取路径，无需为会话管理测试额外启动服务器。
    """
    application = FastAPI()  # 创建独立应用对象，不启动网络服务或生产实例。
    application.state.db_engine = engine  # 把待验证引擎放入正式状态字段，模拟应用启动后状态。
    return Request({"type": "http", "app": application})  # 返回真实请求对象，保证依赖读取路径与实际一致。


@pytest.fixture  # 注册已迁移数据库夹具，为每项用例隔离结构与数据。
def migrated_database(tmp_path: Path) -> Iterator[tuple[Engine, Config]]:  # 提供引擎和迁移配置，并在测试后回收连接。
    """作用：每项测试只迁移自己的临时文件，任何测试失败都不会修改用户数据库。

    调用位置：本文件请求 migrated_database 参数的测试使用；pytest 每项创建独立临时目录。
    原因：每项测试会新增、删除或回退结构，因此必须隔离文件数据库；使用正式迁移准备并最终释放引擎，能兼顾部署一致性与资源安全。
    """
    settings = Settings(  # 构造测试专用设置，随后按正式迁移流程准备结构。
        _env_file=None,  # 禁止读取本机 .env，避免误连开发者数据库。
        environment="test",  # 显式测试环境才允许临时 SQLite 文件库。
        database_url=f"sqlite:///{(tmp_path / 'database.sqlite').as_posix()}",  # 使用本用例临时文件，失败不会修改真实用户数据。
    )  # 完成临时配置，不共享其他用例数据库。
    config = _migration_config(settings)  # 通过辅助函数注入配置，统一避免私人连接混入。
    command.upgrade(config, "head")  # 真实升级全部迁移，检验正式建表文件可执行。
    engine = create_database_engine(settings)  # 用项目工厂建立引擎，覆盖正式连接初始化规则。
    assert engine is not None  # 确保配置确实生成了可用引擎，避免后续断言无效。
    try:  # 开始资源保护区，无论测试成败都需要清理连接。
        yield engine, config  # 把已迁移引擎与配置交给当前测试执行。
    finally:  # 测试返回或抛错后都执行连接清理。
        engine.dispose()  # 释放连接池，避免临时文件被连接占用。


def test_unconfigured_database_is_explicitly_unavailable() -> None:  # 验证缺配置明确拒绝业务，而非静默创建备用库。
    """作用：缺配置不能偷偷降级到本地数据库，调用业务接口应获得稳定且无密钥的错误。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：缺连接时静默改用本地库会让应用写错存储并丢失数据；必须明确返回缺配置错误，而不是制造表面上正常的业务状态。
    """
    settings = Settings(_env_file=None, database_url=None)  # 显式构造没有连接地址的设置，隔离本机环境文件。
    assert create_database_engine(settings) is None  # 工厂不能悄悄创建本地数据库来掩盖配置缺失。
    with pytest.raises(HTTPException) as failure:  # 预期依赖产生正式请求异常，不能只测试空值返回。
        next(get_db(_request(None)))  # 驱动生成器获取会话，模拟路由依赖进入阶段。
    assert failure.value.status_code == 503  # 缺配置对应服务不可用状态，便于调用方识别问题。
    assert failure.value.detail["code"] == "DATABASE_NOT_CONFIGURED"  # 固定可操作的缺配置错误码，且无需暴露任何连接信息。


def test_sqlite_cannot_be_a_deployment_database() -> None:  # 验证开发和生产均不能采用测试文件数据库。
    """作用：防止测试便利性扩散到开发和上线配置，确保部署始终按 PostgreSQL 验证。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：SQLite 和 PostgreSQL 的锁、类型及运维方式不同；隔离测试的便利条件不能成为开发或生产中的隐式替代方案。
    """
    for environment in ("development", "production"):  # 分别覆盖两个非测试运行环境。
        with pytest.raises(ValidationError, match="SQLite 仅允许隔离测试"):  # 要求异常同时说明 SQLite 仅限隔离测试，帮助定位误配。
            Settings(_env_file=None, environment=environment, database_url="sqlite:///:memory:")  # 尝试内存文件库，验证限制由正式配置层执行。


def test_migration_matches_models(migrated_database: tuple[Engine, Config]) -> None:  # 比较迁移结果与模型，防止代码结构和数据库结构漂移。
    """作用：比较实际建表结果与模型，及时发现只改模型却遗漏迁移的结构差异。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：只改模型不会自动更改已经部署的数据库；比较真实迁移结果和全部模型元数据，可及时发现漏列、漏索引和类型漂移。
    """
    engine, _ = migrated_database  # 从夹具取得引擎，本项不需要修改迁移配置。
    inspector = inspect(engine)  # 创建结构检查器，读取实际表名与索引。
    assert set(inspector.get_table_names()) == {"users", "auth_sessions", "alembic_version"}  # 正式账户表、会话表和迁移版本表必须全部存在。
    assert {index["name"] for index in inspector.get_indexes("auth_sessions")} == {  # 核对会话索引集合，避免查询与清理依赖的索引丢失。
        "ix_auth_sessions_user_id", "ix_auth_sessions_expires_at"  # 用户查询索引与到期清理索引都应由迁移建立。
    }  # 完成索引集合精确比较，避免只验证表存在。
    with engine.connect() as connection:  # 以真实连接创建比较上下文，读取迁移后的实际结构。
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []  # 模型与实际结构差异必须为空，发现遗漏立即报错。


def test_account_uniqueness_and_default_values(migrated_database: tuple[Engine, Config]) -> None:  # 验证数据库唯一性最终兜底，并核对账户安全默认值。
    """作用：账户唯一性由数据库最终兜底，不能只依赖可能并发执行的接口查询。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：并发请求都可能在预查时看不到同名账户，因此唯一性必须由数据库最终保证；默认普通角色和零失败次数也影响安全初始状态。
    """
    engine, _ = migrated_database  # 仅取已迁移引擎，保持测试聚焦账户写入。
    with Session(engine) as session:  # 在独立事务中验证新增与重复写入。
        user = _user()  # 通过辅助函数创建最小账户，避免无关字段差异。
        session.add(user)  # 将账户纳入事务，准备实际持久化。
        session.commit()  # 提交后才验证默认值，避免只看到 Python 初始对象。
        assert user.id is not None  # 数据库应为账户生成有效编号。
        assert user.role == "user"  # 未指定角色时必须是普通用户，不能默认提升权限。
        assert user.is_active is True  # 账户默认启用状态应与模型约定一致。
        assert user.failed_login_attempts == 0  # 新账户失败次数应从零开始，不能继承其他记录。
        assert user.locked_until is None  # 新账户不应带有锁定期限。
        assert user.created_at is not None  # 创建时间必须存在，便于后续审计与排序。
        session.add(_user())  # 再次创建相同账户，刻意触发唯一约束。
        with pytest.raises(IntegrityError):  # 数据库层应抛出完整性异常，不能靠接口预查代替。
            session.commit()  # 提交重复记录，确保约束在真正写入时生效。
        session.rollback()  # 异常后回滚事务，释放失败状态并恢复会话可查询。
        assert session.scalar(select(func.count()).select_from(User)) == 1  # 数据库最终只应有第一条账户，避免部分重复写入。


@pytest.mark.parametrize("field,value", [("role", "root"), ("failed_login_attempts", -1)])  # 分别测试非法角色与负失败次数两类检查约束。
def test_user_check_constraints(  # 验证绕过接口直接写库时仍不能保存非法账户状态。
    migrated_database: tuple[Engine, Config], field: str, value: str | int  # 接收临时引擎和本项非法字段样本，复用同一验证过程。
) -> None:  # 本用例只用断言判定约束，不返回共享数据库状态。
    """作用：拒绝非法角色和负数失败次数，避免绕过接口后写入无法解释的账户状态。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：脚本或后续维护功能可能绕过接口输入模型；数据库本身也应拒绝非法角色和负计数，避免出现应用无法解释的持久化状态。
    """
    engine, _ = migrated_database  # 取得隔离引擎，确保故意非法写入不会影响开发数据。
    with Session(engine) as session:  # 创建独立事务，检查异常后的回滚路径。
        user = _user()  # 先构造合法账户，再只修改需要验证的字段。
        setattr(user, field, value)  # 按参数设置非法值，保证每项只覆盖一个约束。
        session.add(user)  # 将非法对象加入事务，模拟绕过接口的写入。
        with pytest.raises(IntegrityError):  # 要求存储层拒绝非法值，证明最终数据防线有效。
            session.commit()  # 实际提交才能触发数据库检查，不能只实例化模型。
        session.rollback()  # 回滚失败事务，避免连接留在失败状态影响清理。


def test_session_foreign_key_and_cascade(migrated_database: tuple[Engine, Config]) -> None:  # 验证外键拒绝孤立会话，并在删用户时级联撤销会话。
    """作用：会话必须属于现存用户，删除账户时同步清理令牌，避免留下孤立登录状态。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：没有父账户的会话无法可靠验证身份，删除账户后遗留会话又会造成撤销不完整；外键与级联删除必须由真实提交结果证明。
    """
    engine, _ = migrated_database  # 取得本用例已迁移引擎，外键设置使用正式工厂规则。
    with Session(engine) as session:  # 在独立事务中先验证不存在用户，再验证合法关联删除。
        session.add(AuthSession(token_hash="a" * 64, user_id=uuid4(), expires_at=200, created_at=100))  # 用随机不存在用户构造会话，刻意触发外键约束。
        with pytest.raises(IntegrityError):  # 数据库必须拒绝没有账户归属的会话记录。
            session.commit()  # 提交触发真实外键校验，不依赖 Python 对象检查。
        session.rollback()  # 回滚非法样本，为后续合法关联准备干净事务。
        user = _user()  # 创建真实父账户，覆盖合法会话所需的基础条件。
        session.add(user)  # 把账户加入事务，接下来取得真实数据库编号。
        session.flush()  # 先写出账户但不独立提交，让会话可以引用其编号。
        session.add(AuthSession(token_hash="b" * 64, user_id=user.id, expires_at=200, created_at=100))  # 创建合法关联会话，与前面的孤立会话形成对照。
        session.commit()  # 提交账户和会话，使接下来的删除行为作用于真实存量。
        session.execute(delete(User).where(User.id == user.id))  # 直接删除账户，检验数据库外键级联而非应用手动清理。
        session.commit()  # 提交删除，确认撤销行为持久生效。
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0  # 账户删除后关联会话必须全部消失，不能留下孤立登录状态。


def test_request_failure_rolls_back(migrated_database: tuple[Engine, Config]) -> None:  # 验证请求执行中途失败时，未提交变更必须整体回滚。
    """作用：请求中途失败后不能遗留半条业务记录，下一请求应看到失败前的数据。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：请求可能在已写出部分数据后失败；把异常抛回依赖生成器再用新会话查询，才能证明失败事务已整体撤销而非仅清空内存对象。
    """
    engine, _ = migrated_database  # 取得已迁移引擎，构造真实请求会话依赖。
    dependency = get_db(_request(engine))  # 建立依赖生成器，模拟框架准备请求数据库会话。
    session = next(dependency)  # 驱动到产出点，取得当前请求专用会话。
    session.add(_user())  # 加入账户样本，模拟业务已经开始写入。
    session.flush()  # 把写入送到数据库但不提交，确保回滚确实有变更可撤销。
    with pytest.raises(RuntimeError, match="模拟业务失败"):  # 要求原业务异常继续传播，依赖不能吞掉异常伪装成功。
        dependency.throw(RuntimeError("模拟业务失败"))  # 向依赖抛入异常，模拟请求处理失败触发回滚和清理。
    with Session(engine) as verification:  # 另起会话核对持久化状态，避免读取失败事务自身缓存。
        assert verification.scalar(select(func.count()).select_from(User)) == 0  # 失败请求不应留下账户，证明事务完整回滚。


def test_each_request_has_its_own_session(migrated_database: tuple[Engine, Config]) -> None:  # 验证每个请求得到独立可变会话，不会互相回滚事务。
    """作用：请求不能共用可变会话，否则一次回滚可能影响另一个用户的事务。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：连接池可以复用底层连接，但请求不能共享可变会话；共享会话会让一个用户的提交或回滚影响另一请求的事务状态。
    """
    engine, _ = migrated_database  # 取得隔离引擎，两个请求可共享连接池但不能共享会话。
    first = get_db(_request(engine))  # 创建第一个请求的依赖生成器。
    second = get_db(_request(engine))  # 创建第二个独立请求的依赖生成器。
    try:  # 保护两个生成器，无论断言成败都要关闭资源。
        assert next(first) is not next(second)  # 两个生成器产出的会话对象必须不同，保证事务状态隔离。
    finally:  # 断言后统一清理请求依赖，避免连接泄露。
        first.close()  # 关闭第一个生成器，执行其会话清理。
        second.close()  # 关闭第二个生成器，同样保证资源回收。


def test_migration_can_downgrade(migrated_database: tuple[Engine, Config]) -> None:  # 在隔离库验证迁移回退顺序，不对真实数据执行删除。
    """作用：在空的隔离数据库验证回退顺序，不对真实账户数据执行删除操作。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：迁移回退有外键删除顺序等约束，只有实际执行才能发现问题；本项仅在空的隔离测试库验证，不应直接用于删除真实业务记录。
    """
    engine, config = migrated_database  # 同时取得引擎和配置，让回退与检查指向同一临时库。
    command.downgrade(config, "base")  # 回到迁移起点，验证降级文件中的删除顺序可执行。
    assert inspect(engine).get_table_names() == ["alembic_version"]  # 业务表应被移除，只保留版本管理表。


def test_offline_postgresql_migration_does_not_expose_connection() -> None:  # 验证无需真实连接也能生成可审查的 PostgreSQL 建表语句。
    """作用：无需连接 PostgreSQL 即可审查生产建表语句，输出中不得出现数据库密码。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：上线前常需要先审查建表语句而不操作服务器；离线模式应正确生成 PostgreSQL 类型和级联规则，同时不把连接密码带入审查材料。
    """
    settings = Settings(  # 构造离线连接设置，只提供方言信息而不会访问地址。
        _env_file=None,  # 隔离本机 .env，避免私人连接信息混入生成过程。
        database_url="postgresql+psycopg://review:do-not-print-this@invalid.example/fixflow",  # 使用虚构主机和固定测试密码，便于核对生成语句是否泄露配置。
    )  # 完成离线设置，后续只生成文本不建立网络连接。
    config = _migration_config(settings)  # 复用注入测试设置的正式迁移配置。
    output = StringIO()  # 创建内存文本缓冲区，捕获待审查建表语句。
    config.output_buffer = output  # 把迁移输出定向到缓冲区，避免无关终端输出。
    command.upgrade(config, "head", sql=True)  # 以 sql=True 离线生成全部迁移语句，绝不实际建表。
    sql = output.getvalue()  # 读取生成结果，逐项核对结构与敏感信息保护。
    assert "CREATE TABLE users" in sql  # 用户表建表语句必须存在，证明业务结构包含在迁移中。
    assert "CREATE TABLE auth_sessions" in sql  # 会话表也必须存在，不能遗漏真实登录所需持久化。
    assert "TIMESTAMP WITH TIME ZONE" in sql  # PostgreSQL 时间字段应保留时区语义，不能用无时区类型代替。
    assert "ON DELETE CASCADE" in sql  # 外键应明确级联删除，保证删账户时撤销关联会话。
    assert "do-not-print-this" not in sql  # 离线输出不得包含配置密码，降低审查材料泄露风险。
    assert "invalid.example" not in sql  # 输出也不得包含内部主机地址，保护连接细节。


def test_migration_requires_configuration() -> None:  # 验证缺连接配置时先拒绝，而不是执行半套迁移。
    """作用：缺少连接地址时在执行任何建表操作前退出，并给出可操作的配置提示。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：迁移缺少目标时不能猜测默认库或只执行部分操作；在真正建表前给出配置变量提示，可避免改错库并减少新手排障成本。
    """
    config = _migration_config(Settings(_env_file=None, database_url=None))  # 注入明确未配置的设置，避免回退到开发者个人连接。
    with pytest.raises(RuntimeError, match="FIXFLOW_DATABASE_URL"):  # 要求异常给出正式环境变量名，便于使用者修正设置。
        command.upgrade(config, "head")  # 执行迁移触发前置检查，缺配置时必须在建表前停止。
