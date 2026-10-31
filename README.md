# Wezterm_config

WezTerm の設定一式です。左端に **Claude Code の稼働状況を表示するサイドバー** が付きます。
macOS 専用です。`bash install.sh` を実行すれば、どの Mac でも同じ環境になります。

```
┌ AGENTS ─────────────┬──────────────────────────────┐
│ ● 1 ログイン画面の修正 │                              │
│   my-app   3m        │   いつものターミナル           │
│ ● 2 README を書く     │                              │
│   docs     12s       │                              │
│ HISTORY             │                              │
│ 📌 API の設計         │                              │
│   過去のセッション…    │                              │
│ 5h ████░░░░ 42%     │                              │
│ 7d ██░░░░░░ 18%     │                              │
└─────────────────────┴──────────────────────────────┘
```

---

## 1. できること
- **AGENTS**: 動いている Claude Code を一覧表示し、状態を色で示します。
  | 色 | 状態 |
  |---|---|
  | 🟡 黄 | 作業中 |
  | 🟢 緑 | 完了・入力待ち |
  | 🔴 赤 | 許可や質問への回答待ち |
- **HISTORY**: 過去の Claude Code セッションの一覧です。クリックすると、新しいタブで続きから再開できます。ピン留めもできます。
- **使用量**: Claude の 5 時間枠・7 日枠の使用率をゲージで表示します。Claude Code の入力欄の下にも、同じ内容が1行で出ます。
- サイドバーの幅はドラッグで変えられます。全タブと次回起動時に引き継がれます。
- 見た目: 半透明＋ぼかしの背景、金色のタブ、タイトルバーなし。フルスクリーンは macOS 標準の方式です。

## 2. 必要なもの
| もの | 入れ方 | 補足 |
|---|---|---|
| macOS | — | Windows・Linux では動きません |
| Homebrew | https://brew.sh の1行コマンド | 下の3つを入れるのに使います |
| WezTerm（**nightly 版**） | `brew install --cask wezterm@nightly` | 通常版でも動きますが、一部の設定（タブの閉じるボタンを隠す）が効かず、警告が出ることがあります |
| Python 3.9 以上 | `brew install python` | サイドバーの描画に使います。追加ライブラリは要りません |
| jq | `brew install jq` | macOS 15 以降は最初から入っています |
| Claude Code | https://claude.com/claude-code | 無くても WezTerm は使えます。サイドバーの AGENTS と使用量が空になるだけです |

入っているかは、次のコマンドで確かめられます。
```
wezterm --version; python3 --version; jq --version; claude --version
```

## 3. 入れ方（おすすめ: スクリプト）
1. このフォルダを好きな場所に置きます（例: デスクトップ）。
2. ターミナルで次を実行します。
   ```
   cd ~/Desktop/Wezterm_config
   bash install.sh
   ```
3. WezTerm を完全に終了（`Cmd+Q`）してから起動し直します。
4. 開いていた Claude Code があれば、終了して開き直します。

install.sh は次のことをします。
- すでに同じ名前のファイルがあれば、`ファイル名.bak-<日時>` として残してから上書きします。
- `~/.claude/settings.json` は丸ごと置き換えません。サイドバー用の hook と statusLine だけを足し、ほかの設定と hook は残します。何度実行しても二重には入りません。
- statusLine をすでに自分で設定している場合は、この設定のもので置き換えます。元の設定はバックアップに残ります。

## 4. 入れ方（手動）
### 4-1. ファイルのコピー
| このフォルダ | コピー先 |
|---|---|
| `wezterm/wezterm.lua` | `~/.config/wezterm/wezterm.lua` |
| `wezterm/keybinds.lua` | `~/.config/wezterm/keybinds.lua` |
| `wezterm/agent_sidebar.lua` | `~/.config/wezterm/agent_sidebar.lua` |
| `wezterm/agent_sidebar.py` | `~/.config/wezterm/agent_sidebar.py` |
| `claude/hooks/agent-status.sh` | `~/.claude/hooks/agent-status.sh` |
| `claude/statusline.py` | `~/.claude/statusline.py` |
| `state/width` | `~/.local/state/wezterm-agent-sidebar/width`（無くても可。その場合は 26 列で始まります） |

