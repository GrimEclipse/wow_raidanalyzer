from boss_plugins.venomous_abyss.coiledaltar import _mechanic_overview as coiledaltar_overview
from boss_plugins.venomous_abyss.nakzali import _mechanic_overview as nakzali_overview
from boss_plugins.venomous_abyss.sentinels import _mechanic_overview as sentinels_overview
from boss_plugins.venomous_abyss.sszorak import _mechanic_overview as sszorak_overview
from boss_plugins.venomous_abyss.twinfangs import _mechanic_overview as twinfangs_overview
from boss_plugins.venomous_abyss.vashnik import _mechanic_overview as vashnik_overview


def pull(**mechanics):
    return {
        "reportID": "REPORT", "fightID": 7, "date": "2026-08-31",
        "startClock": "20:00:00", **mechanics,
    }


def metrics(overview):
    return {row["key"]: row for row in overview["metrics"]}


def test_nakzali_nightly_overview_counts_each_bad_barrage_round_once():
    overview = nakzali_overview([pull(nakzali={
        "possessionBarrage": {"rounds": [{
            "index": 1, "time": "00:20.0", "target": "点名者",
            "waves": [
                {"verdict": "疑似被提前拦截，飞行距离不足"},
                {"verdict": "疑似被提前拦截，飞行距离不足", "interceptorCandidate": {
                    "player": "术士", "classColor": "#8788ee", "distanceToLaneYards": 1.2,
                }},
            ],
        }]},
        "essenceRend": {"placements": [{
            "time": "00:30.0", "player": "法师", "classColor": "#3fc7eb",
            "distanceFromCenterYards": 19.9, "placementEstimate": "太靠近中场", "counted": False,
        }]},
        "avoidableBoard": {"1308227": [{
            "player": "战士", "classColor": "#c69b6d",
            "events": [{"time": "01:00.0"}],
        }]},
    }, difficulty=5)])

    rows = metrics(overview)
    assert rows["barrageIntercepts"]["value"] == 1
    assert rows["barrageIntercepts"]["players"] == [
        {"player": "术士", "count": 1, "classColor": "#8788ee"},
    ]
    assert rows["closeEssenceRends"]["value"] == 1
    assert rows["closeEssenceRends"]["players"] == [
        {"player": "法师", "count": 1, "classColor": "#3fc7eb"},
    ]
    assert rows["missingInnerRealm"]["value"] == 1


def test_sentinels_nightly_overview_combines_requested_three_metrics():
    overview = sentinels_overview([pull(sentinels={
        "marks": {"deathOverThirty": [{
            "time": "00:10.0", "player": "德鲁伊", "classColor": "#ff7c0a",
            "bloodStack": 16, "acidStack": 15, "totalStack": 31,
        }]},
        "livingVenom": {"players": [{
            "player": "德鲁伊", "classColor": "#ff7c0a", "deathCount": 1,
            "events": [{"time": "00:12.0"}, {"time": "00:13.0"}],
        }]},
        "helicalToxins": {"rounds": [{"collisions": [
            {"time": "00:20.0", "firstWrongCollision": True,
             "players": [{"player": "甲"}, {"player": "乙"}]},
            {"time": "00:21.0", "firstWrongCollision": True,
             "players": [{"player": "丙"}, {"player": "丁"}]},
        ]}]},
    })])

    rows = metrics(overview)
    assert rows["deathOverThirty"]["value"] == 1
    assert rows["greenSpearHits"]["value"] == "2 / 1"
    assert rows["firstWrongCollisions"]["value"] == 1


def test_vashnik_nightly_overview_separates_wave_and_floor_hits():
    overview = vashnik_overview([pull(vashnik={
        "avoidable": {"players": [
            {"spellID": 1295798, "spellName": "瘟疫泡沫波浪", "player": "甲",
             "classColor": "#fff", "events": [{"time": "00:05.0"}]},
            {"spellID": 1286737, "spellName": "地板黑圈", "player": "乙",
             "classColor": "#000", "events": [{"time": "00:06.0"}]},
        ]},
    })])

    rows = metrics(overview)
    assert rows["plagueWaveHits"]["value"] == 1
    assert rows["floorCircleHits"]["value"] == 1


