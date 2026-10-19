"""建立用户和登录凭证表，业务结构必须通过迁移显式创建。

作用：保存本次建表的固定历史版本，而不是每次运行都按最新模型临时猜测结构。
调用位置：migrations/env.py 运行 context.run_migrations 后，由 Alembic 根据版本链
调用 upgrade 或 downgrade。应用登录接口不会调用本版本文件。
使用原因：让新开发环境与正式环境按同样顺序获得 users、auth_sessions 及其约束。
升级不创建默认网站账号；降级会删除账号与登录凭证数据，必须明确评估和备份后执行。

Revision ID: 20261016_01
Revises:
Create Date: 2026-10-16
"""
from collections.abc import Sequence  # 版本标记允许字符串序列，用于表达多分支或依赖关系的类型。

from alembic import op  # 取得当前迁移上下文中的结构操作入口，在线执行或离线输出由环境决定。
import sqlalchemy as sa  # 用稳定的列和约束类型构建本版本结构，不导入可能随业务变化的模型定义。

revision: str = "20261016_01"  # 本迁移的唯一版本号，Alembic 将其记入版本表以判断环境已执行到哪里。
down_revision: str | Sequence[str] | None = None  # 没有上一个版本，表明这是当前项目迁移链的起点。
branch_labels: str | Sequence[str] | None = None  # 当前没有命名迁移分支，保留 Alembic 标准元信息结构。
depends_on: str | Sequence[str] | None = None  # 当前没有额外跨分支依赖，执行顺序由 down_revision 链决定。


def upgrade() -> None:  # Alembic 升级经过本版本时调用，按依赖顺序创建两张业务表及索引。
    """作用：创建用户表、登录凭证表及主键、唯一、检查、外键和查询索引。

    调用位置：alembic upgrade 经 migrations/env.py 的迁移上下文调度，不由业务路由调用。
    使用原因：登录凭证的 user_id 依赖 users.id，必须先建用户表再建凭证表；约束从
    第一版起就生效，数据库可拒绝重复账号、非法角色或不存在的用户引用。
    无参数及返回值，结构操作使用当前 Alembic 连接；离线模式只生成语句。
    本函数不创建管理员、不写入真实密码、不代替应用运行时的模型和登录服务。
    """
    op.create_table(  # 先建立被其他表引用的用户表，结构必须与当前 User 模型版本相符。
        "users",  # 对应 app/models/user.py 的 __tablename__，运行时查询使用同名表。
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),  # 用户唯一标识列，不允许空值；随机默认值由运行时 User 模型生成。
        sa.Column("account", sa.String(length=64), nullable=False),  # 保存规范化登录账号，长度与创建用户及登录校验规则相配合。
        sa.Column("display_name", sa.String(length=80), nullable=False),  # 保存向前端展示的用户名称，不可为空。
        sa.Column("password_hash", sa.String(length=255), nullable=False),  # 只保存应用密码的哈希文本，不保存明文或数据库连接密码。
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),  # 数据库缺省普通用户，后续检查约束限制角色值。
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),  # 账号默认启用，登录和鉴权读取该状态决定是否允许访问。
        sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False),  # 持久保存连续失败次数，初始为零以支持登录锁定保护。
        sa.Column("locked_until", sa.BigInteger(), nullable=True),  # 保存锁定截止时间戳，可空表示当前未设置锁定时间。
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # 由数据库生成带时区的账号创建时间，避免依赖客户端提供。
        sa.CheckConstraint("role IN ('user', 'admin')", name=op.f("ck_users_role_valid")),  # 数据库拒绝其他角色，固定约束名方便未来迁移修改。
        sa.CheckConstraint("failed_login_attempts >= 0", name=op.f("ck_users_login_attempts_nonnegative")),  # 防止失败计数变为负数，维护登录保护状态基本规则。
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),  # 用户主键为外键关联和按标识查询提供唯一依据。
        sa.UniqueConstraint("account", name=op.f("uq_users_account")),  # 在数据库层阻止并发操作创建重复账号，优于只做先查后写检查。
    )  # 完成用户表结构创建或离线语句生成，尚不插入任何网站账号。
    op.create_table(  # 用户表存在后，再建立依赖 users.id 的登录凭证表。
        "auth_sessions",  # 对应 app/models/auth_session.py 的表名，登录、鉴权和退出都访问它。
        sa.Column("token_hash", sa.String(length=64), nullable=False),  # 保存 SHA-256 令牌摘要，数据库泄露时不能把摘要直接当令牌使用。
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),  # 保存所属用户标识，列类型与 users.id 保持一致。
        sa.Column("expires_at", sa.BigInteger(), nullable=False),  # 保存有效期截止时间戳，鉴权和清理命令均读取该字段。
        sa.Column("created_at", sa.BigInteger(), nullable=False),  # 保存登录凭证建立时间戳，由登录服务写入。
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users"), ondelete="CASCADE"),  # 拒绝不存在的用户关联，删除用户时级联删除其全部登录凭证。
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_auth_sessions")),  # 令牌摘要作为主键，支持鉴权快速定位并避免重复凭证记录。
    )  # 完成登录凭证表和外键约束，数据仍由登录业务显式写入。
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"])  # 为按用户关联查询建立索引，避免凭证量增大后每次扫描整表。
    op.create_index(op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"])  # 为过期范围查询和清理提供索引，实际收益仍需结合查询计划验证。


def downgrade() -> None:  # Alembic 降级越过本版本时调用，会删除当前两张业务表及全部表内数据。
    """作用：按反向依赖顺序移除本版本建立的索引和表，回到无本版本业务结构的状态。

    调用位置：显式执行 alembic downgrade 到本版本之前时，由迁移环境调度。
    使用原因：版本工具需要结构回退入口，但可回退结构不等于能恢复数据；本函数会删除
    所有网站账号和登录凭证，应在确认影响并备份后才能用于真实环境。
    先删除凭证表再删除用户表，避免外键依赖妨碍操作；无参数和返回值，异常由 Alembic
    向命令行传播。这里未实现自动备份或数据恢复，不能当作日常清理命令使用。
    """
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="auth_sessions")  # 先移除凭证到期时间索引，按与建立相反的顺序回退。
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")  # 移除用户关联索引，随后凭证表将被整体删除。
    op.drop_table("auth_sessions")  # 先删除引用用户表的凭证表，同时永久删除其中的登录状态数据。
    op.drop_table("users")  # 外键来源表已移除，再删除用户表及所有账号、角色和密码哈希数据。
