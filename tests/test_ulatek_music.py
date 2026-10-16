from boss_plugins.venomous_abyss import ulatek


def test_music_uses_egg_summon_and_starts_p3_five_seconds_before_boss_return():
    fight={'startTime':1000,'endTime':601000}
    events=[{'kind':'rage','timeMs':100000,'endTimeMs':120000},
            {'kind':'rage','timeMs':240000,'endTimeMs':260000},
            {'kind':'shatter','timeMs':310000},{'kind':'egg-summon','timeMs':280000}]
    positions=[{'timestamp':308000,'x':0,'y':0},{'timestamp':324000,'x':0,'y':0}]
    profile=ulatek._replay_music_profile(fight,events,positions)
    assert profile['phases']==[
        {'key':'p1','startTimeMs':0,'endTimeMs':120000},
        {'key':'p2','startTimeMs':120000,'endTimeMs':280000},
        {'key':'p25','startTimeMs':280000,'endTimeMs':314000},
        {'key':'p3','startTimeMs':318000,'endTimeMs':600000}]
    assert profile['p3LeadMs']==5000
    assert [profile['tracks'][key]['sourceStartSeconds'] for key in ['p1','p2','p25','p3']]==[0,509,1471,1087]


def test_music_does_not_invent_p3_without_a_boss_return_position():
    profile=ulatek._replay_music_profile({'startTime':0,'endTime':600000},[
        {'kind':'rage','timeMs':100000,'endTimeMs':120000},
        {'kind':'rage','timeMs':240000,'endTimeMs':260000},
        {'kind':'shatter','timeMs':310000},{'kind':'egg-summon','timeMs':280000}],[])
    assert [p['key'] for p in profile['phases']]==['p1','p2','p25']
    assert profile['phases'][-1]['endTimeMs']==314000


def test_truncated_rage_does_not_start_an_unobserved_phase():
    profile=ulatek._replay_music_profile({'startTime':0,'endTime':100000},[
        {'kind':'rage','timeMs':85000,'endTimeMs':100000}],[])
    assert profile['phases']==[{'key':'p1','startTimeMs':0,'endTimeMs':100000}]


def test_early_p3_cue_ends_the_previous_track_without_overlapping_windows():
    profile=ulatek._replay_music_profile({'startTime':0,'endTime':600000},[
        {'kind':'rage','timeMs':100000,'endTimeMs':120000},
        {'kind':'rage','timeMs':240000,'endTimeMs':260000},
        {'kind':'egg-summon','timeMs':280000},{'kind':'shatter','timeMs':290000}],
        [{'timestamp':310000}])
    assert profile['phases'][-2:]==[
        {'key':'p25','startTimeMs':280000,'endTimeMs':305000},
        {'key':'p3','startTimeMs':305000,'endTimeMs':600000}]


def test_p25_waits_for_completed_call_that_started_after_second_fury():
    profile=ulatek._replay_music_profile({'startTime':0,'endTime':600000},[
        {'kind':'rage','timeMs':100000,'endTimeMs':120000},
        {'kind':'rage','timeMs':240000,'endTimeMs':260000},
        {'kind':'egg-summon','timeMs':261000,'castStartTimeMs':259000,'endTimeMs':261000},
        {'kind':'egg-summon','timeMs':270000,'castStartTimeMs':270000,'endTimeMs':274000,'outcome':'interrupted'},
        {'kind':'egg-summon','timeMs':280000,'castStartTimeMs':280000,'endTimeMs':284000,'outcome':'completed'}],[])
    assert profile['phases'][1]['endTimeMs']==284000
    assert profile['phases'][2]['startTimeMs']==284000
    assert profile['p25Evidence']=='completed-serpent-call-after-second-bound-fury'


def test_music_cuts_only_confirmed_internal_silence_with_short_joins():
    from scripts.build_ulatek_music import track_filter
    for key,number in [('p1',3),('p3',2)]:
        track=ulatek.ULATEK_MUSIC_TRACKS[key]
        graph=track_filter(track)
        assert track['durationMs'] < track['sourceDurationMs']
        assert len(track['silenceCutsSeconds'])==number
        assert graph.count('acrossfade=d=0.12')==number
        assert '[s0]atrim=start=0:' in graph
        assert graph.endswith('[music]')
        expected=round(track['sourceDurationMs']-sum((b-a)*1000 for a,b in track['silenceCutsSeconds'])-number*120)
        assert track['durationMs']==expected
    assert track_filter(ulatek.ULATEK_MUSIC_TRACKS['p25']) is None
