#!/usr/bin/env python3
"""Approval cards for the island chat.

A minimal MCP server (stdio, JSON-RPC) with one tool, `approve`, used as
Claude Code's --permission-prompt-tool by bridge.py. Whenever Claude wants to
do something that isn't pre-approved (run a command, edit a file...):

  - the chat shows an approval card in the conversation (approval.json,
    read by the patched ChatView; its buttons answer with --answer), and
  - Panacea's notification approval card fires too, for when you're elsewhere
    (it expires after 30 s; the in-chat card waits up to 2 minutes).

Whichever you answer first wins and the other is withdrawn. No answer = denied.

    approve-mcp.py                       the MCP server (started by Claude Code)
    approve-mcp.py --answer ID allow|deny   answer from the chat's card
"""
import html, json, os, pathlib, subprocess, sys, time, uuid

CACHE = pathlib.Path.home() / ".cache/panacea-claude"
APPROVAL = CACHE / "approval.json"     # the pending request, {} when none
LIVE = CACHE / "live.json"             # bridge.py's progress (for "why")
ICON = str(pathlib.Path.home() / ".config/panacea-claude/claude-critter.svg")   # the pixel Claude from the chat
WAIT = 120                             # seconds the in-chat card waits


def answer_file(rid):
    return CACHE / f"answer-{rid}"


if len(sys.argv) == 4 and sys.argv[1] == "--answer":
    rid, choice = sys.argv[2], sys.argv[3]
    if choice in ("allow", "deny") and all(c.isalnum() for c in rid):
        answer_file(rid).write_text(choice)
    sys.exit(0)

TOOL = {
    "name": "approve",
    "description": "Ask the user to allow or deny a tool call.",
    "inputSchema": {"type": "object", "properties": {
        "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"]},
}


def write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def last_said():
    """The last thing Claude said before asking: usually what it's about to do."""
    try:
        steps = json.loads(LIVE.read_text()).get("steps", [])
        for s in reversed(steps):
            if s.get("k") == "text":
                return s.get("t", "")
    except (OSError, ValueError):
        pass
    return ""


def describe(tool, inp):
    """-> (title, body, why)"""
    why = str(inp.get("description") or "") or last_said()
    if tool == "Bash":
        return "Run a command", inp.get("command", ""), why
    if tool in ("Edit", "MultiEdit"):
        return "Edit a file", inp.get("file_path", ""), why
    if tool == "Write":
        return "Write a file", inp.get("file_path", ""), why
    if tool == "NotebookEdit":
        return "Edit a notebook", inp.get("notebook_path", ""), why
    return f"Use {tool}", json.dumps(inp, ensure_ascii=False), why


def clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def close_notification(nid):
    if nid:
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                        "--object-path", "/org/freedesktop/Notifications",
                        "--method", "org.freedesktop.Notifications.CloseNotification", str(nid)],
                       capture_output=True, timeout=5)



# ----------------------------------------------------------------- safe auto mode
# Commands that only look at the system run without a card, so Claude can
# investigate freely (logs, configs, versions, services) and ask only before it
# changes something. Anything not clearly read-only still gets a card: writes,
# redirections into files, root, package changes, service changes, secrets.
import re, shlex

READ_ONLY = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "stat", "file", "du", "df",
    "free", "uptime", "uname", "whoami", "id", "groups", "date", "which", "whereis", "type", "echo",
    "printf", "pwd", "lsblk", "lspci", "lsusb", "lscpu", "lsmod", "ss", "ps", "pgrep", "readlink",
    "realpath", "basename", "dirname", "sort", "uniq", "cut", "tr", "jq", "column", "diff", "cmp",
    "md5sum", "sha1sum", "sha256sum", "fc-list", "fc-match", "locale", "sensors", "true", "test",
    "nproc", "getent", "tree", "less", "more", "xxd", "hexdump", "strings", "lsof", "findmnt",
    "inxi", "fastfetch", "neofetch", "vainfo", "glxinfo", "vulkaninfo", "wpctl", "pactl", "upower",
    "coredumpctl", "hostnamectl", "timedatectl", "localectl", "loginctl", "resolvectl", "dmesg",
}
SUBCOMMANDS = {   # tools that are read-only only with these first arguments
    "systemctl": {"status", "is-active", "is-enabled", "is-failed", "list-units", "list-unit-files",
                  "list-timers", "list-sockets", "show", "cat", "list-dependencies", "--version"},
    "journalctl": None,       # any reading flags; writing ones are refused below
    "pacman": None, "yay": None, "paru": None,   # only query flags, checked below
    "hyprctl": {"monitors", "clients", "workspaces", "activeworkspace", "activewindow", "version",
                "getoption", "devices", "binds", "layers", "splash", "systeminfo", "instances",
                "cursorpos", "animations", "rollinglog", "globalshortcuts", "-j"},
    "nmcli": {"-t", "-f", "-g", "general", "device", "connection", "radio", "networking", "monitor"},
    "ip": {"-br", "-j", "-c", "-4", "-6", "-d", "addr", "address", "a", "link", "l", "route", "r",
           "neigh", "n", "rule", "monitor"},
    "mullvad": {"status", "version", "relay", "lockdown-mode", "auto-connect", "dns", "tunnel", "obfuscation"},
    "nvidia-smi": None, "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame"},
    "find": None, "flatpak": {"list", "info", "--version"}, "bluetoothctl": {"show", "devices", "info", "list"},
    "sed": None, "awk": None, "qs": None,
}
SECRETS = re.compile(r"\.ssh|\.gnupg|keyring|proton|vault|\.password|\.env\b|token|"
                     r"secret|credential|account\s+get|/etc/shadow|\.pki", re.I)
