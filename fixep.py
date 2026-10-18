# One-shot driver: extract the English and original-language subs from a Netflix-sourced MKV, run fixsigns.py, write
# contact sheets for signs that may have been held back behind dialogue, and remux the fixed track into the same file as the
# default English (original English and every other track kept; --strip keeps only English + original-language subs).
# Sign start overrides (picked from the sheets) go in overrides/<slug>.txt; rerun to apply them.
# usage: fixep.py episode.mkv [workroot] [--force] [--strip]   (default workroot: ./work next to this script)
#   the fixed track is named "<original> (signs fixed vN)"; a file whose fixed track is already at VERSION is
#   skipped unless --force (e.g. after editing its overrides). Bump VERSION whenever the output would change,
#   so every older file is redone on its next run or mpv open
#   only touches non-English-audio releases whose English subs are serialized (fixsigns.serialized): typeset subs
#   (Crunchyroll, fansubs) and English-audio films, e.g. SDH with [DOOR CLOSES], are left alone. A subtitle track
#   in the audio language, when there is one, is the dialogue timing reference (built and tested on Netflix anime;
#   Korean, Spanish etc. should work but are untested)
#   last line on success: "fixed-ass: <path>" (read by mpv/subfix.lua)
import sys, os, re, json, stat, time, tempfile, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixsigns import t, issign, serialized

FRAMES, ROWS, LEAD = 16, 5, 2.0  # frames per sign strip, strips per sheet, seconds before the previous line
STALE = 15 * 60  # a lock this old is from a killed run (a run takes ~1 min)
VERSION = 5  # v1: plain "(signs fixed)", before the second review; v2: signs tracked the drawn text (dialogue
             # chains, shot changes, CC end); v3: signs last their reading time; v4: ...unless the shot changes
             # first, and a repeated sign doesn't blink; v5: ...or until the dialogue beside it ends.
             # Also bump for scope changes (serialized(), pick()): the clean/failed markers carry the version

def fixed_version(n):  # None: not one of ours; 1: unversioned "(signs fixed)"
    m = re.search(r'\(signs fixed(?: v(\d+))?\)$', n)
    return m and int(m.group(1) or 1)

