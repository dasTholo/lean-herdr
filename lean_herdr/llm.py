"""The one HTTP call in this project: a small model, over urllib.

Two consumers, one module. `generate()` turns worktrunk's rendered
commit prompt into a commit message -- it IS the
`commit.generation.command`. `prereview()` runs the same model over a
branch diff before the expensive reviewer is built. Both go through
`complete()`, and `complete()` is the only place that talks to the
network.

`request` is injectable throughout -- the pattern from
`worktree.wt_switch()`, and `runner` still is where a real subprocess
is left: `wt_diff()`. No test in this repository reaches the network.

Stdlib plus `worktree.find_worktree()`, and no entry in
herdr-plugin.toml: this is a library and a CLI, not a plugin handler.
No third-party dependency -- the module starts on every commit in every
repository on the machine, so its import cost stays a handful of stdlib
names.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from lean_herdr import openrouter
from lean_herdr.bus import BusError, canonical_root
from lean_herdr.openrouter import ENDPOINT, api_key
from lean_herdr.settings import (
    EFFORTS,
    LlmSettings,
    SettingsError,
    llm_settings_layered,
)
from lean_herdr.worktree import find_worktree

#: OpenRouter's slug for the model measured in the design (spec 2.2).
#: The floor of the chain, never the decision: `models.auto.toml`, `[llm]` in
#: .lean-ctx/lean-herdr/config.toml, `$LEAN_HERDR_LLM_MODEL` and the CLI flag
#: beat it, in that rising order. See the precedence block below.
DEFAULT_MODEL = "google/gemini-3.8-flash"
MODEL_ENV = "LEAN_HERDR_LLM_MODEL"

# THE TWO CHAINS. This block is the authority; the four other places that
# describe them -- .lean-ctx/lean-herdr/config.toml, the argparse help texts,
# README at two places -- keep these levels in this order, and name them the
# way their own medium names things (inside the `[llm]` table the key is
# `model`, not `[llm].model`; for an operator the floor is "the built-in
# default", not `DEFAULT_MODEL`). A level dropped, added or reordered is a
# defect; a name fitted to its medium is not.
#
#     generate()  model:   --model  >  $LEAN_HERDR_LLM_MODEL  >  [llm].model
#                          >  models.auto.toml [llm].model  >  DEFAULT_MODEL
#     generate()  effort:  --effort  >  [llm].effort  >  GENERATE_EFFORT
#
#     prereview() model:   --model  >  $LEAN_HERDR_PREREVIEW_MODEL
#                          >  [llm].prereview_model  >  $LEAN_HERDR_LLM_MODEL
#                          >  [llm].model  >  models.auto.toml [llm].model
#                          >  DEFAULT_MODEL
#     prereview() effort:  --effort  >  [llm].prereview_effort
#                          >  PREREVIEW_EFFORT
#
# Three things in there are deliberate and not a gap: the effort has NO
# environment level (a flag and the file are enough for four values);
# `prereview_effort` does NOT fall back to `[llm].effort` (that is the
# commit generator's `minimal`, and inheriting it would make the judge
# as quietly thoughtless as the formatter); and the environment sits
# ABOVE the file (it is the grip inside a running pane, without touching
# a file that every repository on this machine reads).
#
# The overlay sits BELOW config.toml on purpose and is not a fifth
# spelling of the same thing: it is what a machine wrote, and the
# operator's own line has to beat it. `llm_settings_layered()` is the one
# place that merges the two; the levels above it never see two files.

#: Above this the call is not made at all. A runaway diff would cost
#: real money for an answer nobody can use, and the fallback is free.
MAX_PROMPT_BYTES = 200_000

GENERATE_TIMEOUT_S = 20.0

#: `{"reasoning": {"enabled": false}}` is REFUSED by this endpoint
#: ("Reasoning is mandatory for this endpoint and cannot be
#: disabled."); `effort` is not. `minimal` measured at 0 reasoning
#: tokens, 26x cheaper, and a byte-identical answer (spec 2.2).
GENERATE_EFFORT = "minimal"

#: worktrunk's prompt carries the diffstat in this block. The fallback
#: reads the file names out of it instead of starting a `git`
#: subprocess on the error path -- the error path is the one place
#: that must not have a second way to fail.
DIFFSTAT_RE = re.compile(r"<diffstat>(.*?)</diffstat>", re.DOTALL)
FALLBACK_FILES = 3

PREREVIEW_TIMEOUT_S = 60.0
DIFF_TIMEOUT_S = 30.0

#: A model of its own for the judge. It is the second of seven levels --
#: `model=` (the CLI's --model), this, `[llm].prereview_model`,
#: $LEAN_HERDR_LLM_MODEL, `[llm].model`, the same key in
#: `models.auto.toml`, DEFAULT_MODEL; the block above is the authority.
#: Without it the two jobs would be stuck on one
#: variable, and they are not the same job: the commit path formats a
#: diffstat and is happy with the smallest model there is, the judge
#: reads code. The builder inherits the pane's environment, so moving
#: $LEAN_HERDR_LLM_MODEL to raise the judge would raise the commit
#: generator's bill on every commit as a side effect.
PREREVIEW_MODEL_ENV = "LEAN_HERDR_PREREVIEW_MODEL"

#: MEASURED 2026-09-03, google/gemini-3.8-flash, 3 runs per cell, over a
#: diff carrying three planted faults and a clean control diff:
#:   effort   faults named on bad.diff       rejects on clean.diff       $/call
#:   minimal  3+3+3 of 3, reject every run   0 of 3                      0.00063
#:   low      3+3+3 of 3, reject every run   0 of 3                      0.00063
#:   medium   3+3+3 of 3, reject every run   0 of 3                      0.00148
#: `medium` buys ~200 reasoning tokens and finds nothing the cheap levels
#: missed; `minimal` and `low` tie inside the noise -- both spend 0 reasoning
#: tokens -- and `low` measured the cheaper of the two.
#: The rule the measurement settled: the cheapest level with no false
#: alarm on a clean diff wins. A false alarm costs a whole builder
#: round; a missed finding costs nothing, because the strong reviewer
#: runs afterwards either way.
PREREVIEW_EFFORT = "low"

#: The note travels into the follow-up order and from there into the
#: order log. A rambling model justification does not belong there.
NOTE_MAX_CHARS = 2_000

#: Bigger than this and there is no judging left to do -- `skipped`,
#: with a reason, and no call. Well under MAX_PROMPT_BYTES, because the
#: prompt around the diff has to fit too.
MAX_DIFF_BYTES = 150_000

#: The FIRST line, exactly as `dispatch.verdict()` reads its own token:
#: the first line alone, so that quoting the same words further down in
#: the reasoning cannot flip the ruling. `PREREVIEW:` is a protocol
#: token, not prose.
PREREVIEW_RE = re.compile(r"PREREVIEW:\s*(pass|reject)\s*$")

#: Deliberately narrow, and every ground checkable without knowing the
#: project: no taste, no formatting, no architecture. Those belong to
#: the strong reviewer, and a cheap model arguing about them would cost
#: a builder round for nothing.
PREREVIEW_PROMPT = """You are a cheap pre-check that runs before an expensive reviewer.
Judge ONLY the diff below, and only against the order it was written for.

