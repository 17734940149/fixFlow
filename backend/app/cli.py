"""数据库管理命令入口，通过 python -m app.cli 调用，独立于浏览器接口。

只提供数据库就绪检查、受控创建网站用户及过期登录凭证清理；不会自动建表。
数据库连接账号仍由 PostgreSQL 管理，本模块创建的是 users 表中的网站账号。
"""
import argparse  # 解析受控的管理子命令和参数，避免把运维功能暴露成公开接口。
import getpass  # 在终端隐藏输入应用密码，避免密码直接进入命令历史或屏幕输出。
import json  # 将数据库检查状态输出为结构化文本，便于人工检查或脚本读取。
import sys  # 将管理函数的退出结果转换为进程退出码，便于调用脚本判断成功失败。
import time  # 取当前时间戳，清理命令只删除已经到期的登录凭证。

from sqlalchemy import delete, select  # 使用统一查询构造器检查重复账号和删除过期凭证，避免拼接输入内容。
from sqlalchemy.exc import SQLAlchemyError  # 将数据库异常收束为安全提示，不打印连接地址或敏感参数。
from sqlalchemy.orm import Session  # 为一次管理操作提供数据库工作上下文，与用户登录凭证不同。

from app.core.accounts import normalize_account  # 复用登录入口的账号规范化规则，保证创建和登录使用相同账号格式。
from app.core.config import Settings  # 从统一配置入口加载数据库地址和连接池参数，不在命令中硬编码密码。
from app.core.security import hash_password  # 复用安全模块将应用登录密码变成不可逆哈希，再写入用户表。
from app.db.health import database_status  # 管理写入前同时检查连接和必要表，避免未迁移时直接执行写库。
from app.db.session import create_database_engine  # 与接口和迁移共用连接策略，保持驱动和敏感参数保护一致。
from app.models import AuthSession, User  # 管理命令通过模型访问网站用户与登录凭证，不创建 PostgreSQL 连接账号。


def create_user(database: Session, account: str, display_name: str, role: str) -> int:  # 在调用方提供的数据库工作会话内创建一个网站账号。
    """作用：校验账号与显示名，交互读取两次密码，只持久保存密码哈希和用户资料。

    调用位置：main 在解析 create-user 子命令并确认数据库就绪后调用；
    tests/test_backend_setup.py 通过命令入口验证成功创建和拒绝错误输入。
    使用原因：当前没有公开注册能力，通过受控终端建账号，避免任意用户自行申请管理员
    角色；交互输入不把明文密码放入命令参数和命令历史。
    参数：database 是本次管理操作的数据库 Session；account 复用登录账号规范；
    display_name 是展示名称；role 由命令参数限定为 user 或 admin，数据库还有角色约束。
    返回：0 代表已提交成功，1 代表输入无效或账号已存在；数据库异常交给 main 统一处理。
    账号唯一检查便于给友好提示，真正并发竞争仍由数据库唯一约束兜底。
    本函数显式 commit 保存新用户，但不关闭工作会话，关闭由 main 的上下文负责。
    """
    try:  # 将账号格式错误转为可读结果，不让正常输入错误产生终端堆栈。
        account = normalize_account(account)  # 与登录服务复用同一规范化逻辑，避免创建后无法用一致账号登录。
    except ValueError as error:  # 只接住账号规范化的输入错误，其他异常仍由命令总入口处理。
        print(str(error))  # 输出已有账号规则提示，不包含数据库连接秘密。
        return 1  # 输入无效时立即结束，尚未提示密码也未写入用户。
    display_name = display_name.strip()  # 去掉展示名称首尾空白，避免保存只有空格的名称。
    if not 1 <= len(display_name) <= 80:  # 在写库前核对与显示名字段相符的长度范围。
        print("显示名称须为 1 至 80 个字符。")  # 用明确中文说明被拒绝的输入条件。
        return 1  # 无效显示名不进入后续密码采集和用户创建。
    if database.scalar(select(User.id).where(User.account == account)) is not None:  # 只查主键判断重复账号，减少读取无关敏感字段。
        print("该账号已存在，不会覆盖密码或提升角色。")  # 重复建用户不会悄悄变成改密码或提权操作。
        return 1  # 保留已有账号原状，拒绝这次重复创建。
    password = getpass.getpass("输入密码（12 至 128 个字符，不回显）：")  # 隐藏输入应用密码，真实明文只暂存于当前进程内存。
    confirmation = getpass.getpass("再次输入密码：")  # 再读一次以降低误输入导致创建后无法登录的概率。
    if not 12 <= len(password) <= 128 or password != confirmation:  # 同时验证密码长度和两次一致性，失败时不生成用户记录。
        print("密码长度不符合要求或两次不一致，未创建账号。")  # 告知失败原因范围，避免输出用户刚输入的密码。
        return 1  # 提前结束，数据库中尚未增加本次用户对象。
    database.add(User(  # 构建用户并加入本次工作会话，只有后续 commit 成功才成为持久记录。
        account=account, display_name=display_name,  # 保存已规范化账号与校验后的显示名，用于登录和当前用户响应。
        role=role, password_hash=hash_password(password),  # 保存允许的角色以及 Argon2 密码哈希，绝不把明文作为用户字段写入。
    ))  # 完成模型构造和待写入登记；此时提交仍可能被数据库约束拒绝。
    database.commit()  # 显式提交用户事务，账号唯一和角色检查等数据库约束在写入时提供最终兜底。
    print(f"已创建账号 {account}，角色 {role}；未显示或保存明文密码。")  # 仅报告账号与角色，避免暴露密码或其哈希。
    return 0  # 让总入口返回成功退出码，供人工和自动化工具判断操作结果。


