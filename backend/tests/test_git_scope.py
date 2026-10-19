"""Git 工具测试，由 pytest 自动发现；不参与网站请求或连接业务数据库。

作用：在临时仓库验证索引白名单、强制暂存、纠正历史、首次推送与缺对象拒绝。
原因：忽略规则和最终快照不足以保证上传范围；使用真实 Git 与正式校验脚本，
才能同时检验引用输入、历史计算和阻止操作的进程退出码。
"""

import os  # 继承环境并显式控制校验子进程编码，覆盖中文路径。
from pathlib import Path  # 定位校验脚本和隔离仓库，减少平台路径差异。
import subprocess  # 调用真实 Git 和脚本，测试实际命令与退出码行为。
import sys  # 复用当前解释器，避免子进程切换到另一套运行环境。

import pytest  # 提供夹具和参数化，全部仓库操作都限制在临时目录。

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_git_scope.py"  # check 辅助函数使用真实脚本绝对路径，不复制一套校验逻辑。
ZERO = "0" * 40  # 全零号供推送测试模拟新远端引用，触发全部祖先检查。


def git(repo: Path, *arguments: str) -> str:  # 封装临时仓库 Git 操作，避免测试改动项目历史。
    """作用：测试仅修改临时仓库，避免检查限制规则时误动真实项目的提交。

    调用位置：repo 夹具与本文件各测试调用；所有命令都在传入的临时仓库中执行。
    原因：检查本身依赖真实 Git 索引和对象历史，模拟命令结果无法证明路径读取正确；指定临时工作目录和局部身份，避免测试触碰真实仓库及全局配置。
    """
    result = subprocess.run(  # 启动真实 Git，覆盖与钩子相同的仓库读取方式。
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=Scope Test",  # 禁用换行转换并设置局部测试身份，减少个人配置影响。
         "-c", "user.email=scope-test@example.invalid", *arguments],  # 补齐局部邮箱与命令参数，不修改用户全局身份。
        cwd=repo, check=True, capture_output=True,  # 仅在临时仓库执行，捕获输出并让准备失败立即暴露。
    )  # 取得 Git 执行结果，后续提取需要的标准输出。
    return result.stdout.decode("utf-8").strip()  # 解码并去除边界换行，供提交号和路径断言使用。


def check(repo: Path, *arguments: str, updates: str = "") -> int:  # 执行真实范围检查，支持模拟推送钩子的标准输入。
    """作用：调用真实检查脚本，覆盖 Git 读取和推送更新的完整行为。

    调用位置：本文件各范围测试调用；子进程执行 backend/scripts/check_git_scope.py。
    原因：Git 钩子根据进程退出码决定是否继续，不是根据 Python 函数返回文字；真实子进程并传入标准输入才能验证整个阻止链路。
    """
    result = subprocess.run(  # 用子进程调用正式脚本，不用模拟返回值绕过逻辑。
        [sys.executable, str(CHECKER), *arguments], cwd=repo,  # 使用当前解释器在临时仓库读取真实索引和提交。
        input=updates, capture_output=True, text=True, encoding="utf-8",  # 传入四字段引用更新记录，以统一文本编码捕获结果。
        env={**os.environ, "PYTHONUTF8": "1"},  # 保留环境并启用 UTF-8，中文路径不依赖终端默认编码。
    )  # 完成校验调用，不写入真实项目工作区或提交。
    return result.returncode  # 返回退出码，验证 Git 实际识别的通过与拒绝结果。


@pytest.fixture  # 为每项测试注册独立仓库夹具。
def repo(tmp_path: Path) -> Path:  # 准备最小合法仓库，避免共享历史掩盖污染问题。
    """作用：每条用例独立初始化，保证已提交历史不会串到另一条检查。

    调用位置：本文件请求 repo 参数的测试使用；pytest 每条用例独立创建 tmp_path。
    原因：索引测试与历史测试会改动仓库状态，不能共享提交；每项单独初始化能让失败只来自当前构造场景，而不是前一用例残留的污染祖先。
    """
    git(tmp_path, "init", "--quiet")  # 只在临时目录初始化，不改项目仓库。
    (tmp_path / "frontend").mkdir()  # 建立允许前端目录，提供默认合法路径。
    (tmp_path / "frontend" / "main.js").write_text("export default {}", encoding="utf-8")  # 写入固定样本字符串，内容不参与业务执行。
    git(tmp_path, "add", "frontend")  # 暂存合法文件，建立后续检查的完整快照基础。
    return tmp_path  # 返回临时仓库路径，让测试自由构造隔离场景。


def test_index_accepts_allowed_files(repo: Path) -> None:  # 验证合法前后端文件不会被白名单误拦截。
    """作用：前后端正常变更应能提交，避免白名单连正常开发一起拦截。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：范围保护也可能误拦正常开发；前端和后端都加入同一完整索引，能证明两类合法内容确实可提交。
    """
    (repo / "backend").mkdir()  # 再建立合法后端目录，让一次检查覆盖两个前缀。
    (repo / "backend" / "main.py").write_text("app = None", encoding="utf-8")  # 写入最小后端文件，只验证路径而不执行样本代码。
    git(repo, "add", "backend")  # 暂存后端内容，模拟正常新增项目文件。
    assert check(repo, "--index") == 0  # 完整暂存快照均合规时应返回成功。


