<div align="center">

# panacea-claude-bridge

**Claude in Panacea's island, on your subscription**

![Panacea](https://img.shields.io/badge/Panacea-island_chat-18181b)
![Claude Code](https://img.shields.io/badge/Claude_Code-claude_--p-ffffff)
![No API key](https://img.shields.io/badge/API_key-not_needed-888888)
![License](https://img.shields.io/badge/license-MIT-d71920)

</div>

[Panacea](https://github.com/EnsixD/Panacea)'s island has a chat tab that
talks to any OpenAI-compatible endpoint. This repo puts **Claude Code** behind
that endpoint, so the island chat runs on your Claude Pro/Max subscription
through Claude Code's own login. There's no API key and no per-token billing.

It also reshapes the chat tab into a single Claude tab:

| Before | After |
|---|---|
| Island / Gemini / ChatGPT / DeepSeek tabs (web views) | One tab: **✦ Claude**, model pills **Opus · Sonnet · Haiku**, a new-chat button |
| Ctrl+Enter sends | **Enter** sends, Shift+Enter adds a new line |
| "Add an API address, model and key in the launcher settings" | Nothing to configure |

## How it works

```
island chat ──POST /v1/chat/completions──▶ bridge.py (127.0.0.1:47321)
                                              │  claude -p --output-format json
                                              │         --resume <session>  --model opus|sonnet|haiku
                                              ▼
                                       Claude Code ─▶ your subscription
```

- **Context:** the bridge keeps one Claude Code session per conversation and `--resume`s it, so it never resends the history. The new-chat button, or any history that doesn't match its last reply, starts a fresh session.
- **Images:** attached images are saved to `~/.cache/panacea-claude/attachments/`, and Claude may `Read` that folder only.
- **Sessions:** they show up in Claude Code (and the desktop app) under the project `~/.local/share/panacea-claude`.

### What Claude can do from here

Read-only: `WebSearch`, `WebFetch`, and `Read` restricted to the attachments
folder. It has **no shell and no file edits.** The bridge listens on
`127.0.0.1` only and requires a random bearer token
(`~/.config/panacea-claude/token`, 0600), so a web page can't reach it through
localhost.

## Install

Needs Panacea, and Claude Code logged in with your subscription
(`curl -fsSL https://claude.ai/install.sh | bash`, then `claude` → `/login`).

```sh
git clone https://github.com/aphesist/panacea-claude-bridge && cd panacea-claude-bridge
bash install.sh
```

The installer:
- sets up the bridge as a user service (`panacea-claude.service`);
- writes `aiUrl`, `aiModel` and `aiKey` into Panacea's settings, keeping a backup;
- patches `ChatView.qml`;
- sends one test message.

The patch re-applies itself after Panacea updates (`panacea-chat-patch.path`).
If an update moves its anchors, it changes nothing, and the stock chat keeps
working with the bridge.

Logs: `journalctl --user -u panacea-claude -f`

Undo: `systemctl --user disable --now panacea-claude panacea-chat-patch.path`,
then restore `~/.config/panacea/ChatView.qml.pristine`.

## Credits

[Panacea Shell](https://github.com/EnsixD/Panacea) by EnsixD (MIT); the patch
quotes small parts of its QML in order to find its place. Uses
[Claude Code](https://claude.com/claude-code) as an external program and is not
affiliated with Anthropic.
