"""环境配置的读取、校验与请求级获取入口。

作用：声明可配置项、默认值和合法范围，并拒绝当前项目不支持的数据库连接格式。
调用位置：应用工厂、数据库引擎工厂、命令行工具、迁移环境和接口配置依赖使用 Settings。
原因：部署环境只需要提供配置，不应通过修改业务代码切换数据库或认证策略。
"""

from pathlib import Path  # 以文件所在位置计算后端根目录，避免启动命令的工作目录影响配置定位。
from typing import Literal  # 限制环境字段只能取声明的名称，拼写错误在启动时即可被发现。

from fastapi import Request  # 请求对象提供当前应用实例，依赖函数从中取得对应配置。
from pydantic import Field, SecretStr, field_validator, model_validator  # 提供数值约束、敏感文本包装，以及字段和整体配置校验入口。
from pydantic_settings import BaseSettings, SettingsConfigDict  # 从环境变量与 .env 读取配置，并将外部文本转换成声明类型。
from sqlalchemy.engine import make_url  # 使用数据库工具的连接地址解析器，避免手工拆分账号密码和地址。
from sqlalchemy.exc import ArgumentError  # 捕获连接地址无法解析的情况，转换成不包含原始凭证的配置错误。

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # Settings.model_config 使用这个根目录定位 .env，避免从其他目录启动时读取错文件。


