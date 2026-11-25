#!/usr/bin/env python3
"""agentdbg - breakpoints for a running agent.

A PreToolUse hook runs synchronously before every tool call, so blocking inside it
pauses the agent mid-run. That is the whole trick: this is a debugger, not a logger.

  agentdbg guard                    arm a sensible default: block destructive shell,
                                    pause on pushes/installs and writes outside here
  agentdbg watch                    tail every tool call (no pausing)
  agentdbg stats                    what this agent actually touches, from the trace
  agentdbg break "Write:!^.*/src/"  pause when Write touches anything outside src
  agentdbg deny "Bash:rm -rf " "..." block it outright, console or not
  agentdbg step / run               pause on every call / stop doing that
  agentdbg rules                    show what is armed, and where the rules file lives
  agentdbg drop break|deny <n>      remove one rule by its number   /  agentdbg clear
  agentdbg attach                   the console: c continue, d deny+why, e edit, s step, r run
  agentdbg install                  print the settings.json hook entry

Two kinds of rule, and the difference is the point:

  break  needs a human, so it FAILS OPEN - no console attached, no pause, no delay.
         A debugger you forgot to detach must never wedge your day.
  deny   is policy, so it FAILS CLOSED - it holds whether or not anyone is watching,
         which is what makes this useful on an agent running unattended.

Windows, macOS and Linux.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

def _state_dir():
    # AGENTDBG_DIR keeps a test run (or a second, isolated console) off the state a live
    # session is using - sharing it means a test's hook waits on your real console.
    if os.environ.get("AGENTDBG_DIR"):
        return Path(os.environ["AGENTDBG_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "agentdbg"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "agentdbg"


DIR = _state_dir()
RULES = DIR / "rules.json"
ATTACHED = DIR / "attached"          # heartbeat: the console is alive and driving
PENDING = DIR / "pending"            # one file per paused tool call
TRACE = DIR / "trace.jsonl"
HEARTBEAT_STALE = 5.0                # seconds without a heartbeat = nobody is driving
WAIT_CAP = 870                       # ceiling on one pause. Must stay UNDER the hook
                                     # timeout in settings.json (900s) - if Claude Code
                                     # kills the hook first, its cleanup never runs.

# Recursive/forced deletion in either shell dialect: rm with an r flag in any order or
# split across flags, plus the PowerShell and cmd.exe spellings Windows agents actually use.
DESTRUCTIVE = (r"\brm\s+(-\S+\s+)*-\S*r|mkfs|dd if=|>\s*/dev/[sh]d"
               r"|remove-item\s.*-(recurse|force)|\b(rd|rmdir|del)\s+/s\b")

# Fields worth showing and matching against, in the order tools tend to use them.
SUBJECT_KEYS = ("file_path", "command", "path", "url", "pattern", "notebook_path", "prompt")
PATH_KEYS = {"file_path", "path", "notebook_path"}   # slash-normalised; a command is not


def normalize_path(value):
    return os.path.normpath(value.replace("\\", "/")).replace("\\", "/")


def same_path(left, right):
    return os.path.normcase(normalize_path(left)) == os.path.normcase(normalize_path(right))


def subject_of(tool_input, cwd=None):
    """-> the one string a breakpoint should match against for this call.

    Paths are normalised to forward slashes: Windows hands over C:\\a\\b while every rule
    anyone writes (and every rule `guard` generates) uses /a/b, so without this a
    path rule matches nothing and a NEGATED one matches everything.
    """
    if isinstance(tool_input, dict):
        for key in SUBJECT_KEYS:
            if isinstance(tool_input.get(key), str):
                value = tool_input[key]
                if key not in PATH_KEYS:
                    return value
                value = normalize_path(value)
                if cwd and not os.path.isabs(value) and not re.match(r"^[A-Za-z]:/", value):
                    value = normalize_path(os.path.join(cwd, value))
                return value
    return json.dumps(tool_input, ensure_ascii=False)[:400]


def validate_rule(rule):
    try:
        re.compile(rule["tool"])
        if rule.get("pattern"):
            re.compile(rule["pattern"])
    except (KeyError, TypeError, re.error) as exc:
        raise ValueError(f"invalid rule {rule!r}: {exc}") from None
    return rule


def parse_rule(spec):
    """'Write:!^.*/src/' -> {tool: 'Write', pattern: '^.*/src/', negate: True}."""
    tool, _, pattern = spec.partition(":")
    if not tool:
        raise ValueError(f"rule needs a tool name: {spec!r}")
    negate = pattern.startswith("!")
    return validate_rule({"tool": tool, "pattern": pattern[1:] if negate else pattern,
                          "negate": negate})


def matches(rule, tool, subject, cwd=None):
    if cwd is not None and rule.get("cwd") and not same_path(cwd, rule["cwd"]):
        return False
    if not re.search(rule["tool"], tool, re.I):
        return False
    if not rule.get("pattern"):
        return True
    hit = bool(re.search(rule["pattern"], subject, re.I))
    return not hit if rule.get("negate") else hit


def write_atomic(path, text):
    """A half-written answer file parses as garbage and silently releases the agent,
    so every handoff file lands whole or not at all."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_rules():
    try:
        rules = json.loads(RULES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"breaks": [], "step": False}
    if not isinstance(rules, dict):
        raise ValueError("rules file must contain a JSON object")
    for kind in ("breaks", "denies"):
        if not isinstance(rules.get(kind, []), list):
            raise ValueError(f"rules field {kind!r} must be a list")
        for rule in rules.get(kind, []):
            validate_rule(rule)
    return rules


