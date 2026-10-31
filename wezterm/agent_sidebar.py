#!/usr/bin/env python3
"""WezTerm 左サイドバー: Claude Code の稼働状況・履歴・使用量を表示する。

- AGENTS: 稼働中のセッション。状態は hooks（~/.claude/hooks/agent-status.sh）が
  ~/.claude/agent-status/<session_id>.json に書き出したものを読む。
    🟡 running: 作業中 / 🟢 done: 完了・待機 / 🔴 waiting: 許可・入力待ち
  数字キー 1〜9 またはクリックで、そのペインへ移動する。
- HISTORY: 過去のセッション（~/.claude/projects/*/*.jsonl）。新しい順。
  j/k（↑↓）で選んで Enter、またはクリックで、新しいタブで claude --resume する。
  p キーか右クリックでピン留め（先頭に固定）を切り替える。
- USAGE: 5時間・7日間の使用率。statusLine（~/.claude/statusline.py）が
  ~/.claude/agent-usage/latest.json に書き出したものを読む。
"""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
import unicodedata
from datetime import datetime
from pathlib import Path

STATUS_DIR = Path.home() / ".claude" / "agent-status"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
USAGE_FILE = Path.home() / ".claude" / "agent-usage" / "latest.json"
# wezterm コマンドの場所。PATH に無くても（dmg から入れた場合など）WezTerm 本体の隣から探す
WEZTERM = (shutil.which("wezterm")
           or str(Path(os.environ.get("WEZTERM_EXECUTABLE_DIR", "/Applications/WezTerm.app/Contents/MacOS")) / "wezterm"))
PYTHON = sys.executable  # 自分を起動した Python（新しいタブのサイドバーも同じものを使う）
MY_PANE = os.environ.get("WEZTERM_PANE", "")
# サイドバーの幅（列数）。どこかのタブで幅を変えるとここに保存され、全タブ・次回起動時に使われる
WIDTH_FILE = Path.home() / ".local" / "state" / "wezterm-agent-sidebar" / "width"
DEFAULT_WIDTH = 26  # agent_sidebar.lua の DEFAULT_WIDTH と合わせる
# ピン留めしたセッションID（ピンした順）。全タブのサイドバーで共有する
PINS_FILE = WIDTH_FILE.with_name("pins.json")
HISTORY_MAX = 40
KEY_RE = re.compile(r"\033\[[A-D]|.", re.S)
MOUSE_RE = re.compile(r"\033\[<(\d+);\d+;(\d+)([Mm])")

# 状態ごとの丸の色（ANSI 256色）と表示名
STATES = {
    "running": (220, "作業中"),
    "waiting": (196, "待ち"),
    "done": (40, "完了"),
}

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
REVERSE = "\033[7m"
HOVER_BG = "\033[48;5;238m"
FOCUS_BG = "\033[48;2;174;139;45m\033[38;5;231m"  # タブの金色（#ae8b2d）に白文字
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
HOVER_TIMEOUT = 2.5  # マウスが止まってからグレーを消すまでの秒数
REFRESH = 1.0  # 状態ファイル・履歴を読み直す間隔（秒）


def fg(n):
    return f"\033[38;5;{n}m"


