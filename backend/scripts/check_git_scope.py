"""Git 工具：限制提交和推送路径，不参与网站请求或数据库登录。

作用：只允许 frontend/ 和 backend/ 内的文件进入提交与推送。
调用位置：backend/.githooks/pre-commit、pre-push，也可由开发者在终端执行。
原因：忽略规则不能撤销已跟踪文件，也可能被强制暂存绕过，因此增加只读检查；
暂存区检查完整的新快照，推送检查远端尚无的新历史，二者防范的风险不同。
"""

import argparse  # 解析终端模式参数，让两个 Git 钩子复用同一套范围检查入口。
import subprocess  # 调用 Git 读取真实暂存区和提交对象，避免自行猜测仓库状态。
import sys  # 读取推送钩子的标准输入，并把阻止原因写到标准错误输出。

ALLOWED_PREFIXES = (b"frontend/", b"backend/")  # check_paths 使用字节前缀白名单；尾部斜杠防止 frontend-extra 等名称冒充合法目录。


def git_output(*arguments: str) -> bytes:  # 集中封装 Git 读取方式，让上层检查都使用一致的失败处理和原始字节输出。
    """作用：执行只读 Git 命令，返回未解码的标准输出。

    调用位置：check_commit、check_push 和 main 的暂存区分支。
    原因：独立参数避免文件名成为 shell 指令；保留字节能够正确处理中文或特殊文件名，
    check=True 则把读取失败交给 main 阻止操作，不能因检查异常而放行。
    """
    return subprocess.run(  # 不启用 shell，使所有参数都只按 Git 参数处理。
        ["git", *arguments], check=True, capture_output=True  # 失败抛出异常；同时捕获输出，避免范围列表直接刷入终端。
    ).stdout  # 仅返回检查所需的标准输出，交给调用者按路径或提交号解释。


def check_paths(paths: bytes, description: str) -> bool:  # 统一判定目录范围，使暂存区与提交历史遵守相同白名单。
    """作用：检查 Git 返回的完整文件快照，报告范围外路径并返回是否合规。

    调用位置：main 检查暂存区，check_commit 检查历史提交。
    原因：按零字节分隔不会误拆含换行的文件名；检查最终快照而非删除清单，
    因此允许把旧资料取消跟踪的纠正提交，且本函数不会删除本地文件。
    """
    invalid = sorted({  # 去重并排序，让多次检查的错误清单稳定且便于定位。
        path for path in paths.split(b"\0")  # Git 的 -z 输出以零字节分隔，文件名中的空格和换行都不会影响解析。
        if path and not path.startswith(ALLOWED_PREFIXES)  # 忽略末尾空项，只保留不在两个授权目录内的路径。
    })  # 得到本次完整快照中的违规路径集合，而不是工作区里的全部文件。
    if not invalid:  # 没有违规路径时才允许继续提交或推送。
        return True  # 向钩子报告范围合规，不修改仓库和本地文件。
    print(f"已阻止{description}：仅允许 frontend/ 和 backend/。", file=sys.stderr)  # 先说明哪个操作被阻止，便于用户修正暂存内容。
    for path in invalid[:10]:  # 最多展示十条路径，避免大量误跟踪文件淹没终端。
        print(f"  {path.decode('utf-8', errors='backslashreplace')}", file=sys.stderr)  # 遇到无法解码的字节用转义显示，检查本身不因文件名失败。
    print(f"范围外文件共 {len(invalid)} 个；本地文件未删除。", file=sys.stderr)  # 显示总量并明确本工具仅阻止操作，没有清理资料。
    return False  # 将违规结果交给入口转换为非零退出码，Git 据此中止操作。


def check_commit(commit: str) -> bool:  # 读取指定历史提交的文件树，而不是读取此刻的工作区。
    """作用：检查单个提交包含的所有文件路径。

    调用位置：check_push 遍历新提交时，以及 main 的 --tree 人工检查模式。
    原因：工作区可能已经修正，但将上传的旧提交仍含越界文件；检查提交快照才能发现该风险。
    """
    return check_paths(  # 将 Git 文件树交给共用白名单逻辑，避免两套判定逐渐不一致。
        git_output("ls-tree", "-r", "--name-only", "-z", commit),  # 递归列出指定提交中的路径，零字节分隔保留特殊文件名。
        f"提交 {commit[:12]}",  # 错误消息保留提交号前缀，帮助定位哪一次历史提交需要纠正。
    )  # 直接返回该提交是否合规，不创建提交也不改写历史。


