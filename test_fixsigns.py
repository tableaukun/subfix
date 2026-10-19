# Runs fixsigns.py on tiny made-up scripts, one case per rule, and checks fixep.py's decisions on fake track
# listings. usage: python3 test_fixsigns.py
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
        for flag, body in (('--ref', jpn), ('--overrides', overrides), ('--cc', cc), ('--cuts', cuts)):
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
    sys.path.insert(0, HERE)
    from fixsigns import issign
    assert not issign('[DOOR CLOSES]') and not issign('(SIGHS)') and issign('BA-BUMP (HEART)')  # SDH labels

def test_signs_last_their_reading_time():
    _, ev = fix(ass(('0:00:10.00', '0:00:11.00', 'EEK'),
                    ('0:00:11.08', '0:00:20.00', 'a long line of dialogue right after it'),
                    ('0:00:30.00', '0:00:31.00', 'MOMOKA KURIKI\\NVOICE CALL - VIDEO CALL - CHAT'),
                    ('0:00:40.00', '0:00:44.00', 'EPISODE 17\\NTRUE FEELINGS')))
    assert ev['EEK'][:2] == ('0:00:10.00', '0:00:11.50')  # 1.5 s minimum, not stretched over the dialogue
    assert ev['MOMOKA KURIKI\\NVOICE CALL - VIDEO CALL - CHAT'][1] == '0:00:32.59'  # 44 characters at 17 cps
    assert ev['EPISODE 17\\NTRUE FEELINGS'][:2] == ('0:00:40.00', '0:00:44.00')  # never shorter than listed

def test_lengthened_sign_ends_at_a_shot_change_in_the_added_stretch():
    # EEK at 5:41: listed 1.0 s ending 0.09 s before a cut; 1.5 s would show it 0.4 s into the next shot
    _, ev = fix(ass(('0:00:10.00', '0:00:11.00', 'EEK'), ('0:00:20.00', '0:00:21.00', 'FLIP'),
                    ('0:00:30.00', '0:00:31.00', 'HUH?')),
                cuts='10.50\n11.09\n21.30\n')
    assert ev['EEK'][:2] == ('0:00:10.00', '0:00:11.09')  # cut in the added stretch (one inside the listed span ignored)
    assert ev['FLIP'][:2] == ('0:00:20.00', '0:00:21.30')
    assert ev['HUH?'][:2] == ('0:00:30.00', '0:00:31.50')  # no cut: full reading time

def test_repeated_sign_does_not_blink():
    # BA-BUMP 18:20 then 18:22.60: 0.76 s gap between two reading-time signs
    out = fix(ass(('0:00:50.00', '0:00:51.00', 'BA-BUMP'), ('0:00:52.26', '0:00:53.26', '{\\an8}BA-BUMP'),
                  ('0:00:58.00', '0:00:59.00', 'BA-BUMP')), raw=True)
    lines = [l.split(',', 9) for l in out if l.startswith('Dialogue:')]
    assert [(l[1], l[2]) for l in lines] == [('0:00:50.00', '0:00:52.26'), ('0:00:52.26', '0:00:53.76'),
                                             ('0:00:58.00', '0:00:59.50')]  # far apart: left alone

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
                overrides='# comment\n0:00:43.08 0:00:41.20\n')
    assert ev['HIDE MY FEELINGS'][0] == '0:00:41.20'
    assert ev['HIDE - TELL'][1] == '0:00:41.20'  # its reading time ran to 41.50; no two signs stacked at the top

def test_truncated_dialogue_paired_by_overlap_not_start():
    # English starts 0.6s before the Japanese line (the 14:23 case)
    _, ev = fix(ass(('0:00:50.00', '0:00:52.00', 'well what the hey'),
                    ('0:00:52.08', '0:00:53.50', '*GENUINELY THINKING')),
                ass(('0:00:50.60', '0:00:53.20', 'ja')))
    assert ev['well what the hey'][1] == '0:00:53.20'

def test_sign_sits_below_top_dialogue():
    # 18:27: top (\\an8) dialogue kept, so it avoids drawn text; the sign makes room under it instead of moving
    lines = fix(ass(('0:01:00.00', '0:01:06.00', 'BA-BUMP'),
                    ('0:01:00.50', '0:01:02.00', 'bottom line'),
                    ('0:01:03.00', '0:01:05.00', '{\\an8}so long as\\Nwe stay friends'),
                    ('0:01:10.00', '0:01:11.00', 'OTHER SIGN')), raw=True)
    ev = {l.split(',', 9)[9]: l.split(',') for l in lines if l.startswith('Dialogue:')}
    assert ev['BA-BUMP'][7] == str(15 + round(2 * 40 * 1.15))  # two dialogue lines of size 40
    assert ev['OTHER SIGN'][7] == '0'
    assert '{\\an8}so long as\\Nwe stay friends' in ev  # dialogue keeps its lift