def run(*a, ok=(0,)):
    r = subprocess.run(a, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode not in ok:
        raise subprocess.CalledProcessError(r.returncode, a, r.stdout, r.stderr)
    return r.stdout
def mkvtool(*a): return run(*a, ok=(0, 1))  # mkvtoolnix exits 1 on warnings, output still complete
def name(x): return x['properties'].get('track_name') or ''

def pick(subs, lang, cc):
    # cc=False: full subs, not SDH/CC/forced/signs-only and not our own output; cc=True: the hearing-impaired track.
    # ASS/SSA text only: Netflix rips come as ASS; bitmap (PGS) or SRT tracks are out of scope
    for x in subs:
        pr, n = x['properties'], name(x).lower()
        hi = bool(pr.get('flag_hearing_impaired') or re.search(r'\b(cc|sdh)\b', n))
        if fixed_version(n) or pr.get('language') != lang or hi != cc or pr.get('codec_id') not in ('S_TEXT/ASS', 'S_TEXT/SSA'):
            continue
        if cc or not (pr.get('forced_track') or re.search(r'\b(forced|signs?)\b', n)):
            return x

def original_language(tracks):
    # the audio's language when it isn't English. Default audio first (a dual-audio release with an English dub
    # first still finds its original); commentary tracks never count, or --strip could delete the real original's
    # subtitles. One with a full subtitle track (timed to that speech, the reference) beats one without
    audio = [x for x in tracks if x['type'] == 'audio' and not re.search(r'comment', name(x), re.I)]
    subs = [x for x in tracks if x['type'] == 'subtitles']
    langs = [x['properties'].get('language') for x in sorted(audio, key=lambda x: not x['properties'].get('default_track'))]
    langs = [l for l in langs if l not in ('eng', 'und', None)]
    return next((l for l in langs if pick(subs, l, False)), langs[0] if langs else None)

def plan_remux(tracks, strip=False, lang='jpn'):
    # fixed track (input 0) goes in just before the first English subtitle track (even a forced or SDH one), so it's
    # the one players pick; earlier fixed tracks are dropped. strip (opt-in): only English and original-language
    # subtitle tracks kept. Video, audio, fonts and chapters untouched. Returns kept ids, track order, English ids
    # (to clear their default flag) and the expected track count
    subs = [x for x in tracks if x['type'] == 'subtitles']
    keep = [x['id'] for x in subs if not fixed_version(name(x))
            and (not strip or x['properties'].get('language') in ('eng', lang))]
    english = [x['id'] for x in subs if x['id'] in keep and x['properties'].get('language') == 'eng']
    order = [f"1:{x['id']}" for x in tracks if x['type'] != 'subtitles' or x['id'] in keep]
    order.insert(order.index(f"1:{english[0]}"), '0:0')
    return keep, order, english, len(tracks) - len(subs) + len(keep) + 1

def alive(pid):
    if os.name != 'posix':
        return None  # os.kill(pid, 0) sends Ctrl-C on Windows: fall back to the lock's age
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

def lock(wd):
    # one run per episode (two mpv windows, mpv plus the folder loop); a lock from a killed run is taken over
    path = os.path.join(wd, 'lock')
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                pid = int(open(path).read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            up = alive(pid) if pid else False  # None: can't tell (Windows)
            if up is not False and time.time() - os.path.getmtime(path) < STALE:  # a reused pid stops counting too
                return None
            os.remove(path)

def shot_changes(mkv, wins):
    def scan(w):
        a, b = max(0, w[0]), w[1]
        log = subprocess.run(['ffmpeg', '-nostdin', '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', mkv, '-an', '-sn',
                              '-vf', "scale=320:-2,select='gt(scene,0.25)',showinfo", '-f', 'null', '-'],
                             check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stderr
        return [a + float(x) for x in re.findall(r'pts_time:([0-9.]+)', log)]  # pts restart at 0 after -ss
    with ThreadPoolExecutor(max(1, (os.cpu_count() or 2) // 2)) as pool:
        return sorted(c for found in pool.map(scan, wins) for c in found)

def rewrite(mkv, make, check):
    # write a new version next to the episode with make(tmp), check its track listing, then swap it in atomically:
    # the original is untouched unless every step succeeds. The temp is hidden and not *.mkv, so players and
    # folder loops never pick it up. Returns (new tracks, problem or None)
    d, base = os.path.dirname(mkv), os.path.basename(mkv)
    for f in os.listdir(d):  # left by killed runs
        if f.startswith('.' + base + '.') and f.endswith('.subfix-tmp'):
            os.remove(os.path.join(d, f))
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.' + base + '.', suffix='.subfix-tmp')
    os.close(fd)
    try:
        make(tmp)
        new = json.loads(mkvtool('mkvmerge', '-J', tmp))['tracks']
        if not check(new):
            sys.exit('remux check failed, original left untouched')
        if not os.path.exists(mkv):  # moved or deleted meanwhile (e.g. mpv's move-after-play): don't recreate it here
            sys.exit('original moved or deleted during the fix: left alone')
        os.chmod(tmp, stat.S_IMODE(os.stat(mkv).st_mode))  # mkstemp makes it 0600; keep the episode's own permissions
        try:
            os.replace(tmp, mkv)  # same directory, so the swap is atomic
        except OSError as err:  # Windows (file open in the player), some network shares: fixed subs still load in mpv
            return new, f'file in use ({err.strerror}), not rewritten (it will be redone next time)'
        return new, None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        sys.exit(__doc__ or 'usage: fixep.py episode.mkv [workroot] [--force] [--strip]')
    if hasattr(os, 'nice'):
        os.nice(10)  # mpv may be playing this very file: let playback have the CPU first (children inherit it)
    here = os.path.dirname(os.path.abspath(__file__))
    force, strip = '--force' in sys.argv, '--strip' in sys.argv
    argv = [x for x in sys.argv[1:] if x not in ('--force', '--strip')]
    mkv = os.path.realpath(argv[0])  # a symlinked episode: rewrite the real file, keep the link
    root = argv[1] if len(argv) > 1 else os.path.join(here, 'work')
    stem = os.path.splitext(os.path.basename(mkv))[0]
    slug = re.sub(r'[^\w.-]+', '_', re.sub(r'\[[0-9A-F]{8}\]$', '', stem)).strip('_')

    tracks = json.loads(mkvtool('mkvmerge', '-J', mkv))['tracks']
    subs = [x for x in tracks if x['type'] == 'subtitles']
    ours = [fixed_version(name(x)) for x in subs if fixed_version(name(x))]
    if ours == [VERSION] and not force:
        print(f'already fixed (v{VERSION}): skipped (use --force to redo)')
        return
    if ours:
        print(f"fixed before (v{', v'.join(map(str, ours))}), current is v{VERSION}: redoing")
    lang = original_language(tracks)
    # CC sound labels are parsed in the Japanese format （…） only; other languages just skip that step
    eng = pick(subs, 'eng', False)
    ref, cc = (pick(subs, lang, False), pick(subs, lang, True) if lang == 'jpn' else None) if lang else (None, None)
    why = None if eng and lang else 'no non-English audio' if eng else 'no full English ASS subtitle track'
    if why and not ours:
        print(f'{why}: skipped, file untouched')
        return
    wd = os.path.join(root, slug)
    os.makedirs(wd, exist_ok=True)
    held = lock(wd)
    if not held:
        print('another run is fixing this episode: skipped')
        return
    # a run that failed, or found nothing to fix, on this exact file isn't repeated on every open
    failed, clean = os.path.join(wd, 'failed'), os.path.join(wd, 'clean')
    st = os.stat(mkv)
    stamp = f'{st.st_size} {st.st_mtime_ns} v{VERSION}'
    seen = lambda f: not force and os.path.exists(f) and open(f).read().split('\n')[0] == stamp
    try:
        if seen(failed):
            print(f'failed before on this exact file (see {failed}): skipped, use --force to retry')
            return
        if seen(clean):
            print(f"{(open(clean).read().split(chr(10)) + ['subs'])[1]}: nothing to fix (checked before), file untouched")
            return
        eng_ass, ref_ass, cc_ass, fixed = (os.path.join(wd, n) for n in ('eng.ass', f'{lang}.ass', f'{lang}cc.ass', 'eng.fixed.ass'))
        if not why:
            mkvtool('mkvextract', mkv, 'tracks', *(f"{x['id']}:{p}" for x, p in ((eng, eng_ass), (ref, ref_ass), (cc, cc_ass)) if x))
            if not serialized(eng_ass):
                why = f"'{name(eng) or 'English'}' isn't streaming-style (no ALL-CAPS signs, or typeset ones)"
        if why:
            if not ours:
                open(clean, 'w').write(f'{stamp}\n{why}\n')
                print(f'{why}: nothing to fix, file untouched')
                return
            # an older version fixed a file this one wouldn't touch: take our track out, original English default again
            keep = [x['id'] for x in subs if not fixed_version(name(x))]
            dflt = [f"{eng['id']}:yes"] if eng else []
            _, problem = rewrite(mkv, lambda tmp: mkvtool('mkvmerge', '-q', '-o', tmp, '-s', ','.join(map(str, keep)),
                                                          *sum((['--default-track-flag', x] for x in dflt), []), mkv),
                                 lambda new: len(new) == len(tracks) - len(ours)
                                             and not any(fixed_version(name(x)) for x in new))
            print(problem or f'{why}: removed the old fixed track, original English is the default again')
            return
        os.makedirs(os.path.join(wd, 'sheets'), exist_ok=True)
        ev = [(q[1], q[9], q[2]) for q in (l.split(',', 9) for l in open(eng_ass, encoding='utf-8-sig') if l.startswith('Dialogue:'))]

        ovr = os.path.join(here, 'overrides', slug + '.txt')
        args = [sys.executable, '-I', os.path.join(here, 'fixsigns.py'), eng_ass, fixed] + (['--ref', ref_ass] if ref else []) \
            + (['--cc', cc_ass] if cc else []) + (['--overrides', ovr] if os.path.exists(ovr) else [])
        # twice: first to find where signs get lengthened, then with the shot changes found only there
        wins, cuts = os.path.join(wd, 'stretches.txt'), os.path.join(wd, 'cuts.txt')
        run(*args, '--stretches', wins)
        found = shot_changes(mkv, [tuple(map(float, l.split())) for l in open(wins) if l.strip()])
        open(cuts, 'w').write(''.join(f'{c:.3f}\n' for c in found))
        print(run(*args, '--cuts', cuts), end='')

        try:  # contact sheets are for checking by eye; never let them block the fix
            rows = sheets(mkv, wd, ev, cc_ass if cc else None)
        except (OSError, subprocess.CalledProcessError) as err:
            rows = []
            print(f'contact sheets failed ({err}), fixing anyway')

        keep, order, english, want = plan_remux(tracks, strip, lang)
        new, problem = rewrite(mkv, lambda tmp: mkvtool(
            'mkvmerge', '-q', '-o', tmp, '--track-order', ','.join(order), '--language', '0:eng',
            '--track-name', f"0:{name(eng) or 'English'} (signs fixed v{VERSION})", '--default-track-flag', '0:yes',
            fixed, *sum((['--default-track-flag', f'{i}:no'] for i in english), []), '-s', ','.join(map(str, keep)), mkv),
            lambda new: len(new) == want and fixed_version(name(next(
                x for x in new if x['type'] == 'subtitles' and x['properties'].get('language') == 'eng'))) == VERSION)
        for f in (failed, clean):  # e.g. a fix that couldn't be swapped in must be tried again next open
            if os.path.exists(f):
                os.remove(f)
        title = f"{name(eng) or 'English'} (signs fixed v{VERSION})"
        print(f"workdir: {wd}\nsheets:  {len(rows)} rows in {(len(rows) + ROWS - 1) // ROWS} sheets ({os.path.join(wd, 'sheets')})\n"
              f"overrides: {ovr if os.path.exists(ovr) else 'none yet'}\n"
              f"{problem or f'updated: {mkv} (default English: {title})'}\nfixed-ass: {fixed}")
    except BaseException as err:
        if not isinstance(err, KeyboardInterrupt):
            open(failed, 'w').write(f'{stamp}\n{err!r}\n')
        raise
    finally:
        os.remove(held)

def sheets(mkv, wd, ev, cc_ass):
    # contact sheets, one row per sign to check by eye, FRAMES evenly spaced:
    # - held back?  sign directly follows another line: from LEAD s before that line to just after the sign's start
    # - shout?      a CC line with a speaker label, e.g. （ミナト）え？, and no sound label starts with it, so the caps
    #               line may be a translated shout rather than drawn text: frames across the sign itself.
    #               (overlap alone flagged 12/38 signs here, all drawn; same start flags 1)
    plain = lambda s: re.sub(r'\{[^}]*\}', '', s).replace('\\N', ' ').strip()
    rows = [(max(0, t(p[0]) - LEAD), t(c[0]) + 0.2, c[0], plain(c[1]), 'held back?')
            for p, c in zip(ev, ev[1:]) if issign(c[1]) and t(c[0]) - t(p[2]) < 0.15]
    if cc_ass:
        def spoken(txt):  # a speaker label, （name） followed by dialogue, and no sound label （…） on a line of its own
            parts = [p.strip().lstrip('-').strip() for p in re.sub(r'\{[^}]*\}', '', txt).split('\\N')]
            label = [re.fullmatch(r'（[^）]*）', p) and (n + 1 == len(parts) or parts[n+1].startswith('（'))
                     for n, p in enumerate(parts)]
            return not any(label) and any(re.match(r'（[^）]*）\S', p) or (re.fullmatch(r'（[^）]*）', p) and not label[n])
                                          for n, p in enumerate(parts))
        talk = [t(q[1]) for q in (l.split(',', 9) for l in open(cc_ass, encoding='utf-8-sig')
                                  if l.startswith('Dialogue:')) if spoken(q[9])]
        rows += [(max(0, t(ss) - 0.5), t(se) + 0.3, ss, plain(txt), 'shout?') for ss, txt, se in ev
                 if issign(txt) and any(abs(s - t(ss)) <= 0.1 for s in talk)]
    sd = os.path.join(wd, 'sheets')
    for f in os.listdir(sd): os.remove(os.path.join(sd, f))
    index, strips = [], []
    for n, (a, b, ss, txt, why) in enumerate(rows):
        step = (b - a) / (FRAMES - 1)
        strip = os.path.join(sd, f'strip{n:03d}.png')
        run('ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b - a + step:.3f}', '-i', mkv, '-an', '-sn',
            '-vf', f'fps=1/{step:.4f},scale=240:-2,tile={FRAMES}x1', '-frames:v', '1', '-y', strip)
        strips.append(strip)
        index.append(f"sheet{n // ROWS + 1:02d} row{n % ROWS + 1}  {why:10}  sign {ss}  frames {a:.2f}+k*{step:.3f}s  {txt[:40]}")
    for g in range(0, len(strips), ROWS):
        grp = strips[g:g + ROWS]
        ins = sum((['-i', s] for s in grp), [])
        run('ffmpeg', '-nostdin', '-v', 'error', *ins, *(['-filter_complex', f'vstack={len(grp)}'] if len(grp) > 1 else []),
            '-y', os.path.join(sd, f'sheet{g // ROWS + 1:02d}.png'))
    for s in strips: os.remove(s)
    open(os.path.join(sd, 'index.txt'), 'w').write('\n'.join(index) + '\n')
    return rows

if __name__ == '__main__':
    main()
