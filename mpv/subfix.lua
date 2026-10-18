-- subfix: when an MKV opens, run fixep.py in the background (playback isn't held up), then load and select the
-- fixed English subs. fixep.py also embeds the fixed track in the file, so later plays skip all of this.
-- Install (macOS/Linux): ln -s /path/to/subfix/mpv/subfix.lua ~/.config/mpv/scripts/
-- If the script is copied rather than symlinked (e.g. Windows), set the repo path in
-- script-opts/subfix.conf:  fixep=C:\path\to\subfix\fixep.py   (optional: python=py)
local utils = require 'mp.utils'
local options = require 'mp.options'
local windows = package.config:sub(1, 1) == '\\'
local opts = {fixep = '', python = windows and 'python' or 'python3'}
options.read_options(opts, 'subfix')

local function fixep_path()
    if opts.fixep ~= '' then return opts.fixep end
    -- follow the symlink in mpv's scripts dir back to the repo: <repo>/mpv/subfix.lua -> <repo>/fixep.py
    local me = debug.getinfo(1, 'S').source:gsub('^@', '')
    local r = mp.command_native({name = 'subprocess', capture_stdout = true, playback_only = false,
        args = {opts.python, '-c', 'import os,sys;print(os.path.realpath(sys.argv[1]))', me}})
    local real = r.status == 0 and r.stdout:gsub('%s+$', '') or me
    local repo = utils.split_path(utils.split_path(real):gsub('[/\\]$', ''))
    return utils.join_path(repo, 'fixep.py')
end

local function environment()
    -- mpv started from the macOS Finder doesn't see Homebrew. Returns nil (inherit) when PATH already has
    -- everything, as on a normal Linux desktop: the subprocess env field needs mpv 0.36+
    if windows then return nil end
    local path = os.getenv('PATH') or ''
    local extra = {}
    for _, d in ipairs({'/opt/homebrew/bin', '/usr/local/bin'}) do
        if utils.file_info(d) and not (':' .. path .. ':'):find(':' .. d .. ':', 1, true) then extra[#extra + 1] = d end
    end
    if #extra == 0 then return nil end
    local env = {}
    for _, kv in ipairs(utils.get_env_list()) do
        env[#env + 1] = kv:match('^PATH=') and ('PATH=' .. table.concat(extra, ':') .. ':' .. kv:sub(6)) or kv
    end
    return env
end

local FIXEP = fixep_path()

mp.register_event('file-loaded', function()
    local opened = mp.get_property('path')
    if not opened or opened:match('^%a%a+://') or not opened:lower():match('%.mkv$') then return end
    for _, t in ipairs(mp.get_property_native('track-list', {})) do
        if t.type == 'sub' and t.title and t.title:match('%(signs fixed%)$') then return end  -- already fixed
    end
    local absolute = opened:match('^/') or opened:match('^%a:[/\\]') or opened:match('^\\\\')
    local abs = absolute and opened or utils.join_path(mp.get_property('working-directory'), opened)
    mp.msg.info('fixing subs in the background (' .. FIXEP .. ')')
    mp.command_native_async({
        name = 'subprocess', playback_only = false, capture_stdout = true, capture_stderr = true,
        env = environment(), args = {opts.python, '-I', FIXEP, abs},
    }, function(ok, res)
        if not ok or res.status ~= 0 then
            mp.msg.warn('fixep.py failed: ' .. ((res and (res.stderr ~= '' and res.stderr or res.error_string)) or '?'))
            return
        end
        local ass = res.stdout:match('fixed%-ass: ([^\r\n]+)')
        if not ass then  -- nothing to fix, or skipped
            mp.msg.info((res.stdout:gsub('%s+$', '')))
            return
        end
        if mp.get_property('path') ~= opened then return end  -- moved on to another file meanwhile
        mp.commandv('sub-add', ass, 'select', 'English (signs fixed)', 'eng')
        mp.msg.info('loaded ' .. ass)
        mp.osd_message('subfix: fixed English subs loaded')
    end)
end)