```
mkdir -p ~/.config/wezterm ~/.claude/hooks ~/.local/state/wezterm-agent-sidebar
cp wezterm/* ~/.config/wezterm/
cp claude/hooks/agent-status.sh ~/.claude/hooks/
cp claude/statusline.py ~/.claude/
cp state/width ~/.local/state/wezterm-agent-sidebar/
chmod +x ~/.claude/hooks/agent-status.sh
```
`~/.config` などは隠しフォルダです。Finder では `Cmd+Shift+.` を押すと見えます。

### 4-2. settings.json の編集
`claude/settings-snippet.json` の中身を `~/.claude/settings.json` に書き足します。
| 今の settings.json | やること |
|---|---|
| 無い | `settings-snippet.json` を `~/.claude/settings.json` としてコピーする |
| あるが `"hooks"` が無い | snippet の `"hooks"` と `"statusLine"` を、一番外側の `{ }` の中に足す |
| `"hooks"` もある | イベント名（`PreToolUse`、`Stop` など）ごとに、snippet の `{ "matcher": …, "hooks": […] }` を既存の `[ ]` の中に足す。今ある hook は消さない |

- `statusLine` に書いてある Python のパスは、自分の Mac のものに直します。`which python3` で調べられます。
- 書き終えたら `jq . ~/.claude/settings.json > /dev/null && echo OK` を実行し、`OK` と出るか確かめます。カンマが1つ抜けるだけで、設定全体が読まれなくなります。

## 5. 使い方
### 5-1. キー操作
`LEADER` は **`Ctrl+q`** です。`Ctrl+q` を押して離してから、2 秒以内に次のキーを押します。
| キー | 動作 |
|---|---|
| `Cmd+T` | 新しいタブ（サイドバー付き） |
| `Cmd+W` | タブを閉じる |
| `Cmd+1`〜`9` / `Ctrl+Tab` | タブの切り替え |
| `Cmd+E` | 入力先を、作業画面とサイドバーの間で切り替える |
| `LEADER` → `b` | サイドバーを出す／消す |
| `LEADER` → `r` / `d` | 右／下に分割（サイドバーにいるときは、作業画面のほうを分割する） |
| `LEADER` → `x` | ペインを閉じる（サイドバーは閉じない） |
| `LEADER` → `z` | 今のペインだけを大きく表示する／元に戻す |
| `LEADER` → `h` `j` `k` `l` | ペインの移動 |
| `LEADER` → `s` → `h` `j` `k` `l` | ペインのサイズ調整（`Enter` で終わる） |
| `LEADER` → `[` | コピーモード（vim 風に移動、`v` で選択、`y` でコピー） |
| `LEADER` → `{` / `}` | タブを左右に並べ替える |
| `LEADER` → `w` | ワークスペースの切り替え |
| `Ctrl+Cmd+F` / `Alt+Enter` | フルスクリーン |
| `Cmd+P` | コマンドパレット |
| `Ctrl+Shift+R` | 設定の再読み込み |
| `Ctrl` + `+` / `-` / `0` | 文字の拡大／縮小／リセット |

**日本語入力のままだと、LEADER のあとのキーが効きません。** 英数モードにしてから押してください。

### 5-2. サイドバーの操作
マウスでも、`Cmd+E` で入力先をサイドバーに移してキーボードでも操作できます。
| 操作 | 動作 |
|---|---|
| AGENTS の行をクリック / `1`〜`9` | そのエージェントのタブへ移動 |
| `j` `k` / `↑` `↓` / ホイール | HISTORY の選択を動かす |
| `Enter` / HISTORY の行をクリック | そのセッションを新しいタブで再開（`claude --resume`） |
| 右クリック / `p` | HISTORY のピン留め／解除（ピン留めしたものは上に並ぶ） |
| 境界線をドラッグ | 幅を変える（全タブに反映） |

