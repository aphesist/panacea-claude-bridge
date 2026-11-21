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
import base64, hashlib, json, mimetypes, os, pathlib, secrets, signal, subprocess, tempfile, threading, time
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
TIMEOUT = 0                                              # no limit: a reply runs until done (Stop ends it); chat.py waits as long

SYSTEM = (
    "You are the sysadmin of this computer, answering in a small chat panel on its desktop "
    "(the Panacea shell's island, Hyprland on Arch). You know the machine (profile below) and look things up "
    "on it before guessing: check logs (journalctl), configs, package versions and running services, "
    "and use the web for current docs and known issues. Diagnose first, then fix with the smallest change, "
    "and say how to undo anything non-trivial. "
    "The panel renders Markdown: paragraphs, headings (#..###), '-' and '1.' lists (nested by two spaces, '- [ ]' task "
    "boxes), **bold**, *italic*, ~~strikethrough~~ (all of them also around `code`), > quotes, --- rules, tables, "
    "`inline code` (shown in a colour; one click copies it) and ``` fenced blocks (shown in a box; one click copies the "
    "whole block), and ![caption](path) on its own line, which shows a picture (or a video's first frame with a play mark) "
    "right in the chat; a click opens it (pictures in the island viewer, videos in mpv). Put anything the owner may type, paste or look for - commands, paths, "
    "package and service names, settings, keys - in inline code, and runnable steps in a fenced block, one command per "
    "line, nothing else in it (no prompts like $, no comments the shell can't take). Use a list for steps or several items. "
    "Links open on click: when the owner would want to see something rather than type it - a picture, screenshot, "
    "document, folder, log file, web page - give it as a Markdown link with a short name, e.g. [the screenshot](~/Pictures/x.png) "
    "or [the wiki page](https://wiki.archlinux.org/...); absolute or ~ paths open in their app, folders in the file manager. "
    "When they'd want to paste or type it (a path for a config, a command, a value), use inline code, which copies. "
    "Keep answers concise unless asked for detail. Attached files are given as paths you may Read. "
    "You can search the web, read files, run commands, open apps (`hyprctl dispatch exec <app>`, `xdg-open <file-or-url>`) "
    "and edit files. You run in auto mode: most actions just run; destructive ones (deleting trees, root, disks, "
    "force pushes, removing packages, power) show the owner an Allow/Deny card, and a safety check may block risky "
    "actions they didn't ask for. Before each action, say in one short sentence what you are about to do and why, "
    "so a card can explain it. If one is denied or blocked, say so and stop; don't look for a way around it. "
    "For anything that needs root, use `pkexec <command>` (never sudo): it asks for the password in the island. "
    "Your memory and notes are shared with the owner's other Claude Code sessions on this machine."
)
# ----------------------------------------------------------------- memory across clears
# One Claude for the island: the chat's "new chat" only clears the view, the same Claude
# Code session carries on (it compacts itself when long). Beyond the session, two files:
#   notebook.md  - Claude's own working notes (what's in progress, decisions, things to carry
#                  forward). Claude keeps it; its contents ride along with every message.
#   journal/     - every exchange, logged by the bridge (YYYY-MM.md). Claude searches it when
#                  something from before isn't in context; a fresh session starts with its tail.
NOTES = HOME / ".local/share/panacea-claude/notebook"
NOTEBOOK = NOTES / "notebook.md"
JOURNAL = NOTES / "journal"
NOTEBOOK_MAX = 10000          # chars of the notebook sent along
SESSION_MAX = 80 * 1024 * 1024   # a session file past this starts afresh (the notebook carries on)
NOTEBOOK_SEED = (
    "# Island notebook\n\n"
    "Claude's working notes for the Panacea island chat. Kept across cleared chats and new sessions.\n\n"
    "## In progress\n\n## Decisions and preferences\n\n## To remember\n")
NOTEBOOK_PROMPT = (
    "Your notebook is {nb}: your own working notes, kept across cleared chats and new sessions, and sent "
    "with every message (below). Keep it current yourself with Edit: what is in progress and where it stands, "
    "decisions made, what the owner asked you to keep in mind, follow-ups. Update it when something worth "
    "carrying forward happens (not for every message), keep it short and tidy (under ~150 lines), and rewrite "
    "or remove stale entries instead of piling up. Lasting facts about the owner or the machine still go to "
    "your memory files as usual. Every exchange is also logged automatically in {jr}/YYYY-MM.md; when the owner "
    "refers to something earlier that isn't in your context, search it (Grep) before saying you don't know. "
    "The owner doesn't need to manage any of this.")


