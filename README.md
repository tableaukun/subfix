# subfix

Fixes English subs in Netflix-sourced MKVs of non-English shows. Netflix never shows a sign (an on-screen-text
translation, in ALL CAPS) and dialogue at the same time, so the two get delayed or cut short around each other.

**Scope:** built for and tested on Netflix **anime** (Japanese audio). It acts on what the English subs look
like, not where they came from: ALL-CAPS signs that never share the screen with dialogue, and nothing positioned
by hand. Typeset subs (Crunchyroll, fansubs: `\pos` signs over the dialogue) and subs without signs are left
alone. The same rule applies to every non-English Netflix show, so a Korean drama or a Spanish series gets the
fixes too, but that is untested. The original-language subtitle track, when there is one, restores dialogue
timing; without it only the signs are fixed. The CC sound-label step (below) reads the Japanese CC format only.
English-language shows have no sign translations and are left alone.

## Requirements

Python 3.9+ (standard library only), `ffmpeg` and `mkvtoolnix` on PATH.

```
brew install ffmpeg mkvtoolnix                # macOS
sudo apt install python3 ffmpeg mkvtoolnix    # Debian/Ubuntu
```

## Install

```
git clone https://github.com/tableaukun/subfix.git
cd subfix
```

`git pull` in that folder updates it; files fixed by an older version are redone on their next run.

## Usage

From the `subfix` folder (or give the full path to `fixep.py`). One file:

```
python3 fixep.py "/path/to/episode.mkv"
```

A whole folder, e.g. a season, before watching:

```
for f in /path/to/season/*.mkv; do python3 fixep.py "$f"; done             # macOS / Linux
Get-ChildItem C:\path\to\season\*.mkv | % { python fixep.py $_.FullName }  # Windows PowerShell
```

Each file takes about 5-15 s (the shot-change check on lengthened signs and the contact sheets; longer while mpv is playing it, as it runs at low
priority). What it prints:

- `updated: … (default English: … (signs fixed v5))`: fixed
- `already fixed (v5): skipped`: done by the current version; add `--force` to redo it (e.g. after editing its
  overrides). A file fixed by an older version is redone automatically
- `no non-English audio: skipped`: never touched, e.g. an English film whose SDH has `[DOOR CLOSES]`
- `… isn't streaming-style …: nothing to fix`: typeset subs (e.g. Crunchyroll), or fewer than 2 caps signs that
  read like labels (several words, no closing `.`/`!`/`?`; a shouted "OK." or "MINATO!" doesn't count); file
  untouched. Checking takes one read of the file (a few seconds) on its first open, then it's remembered until the
  file changes
- `no full English ASS subtitle track: skipped`: bitmap (PGS) or SRT English subs aren't handled
- `another run is fixing this episode: skipped`: e.g. two mpv windows on one file
- `failed before on this exact file: skipped`: a run on this file failed (the error is in
  `work/<episode>/failed`); it isn't retried on every open until the file changes or you pass `--force`
- `… removed the old fixed track, original English is the default again`: an older version fixed a file the
  current one doesn't handle, so its track is taken back out

The fixed subs are added to the same file as the default English track, named `<original> (signs fixed vN)`, just
before the original English track (kept, no longer default). Every other track is kept. With `--strip`, subtitle
tracks other than English and the original language are removed for good (opt-in). The file is rewritten to a hidden temp copy
next to it, checked, then swapped in, so a failed or killed run leaves the original as it was. The file keeps its
permissions. A symlinked episode is fixed at its target. A hard-linked one (e.g. a seeding copy plus a library copy)
is split: the path you run it on gets the fix and becomes a separate file.

## What it fixes

- signs get their own top-of-screen `Sign` style. Dialogue Netflix lifted to the top (to keep clear of drawn text)
  keeps the top line and the sign sits under it
- signs last long enough to read, like dialogue: at least as long as Netflix listed them, 1.5 s minimum, about 17
  characters a second. A sign beside a line of dialogue stays until that line ends, if that's within twice its
  reading time. When that lengthens a sign, the added stretch is checked for a shot change: if the shot
  changes there, the drawn text has gone, so the sign ends at the change. The same sign repeated moments later
  (a heartbeat) is joined up instead of blinking
- dialogue start/end times are restored from the original-language subtitle track, which is timed to the speech
  (for anime, the first Japanese track that isn't CC/SDH). Releases without one keep Netflix's dialogue timing
- sound-effect signs start with their sound in the Japanese CC track's sound labels, e.g. `（心臓の鼓動）` for
  BA-BUMP (Japanese only)

## Sign start overrides

Signs Netflix held back behind dialogue can't be detected reliably (scene-cut detection got 3/7), so each run
writes contact sheets to `work/<episode>/sheets/` for checking by eye:

- a row for every sign that directly follows another line: 16 frames from 2 s before that line to the sign
- a `shout?` row for any caps line that starts with a CC line carrying a speaker label (and no sound label): it may
  be a translated shout, not drawn text. If no text is drawn in that row, it's dialogue

`index.txt` maps rows to signs and frame times. Real starts go in `work/<episode>/overrides.txt`:

```
# sign_start  new_start
0:06:59.12 0:06:56.33  # comments allowed
```

then rerun with `--force`. Without overrides, everything else is still fixed. `work/` isn't in git; everything in it
except `overrides.txt` is rebuilt on each run, so keep that file if you clear it out.

## mpv

`mpv/subfix.lua` runs `fixep.py` in the background whenever an MKV opens, then loads and selects the fixed English
subs (usually 5-15 s in). Files already fixed by the current version are skipped in a fraction of a second, so files
fixed beforehand start straight away; files fixed by an older version are redone. macOS: Homebrew is found even
when mpv starts from Finder. Add `strip=yes` to `script-opts/subfix.conf` for the `--strip` behaviour.

From the `subfix` folder:

macOS / Linux (a symlink, so `git pull` updates it too):

```
mkdir -p ~/.config/mpv/scripts && ln -sf "$PWD/mpv/subfix.lua" ~/.config/mpv/scripts/
```

Windows PowerShell (a copy, told where the repo is; add `python=py` to `subfix.conf` if `python` isn't on PATH):

```
New-Item -Force -ItemType Directory "$env:APPDATA\mpv\scripts", "$env:APPDATA\mpv\script-opts" | Out-Null
Copy-Item mpv\subfix.lua "$env:APPDATA\mpv\scripts\"
Set-Content "$env:APPDATA\mpv\script-opts\subfix.conf" "fixep=$PWD\fixep.py"
```

Windows can't replace a file that's playing, so there the fix loads for that session but isn't embedded.

## Versions

`VERSION` in `fixep.py` is stamped into the fixed track's name. Bump it whenever a change would alter the output;
every file fixed by an older version is then redone on its next run or mpv open.

## Tests

`python3 test_fixsigns.py` (stdlib only): made-up scripts, one case per timing rule, plus fixep.py's track
picking, remux plan, versions and lock on track listings shaped like `mkvmerge -J`.