@pytest.mark.parametrize("outside", ["notes.md", "docs/说明.md", "frontend-extra/file.txt"])  # 覆盖根文件、中文路径和伪装目录名，验证边界。
def test_index_blocks_forced_outside_files(repo: Path, outside: str) -> None:  # 验证强制暂存不能绕过范围校验，且原文件保留。
    """作用：即使强制暂存范围外文件，提交检查也必须阻止，且不能删除该文件。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：.gitignore 可被强制暂存绕过，也不控制已跟踪文件；根文件、中文文档和相似前缀目录分别验证严格白名单，并确认阻止动作保留资料。
    """
    path = repo / outside  # 定位本次参数对应的越界样本。
    path.parent.mkdir(parents=True, exist_ok=True)  # 创建必要父目录，排除文件不存在带来的假失败。
    path.write_text("keep locally", encoding="utf-8")  # 保存固定本地内容，后续确认阻止动作没有破坏它。
    (repo / ".gitignore").write_text("/*\n!/frontend/\n", encoding="utf-8")  # 构造忽略规则，准备强制暂存绕过忽略的实际场景。
    git(repo, "add", "--force", "--", outside)  # 故意强制暂存越界内容，验证额外检查能够拦截。
    assert check(repo, "--index") == 1  # 索引内含越界路径必须返回违规退出码。
    assert path.read_text(encoding="utf-8") == "keep locally"  # 阻止提交不能删除或修改本地文件。


def test_correction_keeps_files_and_excludes_existing_remote_history(repo: Path) -> None:  # 区分纠正旧历史和首次上传污染祖先的风险。
    """作用：已上传的旧历史可用纠正提交更新，但不能把污染的旧历史首次推给空仓库。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：远端已拥有旧历史时可以用新提交纠正最终目录，但空远端首次接收会得到全部污染祖先；同一历史两种远端状态能验证这一关键区别。
    """
    (repo / "notes.md").write_text("keep locally", encoding="utf-8")  # 准备旧版本的越界文档，模拟误提交资料。
    git(repo, "add", "notes.md")  # 将越界文件加入跟踪，构造需要纠正的历史。
    git(repo, "commit", "--quiet", "-m", "old")  # 只在临时仓库创建污染提交。
    old = git(repo, "rev-parse", "HEAD")  # 保存旧提交号，模拟远端已持有该历史。
    git(repo, "rm", "--cached", "notes.md")  # 仅取消跟踪文档，保留本地资料。
    assert check(repo, "--index") == 0  # 纠正后的索引合规，不能因越界删除记录误拦截。
    assert (repo / "notes.md").is_file()  # 确认取消跟踪没有删掉本地文档。
    git(repo, "commit", "--quiet", "-m", "correct")  # 提交新的干净快照，与旧污染提交建立祖先关系。
    new = git(repo, "rev-parse", "HEAD")  # 保存本次待推送的目标提交号。
    update = f"refs/heads/main {new} refs/heads/main {{remote}}\n"  # 构造 Git 四字段记录，远端提交号分别替换为两种状态。
    assert check(repo, "--push", updates=update.format(remote=old)) == 0  # 远端已有旧提交时，只上传新纠正提交，应允许。
    assert check(repo, "--push", updates=update.format(remote=ZERO)) == 1  # 远端为空会携带污染祖先，即使末尾快照干净也要拒绝。


def test_first_push_accepts_clean_history(repo: Path) -> None:  # 验证首次推送全合规历史及单提交人工检查入口。
    """作用：首次推送必须连同全部祖先提交都合规，而不仅检查最后一个目录快照。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：首次推送必须检查所有祖先，但不能因此一律拒绝新仓库；全合规历史的成功样本也能防止保护逻辑误伤正常发布。
    """
    git(repo, "commit", "--quiet", "-m", "clean")  # 提交默认合法样本，构造干净首次历史。
    commit = git(repo, "rev-parse", "HEAD")  # 读取本地目标号，模拟真实推送记录。
    assert check(repo, "--push", updates=f"refs/heads/main {commit} refs/heads/main {ZERO}\n") == 0  # 新远端引用的全部祖先都合规时应通过。
    assert check(repo, "--tree", commit) == 0  # 同一合法提交也应通过人工 --tree 检查。


def test_missing_remote_commit_blocks_push(repo: Path) -> None:  # 验证缺远端父对象时保守失败，不猜测上传范围。
    """作用：缺少远端父提交时不能猜测上传范围，应先同步历史再重新检查。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：本机缺远端父对象时无法可靠计算新增历史；保守失败要求先同步，比猜测上传范围更能避免把未审查的资料发到远端。
    """
    git(repo, "commit", "--quiet", "-m", "clean")  # 先提交合法内容，确保失败只来自缺远端对象。
    commit = git(repo, "rev-parse", "HEAD")  # 读取有效本地目标，作为推送记录的本地项。
    assert check(repo, "--push", updates=f"refs/heads/main {commit} refs/heads/main {'1' * 40}\n") == 2  # 模拟不存在的远端号，必须报检查异常并拒绝推送。
