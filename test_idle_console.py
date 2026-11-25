"""The bug the synthetic test missed: a console blocked on a keypress must keep the
pause alive. Runs the REAL attach console, never answers, and checks the hook waits."""
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
# Isolate from any live session: sharing state means this test's hook ends up waiting
# on YOUR console's heartbeat, and hangs instead of failing.
os.environ["AGENTDBG_DIR"] = tempfile.mkdtemp(prefix="agentdbg-test-")
import agentdbg as A

APP = str(__import__("pathlib").Path(__file__).resolve().parent / "agentdbg.py")
A.save_rules({"breaks": [A.parse_rule("Write:!agentdbg")], "step": False})
for f in A.PENDING.glob("*"):
    f.unlink()
A.ATTACHED.unlink(missing_ok=True)

# the real console, with a pipe for stdin so it blocks at getkey() like a human would
console = subprocess.Popen([sys.executable, APP, "attach"], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, text=True)
time.sleep(1.5)
assert A.attached(), "console did not register a heartbeat"

hook = subprocess.Popen([sys.executable, APP, "hook"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, text=True)
hook.stdin.write(json.dumps({"tool_name": "Write",
                             "tool_input": {"file_path": "C:/tmp/outside.md"}}))
hook.stdin.close()

# nobody presses a key. Before the fix the hook bailed out after HEARTBEAT_STALE.
for waited in (3, 6, 9, 12):
    time.sleep(3)
    alive = hook.poll() is None
    print(f"  {waited:>2}s: hook still holding the tool call = {alive} "
          f"| heartbeat fresh = {A.attached()}")
    assert alive, f"hook released the agent after {waited}s with the console sitting idle"

console.kill()
time.sleep(A.HEARTBEAT_STALE + 1.5)
released = hook.wait(timeout=15)
print(f"  console killed -> hook exited {released}, output {hook.stdout.read()!r}")
print("idle ok")
