# One-shot driver: extract English + Japanese subs from a streaming-sourced MKV, run fixsigns.py, write contact sheets
# for signs that may have been held back behind dialogue, and remux the fixed track into the same file as the
# default English (original English kept, not default).
# Sign start overrides (picked from the sheets) go in overrides/<slug>.txt; rerun to apply them.
# usage: fixep.py episode.mkv [workroot]   (default: ./work next to this script)
import sys, os, re, json, subprocess
here = os.path.dirname(os.path.abspath(__file__))
mkv = sys.argv[1]
root = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, 'work')
stem = os.path.splitext(os.path.basename(mkv))[0]
slug = re.sub(r'[^\w.-]+', '_', re.sub(r'\[[0-9A-F]{8}\]$', '', stem)).strip('_')
wd = os.path.join(root, slug)
os.makedirs(os.path.join(wd, 'sheets'), exist_ok=True)
FRAMES, ROWS, LEAD = 16, 5, 2.0  # frames per sign strip, strips per sheet, seconds before the previous line

def run(*a): return subprocess.run(a, check=True, capture_output=True, text=True).stdout
def t(s): h, m, x = s.split(':'); return int(h)*3600 + int(m)*60 + float(x)

tracks = json.loads(run('mkvmerge', '-J', mkv))['tracks']
subs = [x for x in tracks if x['type'] == 'subtitles']
def pick(lang, cc):
    # cc=False: full subs, not SDH/CC/forced/signs-only; cc=True: the hearing-impaired track
    for x in subs:
        pr = x['properties']
        name = (pr.get('track_name') or '').lower()
        hi = bool(pr.get('flag_hearing_impaired') or 'cc' in name or 'sdh' in name)
        if pr.get('language') == lang and hi == cc and (cc or not (pr.get('forced_track') or 'forced' in name or 'sign' in name)):
            return x
eng, jpn, jcc = pick('eng', False), pick('jpn', False), pick('jpn', True)
if not eng: sys.exit('no full English subtitle track found')
eng_ass, jpn_ass, cc_ass, fixed = (os.path.join(wd, n) for n in ('eng.ass', 'jpn.ass', 'jpncc.ass', 'eng.fixed.ass'))
run('mkvextract', mkv, 'tracks', *(f"{x['id']}:{p}" for x, p in ((eng, eng_ass), (jpn, jpn_ass), (jcc, cc_ass)) if x))

ev = [(q[1], re.sub(r'\{[^}]*\}', '', q[9]).replace('\\N', ' ').strip(), q[2])
      for q in (l.split(',', 9) for l in open(eng_ass, encoding='utf-8-sig') if l.startswith('Dialogue:'))]
sign = lambda s: (lambda L: len(L) >= 2 and all(c.isupper() for c in L))([c for c in s if c.isalpha()])  # as fixsigns.issign
if not any(sign(txt) for _, txt, _ in ev):
    # every fix hangs off an ALL-CAPS sign; none means the subs weren't serialized (e.g. typeset Crunchyroll subs)
    print(f"no ALL-CAPS signs in '{eng['properties'].get('track_name') or 'English'}': nothing to fix, no output written")
    sys.exit(0)

cuts = os.path.join(wd, 'cuts.txt')  # shot changes, cached: a full decode takes ~30s
if not os.path.exists(cuts):
    log = subprocess.run(['ffmpeg', '-i', mkv, '-an', '-sn', '-vf', "scale=320:-2,select='gt(scene,0.25)',showinfo",
                          '-f', 'null', '-'], check=True, capture_output=True, text=True).stderr
    open(cuts, 'w').write(''.join(x + '\n' for x in re.findall(r'pts_time:([0-9.]+)', log)))

ovr = os.path.join(here, 'overrides', slug + '.txt')
args = [eng_ass, fixed, '--cuts', cuts] + (['--jpn', jpn_ass] if jpn else []) + (['--cc', cc_ass] if jcc else []) \
    + (['--overrides', ovr] if os.path.exists(ovr) else [])
print(run(sys.executable, '-I', os.path.join(here, 'fixsigns.py'), *args), end='')

# contact sheets, one row per sign to check by eye, FRAMES evenly spaced:
# - held back?  sign directly follows another line: from LEAD s before that line to just after the sign's start
# - shout?      a CC line with a speaker label, e.g. （ミナト）え？, and no sound label starts with it, so the caps
#               line may be a translated shout rather than drawn text: frames across the sign itself.
#               (overlap alone flagged 12/38 signs here, all drawn; same start flags 1)
rows = [(max(0, t(p[0]) - LEAD), t(c[0]) + 0.2, c[0], c[1], 'held back?')
        for p, c in zip(ev, ev[1:]) if sign(c[1]) and t(c[0]) - t(p[2]) < 0.15]