Answer with `PREREVIEW: pass` or `PREREVIEW: reject` on the FIRST line, then
at most three sentences of reason.

Reject ONLY for one of these, and name which one:
- new or changed logic with no test beside it
- debug leftovers: print/pdb calls, commented-out code
- unresolved merge markers
- hard-coded absolute paths or secrets
- tool droppings in the diff: .orig, .rej, scratch files
- changes the order does not cover

Never reject for taste, formatting or architecture. When in doubt, pass: a
strong reviewer runs after you either way, and a wrong rejection costs a
whole build round.

<order>
{order}
</order>

<diff>
{diff}
</diff>
"""


def _unfence(text: str) -> str:
    """Strip a markdown fence the model wrapped its answer in.

    Asked for one line it still sometimes answers ```\nfix(x): y\n```.
    Stripping it here keeps both callers from doing it twice.
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines).strip()


def _content(stdout: str) -> str | None:
    """`.choices[0].message.content`, unfenced -- or None.

    Every shape that is not exactly that is None, not an exception:
    an error body, a rate-limit page, an empty string. The caller
    cannot tell those apart and does not need to.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    choices = data.get("choices") if isinstance(data, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        return None
    return _unfence(text) or None


def complete(
    prompt: str,
    *,
    effort: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = GENERATE_TIMEOUT_S,
    request: Any = openrouter.request,
    env: Any = None,
    auth_path: Any = None,
) -> str | None:
    """One completion, or None. Never raises, never blocks forever.

    None means "no usable answer" for every reason there is: no key, a
    prompt over the cap, the transport failing, an HTTP error, a body we
    cannot parse, an empty string. The callers turn that into their own
    safe behaviour. A raise here would reach worktrunk as a failed
    generation command, and a failed command is fatal (spec 2.3).

    The key never reaches `argv` and never reaches the filesystem. It
    goes into an Authorization header inside this process and nowhere
    else -- `ps` could not see it before either, but a temporary file
    could be read.
    """
    environ = os.environ if env is None else env
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        return None
    key = api_key(environ, auth_path)
    # NOTE: this function resolves NOTHING but the key. Model and effort
    # arrive decided -- `_first()` at the call site is the one precedence
    # rule, and a second chain here would drift from it (M3).
    #
    # A key with a newline or a carriage return in it is a header
    # INJECTION, not a formatting problem. `http.client` refuses such a
    # value itself -- but with a ValueError, out of a function whose whole
    # contract is "never raises". The quote and the backslash stay in the
    # set for the same reason they were there under curl: no real
    # OpenRouter key looks like this, and a header we assembled wrong is
    # worse than no call at all.
    if not key or any(char in key for char in '"\\\n\r'):
        return None
    try:
        answer = request(
            ENDPOINT,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            body=json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "reasoning": {"effort": effort},
                }
            ),
            timeout_s=timeout_s,
        )
    except OSError, ValueError:
        # The belt on the SEAM, not on the transport: `openrouter.request`
        # answers every failure with None already. But `request` is
        # injectable, and "never raises" is a promise this function makes to
        # worktrunk, not one it borrows from its default. OSError covers the
        # urllib family, ValueError the decode and url shapes.
        return None
    if answer is None:
        return None
    return _content(answer)


def _files_from_diffstat(block: str) -> list[str]:
    """The names out of a `git diff --stat` block: ` a.txt | 1 +`."""
    names = []
    for line in block.splitlines():
        head, sep, _rest = line.partition("|")
        name = head.strip()
        if sep and name:
            names.append(name)
    return names


def fallback_message(prompt: str) -> str:
    """worktrunk's own wording, rebuilt from the prompt it just sent.

    With no command configured worktrunk writes `Changes to a.txt`
    (measured, spec 2.1). Saying the same thing means an operator
    reading `git log` cannot tell a missing key from a missing
    configuration -- and neither state is a lie about the commit.
    """
    hit = DIFFSTAT_RE.search(prompt)
    names = _files_from_diffstat(hit.group(1) if hit else "")
    if not names:
        return "Changes to the working tree"
    shown = ", ".join(names[:FALLBACK_FILES])
    rest = len(names) - FALLBACK_FILES
    return f"Changes to {shown}" + (f" and {rest} more" if rest > 0 else "")


def _first(*candidates: str | None, fallback: str) -> str:
    """The first non-empty candidate -- the ONE precedence rule.

    One function instead of an `or`-chain per caller: two spellings of
    the same precedence drift apart the day somebody inserts a level.
    The ORDER stays visible at each call site, because that is the part
    that actually differs between the generator and the judge.
    """
    return next((c for c in candidates if c), fallback)


def file_settings(root: Any = None, *, cwd: Any = None) -> LlmSettings:
    """`[llm]` from `<repo root>/.lean-ctx/lean-herdr/config.toml` -- NEVER raises.

    Never, and that is the whole reason this wrapper exists next to
    `settings.llm_settings()`. worktrunk starts `bin/herdr-llm generate`
    in EVERY repository on the machine, and a failing generation command
    aborts the commit (spec 2.3). A missing file, a directory that is
    not a repository, a broken TOML and a bad value therefore all cost
    the built-in defaults -- never the commit. The reason goes to
    stderr, where an operator sees it without the commit paying for it.

    `SETTINGS_PATH` is relative and gets joined onto the repo root, not
    onto $PWD: the generator runs in the builder's worktree, and a
    `.lean-ctx/` lookup from there would miss (settings.py:18-27).

    `root` is handed in by callers that resolved it already -- the wait
    mode has it. Without it this asks git once, per process.

    Two files now, one rule: `models.auto.toml` below, `config.toml` above.
    The error tolerance covers both -- a broken overlay costs the defaults,
    never the commit.
    """
    try:
        base = Path(root) if root is not None else canonical_root(cwd)
        return llm_settings_layered(base)
    except (SettingsError, BusError, OSError, subprocess.SubprocessError, ValueError) as exc:
        # SubprocessError is NOT redundant beside OSError: canonical_root()
        # runs git with a timeout, and subprocess.TimeoutExpired descends
        # from SubprocessError, not from OSError. A hung git would
        # otherwise walk straight out of the manual `prereview` mode,
        # which has no blanket except around it.
        #
        # ValueError for the same reason one layer out: canonical_root()
        # (bus.py) reads git with `text=True` and no `errors=`, so a
        # non-UTF-8 byte in the repository PATH decodes strictly and
        # raises UnicodeDecodeError. Neither OSError nor SubprocessError
        # names it, and `prereview` mode would end as a traceback with
        # exit 1 -- this CLI's word for "the model rejected".
        print(f"herdr-llm: ignoring the settings file: {exc}", file=sys.stderr)
        return LlmSettings()


def generate(
    prompt: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout_s: float = GENERATE_TIMEOUT_S,
    request: Any = openrouter.request,
    env: Any = None,
    auth_path: Any = None,
    settings: LlmSettings | None = None,
) -> str:
    """A commit message, always. Never empty, never an exception.

    worktrunk treats a failing generation command as fatal -- `✗ Commit
    generation command failed`, and the commit does not happen (spec
    2.3). Its own fallback to file names applies only when NO command
    is configured. So this function has exactly one contract: text
    out, whatever went wrong.

    Resolution, in this order: the explicit argument (the CLI flag),
    then the environment, then `[llm]` in the settings file, then the
    built-in constant. The environment sits ABOVE the file on purpose:
    it is the grip an operator has inside a running pane, without
    editing a file that every repository on this machine reads. The
    effort has no environment level -- a CLI flag and the file are
    enough, and a third spelling for a four-value enum is clutter.
    """
    environ = os.environ if env is None else env
    cfg = file_settings() if settings is None else settings
    answer = complete(
        prompt,
        effort=_first(effort, cfg.effort, fallback=GENERATE_EFFORT),
        model=_first(model, environ.get(MODEL_ENV), cfg.model, fallback=DEFAULT_MODEL),
        timeout_s=timeout_s,
        request=request,
        env=env,
        auth_path=auth_path,
    )
    return answer or fallback_message(prompt)


def _skip(reason: str) -> dict[str, str]:
    return {"prereview": "skipped", "prereview_note": reason}


def wt_diff(
    path: Any,
    *,
    runner: Any = subprocess.run,
    timeout_s: float = DIFF_TIMEOUT_S,
) -> str | None:
    """`wt -C <path> step diff` -- or None when the call fails at all.

    Verified against `wt step --help` (0.76.0): diff shows "all changes
    since branching (committed, staged, unstaged, untracked)" -- exactly
    the set `wt merge` would take. `git diff` alone would miss the
    committed part, `git diff main...` the untracked one.

    Untracked is also why the decode is lenient: a single latin-1 file
    lying in the tree puts a byte on this stdout that `text=True` alone
    refuses, and refusing is the one answer this layer may never give.
    """
    try:
        proc = runner(
            ["wt", "-C", str(path), "step", "diff"],
            capture_output=True,
            text=True,
            # A foreign byte becomes `�` and gets judged with the
            # rest. Strict decoding would raise UnicodeDecodeError here
            # instead -- a ValueError, so it passed through the handler
            # below and reached the wait mode as `dispatch_crashed` on a
            # task that had completed.
            errors="replace",
            timeout=timeout_s,
        )
    except OSError, subprocess.SubprocessError, ValueError:
        # ValueError for whatever `errors="replace"` does not cover: a
        # failure of this machinery owes the caller `skipped`, never a
        # rejection and never a traceback.
        return None
    return proc.stdout if proc.returncode == 0 else None


def prereview(
    order: str,
    diff: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout_s: float = PREREVIEW_TIMEOUT_S,
    request: Any = openrouter.request,
    env: Any = None,
    auth_path: Any = None,
    settings: LlmSettings | None = None,
) -> tuple[str, str]:
    """(`pass` | `reject` | `skipped`, note). Never raises.

    `skipped` for every failure of the machinery itself -- no key,
    timeout, unparsable answer, empty diff, a diff over the cap. NEVER
    `reject`. That is the technical form of the design decision: the
    model may block, its plumbing may not.

    The judge resolves its own two levels FIRST and falls back to the
    shared ones: flag, `$LEAN_HERDR_PREREVIEW_MODEL`,
    `[llm].prereview_model`, `$LEAN_HERDR_LLM_MODEL`, `[llm].model`, the
    same key in `models.auto.toml`, constant. The effort does NOT fall
    back to `[llm].effort` -- that one is the commit generator's
    `minimal`, and inheriting it would
    quietly make the judge as thoughtless as the formatter.
    """
    if not order.strip():
        # Whoever builds the prompt owns this guard. prereview_result()
        # has its own, earlier, to spare the `wt step diff` -- but the
        # manual CLI never passes through it, and argparse defaults
        # `--order` to "". An empty <order> block against a prompt that
        # lists "changes the order does not cover" as a ground for
        # rejection is a reject waiting to happen, on a branch nobody
        # described.
        return "skipped", "no_order"
    if not diff.strip():
        return "skipped", "empty_diff"
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        return "skipped", "diff_too_large"
    environ = os.environ if env is None else env
    cfg = file_settings() if settings is None else settings
    answer = complete(
        PREREVIEW_PROMPT.format(order=order, diff=diff),
        effort=_first(effort, cfg.prereview_effort, fallback=PREREVIEW_EFFORT),
        model=_first(
            model,
            environ.get(PREREVIEW_MODEL_ENV),
            cfg.prereview_model,
            environ.get(MODEL_ENV),
            cfg.model,
            fallback=DEFAULT_MODEL,
        ),
        timeout_s=timeout_s,
        request=request,
        env=env,
        auth_path=auth_path,
    )
    if answer is None:
        return "skipped", "no_answer"
    lines = answer.lstrip().splitlines()
    hit = PREREVIEW_RE.match(lines[0]) if lines else None
    if hit is None:
        return "skipped", "unparsable_answer"
    return hit.group(1), "\n".join(lines[1:]).strip()[:NOTE_MAX_CHARS]


def prereview_result(
    order: str,
    *,
    branch: str | None,
    worktree_list: Any,
    settings: LlmSettings | None = None,
    runner: Any = subprocess.run,
    **kwargs: Any,
) -> dict[str, str]:
    """The two keys the wait mode merges into its `completed` answer.

    Resolves the path ITSELF via find_worktree(), and deliberately NOT
    via `dispatch._worker_root()`: that one falls back to the repo root
    when the branch does not resolve (dispatch.py:338-345), which is
    right for its own purpose -- finding a crash log on the timeout
    path -- and wrong here. `wt step diff` would then run in the
    orchestrator's own checkout, and a dirty tree there could reject a
    STRANGER's diff. "Not found" is `skipped`: a visibly withheld
    ruling instead of a false one.

    This function lives here and not in dispatch.py for a second
    reason: dispatch.py carries the wait mode already, and the judge is
    a job of its own -- the module that owns the model call owns this
    too.
    """
    if not order:
        # A log whose first event is not `created` leaves `description`
        # empty (orders.py:74). The prompt lists "changes the order does
        # not cover" as a ground for rejection, so an empty <order> block
        # would invite a reject on a branch nobody described -- the false
        # ruling this whole module refuses to produce.
        return _skip("no_order")
    if not branch:
        return _skip("no_branch")
    try:
        entry = find_worktree(worktree_list or {}, branch)
    except AttributeError, TypeError:
        return _skip("worktree_unresolved")
    path = entry.get("path") if isinstance(entry, dict) else None
    if not path:
        return _skip("worktree_unresolved")
    diff = wt_diff(path, runner=runner)
    if diff is None:
        return _skip("diff_failed")
    # `settings` comes in ALREADY VALIDATED from dispatch.main(), which
    # read the file once for its own RoleSettings anyway. Two gains: no
    # second `git rev-parse`, and a wrong `[llm]` value reaches the
    # orchestrator as `config_error:` instead of dying quietly in
    # file_settings(). Only the commit path may swallow it -- there a
    # broken config must not cost a commit; here it has a reader.
    # `runner` stops here: it belongs to `wt_diff` above, and the model call
    # takes `request` instead -- which arrives through **kwargs when a caller
    # injects one.
    ruling, note = prereview(order, diff, settings=settings, **kwargs)
    return {"prereview": ruling, "prereview_note": note}


def _positive_seconds(text: str) -> float:
    """A timeout has to bound something, and zero or less bounds nothing.

    Loud rather than corrected, like every other typo in the operator's
    worktrunk config -- argparse's exit 2 shows up on the first commit.
    """
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, not {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="herdr-llm",
        description=(
            "A small model, twice: `generate` writes worktrunk's commit "
            "messages, `prereview` judges a branch diff against its order."
        ),
    )
    p.add_argument("mode", choices=("generate", "prereview"))
    p.add_argument(
        "-C",
        dest="path",
        default=".",
        help="prereview: the worktree to judge (default: the current one)",
    )
    p.add_argument(
        "--order",
        default="",
        help="prereview: the order text the diff is supposed to answer",
    )
    p.add_argument(
        # Both modes, and their chains differ -- the judge has two levels
        # of its own directly below the flag. Naming only the generator's
        # would tell an operator who set $LEAN_HERDR_PREREVIEW_MODEL the
        # opposite of the truth.
        "--model",
        default=None,
        help="generate: beats $LEAN_HERDR_LLM_MODEL, then [llm].model in "
        ".lean-ctx/lean-herdr/config.toml, then the same key in "
        "models.auto.toml beside it, then the built-in default. "
        "prereview: beats $LEAN_HERDR_PREREVIEW_MODEL, then "
        "[llm].prereview_model, then those same four",
    )
    p.add_argument(
        # EFFORTS, not a second spelling of the same four words: the
        # settings validator rejects anything outside it, and two lists
        # would disagree the day a fifth level shows up.
        "--effort",
        default=None,
        choices=EFFORTS,
        help="generate: beats [llm].effort, then the built-in default. "
        "prereview: beats [llm].prereview_effort, then its own "
        "built-in -- it does NOT inherit [llm].effort. "
        "No environment level exists for either",
    )
    p.add_argument(
        # One flag, and in prereview mode it caps TWO subprocesses whose own
        # defaults differ by a factor of two. `--timeout 40` therefore raises
        # the diff's limit and lowers the model's at once, and a value chosen
        # for the model alone can starve `wt step diff` on a big branch.
        "--timeout",
        type=_positive_seconds,
        default=None,
        help="seconds, per subprocess. generate: the model call (default "
        f"{GENERATE_TIMEOUT_S:g}). prereview: BOTH `wt step diff` "
        f"(default {DIFF_TIMEOUT_S:g}) and the model call (default "
        f"{PREREVIEW_TIMEOUT_S:g}) get this one value",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """`generate` reads stdin, writes stdout and ALWAYS exits 0.

    Always, including on an unexpected exception: worktrunk treats a
    failing `commit.generation.command` as fatal and does not commit
    (spec 2.3). The one thing that may still end this process with a
    non-zero code is argparse's own usage error -- a typo in the
    operator's user config, which is a state that SHOULD be loud, and
    which shows up on the very first commit.

    `prereview` is the manual entry point and MAY end with 1: there the
    exit code carries the ruling -- 1 on `reject`, 0 on `pass` and on
    `skipped` -- so the mode is usable in a shell chain.
    """
    args = build_parser().parse_args(argv)
    if args.mode == "generate":
        prompt = ""
        try:
            if not api_key():
                print(
                    f"herdr-llm: no ${openrouter.KEY_ENV} and no opencode key "
                    "store -- "
                    "falling back to the file names",
                    file=sys.stderr,
                )
            prompt = sys.stdin.read()
            # `None` for model and effort, not the constants: generate()
            # owns the precedence, and passing a constant here would put
            # the CLI's silence ABOVE the settings file.
            message = generate(
                prompt,
                model=args.model,
                effort=args.effort,
                timeout_s=args.timeout or GENERATE_TIMEOUT_S,  # 0 is refused
            )
        except Exception as exc:  # noqa: BLE001 -- a failure would abort the commit
            print(f"herdr-llm: {exc}", file=sys.stderr)
            message = fallback_message(prompt)
        sys.stdout.write(message.rstrip("\n") + "\n")
        return 0
    diff = wt_diff(args.path, timeout_s=args.timeout or DIFF_TIMEOUT_S)
    if diff is None:
        # `skipped`, exactly as prereview_result() answers the same cause
        # on the --await path: one failure, one ruling, whichever entry
        # point asked. Loud on stderr for the human who mistyped `-C`,
        # but exit 0 -- so exit 1 keeps meaning one thing only, that the
        # model rejected the branch.
        print(f"herdr-llm: `wt -C {args.path} step diff` failed", file=sys.stderr)
        sys.stdout.write("skipped\ndiff_failed\n")
        return 0
    # No `settings=`: prereview() resolves the file itself, from the
    # repository the operator is standing in. `--model`/`--effort` stay
    # None when unset, so the file keeps its place in the chain.
    ruling, note = prereview(
        args.order,
        diff,
        model=args.model,
        effort=args.effort,
        timeout_s=args.timeout or PREREVIEW_TIMEOUT_S,
    )
    sys.stdout.write(ruling + "\n")
    if note:
        sys.stdout.write(note + "\n")
    # Exit 1 on a rejection and on nothing else, so the mode is usable in
    # a shell chain: `skipped` is 0 wherever it comes from -- a withheld
    # ruling is not a finding, and neither is a machine that could not
    # look.
    return 1 if ruling == "reject" else 0
