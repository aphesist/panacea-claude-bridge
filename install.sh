#!/usr/bin/env bash
# Panacea island chat -> Claude Code, on your Claude subscription. Run as YOUR USER:
#     bash install.sh
# Needs: Panacea, and Claude Code logged in (`claude` once, /login) at ~/.local/bin/claude.
set -euo pipefail
[ "$(id -u)" -ne 0 ] || { echo "run as your user, not root"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
[ -d "$CFG/panacea" ] || { echo "Panacea not found in $CFG/panacea"; exit 1; }
[ -x "$HOME/.local/bin/claude" ] || { echo "Claude Code not found at ~/.local/bin/claude (curl -fsSL https://claude.ai/install.sh | bash)"; exit 1; }

say "Bridge + chat patcher"
install -Dm644 "$HERE/bridge.py" "$HOME/.local/lib/panacea-claude/bridge.py"
install -Dm644 "$HERE/approve-mcp.py" "$HOME/.local/lib/panacea-claude/approve-mcp.py"
install -Dm644 "$HERE/assets/claude-logo.svg" "$CFG/panacea-claude/claude-logo.svg"
install -Dm644 "$HERE/assets/claude-critter.svg" "$CFG/panacea-claude/claude-critter.svg"
install -Dm755 "$HERE/chat-patch.py" "$CFG/hypr/custom/bin/chat-patch.py"
for u in "$HERE"/systemd/*; do install -Dm644 "$u" "$CFG/systemd/user/$(basename "$u")"; done
systemctl --user daemon-reload
systemctl --user enable --now panacea-claude.service panacea-chat-patch.path
systemctl --user restart panacea-claude.service panacea-chat-patch.path

say "Token (created by the bridge on first start, 0600)"
T="$CFG/panacea-claude/token"
for _ in $(seq 1 20); do [ -s "$T" ] && break; sleep 0.25; done
[ -s "$T" ] || { echo "bridge did not start: journalctl --user -u panacea-claude"; exit 1; }

say "Pointing Panacea's chat at the bridge"
S="$CFG/panacea/settings.json"
cp -a "$S" "$S.bak-claude-$(date +%Y%m%d-%H%M%S)"
jq --rawfile k "$T" '.aiUrl="http://127.0.0.1:47321/v1" | .aiModel=(if (.aiModel//"")|test("^(opus|sonnet|haiku)$") then .aiModel else "opus" end) | .aiKey=($k|rtrimstr("\n"))' \
   "$S" > "$S.new" && cat "$S.new" > "$S" && rm "$S.new"

say "Patching the island chat"
python3 -I "$CFG/hypr/custom/bin/chat-patch.py" || echo "  patch skipped (see message above) - the stock chat still works with the bridge"

say "Test"
curl -s -m 90 -H "Authorization: Bearer $(cat "$T")" -H 'Content-Type: application/json' \
  -d '{"model":"haiku","messages":[{"role":"user","content":"Reply with just: ok"}]}' \
  http://127.0.0.1:47321/v1/chat/completions | jq -r '.choices[0].message.content' || true
echo; echo "Done. Open the island's chat tab."
