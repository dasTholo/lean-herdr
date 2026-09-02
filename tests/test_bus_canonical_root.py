import subprocess
from pathlib import Path

import pytest

from lean_herdr.bus import canonical_root


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-b", "main", cwd=main)
    _git("config", "user.email", "t@example.invalid", cwd=main)
    _git("config", "user.name", "Test", cwd=main)
    (main / "seed.txt").write_text("seed\n")
    _git("add", "seed.txt", cwd=main)
    _git("commit", "-m", "seed", cwd=main)
    linked = tmp_path / "main.feat"
    _git("worktree", "add", "-b", "feat", str(linked), cwd=main)
    return main.resolve(), linked.resolve()


def test_canonical_root_in_the_main_checkout(repo_with_worktree):
    main, _ = repo_with_worktree
    assert canonical_root(main) == main


def test_canonical_root_from_a_linked_worktree(repo_with_worktree):
    """The one test that catches the homemade bus split (B12)."""
    main, linked = repo_with_worktree
    assert canonical_root(linked) == main
    assert canonical_root(linked) != linked


def test_canonical_root_without_a_repo_raises(tmp_path: Path):
    from lean_herdr.bus import BusError

    with pytest.raises(BusError):
        canonical_root(tmp_path)
