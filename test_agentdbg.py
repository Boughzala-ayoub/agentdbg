"""Self-check for rule matching and the hook's output shapes. No agent needed."""

import os
import re
import sys
import tempfile
import threading
from pathlib import Path

os.environ["AGENTDBG_DIR"] = tempfile.mkdtemp(prefix="agentdbg-test-")

from agentdbg import (allow, deny, load_rules, main, matches, next_request, parse_rule,
                      save_rules, subject_of)

# what a breakpoint matches against
assert subject_of({"file_path": "C:/x/src/main.c"}) == "C:/x/src/main.c"
assert subject_of({"command": "rm -rf /"}) == "rm -rf /"
assert subject_of({"weird": 1}).startswith("{")          # falls back to the raw input

# Windows hands over backslashes; every rule is written with forward slashes. Without
# normalising, a path rule matches nothing - and a NEGATED one then matches everything,
# so `guard` would pause on every write including the ones inside your project.
assert subject_of({"file_path": r"C:\Users\me\proj\a.md"}) == "C:/Users/me/proj/a.md"
assert subject_of({"command": r"grep '\d' x"}) == r"grep '\d' x", "a command is not a path"
# ...and `guard` builds its rule with the drive letter intact. Without it the rule is only
# /Users/me/proj, and a write to the SAME path on another drive reads as inside the project.
guard_rule = parse_rule("Write|Edit:!" + re.escape("C:/Users/me/proj"))
assert guard_rule["pattern"] == "C:/Users/me/proj", guard_rule   # colon survives parse_rule
assert not matches(guard_rule, "Write", subject_of({"file_path": r"C:\Users\me\proj\a.md"}))
assert matches(guard_rule, "Write", subject_of({"file_path": r"D:\Users\me\proj\a.md"})), "drive"
assert matches(guard_rule, "Write", subject_of({"file_path": r"C:\tmp\a.md"}))

# `guard` must distinguish the project from a sibling whose name starts the same way.
main(["agentdbg", "guard"])
generated = next(r for r in load_rules()["breaks"] if r["tool"] == "Write|Edit")
here = str(Path.cwd()).replace("\\", "/")
assert generated["cwd"] == here
assert not matches(generated, "Write", f"{here}/src/a.py")
assert matches(generated, "Write", f"{here}-old/secrets.txt"), "sibling is outside the project"
escaped = subject_of({"file_path": f"{here}/src/../../outside.txt"})
assert matches(generated, "Write", escaped), ".. must be resolved"
assert not matches(generated, "Write", f"{here}-old/a.py", f"{here}-old"), "rules are scoped"

# Guarding this project again must retain rules belonging to another project.
foreign = dict(parse_rule("Write"), cwd=f"{here}-other")
saved = load_rules()
saved["breaks"].append(foreign)
legacy_deny = dict(parse_rule("Bash:rm -rf |mkfs|dd if="),
                   why="destructive shell command - do it yourself if you really mean it")
legacy_break = parse_rule("Write|Edit:!" + re.sub(r"^[A-Za-z]:", "", here))
saved["denies"].append(legacy_deny)
saved["breaks"].append(legacy_break)
save_rules(saved)
main(["agentdbg", "guard"])
saved = load_rules()
assert foreign in saved["breaks"]
assert legacy_deny not in saved["denies"] and legacy_break not in saved["breaks"]

r = parse_rule("Write:!^.*/src/")
assert r == {"tool": "Write", "pattern": "^.*/src/", "negate": True}, r
# negation is the useful case: break on writes OUTSIDE src
assert matches(r, "Write", "C:/x/docs/readme.md")
assert not matches(r, "Write", "C:/x/src/main.c")
assert not matches(r, "Read", "C:/x/docs/readme.md"), "tool must match too"

danger = parse_rule("Bash:rm |git push")
assert matches(danger, "Bash", "git push --force")
assert not matches(danger, "Bash", "git status")
assert matches(parse_rule("Edit"), "Edit", "anything"), "no pattern = every call"

try:
    parse_rule("Write:[")
    assert False, "invalid regex must not be saved"
except ValueError:
    pass

# guard's destructive-shell rule must catch flag reorderings and the Windows spellings,
# not just the literal "rm -rf" - and must NOT block a plain non-recursive rm.
from agentdbg import DESTRUCTIVE

wreck = parse_rule(f"Bash|PowerShell:{DESTRUCTIVE}")
for cmd in ("rm -rf /x", "rm -fr /x", "rm -f -r /x", "rm -r /x",
            "Remove-Item -Recurse -Force C:/x", "rd /s /q C:/x", "del /s *.tmp"):
    assert matches(wreck, "PowerShell", cmd) or matches(wreck, "Bash", cmd), cmd
for cmd in ("rm -f one-file.txt", "Remove-Item one-file.txt", "ls -la", "del x.tmp"):
    assert not matches(wreck, "Bash", cmd) and not matches(wreck, "PowerShell", cmd), cmd

# continue must stay silent: an explicit 'allow' would bypass the permission prompt,
# so 'no opinion' is the only safe meaning of stepping past a breakpoint.
assert allow() == {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
assert allow(updated={"a": 1})["hookSpecificOutput"]["updatedInput"] == {"a": 1}
assert deny("nope")["hookSpecificOutput"]["permissionDecision"] == "deny"

# A request stays on disk until the hook consumes the answer, so the console must not
# offer it twice - that is the "I answered and got asked again" bug.
queue = Path(tempfile.mkdtemp(prefix="agentdbg-queue-"))
one, two = queue / "later-low-pid.json", queue / "earlier-high-pid.json"
one.touch()
two.touch()
os.utime(one, (2, 2))
os.utime(two, (1, 1))
assert next_request([one, two], set()) == two, "oldest request must be shown first"
assert next_request([one, two], {two.name}) == one, "answered call must not reappear"
assert next_request([one], {one.name}) is None

# mac/linux keypress: a non-tty (piped stdin, CI, an editor terminal) must fall back to
# a whole line instead of raising - this is the path Windows never exercises.
import io

from agentdbg import getkey_posix

assert getkey_posix(io.StringIO("c\n")) == "c"
assert getkey_posix(io.StringIO("Deny\n")) == "d"
assert getkey_posix(io.StringIO("")) == " ", "EOF must not crash the console"

if sys.platform != "win32":
    import pty

    master, slave = pty.openpty()
    with os.fdopen(slave, "r", encoding="utf-8") as stream:
        threading.Timer(0.1, os.write, args=(master, b"c")).start()
        assert getkey_posix(stream) == "c", "real termios keypress"
    os.close(master)

# A broken $EDITOR must return None, not raise: that exception used to escape cmd_attach,
# kill the console, and silently release every paused call and every later breakpoint.
from agentdbg import edit_json

os.environ["EDITOR"] = "definitely-not-an-editor --wait"
assert edit_json({"a": 1}) is None

print("ok")
