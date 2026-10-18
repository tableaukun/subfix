# One-shot driver: extract the English and original-language subs from a Netflix-sourced MKV, run fixsigns.py, write
# contact sheets for signs that may have been held back behind dialogue, and remux the fixed track into the same file as the
# default English (original English and every other track kept; --strip keeps only English + original-language subs).
# Sign start overrides (picked from the sheets) go in overrides/<slug>.txt; rerun to apply them.
# usage: fixep.py episode.mkv [workroot] [--force] [--strip]   (default workroot: ./work next to this script)
#   the fixed track is named "<original> (signs fixed vN)"; a file whose fixed track is already at VERSION is
#   skipped unless --force (e.g. after editing its overrides). Bump VERSION whenever the output would change,
#   so every older file is redone on its next run or mpv open
#   only touches non-English-audio releases with a subtitle track in the audio language, the timing reference
#   (built and tested on Netflix anime; Korean, Spanish etc. should work but are untested): anything else, e.g.
#   a Western film whose SDH has [DOOR CLOSES], is left alone
#   last line on success: "fixed-ass: <path>" (read by mpv/subfix.lua)
import sys, os, re, json, time, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixsigns import t, issign

FRAMES, ROWS, LEAD = 16, 5, 2.0  # frames per sign strip, strips per sheet, seconds before the previous line
STALE = 15 * 60  # a lock this old is from a killed run (a run takes ~1 min)
VERSION = 3  # v1: plain "(signs fixed)", before the second review; v2: signs tracked the drawn text (dialogue
             # chains, shot changes, CC end); v3: signs last their reading time

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
    # cc=False: full subs, not SDH/CC/forced/signs-only and not our own output; cc=True: the hearing-impaired track
    for x in subs:
        pr, n = x['properties'], name(x).lower()
        hi = bool(pr.get('flag_hearing_impaired') or re.search(r'\b(cc|sdh)\b', n))
        if fixed_version(n) or pr.get('language') != lang or hi != cc:
            continue
        if cc or not (pr.get('forced_track') or re.search(r'\b(forced|signs?)\b', n)):
            return x

def original_language(tracks):
    # first non-English audio language that also has a full subtitle track (timed to that speech): the reference.
    # A dual-audio release with an English dub first still finds its Japanese/Korean/... original
    subs = [x for x in tracks if x['type'] == 'subtitles']
    for x in tracks:
        lang = x['properties'].get('language')
        if x['type'] == 'audio' and lang not in ('eng', 'und', None) and pick(subs, lang, False):
            return lang

def plan_remux(tracks, eng, strip=False, lang='jpn'):
    # fixed track (input 0) goes in just before the original English one; an earlier fixed track is dropped;
    # strip (opt-in): only English and original-language subtitle tracks kept. Video, audio, fonts, chapters untouched
    subs = [x for x in tracks if x['type'] == 'subtitles']
    keep = [x['id'] for x in subs if not fixed_version(name(x))
            and (not strip or x['properties'].get('language') in ('eng', lang))]
    order = [f"1:{x['id']}" for x in tracks if x['type'] != 'subtitles' or x['id'] in keep]
    order.insert(order.index(f"1:{eng['id']}"), '0:0')
    return keep, order, len(tracks) - len(subs) + len(keep) + 1

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
            up = alive(pid) if pid else False
            if up or (up is None and time.time() - os.path.getmtime(path) < STALE):
                return None
            os.remove(path)

