# Held-back sign starts from the video, no vision model: a sign Netflix held back behind dialogue moves to the start
# of its shot, when that shot began while the dialogue was on and nothing of note appeared mid-shot. Measured on 34
# hand-checked rows (Koori no Jouheki S2 03, Ao no Hako S2 01): 5 of 16 held-back starts found, 0 wrong moves, all 18
# correct starts kept. Text that fades in, is revealed by motion, or zooms in mid-shot isn't found (contact sheets).
import os, sys, subprocess
from concurrent.futures import ProcessPoolExecutor
from fixsigns import t, plain, issign

W, H, FPS, LEAD, POST, TAU = 240, 136, 24000 / 1001, 1.5, 0.1, 20  # small grey frames at a fixed rate
THETA, RISE, SPAN, MINMOVE, DMAX, DMIN, RISE_D, LATE, DROP = 0.7, 0.35, 8, 8, 0.08, 0.002, 0.35, 10, 0.3
# thresholds held their 5/0 result across wide sweeps, but were tuned on the same 34 rows: expect about a third

def sim(f, r, idx=None):  # fraction of pixels within TAU grey levels of the reference frame
    if idx is None:
        return sum(1 for x, y in zip(f, r) if -TAU <= x - y <= TAU) / len(r)
    return sum(1 for i in idx if -TAU <= f[i] - r[i] <= TAU) / len(idx)

def onset(frames, kr):
    # frames up to and including kr, the one just after the listed start. Returns (frame index or None, reason)
    r = frames[kr]
    S = [sim(f, r) for f in frames[:kr + 1]]
    k = kr
    while k > 0 and S[k-1] >= THETA:  # the listed moment's shot runs back to k
        k -= 1
    if k == 0:
        return None, 'same shot for the whole window'
    if kr - k < MINMOVE:
        return None, 'shot starts at the listed start'
    if S[k] - min(S[max(0, k - SPAN):k]) < RISE:
        return None, 'no clean shot start'
    first = frames[k + 2:min(k + 6, kr)]
    D = [i for i in range(len(r)) if all(not -TAU <= f[i] - r[i] <= TAU for f in first)]  # still unlike the listed moment
    dfrac = len(D) / len(r)
    if dfrac > DMAX:
        return None, f'{dfrac:.0%} of the frame still changes after the shot start'
    if dfrac >= DMIN:
        SD = [sim(f, r, D) for f in frames[k:kr + 1]]
        half = next((j for j, s in enumerate(SD) if s >= 0.5), None)
        if half is not None and half > LATE and SD[half] - SD[max(0, half - 12)] >= RISE_D:
            return None, f'something appeared {half / FPS:.2f}s into the shot'  # a title fading in, typing
        mx = 0
        for s in SD:
            mx = max(mx, s)
            if s < mx - DROP:
                return None, 'keeps changing mid-shot'
    return k, 'shot start'

def windows(ev):
    # ev: (start, text, end) strings as in the ASS. Signs right after another line, from LEAD s before the first of
    # the back-to-back lines it may have waited through
    for i in range(1, len(ev)):
        s, txt, _ = ev[i]
        if not issign(txt) or t(s) - t(ev[i-1][2]) >= 0.15:
            continue
        k = i - 1
        while k > 0 and t(ev[k][0]) - t(ev[k-1][2]) < 0.15 and not issign(ev[k-1][1]):
            k -= 1
        yield max(0, t(ev[k][0]) - LEAD), s, plain(txt).strip()

def decode(mkv, a, b, hw):
    return subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', *(['-hwaccel', 'videotoolbox'] if hw else []),
                           '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', mkv, '-an', '-sn',
                           '-vf', f'fps={FPS},scale={W}:{H},format=gray', '-f', 'rawvideo', '-'],
                          capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout

def check(job):
    mkv, (a, s, txt) = job
    listed = t(s)
    try:
        raw = decode(mkv, a, listed + POST, sys.platform == 'darwin')  # hardware decode: ~1.5x on a Mac
    except subprocess.CalledProcessError:
        raw = decode(mkv, a, listed + POST, False)
    frames = [raw[i:i + W * H] for i in range(0, len(raw) - W * H + 1, W * H)]
    if not frames:
        return s, None, 'no frames', txt
    k, why = onset(frames, min(len(frames) - 1, round((listed + 0.05 - a) * FPS)))
    return s, (a + k / FPS if k is not None else None), why, txt

def scan(mkv, ev):
    # [(listed start, new start or None, reason, text)]. The pixel loops are pure Python: processes, not threads
    jobs = [(mkv, w) for w in windows(ev)]
    if not jobs:
        return []
    with ProcessPoolExecutor(max(1, min(len(jobs), (os.cpu_count() or 2) // 2))) as pool:
        return list(pool.map(check, jobs))
