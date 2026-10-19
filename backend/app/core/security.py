"""密码保护与随机会话凭证工具。

作用：集中生成与验证密码摘要，以及生成和计算会话凭证摘要。
调用位置：创建用户命令、app.services.auth 登录服务和 app.api.dependencies 身份依赖。
原因：人类密码和高随机性的会话凭证风险不同，应分别使用合适的算法并共享正确实现。
"""

import hashlib  # 使用标准库计算随机会话凭证的单向摘要，数据库只保存摘要值。
import secrets  # 使用适合安全用途的随机数生成器，避免普通伪随机数被预测。

from pwdlib import PasswordHash  # 复用成熟密码工具的推荐算法与参数，避免自行设计密码保护算法。
from pwdlib.exceptions import UnknownHashError  # 识别无法解析的密码摘要，转换为普通校验失败。

PASSWORD_HASH = PasswordHash.recommended()  # 密码工具实例由创建用户与登录校验共同使用，统一推荐的高成本密码算法。
# 未知账号仍执行一次密码校验，减少通过响应耗时判断账号是否存在的差异。
DUMMY_PASSWORD_HASH = PASSWORD_HASH.hash(secrets.token_urlsafe(32))  # 登录服务用启动时生成的虚拟摘要处理未知账号，减少立即返回造成的明显耗时差异。


def hash_password(password: str) -> str:  # 把用户输入的密码转为可保存的单向密码摘要。
    """作用：使用推荐密码算法生成带算法参数与盐值的密码摘要。

    调用位置：app.cli 创建用户时调用；数据库用户记录保存返回值而非明文密码。
    原因：密码通常可被字典猜测，必须用较高计算成本的算法降低泄露后的批量猜测速度。
    参数与返回：接收原始密码，返回供 verify_password 校验的摘要字符串。
    """
    return PASSWORD_HASH.hash(password)  # 交给成熟密码库生成盐值和摘要，避免业务自行维护易出错的算法细节。


def verify_password(password: str, password_hash: str) -> bool:  # 同时支持真实用户摘要和未知账号使用的虚拟摘要。
    """作用：验证输入密码是否与已保存摘要匹配。

    调用位置：app.services.auth.authenticate_user 登录服务。
    原因：统一不匹配和摘要不可识别的结果，避免错误格式暴露内部存储细节。
    参数：password 为本次输入密码，password_hash 为数据库或虚拟摘要。
    返回：匹配时为 True；不匹配或摘要格式未知时为 False。
    """
    try:  # 将密码库对摘要格式的异常限制在公共工具内部。
        return PASSWORD_HASH.verify(password, password_hash)  # 由密码库读取摘要参数并验证原始输入，业务无需自行比较摘要。
    except UnknownHashError:  # 无法识别的摘要不能视为通过，也不应把内部格式错误回显给用户。
        return False  # 统一返回失败，交由登录服务使用相同错误处理路径。


def create_session_token() -> str:  # 为每次成功登录创建独立的原始会话凭证。
    """作用：生成含 256 位随机性的、适合放入请求头的会话凭证。

    调用位置：app.services.auth.authenticate_user 密码校验成功后调用。
    原因：凭证代表登录身份，必须难以预测；不同登录还需要独立撤销而不互相影响。
    返回：由 32 个随机字节编码成的文本；该长度在当前实现中为 43 个字符。
    """
    return secrets.token_urlsafe(32)  # 生成安全随机字节并转为地址安全文本，避开请求头不便传输的字符。


def hash_session_token(token: str) -> str:  # 为保存或查找随机凭证计算同一种单向摘要。
    """作用：把随机会话凭证转换成固定长度摘要。

    调用位置：登录服务保存会话时调用；身份依赖收到凭证后也调用以查询同一记录。
    原因：数据库只保存摘要，读取会话表的人不能直接拿表中的值冒用登录。
    参数与返回：接收只含地址安全字符的凭证，返回 64 个十六进制字符的摘要。
    """
    return hashlib.sha256(token.encode("ascii")).hexdigest()  # 对高随机性凭证采用固定摘要方便索引查询；它与人类密码使用的高成本算法职责不同。