def test_cc_sound_label_times_sign_but_speaker_name_does_not():
    cc = ass(('0:01:10.00', '0:01:12.60', '（心臓の鼓動）\\N（湊）あれ？'),
             ('0:01:20.00', '0:01:22.00', '（大地）\\Nこっち'))
    _, ev = fix(ass(('0:01:09.00', '0:01:11.42', 'held it back'),
                    ('0:01:11.50', '0:01:12.00', 'BA-BUMP'),
                    ('0:01:12.08', '0:01:15.00', 'dialogue'),
                    ('0:01:20.50', '0:01:21.00', 'OVER HERE'),
                    ('0:01:21.08', '0:01:22.00', 'more dialogue')), cc=cc)
    assert ev['BA-BUMP'][:2] == ('0:01:10.00', '0:01:12.00')  # starts with the sound, listed end kept
    assert ev['OVER HERE'][:2] == ('0:01:20.50', '0:01:22.00')  # speaker label ignored: listed start, 1.5 s

def test_cc_sound_moves_a_sign_only_past_dialogue_that_held_it_back():
    # Ao no Hako S2 03 9:06: the phone alarm rings over the bedroom; the sign is the phone screen, shown at 9:10
    cc = ass(('0:09:06.46', '0:09:12.46', '（携帯電話のアラーム）'))
    _, ev = fix(ass(('0:09:00.00', '0:09:03.00', 'earlier talk'), ('0:09:10.46', '0:09:12.26', '5:30 ALARM\\NSTOP - SNOOZE')), cc=cc)
    assert ev['5:30 ALARM\\NSTOP - SNOOZE'][0] == '0:09:10.46'

def test_cc_sound_used_for_one_sign_only():
    cc = ass(('0:01:30.00', '0:01:35.00', '（うなり声）'))
    _, ev = fix(ass(('0:01:30.00', '0:01:31.00', 'URGH'), ('0:01:31.00', '0:01:33.95', 'talk'), ('0:01:34.00', '0:01:34.50', 'RUMBLE')), cc=cc)
    assert ev['URGH'][:2] == ('0:01:30.00', '0:01:31.50')
    assert ev['RUMBLE'][0] == '0:01:34.00'  # the growl already went to URGH

def test_rerun_is_idempotent_and_overrides_tolerate_comments():
    once = fix(ass(('0:00:01.00', '0:00:02.00', 'SIGN')), overrides='0:00:01.00 0:00:00.50  # visible earlier\n', raw=True)
    twice = fix('\n'.join(once) + '\n', raw=True)
    assert sum(l.startswith('Style: Sign,') for l in twice) == 1
    assert [l for l in once if l.startswith('Dialogue')] == [l for l in twice if l.startswith('Dialogue')]
    assert once[-1].split(',')[1] == '0:00:00.50'

def test_sign_stays_top_when_bottom_dialogue_also_overlaps():
    # BA-BUMP 18:22: overlapped top dialogue once and bottom dialogue three times; moving it made it jump
    _, ev = fix(ass(('0:02:00.00', '0:02:06.00', 'BA-BUMP'),
                    ('0:02:00.50', '0:02:02.00', 'bottom line'),
                    ('0:02:03.00', '0:02:05.00', '{\\an8}top line')))
    assert 'BA-BUMP' in ev

def test_script_without_signs_comes_back_unchanged():
    # typeset (Crunchyroll-style) subs: no caps signs, overlaps allowed, event order deliberate
    src = ass(('0:00:05.00', '0:00:07.00', "Who are you?"),
              ('0:00:04.00', '0:00:05.00', "Let's go."),
              ('0:00:04.50', '0:00:09.00', '{\\an8\\pos(320,20)}Tennyo Island'))
    lines = fix(src, raw=True)
    assert [l for l in lines if l.strip()] == [l for l in src.splitlines() if l.strip()]

def test_ts_rounds_to_whole_centiseconds():
    sys.path.insert(0, HERE)
    from fixsigns import ts
    assert ts(119.996) == '0:02:00.00' and ts(3599.999) == '1:00:00.00' and ts(61.234) == '0:01:01.23'

# fixep.py decisions, on track listings shaped like mkvmerge -J output (fixep.py is covered here too)
def trk(i, kind, lang, name='', **flags):
    codec = {'codec_id': 'S_TEXT/ASS'} if kind == 'subtitles' else {}
    return {'id': i, 'type': kind, 'properties': {'language': lang, 'track_name': name, **codec, **flags}}