def check_push() -> bool:  # 根据 Git 推送钩子的引用更新记录，逐一检查本次将新增到远端的提交。
    """作用：校验本次推送的新历史，而不是只校验最后一个提交。

    调用位置：main 的 --push 分支，由 pre-push 钩子触发。
    原因：首次推送必须检查全部祖先；已有远端则排除对方已持有的历史，
    允许通过合法的新提交纠正旧目录。缺少远端父对象时必须失败，不能猜测上传范围。
    """
    checked: set[str] = set()  # 记录已校验的提交号，多个分支共享祖先时避免重复读取同一文件树。
    for line in sys.stdin:  # Git 每行提供一项引用更新；一次推送可能同时更新多个分支。
        _, local_commit, _, remote_commit = line.split()  # 四项依次是本地引用、本地提交、远端引用、远端提交；这里只需两个提交号。
        if set(local_commit) == {"0"}:  # 全零本地提交号表示删除远端引用，没有新文件会被上传。
            continue  # 跳过删除动作，继续核验同次推送中的其他引用。
        arguments = ["rev-list", local_commit]  # 先枚举本地目标提交的全部祖先，适用于远端尚不存在的引用。
        if set(remote_commit) != {"0"}:  # 远端提交非零表示已有历史，可以排除远端已拥有的提交。
            # 远端父提交应已在本机；缺失时让检查失败，先同步再推送。
            git_output("cat-file", "-e", f"{remote_commit}^{{commit}}")  # 先确认本机确有远端提交对象，否则由 main 阻止推送并要求同步历史。
            arguments.extend(["--not", remote_commit])  # 只保留远端尚无的提交，防止把已有旧历史错误当作本次新增内容。
        for commit in git_output(*arguments).decode("ascii").splitlines():  # 提交号仅含十六进制字符，可按 ASCII 解码并逐行校验。
            if commit not in checked and not check_commit(commit):  # 未检查的提交一旦越界，即停止整次推送。
                return False  # 返回违规结果，钩子会以非零退出码阻止 Git 上传。
            checked.add(commit)  # 合规或之前检查过的提交都记入集合，供后续引用去重。
    return True  # 所有将上传的新提交均合规，才允许 Git 继续发送。


def main() -> int:  # 为钩子和人工检查提供同一终端入口，并统一退出码含义。
    """作用：选择检查模式，把检查结果转换成 Git 可以识别的进程退出码。

    调用位置：本文件作为脚本运行时，两个 Git 钩子间接调用。
    原因：0 表示允许，1 表示路径违规，2 表示读取或解析失败；任何失败都不能默认放行上传。
    """
    parser = argparse.ArgumentParser(description="限制 Git 仅提交前后端两个目录")  # 提供终端帮助说明，减少误用检查参数的情况。
    mode = parser.add_mutually_exclusive_group(required=True)  # 三种检查方式必须且只能选择一种，避免模式含糊。
    mode.add_argument("--index", action="store_true", help="检查完整暂存区")  # 提交前使用，检查下次提交将保存的完整暂存快照。
    mode.add_argument("--push", action="store_true", help="读取推送钩子传入的提交")  # 推送前使用，按标准输入中的引用记录计算新增历史。
    mode.add_argument("--tree", metavar="COMMIT", help="检查指定提交的文件快照")  # 开发者人工验证某个历史提交时使用。
    arguments = parser.parse_args()  # 解析终端参数，不合法的组合由参数库直接拒绝。
    try:  # 将 Git 读取或推送输入解析异常统一转换成阻止操作的退出码。
        if arguments.index:  # pre-commit 选择完整暂存区检查，删除范围外文件的纠正提交可正常通过。
            allowed = check_paths(git_output("ls-files", "-z"), "提交")  # ls-files 默认读取索引，忽略工作区尚未暂存的变更。
        elif arguments.push:  # pre-push 选择本次新增提交历史检查，防止旧污染随首次推送发出。
            allowed = check_push()  # 委托专门函数处理多个引用、全零提交号和历史去重。
        else:  # 互斥组保证剩下的模式一定是 --tree，无需提供隐式默认模式。
            allowed = check_commit(arguments.tree)  # 校验用户明确指定的提交快照，便于排查阻止原因。
    except (OSError, subprocess.CalledProcessError, ValueError) as error:  # 命令不可用、读取失败或钩子输入不合法时都保守拒绝。
        print(f"Git 范围检查失败，已阻止操作：{error}", file=sys.stderr)  # 给出可定位的失败原因，而不是把异常静默吞掉。
        return 2  # 非零退出码通知 Git 中止操作，先解决检查异常再重试。
    return 0 if allowed else 1  # 明确区分通过与路径违规，供 Git 和自动测试判定。


if __name__ == "__main__":  # 只在直接执行脚本时启动检查，被导入时不自动读取参数或标准输入。
    raise SystemExit(main())  # 把检查结果作为进程退出码返回，Git 钩子据此允许或中止操作。