def width(s):
    """全角を2として表示幅を数える"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def truncate(s, w):
    if width(s) <= w:
        return s
    out = ""
    for c in s:
        if width(out + c) > w - 1:
            break
        out += c
    return out + "…"


def pad_to(s, w):
    return s + " " * max(0, w - width(s))


def elapsed(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h"
    return f"{sec // 86400}d"


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def list_panes():
    try:
        out = subprocess.run(
            [WEZTERM, "cli", "list", "--format", "json"],
            capture_output=True, text=True, timeout=3,
        ).stdout
        return json.loads(out)
    except Exception:
        return None


# ---------------------------------------------------------------- AGENTS

def load_agents(panes):
    """状態ファイルを読み、タブの並び順に並べて返す。死んだセッションのファイルは消す。"""
    pane_map = {str(p["pane_id"]): p for p in panes} if panes is not None else None
    order = {str(p["pane_id"]): i for i, p in enumerate(panes or [])}
    agents = []
    for f in STATUS_DIR.glob("*.json"):
        try:
            a = json.loads(f.read_text())
        except Exception:
            continue
        pane = a.get("pane", "")
        dead = (a.get("pid") and not pid_alive(a["pid"])) or (
            pane_map is not None and pane and pane not in pane_map
        )
        if dead:
            f.unlink(missing_ok=True)
            continue
        if not pane:
            continue  # WezTerm 以外（VS Code など）で動いているものは出さない
        a["_pane"] = pane_map.get(pane) if pane_map else None
        agents.append(a)
    agents.sort(key=lambda a: order.get(a.get("pane", ""), 1e9))
    return agents


# ---------------------------------------------------------------- HISTORY

_history_cache = {}  # path -> (mtime, info)


def read_session(path):
    """jsonl からタイトル・cwd を取り出す。大きいので行ごとに必要な行だけ見る。"""
    title = custom = prompt = cwd = None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if cwd is None and '"cwd":"' in line:
                    try:
                        cwd = json.loads(line).get("cwd")
                    except ValueError:
                        pass
                if '"type":"ai-title"' in line or '"type":"custom-title"' in line \
                        or '"type":"last-prompt"' in line:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    title = d.get("aiTitle") or title
                    custom = d.get("customTitle") or custom
                    prompt = d.get("lastPrompt") or prompt
    except OSError:
        return None
    name = custom or title or (prompt or "").replace("\n", " ").strip()
    if not name or not cwd:
        return None  # 中身の無いセッションは出さない
    return {"session_id": path.stem, "title": name, "cwd": cwd}


def read_pins():
    try:
        pins = json.loads(PINS_FILE.read_text())
        return [x for x in pins if isinstance(x, str)]
    except (OSError, ValueError):
        return []


def toggle_pin(session_id):
    pins = read_pins()
    if session_id in pins:
        pins.remove(session_id)
    else:
        pins.append(session_id)
    try:
        PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PINS_FILE.with_name(f"pins.json.{os.getpid()}")
        tmp.write_text(json.dumps(pins))
        tmp.replace(PINS_FILE)
    except OSError:
        pass


def load_history(exclude_ids):
    """過去のセッションを返す。ピン留めしたものは件数制限なしで先頭（ピンした順）、残りは新しい順"""
    pins = read_pins()
    files = []
    for p in PROJECTS_DIR.glob("*/*.jsonl"):
        if p.stem in exclude_ids:
            continue
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            pass
    files.sort(reverse=True)
    pinned, out = {}, []
    for mtime, p in files:
        is_pinned = p.stem in pins
        if not is_pinned and len(out) >= HISTORY_MAX:
            continue
        cached = _history_cache.get(p)
        if not cached or cached[0] != mtime:
            cached = (mtime, read_session(p))
            _history_cache[p] = cached
        if not cached[1]:
            continue
        item = {**cached[1], "mtime": mtime, "pinned": is_pinned}
        if is_pinned:
            pinned[p.stem] = item
        else:
            out.append(item)
    return [pinned[x] for x in pins if x in pinned] + out


def resume(session, panes):
    """新しいタブ（サイドバー付き）で claude --resume する"""
    me = next((p for p in panes or [] if str(p["pane_id"]) == MY_PANE), None)
    cmd = [WEZTERM, "cli", "spawn", "--cwd", session["cwd"]]
    if me:
        cmd += ["--window-id", str(me["window_id"])]
    try:
        new_pane = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        if not new_pane:
            return
        subprocess.run([WEZTERM, "cli", "split-pane", "--pane-id", new_pane, "--left",
                        "--cells", str(read_width()), "--", PYTHON, os.path.abspath(__file__)],
                       capture_output=True, timeout=5)
        subprocess.run([WEZTERM, "cli", "send-text", "--pane-id", new_pane, "--no-paste",
                        f"claude --resume {session['session_id']}\r"],
                       capture_output=True, timeout=5)
        jump(new_pane, panes)
    except Exception:
        pass


# ---------------------------------------------------------------- 幅

def read_width():
    try:
        return max(10, int(WIDTH_FILE.read_text().strip()))
    except (OSError, ValueError):
        return DEFAULT_WIDTH


def save_width(cols):
    try:
        WIDTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = WIDTH_FILE.with_name(f"width.{os.getpid()}")
        tmp.write_text(str(cols))
        tmp.replace(WIDTH_FILE)
    except OSError:
        pass


def tab_pane_count(panes):
    me = next((p for p in panes or [] if str(p["pane_id"]) == MY_PANE), None)
    if not me:
        return None
    return sum(1 for p in panes if p["tab_id"] == me["tab_id"])


def sync_width(prev_size, size, count, prev_count, adjusted):
    """幅を手で変えたら保存し、保存された幅と違えば自分の幅を合わせる。
    自分で幅を合わせたら True を返す（その直後の幅の変化は保存しないため）"""
    # 横幅だけ変わった＝境目をドラッグした等。縦も変わったならウィンドウ全体の変化なので保存しない。
    # 同じタブのペインが増減したとき（分割・閉じる）も、自分の意思で変えた幅ではないので保存しない
    if (prev_size and size.columns != prev_size.columns and size.lines == prev_size.lines
            and count is not None and count == prev_count and not adjusted):
        save_width(size.columns)
        return False
    target = read_width()
    if size.columns != target:
        direction = "Right" if target > size.columns else "Left"
        subprocess.run([WEZTERM, "cli", "adjust-pane-size", "--pane-id", MY_PANE,
                        "--amount", str(abs(target - size.columns)), direction],
                       capture_output=True, timeout=3)
        return True
    return False


# ---------------------------------------------------------------- USAGE

def gauge(pct, w):
    filled = round(w * min(max(pct, 0), 100) / 100)
    color = 196 if pct >= 80 else 220 if pct >= 50 else 40
    return f"{fg(color)}{'▰' * filled}{DIM}{'▱' * (w - filled)}{RESET}"


def usage_lines(w):
    try:
        u = json.loads(USAGE_FILE.read_text())
    except Exception:
        return [f"{DIM} 使用量: claude 起動後に表示{RESET}"]
    now = time.time()
    out = []
    for key, label, with_date in (("five_hour", "5h", False), ("seven_day", "7d", True)):
        d = u.get(key) or {}
        pct, reset = d.get("pct"), d.get("resets_at")
        if pct is None:
            continue
        if isinstance(reset, (int, float)) and reset < now:
            pct, when = 0, "リセット済"  # 記録後に期間が切り替わった
        elif isinstance(reset, (int, float)):
            dt = datetime.fromtimestamp(reset)
            when = dt.strftime(f"{dt.month}/{dt.day} %H:%M" if with_date else "%H:%M")
        else:
            when = ""
        pct_s = f"{pct:>3}%"
        bar_w = max(4, w - 2 - len(label) - 1 - len(pct_s) - 1)
        out.append(f" {label} {gauge(pct, bar_w)} {pct_s}")
        if when:
            out.append(f"    {DIM}~{when}{RESET}")
    return out


# ---------------------------------------------------------------- 描画

def render(agents, history, panes, cols, rows, cursor, hover_row=None, focused=False):
    """画面を描き、クリック用の {行番号: ("pane", id) | ("history", index)} を返す"""
    me = next((p for p in panes or [] if str(p["pane_id"]) == MY_PANE), None)
    my_tab = me["tab_id"] if me else None
    now = time.time()
    w = max(cols - 1, 10)
    rule = f"{DIM} {'─' * (w - 1)}{RESET}"
    lines, actions = [], {}

    def add(line, action=None):
        lines.append(line)
        if action:
            actions[len(lines)] = action

    # AGENTS
    if focused:
        # フォーカス中（キー入力がサイドバーに届く状態）は見出しを金色の帯にする
        add(f"{FOCUS_BG}{BOLD}{pad_to(' AGENTS  ⌘E で戻る', w + 1)}{RESET}")
    else:
        add(f" {BOLD}AGENTS{RESET}")
    add(rule)
    if not agents:
        add(f"{DIM} 稼働中なし{RESET}")
    for i, a in enumerate(agents):
        color, label = STATES.get(a.get("state"), (244, "?"))
        name = Path(a.get("cwd") or "?").name or "/"
        p = a.get("_pane") or {}
        here = my_tab is not None and p.get("tab_id") == my_tab
        num = str(i + 1) if i < 9 else " "
        style = BOLD if here else ""
        act = ("pane", a.get("pane"))
        # 1行目: Claude がペインに付けるタイトル（作業内容の要約）
        title = (p.get("title") or "").strip()
        if len(title) > 2 and title[1] == " " and not title[0].isalnum():
            title = title[2:]  # 先頭のスピナー記号（✳ ◑ など）を除く
        title = truncate(title or label, w - 5)
        add(f" {fg(color)}●{RESET} {DIM}{num}{RESET} {style}{title}{RESET}", act)
        # 2行目: 場所（起動したフォルダ）と経過時間
        t = elapsed(now - a.get("since", now))
        add(f"{DIM}{pad_to('    ' + truncate(name, w - 5 - len(t)), w - len(t))}{t}{RESET}", act)

    # USAGE は画面の一番下に固定する
    footer = [rule, f" {BOLD}USAGE{RESET}"] + usage_lines(w)

    # HISTORY は残りの高さに収まるぶんだけ、カーソル位置が見えるようにずらして出す
    add("")
    hint = "j/k Enter  p:ピン" if w >= 28 else "p:ピン"
    add(f" {BOLD}HISTORY{RESET} {DIM}{hint}{RESET}")
    add(rule)
    room = max(0, rows - len(lines) - len(footer) - 1)
    per = 2
    # ピン留めと通常の間に区切り線を1行入れるぶんを差し引く
    if any(h.get("pinned") for h in history) and not all(h.get("pinned") for h in history):
        room -= 1
    visible = max(0, room // per)
    start = 0
    if visible and cursor >= visible:
        start = cursor - visible + 1
    for i in range(start, min(len(history), start + visible)):
        h = history[i]
        sel = i == cursor
        if i > start and history[i - 1].get("pinned") and not h.get("pinned"):
            add(f"{DIM} {'┄' * (w - 1)}{RESET}")
        # 1行目: タイトル / 2行目: 場所（起動したフォルダ）と経過時間
        t = elapsed(now - h["mtime"])
        if h.get("pinned"):
            head = pad_to(f" 📌{truncate(h['title'], w - 3)}", w)
        else:
            head = pad_to(f" ○ {truncate(h['title'], w - 3)}", w)
        name = truncate(Path(h["cwd"]).name or "/", w - 5 - len(t))
        sub = pad_to(f"    {name}", w - len(t)) + t
        if sel:
            add(f"{REVERSE}{head}{RESET}", ("history", i))
            add(f"{REVERSE}{sub}{RESET}", ("history", i))
        else:
            add(head, ("history", i))
            add(f"{DIM}{sub}{RESET}", ("history", i))

    # マウスが乗っている項目（2行ぶん）の背景をグレーにする。j/k で選択中の履歴は反転表示のまま
    hovered = actions.get(hover_row) if hover_row else None
    if hovered and hovered != ("history", cursor):
        for row, act in actions.items():
            if act == hovered:
                line = lines[row - 1]
                bg = HOVER_BG
                lines[row - 1] = (bg + line.replace(RESET, RESET + bg)
                                  + " " * max(0, w + 1 - width(ANSI_RE.sub("", line))) + RESET)

    gap = max(0, rows - len(lines) - len(footer))
    screen = (lines + [""] * gap + footer)[:rows]
    # 画面全体を消さずに上書きする（マウスの動きで頻繁に描き直してもちらつかないように）
    sys.stdout.write("\033[H" + "\033[K\r\n".join(screen) + "\033[K\033[J")
    sys.stdout.flush()
    return actions


def jump(pane_id, panes=None):
    """pane_id へ移動する。移動元のタブはサイドバーではなく作業ペインにフォーカスを戻しておく
    （タブ名が agents にならず、次にそのタブへ来たときすぐ入力できるように）"""
    if not pane_id:
        return
    me = next((p for p in panes or [] if str(p["pane_id"]) == MY_PANE), None)
    if me:
        work = next((p for p in panes if p["tab_id"] == me["tab_id"]
                     and str(p["pane_id"]) != MY_PANE), None)
        if work and str(work["pane_id"]) != str(pane_id):
            subprocess.run([WEZTERM, "cli", "activate-pane", "--pane-id", str(work["pane_id"])],
                           capture_output=True, timeout=3)
    subprocess.run([WEZTERM, "cli", "activate-pane", "--pane-id", str(pane_id)],
                   capture_output=True, timeout=3)


def only_me_left(panes):
    """作業ペインが閉じられてサイドバーだけ残ったら終了する"""
    me = next((p for p in panes if str(p["pane_id"]) == MY_PANE), None)
    if not me:
        return False
    return sum(1 for p in panes if p["tab_id"] == me["tab_id"]) == 1


def main():
    # WezTerm 側でサイドバーペインを識別するための user var（agent_sidebar=1）
    sys.stdout.write("\033]1337;SetUserVar=agent_sidebar=MQ==\007")
    sys.stdout.write("\033]2;agents\007")      # ペインのタイトル
    sys.stdout.write("\033[?25l")              # カーソル非表示
    # マウスのクリック・移動を受け取る（1003: ボタンを押していない移動も、1006: SGR形式）
    sys.stdout.write("\033[?1000h\033[?1003h\033[?1006h\033[?1004h")
    sys.stdout.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    agents, history, panes = [], [], None
    cursor = 0
    selected_id = None  # 履歴が並び変わってもカーソルを同じセッションに保つ
    pressed_row = None  # マウスボタンを押した行（離したときに実行する）
    hover_row, hover_at = None, 0.0  # マウスが乗っている行と、最後に動いた時刻
    last_refresh = 0.0
    focused = False  # キー入力がサイドバーに届く状態か
    prev_size = None  # 前回の自分の大きさ（幅を手で変えたかの判定用）
    prev_count = None  # 前回の同じタブのペイン数
    adjusted = False  # 前回、自分で幅を合わせたか
    try:
        while True:
            now = time.time()
            if now - last_refresh >= REFRESH:
                last_refresh = now
                panes = list_panes()
                if panes is not None and only_me_left(panes):
                    break
                agents = load_agents(panes)
                running_ids = {a.get("session_id") for a in agents}
                history = load_history(running_ids)
                size = shutil.get_terminal_size()
                count = tab_pane_count(panes)
                adjusted = sync_width(prev_size, size, count, prev_count, adjusted)
                prev_size, prev_count = size, count
            ids = [h["session_id"] for h in history]
            if selected_id in ids:
                cursor = ids.index(selected_id)
            cursor = min(cursor, max(0, len(history) - 1))
            if hover_row and now - hover_at > HOVER_TIMEOUT:
                hover_row = None
            size = shutil.get_terminal_size()
            actions = render(agents, history, panes, size.columns, size.lines, cursor, hover_row, focused)

            wait = REFRESH - (time.time() - last_refresh)
            if hover_row:
                wait = min(wait, HOVER_TIMEOUT - (time.time() - hover_at))
            r, _, _ = select.select([fd], [], [], max(0.05, wait))
            if not r:
                continue
            data = os.read(fd, 1024).decode(errors="ignore")
            action = None
            # フォーカスの出入り（ESC [ I / ESC [ O）
            if "\033[I" in data or "\033[O" in data:
                focused = data.rfind("\033[I") > data.rfind("\033[O")
                data = data.replace("\033[I", "").replace("\033[O", "")
            if not data:
                continue
            if data.startswith("\033[<"):
                # クリック: ESC [ < btn ; x ; y M（押す）/ m（離す）。1回の読み込みに複数来ることがある
                # 押した瞬間に切り替えると、離した操作が切替先のペインに届いて
                # リンクが開いてしまうため、同じ行で離したときに実行する
                for btn, y, kind in MOUSE_RE.findall(data):
                    y = int(y)
                    if btn == "0" and kind == "M":
                        pressed_row = y
                    elif btn == "0" and kind == "m":
                        if pressed_row == y:
                            action = actions.get(y)
                        pressed_row = None
                    elif btn == "2" and kind == "M":
                        # 右クリックでピン留めの切り替え
                        act = actions.get(y)
                        if act and act[0] == "history":
                            toggle_pin(history[act[1]]["session_id"])
                            last_refresh = 0.0
                    elif btn == "35":
                        # ボタンを押していない移動
                        hover_row, hover_at = y, time.time()
                    elif kind == "M" and btn in ("64", "65") and history:
                        # ホイールで履歴のカーソルを動かす
                        cursor = max(0, min(len(history) - 1, cursor + (1 if btn == "65" else -1)))
            else:
                # キー入力。まとめて届くことがあるので1つずつ処理する（矢印キーは3文字で1つ）
                for key in KEY_RE.findall(data):
                    if key in ("j", "\033[B") and history:
                        cursor = min(len(history) - 1, cursor + 1)
                    elif key in ("k", "\033[A") and history:
                        cursor = max(0, cursor - 1)
                    elif key == "p" and history:
                        toggle_pin(history[cursor]["session_id"])
                        last_refresh = 0.0  # すぐ並べ直す
                    elif key in ("\r", "\n") and history:
                        action = ("history", cursor)
                    elif key.isdigit() and key != "0":
                        i = int(key) - 1
                        if i < len(agents):
                            action = ("pane", agents[i].get("pane"))
                    if history:
                        selected_id = history[cursor]["session_id"]

            if history:
                selected_id = history[cursor]["session_id"]
            if action and action[0] == "pane":
                jump(action[1], panes)
            elif action and action[0] == "history":
                cursor = action[1]
                selected_id = history[cursor]["session_id"]
                resume(history[cursor], panes)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\033[?1000l\033[?1003l\033[?1006l\033[?1004l\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
