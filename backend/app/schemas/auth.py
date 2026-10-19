"""认证请求与公开返回字段的模型边界。

作用：校验登录输入、规范化账号，并明确用户与登录响应允许公开的字段。
调用位置：认证路由声明请求体和响应模型，登录服务构造成功响应时也使用这些模型。
原因：数据库模型包含密码摘要等内部字段，不能直接作为接口输出；输入也不能夹带角色。
"""

from typing import Literal  # 限制角色和凭证类型取值，使输出契约与现有认证规则一致。
from uuid import UUID  # 声明用户编号的标准类型，响应时由模型序列化为文本。

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator  # 提供输入输出模型、字段范围、敏感文本包装与账号预处理规则。

from app.core.accounts import normalize_account  # 复用创建用户流程也使用的账号规则，避免创建和登录规范不一致。


class LoginRequest(BaseModel):  # 登录路由使用的请求体模型，框架据此把外部数据转换成受约束对象。
    """作用：只允许客户端提交格式正确的账号与密码。

    调用位置：login 路由的 payload 参数声明本类，FastAPI 调用模型进行请求校验。
    原因：客户端不能通过额外字段指定角色或用户编号；账号规范化必须先于实际数据库查询。
    边界：SecretStr 防止普通对象显示意外露出密码，不等于加密传输或自动保护所有日志。
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)  # 模型框架据此拒绝未声明字段，并避免普通校验错误文本包含原始输入。

    account: str = Field(min_length=3, max_length=64)  # 接收规范化后用于定位用户的账号，并限制合理长度。
    password: SecretStr = Field(min_length=1, max_length=128)  # 接收本次登录密码，不去除空白或改大小写；登录路由仅在调用验证服务时解包。

    @field_validator("account", mode="before")  # 在账号字段标准类型和长度校验之前统一字符串输入形式。
    @classmethod  # 此规则由模型框架通过类调用，不依赖尚未创建的请求实例。
    def normalize_account(cls, value: object) -> object:  # 接收任意原始输入，把字符串交给公共账号规则，其他类型交给模型拒绝或处理。
        """作用：为登录请求调用与创建用户一致的账号规范化逻辑。

        调用位置：构造 LoginRequest 时由 Pydantic 自动执行，路由不需要手工调用。
        原因：同一账号大小写或首尾空白不同不应造成身份不一致，也不能创建后无法登录。
        返回与错误：字符串返回规范化账号；其他值保留供字段校验；格式无效时转换成校验失败。
        """
        return normalize_account(value) if isinstance(value, str) else value  # 这里只处理账号，不处理密码；不合法类型继续由字段类型规则判断。


class UserResponse(BaseModel):  # 登录响应和当前身份接口共用的公开用户模型。
    """作用：限定接口可以公开的用户编号、账号、显示名和角色。

    调用位置：登录服务和 current_user 路由通过 model_validate 从 User 对象读取资料。
    原因：显式列出输出字段，数据库未来增加敏感字段时也不会自动暴露给前端。
    边界：角色用于前端展示和交互判断，实际权限检查仍由服务端依赖执行。
    """

    model_config = ConfigDict(from_attributes=True)  # 允许模型从数据库 User 对象属性读取已声明字段，无需复制整个对象字典。

    id: UUID  # 返回稳定用户编号，供前端识别当前身份而不暴露密码等内部字段。
    account: str  # 返回服务端保存的规范账号，不回显未经校验的请求输入。
    display_name: str = Field(min_length=1, max_length=80)  # 限制公开显示名的长度，与创建用户约束保持一致。
    role: Literal["user", "admin"]  # 只公开当前实现支持的角色名称，不能由登录请求自行赋值。


class LoginResponse(BaseModel):  # 只有成功登录服务构造，登录路由据此约束返回字段。
    """作用：描述成功登录后交给客户端的凭证、有效时长和公开用户资料。

    调用位置：authenticate_user 构造实例；login 的 response_model 用它定义接口契约。
    原因：原始凭证仅在签发时返回一次，后续身份接口不再次暴露，数据库也只存摘要。
    边界：有效时长只说明计划期限，凭证仍可能因退出撤销或用户停用提前失效。
    """

    access_token: str  # 本次登录生成的原始随机凭证，客户端后续放入 Authorization 头使用。
    token_type: Literal["bearer"] = "bearer"  # 明确采用持有者凭证方式；凭证不是携带用户声明的自包含令牌。
    expires_in: int  # 凭证计划有效秒数，数据库 expires_at 决定实际到期检查。
    user: UserResponse  # 嵌套公开用户资料模型，确保不带出数据库中的密码摘要或失败状态。
