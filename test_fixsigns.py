# Runs fixsigns.py on tiny made-up scripts, one case per rule. usage: python3 test_fixsigns.py
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HEAD = """[Script Info]
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,15,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def ass(*events):
    return HEAD + ''.join(f"Dialogue: 0,{s},{e},Main,,0,0,0,,{txt}\n" for s, e, txt in events)

def fix(eng, jpn=None, overrides=None, cc=None, cuts=None, raw=False):
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, 'eng'), os.path.join(d, 'out')
        open(src, 'w', encoding='utf-8').write(eng)
        args = [src, out]
        for flag, body in (('--jpn', jpn), ('--overrides', overrides), ('--cc', cc), ('--cuts', cuts)):
            if body is not None:
                path = os.path.join(d, flag[2:])
                open(path, 'w', encoding='utf-8').write(body)
                args += [flag, path]
        subprocess.run([sys.executable, '-I', os.path.join(HERE, 'fixsigns.py'), *args], check=True, capture_output=True)
        lines = open(out, encoding='utf-8-sig').read().splitlines()
    if raw:
        return lines
    styles = [l for l in lines if l.startswith('Style:')]
    ev = {l.split(',', 9)[9]: tuple(l.split(',')[1:4]) for l in lines if l.startswith('Dialogue:')}
    return styles, ev  # ev: text -> (start, end, style)

def test_sign_style_and_detection():
    styles, ev = fix(ass(('0:00:01.00', '0:00:02.00', 'BA-BUMP'),
                         ('0:00:03.00', '0:00:04.00', 'I…'),
                         ('0:00:05.00', '0:00:06.00', '{\\an8}GRADE 2'),
                         ('0:00:07.00', '0:00:08.00', 'ドキッ')))
    assert styles[1] == 'Style: Sign,Arial,34,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,10,10,15,1'
    assert ev['BA-BUMP'][2] == 'Sign' and ev['GRADE 2'][2] == 'Sign'  # \an dropped, Sign style is top already
    assert ev['I…'][2] == 'Main'  # one letter is not a sign
    assert ev['ドキッ'][2] == 'Main'  # kana has no case

def test_sign_extends_over_following_dialogue_until_next_sign():
    _, ev = fix(ass(('0:00:01.00', '0:00:02.00', 'SIGN ONE'),
                    ('0:00:02.08', '0:00:03.00', 'line a'),
                    ('0:00:03.08', '0:00:04.00', 'line b'),
                    ('0:00:04.08', '0:00:05.00', 'SIGN TWO'),
                    ('0:00:05.08', '0:00:20.00', 'long line')))
    assert ev['SIGN ONE'][:2] == ('0:00:01.00', '0:00:04.00')
    assert ev['SIGN TWO'][1] == '0:00:05.00'  # 5s cap: long line not absorbed

def test_delayed_dialogue_snaps_to_japanese_start():
    _, ev = fix(ass(('0:00:10.00', '0:00:11.00', 'IRRITATED'),
                    ('0:00:11.08', '0:00:13.00', 'how irritating')),
                ass(('0:00:10.00', '0:00:13.00', 'イライラ')))
    assert ev['how irritating'][0] == '0:00:10.00'

def test_aligned_dialogue_not_moved():
    _, ev = fix(ass(('0:00:10.00', '0:00:11.00', 'HUH?'),
                    ('0:00:11.08', '0:00:13.00', 'but why')),
                ass(('0:00:09.00', '0:00:10.50', 'ja one'), ('0:00:11.08', '0:00:13.00', 'ja two')))
    assert ev['but why'][0] == '0:00:11.08'

def test_truncated_dialogue_follows_merged_japanese_lines():
    # English merges two JP lines; the second one runs past the sign start (the 7:00 bug)
    _, ev = fix(ass(('0:00:20.00', '0:00:22.70', 'agonize over the options'),
                    ('0:00:22.78', '0:00:25.00', 'DATE - DON\'T DATE')),
                ass(('0:00:20.00', '0:00:22.10', 'ja a'), ('0:00:22.20', '0:00:25.00', 'ja b')))
    assert ev['agonize over the options'][1] == '0:00:25.00'

def test_extension_stops_before_next_dialogue():
    _, ev = fix(ass(('0:00:30.00', '0:00:31.00', 'oh am I'),
                    ('0:00:31.08', '0:00:31.60', 'SFX'),
                    ('0:00:31.68', '0:00:33.00', 'next line')),
                ass(('0:00:30.00', '0:00:32.50', 'ja')))
    assert ev['oh am I'][1] == '0:00:31.66'

def test_override_moves_sign_and_caps_previous_sign():
    _, ev = fix(ass(('0:00:40.00', '0:00:41.00', 'HIDE - TELL'),
                    ('0:00:41.08', '0:00:43.00', 'dialogue'),
                    ('0:00:43.08', '0:00:44.00', 'HIDE MY FEELINGS')),
                overrides='# comment\n0:00:43.08 0:00:42.00\n')
    assert ev['HIDE MY FEELINGS'][0] == '0:00:42.00'
    assert ev['HIDE - TELL'][1] == '0:00:42.00'  # no two signs stacked at the top

def test_truncated_dialogue_paired_by_overlap_not_start():
    # English starts 0.6s before the Japanese line (the 14:23 case)
    _, ev = fix(ass(('0:00:50.00', '0:00:52.00', 'well what the hey'),
                    ('0:00:52.08', '0:00:53.50', '*GENUINELY THINKING')),
                ass(('0:00:50.60', '0:00:53.20', 'ja')))
    assert ev['well what the hey'][1] == '0:00:53.20'

def test_sign_goes_bottom_when_dialogue_is_on_top():
    _, ev = fix(ass(('0:01:00.00', '0:01:01.00', 'IRRITATED'),
                    ('0:01:00.00', '0:01:02.00', '{\\an8}so irritating'),
                    ('0:01:05.00', '0:01:06.00', 'OTHER SIGN')))
    assert '{\\an2}IRRITATED' in ev and 'OTHER SIGN' in ev

def test_cc_sound_label_times_sign_but_speaker_name_does_not():
    cc = ass(('0:01:10.00', '0:01:12.60', '（心臓の鼓動）\\N（湊）あれ？'),
             ('0:01:20.00', '0:01:22.00', '（大地）\\Nこっち'))
    _, ev = fix(ass(('0:01:11.50', '0:01:12.00', 'BA-BUMP'),
                    ('0:01:12.08', '0:01:15.00', 'dialogue'),
                    ('0:01:20.50', '0:01:21.00', 'OVER HERE'),
                    ('0:01:21.08', '0:01:22.00', 'more dialogue')), cc=cc)
    assert ev['BA-BUMP'][:2] == ('0:01:10.00', '0:01:12.60')  # sound's span, not the 5s dialogue extension
    assert ev['OVER HERE'][:2] == ('0:01:20.50', '0:01:22.00')  # speaker label ignored, normal extension

def test_cc_sound_used_for_one_sign_only():
    cc = ass(('0:01:30.00', '0:01:35.00', '（うなり声）'))
    _, ev = fix(ass(('0:01:30.00', '0:01:31.00', 'URGH'), ('0:01:34.00', '0:01:34.50', 'RUMBLE')), cc=cc)
    assert ev['URGH'][:2] == ('0:01:30.00', '0:01:34.00')  # sound span, capped at next sign
    assert ev['RUMBLE'][0] == '0:01:34.00'

def test_rerun_is_idempotent_and_overrides_tolerate_comments():
    once = fix(ass(('0:00:01.00', '0:00:02.00', 'SIGN')), overrides='0:00:01.00 0:00:00.50  # visible earlier\n', raw=True)
    twice = fix('\n'.join(once) + '\n', raw=True)
    assert sum(l.startswith('Style: Sign,') for l in twice) == 1
    assert [l for l in once if l.startswith('Dialogue')] == [l for l in twice if l.startswith('Dialogue')]
    assert once[-1].split(',')[1] == '0:00:00.50'

def test_sign_never_runs_past_shot_change_after_listed_end():
    # WHOA?!/SURGE at 18:31: listed end 0.09s before a shot change, then dialogue would extend it 1.7s
    _, ev = fix(ass(('0:00:10.00', '0:00:11.40', 'WHOA?!'),
                    ('0:00:11.50', '0:00:13.20', 'Amamiya!'),
                    ('0:00:20.00', '0:00:21.00', 'HELD BACK'),
                    ('0:00:21.08', '0:00:23.00', 'line')),
                cuts='11.49\n17.00\n22.00\n', overrides='0:00:20.00 0:00:17.50\n')
    assert ev['WHOA?!'][:2] == ('0:00:10.00', '0:00:11.49')
    assert ev['HELD BACK'][:2] == ('0:00:17.50', '0:00:22.00')  # cut before its listed start doesn't count

if __name__ == '__main__':
    tests = [f for n, f in sorted(globals().items()) if n.startswith('test_')]
    for f in tests:
        f()
        print('ok', f.__name__)
    print(len(tests), 'passed')
