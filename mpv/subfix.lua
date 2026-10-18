-- subfix: when an MKV opens, run fixep.py in the background (playback isn't held up), then load and select the
-- fixed English subs. fixep.py also embeds the fixed track in the file, so later plays skip all of this.
-- Install: ln -s ~/Documents/projects/subfix/mpv/subfix.lua ~/.config/mpv/scripts/
local utils = require 'mp.utils'
local FIXEP = os.getenv('HOME') .. '/Documents/projects/subfix/fixep.py'
local PATH = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'  -- mpv started from Finder has no Homebrew PATH

mp.register_event('file-loaded', function()
    local opened = mp.get_property('path')
    if not opened or opened:match('^%a+://') or not opened:lower():match('%.mkv$') then return end
    for _, t in ipairs(mp.get_property_native('track-list', {})) do
        if t.type == 'sub' and t.title and t.title:match('%(signs fixed%)$') then return end  -- already fixed
    end
    local abs = opened:match('^/') and opened or utils.join_path(mp.get_property('working-directory'), opened)
    mp.msg.info('fixing subs in the background')
    mp.command_native_async({
        name = 'subprocess', playback_only = false, capture_stdout = true, capture_stderr = true,
        args = {'/usr/bin/env', 'PATH=' .. PATH, 'python3', '-I', FIXEP, abs},
    }, function(ok, res)
        if not ok or res.status ~= 0 then
            mp.msg.warn('fixep.py failed: ' .. ((res and (res.stderr ~= '' and res.stderr or res.error_string)) or '?'))
            return
        end
        local ass = res.stdout:match('fixed%-ass: ([^\n]+)')
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
