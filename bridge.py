#!/usr/bin/env python3
"""Local bridge: Panacea island chat -> Claude Code (your Claude subscription).

Panacea's chat (scripts/chat.py) speaks the OpenAI /chat/completions format.
This answers that format on 127.0.0.1 only and forwards each message to
`claude -p`, resuming the same Claude Code session while the conversation
continues, so Claude keeps context without resending the whole history.

Claude runs from your home folder, so it shares Claude Code's memory and
CLAUDE.md for it (the same "system" context as your terminal sessions).

Security:
  - listens on 127.0.0.1 only, and requires the bearer token in
    ~/.config/panacea-claude/token (so web pages can't use it via localhost)
  - without asking: web search, reading web pages, reading files (except
    secrets: ~/.ssh, ~/.gnupg, keyrings, this bridge's token...)
  - everything else (commands, opening apps, file edits) shows an Allow/Deny
    card in the island (approve-mcp.py); no answer within 30 s = denied.
    Root work goes through pkexec, i.e. Panacea's own password prompt.
"""
import base64, hashlib, json, mimetypes, os, pathlib, secrets, subprocess, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = pathlib.Path.home()
HERE = pathlib.Path(__file__).resolve().parent              # sysprofile.py and approve-mcp.py sit next to this file
HOST, PORT = "127.0.0.1", 47321
CLAUDE = str(HOME / ".local/bin/claude")
CONF = HOME / ".config/panacea-claude"
STATE = HOME / ".local/state/panacea-claude/state.json"
WORKDIR = HOME                                           # same project (memory, CLAUDE.md) as your sessions
APPROVE = pathlib.Path(__file__).resolve().with_name("approve-mcp.py")
ATTACH = HOME / ".cache/panacea-claude/attachments"
LIVE = HOME / ".cache/panacea-claude/live.json"         # progress for the chat (patched ChatView)
CACHE = LIVE.parent                                       # approve-mcp.py leaves its decisions here
TIMEOUT = 590                                            # chat.py (patched) waits 600 s

SYSTEM = (
    "You are the sysadmin of this computer, answering in a small chat panel on its desktop "
    "(the Panacea shell's island, Hyprland on Arch). You know the machine (profile below) and look things up "
    "on it before guessing: check logs (journalctl), configs, package versions and running services, "
    "and use the web for current docs and known issues. Diagnose first, then fix with the smallest change, "
    "and say how to undo anything non-trivial. "
    "The panel shows plain text only: no Markdown headings, tables or bold; short paragraphs and simple '-' lists are fine. "
    "Keep answers concise unless asked for detail. Attached files are given as paths you may Read. "
    "You can search the web, read files, run commands, open apps (`hyprctl dispatch exec <app>`, `xdg-open <file-or-url>`) "
    "and edit files. Commands and edits show the owner an Allow/Deny card: right before each one, say in one short "
    "sentence what you are about to do and why, so the card can explain it. If one is denied, say so and stop. "
    "For anything that needs root, use `pkexec <command>` (never sudo): it asks for the password in the island. "
    "Your memory and notes are shared with the owner's other Claude Code sessions on this machine."
)
PROFILE = CACHE / "system-profile.md"       # sysprofile.py: hardware, OS, services + the owner's notes
PROFILE_MAX_AGE = 6 * 3600


def profile():
    """The machine profile, rebuilt when missing, older than a few hours or after a package change."""
    try:
        age = time.time() - PROFILE.stat().st_mtime
        stale = age > PROFILE_MAX_AGE or os.path.getmtime("/var/log/pacman.log") > PROFILE.stat().st_mtime \
            or os.path.getmtime(HOME / ".config/panacea-claude/notes.md") > PROFILE.stat().st_mtime
    except OSError:
        stale = True
    if stale:
        subprocess.run(["python3", "-I", str(HERE / "sysprofile.py"), "--write"],
                       capture_output=True, timeout=30)
    try:
        return PROFILE.read_text()
    except OSError:
        return ""
ALLOWED = ["WebSearch", "WebFetch", "Read", "Glob", "Grep"]
DENIED = [f"Read({p})" for p in ("~/.ssh/**", "~/.gnupg/**", "~/.local/share/keyrings/**",
                                 "~/.config/panacea-claude/**", "~/.config/proton*/**",
                                 "~/.local/share/proton*/**", "~/.local/share/panacea/vault*")]
MCP = json.dumps({"mcpServers": {"panacea": {"command": "python3", "args": ["-I", str(APPROVE)]}}})

for d in (CONF, STATE.parent, WORKDIR, ATTACH):
    d.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = CONF / "token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    TOKEN_FILE.chmod(0o600)
TOKEN = TOKEN_FILE.read_text().strip()
LOCK = threading.Lock()
CARDS = []   # this run's answered approvals with their outcome (done / failed / denied)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(s):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s))
    os.replace(tmp, STATE)


def text_of(content):
    """Flatten OpenAI content (string or parts). Images are saved for Read."""
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if part.get("type") == "text":
            out.append(part.get("text", ""))
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:
                mime, b64 = url[5:].split(";base64,", 1)
                data = base64.b64decode(b64)
                ext = mimetypes.guess_extension(mime) or ".bin"
                path = ATTACH / (hashlib.sha256(data).hexdigest()[:16] + ext)
                path.write_bytes(data)
                out.append(f"[Attached image: {path}]")
    return "\n\n".join(x for x in out if x)


def write_live(obj):
    tmp = LIVE.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, LIVE)