def notebook():
    try:
        t = NOTEBOOK.read_text()
    except OSError:
        NOTES.mkdir(parents=True, exist_ok=True)
        NOTEBOOK.write_text(NOTEBOOK_SEED)
        t = NOTEBOOK_SEED
    if len(t) > NOTEBOOK_MAX:
        t = t[:NOTEBOOK_MAX] + "\n[... notebook cut here: it is too long, tidy it up]"
    return (NOTEBOOK_PROMPT.format(nb=NOTEBOOK, jr=JOURNAL)
            + "\n\n<notebook>\n" + t.strip() + "\n</notebook>")


def journal_add(prompt, answer, tools):
    """Append one exchange to this month's journal."""
    try:
        JOURNAL.mkdir(parents=True, exist_ok=True)
        clip = lambda x, n: x if len(x) <= n else x[:n] + " [...]"
        entry = f"\n## {time.strftime('%Y-%m-%d %H:%M')}\n\nOwner: {clip(prompt.strip(), 2000)}\n\n"
        if tools:
            entry += "Tools: " + "; ".join(clip(t, 120) for t in tools[:15]) + ("; ..." if len(tools) > 15 else "") + "\n\n"
        entry += f"Claude: {clip(answer.strip(), 4000)}\n"
        with open(JOURNAL / time.strftime("%Y-%m.md"), "a") as f:
            f.write(entry)
    except OSError:
        pass


def journal_tail(n=8000):
    """The end of the journal (this month, else last month), for a fresh session."""
    try:
        files = sorted(JOURNAL.glob("*.md"))
    except OSError:
        return ""
    t = ""
    for f in reversed(files[-2:]):
        t = f.read_text() + t
        if len(t) >= n:
            break
    if len(t) > n:
        t = t[-n:]
        t = t[t.find("\n## ") + 1:] if "\n## " in t else t
    return t.strip()


def session_ok(sid):
    if not sid:
        return False
    f = HOME / ".claude/projects" / str(WORKDIR).replace("/", "-") / f"{sid}.jsonl"
    try:
        return f.stat().st_size < SESSION_MAX
    except OSError:
        return False


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
ALLOWED = ["WebSearch", "WebFetch", "Read", "Glob", "Grep",
           "Edit(~/.local/share/panacea-claude/notebook/notebook.md)",   # its own notebook: no card
           "Write(~/.local/share/panacea-claude/notebook/notebook.md)"]
DENIED = [f"Read({p})" for p in ("~/.ssh/**", "~/.gnupg/**", "~/.local/share/keyrings/**",
                                 "~/.config/panacea-claude/**", "~/.config/proton*/**",
                                 "~/.local/share/proton*/**", "~/.local/share/panacea/vault*")]
# Auto mode, like the CLI's: a classifier lets through what you asked for and blocks
# risky things you didn't (Claude is told why and carries on). These always ask
# anyway, with the island's Allow/Deny card: deleting trees, root, disks, history
# rewrites, removing packages, ending the session or powering off.
ASK = [f"Bash({c})" for c in (
    "rm -rf *", "rm -fr *", "rm -r *", "rm -R *", "find * -delete*", "shred *",
    "sudo *", "pkexec *", "su *", "doas *", "run0 *",
    "dd *", "mkfs*", "wipefs *", "fdisk *", "parted *", "sgdisk *", "cryptsetup *", "mount *", "umount *",
    "git push --force*", "git push -f*", "git push * --force*", "git reset --hard*", "git clean -f*",
    "git branch -D *", "git checkout -- *", "git restore *",
    "pacman -R*", "yay -R*", "paru -R*", "flatpak uninstall*",
    "systemctl disable*", "systemctl mask*", "systemctl --user disable*", "systemctl --user mask*",
    "reboot*", "poweroff*", "shutdown*", "halt*", "systemctl reboot*", "systemctl poweroff*",
    "systemctl suspend*", "systemctl hibernate*", "loginctl terminate*", "hyprctl dispatch exit*",
    "killall *", "pkill *", "kill -9 *", "chmod -R *", "chown -R *", "crontab -r*")]