def test_sszorak_and_twinfangs_nightly_overviews_use_actual_events():
    sszorak = sszorak_overview([pull(sszorak={
        "cysts": {"rounds": [{"placements": [{
            "time": "00:08.0", "player": "甲", "classColor": "#fff",
            "placementOk": False, "expected": "对面位置",
        }]}]},
        "apexPredator": {"tempestDamage": [{
            "player": "乙", "classColor": "#000", "events": [{"time": "00:09.0"}],
        }]},
    })])
    twin = twinfangs_overview([pull(twinfangs={
        "waveHits": {"players": [{
            "player": "丙", "classColor": "#123456",
            "events": [{"time": "00:11.0"}, {"time": "00:12.0"}],
        }]},
    })])

    sszorak_rows = metrics(sszorak)
    assert sszorak_rows["badCystPlacements"]["value"] == 1
    assert sszorak_rows["stormHits"]["value"] == 1
    assert metrics(twin)["waveHits"]["value"] == 2


def test_coiledaltar_nightly_overview_counts_requested_four_metrics():
    overview = coiledaltar_overview([pull(coiledaltar={
        "gloombomb": {"rounds": [{
            "time": "03:40.0",
            "targets": [{
                "player": "术士", "classColor": "#8788ee",
                "collateralGravebound": [
                    {"player": "牧师", "receivedGravebound": True},
                    {"player": "猎人", "receivedGravebound": True},
                ],
            }],
            "collateralHits": [
                {"player": "牧师", "classColor": "#fff", "fromPlayer": "术士"},
                {"player": "猎人", "classColor": "#abd473", "fromPlayer": "术士"},
            ],
        }]},
        "soulSever": {"rounds": [{
            "time": "04:10.0",
            "unclearedManifestations": [
                {"player": "法师", "classColor": "#3fc7eb", "inCone": False},
                {"player": "战士", "classColor": "#c69b6d", "inCone": True},
            ],
        }]},
        "blightedSever": {"rounds": [{
            "time": "08:20.0",
            "unclearedManifestations": [
                {"player": "德鲁伊", "classColor": "#ff7c0a", "inCone": False},
            ],
        }]},
        "dreadmarch": {
            "applications": [
                {"player": "甲", "classColor": "#fff", "phase": "p2", "appliedTime": "03:00.0", "hitManifestation": False, "triggerKind": "boss-cast"},
                {"player": "乙", "classColor": "#3fc7eb", "phase": "p2", "appliedTime": "03:12.0", "hitManifestation": True, "triggerKind": "manifest-collision"},
                {"player": "丙", "classColor": "#fff", "phase": "intermission", "appliedTime": "06:00.0", "hitManifestation": False, "triggerKind": "boss-cast"},
            ],
            "rounds": [
                {
                    "index": 1, "time": "03:00.0", "phase": "p2",
                    "targets": [
                        {"player": "甲", "hitManifestation": False},
                        {"player": "乙", "hitManifestation": True},
                    ],
                },
            ],
        },
        "graveboundFailures": {"failures": [
            {"time": "03:41.0", "player": "牧师", "classColor": "#fff", "deathAbilityID": 1308330, "deathAbility": "墓缚"},
            {"time": "04:02.0", "player": "猎人", "classColor": "#abd473", "deathAbilityID": 1297906, "deathAbility": "墓缚"},
            {"time": "04:10.0", "player": "战士", "classColor": "#c69b6d", "deathAbilityID": 1, "deathAbility": "自动攻击", "killedByGraveboundDamage": False},
        ]},
    })])

    rows = metrics(overview)
    assert rows["gloombombCollateralHits"]["value"] == 2
    assert rows["gloombombCollateralHits"]["players"] == [
        {"player": "术士", "count": 2, "classColor": "#8788ee"},
    ]
    assert rows["unclearedSouls"]["value"] == 2
    assert {row["player"] for row in rows["unclearedSouls"]["players"]} == {"法师", "德鲁伊"}
    assert rows["regularDreadmarch"]["value"] == 1
    assert rows["regularDreadmarch"]["players"] == [
        {"player": "乙", "count": 1, "classColor": "#3fc7eb"},
    ]
    assert rows["graveboundDeaths"]["value"] == 1
    assert rows["graveboundDeaths"]["players"] == [
        {"player": "猎人", "count": 1, "classColor": "#abd473"},
    ]