def step_of(block):
    """A content block from the stream -> a short progress line, or None."""
    t = block.get("type")
    if t == "thinking" and block.get("thinking", "").strip():
        return {"k": "think", "t": block["thinking"].strip()[-600:]}
    if t == "text" and block.get("text", "").strip():
        return {"k": "text", "t": block["text"].strip()[:600]}
    if t == "tool_use":
        name, inp = block.get("name", ""), block.get("input") or {}
        if name in ("ToolSearch", "TodoWrite"):      # internal bookkeeping, not worth a line
            return None
        label = {
            "WebSearch": lambda: "Searching the web: " + str(inp.get("query", "")),
            "WebFetch": lambda: "Reading " + str(inp.get("url", "")),
            "Read": lambda: "Reading " + str(inp.get("file_path", "")),
            "Glob": lambda: "Looking for " + str(inp.get("pattern", "")),
            "Grep": lambda: "Searching files for " + str(inp.get("pattern", "")),
            "Bash": lambda: str(inp.get("description") or ("Running " + str(inp.get("command", "")))),
            "Edit": lambda: "Editing " + str(inp.get("file_path", "")),
            "Write": lambda: "Writing " + str(inp.get("file_path", "")),
        }.get(name, lambda: "Using " + name)()
        return {"k": "tool", "t": label[:300]}
    return None


def card_of(block):
    """A tool_result whose call went through an approval -> {title, body, decision, ok}."""
    if block.get("type") != "tool_result":
        return None
    f = CACHE / f"decision-{block.get('tool_use_id', '')}.json"
    try:
        d = json.loads(f.read_text())
        f.unlink()
    except (OSError, ValueError):
        return None          # not one that asked you (auto-allowed reads and searches)
    return {"title": d.get("title", ""), "body": d.get("body", ""),
            "decision": d.get("choice", ""), "ok": not block.get("is_error", False)}


def ask_claude(messages, model):
    last = messages[-1]
    if last.get("role") != "user":
        raise ValueError("last message is not from the user")
    prompt = text_of(last.get("content"))

    # Continue the same Claude Code session if the panel's previous assistant
    # message is the reply we gave last time; otherwise start fresh and pass
    # the visible history along as context.
    st = load_state()
    prev = messages[-2] if len(messages) >= 2 else None
    resume = None
    if prev and prev.get("role") == "assistant" and st.get("last_reply") == text_of(prev.get("content")):
        resume = st.get("session_id")
    elif len(messages) > 1:
        hist = "\n\n".join(f"{m['role']}: {text_of(m.get('content'))}" for m in messages[:-1])
        prompt = f"(Earlier in this chat:)\n{hist}\n\n(New message:)\n{prompt}"

    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
           "--append-system-prompt", SYSTEM + "\n\n" + profile(),
           "--mcp-config", MCP, "--strict-mcp-config",
           "--permission-prompt-tool", "mcp__panacea__approve",
           "--allowedTools", *ALLOWED, "--disallowedTools", *DENIED]
    if model and model not in ("claude", "default"):
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--", prompt]

    # Stream the run: every thinking block, remark and tool call goes to
    # live.json so the chat can show what Claude is doing while it works.
    live = {"busy": True, "steps": [], "started": time.time(), "at": last.get("at")}
    write_live(live)
    out, tail = None, []
    errf = tempfile.TemporaryFile(mode="w+")   # a file, not a pipe: a full pipe would stall the run
    proc = subprocess.Popen(cmd, cwd=WORKDIR, stdout=subprocess.PIPE, stderr=errf, text=True)
    killer = threading.Timer(TIMEOUT, proc.kill)
    killer.start()
    try:
        for line in proc.stdout:
            tail = (tail + [line])[-5:]
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    st = step_of(block)
                    if st:
                        live["steps"] = (live["steps"] + [st])[-12:]
                        write_live(live)
            elif ev.get("type") == "user":
                # tool results: an approval you answered becomes a record of what happened
                for block in (ev.get("message") or {}).get("content") or []:
                    card = card_of(block) if isinstance(block, dict) else None
                    if card:
                        CARDS.append(card)
                        live["cards"] = CARDS[-8:]
                        write_live(live)
            elif ev.get("type") == "result":
                out = ev
        proc.wait()
    finally:
        killer.cancel()   # live.json is closed by do_POST, together with the reply
    if out is None:
        if proc.returncode in (-9, 137):
            raise subprocess.TimeoutExpired(cmd, TIMEOUT)
        errf.seek(0)
        err = errf.read()
        raise RuntimeError((err or "".join(tail) or "no output from claude").strip()[:400])
    if out.get("is_error"):
        raise RuntimeError(str(out.get("result") or out.get("subtype"))[:400])
    reply = out.get("result", "")
    save_state({"session_id": out.get("session_id"), "last_reply": reply})
    return reply


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            return self.reply(404, {"error": "not found"})
        if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN):
            return self.reply(401, {"error": "bad token"})
        at = None
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(min(n, 50 * 1024 * 1024)))
            msgs = req.get("messages") or []
            at = (msgs[-1] if msgs else {}).get("at")
            with LOCK:
                CARDS.clear()
                answer = ask_claude(msgs, req.get("model", ""))
        except subprocess.TimeoutExpired:
            answer = "Claude took too long (over 10 minutes) and was stopped."
        except Exception as e:
            answer = f"Claude bridge error: {e}"
        # The reply also goes to live.json, tagged with the message it answers
        # ("at", set by the chat). If the chat page was closed meanwhile (you left
        # it, or answered an approval from the notification), its request died
        # with it; the chat picks the reply up from here when it opens again.
        write_live({"busy": False, "steps": [], "last": {"at": at, "answer": answer, "cards": CARDS[-8:]}})
        self.reply(200, {"object": "chat.completion",
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": answer}}]})


if __name__ == "__main__":
    threading.Thread(target=profile, daemon=True).start()   # fresh machine profile at startup
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
