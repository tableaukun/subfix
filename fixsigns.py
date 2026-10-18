# Streaming-style ASS (Netflix etc.) -> signs get own style and their timing is un-serialized from the dialogue
# (streaming subs never show a sign and dialogue at once, so one of them gets delayed or cut short).
#   --ref  subtitle track in the audio's language (Japanese for anime), timed to the speech: restores dialogue
#          that was delayed/cut short by a sign. --jpn is the old name
#   --cc   Japanese CC track: lines entirely in （…） are sound labels; they give the real start of SFX signs
#   --overrides  lines of "old_start new_start" (ASS times) for signs held back behind dialogue, picked by eye
#                from contact sheets (scene-cut detection got only 3 of 7 right)
# Signs last long enough to read, like dialogue, not for as long as the drawn text is on screen: at least as listed,
# READ_MIN at minimum, READ_CPS characters a second. (Tracking the drawn text needed a dialogue-chain heuristic and a
# shot-change scan; reading time differed by under 0.5 s past a shot change for 5 of 38 signs.)
#   --cuts shot-change times found in the stretch a sign is lengthened past its listed end (fixep.py scans only
#          there): the drawn text has left, so the sign ends at the change instead, never before its listed end
# usage: fixsigns.py in.ass out.ass [--ref R] [--cc C] [--cuts S] [--overrides O]
import argparse, re
READ_MIN, READ_CPS = 1.5, 17  # Netflix-style reading speed; signs sit at the top, so a little slower than 20 cps
CAP = 5.0  # a CC sound label may start up to this long before its (held-back) sign
ADJ, SNAP = 0.15, 0.1  # adjacency to a sign, "already aligned" tolerance

