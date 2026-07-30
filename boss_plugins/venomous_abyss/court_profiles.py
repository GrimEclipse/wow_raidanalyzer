"""Initial court-rule surface for the first three Venomous Abyss bosses.

These profiles describe what may be counted after evidence extraction.  They
do not fetch WCL data and do not infer assignments from the raid centroid.
"""

from analyzer_core.court_rules import validate_court_profile


COURT_PROFILES = {
    "nakzali": {
        "bossKey": "nakzali",
        "phaseModel": "event_driven",
        "rules": [
            {
                "key": "amani_reached_well",
                "label": "无眠的阿曼尼漏进灵魂之井",
                "mode": "direct",
                "spellIDs": [1287533, 1297624],
                "requiredEvidence": ["add identity", "well entry", "adjacent Ritual Burn"],
                "countOption": "amaniLeakCountEnabled",
                "defaultCountEnabled": True,
                "severityUnits": 1,
            },
            {
                "key": "possession_barrage_intercept",
                "label": "附身弹幕路径拦截",
                "mode": "assignment",
                "spellIDs": [1284103, 1292034],
                "assignmentKey": "possessionBarrageTankLane",
                "requiredEvidence": ["cast target", "boss facing", "hit players", "position samples"],
                "countOption": "possessionBarrageCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
            {
                "key": "essence_rend_placement",
                "label": "精华撕裂解除位置",
                "mode": "assignment",
                "spellIDs": [1287426, 1287434, 1287198],
                "assignmentKey": "essenceRendAllowedRegions",
                "requiredEvidence": ["remove timestamp", "nearest position sample", "sample offset"],
                "countOption": "essenceRendPlacementCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
        ],
    },
    "sentinels": {
        "bossKey": "sentinels",
        "phaseModel": "energy_cycle",
        "rules": [
            {
                "key": "toxic_droplet_missed",
                "label": "剧毒水滴漏踩",
                "mode": "direct",
                "spellIDs": [1284434, 1284451, 1284452],
                "requiredEvidence": ["droplet cast", "raid explosion 1284452"],
                "countOption": "toxicDropletCountEnabled",
                "defaultCountEnabled": True,
                "severityUnits": 1,
            },
            {
                "key": "helical_toxin_timeout",
                "label": "合星座（螺旋剧毒）未在 28 秒内完成",
                "mode": "direct",
                "spellIDs": [1284590, 1284941, 1311488],
                "requiredEvidence": ["stasis round", "Cultivated Burst"],
                "countOption": "helicalToxinCountEnabled",
                "defaultCountEnabled": True,
                "severityUnits": 1,
            },
            {
                "key": "protovenom_eruption",
                "label": "变换原毒错误碰撞",
                "mode": "direct",
                "spellIDs": [1296878, 1296882, 1296962],
                "requiredEvidence": ["round cast", "eruption center", "victim set"],
                "countOption": "protovenomCountEnabled",
                "defaultCountEnabled": True,
                "severityUnits": 1,
            },
            {
                "key": "red_water_placement",
                "label": "红水放置位置",
                "mode": "review",
                "spellIDs": [1284210, 1284471, 1284491, 1288260, 1288297],
                "requiredEvidence": [
                    "water source",
                    "source debuff remove timestamp",
                    "nearest position",
                    "water radius by source",
                ],
                "calibration": "不同来源红水半径尚未确认",
                "countOption": "redWaterPlacementCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
        ],
    },
    "vashnik": {
        "bossKey": "vashnik",
        "phaseModel": "fixed_timeline",
        "phaseRule": "只按起战后的固定事件轴和 Imbibe/Infusion Aura 切段；不得用血量提前结束阶段。",
        "rules": [
            {
                "key": "plague_wave_assignment",
                "label": "瘟疫泡沫波浪未命中指定目标",
                "mode": "assignment",
                "spellIDs": [1281908, 1281910, 1282078, 1295796, 1295798],
                "assignmentKey": "plagueWaveTargets",
                "requiredEvidence": [
                    "Plague Froth remove timestamp",
                    "player position near remove",
                    "wave direction/facing",
                    "assigned target position",
                    "Plague Wave hit set",
                ],
                "countOption": "plagueWaveAssignmentCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
            {
                "key": "hardened_tumor_burst",
                "label": "硬化肿瘤未正确解除",
                "mode": "review",
                "spellIDs": [1304437, 1304459, 1295798],
                "requiredEvidence": ["tumor spawn", "Hardened Tumor aura", "wave intersection", "Tumor Burst"],
                "countOption": "hardenedTumorCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
            {
                "key": "avoidable_plague_wave_hit",
                "label": "误吃瘟疫波浪",
                "mode": "review",
                "spellIDs": [1295798],
                "requiredEvidence": ["wave source", "wave direction", "damage target"],
                "countOption": "avoidablePlagueWaveCountEnabled",
                "defaultCountEnabled": False,
                "severityUnits": 1,
            },
        ],
    },
}

for _profile in COURT_PROFILES.values():
    validate_court_profile(_profile)
