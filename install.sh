#!/bin/bash
# WezTerm の設定（AI エージェントのサイドバー込み）をこの Mac に入れる。
# 使い方: bash install.sh
# 既にあるファイルは *.bak-<日時> として残してから上書きする。
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
STAMP=$(date +%Y%m%d-%H%M%S)

backup() {
  [ -e "$1" ] && cp -p "$1" "$1.bak-$STAMP" && echo "  バックアップ: $1.bak-$STAMP"
  return 0
}

install_file() {
  backup "$2"
  cp "$1" "$2"
  echo "  配置: $2"
}

# 0. 動かす前の確認
[ "$(uname)" = "Darwin" ] || { echo "この設定は macOS 専用です"; exit 1; }
command -v jq >/dev/null || { echo "jq が見つかりません。先に brew install jq を実行してください"; exit 1; }
PYTHON=""
for p in /opt/homebrew/opt/python@3/libexec/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$p" ] && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null && { PYTHON="$p"; break; }
done
[ -z "$PYTHON" ] && { echo "Python 3.9 以上が見つかりません。先に brew install python を実行してください"; exit 1; }
echo "Python: $PYTHON"
# 無くても入れられるが、動かないものは先に知らせる
[ -d /Applications/WezTerm.app ] || command -v wezterm >/dev/null \
  || echo "注意: WezTerm が見つかりません。brew install --cask wezterm@nightly で入れてください"
command -v claude >/dev/null \
  || echo "注意: Claude Code が見つかりません。入れるまでサイドバーの AGENTS と使用量は空のままです"

# 1. WezTerm
echo "1. WezTerm の設定"
mkdir -p ~/.config/wezterm
for f in wezterm.lua keybinds.lua agent_sidebar.lua agent_sidebar.py; do
  install_file "$SRC/wezterm/$f" ~/.config/wezterm/$f
done

# 2. Claude Code の hook と statusLine
echo "2. Claude Code の hook と statusLine"
mkdir -p ~/.claude/hooks
install_file "$SRC/claude/hooks/agent-status.sh" ~/.claude/hooks/agent-status.sh
install_file "$SRC/claude/statusline.py" ~/.claude/statusline.py
chmod +x ~/.claude/hooks/agent-status.sh ~/.claude/statusline.py

# 3. settings.json に hook を足す（既存の hook・設定は残す。同じものは二重に入れない）
echo "3. ~/.claude/settings.json"
SETTINGS=~/.claude/settings.json
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
jq empty "$SETTINGS" 2>/dev/null || { echo "  $SETTINGS の書き方に誤りがあるため中止しました（直してから再実行してください）"; exit 1; }
backup "$SETTINGS"
old_sl=$(jq -r '.statusLine.command // empty' "$SETTINGS")
if [ -n "$old_sl" ] && [[ "$old_sl" != *statusline.py* ]]; then
  echo "  注意: 今までの statusLine（${old_sl}）を置き換えます。元の設定はバックアップに残っています"
fi
tmp=$(mktemp)
jq --slurpfile s "$SRC/claude/settings-snippet.json" --arg py "$PYTHON" '
  ($s[0].hooks) as $new
  | .hooks = (reduce ($new | keys[]) as $ev (.hooks // {};
      .[$ev] = ((.[$ev] // []) | map(select(any(.hooks[]?; .command | test("agent-status.sh")) | not)))
               + $new[$ev]))
  | .statusLine = {type: "command", command: ($py + " ~/.claude/statusline.py")}
' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
echo "  hook と statusLine を追加しました"

# 4. サイドバーの幅（入っていなければ同梱の幅で始める）
mkdir -p ~/.local/state/wezterm-agent-sidebar
[ -f ~/.local/state/wezterm-agent-sidebar/width ] || cp "$SRC/state/width" ~/.local/state/wezterm-agent-sidebar/width

echo "完了。WezTerm を再起動し、Claude Code も開き直してください。"
