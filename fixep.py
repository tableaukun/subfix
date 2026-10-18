# One-shot driver: extract English + Japanese subs from a streaming-sourced MKV, run fixsigns.py, write contact sheets
# for signs that may have been held back behind dialogue, and remux to "<name>[fixed-eng].mkv" beside the input.
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
FRAMES, ROWS = 12, 5  # frames per sign strip, strips per sheet

def run(*a): return subprocess.run(a, check=True, capture_output=True, text=True).stdout
def t(s): h, m, x = s.split(':'); return int(h)*3600 + int(m)*60 + float(x)

tracks = json.loads(run('mkvmerge', '-J', mkv))['tracks']
subs = [x for x in tracks if x['type'] == 'subtitles']
eng = next(x for x in subs if x['properties'].get('language') == 'eng')
jpn = next((x for x in subs if x['properties'].get('language') == 'jpn'
            and 'CC' not in (x['properties'].get('track_name') or '')), None)
eng_ass, jpn_ass, fixed = (os.path.join(wd, n) for n in ('eng.ass', 'jpn.ass', 'eng.fixed.ass'))
run('mkvextract', mkv, 'tracks', f"{eng['id']}:{eng_ass}", *([f"{jpn['id']}:{jpn_ass}"] if jpn else []))

ovr = os.path.join(here, 'overrides', slug + '.txt')
args = [eng_ass, fixed, jpn_ass if jpn else '-'] + ([ovr] if os.path.exists(ovr) else [])
print(run(sys.executable, '-I', os.path.join(here, 'fixsigns.py'), *args), end='')

# contact sheets: each row = one sign, FRAMES evenly spaced from the preceding dialogue start to the sign start
ev = [(q[1], re.sub(r'\{[^}]*\}', '', q[9]).replace('\\N', ' ').strip(), q[2])
      for q in (l.split(',', 9) for l in open(eng_ass, encoding='utf-8-sig') if l.startswith('Dialogue:'))]
sign = lambda s: sum(c.isalpha() for c in s) >= 2 and s == s.upper()
cand = [(p[0], c[0], c[1]) for p, c in zip(ev, ev[1:]) if sign(c[1]) and not sign(p[1]) and t(c[0]) - t(p[2]) < 0.15]
index, strips = [], []
for n, (ds, ss, txt) in enumerate(cand):
    a, b = t(ds), t(ss) + 0.2
    step = (b - a) / (FRAMES - 1)
    strip = os.path.join(wd, 'sheets', f'strip{n:03d}.png')
    run('ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b - a + step:.3f}', '-i', mkv, '-an', '-sn',
        '-vf', f'fps=1/{step:.4f},scale=240:-2,tile={FRAMES}x1', '-frames:v', '1', '-y', strip)
    strips.append(strip)
    index.append(f"sheet{n // ROWS + 1:02d} row{n % ROWS + 1}  sign {ss}  frames {a:.2f}+k*{step:.3f}s  {txt[:40]}")
for g in range(0, len(strips), ROWS):
    grp = strips[g:g + ROWS]
    out = os.path.join(wd, 'sheets', f'sheet{g // ROWS + 1:02d}.png')
    ins = sum((['-i', s] for s in grp), [])
    run('ffmpeg', '-v', 'error', *ins, *(['-filter_complex', f'vstack={len(grp)}'] if len(grp) > 1 else []), '-y', out)
for s in strips: os.remove(s)
open(os.path.join(wd, 'sheets', 'index.txt'), 'w').write('\n'.join(index) + '\n')

out = os.path.join(os.path.dirname(mkv), re.sub(r'\[[0-9A-F]{8}\]$', '', stem) + '[fixed-eng].mkv')
if os.path.exists(out): os.remove(out)
run('mkvmerge', '-q', '-o', out, '--track-order', f'1:0,1:1,0:0', '--language', '0:eng',
    '--track-name', f"0:{eng['properties'].get('track_name') or 'English'} (signs fixed)", '--default-track-flag', '0:yes', fixed, '-s', f"!{eng['id']}", mkv)
print(f"workdir: {wd}\nsheets:  {len(cand)} signs in {(len(cand) + ROWS - 1) // ROWS} sheets ({os.path.join(wd, 'sheets')})\n"
      f"overrides: {ovr if os.path.exists(ovr) else 'none yet'}\noutput:  {out}")
