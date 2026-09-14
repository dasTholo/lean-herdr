#!/usr/bin/env bash
# Guard: docs/specs/ and docs/lean-md/ (dev-only specs and plans) must NEVER
# reach main/master.
#
# .gitignore is the wrong tool -- it would hide them on the working branches
# too, and cannot un-track what is already committed. Instead we gate the two
# moments a path can cross onto main:
#
#   commit  -> a direct commit while HEAD is main/master that adds or changes
#              a guarded path. Deletions pass, so the cleanup commit can land.
#   push    -> any ref pushed to main/master whose tree still carries a guarded
#              path (catches merge / rebase / cherry-pick, however it arose).
#
# Invoked by the `pre-commit` framework (see .pre-commit-config.yaml) with $1
# selecting the stage: "commit" (pre-commit stage) or "push" (pre-push stage).
#
# Bypass a single operation (rarely needed): git commit/push --no-verify
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PATHSPECS=(docs/specs docs/lean-md)
PROTECTED_RE='^(refs/heads/)?(main|master)$'

blocked() {
  {
    echo ""
    echo "--------------------------------------------------------------"
    echo "BLOCKED: ${PATHSPECS[*]} must not reach $1."
    echo "  Specs and plans are dev-only and never live on main."
    echo "  If a merge dragged them in, drop the paths before they land:"
    echo "      git rm -r --cached ${PATHSPECS[*]} && git commit"
    echo "  Deliberate override (discouraged):  --no-verify"
    echo "--------------------------------------------------------------"
  } >&2
  exit 1
}

mode="${1:-commit}"

case "$mode" in
  commit)
    # symbolic-ref (not rev-parse --abbrev-ref) so an unborn branch still reports
    # its name -- pre-commit runs before the first commit exists. Detached HEAD
    # yields empty -> not protected -> pass.
    branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo '')"
    [[ "$branch" =~ $PROTECTED_RE ]] || exit 0
    if git diff --cached --name-only --diff-filter=d -- "${PATHSPECS[@]}" | grep -q .; then
      blocked "branch '$branch' (commit)"
    fi
    ;;
  push)
    # pre-commit exports the destination ref (REMOTE_BRANCH) and the local ref
    # being pushed. On a *new* remote branch it omits TO_REF/FROM_REF and only
    # sets LOCAL_BRANCH, so fall back to it.
    remote_branch="${PRE_COMMIT_REMOTE_BRANCH:-}"
    if [[ -z "$remote_branch" ]]; then
      echo "warning: guard-plans-on-main: PRE_COMMIT_REMOTE_BRANCH unset; push guard skipped." >&2
      exit 0
    fi
    [[ "$remote_branch" =~ $PROTECTED_RE ]] || exit 0
    to_ref="${PRE_COMMIT_TO_REF:-}"
    [[ -z "$to_ref" ]] && to_ref="${PRE_COMMIT_LOCAL_BRANCH:-}"
    # empty local ref = deletion of the remote branch -> no tree to inspect.
    if [[ -z "$to_ref" || "$to_ref" =~ ^0+$ ]]; then
      exit 0
    fi
    if git ls-tree -r --name-only "$to_ref" -- "${PATHSPECS[@]}" | grep -q .; then
      blocked "$remote_branch (push)"
    fi
    ;;
  *)
    echo "guard-plans-on-main: unknown mode '$mode' (expected commit|push)" >&2
    exit 2
    ;;
esac

exit 0