NO_REDIRECT = re.compile(r"(?<![0-9&])>|>>|<\(|\$\(|`|\bsudo\b|\bpkexec\b|\bdoas\b|\bsu\b")


def _args_ok(prog, args):
    allowed = SUBCOMMANDS.get(prog, "missing")
    if prog in READ_ONLY:
        return True
    if allowed == "missing":
        return False
    first = next((a for a in args if not a.startswith("--") or a in (allowed or ())), "")
    if prog == "journalctl":
        return not any(a.startswith(("--vacuum", "--rotate", "--flush", "--sync", "--relinquish", "--setup-keys")) for a in args)
    if prog in ("pacman", "yay", "paru"):
        ops = [a for a in args if a.startswith("-") and not a.startswith("--")]
        return bool(ops) and all(o.startswith("-Q") or o in ("-Ss", "-Si", "-Sl", "-Fl", "-Fy") or o.startswith("-Ss") for o in ops) \
            and not any(a in ("--sync", "--remove", "--upgrade") for a in args)
    if prog == "nvidia-smi":
        return all(a.startswith(("--query", "--format", "-q", "-L", "--list")) or not a.startswith("-") for a in args)
    if prog == "find":
        return not any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for a in args)
    if prog == "sed":
        return not any(a.startswith("-i") or a == "--in-place" for a in args) and not any(re.search(r"(^|;)\s*[we]\b", a) for a in args)
    if prog == "awk":
        return not any(re.search(r"system|print\s*>|getline|\|", a) for a in args)
    if prog == "qs":
        return "ipc" in args and ("show" in args) and "call" not in args
    if prog == "nmcli":
        return not any(a in ("up", "down", "modify", "add", "delete", "reload", "on", "off", "connect", "disconnect") for a in args)
    if prog == "ip":
        return not any(a in ("add", "del", "delete", "set", "change", "replace", "flush", "append") for a in args)
    if prog == "mullvad":
        return bool(args) and args[0] in allowed and not any(a in ("set", "login", "logout", "connect", "disconnect", "reset", "revoke") for a in args) \
            and "account" not in args
    sub = next((a for a in args if not a.startswith("-")), "")
    return sub in allowed or (not sub and all(a in allowed for a in args))


def auto_ok(tool, inp):
    """True when this call only reads: it can run without a card."""
    if tool != "Bash":
        return False
    cmd = str(inp.get("command", ""))
    if not cmd.strip() or "\n" in cmd.strip() or SECRETS.search(cmd) or NO_REDIRECT.search(cmd.replace("2>/dev/null", "").replace(">/dev/null", "").replace("2>&1", "")):
        return False
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return False
    parts, cur = [], []
    for t in tokens:
        if t in ("|", "||", "&&", ";"):
            parts.append(cur); cur = []
        elif t in ("&", ">", ">>", "<", "<<", "|&"):
            return False
        else:
            cur.append(t)
    parts.append(cur)
    for part in parts:
        if not part or "=" in part[0]:
            return False
        prog = os.path.basename(part[0])
        if not _args_ok(prog, part[1:]):
            return False
    return True

def ask(tool, inp, tuid=""):
    if auto_ok(tool, inp):          # read-only: no card (safe auto mode)
        return {"behavior": "allow", "updatedInput": inp}
    title, body, why = describe(tool, inp)
    rid = uuid.uuid4().hex[:12]
    CACHE.mkdir(parents=True, exist_ok=True)
    write_json(APPROVAL, {"id": rid, "tuid": tuid, "title": title, "body": clip(body, 1200), "why": clip(why, 300)})

    note = None
    try:   # -p prints the notification id first, then the chosen action when answered
        note = subprocess.Popen(
            ["notify-send", "-p", "--app-name", "Panacea Claude", "--icon", ICON,
             "--urgency", "normal", "--expire-time", "30000",
             "--action=panacea-allow=Allow", "--action=panacea-deny=Deny",
             title,   # the card already says "Panacea Claude"
             html.escape(clip((why + "\n" if why else "") + str(body), 400))],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        nid = (note.stdout.readline() or "").strip()
    except OSError:
        nid = ""

    choice, end = "", time.time() + WAIT
    while not choice and time.time() < end:
        f = answer_file(rid)
        if f.exists():
            choice = f.read_text().strip()
            f.unlink(missing_ok=True)
            break
        if note and note.poll() is not None:        # the notification was answered or expired
            act = (note.stdout.read() or "").strip().splitlines()
            act = act[-1] if act else ""
            note = None
            if act in ("panacea-allow", "panacea-deny"):
                choice = "allow" if act == "panacea-allow" else "deny"
                break
        time.sleep(0.2)

    write_json(APPROVAL, {})
    # what you decided, for bridge.py: it pairs this with the tool's result and
    # leaves a "done / failed / denied" record in the conversation
    if tuid and all(c.isalnum() or c in "_-" for c in tuid):
        write_json(CACHE / f"decision-{tuid}.json",
                   {"title": title, "body": clip(body, 300), "choice": choice or "timeout"})
    if note:                                         # answered in the chat: withdraw the notification
        close_notification(nid)
        note.kill()
    if choice == "allow":
        return {"behavior": "allow", "updatedInput": inp}
    why_no = "The user denied this." if choice == "deny" else "No answer from the user."
    return {"behavior": "deny", "message": why_no + " Don't retry it; tell the user what you wanted to do."}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:          # notifications (initialized, cancelled...)
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "panacea", "version": "2"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {}) or {}
        res = ask(str(args.get("tool_name", "tool")), args.get("input") or {}, str(args.get("tool_use_id") or ""))
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(res)}]}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})