NETFLIX = [trk(0, 'video', 'jpn'), trk(1, 'audio', 'jpn'), trk(2, 'audio', 'jpn'),
           trk(3, 'subtitles', 'eng', 'NF_English'), trk(4, 'subtitles', 'eng', 'NF_English(SDH)'),
           trk(5, 'subtitles', 'por', 'NF_Portuguese'), trk(6, 'subtitles', 'jpn', 'NF_Japanese'),
           trk(7, 'subtitles', 'jpn', 'NF_Japanese(CC)')]

def fixep():
    sys.path.insert(0, HERE)
    import fixep
    return fixep

def test_pick_skips_sdh_forced_and_our_own_track():
    f = fixep()
    subs = [x for x in NETFLIX if x['type'] == 'subtitles']
    assert f.pick(subs, 'eng', False)['id'] == 3 and f.pick(subs, 'jpn', False)['id'] == 6
    assert f.pick(subs, 'jpn', True)['id'] == 7
    ours = [trk(8, 'subtitles', 'eng', 'NF_English (signs fixed v2)'), trk(9, 'subtitles', 'eng', 'NF_English (signs fixed)')] + subs
    assert f.pick(ours, 'eng', False)['id'] == 3  # --force rebuilds from the original, not from our output
    assert f.pick([trk(1, 'subtitles', 'eng', 'Signs & Songs'), trk(2, 'subtitles', 'eng', 'Accessible')],
                  'eng', False)['id'] == 2  # whole words: "Accessible" isn't CC
    assert f.pick([trk(1, 'subtitles', 'eng', codec_id='S_HDMV/PGS'), trk(2, 'subtitles', 'eng', codec_id='S_TEXT/UTF8')],
                  'eng', False) is None  # bitmap and SRT subs can't be fixed

def test_fixed_track_versions():
    f = fixep()
    assert f.fixed_version('NF_English (signs fixed v2)') == 2 and f.fixed_version('NF_English (signs fixed v13)') == 13
    assert f.fixed_version('NF_English (signs fixed)') == 1  # tracks from before versioning
    assert f.fixed_version('NF_English') is None and f.fixed_version('Signs fixed by fansubber') is None

def test_original_language_is_the_non_english_audio():
    f = fixep()
    assert f.original_language(NETFLIX) == 'jpn'
    western = [trk(0, 'video', 'und'), trk(1, 'audio', 'eng'), trk(2, 'subtitles', 'eng', 'English SDH'),
               trk(3, 'subtitles', 'fre', 'French')]
    crunchyroll = [trk(0, 'video', 'und'), trk(1, 'audio', 'jpn'), trk(2, 'subtitles', 'eng', 'English subs')]
    with_jpn_subs = western + [trk(4, 'subtitles', 'jpn', 'Japanese')]  # English audio: no sign translations
    assert f.original_language(western) is None and f.original_language(with_jpn_subs) is None
    assert f.original_language(crunchyroll) == 'jpn'  # no reference subs: its English subs' shape decides
    dual = [trk(0, 'video', 'und'), trk(1, 'audio', 'spa'), trk(2, 'audio', 'jpn')] + NETFLIX[3:]
    assert f.original_language(dual) == 'jpn'  # one with reference subs beats one without
    kdrama = [trk(0, 'video', 'und'), trk(1, 'audio', 'kor'), trk(2, 'subtitles', 'eng', 'English'),
              trk(3, 'subtitles', 'kor', 'Korean'), trk(4, 'subtitles', 'spa', 'Spanish')]
    assert f.original_language(kdrama) == 'kor'
    dub_first = [trk(0, 'video', 'und'), trk(1, 'audio', 'eng'), trk(2, 'audio', 'jpn')] + NETFLIX[3:]
    assert f.original_language(dub_first) == 'jpn'
    keep, _, _, _ = f.plan_remux(kdrama, strip=True, lang='kor')
    assert keep == [2, 3]  # --strip keeps English and the original language

def test_remux_plan_keeps_all_subs_unless_strip_and_replaces_an_earlier_fixed_track():
    f = fixep()
    keep, order, english, want = f.plan_remux(NETFLIX)
    assert keep == [3, 4, 5, 6, 7] and order == ['1:0', '1:1', '1:2', '0:0', '1:3', '1:4', '1:5', '1:6', '1:7'] and want == 9
    assert english == [3, 4]  # both lose the default flag, so the fixed track is the only default English
    keep, order, english, want = f.plan_remux(NETFLIX, strip=True)  # opt-in: Portuguese dropped
    assert keep == [3, 4, 6, 7] and order == ['1:0', '1:1', '1:2', '0:0', '1:3', '1:4', '1:6', '1:7'] and want == 8
    again = NETFLIX[:3] + [trk(9, 'subtitles', 'eng', 'NF_English (signs fixed v1)')] + NETFLIX[3:]
    keep, order, english, want = f.plan_remux(again)
    assert 9 not in keep and order.count('0:0') == 1 and want == 9
    forced_first = NETFLIX[:3] + [trk(8, 'subtitles', 'eng', 'NF_English (Forced)', forced_track=True)] + NETFLIX[3:]
    _, order, _, _ = f.plan_remux(forced_first)
    assert order.index('0:0') == order.index('1:8') - 1  # before the forced track too, so it's the first English

