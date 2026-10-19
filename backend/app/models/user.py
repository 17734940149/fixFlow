"""用户表的运行时映射；真实建表语句位于 migrations/versions/20261016_01_users_auth_sessions.py。"""
from datetime import datetime  # created_at 使用带时区的日期时间类型，便于统一记录账号建立时间。
from uuid import UUID, uuid4  # UUID 标注全局唯一标识类型，uuid4 在新增用户时生成随机主键。

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, Uuid, func, true  # 提供列类型、数据库约束和服务器默认值表达式。
from sqlalchemy.orm import Mapped, mapped_column  # Mapped 标注模型属性类型，mapped_column 将属性声明为数据库列。

from app.db.base import Base  # 继承公共结构容器，确保查询映射和迁移读取的是同一份预期模型。


class User(Base):  # 一个实例对应 users 表的一条记录，作为账号和登录保护状态的持久载体。
    """作用：声明用户身份、密码哈希、角色、启停状态与失败锁定状态的数据库映射。

    调用位置：app/cli.py 创建用户；app/services/auth.py 查询并锁定用户行、验证密码、
    更新失败次数与锁定时间；app/api/dependencies.py 联合登录凭证验证有效用户；
    app/db/health.py 查询表是否存在。migrations/env.py 导入本类后读取 Base.metadata。
    使用原因：把数据规则映射为同一模型，避免业务直接拼接数据库语句；账号唯一、角色
    合法和失败次数非负还由数据库约束兜底，不能只依赖路由参数验证。
    字段声明只定义结构。建表由迁移 upgrade 完成，真正写数据由 Session.add/commit 完成。
    实例不包含数据库连接密码；password_hash 是应用登录密码的不可逆派生值，不能直接
    拿来连接 PostgreSQL。数据库账号与本模型表示的网站账号是两套独立账号体系。
    """

    __tablename__ = "users"  # 运行时查询使用此表名；导入模型后该名称同时登记到迁移元数据。
    __table_args__ = (  # 声明由迁移落地的表级约束，运行时写入必须满足数据库规则。
        CheckConstraint("role IN ('user', 'admin')", name="role_valid"),  # 数据库阻止未知角色，管理员依赖只在合法角色集合内判断。
        CheckConstraint("failed_login_attempts >= 0", name="login_attempts_nonnegative"),  # 数据库防止出现负失败次数，维护登录锁定状态的基本有效性。
    )  # 约束被 Base.metadata 收集；该声明本身不会更改已建好的数据库表。

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)  # 创建用户时生成随机唯一标识，鉴权返回及 AuthSession 外键都用它关联用户；迁移建立主键。
    account: Mapped[str] = mapped_column(String(64), unique=True)  # 命令行和登录服务使用规范化账号；数据库唯一约束防止并发创建重复账号，迁移读取长度与约束。
    display_name: Mapped[str] = mapped_column(String(80))  # 命令行保存显示名，当前用户响应读取它；列长度也进入迁移结构比较。
    password_hash: Mapped[str] = mapped_column(String(255))  # 创建账号保存 Argon2 密码哈希，登录服务读取验证；迁移只建立列，当前未实现摘要参数升级，不保存明文密码。
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")  # 创建用户默认普通角色，管理员依赖读取角色；应用默认和迁移中的服务器默认共同保持默认规则。
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # 登录和每次鉴权都检查启用状态，停用后旧令牌也不能继续访问；迁移声明布尔列及默认值。
    failed_login_attempts: Mapped[int] = mapped_column(default=0, server_default="0")  # 登录失败时在被锁定的用户行内递增，成功时清零；迁移建立非负检查和初始值。
    locked_until: Mapped[int | None] = mapped_column(BigInteger)  # 登录服务保存锁定截止的时间戳，None 表示未锁定；迁移声明可空大整数以保存时间值。
    created_at: Mapped[datetime] = mapped_column(  # 账号创建时间由数据库提供，避免依赖客户端传值；迁移读取该服务器默认表达式。
        DateTime(timezone=True), server_default=func.now()  # 带时区日期列与数据库当前时间默认值，便于在不同时区部署时解释记录。
    )  # 完成创建时间映射；真正插入用户时才由数据库填充默认值。