def main(argv: list[str] | None = None) -> int:  # 解析管理子命令并持有整次操作的引擎生命周期。
    """作用：分派数据库检查、网站用户创建和过期登录凭证清理三个命令。

    调用位置：本文件末尾的模块执行保护块在 python -m app.cli 时调用；
    测试也可传入 argv 参数列表直接调用，避免依赖真实终端参数。
    使用原因：数据库迁移、网站用户创建及凭证清理属于显式运维动作，服务启动不应
    偷偷建表、创建管理员或删除记录。此命令只做所选动作，结构迁移另由 Alembic 执行。
    参数 argv 为 None 时 argparse 使用进程参数；传列表时使用指定参数。返回 0 表示
    操作成功，1 表示检查未就绪、输入取消或数据库操作失败；参数格式错误由 argparse
    自己提示并退出。配置与引擎创建在 try 之前，配置验证异常不会被本函数数据库异常分支捕获。
    生命周期：一次调用创建一个引擎；写入共用一次 Session 上下文，异常退出会关闭会话
    并清理未提交事务；finally 无论结果如何都 dispose 引擎，避免命令结束后遗留连接。
    """
    parser = argparse.ArgumentParser(description="FixFlow 数据库操作工具")  # 定义管理入口帮助信息，明确这是终端操作工具。
    commands = parser.add_subparsers(dest="command", required=True)  # 要求选择具体子命令，避免无意运行默认写库动作。
    commands.add_parser("check-db", help="检查数据库连接及必要表是否已经建立")  # 注册只读检查入口，不创建用户或迁移表。
    create = commands.add_parser("create-user", help="交互创建账号，不接受命令行密码")  # 创建受控网站用户命令，不接受明文密码参数。
    create.add_argument("--account", required=True)  # 要求明确提供网站登录账号，避免默认管理员账号隐式存在。
    create.add_argument("--display-name", required=True)  # 要求提供前端展示名称，实际长度由 create_user 检查。
    create.add_argument("--role", choices=("user", "admin"), default="user")  # 角色限定为两种，缺省普通用户，减少误创建管理员的风险。
    commands.add_parser("cleanup-sessions", help="只清理已经到期的登录凭证")  # 注册显式过期清理命令，不会在导入或启动时自动执行。
    arguments = parser.parse_args(argv)  # 校验参数并得到选定命令与参数对象，错误参数由 argparse 提示。
    engine = create_database_engine(Settings())  # 复用本机统一配置创建连接管理器，首次检查时才真正借用连接。
    try:  # 统一处理检查、管理查询和交互输入中的可预期失败。
        state = database_status(engine)  # 确认连接以及用户和登录凭证表就绪，避免未迁移时继续写库。
        if arguments.command == "check-db":  # 只读检查命令只需要输出当前状态。
            print(json.dumps({"database": state}, ensure_ascii=False))  # 输出稳定结构化检查结果，不输出数据库地址或密码。
            return 0 if state == "ready" else 1  # 状态就绪才报告进程成功，便于部署检查脚本判断。
        if state != "ready" or engine is None:  # 写操作必须有已配置引擎及检查通过的必要表。
            print("数据库未就绪：请检查本机连接配置，并执行数据库迁移。")  # 指出先配置和迁移，而不是在管理命令中偷偷建表。
            return 1  # 不具备前置条件时结束，不进行用户创建或清理。
        with Session(engine) as database:  # 为这次管理动作创建独立数据库工作会话，退出时自动关闭并释放剩余资源。
            if arguments.command == "create-user":  # 按已验证子命令分派到用户创建函数。
                return create_user(database, arguments.account, arguments.display_name, arguments.role)  # 传入解析参数和当前会话，并沿用创建函数结果。
            result = database.execute(delete(AuthSession).where(AuthSession.expires_at <= int(time.time())))  # 其余合法命令为 cleanup-sessions，仅删除截止当前时刻已到期的凭证。
            database.commit()  # 显式提交删除事务，未提交之前删除不会永久生效。
            print(f"已清理 {result.rowcount} 条过期登录凭证。")  # 报告数据库返回的删除条数，不打印任何原始登录令牌。
            return 0  # 清理事务成功提交后返回成功退出码。
    except SQLAlchemyError:  # 捕获连接或写库错误，包括并发重复账号触发的数据库唯一约束失败。
        print("数据库操作失败：请检查连接及迁移；未输出连接地址或密码。")  # 给出安全概括提示，不直接显示可能携带敏感信息的数据库异常。
        return 1  # 数据库操作失败时让调用脚本能够识别失败。
    except (EOFError, KeyboardInterrupt):  # 隐藏输入遇到输入结束或用户中断时停止本次操作。
        print("已取消，未继续创建账号。")  # 说明没有继续执行创建；不输出已输入的明文密码。
        return 1  # 将取消视为未成功完成，避免自动化误判用户已创建。
    finally:  # 即使函数在分支中提前 return，也必须执行引擎资源清理。
        if engine is not None:  # 无配置时没有引擎可清理，避免对 None 调用方法。
            engine.dispose()  # 释放本次管理命令的连接池资源，不影响其他进程持有的引擎。


if __name__ == "__main__":  # 只有直接以模块运行时执行命令，测试或其他模块导入本文件不会自动操作数据库。
    sys.exit(main())  # 将管理结果变成终端退出码，供用户和部署脚本判断成功失败。