SETTINGS = json.dumps({"permissions": {"ask": ASK}})
MCP_PANACEA = {"panacea": {"command": "python3", "args": ["-I", str(APPROVE)]}}

# ----------------------------------------------------------------- the browser (Claudezilla)
# Claude can use the owner's own Zen through the Claudezilla extension + its MCP server
# (~/.local/share/claudezilla). Settings > Claude in the island: on/off, and what asks first.
PANACEA_CFG = HOME / ".config/panacea/settings.json"
CLAUDEZILLA = HOME / ".local/share/claudezilla/mcp/server.js"
FX = "mcp__claudezilla__firefox_"
FX_READ = [FX + t for t in (
    "get_content", "get_accessibility_snapshot", "get_page_state", "diff_page_state", "find",
    "get_element", "get_tabs", "screenshot", "get_console", "get_network",
    "diagnose", "wait_for", "scroll", "loop_status", "get_slot_requests", "activate")]
FX_YOURS = [FX + "list_all_tabs", FX + "attach_tab"]   # your own tabs: always a card, whatever the mode (ask beats allow)
FX_ACT = [FX + t for t in (
    "navigate", "create_window", "click", "type", "press_key", "close_tab", "close_window",
    "attach_tab", "detach_tab", "resize_window", "set_viewport", "set_config", "set_private_mode",
    "handle_consent", "start_loop", "stop_loop", "request_tab_space", "grant_tab_space")]
FX_NEVER = [FX + "evaluate"]          # runs JavaScript in your pages: off, like Claudezilla's default
BROWSER_PROMPT = (
    "You can use a web browser through the claudezilla tools (firefox_*): Zen with a separate profile that "
    "exists only for you (claude-zen-sandbox). The owner's own Zen and its tabs are out of your reach by design; "
    "don't try to reach them. This profile is only signed in where the owner logged in to it by hand. "
    "It starts by itself on your first browser call (allow up to a minute). Its window opens where the owner chose "
    "in Settings > Claude (by default its own desktop, workspace 10 / Super+0) so they can watch you work; it never "
    "takes focus. For sites that need a login (WhatsApp Web, etc.) ask them to log in in that window by hand "
    "(e.g. scan the QR code); never ask for passwords. Read pages with "
    "firefox_get_accessibility_snapshot (cheaper than screenshots). Close the tabs you opened when you're done "
    "unless they want them kept. Never buy, send, post, delete or change account settings unless they asked "
    "for exactly that."
)
BROWSER_PROMPT_SPACE = (
    "You can use the owner's own Zen browser through the claudezilla tools (firefox_*), signed in as them. "
    "Every tab you open goes, in the background, into their \"Claude\" Space; you can only act on tabs you opened. "
    "Their other tabs are theirs: only touch one when they explicitly ask, via firefox_list_all_tabs and "
    "firefox_attach_tab (both show them a card), and firefox_detach_tab when done. Never switch their view or Space. "
    "Read pages with firefox_get_accessibility_snapshot (cheaper than screenshots). Leave your tabs open unless they "
    "ask you to close them. Never buy, send, post, delete or change account settings unless they asked for exactly that. "
    "If a tool says the extension isn't connected, ask them to open Zen."
)
BROWSER_BLOCKED = (
    "The browser tools are switched off for this run: the owner's own Zen profile still has the Claudezilla "
    "add-on, and Claude may only use its separate profile. If they ask for the browser, tell them to remove "
    "Claudezilla from their Zen (about:addons > Claudezilla > Remove)."
)
ZEN = HOME / ".config/zen"
ZEN_CLAUDE = ZEN / "claude"


def own_zen_has_claudezilla():
    """True if any of the owner's own Zen profiles (not Claude's) has the add-on installed."""
    for ej in ZEN.glob("*/extensions.json"):
        if ej.parent == ZEN_CLAUDE:
            continue
        try:
            # removed in about:addons = pendingUninstall (and inactive) until Zen restarts: that one is gone
            if any(a.get("id") in ("claudezilla@boot.industries", "claude-zen@aphesist") and not a.get("pendingUninstall")
                   for a in json.loads(ej.read_text()).get("addons", [])):
                return True
        except (OSError, ValueError):
            continue
    return False


