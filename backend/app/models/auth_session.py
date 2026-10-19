"""登录凭证表映射，用于鉴权、退出撤销以及清理过期凭证，不是数据库连接会话。"""
from uuid import UUID  # 与 User.id 使用相同的唯一标识类型，保证登录凭证可以可靠关联用户。

from sqlalchemy import BigInteger, ForeignKey, String, Uuid  # 提供时间戳、哈希列、用户标识类型以及表间外键依赖。
from sqlalchemy.orm import Mapped, mapped_column  # 将带类型的属性登记为数据库列，供查询映射与迁移比较共同使用。

from app.db.base import Base  # 共享 users 与 auth_sessions 的结构容器，便于建立外键并统一迁移。


class AuthSession(Base):  # 一个实例代表一次可撤销的用户登录凭证，而不是 SQLAlchemy Session 工作会话。
    """作用：将登录令牌摘要、所属用户和有效期持久保存到 auth_sessions 表。

    调用位置：app/services/auth.py 登录成功时新增、退出时删除；
    app/api/dependencies.py 根据收到令牌的摘要联合 User 查询有效身份；app/cli.py
    的 cleanup-sessions 删除已过期记录；app/db/health.py 核对必要表存在。
    迁移链：migrations/env.py 导入模型后将本类登记的表、外键和索引交给 Alembic 比较；
    真正建表由版本脚本 upgrade 执行，导入本类不会执行数据库语句。
    使用原因：服务端保存状态可立即撤销单个凭证，停用用户也能在下次鉴权生效；仅保存
    令牌的单向哈希，读到数据库记录的人无法直接把摘要当成原始令牌访问接口。
    生命周期：登录创建，鉴权读取，到期后不再认可；退出主动删除，过期清理由命令显式
    执行。模型本身不负责自动定时清理，也不控制数据库网络连接的生命周期。
    """

    __tablename__ = "auth_sessions"  # 登录及鉴权查询使用此表名，迁移元数据也按此名称生成结构差异。

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # 保存令牌的 64 字符 SHA-256 摘要作为查询主键；迁移创建对应主键，原始令牌不落库。
    user_id: Mapped[UUID] = mapped_column(  # 登录创建时关联用户，鉴权联合查询使用它；迁移建立同类型列、外键和索引。
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True  # 删除用户时数据库级联删除凭证，索引帮助按用户关联查询。
    )  # 完成用户关联字段；数据库外键还能拒绝不存在的用户标识。
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)  # 鉴权拒绝已到期凭证，清理命令按此时间筛选；迁移建立索引以支持时间范围删除。
    created_at: Mapped[int] = mapped_column(BigInteger)  # 登录服务填入创建时间戳，保留凭证产生时间；迁移建立持久保存该值的大整数列。
