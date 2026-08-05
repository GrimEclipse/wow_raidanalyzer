"""Season 1 Mythic+ evidence configuration.

Names and spell IDs are maintenance data. Generated samples remain immutable
until an operator explicitly runs the online exporter again.
"""

from __future__ import annotations


SKYREACH_ACTORS_ZH = {
    "Dread Raven": "恐惧渡鸦",
    "Raging Squall": "狂怒的飑风",
    "Soaring Chakram Master": "飞天轮舞大师",
    "Driving Gale-Caller": "强势唤风者",
    "Adorned Bladetalon": "华胄锐爪战士",
    "Lowborn Servant": "下层仆从",
    "Outcast Warrior": "流亡战士",
    "Solar Elemental": "太阳元素",
    "Solar Construct": "烈日构造体",
    "Blinding Sun Priestess": "耀目太阳祭司",
    "Adept of the Dawn": "黎明精锐",
    "Solar Orb": "太阳宝珠",
    "Initiate of the Rising Sun": "旭日新兵",
    "Suntalon": "日爪",
    "Suntalon Tamer": "日爪驯服者",
    "Sunwing": "日翼幼雏",
    "Solar Zealot": "拜日狂信徒",
    "Ranjit": "兰吉特",
    "Araknath": "阿尔卡纳斯",
    "Rukhran": "鲁克兰",
    "High Sage Viryx": "高阶贤者维里克斯",
}


