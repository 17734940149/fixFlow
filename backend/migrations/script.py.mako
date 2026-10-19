"""${message}

作用：本模板生成新的迁移版本文件，记录一次可追溯的数据库结构变更。
调用位置：Alembic 的 revision 或 revision --autogenerate 命令读取此模板；
生成后的 upgrade/downgrade 再由 migrations/env.py 调度，而非由登录接口调用。
使用原因：统一版本标记和升级、降级入口，使不同环境按相同历史版本演进结构。
模板只能解释动态片段的入口；生成后应审查实际操作，为每行生成代码补充具体中文
注释，并在执行降级前核对删表、删列与数据丢失影响，不能直接信任自动生成结果。

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from collections.abc import Sequence  # 标注可能涉及多个前置版本的迁移元信息类型。

from alembic import op  # 结构操作由当前 Alembic 上下文决定在线执行或离线输出。
import sqlalchemy as sa  # 提供当前迁移使用的列、数据类型和约束构造器，避免依赖后来改变的业务模型。
## 动态导入入口：imports 可能是多行 Python，保留原片段结构，生成后逐行审查其用途并补注释。
${imports if imports else ""}

revision: str = ${repr(up_revision)}  # 当前生成版本的唯一标识，升级时记录到数据库版本表。
down_revision: str | Sequence[str] | None = ${repr(down_revision)}  # 指向前置版本，Alembic 据此确定迁移先后顺序。
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}  # 保存可选分支标签，多条迁移线并行时区分分支。
depends_on: str | Sequence[str] | None = ${repr(depends_on)}  # 保存可选额外依赖，未指定时无需跨分支前置版本。


def upgrade() -> None:  # Alembic 升级经过当前版本时调用生成的结构变更入口。
    """作用：执行本版本新增的数据库结构变更。

    调用位置：migrations/env.py 的 context.run_migrations 按版本顺序调度。
    使用原因：将建表、改列和索引等结构操作集中到可审查版本，避免应用启动时隐式改库。
    无参数与返回值，连接和事务由迁移环境管理；实际写库或仅输出语句取决于命令模式。
    生成后必须根据下方真实变更补充用途、影响数据与失败处理说明，并逐行注释动态代码。
    """
    # 动态升级片段入口：可能展开为多行结构操作，应在生成版本中逐行确认并补注释。
    ${upgrades if upgrades else "pass  # 本版本没有升级操作，保留合法的空函数主体。"}


def downgrade() -> None:  # Alembic 显式降级越过当前版本时调用，是否丢数据取决于生成的操作。
    """作用：执行本版本对应的反向结构变更。

    调用位置：migrations/env.py 根据显式 downgrade 命令选择并调度版本。
    使用原因：保留可追溯的结构回退入口；结构回退不保证恢复已删数据，必须评估并备份。
    无参数与返回值，连接与事务由迁移环境管理，不提供自动备份或数据恢复。
    生成后必须解释真实删表、删列或恢复操作的顺序、调用条件、风险，并逐行补充注释。
    """
    # 动态降级片段入口：保留生成代码原结构，执行前逐行审查破坏性操作并补注释。
    ${downgrades if downgrades else "pass  # 本版本没有降级操作，保留合法的空函数主体。"}