def main():
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
    done = max((fixed_version(name(x)) or 0 for x in subs), default=0)
    if done >= VERSION and not force:
        print(f'already fixed (v{done}): skipped (use --force to redo)')
        return
    if done:
        print(f'fixed by v{done}, current is v{VERSION}: redoing')
    lang = original_language(tracks)
    if not lang:
        print('not a non-English-audio release with original-language subs: skipped, file untouched')
        return
    # CC sound labels are parsed in the Japanese format （…） only; other languages just skip that step
    eng, ref, cc = pick(subs, 'eng', False), pick(subs, lang, False), pick(subs, lang, True) if lang == 'jpn' else None
    if not eng:
        sys.exit('no full English subtitle track found')

    wd = os.path.join(root, slug)
    os.makedirs(os.path.join(wd, 'sheets'), exist_ok=True)
    held = lock(wd)
    if not held:
        print('another run is fixing this episode: skipped')
        return
    tmp = None
    try:
        # temp copies from killed runs: hidden, not *.mkv, so players and folder loops never pick them up
        d, base = os.path.dirname(mkv), os.path.basename(mkv)
        for f in os.listdir(d):
            if f.startswith('.' + base + '.') and f.endswith('.subfix-tmp'):
                os.remove(os.path.join(d, f))

        eng_ass, ref_ass, cc_ass, fixed = (os.path.join(wd, n) for n in ('eng.ass', f'{lang}.ass', f'{lang}cc.ass', 'eng.fixed.ass'))
        mkvtool('mkvextract', mkv, 'tracks', *(f"{x['id']}:{p}" for x, p in ((eng, eng_ass), (ref, ref_ass), (cc, cc_ass)) if x))
        ev = [(q[1], q[9], q[2]) for q in (l.split(',', 9) for l in open(eng_ass, encoding='utf-8-sig') if l.startswith('Dialogue:'))]
        if not any(issign(txt) for _, txt, _ in ev):
            # every fix hangs off an ALL-CAPS sign; none means the subs weren't serialized
            print(f"no ALL-CAPS signs in '{name(eng) or 'English'}': nothing to fix, no output written")
            return

        ovr = os.path.join(here, 'overrides', slug + '.txt')
        args = [eng_ass, fixed, '--ref', ref_ass] + (['--cc', cc_ass] if cc else []) \
            + (['--overrides', ovr] if os.path.exists(ovr) else [])
        print(run(sys.executable, '-I', os.path.join(here, 'fixsigns.py'), *args), end='')

        rows = sheets(mkv, wd, ev, cc_ass if cc else None)

        keep, order, want = plan_remux(tracks, eng, strip, lang)
        fd, tmp = tempfile.mkstemp(dir=d, prefix='.' + base + '.', suffix='.subfix-tmp')
        os.close(fd)
        mkvtool('mkvmerge', '-q', '-o', tmp, '--track-order', ','.join(order), '--language', '0:eng',
                '--track-name', f"0:{name(eng) or 'English'} (signs fixed v{VERSION})", '--default-track-flag', '0:yes',
                fixed, '--default-track-flag', f"{eng['id']}:no", '-s', ','.join(map(str, keep)), mkv)
        new = json.loads(mkvtool('mkvmerge', '-J', tmp))['tracks']
        first_eng = next((x for x in new if x['type'] == 'subtitles' and x['properties'].get('language') == 'eng'), None)
        if len(new) != want or not first_eng or fixed_version(name(first_eng)) != VERSION:
            sys.exit('remux check failed, original left untouched')
        if not os.path.exists(mkv):  # moved or deleted meanwhile (e.g. mpv's move-after-play): don't recreate it here
            sys.exit('original moved or deleted during the fix: left alone')
        try:
            os.replace(tmp, mkv)  # same directory, so the swap is atomic
            tmp = None
            status = f"updated: {mkv} (default English: {name(first_eng)})"
        except OSError as err:  # Windows (file open in the player), some network shares: fixed subs still load in mpv
            status = f'file in use ({err.strerror}), fixed track not embedded (it will be redone next time)'
        print(f"workdir: {wd}\nsheets:  {len(rows)} rows in {(len(rows) + ROWS - 1) // ROWS} sheets ({os.path.join(wd, 'sheets')})\n"
              f"overrides: {ovr if os.path.exists(ovr) else 'none yet'}\n{status}\nfixed-ass: {fixed}")
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
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
