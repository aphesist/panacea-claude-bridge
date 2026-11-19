#!/usr/bin/env python3
"""Approval cards for the island chat.

A minimal MCP server (stdio, JSON-RPC) with one tool, `approve`, used as
Claude Code's --permission-prompt-tool by bridge.py: whenever Claude wants to
do something that isn't pre-approved (run a command, edit a file...), it shows
Panacea's approval card (a notification from "Panacea Claude" with Allow /
Deny, 30 s countdown) and returns your answer. No answer = denied.
"""
import html, json, subprocess, sys

TOOL = {
    "name": "approve",
    "description": "Ask the user to allow or deny a tool call.",
    "inputSchema": {"type": "object", "properties": {
        "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"]},
}


def describe(tool, inp):
    """-> (card title, card body)"""
    if tool == "Bash":
        return "Claude wants to run a command", inp.get("command", "")
    if tool in ("Edit", "MultiEdit"):
        return "Claude wants to edit a file", inp.get("file_path", "")
    if tool == "Write":
        return "Claude wants to write a file", inp.get("file_path", "")
    if tool == "NotebookEdit":
        return "Claude wants to edit a notebook", inp.get("notebook_path", "")
    return f"Claude wants to use {tool}", json.dumps(inp, ensure_ascii=False)


def ask(tool, inp):
    title, body = describe(tool, inp)
    body = str(body)
    if len(body) > 400:
        body = body[:400] + "…"
    try:
        r = subprocess.run(
            ["notify-send", "--app-name", "Panacea Claude", "--icon", "dialog-question",
             "--urgency", "normal", "--expire-time", "30000",
             "--action=panacea-allow=Allow", "--action=panacea-deny=Deny",
             title, html.escape(body)],
            capture_output=True, text=True, timeout=40)
        choice = r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        choice = ""
    if choice == "panacea-allow":
        return {"behavior": "allow", "updatedInput": inp}
    why = "The user denied this." if choice == "panacea-deny" else "No answer from the user (the approval card expired)."
    return {"behavior": "deny", "message": why}


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
            "capabilities": {"tools": {}}, "serverInfo": {"name": "panacea", "version": "1"}}})
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
