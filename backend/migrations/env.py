"""Alembic 迁移命令加载的环境，决定连接配置、目标结构及在线或离线执行方式。

此模块不是应用接口；alembic upgrade、downgrade 或 revision 命令通过迁移环境加载它。
导入模型是为了登记元数据，不等同于自动建表。数据库变更只在所选迁移执行时发生。
"""
from alembic import context  # 获取当前迁移命令的配置、事务管理和版本脚本执行入口。

from app.core.config import Settings  # 与应用共用配置读取入口，不在迁移配置内另存真实数据库密码。
from app.db.base import Base  # 获取声明模型共同登记的结构容器，供结构比较和迁移上下文使用。
from app.db.session import create_database_engine  # 与运行时复用驱动、超时和连接参数保护，避免迁移走另一套连接规则。
from app.models import AuthSession, User  # noqa: F401  # 导入虽不直接使用类名，但会登记两张表，避免自动比较误认模型缺失。

config = context.config  # 当前 Alembic 命令持有的配置对象；测试可在 attributes 中注入隔离配置。
target_metadata = Base.metadata  # 已导入模型的目标表结构，revision 自动比较和在线上下文都从此读取。


def _migration_settings() -> Settings:  # 为在线和离线迁移取得同一份已配置数据库地址的设置对象。
    """作用：选择测试注入配置或正常环境配置，并验证迁移目标明确存在。

    调用位置：本文件的 run_migrations_offline 和 run_migrations_online。
    使用原因：迁移必须明确知道目标数据库，不能缺配置时静默改用其他库；测试可通过
    config.attributes 注入隔离设置，避免读取开发库连接并误改真实数据。
    返回 Settings；缺少 database_url 时抛 RuntimeError，中断命令而不执行结构变更。
    这里只读取和验证配置，不建立连接、不输出包含密码的连接地址。
    """
    settings = config.attributes.get("settings")  # 优先读取测试或显式调用方注入的隔离设置。
    if settings is None:  # 正常终端迁移没有注入对象时才读取统一环境配置。
        settings = Settings()  # 使用应用同样的配置加载规则，真实密码仍从本机环境读取。
    if settings.database_url is None:  # 迁移不允许缺少明确数据库目标。
        raise RuntimeError("数据库尚未配置，请设置 FIXFLOW_DATABASE_URL 后执行迁移。")  # 安全提示配置项名称，阻止对未知目标执行迁移。
    return settings  # 将已经验证的配置交给在线连接或离线语句生成流程。


def run_migrations_offline() -> None:  # 处理带 --sql 的离线迁移，只生成可审查语句而不直接执行数据库变更。
    """作用：配置离线迁移上下文，让版本脚本输出目标数据库适用的结构变更语句。

    调用位置：本模块末尾在 context.is_offline_mode 为真时调用，常见入口是
    alembic upgrade head --sql。使用原因：上线前可以审查语句、评估删表风险，
    由受控数据库发布流程执行，而不让每次检查都直接连接并改库。
    无参数和返回值；连接地址只用于选择数据库语法，不建立数据库网络连接。
    context.begin_transaction 在离线模式组织输出的事务边界，run_migrations
    调用已选版本的 upgrade 或 downgrade 输出语句；此流程本身不备份数据。
    """
    settings = _migration_settings()  # 仍需明确目标驱动，保证生成的语法适用于实际 PostgreSQL。
    context.configure(  # 为当前离线命令准备迁移上下文，而不是创建业务请求 Session。
        url=settings.database_url.get_secret_value(),  # 从保密配置取出目标地址，仅供 Alembic 识别数据库方言。
        target_metadata=target_metadata,  # 提供已登记的模型结构，保持在线与离线配置一致。
        literal_binds=True,  # 将可渲染常量直接写入离线语句，使生成脚本不依赖运行时绑定参数。
        dialect_opts={"paramstyle": "named"},  # 使用命名参数形式处理方言选项，符合 Alembic 离线配置惯例。
        compare_type=True,  # 结构比较时纳入列类型差异，减少模型类型变更被忽略的风险。
    )  # 完成离线上下文配置，还没有向数据库发送任何查询。
    with context.begin_transaction():  # 按离线输出模式组织迁移事务起止语句。
        context.run_migrations()  # 执行所选版本的迁移函数，离线模式下只输出结构变更语句。


def run_migrations_online() -> None:  # 处理默认在线迁移命令，连接目标数据库并执行所选版本的结构变化。
    """作用：借用真实数据库连接，配置迁移上下文并显式执行升级或降级版本脚本。

    调用位置：本模块末尾在非离线模式调用，入口包括 alembic upgrade head、
    alembic downgrade 及需要连接比较结构的 revision --autogenerate。
    使用原因：表结构必须通过可追溯版本统一发布，不能让应用每次启动自行猜测并改表。
    create_database_engine 只创建管理器，engine.connect 才实际借连接；
    上下文事务组织当前迁移，失败向外抛异常并按数据库事务能力回滚，不能替代数据备份。
    生命周期：连接上下文结束归还连接，finally 始终 dispose 本次命令的连接池。
    """
    engine = create_database_engine(_migration_settings())  # 验证配置并使用应用同一工厂创建迁移专属引擎。
    if engine is None:  # 保留显式防御检查，迁移决不在没有目标连接管理器时继续。
        raise RuntimeError("数据库尚未配置，无法执行迁移。")  # 中止命令并提示补充配置，避免假装迁移成功。
    try:  # 在线操作无论成功还是异常，都必须释放本次命令创建的引擎。
        with engine.connect() as connection:  # 此处实际向目标库借连接，连接创建或鉴权失败会向外抛错。
            context.configure(  # 将真实连接绑定到当前 Alembic 上下文，版本脚本的 op 操作通过它执行。
                connection=connection,  # 使用当前上下文连接，不另行创建业务请求的数据库 Session。
                target_metadata=target_metadata,  # 提供完整模型预期结构，用于自动比较和迁移环境管理。
                compare_type=True,  # 自动比较结构时检查列类型，防止长度或类型变化未被识别。
            )  # 完成在线上下文配置，后续按迁移命令选择版本执行。
            with context.begin_transaction():  # 组织迁移事务，PostgreSQL 支持的大多数结构变更可在事务内提交或回滚。
                context.run_migrations()  # 根据命令执行版本回调：升级降级调用版本脚本并管理标记，生成候选迁移则比较结构而不升级。
    finally:  # 异常不在此吞掉，只负责释放命令持有的连接池资源。
        engine.dispose()  # 结束迁移专属引擎，不影响另一个应用进程管理的连接池。


if context.is_offline_mode():  # 根据当前 Alembic 命令是否要求离线输出选择执行路径。
    run_migrations_offline()  # 离线只输出语句，便于上线前人工审查。
else:  # 默认在线模式使用配置的真实目标数据库。
    run_migrations_online()  # 在线迁移连接数据库，按命令执行结构变更或结构比较。