def test_commentary_audio_is_never_the_original_language():
    f = fixep()
    comm = [trk(0, 'video', 'und'), trk(1, 'audio', 'spa', 'Commentary'), trk(2, 'audio', 'jpn'),
            trk(3, 'subtitles', 'eng', 'English'), trk(4, 'subtitles', 'jpn', 'Japanese'), trk(5, 'subtitles', 'spa', 'Spanish')]
    assert f.original_language(comm) == 'jpn'
    dflt = [trk(0, 'video', 'und'), trk(1, 'audio', 'spa'), trk(2, 'audio', 'jpn', default_track=True)] + comm[3:]
    assert f.original_language(dflt) == 'jpn'  # the default audio wins over an earlier one

def test_stretches_only_where_a_sign_is_lengthened():
    with tempfile.TemporaryDirectory() as d:
        src, wins = os.path.join(d, 'eng'), os.path.join(d, 'wins')
        open(src, 'w').write(ass(('0:00:10.00', '0:00:11.00', 'EEK'), ('0:00:20.00', '0:00:24.00', 'EPISODE 17'),
                                 ('0:00:30.00', '0:00:31.00', 'line'), ('0:00:40.00', '0:00:41.41', 'HUH?')))  # HUH?: +0.09 s
        subprocess.run([sys.executable, '-I', os.path.join(HERE, 'fixsigns.py'), src, os.path.join(d, 'out'),
                        '--stretches', wins], check=True, capture_output=True)
        assert open(wins).read() == '9.850 11.550\n'

def test_sign_stays_until_the_dialogue_beside_it_ends():
    _, ev = fix(ass(('0:00:10.00', '0:00:11.00', 'FLIP'), ('0:00:11.00', '0:00:12.80', 'beside it'),
                    ('0:00:20.00', '0:00:21.00', 'RUMBLE'), ('0:00:21.00', '0:00:25.00', 'a long line beside it')))
    assert ev['FLIP'][1] == '0:00:12.80'  # within twice its reading time
    assert ev['RUMBLE'][1] == '0:00:21.50'  # 4 s more is too long: just its reading time

def test_only_serialized_subs_count():
    sys.path.insert(0, HERE)
    from fixsigns import serialized
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'x')
        two = (('0:00:01.00', '0:00:02.00', 'TRAINING ROOM'), ('0:00:02.00', '0:00:04.00', 'talk'),
               ('0:00:05.00', '0:00:06.00', 'EPISODE 27\\NADMIRATION'))
        for body, want in ((ass(*two), True),
                           (ass(*two, ('0:00:05.50', '0:00:07.00', 'talk over a sign')), False),
                           (ass(('0:00:01.00', '0:00:02.00', '{\\pos(640,80)}SIGN'), *two[1:]), False),
                           (ass(('0:00:01.00', '0:00:02.00', '{\\move(0,0,9,9)}SIGN'), *two[1:]), False),
                           (ass(('0:00:01.00', '0:00:02.00', 'only dialogue')), False),
                           (ass(('0:00:01.00', '0:00:02.00', 'OK.'), ('0:00:03.00', '0:00:04.00', 'MINATO!'),
                                ('0:00:05.00', '0:00:06.00', 'OH MY GOD!'), ('0:00:07.00', '0:00:08.00', 'TV'),
                                ('0:00:09.00', '0:00:10.00', 'plain talk')), False)):  # shouts aren't signs
            open(p, 'w').write(body)
            assert serialized(p) is want, body

def test_lock_is_exclusive_and_taken_over_from_a_dead_run():
    f = fixep()
    with tempfile.TemporaryDirectory() as d:
        held = f.lock(d)
        assert held and f.lock(d) is None  # our own pid is alive
        os.remove(held)
        open(os.path.join(d, 'lock'), 'w').write('999999')  # no such process
        held = f.lock(d)
        assert held
        os.utime(held, (0, 0))  # our pid looks alive, but the lock is ancient: a reused pid, take it over
        assert f.lock(d)

if __name__ == '__main__':
    tests = [f for n, f in sorted(globals().items()) if n.startswith('test_')]
    for f in tests:
        f()
        print('ok', f.__name__)
    print(len(tests), 'passed')