def panacea_cfg():
    try:
        return json.loads(PANACEA_CFG.read_text())
    except (OSError, ValueError):
        return {}


def run_config():
    """-> (mcp json, allowed, ask, denied, extra prompt) for this run, from the island's settings."""
    cfg = panacea_cfg()
    servers, allowed, ask, denied, extra = dict(MCP_PANACEA), list(ALLOWED), list(ASK), list(DENIED), ""
    space = cfg.get("claudeBrowserMode", "space") != "profile"   # space: a Space in your own Zen
    if cfg.get("claudeBrowser", True) and CLAUDEZILLA.exists() and not space and own_zen_has_claudezilla():
        extra = BROWSER_BLOCKED          # sandbox broken: no browser at all until it's fixed
    elif cfg.get("claudeBrowser", True) and CLAUDEZILLA.exists():
        # one agent for every message (its tabs stay open and usable between replies);
        # needs claude-zen-sandbox's patched MCP server (CLAUDEZILLA_AGENT_ID / _KEEP_TABS)
        env = {"CLAUDEZILLA_AGENT_ID": "agent_panacea_island", "CLAUDEZILLA_KEEP_TABS": "1",
               "CLAUDEZILLA_AGENT_TIMEOUT_MS": "0"}
        servers["claudezilla"] = {"command": "/usr/bin/node", "args": [str(CLAUDEZILLA), "--tools", "all"], "env": env}
        if space:
            env["CLAUDEZILLA_ZEN_SPACE"] = "1"
        elif cfg.get("claudeBrowserAutostart", True):      # Claude's Zen starts on its first browser call
            env |= {
                "CLAUDEZILLA_AUTOSTART_CMD": json.dumps(["systemctl", "--user", "start", "zen-claude.service"]),
                "CLAUDEZILLA_AUTOSTART_WAIT_MS": "60000"}
        mode = cfg.get("claudeBrowserAsk", "actions")      # actions | all | none
        if mode == "all":
            ask += FX_READ + FX_ACT
        elif mode == "none":
            allowed += FX_READ + FX_ACT
        else:
            allowed += FX_READ
            ask += FX_ACT
        denied += FX_NEVER
        ask += FX_YOURS
        extra = BROWSER_PROMPT_SPACE if space else BROWSER_PROMPT
    return json.dumps({"mcpServers": servers}), allowed, ask, denied, extra

for d in (CONF, STATE.parent, WORKDIR, ATTACH):
    d.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = CONF / "token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    TOKEN_FILE.chmod(0o600)
TOKEN = TOKEN_FILE.read_text().strip()
LOCK = threading.Lock()
CARDS = []   # this run's answered approvals with their outcome (done / failed / denied)
STEPS = []   # this run's timeline (text, tool and card steps, in order)
RUN = {"proc": None, "stopped": False}   # the run in progress, so the chat can stop it
COMMANDS = CACHE / "commands.json"      # Claude Code's slash commands, for the chat's / picker


