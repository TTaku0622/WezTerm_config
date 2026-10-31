#!/usr/bin/env python3
"""Claude Code の statusLine。入力欄の下に1行で使用状況を出す。

例: [Opus 5.5] ctx 18% | $15.37 | 5h 2% ~12:30 | 7d 27% ~10/9 00:00
受け取った値は ~/.claude/agent-usage/latest.json にも書き出し、
WezTerm サイドバー（~/.config/wezterm/agent_sidebar.py）の使用量ゲージに使う。
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

USAGE_DIR = Path.home() / ".claude" / "agent-usage"

RESET = "\033[0m"
DIM = "\033[2m"


def color_for(pct):
    """使用率に応じた色（緑→黄→赤）"""
    if pct is None:
        return DIM
    if pct >= 80:
        return "\033[38;5;196m"
    if pct >= 50:
        return "\033[38;5;220m"
    return "\033[38;5;40m"


def get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def reset_label(ts, with_date):
    """リセット時刻（epoch 秒 or ISO 文字列）を ~12:30 / ~10/9 00:00 の形にする"""
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
    except (ValueError, OSError):
        return ""
    fmt = f"{dt.month}/{dt.day} %H:%M" if with_date else "%H:%M"
    return f" {DIM}~{dt.strftime(fmt)}{RESET}"


def limit(data, key):
    """rate_limits.<key> から (使用率, リセット時刻) を取り出す"""
    rl = get(data, "rate_limits", key) or {}
    pct = rl.get("used_percentage", rl.get("utilization"))
    return (round(pct) if isinstance(pct, (int, float)) else None,
            rl.get("resets_at", rl.get("reset_at")))


def save(data, five, seven):
    try:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        out = {
            "updated": time.time(),
            "model": get(data, "model", "display_name"),
            "five_hour": {"pct": five[0], "resets_at": five[1]},
            "seven_day": {"pct": seven[0], "resets_at": seven[1]},
        }
        tmp = USAGE_DIR / f"latest.json.{os.getpid()}"
        tmp.write_text(json.dumps(out, ensure_ascii=False))
        tmp.replace(USAGE_DIR / "latest.json")
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}

    model = get(data, "model", "display_name") or "?"
    ctx = get(data, "context_window", "used_percentage")
    cost = get(data, "cost", "total_cost_usd")
    five = limit(data, "five_hour")
    seven = limit(data, "seven_day")
    save(data, five, seven)

    parts = [f"[{model}]"]
    if isinstance(ctx, (int, float)):
        parts.append(f"ctx {color_for(ctx)}{round(ctx)}%{RESET}")
    if isinstance(cost, (int, float)):
        parts.append(f"${cost:.2f}")
    if five[0] is not None:
        parts.append(f"5h {color_for(five[0])}{five[0]}%{RESET}{reset_label(five[1], False)}")
    if seven[0] is not None:
        parts.append(f"7d {color_for(seven[0])}{seven[0]}%{RESET}{reset_label(seven[1], True)}")
    print(f" {DIM}|{RESET} ".join(parts))


if __name__ == "__main__":
    main()