def t(s): h, m, x = s.split(':'); return int(h)*3600 + int(m)*60 + float(x)
def ts(v):  # whole centiseconds first: 119.996 must give 0:02:00.00, not 0:01:60.00
    cs = round(v * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"
def plain(txt): return re.sub(r'\{[^}]*\}', '', txt).replace('\\N', ' ')
def reading(txt): return max(READ_MIN, len(plain(txt).strip()) / READ_CPS)  # seconds to read a sign
def issign(txt):  # ALL-CAPS Latin text; kana/kanji have no case so never count
    letters = [c for c in plain(txt) if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)
def cues(path):
    return [(t(q[1]), t(q[2]), q[9]) for q in (l.rstrip('\n').split(',', 9) for l in open(path, encoding='utf-8-sig')
                                               if l.startswith('Dialogue:'))]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--ref', '--jpn', dest='ref'); ap.add_argument('--cc'); ap.add_argument('--cuts'); ap.add_argument('--overrides')
    a = ap.parse_args()
    lines = open(a.src, encoding='utf-8-sig').read().splitlines()
    has_sign_style = any(l.startswith('Style: Sign,') for l in lines)
    added = False
    head, ev = [], []  # ev: [start, end, is_sign, fields]
    dlg_size = dlg_mv = None  # first non-Sign style: dialogue font size and vertical margin
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
            if l.startswith('Style:') and not l.startswith('Style: Sign,') and dlg_size is None:
                dlg_size, dlg_mv = float(l.split(',')[2]), int(l.split(',')[21])
            if l.startswith('Style:') and not has_sign_style:
                f = l.split(',')  # base Sign on the first style, whatever it is called: 85% size, top-center
                f[0], f[2], f[18] = 'Style: Sign', str(round(float(f[2]) * 0.85)), '8'
                head.append(','.join(f))
                has_sign_style = added = True

    if a.ref:
        jp = [(s, e) for s, e, _ in cues(a.ref)]
        dlg = [e for e in ev if not e[2]]
        pos = {id(e): k for k, e in enumerate(dlg)}  # by identity: two identical lines must keep their own neighbours
        for i, e in enumerate(ev):
            if e[2]: continue
            k = pos[id(e)]
            prev_end = dlg[k-1][1] if k else 0
            next_start = dlg[k+1][0] if k + 1 < len(dlg) else 1e9
            # delayed: starts right after a sign and the Japanese line started earlier
            if i and ev[i-1][2] and e[0] - ev[i-1][1] < ADJ and not any(abs(s - e[0]) <= SNAP for s, _ in jp):
                cand = [s for s, _ in jp if ev[i-1][0] - SNAP <= s < e[0] and s >= prev_end]
                if cand:
                    print(f"start {ts(e[0])} -> {ts(max(cand))}  {plain(e[3][9])[:40]}")
                    e[0] = max(cand)
            # truncated: ends right before a sign and the Japanese speech it covers runs longer.
            # Pair by overlap, not start: the English line may start early (chained to the previous line)
            # or merge several Japanese lines.
            if i + 1 < len(ev) and ev[i+1][2] and ev[i+1][0] - e[1] < ADJ:
                ends = [x for s, x in jp if e[0] - ADJ <= s < e[1]]
                if ends:
                    new = min(max(ends), next_start - 0.02)
                    if new > e[1]:
                        print(f"end   {ts(e[1])} -> {ts(new)}  {plain(e[3][9])[:40]}")
                        e[1] = new

    if a.cc:
        # sound labels, with consecutive cues of the same label merged (CC splits cues at overlap boundaries)
        snd = []
        for s, x, txt in cues(a.cc):
            parts = [p.strip() for p in plain(txt.replace('\\N', '\n')).split('\n')]
            for n, part in enumerate(parts):
                # a line that is only （…） is a sound label, unless plain dialogue follows (then it's a speaker name)
                if re.fullmatch(r'-?\s*（[^）]*）', part) and (n + 1 == len(parts) or parts[n+1].lstrip('-').startswith('（')):
                    if snd and snd[-1][2] == part.strip() and s - snd[-1][1] <= SNAP:
                        snd[-1][1] = max(snd[-1][1], x)
                    else:
                        snd.append([s, x, part.strip()])
        used = set()
        for e in ev:
            if not e[2]: continue
            # sound must overlap the sign as listed and start no later than it; one sound per sign
            m = [k for k, (s, x, _) in enumerate(snd) if k not in used and s <= e[0] + SNAP and x > e[0] and s >= e[0] - CAP]
            if m:
                k = m[0]; used.add(k)
                if snd[k][0] < e[0]:
                    print(f"cc    {ts(e[0])} -> {ts(snd[k][0])}  {plain(e[3][9])[:24]} = {snd[k][2]}")
                    e[0] = snd[k][0]

    if a.overrides:
        ovr = {}
        for l in open(a.overrides):
            tok = l.split('#')[0].split()
            if len(tok) >= 2:
                ovr[round(t(tok[0]), 2)] = t(tok[1])
        for e in ev:
            new = ovr.get(round(t(e[3][1]), 2)) if e[2] else None  # keyed on the sign's original start
            if new is not None:
                print(f"sign  {e[3][1]} -> {ts(new)}  {plain(e[3][9])[:40]}")
                e[0] = new

    cuts = [float(x) for x in open(a.cuts) if x.strip()] if a.cuts else []
    for e in ev:
        if e[2]:  # long enough to read (from its possibly earlier start), never shorter than listed
            listed_end = t(e[3][2])
            e[1] = max(e[1], e[0] + reading(e[3][9]))
            c = [x for x in cuts if max(e[0], listed_end - ADJ) < x < e[1]]  # shot changed in the added stretch
            if c:
                e[1] = max(listed_end, min(c))

    signs = sorted((e for e in ev if e[2]), key=lambda e: e[0])
    for x, y in zip(signs, signs[1:]):  # the same sign again moments later (a heartbeat): one sign, no blink
        if plain(x[3][9]).strip() == plain(y[3][9]).strip() and 0 < y[0] - x[1] < READ_MIN:
            x[1] = y[0]
    for x, y in zip(signs, signs[1:]):
        if y[0] > x[0]: x[1] = min(x[1], y[0])  # don't stack two signs
    for s in signs:
        # dialogue lifted to the top (\an8, so it doesn't cover drawn text at the bottom) gets the top line; the sign
        # sits one dialogue-height lower for its whole run, so neither moves while on screen
        top = [e for e in ev if not e[2] and '\\an8' in e[3][9] and e[0] < s[1] and s[0] < e[1]]
        if top and dlg_size:
            n = max(e[3][9].count('\\N') + 1 for e in top)
            s[3][7] = str(dlg_mv + round(n * dlg_size * 1.15))  # ponytail: assumes lines don't auto-wrap
    for e in ev:
        e[3][1], e[3][2] = ts(e[0]), ts(e[1])

    if added and not any(e[2] for e in ev):
        head = [l for l in head if not l.startswith('Style: Sign,')]  # nothing to fix: leave the script as it was
    # events keep their input order: it decides which line a renderer stacks on top when two overlap
    res = []
    for l in (l for l in head if l.strip()):  # rebuild with blank lines before sections
        if l.startswith('[') and res: res.append('')
        res.append(l)
    res += [','.join(e[3]) for e in ev]
    open(a.dst, 'w', encoding='utf-8-sig').write('\n'.join(res) + '\n')
    print(sum(e[2] for e in ev), 'signs of', len(ev))

if __name__ == '__main__':
    main()
