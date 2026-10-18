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

def fix(eng, jpn=None, overrides=None):
    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for name, body in (('eng', eng), ('jpn', jpn), ('ovr', overrides)):
            if body is not None:
                paths[name] = os.path.join(d, name)
                open(paths[name], 'w', encoding='utf-8').write(body)
        out = os.path.join(d, 'out')
        args = [paths['eng'], out, paths.get('jpn', '-')] + ([paths['ovr']] if 'ovr' in paths else [])
        subprocess.run([sys.executable, '-I', os.path.join(HERE, 'fixsigns.py'), *args], check=True, capture_output=True)
        lines = open(out, encoding='utf-8-sig').read().splitlines()
    styles = [l for l in lines if l.startswith('Style:')]
    ev = {l.split(',', 9)[9]: tuple(l.split(',')[1:4]) for l in lines if l.startswith('Dialogue:')}
    return styles, ev  # ev: text -> (start, end, style)

def test_sign_style_and_detection():
    styles, ev = fix(ass(('0:00:01.00', '0:00:02.00', 'BA-BUMP'),
                         ('0:00:03.00', '0:00:04.00', 'I…'),
                         ('0:00:05.00', '0:00:06.00', '{\\an8}GRADE 2')))
    assert styles[1] == 'Style: Sign,Arial,34,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,10,10,15,1'
    assert ev['BA-BUMP'][2] == 'Sign' and ev['GRADE 2'][2] == 'Sign'  # \an dropped, Sign style is top already
    assert ev['I…'][2] == 'Main'  # one letter is not a sign

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
    assert ev['agonize over the options'][1] == '0:00:24.70'  # +2s cap

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

if __name__ == '__main__':
    tests = [f for n, f in sorted(globals().items()) if n.startswith('test_')]
    for f in tests:
        f()
        print('ok', f.__name__)
    print(len(tests), 'passed')
