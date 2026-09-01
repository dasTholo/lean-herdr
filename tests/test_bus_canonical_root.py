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


def test_canonical_root_im_haupt_checkout(repo_with_worktree):
    main, _ = repo_with_worktree
    assert canonical_root(main) == main


def test_canonical_root_aus_linked_worktree(repo_with_worktree):
    """Der eine Test, der den selbstgemachten Bus-Split faengt (B12)."""
    main, linked = repo_with_worktree
    assert canonical_root(linked) == main
    assert canonical_root(linked) != linked


def test_canonical_root_ohne_repo_wirft(tmp_path: Path):
    from lean_herdr.bus import BusError

    with pytest.raises(BusError):
        canonical_root(tmp_path)
