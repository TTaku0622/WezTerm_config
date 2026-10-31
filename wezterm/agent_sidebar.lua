-- 左サイドバー（AI エージェントの稼働状況）を付け外しする
-- 描画は agent_sidebar.py、状態は ~/.claude/hooks/agent-status.sh が書き出す
local wezterm = require("wezterm")

local M = {}

-- サイドバーの幅（列数）。agent_sidebar.py がどこかのタブで変えた幅をこのファイルに保存する
local WIDTH_FILE = wezterm.home_dir .. "/.local/state/wezterm-agent-sidebar/width"
local DEFAULT_WIDTH = 26

function M.width()
  local f = io.open(WIDTH_FILE, "r")
  if not f then
    return DEFAULT_WIDTH
  end
  local n = tonumber(f:read("*l"))
  f:close()
  return (n and n >= 10) and n or DEFAULT_WIDTH
end

local SCRIPT = wezterm.config_dir .. "/agent_sidebar.py"
-- Python の場所。Homebrew の更新で python3 の名前が消えることがあるので、候補を順に探す
local PYTHON_CANDIDATES = {
  "/opt/homebrew/opt/python@3/libexec/bin/python3", -- Homebrew の Python 3（更新しても同じパス）
  "/opt/homebrew/bin/python3",
  "/usr/bin/python3", -- macOS 付属（最後の手段）
}
local function find_python()
  for _, path in ipairs(PYTHON_CANDIDATES) do
    local f = io.open(path, "r")
    if f then
      f:close()
      return path
    end
  end
  return "python3"
end
local PYTHON = find_python()

function M.is_sidebar(pane)
  return pane:get_user_vars().agent_sidebar == "1"
end

-- タブ内のサイドバーペインを探す
function M.find(tab)
  for _, p in ipairs(tab:panes()) do
    if M.is_sidebar(p) then
      return p
    end
  end
  return nil
end

-- pane の左にサイドバーを作り、フォーカスを元のペインに戻す
function M.add(pane)
  pane:split({
    direction = "Left",
    size = M.width(),
    args = { PYTHON, SCRIPT },
  })
  pane:activate()
end

-- 現在のタブのサイドバーを出し入れする
function M.toggle(window, pane)
  local tab = window:active_tab()
  local sidebar = M.find(tab)
  if sidebar then
    wezterm.run_child_process({
      wezterm.executable_dir .. "/wezterm", "cli", "kill-pane", "--pane-id", tostring(sidebar:pane_id()),
    })
  else
    -- サイドバー自身にフォーカスがある場合も考え、サイドバー以外のペインを基準にする
    if M.is_sidebar(pane) then
      return
    end
    M.add(pane)
  end
end

-- 作業画面のペインにいるとき、そのペインをタブごとに覚えておく（update-right-status から毎回呼ぶ）
-- Cmd+E で戻る先や、サイドバーで分割キーを押したときの分割先に使う
function M.remember(window, pane)
  if M.is_sidebar(pane) then
    return
  end
  local tab = window:active_tab()
  if not tab then
    return
  end
  local last = wezterm.GLOBAL.agent_sidebar_last_pane or {}
  local key = tostring(tab:tab_id())
  if last[key] ~= pane:pane_id() then
    last[key] = pane:pane_id()
    wezterm.GLOBAL.agent_sidebar_last_pane = last
  end
end

-- 操作の対象にする作業画面のペイン。サイドバーにいるなら、直前にいた作業画面
function M.work_pane(window, pane)
  if not M.is_sidebar(pane) then
    return pane
  end
  local tab = window:active_tab()
  local back = (wezterm.GLOBAL.agent_sidebar_last_pane or {})[tostring(tab:tab_id())]
  local first
  for _, p in ipairs(tab:panes()) do
    if not M.is_sidebar(p) then
      if p:pane_id() == back then
        return p
      end
      first = first or p
    end
  end
  return first
end

-- 分割（LEADER+r / d 用）。サイドバーにいるときは作業画面を分割する
function M.split(direction)
  return function(window, pane)
    local target = M.work_pane(window, pane)
    if not target then
      return
    end
    local cwd = target:get_current_working_dir()
    local new_pane = target:split({
      direction = direction,
      cwd = cwd and cwd.file_path or nil,
    })
    new_pane:activate()
  end
end

-- ペインを閉じる（LEADER+x 用）。サイドバーは閉じない（消すのは LEADER+b）
function M.close(window, pane)
  if M.is_sidebar(pane) then
    return
  end
  window:perform_action(wezterm.action.CloseCurrentPane({ confirm = true }), pane)
end

-- 今のペインだけ大きく表示（LEADER+z 用）。サイドバーにいるときは作業画面を大きくする
function M.zoom(window, pane)
  local target = M.work_pane(window, pane)
  if not target then
    return
  end
  if target:pane_id() ~= pane:pane_id() then
    target:activate()
  end
  window:perform_action(wezterm.action.TogglePaneZoomState, target)
end

-- 作業画面とサイドバーの間でフォーカスを切り替える（Cmd+E 用）
-- 作業画面が分割されていても、サイドバーに入る前にいたペインへ戻る
function M.focus_toggle(window, pane)
  local tab = window:active_tab()
  local last = wezterm.GLOBAL.agent_sidebar_last_pane or {}
  if M.is_sidebar(pane) then
    local back = last[tostring(tab:tab_id())]
    for _, p in ipairs(tab:panes()) do
      if p:pane_id() == back then
        p:activate()
        return
      end
    end
    for _, p in ipairs(tab:panes()) do
      if not M.is_sidebar(p) then
        p:activate()
        return
      end
    end
    return
  end
  last[tostring(tab:tab_id())] = pane:pane_id()
  wezterm.GLOBAL.agent_sidebar_last_pane = last
  local sidebar = M.find(tab)
  if not sidebar then
    -- サイドバーが無いタブでは作ってから移る
    M.add(pane)
    sidebar = M.find(tab)
  end
  if sidebar then
    sidebar:activate()
  end
end

-- 新しいタブを開いてサイドバーを付ける（Cmd+T 用）
function M.spawn_tab(window, pane)
  local cwd = pane:get_current_working_dir()
  local _, new_pane = window:mux_window():spawn_tab({
    cwd = cwd and cwd.file_path or nil,
  })
  M.add(new_pane)
end

return M