普通のクリックでリンクを開く動作は、作業画面ではそのまま使えます。

## 6. 好みに合わせて変える
| 変えたいもの | ファイル | 場所 |
|---|---|---|
| 文字の大きさ | `wezterm.lua` | `config.font_size` |
| 背景の透け具合・ぼかし | `wezterm.lua` | `window_background_opacity` / `macos_window_background_blur` |
| タブの色 | `wezterm.lua` | `format-tab-title` の中の `#ae8b2d`（選択中）・`#5c6d74` |
| タブが1つでもタブバーを出す | `wezterm.lua` | `hide_tab_bar_if_only_one_tab = false` |
| LEADER キー | `wezterm.lua` | `config.leader` |
| キーの割り当て | `keybinds.lua` | `keys` |
| HISTORY の件数 | `agent_sidebar.py` | `HISTORY_MAX` |
| 情報を読み直す間隔 | `agent_sidebar.py` | `REFRESH`（秒） |

設定ファイルは保存すると自動で読み直されます。サイドバー（`agent_sidebar.py`）を変えたときは、`LEADER` → `b` を2回押して作り直してください。

## 7. うまく動かないとき
| 症状 | 原因と対処 |
|---|---|
| サイドバーに `Unable to spawn` などのエラーが出る | Python が見つかっていません。`ls /opt/homebrew/opt/python@3/libexec/bin/python3` で確かめ、無ければ `brew install python`。そのあと `LEADER` → `b` を2回 |
| AGENTS に何も出ない | Claude Code を開き直してください（hook は開いた後から効きます）。`~/.claude/settings.json` に `agent-status.sh` が入っているかも確かめます |
| 使用量のゲージが出ない | Claude Code で一度何か送ると出ます。`statusLine` の Python のパスも確かめます |
| 色がずっと黄色のまま | Claude Code を強制終了した可能性があります。数秒で一覧から自動的に消えます |
| `Ctrl+q` → `r` などが効かない | 日本語入力を英数にします。2つのキーは同時に押さず、順番に押します |
| 起動時に設定の警告が出る | WezTerm が通常版の可能性があります。nightly 版を入れてください |

## 8. 元に戻す
```
bash uninstall.sh
```
- WezTerm の設定は、install.sh が残したバックアップがあればそれに戻します。無ければ `*.removed-<日時>` という名前に変えて退けます。
- `settings.json` からは、サイドバー用の hook と statusLine だけを外します。
- install.sh の前に自分で statusLine を設定していた場合は、`settings.json.bak-<日時>` を見て書き戻してください。

## 9. フォルダの中身
```
Wezterm_config/
├── README.md               このファイル
├── install.sh              入れるスクリプト
├── uninstall.sh            元に戻すスクリプト
├── wezterm/
│   ├── wezterm.lua         本体の設定（見た目・タブ・起動時にサイドバーを付ける）
│   ├── keybinds.lua        キーの割り当て
│   ├── agent_sidebar.lua   サイドバーの付け外し・分割・入力先の切り替え
│   └── agent_sidebar.py    サイドバーの描画（AGENTS / HISTORY / 使用量）
├── claude/
│   ├── hooks/agent-status.sh   Claude Code の状態を ~/.claude/agent-status/ に書き出す
│   ├── statusline.py           使用量の表示（~/.claude/agent-usage/ にも保存する）
│   └── settings-snippet.json   settings.json に足す hook と statusLine
└── state/width             サイドバーの最初の幅（36 列）
```

### 仕組み
```
Claude Code ──hook──▶ ~/.claude/agent-status/*.json ─┐
            ──statusLine──▶ ~/.claude/agent-usage/ ──┼─▶ agent_sidebar.py（1 秒ごとに読んで描画）
過去の会話 ~/.claude/projects/*.jsonl ───────────────┘
```
サイドバーは、各タブの左端に置いた細いペインです。WezTerm には縦のタブバーが無いため、この方式にしています。

### 含まれていないもの
- 過去の会話（HISTORY の中身）とピン留め。新しい Mac では空から始まります。
- 個人のパスワードや API キー。
