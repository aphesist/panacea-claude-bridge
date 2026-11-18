#!/usr/bin/env python3
"""Local bridge: Panacea island chat -> Claude Code (your Claude subscription).

Panacea's chat (scripts/chat.py) speaks the OpenAI /chat/completions format.
This answers that format on 127.0.0.1 only and forwards each message to
`claude -p`, resuming the same Claude Code session while the conversation
continues, so Claude keeps context without resending the whole history.

Security:
  - listens on 127.0.0.1 only, and requires the bearer token in
    ~/.config/panacea-claude/token (so web pages can't use it via localhost)
  - Claude gets read-only web tools, plus Read limited to this bridge's
    attachment folder; no shell, no file edits
"""
import base64, hashlib, json, mimetypes, os, pathlib, secrets, subprocess, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = pathlib.Path.home()
HOST, PORT = "127.0.0.1", 47321
CLAUDE = str(HOME / ".local/bin/claude")
CONF = HOME / ".config/panacea-claude"
STATE = HOME / ".local/state/panacea-claude/state.json"
WORKDIR = HOME / ".local/share/panacea-claude"           # sessions are grouped under this "project"
ATTACH = HOME / ".cache/panacea-claude/attachments"
TIMEOUT = 85                                             # chat.py gives up after 90 s

SYSTEM = (
    "You are answering in a small chat panel on the user's Linux desktop "
    "(the Panacea shell's island, Hyprland on Arch). The panel shows plain text only: "
    "do not use Markdown headings, tables or bold; short paragraphs and simple '-' lists are fine. "
    "Keep answers concise unless asked for detail. Attached files are given as paths you may Read."
)

for d in (CONF, STATE.parent, WORKDIR, ATTACH):
    d.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = CONF / "token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    TOKEN_FILE.chmod(0o600)
TOKEN = TOKEN_FILE.read_text().strip()
LOCK = threading.Lock()


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

    cmd = [CLAUDE, "-p", "--output-format", "json",
           "--append-system-prompt", SYSTEM,
           "--tools", "Read", "WebSearch", "WebFetch",
           "--allowedTools", f"Read(/{ATTACH}/**)", "WebSearch", "WebFetch"]
    if model and model not in ("claude", "default"):
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--", prompt]

    r = subprocess.run(cmd, cwd=WORKDIR, capture_output=True, text=True, timeout=TIMEOUT)
    try:
        out = json.loads(r.stdout)
    except Exception:
        raise RuntimeError((r.stderr or r.stdout or "no output from claude").strip()[:400])
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
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(min(n, 50 * 1024 * 1024)))
            with LOCK:
                answer = ask_claude(req.get("messages") or [], req.get("model", ""))
        except subprocess.TimeoutExpired:
            answer = "Claude took too long (over 85 s) - try a shorter question."
        except Exception as e:
            answer = f"Claude bridge error: {e}"
        self.reply(200, {"object": "chat.completion",
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": answer}}]})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
