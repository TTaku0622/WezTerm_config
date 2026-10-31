#!/bin/bash
# install.sh で入れたものを取り除く。
# 使い方: bash uninstall.sh
# WezTerm の設定ファイルは消さず、install.sh が残したバックアップがあればそれに戻す。
set -euo pipefail

STAMP=$(date +%Y%m%d-%H%M%S)

# 一番新しいバックアップ（*.bak-<日時>）に戻す。無ければ *.removed-<日時> に名前を変えて退ける
restore() {
  local latest
  latest=$(ls -1 "$1".bak-* 2>/dev/null | sort | tail -1 || true)
  if [ -n "$latest" ]; then
    cp -p "$latest" "$1" && echo "  元に戻した: $1（$latest から）"
  elif [ -e "$1" ]; then
    mv "$1" "$1.removed-$STAMP" && echo "  退けた: $1 → $1.removed-$STAMP"
  fi
}

echo "1. WezTerm の設定"
for f in wezterm.lua keybinds.lua agent_sidebar.lua agent_sidebar.py; do
  restore ~/.config/wezterm/$f
done

echo "2. Claude Code の hook と statusLine"
restore ~/.claude/hooks/agent-status.sh
restore ~/.claude/statusline.py

echo "3. ~/.claude/settings.json"
SETTINGS=~/.claude/settings.json
if [ -f "$SETTINGS" ] && command -v jq >/dev/null; then
  cp -p "$SETTINGS" "$SETTINGS.bak-$STAMP"
  tmp=$(mktemp)
  jq '
    .hooks |= ((. // {}) | map_values(map(select(any(.hooks[]?; .command | test("agent-status.sh")) | not)))
               | with_entries(select(.value | length > 0)))
    | if (.statusLine.command // "" | test("statusline.py")) then del(.statusLine) else . end
  ' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  echo "  サイドバー用の hook と statusLine を外しました（他の設定はそのまま）"
fi

echo "完了。WezTerm を再起動してください。"
echo "サイドバーが記録したデータ（~/.claude/agent-status, ~/.claude/agent-usage, ~/.local/state/wezterm-agent-sidebar）は残しています。不要なら手で消してください。"