def save_rules(rules):
    DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(RULES, json.dumps(rules, indent=1))


def attached():
    try:
        return time.time() - ATTACHED.stat().st_mtime < HEARTBEAT_STALE
    except OSError:
        return False


def allow(reason=None, updated=None):
    """PreToolUse output. No output at all = 'no opinion', which keeps the normal
    permission flow intact - that is what 'continue' should mean, not auto-approve."""
    out = {"hookEventName": "PreToolUse"}
    if reason:
        out["permissionDecision"] = "allow"
        out["permissionDecisionReason"] = reason
    if updated is not None:
        out["updatedInput"] = updated
    return {"hookSpecificOutput": out}


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


# ---------------------------------------------------------------- the hook

def cmd_hook():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    event_cwd = normalize_path(event.get("cwd") or "")
    subject = subject_of(tool_input, event_cwd)

    try:
        rules = load_rules()
    except (OSError, ValueError) as exc:
        print(json.dumps(deny(f"agentdbg rules unreadable: {exc}")))
        return 0
    denied = next((r for r in rules.get("denies", [])
                   if matches(r, tool, subject, event_cwd)), None)
    hit = rules.get("step") or any(matches(r, tool, subject, event_cwd)
                                   for r in rules.get("breaks", []))
    live = attached()

    entry = {"t": round(time.time(), 3), "tool": tool, "subject": subject[:200],
             "cwd": event_cwd}
    if hit and not denied and not live:
        # Fail-open is silent by design, but silent-and-unrecorded means you never learn
        # what you missed - `stats` surfaces the count of these.
        entry["missed"] = True
    DIR.mkdir(parents=True, exist_ok=True)
    with open(TRACE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Deny rules are policy, not debugging: they hold whether or not anyone is watching.
    # This is the one path that fails CLOSED, and it is why the tool is useful unattended.
    if denied:
        print(json.dumps(deny(denied.get("why")
                              or f"blocked by agentdbg rule {denied['tool']}:{denied['pattern']}")))
        return 0

    if not hit or not live:
        return 0  # fastest path, and the fail-open path: say nothing, change nothing

    req = PENDING / f"{os.getpid()}-{int(time.time()*1000)}.json"
    PENDING.mkdir(parents=True, exist_ok=True)
    write_atomic(req, json.dumps({"tool": tool, "input": tool_input, "subject": subject,
                                  "session": event.get("session_id", "")[:8],
                                  "cwd": event.get("cwd", "")}, ensure_ascii=False))
    answer = req.with_suffix(".answer")
    try:
        deadline = time.time() + WAIT_CAP
        while time.time() < deadline:
            if answer.exists():
                try:
                    reply = json.loads(answer.read_text(encoding="utf-8"))
                except ValueError:
                    break
                if reply.get("action") == "deny":
                    print(json.dumps(deny(reply.get("reason") or "stopped in agentdbg")))
                elif reply.get("action") == "edit":
                    print(json.dumps(allow("edited in agentdbg", reply.get("input"))))
                return 0
            if not attached():      # console died mid-pause: let the agent go
                return 0
            time.sleep(0.15)
    finally:
        req.unlink(missing_ok=True)
        answer.unlink(missing_ok=True)
    return 0


# ---------------------------------------------------------------- the console

def edit_json(value):
    """Open the tool input in an editor; return it parsed, or None if unusable."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(json.dumps(value, indent=2, ensure_ascii=False))
        path = fh.name
    editor = os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "vi")
    # EDITOR usually carries arguments ("code --wait"): Windows lets CreateProcess parse the
    # whole line, POSIX needs it split. Handing the unsplit string to argv[0] looks for an
    # executable literally named "code --wait" and raises - which used to kill the console.
    cmd = f'{editor} "{path}"' if sys.platform == "win32" else shlex.split(editor) + [path]
    try:
        subprocess.run(cmd)
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  edit not applied ({exc}) - continuing unedited")
        return None
    finally:
        Path(path).unlink(missing_ok=True)


_beating = threading.Event()


def _heartbeat():
    _beating.set()
    while _beating.is_set():
        ATTACHED.touch()
        time.sleep(HEARTBEAT_STALE / 5)


def next_request(reqs, answered):
    """-> the next call to show. A request stays on disk until the hook picks up the
    answer, so without this the console re-prompts for the call you just decided."""
    try:
        return min((r for r in reqs if r.name not in answered),
                   key=lambda r: r.stat().st_mtime_ns, default=None)
    except OSError:                  # a hook removed its request between glob and stat
        return None


def getkey_posix(stream):
    """One keypress on mac/linux, raw-mode if we have a tty and a whole line if not
    (piped stdin, CI, an editor's terminal emulation) - never crash on a non-tty."""
    try:
        import termios
        import tty
        fd = stream.fileno()
        old = termios.tcgetattr(fd)
    except Exception:
        line = stream.readline()
        return (line.strip() or " ")[0].lower()
    try:
        tty.setraw(fd)
        return (stream.read(1) or " ").lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def getkey():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getch().decode("utf-8", "replace").lower()
    return getkey_posix(sys.stdin)


def cmd_attach():
    DIR.mkdir(parents=True, exist_ok=True)
    PENDING.mkdir(parents=True, exist_ok=True)
    rules = load_rules()
    # The heartbeat MUST be independent of the main loop: that loop spends most of its
    # life blocked in getkey() waiting for a human, and a heartbeat touched inline goes
    # stale the moment you stop to think - the hook then decides the console died and
    # releases the very call you were looking at.
    beat = threading.Thread(target=_heartbeat, daemon=True)
    beat.start()
    now = time.time()
    for leftover in PENDING.glob("*"):
        # A hook killed mid-pause never runs its own cleanup, so either half can outlive it.
        # Anything older than one pause's ceiling is a corpse - showing it asks a human about
        # a tool call that already ran, on every console restart, forever.
        try:
            orphan = leftover.suffix == ".answer" and not leftover.with_suffix(".json").exists()
            if orphan or now - leftover.stat().st_mtime > WAIT_CAP:
                leftover.unlink(missing_ok=True)
        except OSError:
            pass
    print(f"agentdbg attached. step={rules.get('step', False)} "
          f"breaks={len(rules.get('breaks', []))}   (ctrl-c to detach)")
    answered = set()
    try:
        while True:
            req = next_request(PENDING.glob("*.json"), answered)
            if req is None:
                answered &= {p.name for p in PENDING.glob("*.json")}  # forget dead ones
                time.sleep(0.15)
                continue
            try:
                call = json.loads(req.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.1)
                continue
            print(f"\a\n  {call['tool']}  {call['subject'][:120]}")  # \a: you looked away
            print("  [c]ontinue  [d]eny+why  [e]dit input  [s]tep  [r]un free  > ", end="",
                  flush=True)
            reply = {"action": "continue"}
            try:
                key = getkey()
                print(key)
                if key == "d":
                    reply = {"action": "deny", "reason": input("  tell it why: ").strip()}
                elif key == "e":
                    edited = edit_json(call["input"])
                    if edited is not None:
                        reply = {"action": "edit", "input": edited}
                elif key in ("s", "r"):
                    rules = load_rules()
                    rules["step"] = key == "s"
                    save_rules(rules)
                    print(f"  step mode {'on' if rules['step'] else 'off'}")
            except Exception as exc:
                # The console dying is the worst outcome in this file: the heartbeat stops,
                # every paused call is released and every later breakpoint fails open, with
                # nothing on screen to say so. So any mishap falls through to "continue",
                # which emits nothing and leaves the normal permission prompt in charge.
                # KeyboardInterrupt is a BaseException and still detaches, as it should.
                print(f"  {exc!r} - continuing this call")
            write_atomic(req.with_suffix(".answer"), json.dumps(reply))
            answered.add(req.name)
            for _ in range(100):        # the hook removes the request as it resumes
                if not req.exists():
                    break
                time.sleep(0.05)
    except KeyboardInterrupt:
        _beating.clear()
        ATTACHED.unlink(missing_ok=True)
        print("\ndetached - the agent runs untouched now")
    return 0


# ---------------------------------------------------------------- rules & misc

HOOK_ENTRY = """Add this inside the \"hooks\" object in ~/.claude/settings.json:

  "PreToolUse": [
    {
      "matcher": "Write|Edit|Bash|PowerShell",
      "hooks": [
        {
          "type": "command",
          "command": "%s \\"%s\\" hook",
          "timeout": 900
        }
      ]
    }
  ]

Drop the matcher to see every tool; keep it to skip the ~60ms on calls you would never
break on. Run /hooks afterwards to verify that Claude Code loaded it."""


def main(argv):
    args = argv[1:]
    op = args[0] if args else "help"

    if op == "hook":
        return cmd_hook()
    if op == "attach":
        return cmd_attach()
    if op == "install":
        runner = "python" if sys.platform == "win32" else "python3"
        print(HOOK_ENTRY % (runner, str(Path(__file__).resolve()).replace("\\", "/")))
        return 0
    if op == "break":
        if len(args) < 2:
            print("usage: agentdbg break \"Tool:regex\"  (! before the regex negates it)")
            return 2
        rules = load_rules()
        rule = parse_rule(args[1])
        rule["cwd"] = normalize_path(str(Path.cwd()))
        if rule in rules.setdefault("breaks", []):
            print(f"already armed: {args[1]}")
            return 0
        rules["breaks"].append(rule)
        save_rules(rules)
        print(f"breakpoint {len(rules['breaks'])}: {args[1]}")
        return 0
    if op == "deny":
        if len(args) < 2:
            print('usage: agentdbg deny "Tool:regex" ["reason shown to the model"]')
            return 2
        rules = load_rules()
        rule = parse_rule(args[1])
        rule["cwd"] = normalize_path(str(Path.cwd()))
        rule["why"] = args[2] if len(args) > 2 else ""
        if rule in rules.setdefault("denies", []):
            print(f"already denied: {args[1]}")
            return 0
        rules["denies"].append(rule)
        save_rules(rules)
        print(f"deny rule {len(rules['denies'])}: {args[1]}  (holds with no console attached)")
        return 0
    if op == "guard":
        # Keep the drive: dropping it left the rule as /Users/you/proj, so a write to
        # D:/Users/you/proj read as inside your project and sailed past the breakpoint.
        here = normalize_path(str(Path.cwd()))
        inside = rf"^{re.escape(here)}(?:/|$)"
        rules = load_rules()
        denies = [
            dict(parse_rule(f"Bash|PowerShell:{DESTRUCTIVE}"), cwd=here,
                 why="destructive shell command - do it yourself if you really mean it"),
            dict(parse_rule(r"Bash|PowerShell:git push .*(--force|-f)\b|git reset --hard"), cwd=here,
                 why="rewriting shared history needs a human"),
        ]
        breaks = [
            dict(parse_rule(r"Bash|PowerShell:git push|git commit|npm i|pip install"), cwd=here),
            dict(parse_rule(f"Write|Edit:!{inside}"), cwd=here),
        ]
        legacy_paths = {re.escape(here), re.escape(re.sub(r"^[A-Za-z]:", "", here))}

        def generated_here(rule, kind, defaults):
            if rule.get("cwd") not in (None, here):
                return False
            if any(all(rule.get(key) == default.get(key)
                       for key in ("tool", "pattern", "negate", "why"))
                   for default in defaults):
                return True
            if rule.get("cwd"):
                return False
            if kind == "denies":
                return rule.get("why") in {default.get("why") for default in defaults}
            return ((rule.get("tool") in ("Bash", "Bash|PowerShell")
                     and rule.get("pattern") == "git push|git commit|npm i|pip install")
                    or (rule.get("tool") == "Write|Edit" and rule.get("negate")
                        and rule.get("pattern") in legacy_paths))

        # Replace this project's defaults while retaining custom and other-project rules.
        for kind, defaults in (("denies", denies), ("breaks", breaks)):
            rules[kind] = [rule for rule in rules.get(kind, [])
                           if not generated_here(rule, kind, defaults)] + defaults
        save_rules(rules)
        print(f"guarded: 2 deny rules, 2 breakpoints (writes outside {Path.cwd()} pause)")
        return 0
    if op == "stats":
        tools, subjects, total, unattended = {}, {}, 0, 0
        here = normalize_path(str(Path.cwd()))
        for line in TRACE.read_text(encoding="utf-8").splitlines() if TRACE.exists() else []:
            try:
                call = json.loads(line)
            except ValueError:
                continue
            if call.get("cwd") and not same_path(call["cwd"], here):
                continue
            total += 1
            unattended += 1 if call.get("missed") else 0
            tools[call["tool"]] = tools.get(call["tool"], 0) + 1
            subjects[call["subject"][:80]] = subjects.get(call["subject"][:80], 0) + 1
        print(f"{total} tool calls seen")
        if unattended:
            print(f"{unattended} break(s) fired with no console attached "
                  f"(fail-open, went through) - `agentdbg attach` to drive them")
        for tool, n in sorted(tools.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {n:>5}  {tool}")
        print("most touched:")
        for subject, n in sorted(subjects.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {n:>5}  {subject}")
        return 0
    if op in ("step", "run"):
        rules = load_rules()
        rules["step"] = op == "step"
        save_rules(rules)
        print(f"step mode {'on' if rules['step'] else 'off'}")
        return 0
    if op == "drop":
        if len(args) < 3 or args[1] not in ("break", "deny") or not args[2].isdigit():
            print("usage: agentdbg drop break|deny <number from 'agentdbg rules'>")
            return 2
        kind = "breaks" if args[1] == "break" else "denies"
        rules = load_rules()
        listed = rules.setdefault(kind, [])
        index = int(args[2]) - 1
        if not 0 <= index < len(listed):
            print(f"no {args[1]} rule {args[2]} (there are {len(listed)})")
            return 2
        gone = listed.pop(index)
        save_rules(rules)
        print(f"dropped {args[1]} {args[2]}: {gone['tool']}:"
              f"{'!' if gone.get('negate') else ''}{gone.get('pattern', '')}")
        return 0
    if op == "clear":
        save_rules({"breaks": [], "denies": [], "step": False})
        print("cleared")
        return 0
    if op == "rules":
        rules = load_rules()
        print(f"step: {rules.get('step', False)}")
        for kind in ("denies", "breaks"):
            for i, r in enumerate(rules.get(kind, []), 1):
                label = "deny " if kind == "denies" else "break"
                why = f"   # {r['why']}" if r.get("why") else ""
                scope = f"   @ {r['cwd']}" if r.get("cwd") else "   @ all projects"
                print(f"  {label} {i}. {r['tool']}:"
                      f"{'!' if r.get('negate') else ''}{r.get('pattern', '')}{why}{scope}")
        print(f"attached: {attached()}   (deny rules hold either way)")
        print(f"edit directly: {RULES}")
        return 0
    if op == "watch":
        DIR.mkdir(parents=True, exist_ok=True)
        TRACE.touch()
        with open(TRACE, encoding="utf-8") as fh:
            fh.seek(0, 2)
            print("watching tool calls (ctrl-c to stop)")
            try:
                while True:
                    pos = fh.tell()
                    line = fh.readline()
                    if not line.endswith("\n"):   # nothing yet, or a hook mid-append
                        fh.seek(pos)              # rewind, or the record is lost torn in half
                        time.sleep(0.2)
                        continue
                    try:
                        call = json.loads(line)
                    except ValueError:
                        continue
                    print(f"  {call['tool']:<12} {call['subject'][:100]}")
            except KeyboardInterrupt:
                return 0
    print(__doc__)
    return 0 if op == "help" else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (OSError, ValueError) as exc:
        print(f"agentdbg: {exc}", file=sys.stderr)
        sys.exit(2)