class Settings(BaseSettings):  # 继承配置模型，使应用启动与测试都使用同一组字段约束。
    """作用：把外部配置转换成有类型、有默认值且经过校验的配置对象。

    调用位置：create_app、创建用户命令与迁移环境创建实例；数据库和登录服务读取其字段。
    原因：集中管理配置可避免多个模块采用不同超时、会话期限或数据库地址。
    规则：显式传入的值优先于环境变量，环境变量优先于 .env，最后才使用字段默认值。
    安全边界：SecretStr 隐藏常规显示中的连接值，但不等于加密配置文件或加密数据库连接。
    """

    model_config = SettingsConfigDict(  # 配置模型读取规则，供 BaseSettings 在创建 Settings 时使用。
        env_prefix="FIXFLOW_",  # 环境变量统一使用项目前缀，减少与机器上其他应用配置重名的机会。
        env_file=BACKEND_ROOT / ".env",  # 从固定后端目录加载本机配置，不依赖当前命令执行目录。
        env_file_encoding="utf-8",  # 统一配置文件编码，避免中文配置在不同机器上解析不同。
        extra="ignore",  # 忽略不属于本模型的配置项，允许同一个文件保留其他本机配置。
        hide_input_in_errors=True,  # 配置校验失败时不在普通错误文本中展示原始输入，降低密码误输出风险。
    )  # 完成配置读取约定，下面声明的字段都按这些规则取值。

    app_name: str = "FixFlow"  # 应用工厂和健康接口共同展示的服务名称。
    app_version: str = "0.1.0"  # 接口文档与健康返回使用的版本，便于核对部署是否更新。
    environment: Literal["development", "test", "production"] = "development"  # 区分运行环境，整体校验仅允许测试环境使用 SQLite。
    docs_enabled: bool = True  # 应用工厂据此同时开启或关闭两个文档页面与接口描述文件。
    cors_origins: tuple[str, ...] = (  # 声明前端获准访问的完整来源列表，供跨域中间件使用。
        "http://localhost:5173",  # 放行使用 localhost 打开的本机前端开发页面。
        "http://127.0.0.1:5173",  # 放行使用环回地址打开的本机前端页面，两种主机名属于不同来源。
    )  # 结束默认来源列表，上线时应通过配置替换为实际前端来源。
    database_url: SecretStr | None = None  # 数据库工厂解包后连接数据库；None 明确表示未配置，不自动创建数据库。
    database_pool_size: int = Field(default=5, ge=1, le=20)  # 限定常驻连接池的目标大小，避免配置错误耗尽数据库连接数。
    database_max_overflow: int = Field(default=5, ge=0, le=20)  # 限制高峰期可额外借用的连接，归还后不作为常驻连接保留。
    database_pool_timeout_seconds: int = Field(default=5, ge=1, le=30)  # 连接池已满时最多等待的秒数，避免请求无限排队。
    database_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)  # 新建数据库连接允许等待的秒数，数据库故障时及时反馈。
    session_ttl_minutes: int = Field(default=60, ge=1, le=1440)  # 登录服务据此生成会话失效时刻，限制凭证可使用的时间范围。
    login_max_attempts: int = Field(default=5, ge=1, le=20)  # 登录服务对单个账号累计失败达到此值后进入锁定。
    login_lock_seconds: int = Field(default=300, ge=1, le=3600)  # 登录服务设置锁定结束时刻使用的秒数，避免持续无限尝试密码。

    @field_validator("database_url", mode="before")  # 在敏感文本类型转换前处理 .env 中可能出现的空字符串。
    @classmethod  # 让配置校验框架通过类调用该规则，不依赖尚未构造完成的实例。
    def empty_database_url_is_unconfigured(cls, value: object) -> object:  # 接收外部原始配置，保留非字符串值供后续类型校验。
        """作用：把空白数据库配置统一转成未配置状态。

        调用位置：Settings 创建时由字段校验器自动执行，不由路由直接调用。
        原因：空字符串不能被误解成某个默认数据库地址，未配置应有清晰的就绪状态。
        返回：空白字符串返回 None；其他值原样交给配置模型继续处理。
        """
        return None if isinstance(value, str) and not value.strip() else value  # 只规范化空值，不擅自修正可能包含密码的完整连接地址。

    @model_validator(mode="after")  # 字段转换完成后，同时检查运行环境与数据库驱动之间的约束。
    def validate_database_driver(self) -> "Settings":  # 返回经整体规则验证的配置实例供应用启动使用。
        """作用：校验连接地址格式，并限制当前项目支持的数据库驱动。

        调用位置：Settings 创建时由配置框架自动执行，先于数据库引擎工厂使用连接地址。
        原因：正式业务使用 PostgreSQL；轻量的 SQLite 仅用于隔离测试，不能无意中替代部署数据库。
        返回与错误：合法或未配置时返回当前对象；不支持或无法解析时抛出 ValueError。
        """
        if self.database_url is None:  # 允许应用以未配置数据库的状态启动，健康与就绪接口会区分这种情况。
            return self  # 未配置时没有驱动可校验，把明确空状态交给数据库工厂处理。
        try:  # 将底层解析错误转换成不带原始连接地址的配置提示。
            url = make_url(self.database_url.get_secret_value())  # 只在必要解析处取得真实连接文本，不把其写入提示或日志。
        except ArgumentError:  # 捕获数据库工具报告的地址格式错误。
            raise ValueError("数据库连接格式不正确，请参照 .env.example。") from None  # 去除原异常链，避免无意输出带凭证的解析细节。
        if url.drivername == "postgresql+psycopg" and url.database:  # 正常运行只接受已实现的 PostgreSQL 驱动且要求明确数据库名。
            return self  # 地址符合当前连接工厂支持范围，允许后续创建引擎。
        if self.environment == "test" and url.drivername == "sqlite":  # 仅显式测试环境允许内嵌数据库，测试无需依赖真实服务器。
            return self  # 保留现有隔离测试入口，不把测试数据库当作生产支持方案。
        raise ValueError("请使用 postgresql+psycopg 连接；SQLite 仅允许隔离测试。")  # 在启动阶段拒绝不受支持的组合，避免运行到接口才发现驱动不匹配。


def get_settings(request: Request) -> Settings:  # 作为接口依赖，从收到请求的那个应用取得配置。
    """作用：向健康和登录接口提供当前应用持有的 Settings。

    调用位置：路由通过 Depends(get_settings) 声明，由 FastAPI 注入请求对象后执行。
    原因：多个测试应用可能采用不同数据库或策略，不能读取一个跨应用共享的全局配置。
    返回：create_app 提前放入 request.app.state.settings 的配置实例。
    """
    return request.app.state.settings  # 不在每次请求重新读取 .env，保持同一应用运行期间配置的一致性。
