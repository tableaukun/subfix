# subfix

Fixes English subs in streaming-sourced anime MKVs (Netflix, and others with the same style).
Netflix-style subs never show a sign and dialogue at the same time, so on-screen-text translations
(ALL-CAPS lines) and dialogue get delayed or cut short around each other.

## Requirements

Python 3.9+ (standard library only), `ffmpeg` and `mkvtoolnix` on PATH.

```
brew install ffmpeg mkvtoolnix                # macOS
sudo apt install python3 ffmpeg mkvtoolnix    # Debian/Ubuntu
```

## Usage

One file:

```
python3 fixep.py "/path/to/episode.mkv"
```

A whole folder, e.g. a season, before watching:

```
for f in /path/to/season/*.mkv; do python3 fixep.py "$f"; done             # macOS / Linux
Get-ChildItem C:\path\to\season\*.mkv | % { python fixep.py $_.FullName }  # Windows PowerShell
```

Each file takes about 40 s (most of it shot-change detection). What it prints:

- `updated: … (default English: … (signs fixed))`: fixed
- `no ALL-CAPS signs …: nothing to fix`: subs aren't Netflix-style (e.g. typeset Crunchyroll subs); file untouched
- `already has a "(signs fixed)" track: skipped`: done before; add `--force` to redo it (e.g. after editing its
  overrides)

The fixed subs are added to the same file as the default English track, just before the original English track
(kept, no longer default). Only English and Japanese subtitle tracks are kept; video, audio, fonts and chapters are
untouched. The file is rewritten to a temp copy next to it, checked, then swapped in, so a failed run leaves the
original as it was.

## What it fixes

- signs get their own top-of-screen `Sign` style and are extended over the dialogue that cut them off. Dialogue
  Netflix lifted to the top (to keep clear of drawn text) keeps the top line and the sign sits under it
- dialogue start/end times are restored from the Japanese track's timing (first `jpn` track that isn't CC/SDH)
- sound-effect signs are timed from the Japanese CC track's sound labels, e.g. `（心臓の鼓動）` for BA-BUMP
- every sign ends by the first shot change after its listed end (drawn text leaves with its shot)

## Sign start overrides

Signs Netflix held back behind dialogue can't be detected reliably (scene-cut detection got 3/7), so each run
writes contact sheets to `work/<episode>/sheets/` for checking by eye:

- a row for every sign that directly follows another line: 16 frames from 2 s before that line to the sign
- a `shout?` row for any caps line that starts with a CC line carrying a speaker label (and no sound label): it may
  be a translated shout, not drawn text. If no text is drawn in that row, it's dialogue

`index.txt` maps rows to signs and frame times. Real starts go in `overrides/<episode>.txt`:

```
# sign_start  new_start
0:06:59.12 0:06:56.33  # comments allowed
```

then rerun with `--force`. Without overrides, everything else is still fixed.

## mpv

`mpv/subfix.lua` runs `fixep.py` in the background whenever an MKV opens, then loads and selects the fixed English
subs (about 40 s in). Files that already have a "(signs fixed)" track are skipped, so files fixed beforehand
start straight away. macOS: Homebrew is found even when mpv starts from Finder.

- macOS / Linux: `ln -s /path/to/subfix/mpv/subfix.lua ~/.config/mpv/scripts/` (the symlink is followed back
  to the repo)
- Windows, or a copied script: copy it to `%APPDATA%\mpv\scripts\` and create `script-opts\subfix.conf` with
  `fixep=C:\path\to\subfix\fixep.py` (and `python=py` if `python` isn't on PATH). Windows can't replace a file
  that's playing, so the fix loads for that session but isn't embedded.

## Tests

`python3 test_fixsigns.py` (stdlib only, made-up scripts, one case per rule).
