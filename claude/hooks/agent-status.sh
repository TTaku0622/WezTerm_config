#!/bin/bash
# Claude Code の状態を ~/.claude/agent-status/<session_id>.json に書き出す。
# WezTerm 左サイドバー（~/.config/wezterm/agent_sidebar.py）がこれを読んで表示する。
# 使い方: agent-status.sh <running|done|waiting|pre|end>
#   pre: PreToolUse 用。AskUserQuestion / ExitPlanMode なら waiting、それ以外は running
# 作業を止めないよう、どんな場合も exit 0 で終わる。

mode="$1"
input=$(cat)
dir="$HOME/.claude/agent-status"
mkdir -p "$dir" 2>/dev/null

sid=$(printf '%s' "$input" | /usr/bin/jq -r '.session_id // empty' 2>/dev/null)
[ -z "$sid" ] && exit 0
file="$dir/$sid.json"

if [ "$mode" = "end" ]; then
  rm -f "$file"
  exit 0
fi

state="$mode"
if [ "$mode" = "pre" ]; then
  tool=$(printf '%s' "$input" | /usr/bin/jq -r '.tool_name // empty' 2>/dev/null)
  case "$tool" in
    AskUserQuestion|ExitPlanMode) state="waiting" ;;
    *) state="running" ;;
  esac
fi

# 親プロセスをたどって claude 本体の PID を探す（強制終了の検出用）
pid=""
p=$PPID
for _ in 1 2 3 4 5; do
  [ -z "$p" ] || [ "$p" -le 1 ] 2>/dev/null && break
  comm=$(ps -o comm= -p "$p" 2>/dev/null)
  case "$comm" in
    *claude*) pid="$p"; break ;;
  esac
  p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
done

now=$(date +%s)
# 同じ状態が続いている間は since（その状態になった時刻）を引き継ぐ
since=$now
cwd0=""
if [ -f "$file" ]; then
  prev=$(/usr/bin/jq -r '"\(.state) \(.since)"' "$file" 2>/dev/null)
  [ "${prev%% *}" = "$state" ] && since="${prev##* }"
  # 表示名がぶれないよう、最初に記録したフォルダを使い続ける
  cwd0=$(/usr/bin/jq -r '.cwd // empty' "$file" 2>/dev/null)
fi

tmp="$file.$$"
printf '%s' "$input" | /usr/bin/jq -c \
  --arg state "$state" --arg pane "${WEZTERM_PANE:-}" --arg pid "$pid" \
  --argjson now "$now" --argjson since "$since" --arg cwd0 "$cwd0" \
  '{session_id, cwd: (if $cwd0 != "" then $cwd0 else .cwd end), state: $state, pane: $pane, pid: $pid, since: $since, updated: $now}' \
  > "$tmp" 2>/dev/null && mv "$tmp" "$file"
rm -f "$tmp" 2>/dev/null
exit 0
