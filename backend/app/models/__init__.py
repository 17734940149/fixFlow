"""业务数据模型的公共导入入口。

作用：集中导出用户与登录凭证映射，并在导入时把两张表登记到 Base.metadata。
调用位置：登录服务、鉴权依赖、数据库检查、管理命令和迁移环境从 app.models 导入。
使用原因：迁移环境必须导入所有模型，元数据才能包含完整结构；集中入口减少遗漏。
这里仅声明并登记表结构，不连接数据库、不建表，也不创建默认网站账号。
"""
from app.models.auth_session import AuthSession  # 导出登录凭证模型，同时将 auth_sessions 结构登记到共享元数据。
from app.models.user import User  # 导出用户模型，同时登记被登录凭证外键引用的 users 结构。

__all__ = ["AuthSession", "User"]  # 声明本包的公开模型名称，供调用方识别稳定导入边界。