if jcc:
    def spoken(txt):  # a speaker label, （name） followed by dialogue, and no sound label （…） on a line of its own
        parts = [p.strip().lstrip('-').strip() for p in re.sub(r'\{[^}]*\}', '', txt).split('\\N')]
        label = [re.fullmatch(r'（[^）]*）', p) and (n + 1 == len(parts) or parts[n+1].startswith('（'))
                 for n, p in enumerate(parts)]
        return not any(label) and any(re.match(r'（[^）]*）\S', p) or (re.fullmatch(r'（[^）]*）', p) and not label[n])
                                      for n, p in enumerate(parts))
    talk = [(t(q[1]), t(q[2])) for q in (l.split(',', 9) for l in open(cc_ass, encoding='utf-8-sig')
                                         if l.startswith('Dialogue:')) if spoken(q[9])]
    rows += [(max(0, t(ss) - 0.5), t(se) + 0.3, ss, txt, 'shout?') for ss, txt, se in ev
             if sign(txt) and any(abs(s - t(ss)) <= 0.1 for s, _ in talk)]
for f in os.listdir(os.path.join(wd, 'sheets')): os.remove(os.path.join(wd, 'sheets', f))
index, strips = [], []
for n, (a, b, ss, txt, why) in enumerate(rows):
    step = (b - a) / (FRAMES - 1)
    strip = os.path.join(wd, 'sheets', f'strip{n:03d}.png')
    run('ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b - a + step:.3f}', '-i', mkv, '-an', '-sn',
        '-vf', f'fps=1/{step:.4f},scale=240:-2,tile={FRAMES}x1', '-frames:v', '1', '-y', strip)
    strips.append(strip)
    index.append(f"sheet{n // ROWS + 1:02d} row{n % ROWS + 1}  {why:10}  sign {ss}  frames {a:.2f}+k*{step:.3f}s  {txt[:40]}")
for g in range(0, len(strips), ROWS):
    grp = strips[g:g + ROWS]
    out = os.path.join(wd, 'sheets', f'sheet{g // ROWS + 1:02d}.png')
    ins = sum((['-i', s] for s in grp), [])
    run('ffmpeg', '-v', 'error', *ins, *(['-filter_complex', f'vstack={len(grp)}'] if len(grp) > 1 else []), '-y', out)
for s in strips: os.remove(s)
open(os.path.join(wd, 'sheets', 'index.txt'), 'w').write('\n'.join(index) + '\n')

# remux in place: fixed track goes in just before the original English one and becomes the default English;
# the original stays (not default). A "(signs fixed)" track from an earlier run is dropped and rebuilt.
old = [x['id'] for x in subs if (x['properties'].get('track_name') or '').endswith('(signs fixed)')]
order = [f"1:{x['id']}" for x in tracks if x['id'] not in old]
order.insert(order.index(f"1:{eng['id']}"), '0:0')
tmp = mkv + '.subfix-tmp.mkv'
run('mkvmerge', '-q', '-o', tmp, '--track-order', ','.join(order), '--language', '0:eng',
    '--track-name', f"0:{eng['properties'].get('track_name') or 'English'} (signs fixed)", '--default-track-flag', '0:yes',
    fixed, '--default-track-flag', f"{eng['id']}:no", *(['-s', '!' + ','.join(map(str, old))] if old else []), mkv)
new = json.loads(run('mkvmerge', '-J', tmp))['tracks']
first_eng = next(x for x in new if x['type'] == 'subtitles' and x['properties'].get('language') == 'eng')
if len(new) != len(tracks) - len(old) + 1 or not first_eng['properties'].get('track_name', '').endswith('(signs fixed)'):
    os.remove(tmp)
    sys.exit('remux check failed, original left untouched')
os.replace(tmp, mkv)  # same directory, so the swap is atomic
print(f"workdir: {wd}\nsheets:  {len(rows)} rows in {(len(rows) + ROWS - 1) // ROWS} sheets ({os.path.join(wd, 'sheets')})\n"
      f"overrides: {ovr if os.path.exists(ovr) else 'none yet'}\nupdated: {mkv} (default English: {first_eng['properties']['track_name']})")