def refresh_commands():
    """Ask Claude Code (SDK control protocol, no model call) for its slash commands."""
    try:
        p = subprocess.Popen([CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                              "--verbose"], cwd=WORKDIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        timer = threading.Timer(30, p.kill)
        timer.start()
        p.stdin.write(json.dumps({"type": "control_request", "request_id": "cmds",
                                  "request": {"subtype": "initialize"}}) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "control_response":
                cmds = ((ev.get("response") or {}).get("response") or {}).get("commands") or []
                out = [{"name": c.get("name", ""), "description": c.get("description", ""),
                        "argumentHint": c.get("argumentHint", "")} for c in cmds if c.get("name")
                       and not c["name"].startswith("__")]
                tmp = COMMANDS.with_suffix(".tmp")
                tmp.write_text(json.dumps(out, ensure_ascii=False))
                os.replace(tmp, COMMANDS)
                break
        timer.cancel()
        p.kill()
    except Exception:
        pass


def commands_loop():
    while True:
        refresh_commands()
        time.sleep(6 * 3600)


def interrupt():
    """Stop the current run (like Esc in the CLI). The session is kept: the next message resumes it."""
    proc = RUN["proc"]
    if not proc or proc.poll() is not None:
        return False
    RUN["stopped"] = True
    proc.send_signal(signal.SIGINT)
    threading.Timer(4, lambda: proc.poll() is None and proc.kill()).start()
    try:                                   # a card that was waiting goes away with the run
        (CACHE / "approval.json").write_text("{}")
    except OSError:
        pass
    return True


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
        return {"k": "text", "t": block["text"].strip()[:4000]}
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
        }.get(name, lambda: FX_LABELS.get(name.removeprefix(FX), lambda i: "")(inp) or "Using " + name)()
        # "d": what it ran, shown when the line is opened in the chat; "done" once its result is in
        return {"k": "tool", "t": label[:300], "id": block.get("id", ""), "d": detail_of(name, inp), "done": False}
    return None


def detail_of(name, inp):
    """A tool call's input, as you'd want to read it when you open its line in the chat."""
    s = lambda k: str(inp.get(k) or "")
    if name == "Bash":
        d = s("command")
    elif name == "Edit":
        d = s("file_path") + "\n- " + s("old_string")[:300] + "\n+ " + s("new_string")[:300]
    elif name == "Write":
        d = s("file_path") + "\n" + s("content")[:400]
    elif name in ("Read", "NotebookEdit"):
        d = s("file_path")
    elif name == "WebSearch":
        d = s("query")
    elif name == "WebFetch":
        d = s("url") + ("\n" + s("prompt") if inp.get("prompt") else "")
    elif name in ("Grep", "Glob"):
        d = s("pattern") + (" in " + s("path") if inp.get("path") else "")
    else:
        try:
            d = json.dumps(inp, ensure_ascii=False, indent=1)
        except (TypeError, ValueError):
            d = str(inp)
    return d.strip()[:1000]


def result_of(block):
    """A tool result's text, trimmed for the chat."""
    c = block.get("content")
    if isinstance(c, list):
        c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    t = str(c or "").strip()
    return t if len(t) <= 800 else t[:800].rstrip() + "\n…"


FX_LABELS = {   # the browser's steps, in words
    "navigate": lambda i: "Opening " + str(i.get("url", "")) + " in Claude's Zen",
    "create_window": lambda i: "Opening " + str(i.get("url", "")) + " in Claude's Zen",
    "get_accessibility_snapshot": lambda i: "Reading the page",
    "get_content": lambda i: "Reading the page",
    "get_page_state": lambda i: "Looking at the page",
    "find": lambda i: "Looking for " + str(i.get("text") or i.get("query") or "something") + " on the page",
    "screenshot": lambda i: "Taking a screenshot of the page",
    "click": lambda i: "Clicking on the page",
    "type": lambda i: "Typing into the page",
    "press_key": lambda i: "Pressing " + str(i.get("key", "a key")),
    "scroll": lambda i: "Scrolling the page",
    "list_all_tabs": lambda i: "Looking at the open tabs",
    "get_tabs": lambda i: "Looking at its tabs",
    "attach_tab": lambda i: "Taking over a tab",
    "close_tab": lambda i: "Closing a tab",
    "wait_for": lambda i: "Waiting for the page",
    "diagnose": lambda i: "Checking the browser connection",
}


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

    # One continuous session, whatever the chat shows (clearing it only clears the view).
    # A new one only when there is none yet, or it got too big: then it starts with the
    # end of the journal, and the notebook (always sent) carries the rest.
    st = load_state()
    resume = st.get("session_id") if session_ok(st.get("session_id")) else None
    if not resume and not prompt.lstrip().startswith("/"):   # a /command goes as it is
        tail = journal_tail()
        if tail:
            prompt = (f"(A new session. The end of your journal, for context:)\n{tail}\n\n"
                      f"(New message:)\n{prompt}")

    mcp, allowed, ask, denied, extra = run_config()
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
           "--append-system-prompt", SYSTEM + ("\n\n" + extra if extra else "") + "\n\n" + notebook() + "\n\n" + profile(),
           "--mcp-config", mcp, "--strict-mcp-config",
           "--permission-mode", "auto", "--settings", json.dumps({"permissions": {"ask": ask}}),
           "--permission-prompt-tool", "mcp__panacea__approve",
           "--allowedTools", *allowed, "--disallowedTools", *denied]
    if model and model not in ("claude", "default"):
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--", prompt]

    # Stream the run: every thinking block, remark and tool call goes to
    # live.json so the chat can show what Claude is doing while it works.
    live = {"busy": True, "steps": [], "started": time.time(), "at": last.get("at")}
    STEPS[:] = []
    live["steps"] = STEPS
    write_live(live)
    out, tail = None, []
    errf = tempfile.TemporaryFile(mode="w+")   # a file, not a pipe: a full pipe would stall the run
    proc = subprocess.Popen(cmd, cwd=WORKDIR, stdout=subprocess.PIPE, stderr=errf, text=True)
    RUN["proc"], RUN["stopped"] = proc, False
    sid = resume
    killer = threading.Timer(TIMEOUT, proc.kill) if TIMEOUT else None
    if killer:
        killer.start()
    try:
        for line in proc.stdout:
            tail = (tail + [line])[-5:]
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                sid = ev.get("session_id") or sid
            elif ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    st = step_of(block)
                    if st:
                        STEPS.append(st)
                        del STEPS[:-200]         # in place: live["steps"] is STEPS
                        write_live(live)
            elif ev.get("type") == "user":
                # tool results: an approval you answered becomes a record of what happened
                for block in (ev.get("message") or {}).get("content") or []:
                    card = card_of(block) if isinstance(block, dict) else None
                    if not card and isinstance(block, dict) and block.get("type") == "tool_result":
                        # any other tool: its result goes on its line (opened in the chat)
                        tid = block.get("tool_use_id", "")
                        for st in reversed(live["steps"]):
                            if st.get("k") == "tool" and st.get("id") == tid:
                                st.update({"done": True, "out": result_of(block), "err": bool(block.get("is_error"))})
                                write_live(live)
                                break
                    if card:
                        CARDS.append(card)
                        live["cards"] = CARDS[-8:]
                        # the record takes the place of its own step, so the chat reads in
                        # order: Claude's text, what it ran (and how it went), more text...
                        tid = block.get("tool_use_id", "")
                        for i, st in enumerate(live["steps"]):
                            if st.get("k") == "tool" and st.get("id") == tid:
                                live["steps"][i] = {"k": "card", "id": tid, **card}
                                break
                        else:
                            live["steps"].append({"k": "card", "id": tid, **card})
                        write_live(live)
            elif ev.get("type") == "result":
                out = ev
        proc.wait()
    finally:
        if killer:
            killer.cancel()   # live.json is closed by do_POST, together with the reply
        RUN["proc"] = None
    if RUN["stopped"]:
        # stopped from the chat: keep the session so the next message carries on from here
        reply = "Stopped."
        if sid:
            save_state({"session_id": sid, "last_reply": reply})
        return reply
    if out is None:
        if TIMEOUT and proc.returncode in (-9, 137):
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
        if self.path.rstrip("/") == "/v1/interrupt":
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN):
                return self.reply(401, {"error": "bad token"})
            return self.reply(200, {"stopped": interrupt()})
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
        # kept with the reply: the whole timeline as the chat showed it while Claude worked -
        # remarks, the tools it ran (with what they returned) and the actions you approved -
        # so nothing changes when it finishes (the last remark is usually the reply itself,
        # so it's left out)
        timeline = [st for st in STEPS if st.get("k") in ("text", "tool", "card")]
        if msgs and not str(answer).startswith("Claude bridge error"):
            journal_add(text_of(msgs[-1].get("content")), answer,
                        [st.get("t", "") for st in STEPS if st.get("k") == "tool"])
        if timeline and timeline[-1].get("k") == "text" and answer.strip().startswith(timeline[-1]["t"][:200]):
            timeline.pop()
        write_live({"busy": False, "steps": [],
                    "last": {"at": at, "answer": answer, "cards": CARDS[-8:], "timeline": timeline[-200:]}})
        self.reply(200, {"object": "chat.completion",
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": answer}}]})


if __name__ == "__main__":
    threading.Thread(target=profile, daemon=True).start()   # fresh machine profile at startup
    threading.Thread(target=commands_loop, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
