/**
 * Runs the existing lean-ctx policy hooks under opencode.
 *
 * The adapter only translates the protocol -- it decides nothing. A rule
 * exists exactly once, in the Python scripts Claude Code already runs.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const HOOKS_DIR =
  process.env.LEAN_HERDR_HOOKS_DIR || join(homedir(), ".claude", "hooks");
const TIMEOUT_MS = 5000;

/** Tool name (lower-cased) -> the scripts in charge, in this order. */
const SCRIPTS = {
  read: ["read-search-discipline.py"],
  grep: ["read-search-discipline.py"],
  glob: ["read-search-discipline.py"],
  list: ["read-search-discipline.py"],
  ls: ["read-search-discipline.py"],
  bash: ["bash-enforce-ctx-shell.py", "lean-ctx-policy-guard.py"],
  edit: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
  write: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
  patch: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
};

function note(text) {
  process.stderr.write(`[lean-ctx-policy] ${text}\n`);
}

/** Run one hook. Returns its decision or null. */
function runHook(script, payload) {
  return new Promise((resolve) => {
    const path = join(HOOKS_DIR, script);
    if (!existsSync(path)) {
      note(`${script} is missing -- the tool runs through`);
      return resolve(null);
    }
    let child;
    try {
      child = spawn("python3", [path], { stdio: ["pipe", "pipe", "pipe"] });
    } catch (err) {
      note(`python3 not startable (${err.message}) -- the tool runs through`);
      return resolve(null);
    }
    let out = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      note(`${script} did not answer within ${TIMEOUT_MS} ms -- the tool runs through`);
      resolve(null);
    }, TIMEOUT_MS);

    child.stdout.on("data", (b) => (out += b));
    child.on("error", (err) => {
      clearTimeout(timer);
      note(`${script}: ${err.message} -- the tool runs through`);
      resolve(null);
    });
    child.on("close", () => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(out)?.hookSpecificOutput ?? null);
      } catch {
        resolve(null);
      }
    });
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

/** Feed `lean-ctx hook observe`. Result-free and always without consequence. */
function observe(payload) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn("lean-ctx", ["hook", "observe"], {
        stdio: ["pipe", "ignore", "ignore"],
      });
    } catch (err) {
      note(`lean-ctx not startable (${err.message}) -- not observed`);
      return resolve();
    }
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve();
    }, TIMEOUT_MS);
    child.on("error", () => {
      clearTimeout(timer);
      resolve();
    });
    child.on("close", () => {
      clearTimeout(timer);
      resolve();
    });
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

export const LeanCtxPolicy = async ({ project, directory }) => ({
  "tool.execute.before": async (input, output) => {
    const name = String(input.tool || "").toLowerCase();
    for (const script of SCRIPTS[name] ?? []) {
      const decision = await runHook(script, {
        tool_name: name,
        tool_input: output.args ?? {},
        cwd: directory ?? project?.worktree ?? process.cwd(),
        session_id: input.sessionID ?? null,
      });
      if (decision?.permissionDecision === "deny") {
        // Throwing blocks the tool call; opencode shows the reason as a tool
        // error. The turn continues -- never a session abort.
        throw new Error(
          decision.permissionDecisionReason || `[lean-ctx-policy] ${name} is blocked`,
        );
      }
      if (decision?.updatedInput) {
        Object.assign(output.args, decision.updatedInput);
      }
    }
  },

  "tool.execute.after": async (input, output) => {
    // `lean-ctx hook observe` feeds cache and ledger with what the tool
    // actually did -- the same payload shape as PostToolUse on Claude. It
    // decides nothing, prints nothing and exits 0; measured against
    // lean-ctx 3.10.1.
    await observe({
      tool_name: String(input.tool || "").toLowerCase(),
      tool_input: output.args ?? {},
      tool_response: output.output ?? output.result ?? {},
      cwd: directory ?? project?.worktree ?? process.cwd(),
      session_id: input.sessionID ?? null,
    });
  },

  "permission.ask": async (_permission, output) => {
    // No human sits at a worker pane. Asking means hanging.
    output.status = "deny";
  },
});
