#!/usr/bin/env python3
"""Tiny client for the bridge, used by the island chat: `ctl.py interrupt` stops the
current run (like Esc in the CLI); the session is kept, so the next message resumes it."""
import pathlib, sys, urllib.request

TOKEN = (pathlib.Path.home() / ".config/panacea-claude/token").read_text().strip()


def main():
    if sys.argv[1:] != ["interrupt"]:
        print("usage: ctl.py interrupt", file=sys.stderr)
        return 2
    req = urllib.request.Request("http://127.0.0.1:47321/v1/interrupt", data=b"{}", method="POST",
                                 headers={"Authorization": "Bearer " + TOKEN})
    try:
        print(urllib.request.urlopen(req, timeout=5).read().decode())
    except OSError as e:
        print(f"bridge unreachable: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
