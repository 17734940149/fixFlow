import os
from pathlib import Path
import subprocess
import sys

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_git_scope.py"
ZERO = "0" * 40


def git(repo: Path, *arguments: str) -> str:
    """测试仅修改临时仓库，避免检查限制规则时误动真实项目的提交。"""
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=Scope Test",
         "-c", "user.email=scope-test@example.invalid", *arguments],
        cwd=repo, check=True, capture_output=True,
    )
    return result.stdout.decode("utf-8").strip()


def check(repo: Path, *arguments: str, updates: str = "") -> int:
    """调用真实检查脚本，覆盖 Git 读取和推送更新的完整行为。"""
    result = subprocess.run(
        [sys.executable, str(CHECKER), *arguments], cwd=repo,
        input=updates, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    return result.returncode


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """每条用例独立初始化，保证已提交历史不会串到另一条检查。"""
    git(tmp_path, "init", "--quiet")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "main.js").write_text("export default {}", encoding="utf-8")
    git(tmp_path, "add", "frontend")
    return tmp_path


def test_index_accepts_allowed_files(repo: Path) -> None:
    """前后端正常变更应能提交，避免白名单连正常开发一起拦截。"""
    (repo / "backend").mkdir()
    (repo / "backend" / "main.py").write_text("app = None", encoding="utf-8")
    git(repo, "add", "backend")
    assert check(repo, "--index") == 0


@pytest.mark.parametrize("outside", ["notes.md", "docs/说明.md", "frontend-extra/file.txt"])
def test_index_blocks_forced_outside_files(repo: Path, outside: str) -> None:
    """即使强制暂存范围外文件，提交检查也必须阻止，且不能删除该文件。"""
    path = repo / outside
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("keep locally", encoding="utf-8")
    (repo / ".gitignore").write_text("/*\n!/frontend/\n", encoding="utf-8")
    git(repo, "add", "--force", "--", outside)
    assert check(repo, "--index") == 1
    assert path.read_text(encoding="utf-8") == "keep locally"


def test_correction_keeps_files_and_excludes_existing_remote_history(repo: Path) -> None:
    """已上传的旧历史可用纠正提交更新，但不能把污染的旧历史首次推给空仓库。"""
    (repo / "notes.md").write_text("keep locally", encoding="utf-8")
    git(repo, "add", "notes.md")
    git(repo, "commit", "--quiet", "-m", "old")
    old = git(repo, "rev-parse", "HEAD")
    git(repo, "rm", "--cached", "notes.md")
    assert check(repo, "--index") == 0
    assert (repo / "notes.md").is_file()
    git(repo, "commit", "--quiet", "-m", "correct")
    new = git(repo, "rev-parse", "HEAD")
    update = f"refs/heads/main {new} refs/heads/main {{remote}}\n"
    assert check(repo, "--push", updates=update.format(remote=old)) == 0
    assert check(repo, "--push", updates=update.format(remote=ZERO)) == 1


def test_first_push_accepts_clean_history(repo: Path) -> None:
    """首次推送必须连同全部祖先提交都合规，而不仅检查最后一个目录快照。"""
    git(repo, "commit", "--quiet", "-m", "clean")
    commit = git(repo, "rev-parse", "HEAD")
    assert check(repo, "--push", updates=f"refs/heads/main {commit} refs/heads/main {ZERO}\n") == 0
    assert check(repo, "--tree", commit) == 0


def test_missing_remote_commit_blocks_push(repo: Path) -> None:
    """缺少远端父提交时不能猜测上传范围，应先同步历史再重新检查。"""
    git(repo, "commit", "--quiet", "-m", "clean")
    commit = git(repo, "rev-parse", "HEAD")
    assert check(repo, "--push", updates=f"refs/heads/main {commit} refs/heads/main {'1' * 40}\n") == 2
