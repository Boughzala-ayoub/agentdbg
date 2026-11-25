"""Drives the hook the way a console does, and asserts what it emits to Claude Code.

Isolated via AGENTDBG_DIR so it never touches the state a live session is using.
"""
import json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["AGENTDBG_DIR"] = tempfile.mkdtemp(prefix="agentdbg-test-")
import agentdbg as A  # noqa: E402  (must follow the env var)

APP = str(HERE / "agentdbg.py")
A.save_rules({"breaks": [A.parse_rule("Write:!/src/")], "step": False})
A.PENDING.mkdir(parents=True, exist_ok=True)
stop = threading.Event()


def heartbeat():
    while not stop.is_set():
        A.ATTACHED.touch()
        time.sleep(0.3)


threading.Thread(target=heartbeat, daemon=True).start()
EVENT = {"tool_name": "Write", "tool_input": {"file_path": "C:/x/docs/a.md", "content": "hi"},
         "session_id": "sess1234", "cwd": "C:/x"}


def fire(event=EVENT):
    proc = subprocess.Popen([sys.executable, APP, "hook"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps(event))
    proc.stdin.close()
    return proc


def pending(timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        files = sorted(A.PENDING.glob("*.json"))
        if files:
            return files[0]
        time.sleep(0.1)
    raise AssertionError("hook never paused")


def answer(req, reply):
    req.with_suffix(".answer").write_text(json.dumps(reply), encoding="utf-8")


# 1. deny carries the human's reason back to the model
proc = fire()
req = pending()
call = json.loads(req.read_text(encoding="utf-8"))
assert call["tool"] == "Write" and call["subject"] == "C:/x/docs/a.md", call
answer(req, {"action": "deny", "reason": "use src/ instead"})
out = json.loads(proc.stdout.read())["hookSpecificOutput"]
proc.wait()
assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"] == "use src/ instead"
print(f"1. deny         -> {out['permissionDecisionReason']}")

# 2. edit resumes the call with different input
proc = fire()
req = pending()
edited = {"file_path": "C:/x/src/a.md", "content": "edited by the human"}
answer(req, {"action": "edit", "input": edited})
out = json.loads(proc.stdout.read())["hookSpecificOutput"]
proc.wait()
assert out["updatedInput"] == edited, out
print(f"2. edit         -> updatedInput file_path={out['updatedInput']['file_path']}")

# 3. continue stays silent, so normal permission handling is untouched
proc = fire()
answer(pending(), {"action": "continue"})
assert proc.stdout.read().strip() == ""
proc.wait()
print("3. continue     -> no output")

# 4. the console dying mid-pause must release the agent, not strand it
proc = fire()
pending()
stop.set()
started = time.time()
assert proc.stdout.read().strip() == ""
proc.wait()
print(f"4. console dies -> released after {time.time() - started:.1f}s")

# 4b. a break firing with nobody attached passes instantly AND leaves a "missed" trace
# line - fail-open must be on record, or you never learn the console was worth opening
proc = fire()
started = time.time()
assert proc.stdout.read().strip() == "" and time.time() - started < 5
proc.wait()
last = json.loads(A.TRACE.read_text(encoding="utf-8").splitlines()[-1])
assert last.get("missed") is True and last["tool"] == "Write", last
print("4b. missed break -> released instantly, recorded in trace")

# 5. a call no breakpoint matches is never paused
proc = fire({"tool_name": "Read", "tool_input": {"file_path": "C:/x/docs/a.md"}})
started = time.time()
assert proc.stdout.read().strip() == "" and time.time() - started < 5
proc.wait()
print("5. no match     -> straight through")

# 6. a deny RULE holds with no console at all - the fail-closed half of the tool
A.save_rules({"breaks": [], "step": False,
              "denies": [dict(A.parse_rule("Bash:rm -rf "), why="not on my watch")]})
assert not A.attached(), "this case is only meaningful with nobody watching"
proc = fire({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/x"}})
started = time.time()
out = json.loads(proc.stdout.read())["hookSpecificOutput"]
proc.wait()
assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"] == "not on my watch"
assert time.time() - started < 5, "policy must be instant, never waiting for a human"
print(f"6. deny rule    -> {out['permissionDecisionReason']} (unattended, no pause)")

# ...and it must not block everything else
proc = fire({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
assert proc.stdout.read().strip() == ""
proc.wait()
print("7. other calls  -> untouched by the deny rule")

# 8. a damaged policy must fail closed instead of silently dropping every deny rule
A.RULES.write_text("{broken", encoding="utf-8")
proc = fire({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
out = json.loads(proc.stdout.read())["hookSpecificOutput"]
proc.wait()
assert out["permissionDecision"] == "deny" and "rules" in out["permissionDecisionReason"]
print("8. bad rules    -> denied with a repairable error")
print("protocol ok")
