"""数据库模型共用的声明基类。

应用查询链：User、AuthSession 继承 Base，数据库会话根据模型映射读写对应表。
迁移建表链：migrations/env.py 导入模型后读取 Base.metadata，识别预期表结构。
本模块只描述结构，不连接数据库，也不会在服务启动时自动创建或修改表。
"""
from sqlalchemy import MetaData  # 引入表结构容器，统一收集模型定义并交给迁移工具比较结构。
from sqlalchemy.orm import DeclarativeBase  # 引入声明式映射基类，让 Python 类可以对应数据库表。


class Base(DeclarativeBase):  # User 和 AuthSession 的共同父类，将模型登记到同一结构集合。
    """作用：为所有业务模型提供共享的表结构容器和约束命名规则。

    调用位置：app/models/user.py、auth_session.py 继承本类；migrations/env.py
    将本类的 metadata 传给 Alembic；数据库测试也用它核对模型与迁移的一致性。
    使用原因：让运行时查询和迁移建表看到同一份结构声明，稳定的约束名称便于后续
    精确修改约束。声明类本身不会执行建表，真实建表由显式迁移命令完成。
    """

    metadata = MetaData(  # 全局共享的结构对象；模型映射在此登记，迁移环境从此读取表和约束。
        naming_convention={  # 约束名称使用稳定模板，避免不同数据库随机取名影响迁移识别。
            "ix": "ix_%(table_name)s_%(column_0_name)s",  # 普通索引按表名和首列命名，方便定位查询加速结构。
            "uq": "uq_%(table_name)s_%(column_0_name)s",  # 唯一约束按表名和首列命名，例如账号不可重复。
            "ck": "ck_%(table_name)s_%(constraint_name)s",  # 检查约束保留显式业务名称，例如角色只能取允许值。
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # 外键标明来源表、列和目标表，方便追溯依赖。
            "pk": "pk_%(table_name)s",  # 主键约束按表命名，迁移修改主键时可以准确找到它。
        }  # 收束命名规则字典，所有继承 Base 的模型使用同一规则。
    )  # 完成结构容器声明；此时尚未与数据库建立连接。
