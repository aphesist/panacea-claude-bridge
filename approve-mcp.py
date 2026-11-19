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


def ask(tool, inp):
    title, body, why = describe(tool, inp)
    rid = uuid.uuid4().hex[:12]
    CACHE.mkdir(parents=True, exist_ok=True)
    write_json(APPROVAL, {"id": rid, "title": title, "body": clip(body, 1200), "why": clip(why, 300)})

    note = None
    try:   # -p prints the notification id first, then the chosen action when answered
        note = subprocess.Popen(
            ["notify-send", "-p", "--app-name", "Panacea Claude", "--icon", ICON,
             "--urgency", "normal", "--expire-time", "30000",
             "--action=panacea-allow=Allow", "--action=panacea-deny=Deny",
             "Claude: " + title.lower(), html.escape(clip((why + "\n" if why else "") + str(body), 400))],
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
        res = ask(str(args.get("tool_name", "tool")), args.get("input") or {})
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(res)}]}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})
