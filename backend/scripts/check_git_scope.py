"""只允许前后端路径进入提交和推送，不删除工作区中的任何文件。"""

import argparse
import subprocess
import sys

ALLOWED_PREFIXES = (b"frontend/", b"backend/")


def git_output(*arguments: str) -> bytes:
    """用独立参数调用只读 Git 命令，避免文件名被当作 shell 指令执行。"""
    return subprocess.run(
        ["git", *arguments], check=True, capture_output=True
    ).stdout


def check_paths(paths: bytes, description: str) -> bool:
    """核验完整快照而非删除清单，清理旧资料的提交仍应被允许。"""
    invalid = sorted({
        path for path in paths.split(b"\0")
        if path and not path.startswith(ALLOWED_PREFIXES)
    })
    if not invalid:
        return True
    print(f"已阻止{description}：仅允许 frontend/ 和 backend/。", file=sys.stderr)
    for path in invalid[:10]:
        print(f"  {path.decode('utf-8', errors='backslashreplace')}", file=sys.stderr)
    print(f"范围外文件共 {len(invalid)} 个；本地文件未删除。", file=sys.stderr)
    return False


def check_commit(commit: str) -> bool:
    """按提交快照检查路径，使推送检查不依赖当前工作区是否干净。"""
    return check_paths(
        git_output("ls-tree", "-r", "--name-only", "-z", commit),
        f"提交 {commit[:12]}",
    )


def check_push() -> bool:
    """只检查待上传的新提交；远端已有历史由本次纠正提交更新最终目录。"""
    checked: set[str] = set()
    for line in sys.stdin:
        _, local_commit, _, remote_commit = line.split()
        if set(local_commit) == {"0"}:
            continue
        arguments = ["rev-list", local_commit]
        if set(remote_commit) != {"0"}:
            # 远端父提交应已在本机；缺失时让检查失败，先同步再推送。
            git_output("cat-file", "-e", f"{remote_commit}^{{commit}}")
            arguments.extend(["--not", remote_commit])
        for commit in git_output(*arguments).decode("ascii").splitlines():
            if commit not in checked and not check_commit(commit):
                return False
            checked.add(commit)
    return True


def main() -> int:
    """任何读取失败都阻止操作，避免检查异常时默认放行上传。"""
    parser = argparse.ArgumentParser(description="限制 Git 仅提交前后端两个目录")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--index", action="store_true", help="检查完整暂存区")
    mode.add_argument("--push", action="store_true", help="读取推送钩子传入的提交")
    mode.add_argument("--tree", metavar="COMMIT", help="检查指定提交的文件快照")
    arguments = parser.parse_args()
    try:
        if arguments.index:
            allowed = check_paths(git_output("ls-files", "-z"), "提交")
        elif arguments.push:
            allowed = check_push()
        else:
            allowed = check_commit(arguments.tree)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Git 范围检查失败，已阻止操作：{error}", file=sys.stderr)
        return 2
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
