#!/usr/bin/env python3
"""Tiny client for the bridge, used by the island chat: `ctl.py interrupt` stops the
current run (like Esc in the CLI); the session is kept, so the next message resumes it.
`ctl.py inject TEXT` hands a message to the run in progress (Claude reads it at its next
step, like typing in the CLI while it works); prints {"injected": false} when no run takes it."""
import json, pathlib, sys, urllib.request

TOKEN = (pathlib.Path.home() / ".config/panacea-claude/token").read_text().strip()


def main():
    args = sys.argv[1:]
    if args == ["interrupt"]:
        path, body = "interrupt", b"{}"
    elif len(args) >= 2 and args[0] == "inject":
        words, files, rest = [], [], args[1:]
        while rest:   # inject TEXT [--file PATH]...: the files go with it, like attachments
            a = rest.pop(0)
            if a == "--file" and rest:
                files.append(rest.pop(0))
            else:
                words.append(a)
        path, body = "inject", json.dumps({"text": " ".join(words), "files": files}).encode()
    else:
        print("usage: ctl.py interrupt | ctl.py inject TEXT [--file PATH]...", file=sys.stderr)
        return 2
    req = urllib.request.Request(f"http://127.0.0.1:47321/v1/{path}", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        print(urllib.request.urlopen(req, timeout=5).read().decode())
    except OSError as e:
        print(f"bridge unreachable: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
