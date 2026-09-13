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


@pytest.mark.parametrize(
    "cause",
    [
        pytest.param(FileNotFoundError(2, "No such file or directory", "git"), id="git missing"),
        pytest.param(subprocess.TimeoutExpired(cmd=["git"], timeout=5.0), id="git hung"),
        pytest.param(
            UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid start byte"), id="undecodable"
        ),
    ],
)
def test_a_git_that_cannot_answer_is_git_unusable(monkeypatch, tmp_path, cause):
    """Three ways git fails to answer at all, and each one used to leave raw.

    Raw, they walked past every `main()`'s BusError rung and came out as
    `workspace_crashed:` or `models_crashed:` -- or, in `init`, next to a
    `not_a_git_repo` that sends the operator to `git init` for a missing binary.
    """
    from lean_herdr.bus import BusError, GitUnusable

    def refuse(*_args, **_kwargs):
        raise cause

    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(GitUnusable, match="^git_unusable: ") as caught:
        canonical_root(tmp_path)
    assert isinstance(caught.value, BusError)
    assert caught.value.__cause__ is cause


def test_no_repository_stays_a_plain_bus_error(tmp_path: Path):
    """git answered, and its answer was "no". That is not git being unusable."""
    from lean_herdr.bus import BusError, GitUnusable

    with pytest.raises(BusError) as caught:
        canonical_root(tmp_path)
    assert not isinstance(caught.value, GitUnusable)