DUNGEON_CONFIGS = {
    "algethar_academy": {
        "name": "学院",
        "officialNameZh": "艾杰斯亚学院",
        "aliases": ["Algeth'ar Academy"],
        "enemyAbilities": {
            1270356: "奥术碎击", 377344: "啄击", 1276632: "狂怒尖啸",
            1282244: "邪恶撕咬", 1270098: "缚咒武器",
            396716: "皲皮", 388923: "爆发苏醒", 388544: "裂树击", 388623: "分枝",
            376997: "狂野啄击", 377004: "震耳尖啸", 1285508: "炽热之火",
            387691: "奥术宝珠", 386173: "法力炸弹", 385958: "奥术驱除", 388537: "奥术裂隙",
            1276752: "毁灭之风",
            1282251: "星界冲击", 374343: "能量炸弹", 388822: "力量真空",
        },
        "linkedTargetCasts": {
            386173: {"displayEventType": "begincast", "targetEventType": "cast", "targetAuraId": 386181, "toleranceMs": 600},
            374343: {"displayEventType": "begincast", "targetEventType": "cast", "targetAuraId": 374350, "toleranceMs": 600},
        },
    },
    "maisara_caverns": {
        "name": "洞窟",
        "officialNameZh": "迈萨拉洞窟",
        "aliases": ["Maisara Caverns"],
        "enemyAbilities": {
            1256561: "碎裂护甲", 1257088: "死疽波动", 1257895: "先祖碾碎",
            1259631: "震荡打击", 1256059: "撕裂角刺", 1256047: "震耳咆哮",
            1257920: "恐惧打击", 1260648: "弹幕射击", 1266480: "长矛侧攻",
            1246666: "感染羽翼", 1243900: "恶臭羽毛风暴", 1249478: "腐肉飞扑",
            1266488: "迸裂创伤", 1251813: "萦绕恐惧", 1263735: "死疽融合",
            1251554: "吸取灵魂", 1251204: "束缚幻影", 1252777: "灵魂束缚",
            1252676: "粉碎灵魂", 1251023: "碎魂者",
            1251024: "二连击", 1253765: "最后一击", 1253788: "裂魂咆哮",
        },
        "linkedTargetCasts": {
            1260648: {
                "displayEventType": "cast", "targetAuraId": 1260643,
                "toleranceMs": 25, "requireLinkedTarget": True,
            },
            1266480: {
                "displayEventType": "begincast", "targetEventType": "cast",
                "includeAnchorTarget": True, "requireAnchor": True,
            },
            1251204: {"displayEventType": "cast"},
            1252676: {
                "displayEventType": "begincast", "targetAuraId": 1252675,
                "toleranceMs": 3100, "requireLinkedTarget": True,
            },
            1251023: {"displayEventType": "cast"},
            # WCL's Soulbind cast already contains its concrete player target.
            1252777: {"displayEventType": "cast"},
        },
        "syntheticEnemyCasts": [
            {
                "trigger": "aura", "triggerAbilityId": 1249478,
                "eventDataType": "Debuffs", "hostilityType": "Friendlies",
                "triggerEventType": "applydebuff", "abilityId": 1249478,
                "name": "腐肉飞扑", "evidence": "腐肉飞扑点名光环",
            },
            {
                "trigger": "aura", "triggerAbilityId": 1251598,
                "eventDataType": "Buffs", "hostilityType": "Enemies",
                "triggerEventType": "applybuff", "endEventType": "removebuff",
                "abilityId": 1263735, "name": "死疽融合",
                "evidence": "死亡之幕获得→消失",
            },
        ],
    },
    "pit_of_saron": {
        "name": "矿坑",
        "officialNameZh": "萨隆矿坑",
        "aliases": ["Pit of Saron"],
        "enemyAbilities": {
            1258435: "破甲打击", 1258439: "冰霜猛袭", 1258437: "蚀骨寒气",
            1258997: "猛拽擒握", 1258820: "苦难洪流", 1261546: "碎矿猛击",
            1261847: "寒晶践踏", 1262029: "冰川过载", 1264336: "瘟疫喷射",
            1264287: "凋零猛击", 1264453: "笨重凝视", 1262745: "白霜冲击",
            1262582: "天灾领主的印记", 1263756: "死亡之握", 1263406: "亡者大军",
            1276648: "骸骨灌注",
        },
        "linkedTargetCasts": {
            1262745: {"displayEventType": "begincast", "targetEventType": "begincast", "targetAuraId": 1262772, "toleranceMs": 25},
        },
    },
    "nexus_point_xenas": {
        "name": "节点",
        "officialNameZh": "节点希纳斯",
        "aliases": ["Nexus-Point Xenas"],
        "enemyAbilities": {
            1257701: "灼热撕裂", 1281657: "酷热惩击", 1269283: "压制力场",
            1252436: "虚空鞭笞", 1252962: "熵能吸取", 1252406: "恐惧咆哮",
            1252429: "虚无壁垒冲击", 1249806: "弧光法力", 1251767: "回流充能",
            1264048: "能量坍缩", 1257509: "核闪引爆", 1247937: "幽影鞭笞",
            1282723: "暮色骇魔", 1264429: "光痕耀斑", 1282665: "虚空鞭笞",
            1249014: "蚀光步伐", 1257595: "神圣诡计", 1269222: "闪烁",
            1253950: "灼热撕裂", 1253855: "辉熠消散",
        },
        "linkedTargetCasts": {
            1251767: {"displayEventType": "cast"},
            1264429: {"displayEventType": "cast"},
            1249014: {"displayEventType": "cast", "targetEventType": "cast", "targetAuraId": 1249020, "effectAuraId": 1252875, "toleranceMs": 600},
            1253855: {"displayEventType": "begincast", "targetEventType": "cast", "targetAuraId": 1255503, "toleranceMs": 1100},
        },
    },
    "seat_of_the_triumvirate": {
        "name": "执政团",
        "officialNameZh": "执政团之座",
        "aliases": ["The Seat of the Triumvirate", "Seat of the Triumvirate"],
        "enemyAbilities": {
            1262517: "冷酷追杀", 1262509: "制伏锁链", 1262506: "抽取虚空",
            1262508: "虚空灌输", 1280326: "虚空重殴", 1264512: "裂隙撕裂",
            1264257: "幽影波", 1262429: "喷发", 1262519: "背刺",
            1263440: "虚空挥砍", 1263484: "虚空挥砍·一", 1263492: "虚空挥砍·二",
            1263494: "虚空挥砍·三", 1263282: "残杀", 1263399: "软泥猛击",
            1263297: "崩解虚空", 248831: "恐惧尖啸", 245742: "暗影突袭",
            1263523: "过载", 1280065: "相位冲锋", 1263542: "群体虚空灌输",
            1263538: "暗影触须", 1263528: "驱逐", 1263532: "虚空风暴",
            1268733: "精神鞭笞", 1265419: "绝望音符", 1265421: "绝望哀歌",
            1265463: "不谐射线", 1265689: "幽冥和音", 1266003: "永夜交响曲",
            1263529: "崩塌虚空", 1266001: "反冲",
        },
        "linkedTargetCasts": {
            245742: {"displayEventType": "cast"},
            1266001: {"displayEventType": "cast"},
            1263542: {"displayEventType": "begincast", "targetEventType": "cast", "targetAuraId": 1263542, "toleranceMs": 25},
            1265463: {"displayEventType": "begincast", "targetEventType": "begincast", "targetAuraId": 1265426, "effectAuraId": 1265464, "toleranceMs": 25},
        },
    },
    "skyreach": {
        "name": "通天峰",
        "officialNameZh": "通天峰",
        "aliases": ["Skyreach"],
        "actorTranslations": SKYREACH_ACTORS_ZH,
        "enemyAbilities": {
            1254460: "刀锋冲刺", 1258174: "恐惧之风", 1254380: "剪切",
            1254566: "可怖尖啸", 1254666: "弹射风轮", 1254672: "灼热利爪",
            153757: "散刃", 1258152: "风轮", 1252690: "疾风奔涌",
            156793: "战轮旋风", 154135: "超级新星", 154110: "灼热重击",
            1258205: "日光灌注", 1253519: "燃烧之爪", 1253511: "爆燃追击",
            1253510: "曙光", 159382: "灼热飞羽", 1253538: "灼烧射线",
            154396: "日光冲击", 153954: "扔下", 1253840: "眩光",
        },
        "linkedTargetCasts": {
            1253538: {"displayEventType": "cast", "targetEventType": "cast", "targetAuraId": 1253541, "toleranceMs": 50},
        },
    },
    "windrunner_spire": {
        "name": "风行",
        "officialNameZh": "风行者之塔",
        "aliases": ["Windrunner Spire"],
        "bossActorOriginalNames": ["Kalis", "Latch"],
        "enemyAbilities": {
            1216462: "精确切割", 1216825: "毒性喷射", 1216253: "奥术齐射",
            471643: "干扰尖啸", 1216985: "刺穿撕咬", 1217021: "凶猛扑击",
            1270618: "烈焰新星", 466556: "炽焰腾流", 466064: "炽热尖喙",
            467040: "燃烧烈风", 472888: "碎骨猛砍", 472795: "猛力拖拽",
            474105: "黑暗诅咒", 472745: "飞溅喷吐",
            1219491: "衰弱尖啸", 472053: "无情跳跃", 467620: "暴怒",
            472043: "集结怒吼", 1270620: "烈焰新星", 1253026: "破胆怒吼",
            1253272: "破胆怒吼", 472662: "暴风斩", 468429: "疾风狙击",
            474528: "飞矢烈风", 1253986: "劲风射击",
        },
        "linkedTargetCasts": {
            467040: {"displayEventType": "cast"},
            474528: {
                "displayEventType": "begincast", "targetAuraId": 1282911,
                "toleranceMs": 25, "requireLinkedTarget": True,
            },
            466556: {"displayEventType": "begincast", "targetEventType": "cast", "targetAuraId": 466559, "toleranceMs": 500},
            1253986: {"displayEventType": "cast", "targetEventType": "cast", "targetAuraId": 1253979, "effectAuraId": 1253978, "toleranceMs": 900},
        },
        "syntheticEnemyCasts": [
            {
                "trigger": "hostileCast", "triggerAbilityId": 472795,
                "triggerEventType": "begincast", "abilityId": 1219491,
                "name": "衰弱尖啸", "sourceOriginalName": "Kalis",
                "evidence": "伴随猛力拖拽开始读条",
            },
        ],
    },
    "magisters_terrace": {
        "name": "魔导师平台",
        "officialNameZh": "魔导师平台",
        "aliases": ["Magister's Terrace", "Magisters' Terrace"],
        "enemyAbilities": {
            145629: "反魔法领域（环境）", 1254338: "燃烧", 1254336: "燃烧",
            1244907: "符文战刃", 473258: "人群驱散", 474496: "震退猛击",
            1264687: "吞噬打击", 1248138: "虚空炸弹", 1265977: "吞噬暗影",
            1214081: "奥术驱除", 474345: "补给协议", 1225792: "符文印记",
            1225193: "静默浪潮", 1224299: "星界束缚", 1223847: "三重复制",
            1284954: "寰宇刺击", 1280113: "庞大碎片", 1215087: "不稳定的虚空精华",
        },
        "linkedTargetCasts": {
            1248138: {"displayEventType": "cast"},
            1244907: {
                "displayEventType": "begincast", "targetEventType": "cast",
                "targetAuraId": 1244907, "toleranceMs": 1200,
                "requireAnchor": True, "includeAnchorTarget": True,
            },
            1225792: {
                "displayEventType": "begincast", "targetEventType": "cast",
                "targetAuraId": 1225792, "toleranceMs": 1100,
                "requireAnchor": True, "includeAnchorTarget": True,
            },
        },
        "bossCastRoundRules": [
            {
                "pullOriginalName": "Gemellus",
                "sourceOriginalName": "Gemellus",
                "abilityIds": [1284954, 1224299],
                "windowMs": 250,
                "replicationAbilityId": 1223847,
                "initialCopies": 2,
                "additionalCopies": 2,
            },
        ],
    },
}


def dungeon_config(key: str) -> dict:
    try:
        return {"key": key, **DUNGEON_CONFIGS[key]}
    except KeyError as error:
        raise ValueError(f"unknown dungeon config: {key}") from error
