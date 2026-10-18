# subfix

Fixes English subs in streaming-sourced anime MKVs (Netflix, and others with the same style).
Netflix-style subs never show a sign and dialogue at the same time, so on-screen-text translations
(ALL-CAPS lines) and dialogue get delayed or cut short around each other.

```
python3 fixep.py "/path/to/episode.mkv"
```

Writes `<name>[fixed-eng].mkv` next to the input (the original is left alone). It:

- moves signs to their own top-of-screen `Sign` style (bottom when all dialogue alongside was moved to the top)
  and extends them over the dialogue that cut them off
- restores dialogue start/end times from the Japanese track's timing (first `jpn` track that isn't CC/SDH)
- times sound-effect signs from the Japanese CC track's sound labels, e.g. `（心臓の鼓動）` for BA-BUMP
- ends every sign by the first shot change after its listed end (drawn text leaves with its shot)
- writes contact sheets to `work/<episode>/sheets/` for every sign that directly follows another line
  (16 frames from 2 s before that line to the sign; `index.txt` maps rows to signs and frame times)
  plus a `shout?` row for any caps line that starts with a CC line carrying a speaker label (and no
  sound label): it may be a translated shout, not drawn text. If no text is drawn in that row, it's dialogue.

Signs Netflix held back behind dialogue can't be detected reliably (scene-cut detection got 3/7),
so their real start is picked by eye from the sheets into `overrides/<episode>.txt`:

```
# sign_start  new_start
0:06:59.12 0:06:56.33  # comments allowed
```

then rerun `fixep.py`. Requires `mkvtoolnix` and `ffmpeg`.

Tests: `python3 test_fixsigns.py` (stdlib only, made-up scripts, one case per rule).
