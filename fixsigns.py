# Streaming-style ASS (Netflix etc.) -> signs get own top style and are extended over the dialogue they were serialized against.
# Optional 3rd arg: a Japanese-audio track of the same release, used to undo dialogue that was
# delayed or truncated to make room for a sign.
# Optional 4th arg: sign start overrides, lines of "old_start new_start" (ASS times), for signs held back
# behind dialogue. Picked by eye from frames; scene-cut detection got only 3 of 7 right.
# usage: fixsigns.py in.ass out.ass [jpn.ass|-] [overrides.txt]
import sys, re
src, dst = sys.argv[1:3]
ref = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != '-' else None
ovr_file = sys.argv[4] if len(sys.argv) > 4 else None
GAP, CAP = 0.3, 5.0  # ponytail: heuristic; sign's true on-screen time is unknown, cap keeps it sane
ADJ, SNAP, GROW = 0.15, 0.1, 2.0  # adjacency to sign, "already aligned" tolerance, max end extension

def t(s): h, m, x = s.split(':'); return int(h)*3600 + int(m)*60 + float(x)
def ts(v): return f"{int(v//3600)}:{int(v%3600//60):02d}:{v%60:05.2f}"
def plain(txt): return re.sub(r'\{[^}]*\}', '', txt).replace('\\N', ' ')
def issign(txt): p = plain(txt); return sum(c.isalpha() for c in p) >= 2 and p == p.upper()

lines = open(src, encoding='utf-8-sig').read().splitlines()
head, ev = [], []
for l in lines:
    if l.startswith('Dialogue:'):
        p = l.split(',', 9)
        txt = p[9].replace('{\\c&Hffffff&}', '').replace('\\c&Hffffff&', '').replace('{}', '')
        txt = re.sub(r'\{\\i0\}\\N\{\\i1\}', r'\\N', txt)  # one italic span across line break
        sign = issign(txt)
        if sign:
            p[3] = 'Sign'
            txt = re.sub(r'\\an\d', '', txt).replace('{}', '')
        p[9] = txt
        ev.append([t(p[1]), t(p[2]), sign, p])
    else:
        head.append(l)
        if l.startswith('Style:') and not any(h.startswith('Style: Sign,') for h in head[:-1]):
            f = l.split(',')  # base Sign on the first style, whatever it is called: 85% size, top-center
            f[0], f[2], f[18] = 'Style: Sign', str(round(float(f[2]) * 0.85)), '8'
            head.append(','.join(f))

if ref:
    jp = [(t(q[1]), t(q[2])) for q in (l.split(',', 9) for l in open(ref, encoding='utf-8-sig') if l.startswith('Dialogue:'))]
    dlg = [e for e in ev if not e[2]]
    for i, e in enumerate(ev):
        if e[2]: continue
        k = dlg.index(e)
        prev_end = dlg[k-1][1] if k else 0
        next_start = dlg[k+1][0] if k + 1 < len(dlg) else 1e9
        # delayed: starts right after a sign and the Japanese line started earlier
        if i and ev[i-1][2] and e[0] - ev[i-1][1] < ADJ and not any(abs(s - e[0]) <= SNAP for s, _ in jp):
            cand = [s for s, _ in jp if ev[i-1][0] - SNAP <= s < e[0] and s >= prev_end]
            if cand:
                print(f"start {ts(e[0])} -> {ts(max(cand))}  {plain(e[3][9])[:40]}")
                e[0] = max(cand)
        # truncated: ends right before a sign and the matching Japanese line runs longer
        if i + 1 < len(ev) and ev[i+1][2] and ev[i+1][0] - e[1] < ADJ:
            m = [k for k, (s, _) in enumerate(jp) if abs(s - e[0]) <= ADJ]
            if m:
                # English line may merge several Japanese lines: follow ones that start while it is still up
                k = m[-1]
                while k + 1 < len(jp) and jp[k+1][0] < e[1] and jp[k+1][0] - jp[k][1] < GAP:
                    k += 1
                new = min(jp[k][1], e[1] + GROW, next_start - 0.02)
                if new > e[1]:
                    print(f"end   {ts(e[1])} -> {ts(new)}  {plain(e[3][9])[:40]}")
                    e[1] = new

for i, e in enumerate(ev):
    if not e[2]: continue
    end, j = e[1], i + 1
    while j < len(ev) and not ev[j][2] and ev[j][0] - end <= GAP and ev[j][1] - e[0] <= CAP:
        end = ev[j][1]; j += 1
    e[1] = end

if ovr_file:
    ovr = dict(l.split() for l in open(ovr_file) if l.strip() and not l.startswith('#'))
    for e in ev:
        if e[2] and ovr.get(e[3][1]):
            print(f"sign  {e[3][1]} -> {ovr[e[3][1]]}  {plain(e[3][9])[:40]}")
            e[0] = t(ovr[e[3][1]])
    signs = sorted((e for e in ev if e[2]), key=lambda e: e[0])
    for a, b in zip(signs, signs[1:]):
        a[1] = min(a[1], b[0]) if b[0] > a[0] else a[1]  # don't stack two signs at the top
    ev.sort(key=lambda e: e[0])
for e in ev:
    e[3][1], e[3][2] = ts(e[0]), ts(e[1])

res = []
for l in (l for l in head if l.strip()):  # rebuild with blank lines before sections
    if l.startswith('[') and res: res.append('')
    res.append(l)
res += [','.join(e[3]) for e in ev]
open(dst, 'w', encoding='utf-8-sig').write('\n'.join(res) + '\n')
print(sum(e[2] for e in ev), 'signs of', len(ev))
