"""Collect a difficulty-aware spell/evidence catalog for WCL zone 54.

This is a developer discovery tool, not a player-facing analysis entry point.
It uses Heroic kills/long pulls as the baseline, Mythic pulls as observed
differences, and a separately extracted Dungeon Journal as the expected
mechanic surface.  Every WCL spell keeps report/fight provenance.
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ZONE_ID = 54
DIFFICULTIES = {4: "heroic", 5: "mythic"}
ENCOUNTERS = {
    53470: {"key": "nakzali", "name": "Nek'zali the Soulcoiler"},
    53445: {"key": "sentinels", "name": "Entombed Sentinels"},
    53455: {"key": "vashnik", "name": "Vashnik the Malignant"},
    53497: {"key": "lostexplorers", "name": "The Lost Explorers"},
    53420: {"key": "sszorak", "name": "Sszorak"},
    53421: {"key": "twinfangs", "name": "The Twin Fangs"},
    53429: {"key": "bargained", "name": "The Coiled Altar"},
    53492: {
        "key": "ulatek",
        "name": "Ula'tek",
        "expectedUntested": True,
        "note": "团队副本尾王按惯例不开放公开测试，缺少 Mythic 日志属于预期状态。",
    },
}

MODE_DRAFTS = {
    "nakzali": {
        "confidence": "medium",
        "summary": "Boss 本体与多类灵魂/add 共同构成循环；Invoke/苏醒仪式召出或强化对象，灵魂转移与点燃构成处理链。",
        "phaseSignals": [1299673, 1295124, 1289683, 1289696, 1290003],
        "majorMechanics": [
            {"spellIDs": [1284103, 1292034], "note": "Possession Barrage 点名/射线伤害链"},
            {"spellIDs": [1287434], "note": "Essence Rend 约覆盖半团目标"},
            {"spellIDs": [1307939, 1293214, 1288772], "note": "多来源持续团队伤害/场地压力"},
        ],
    },
    "sentinels": {
        "confidence": "high",
        "summary": "Blood of Ula'tek 与 Breath of Ula'tek 双目标战；酸/血两类印记长期覆盖团队，约 103 秒一次 Vitriolic Stasis，Contaminate 约 52 秒循环。",
        "phaseSignals": [1284606, 1284588, 1290193, 1290189],
        "majorMechanics": [
            {"spellIDs": [1284500, 1284506], "note": "Mark of Acid/Blood 双阵营或双属性分配"},
            {"spellIDs": [1284257, 1284258], "note": "Contaminate 周期性团队伤害"},
            {"spellIDs": [1284487, 1284491, 1310126], "note": "Bloodvenom Injection 点名与后续伤害"},
        ],
    },
    "vashnik": {
        "confidence": "high",
        "summary": "Blood/Flame/Shadow 三种 Infusion 状态循环；Boss 通过 Imbibe 切换/吸收状态，Malignant Tumor 周期生成并以 Tumor Burst 结算。",
        "phaseSignals": [1298484, 1298489, 1298490, 1293968, 1293969, 1293971],
        "majorMechanics": [
            {"spellIDs": [1304437, 1304459], "note": "肿瘤生成、强化与爆炸链"},
            {"spellIDs": [1285979], "note": "Caustic Surge 高频团队压力"},
            {"spellIDs": [1294994, 1295173, 1295224], "note": "三类感染 Debuff/爆炸结果"},
        ],
    },
    "lostexplorers": {
        "confidence": "medium",
        "summary": "多首领/多物件战；Nama、Iku、Mor'zahi 与场地物件分别提供近战、卷轴、命令和环境技能，United Defense 暗示共享防御或联动阶段。",
        "phaseSignals": [1297646, 1292778, 1297075, 1297022, 1297024, 1296975],
        "majorMechanics": [
            {"spellIDs": [1297648, 1297649], "note": "冰/火 Patch 场地污染"},
            {"spellIDs": [1295858, 1310616], "note": "Shredding Shards 点名/分摊链"},
            {"spellIDs": [1292778, 1292780], "note": "最终扬升叠层与终局伤害"},
        ],
    },
    "sszorak": {
        "confidence": "medium",
        "summary": "以 Mutilate/Ravage 坦克连段为基础，穿插 Tempest 与多版本 Raging Crosswinds；后段出现 Venomous Surge 和 Unbound Ferocity 强化信号。",
        "phaseSignals": [1305959, 1286033, 1296898],
        "majorMechanics": [
            {"spellIDs": [1277027, 1277031, 1277002, 1277101], "note": "坦克 Mutilate/Ravage 连段"},
            {"spellIDs": [1285425, 1285453, 1297096, 1297111], "note": "Raging Crosswinds 风向/站位机制"},
            {"spellIDs": [1287205, 1297707, 1299899], "note": "Viscous Cyst 与 Virulence 点名/场地压力"},
        ],
    },
    "twinfangs": {
        "confidence": "high",
        "summary": "Ithraz/Vexhul 双首领并带 Barbed Bulwark/幼体对象；Protected Gestation 是显著护盾/孵化阶段，Stir the Depths 与 Ravenous Feast 是阶段切换信号。",
        "phaseSignals": [1303378, 1290956, 1290516, 1306872, 1294293],
        "majorMechanics": [
            {"spellIDs": [1290336, 1290480], "note": "Eternal Venom 高频全程压力"},
            {"spellIDs": [1289994, 1289237], "note": "Caustic Deluge 大范围伤害"},
            {"spellIDs": [1310102, 1310096, 1306925], "note": "Tainted Blood/Feasted/Congealed Gore 目标状态"},
        ],
    },
    "bargained": {
        "confidence": "medium",
        "summary": "Zul'jan 与 Hex Lord Malacrass 主导的多对象/祭坛战；Fangs of the Crucible 叠层推进，Manifestation of Dread 与灵魂系 add 构成恐惧阶段。",
        "phaseSignals": [1282520, 1282487, 1290316, 1309105, 1307959],
        "majorMechanics": [
            {"spellIDs": [1285017, 1283832], "note": "Axegrinder 目标追击/坦克压力"},
            {"spellIDs": [1283489, 1307425], "note": "Guillotine 点名处决链"},
            {"spellIDs": [1285911, 1286399], "note": "Unnerving Fixation/Wail of Terror 恐惧机制"},
        ],
    },
}

MODE_DRAFTS["sszorak"] = {
    "confidence": "high",
    "summary": (
        "纯单体固定大循环：两轮毒液激流生成四个囊肿，随后以 Dig In "
        "进入 25 秒呼啸漩涡；顶级掠食者内部五段剑技顺序随机。史诗额外加入 "
        "Serpent's Fury 集合清怒流程。"
    ),
    "phaseSignals": [1305959, 1286033, 1305621, 1296898],
    "majorMechanics": [
        {
            "spellIDs": [1277025, 1277002, 1277027, 1287072],
            "note": "顶级掠食者：两次劫掠、两次毁伤、一次风暴，顺序随机",
        },
        {
            "spellIDs": [1305959, 1287205, 1286033],
            "note": "两轮毒液激流生成四个囊肿，前三个服务三次吹风",
        },
        {
            "spellIDs": [1305621, 1297707, 1296898],
            "note": "史诗毒蛇之怒：14 人进入 8 码清怒，否则怒不可遏",
        },
    ],
}

MODE_DRAFTS["twinfangs"] = {
    "confidence": "high",
    "summary": (
        "固定时间轴的集中双目标战：维克苏尔负责叠加永久的永恒毒液，"
        "伊斯拉兹通过三次贪婪盛宴帮助玩家消层。每个场地位置处理两轮常态循环，"
        "随后用涌动射线转移；史诗额外加入液滴护盾、场边蛇群打断和污血。"
    ),
    "phaseSignals": [1289192, 1291404, 1290516, 1294293, 1308356],
    "majorMechanics": [
        {
            "spellIDs": [1290336, 1290480, 1290516],
            "note": "永恒毒液永久叠层，并由贪婪盛宴逐击消除",
        },
        {
            "spellIDs": [1289192, 1289201, 1291404, 1291478],
            "note": "腐蚀洪流/液滴与三只子嗣的腐蚀唾液",
        },
        {
            "spellIDs": [1303230, 1303378, 1308356, 1308385],
            "note": "史诗液滴护盾与幼体密集打断组",
        },
    ],
}

MODE_DRAFTS["bargained"] = {
    "confidence": "high",
    "summary": (
        "P1 祖尔加、P2 玛拉卡斯、35 秒被夺取的容器、P3 双目标的固定流程。"
        "前两阶段分别管理凝结毒液和恐惧具象，P3 用强化版清场/分摊组合并持续压缩场地。"
    ),
    "phaseSignals": [1282487, 1307184, 1304032, 1289798, 1298381],
    "majorMechanics": [
        {
            "spellIDs": [1299960, 1282403, 1299684, 1299838],
            "note": "凝结毒液搬运，并由坦克撕裂按计划清理",
        },
        {
            "spellIDs": [1285643, 1290316, 1286620, 1286918],
            "note": "死亡进军救人、具象摆位、灵魂撕裂与永恒夜幕",
        },
        {
            "spellIDs": [1304032, 1304033, 1287722, 1289798],
            "note": "35 秒再生转阶段与 P3 双首领灵魂绑定",
        },
    ],
}

BOSS_ZH = {
    "nakzali": "缠魂者内克扎莉",
    "sentinels": "陵寝哨兵",
    "vashnik": "万毒邪祟者瓦什尼克",
    "lostexplorers": "迷失的探险者",
    "sszorak": "斯索拉克",
    "twinfangs": "双子毒牙",
    "bargained": "盘卷祭坛",
    "ulatek": "乌拉特克",
}

# These are editorial translations for the discovery document, not stable rule
# keys. English spell names and numeric spell IDs remain authoritative.
SPELL_ZH = {
    1243002: "死亡进军",
    1277002: "撕裂",
    1277025: "顶级掠食者",
    1277027: "毁伤",
    1280189: "恶性反应",
    1280935: "瘟疫泡沫",
    1281907: "瘟疫泡沫",
    1282116: "适应性毒素",
    1282117: "适应性感染",
    1282287: "毒牙",
    1282403: "聚合毒液",
    1282419: "不稳定毒液",
    1282487: "熔炉之牙",
    1282525: "恶性催化",
    1282869: "腐蚀毒液",
    1283164: "汲取",
    1283290: "剧毒地面",
    1283489: "断头台",
    1283623: "寡妇之吻",
    1283631: "寡妇之触",
    1283832: "飞旋战斧",
    1284032: "缠魂之井",
    1284033: "缠魂仪式",
    1284034: "解缚之怒",
    1284103: "附身弹幕",
    1284109: "灵魂残缺",
    1284110: "斩魂",
    1284207: "活体毒液",
    1284208: "鲜血毒液",
    1284251: "毒液凝结",
    1284257: "污染",
    1284434: "剧毒液滴",
    1284452: "毒性爆炸",
    1284458: "强化猛击",
    1284471: "枯萎之血",
    1284487: "血毒注射",
    1284494: "酸液印记",
    1284503: "鲜血印记",
    1284588: "腐毒停滞",
    1284590: "螺旋毒素",
    1284670: "汲取",
    1285681: "缠魂点燃",
    1285732: "呼啸漩涡",
    1285844: "恐惧化身",
    1285911: "不安凝视",
    1285979: "腐蚀涌动",
    1286033: "稳固姿态",
    1286324: "暗影之牙",
    1286399: "恐惧哀嚎",
    1286573: "灵魂割裂",
    1286620: "灵魂割裂",
    1286834: "死灵蒸汽",
    1286837: "墓缚",
    1286860: "被缚者之怒",
    1286895: "幽暗炸弹",
    1286912: "暮光帷幕",
    1286918: "永恒夜幕",
    1286921: "冰缚烈焰",
    1286945: "失控之怒",
    1286997: "剧毒涌动",
    1287008: "粘稠囊肿",
    1287036: "剧毒撕咬",
    1287072: "风暴",
    1287198: "潜伏教徒",
    1287265: "碎裂盘卷",
    1287426: "精华撕裂",
    1287587: "连接斩断",
    1287718: "回收精华",
    1287722: "灵体抹除",
    1288232: "不稳定瘴气",
    1288297: "附着幽暗",
    1288624: "恐怖存在",
    1288879: "涌动之牙",
    1289192: "腐蚀洪流",
    1289683: "苏醒仪式",
    1289696: "苏醒纽带",
    1289855: "饥渴火葬",
    1289875: "火葬",
    1289919: "躁动的阿曼尼",
    1289962: "蜿蜒之握",
    1289993: "腐蚀液球",
    1290003: "解缚",
    1290189: "乌拉特克的统御",
    1290193: "乌拉特克的统御",
    1290336: "永恒毒液",
    1290361: "缠魂",
    1290516: "饥饿盛宴",
    1290779: "恶意",
    1290809: "盘绕毒素",
    1290956: "搅动深渊",
    1290990: "蠕动孵化",
    1291390: "灾变召唤",
    1291478: "腐蚀喷吐",
    1291930: "稳健打击",
    1292034: "附身弹幕",
    1292104: "蘑菇投掷",
    1292177: "真菌爆发",
    1292248: "灵魂转移",
    1292388: "邪眼",
    1292505: "毒性滑液",
    1292778: "最终扬升",
    1292779: "最终扬升",
    1292780: "最终扬升",
    1293212: "攫取深渊",
    1293497: "交织舞步",
    1293749: "涌动",
    1293792: "弹幕",
    1293968: "暗影灌注",
    1293969: "鲜血灌注",
    1293971: "火焰灌注",
    1294293: "涌动",
    1294729: "尸体枯萎",
    1294994: "汲取感染",
    1295049: "毒性烟雾",
    1295107: "浓缩唾液",
    1295173: "爆炸感染",
    1295209: "爆炸",
    1295224: "冥河感染",
    1295229: "汲取鲜血",
    1295360: "恶性外壳",
    1295449: "恶毒存在",
    1295451: "黑暗低语",
    1295798: "瘟疫波浪",
    1295854: "撕裂碎片",
    1295886: "霜火箭雨",
    1295905: "毒蛇之咬",
    1295952: "元素爆炸",
    1296061: "甲壳旋转",
    1296092: "强力重击",
    1296301: "腐毒横扫",
    1296602: "腐蚀残渣",
    1296667: "腐蚀残渣",
    1296878: "变换原毒",
    1296898: "怒不可遏",
    1296962: "原毒爆发",
    1297022: "束缚痛苦",
    1297024: "束缚痛苦",
    1297075: "强化",
    1297367: "毒蛇之怒",
    1297414: "大开杀戒",
    1297624: "仪式灼烧",
    1297644: "团结光环",
    1297645: "联合防御",
    1297646: "联合防御",
    1297648: "冰霜地带",
    1297649: "烈焰地带",
    1297707: "剧毒",
    1298367: "母神之怒",
    1298381: "熔炉亵渎",
    1298417: "石化毒液",
    1298484: "汲取",
    1298489: "汲取",
    1298490: "汲取",
    1298591: "亵渎之地",
    1298698: "残响代价",
    1299267: "恐怖断头台",
    1299396: "死亡之拥",
    1299401: "死亡低语",
    1299526: "暴露之心",
    1299650: "硬化",
    1299673: "召请",
    1299757: "毒性孵化",
    1299838: "毒液破裂",
    1299941: "汲取感染",
    1299949: "爆炸感染",
    1299950: "冥河感染",
    1299960: "剧毒洪流",
    1299988: "不朽盘卷",
    1300235: "灵魂衰竭",
    1300238: "缠魂者诅咒",
    1300265: "末日鳞片信息素",
    1300312: "末日鳞片外壳",
    1300322: "双牙毒素",
    1300743: "毒液气泡",
    1300751: "毒蛇召唤",
    1301117: "攫取之牙",
    1301213: "暗影蜕皮",
    1301268: "腐臭薄膜",
    1301510: "毁灭重击",
    1301800: "酸液爆发",
    1302013: "鲜血喷发",
    1302489: "冥河爆发",
    1302505: "乌拉特克的纽带",
    1302982: "剧毒喷吐",
    1303230: "鲜血洪流",
    1303378: "受护孵化",
    1303414: "石化蜇刺",
    1304012: "毒蛇召唤",
    1304028: "死亡守卫",
    1304032: "灵魂绑定",
    1304033: "幽魂再生",
    1304437: "硬化肿瘤",
    1304459: "肿瘤爆裂",
    1305650: "痛苦尖啸",
    1305709: "绝望横扫",
    1305775: "恐惧咆哮",
    1305833: "凝结箭",
    1305844: "冲击波",
    1305902: "灼热存在",
    1305959: "毒液涌动",
    1305998: "腐蚀利爪",
    1306086: "不稳定净化",
    1306119: "钙化尸体",
    1306858: "守卫者庇护",
    1306872: "弹幕",
    1306922: "凝结血块",
    1307009: "绝望",
    1307184: "恐惧箭",
    1307279: "枯萎斩魂",
    1307425: "被斩首",
    1307612: "毒性外壳",
    1307635: "毒性飞溅",
    1308038: "群体孵化",
    1308323: "报复恶意",
    1308356: "唤醒蛇群",
    1308385: "内脏爆裂",
    1308583: "解缚之怒",
}

SPELL_ZH.update({
    1277002: "劫掠",
    1277025: "顶级掠食者",
    1277027: "毁伤",
    1277031: "毁伤",
    1277051: "残毁创伤",
    1285998: "残毁创伤",
    1285999: "毁伤",
    1277101: "劫掠",
    1277105: "劫掠",
    1282869: "侵蚀毒液",
    1282873: "侵蚀毒液",
    1285419: "狂怒侧风",
    1285425: "狂怒侧风",
    1285453: "狂怒侧风",
    1285616: "狂怒侧风",
    1297096: "狂怒侧风",
    1297111: "狂怒侧风",
    1312219: "狂怒侧风",
    1285444: "狂怒侧风",
    1285447: "湍流侧风",
    1285961: "乌拉特克之仪",
    1285965: "乌拉特克之仪",
    1287177: "剧毒涌动",
    1285732: "呼啸漩涡",
    1286033: "掘地固守",
    1286997: "剧毒涌动",
    1305959: "剧毒涌动",
    1305963: "剧毒涌动",
    1306120: "剧毒涌动",
    1312156: "剧毒涌动",
    1287008: "粘稠囊肿",
    1287205: "粘稠囊肿",
    1287072: "风暴",
    1287083: "风暴",
    1297367: "毒蛇之怒",
    1305621: "毒蛇之怒",
    1297414: "大开杀戒",
    1296602: "腐蚀残渣",
    1296667: "腐蚀残渣",
    1297338: "致命剧毒",
    1305998: "腐蚀利爪",
    1296898: "怒不可遏",
    1297707: "剧毒",
    1299899: "剧毒",
    1300089: "剧毒",
    1312189: "剧毒",
    1288538: "碎石击",
    1289092: "碎石击",
    1289192: "腐蚀洪流",
    1289237: "腐蚀洪流",
    1289994: "腐蚀洪流",
    1289201: "腐蚀液滴",
    1289993: "腐蚀液滴",
    1290338: "腐蚀液滴",
    1290336: "永恒毒液",
    1290480: "永恒毒液",
    1290516: "贪婪盛宴",
    1290654: "贪婪盛宴",
    1290662: "贪婪盛宴",
    1310211: "贪婪盛宴",
    1290809: "缠绕脓液",
    1290814: "缠绕脓液",
    1290878: "缠绕脓液",
    1290956: "搅动深渊",
    1292806: "搅动深渊",
    1292807: "搅动深渊",
    1291478: "腐蚀唾液",
    1293295: "腐蚀唾液",
    1293979: "腐蚀唾液",
    1293749: "涌动",
    1294293: "涌动",
    1302013: "鲜血喷涌",
    1302048: "鲜血喷涌",
    1302695: "鲜血喷涌",
    1292552: "血液凝块",
    1306922: "血液凝块",
    1306925: "血液凝块",
    1303230: "鲜血洪流",
    1303235: "鲜血洪流",
    1303378: "受护孵化",
    1308356: "唤醒蛇群",
    1308385: "内脏爆裂",
})

SPELL_ZH.update({
    1243002: "死亡进军",
    1282287: "毒牙",
    1282403: "凝结毒液",
    1282408: "凝结毒液",
    1282419: "不稳定毒液",
    1282487: "熔炉之牙",
    1282512: "熔炉之牙",
    1282520: "熔炉之牙",
    1283485: "处斩",
    1283489: "处斩",
    1283594: "处斩",
    1283832: "碎斧",
    1285643: "死亡进军",
    1285844: "恐惧具象",
    1285911: "凝视",
    1286399: "恐惧哀嚎",
    1286441: "精魂狂啸",
    1286573: "灵魂撕裂",
    1286620: "灵魂撕裂",
    1286837: "墓缚",
    1286895: "幽魂炸弹",
    1286912: "永恒夜幕护盾",
    1286918: "永恒夜幕",
    1287718: "精魂回收",
    1287722: "灵魂抹除",
    1289798: "灵魂绑定",
    1289802: "灵魂绑定",
    1290316: "恐惧具象",
    1297445: "死亡进军",
    1298381: "熔炉亵渎",
    1298395: "熔炉亵渎",
    1298591: "亵渎之地",
    1298594: "熔炉亵渎",
    1299267: "残酷断头台",
    1299838: "毒液爆裂",
    1299960: "剧毒洪流",
    1301690: "撕裂",
    1304032: "灵魂绑定",
    1304033: "幽魂再生",
    1304498: "幽魂再生",
    1306906: "毒牙",
    1307130: "灵魂绑定",
    1307279: "枯萎之刃",
    1307425: "处斩",
    1307652: "残酷断头台",
    1307959: "灵魂撕裂",
    1308011: "恐惧哀嚎",
    1308330: "墓缚",
})

PHASE_DRAFTS = {
    "nakzali": [
        ("P1 缠魂者启蒙", "开场至 50% 生命", [1284033, 1285681, 1287426, 1284103], "用灵魂强化缠魂之井；处理精华撕裂、躁动的阿曼尼与坦克弹幕。"),
        ("转阶段：苏醒仪式", "50% 生命触发", [1289683, 1289696, 1292248, 1293212], "Boss 受苏醒纽带保护；击杀回响切断纽带。史诗还会把玩家拉入不朽盘卷。"),
        ("P2 解缚", "能量满后直至击杀", [1290003, 1299673, 1293497], "场地持续伤害并反复召请潜伏教徒；史诗召请会打断施法并沉默打断者。"),
    ],
    "sentinels": [
        ("双首领循环", "0–100 能量", [1284207, 1284208, 1284251, 1284487], "两只哨兵分别制造活体毒液和鲜血毒液；需要拉开超过 25 码并处理软泥、液滴、驱散与换坦。"),
        ("腐毒停滞", "100 能量", [1284588, 1284590, 1284941], "两只哨兵会合并平衡生命；玩家用碰撞把螺旋毒素精确叠到 4 层，否则持续时间结束时爆炸。"),
        ("史诗附加：变换原毒", "全程周期出现", [1296878, 1296962], "同类原毒相碰可中和；碰到未感染玩家会造成范围爆发与击退。"),
    ],
    "lostexplorers": [
        ("附身轮次", "全程轮换", [1295451, 1297022, 1297075], "莫扎希依次控制探险者；破除控制后用束缚痛苦重新附身并赋予目标更多技能。"),
        ("探险者技能组合", "随当前被控制目标变化", [1295886, 1295854, 1296061, 1292104], "冰火效果可互相抵消；包含远近衰减、分摊、场地与坦克易伤等不同解题方式。"),
        ("最终扬升", "Boss 达到满能量", [1292779], "未及时打断附身循环的惩罚/软狂暴信号。"),
    ],
    "vashnik": [
        ("三毒灌注循环", "Boss 从最近两座喷泉汲取", [1284670, 1293968, 1293969, 1293971], "血、暗影、火焰三类灌注组合改变小怪与玩家感染的结果。"),
        ("感染结算", "每轮灌注期间", [1282117, 1299941, 1299949, 1299950], "血感染吸收治疗并吸取队友；火感染需远离衰减；暗影感染在脚下制造爆发。"),
        ("史诗肿瘤", "全程附加", [1304437, 1304459, 1280935, 1295798], "硬化肿瘤不能直接正常处理，需要用玩家身上的瘟疫波浪命中去除硬化。"),
    ],
    "sszorak": [
        ("掠食者循环", "全程", [1277025, 1277027, 1277002, 1297367], "毁伤/撕裂形成坦克连段；蛇之怒要求团队正确承受/引导攻击，失败会进入屠戮惩罚。"),
        ("风暴升级", "随能量与场地风压推进", [1285419, 1285447, 1285732], "交叉风与阵风限制站位，最终进入呼啸漩涡。"),
        ("后段强化", "战斗后段", [1286997, 1296898, 1287008], "剧毒涌动与怒不可遏增加团伤，粘稠囊肿/腐蚀残渣持续压缩场地。"),
    ],
    "twinfangs": [
        ("双首领循环", "全程", [1293749, 1293792, 1290336, 1289192], "两只毒牙分别施放涌动/弹幕并叠加永恒毒液；腐蚀洪流和场地毒液形成持续压力。"),
        ("受护孵化", "能量阶段", [1303378, 1308356, 1308385], "首领保护并唤醒蛇群，需要处理孵化目标与内脏爆裂。"),
        ("深渊盛宴", "阶段切换", [1290956, 1290516, 1306922], "搅动深渊后进入饥饿盛宴，凝结血块等目标改变场上处理优先级。"),
    ],
    "bargained": [
        ("P1 毒蛇交易", "开场至祖尔金 50%", [1282487, 1283832, 1282287, 1283489], "祖尔金强化熔炉之牙并使用飞斧、毒斧和断头台；熔炉亵渎逐步改变场地。"),
        ("P2 篡位者复仇", "祖尔金 50% 后", [1243002, 1285844, 1285911, 1286573], "玛拉克拉斯附身玩家并召出恐惧化身；凝视、恐惧哀嚎和灵魂割裂构成核心控制链。"),
        ("转阶段：被夺取的容器", "祖尔金降至 1 点生命", [1304032, 1304033, 1287722], "玛拉克拉斯与祖尔金绑定并产生灵魂碎片；踩碎会造成团队伤害，漏掉则治疗祖尔金。"),
        ("P3 盘卷联合", "最终阶段", [1289802, 1298381, 1286918, 1286912], "两名首领同时作战且一方先死会令另一方狂暴；暗影与毒液机制叠加。"),
    ],
    "ulatek": [
        ("P1 毒蛇之母的怒火", "开场", [1292403, 1300751, 1298367, 1298559], "毒浪会孵化场上虫卵；处理尾部实体、母神之怒与暴露之心。"),
        ("转阶段：恶意孵化", "阶段转换", [1299757, 1299650, 1307612], "毒性孵化的直线会令虫卵立即孵化；史诗虫卵带硬化与毒性外壳。"),
        ("中段：多形态循环", "手册重复技能组", [1304012, 1301117, 1301213, 1306086], "召唤蛇群并处理抓取、蜕皮和毒素传递；不稳定净化在史诗到期时额外放出波浪。"),
        ("转阶段：碎裂", "后段转换", [1287265, 1301510, 1300743], "尾部砸击需要集合分摊，同时虫卵和毒液气泡压缩安全区域。"),
        ("终局：怒火释放", "最终阶段/狂暴", [1286905, 1286834, 1302505], "场地被彻底破坏，持续全团伤害急剧上升。乌拉特克无公开测试日志，本段完全来自地下城手册草案。"),
    ],
}

PHASE_DRAFTS["sszorak"] = [
    (
        "常态循环",
        "每次呼啸漩涡之间",
        [1277025, 1277002, 1277027, 1287072, 1305959, 1285419],
        "处理五段随机剑技、两轮毒液激流与狂怒侧风，并保存四个囊肿。",
    ),
    (
        "呼啸漩涡",
        "掘地固守 1286033 持续约 25 秒",
        [1285732, 1286033, 1287008, 1287205],
        "按预告的 1—2—3 风口顺序逐次激活三个囊肿，以 5 秒粘滞效果抵抗吹风；第四个留给坦克归位。",
    ),
    (
        "史诗：毒蛇之怒",
        "全程周期附加",
        [1297367, 1305621, 1297414, 1297707, 1296898],
        "至少 14 人进入点名玩家 8 码内触发大开杀戒清怒；100 怒获得怒不可遏。",
    ),
]

PHASE_DRAFTS["twinfangs"] = [
    (
        "双目标常态循环",
        "开场及每次涌动转场结束后",
        [1289192, 1289201, 1291404, 1290809, 1290956, 1290516],
        "每处场地完成两轮吃液滴、召唤子嗣、放脓液、躲波和贪婪盛宴消层，并穿插三次碎石击。",
    ),
    (
        "涌动转场",
        "每两轮常态循环后",
        [1293749, 1294293, 1306872, 1294605],
        "以当前坦克方向为射线起点，按预兆确认顺时针或逆时针旋转，随后移动到下一处场地。",
    ),
    (
        "史诗附加",
        "全程与对应常态技能同步",
        [1303230, 1303378, 1308356, 1308385, 1310102],
        "打断液滴护盾的受护孵化，分组持续打断场边幼体的内脏爆裂，并处理盛宴后的污血。",
    ),
    (
        "中场狂暴",
        "第三次涌动转场结束",
        [1308583],
        "三个场地位置全部使用后回到中场进入狂暴；现有英雄击杀样本在该阶段前结束。",
    ),
]

PHASE_DRAFTS["bargained"] = [
    (
        "P1 毒蛇交易",
        "开场至祖尔加降至 1 点生命",
        [1299960, 1282403, 1299684, 1283489, 1282487, 1283832],
        "搬运凝结毒液，用撕裂按计划清场，并处理处斩、毒牙、熔炉之牙与碎斧。",
    ),
    (
        "P2 篡位者复仇",
        "祖尔加退场至玛拉卡斯降至 1 点生命",
        [1285643, 1290316, 1286620, 1286895, 1286441, 1286918],
        "打破死亡进军护盾，固定恐惧具象位置，用灵魂撕裂清场并破盾打断永恒夜幕。",
    ),
    (
        "转阶段：被夺取的容器",
        "灵魂绑定/幽魂再生持续约 35 秒",
        [1304028, 1304032, 1304033, 1287718, 1287722],
        "祖尔加每秒回复 2% 且受到 100% 额外伤害；按节奏踩碎残片，阻止其回收精华。",
    ),
    (
        "P3 盘卷联合",
        "幽魂再生结束后",
        [1289798, 1298381, 1307279, 1299267],
        "双首领同步压血，处理熔炉亵渎、枯萎之刃与残酷断头台的场地压缩组合。",
    ),
    (
        "史诗附加",
        "全程与对应阶段同步",
        [1310498, 1310544, 1310732, 1309105, 1287722],
        "控制毒液变异连锁；私有具象由被凝视者负责；幽魂炸弹解除精魂护盾；踩片保持至少 5 秒节奏。",
    ),
]


def report_index(token, report_id):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights {
            id encounterID name difficulty startTime endTime kill
          }
          masterData {
            actors { id name type subType gameID petOwner }
            abilities { gameID name type }
          }
        }
      }
    }
    """
    try:
        return graphql(token, query, {"code": report_id})
    except RuntimeError:
        fallback = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              startTime
              fights {
                id encounterID name difficulty startTime endTime kill
              }
              masterData {
                actors { id name type subType gameID petOwner }
              }
            }
          }
        }
        """
        return graphql(token, fallback, {"code": report_id})


def ability_id(event):
    value = (
        event.get("abilityGameID")
        or event.get("abilityID")
        or (event.get("ability") or {}).get("gameID")
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_amount(event):
    return int(event.get("amount") or event.get("unmitigatedAmount") or 0)


def event_is_apply(event):
    return str(event.get("type") or "").lower() in {
        "applydebuff",
        "applybuff",
        "applybuffstack",
        "applydebuffstack",
        "refreshdebuff",
        "refreshbuff",
    }


def event_is_remove(event):
    return str(event.get("type") or "").lower() in {
        "removedebuff",
        "removebuff",
        "removebuffstack",
        "removedebuffstack",
    }


def choose_representative_fights(report_documents, difficulty):
    candidates = defaultdict(list)
    for report_id, document in report_documents.items():
        for fight in document.get("fights") or []:
            encounter_id = int(fight.get("encounterID") or 0)
            if (
                encounter_id not in ENCOUNTERS
                or int(fight.get("difficulty") or 0) != int(difficulty)
            ):
                continue
            candidates[encounter_id].append({
                **fight,
                "reportID": report_id,
                "durationMs": int(fight["endTime"] - fight["startTime"]),
            })
    selected = {}
    for encounter_id, fights in candidates.items():
        selected[encounter_id] = max(
            fights,
            key=lambda fight: (
                bool(fight.get("kill")),
                int(fight.get("durationMs") or 0),
            ),
        )
    return selected


def actor_maps(document):
    actors = (document.get("masterData") or {}).get("actors") or []
    by_id = {int(actor["id"]): actor for actor in actors}
    abilities = (document.get("masterData") or {}).get("abilities") or []
    ability_names = {
        int(ability["gameID"]): ability.get("name") or str(ability["gameID"])
        for ability in abilities
        if ability.get("gameID") is not None
    }
    return by_id, ability_names


def actor_is_friendly_player_or_pet(actor_id, actors):
    try:
        actor_id = int(actor_id)
    except (TypeError, ValueError):
        return False
    actor = actors.get(actor_id) or {}
    if actor.get("type") == "Player":
        return True
    owner_id = actor.get("petOwner")
    return bool(owner_id and (actors.get(int(owner_id)) or {}).get("type") == "Player")


def summarize_spell_events(events, *, fight, report_id, ability_names, actors, mode):
    grouped = defaultdict(list)
    for event in events:
        spell_id = ability_id(event)
        if not spell_id:
            continue
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        try:
            target_actor = actors.get(int(target_id)) or {}
        except (TypeError, ValueError):
            target_actor = {}
        if actor_is_friendly_player_or_pet(source_id, actors):
            continue
        # Anonymous/environment events can include player utility and self-damage
        # in WCL tables.  PTR boss spells in this zone use the new 1.2M+ range;
        # discard legacy low-ID environment rows while retaining NPC melee.
        if source_id in {None, -1, "-1"} and spell_id < 1_000_000:
            continue
        if mode == "debuffs" and target_actor.get("type") != "Player":
            continue
        if mode == "bossAuras" and target_actor.get("type") == "Player":
            continue
        grouped[spell_id].append(event)

    result = []
    for spell_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda event: int(event.get("timestamp") or 0))
        timestamps = [int(event.get("timestamp") or 0) for event in ordered]
        targets = {
            int(event["targetID"])
            for event in ordered
            if event.get("targetID") is not None
        }
        sources = {
            int(event["sourceID"])
            for event in ordered
            if event.get("sourceID") is not None
        }
        intervals = [
            timestamps[index] - timestamps[index - 1]
            for index in range(1, len(timestamps))
            if timestamps[index] > timestamps[index - 1]
        ]
        amounts = [event_amount(event) for event in ordered if event_amount(event) > 0]
        result.append({
            "spellID": spell_id,
            "name": ability_names.get(spell_id, str(spell_id)),
            "eventCount": len(ordered),
            "sourceIDs": sorted(sources),
            "sourceNames": sorted({
                (actors.get(source_id) or {}).get("name") or str(source_id)
                for source_id in sources
            }),
            "uniqueTargetCount": len(targets),
            "firstMs": timestamps[0] - int(fight["startTime"]),
            "lastMs": timestamps[-1] - int(fight["startTime"]),
            "medianIntervalMs": int(statistics.median(intervals)) if intervals else None,
            "totalAmount": sum(amounts),
            "maxAmount": max(amounts) if amounts else 0,
            "eventTypes": dict(Counter(str(event.get("type") or "") for event in ordered)),
            "provenance": {
                "reportID": report_id,
                "fightID": int(fight["id"]),
            },
        })
    return sorted(
        result,
        key=lambda row: (row["eventCount"], row["maxAmount"]),
        reverse=True,
    )


def summarize_resource_events(events, actors, fight, report_id):
    rows = []
    for event in events:
        source_id = event.get("sourceID")
        if actor_is_friendly_player_or_pet(source_id, actors):
            continue
        change = event.get("resourceChange")
        resource_type = event.get("resourceChangeType")
        if change in {None, 0} and resource_type is None:
            continue
        rows.append({
            "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
            "sourceID": source_id,
            "source": (actors.get(source_id) or {}).get("name") or str(source_id),
            "resourceChange": change,
            "resourceChangeType": resource_type,
            "resourceActor": event.get("resourceActor"),
            "provenance": {"reportID": report_id, "fightID": int(fight["id"])},
        })
    return rows


def summarize_death_clusters(events, actors, fight, report_id, window_ms=1_500):
    ordered = sorted(events, key=lambda event: int(event.get("timestamp") or 0))
    clusters = []
    current = []
    for event in ordered:
        timestamp = int(event.get("timestamp") or 0)
        if current and timestamp - int(current[-1].get("timestamp") or 0) > window_ms:
            clusters.append(current)
            current = []
        current.append(event)
    if current:
        clusters.append(current)
    result = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        timestamps = [int(event.get("timestamp") or 0) for event in cluster]
        result.append({
            "timeMs": timestamps[0] - int(fight["startTime"]),
            "count": len(cluster),
            "durationMs": timestamps[-1] - timestamps[0],
            "players": [
                (actors.get(event.get("targetID")) or {}).get("name")
                or str(event.get("targetID"))
                for event in cluster
            ],
            "abilityIDs": [event.get("killingAbilityGameID") for event in cluster],
            "provenance": {"reportID": report_id, "fightID": int(fight["id"])},
        })
    return result


def analyze_fight(token, fight, document):
    report_id = fight["reportID"]
    actors, ability_names = actor_maps(document)
    event_sets = {
        "casts": fetch_events_all(token, report_id, "Casts", fight, hostility_type="Enemies"),
        "damage": fetch_events_all(token, report_id, "DamageTaken", fight),
        "debuffs": fetch_events_all(token, report_id, "Debuffs", fight, hostility_type="Friendlies"),
        "bossAuras": fetch_events_all(token, report_id, "Buffs", fight, hostility_type="Enemies"),
        "resources": fetch_events_all(
            token,
            report_id,
            "Resources",
            fight,
            hostility_type="Enemies",
            include_resources=True,
        ),
        "deaths": fetch_events_all(token, report_id, "Deaths", fight),
    }
    return {
        "fight": {
            "reportID": report_id,
            "fightID": int(fight["id"]),
            "name": fight.get("name"),
            "kill": bool(fight.get("kill")),
            "durationMs": int(fight["endTime"] - fight["startTime"]),
            "difficulty": int(fight.get("difficulty") or 0),
        },
        "enemyCasts": summarize_spell_events(
            event_sets["casts"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="casts",
        ),
        "damageAbilities": summarize_spell_events(
            event_sets["damage"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="damage",
        ),
        "playerDebuffs": summarize_spell_events(
            event_sets["debuffs"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="debuffs",
        ),
        "bossAuras": summarize_spell_events(
            event_sets["bossAuras"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="bossAuras",
        ),
        "bossResources": summarize_resource_events(
            event_sets["resources"], actors, fight, report_id,
        ),
        "deathClusters": summarize_death_clusters(
            event_sets["deaths"], actors, fight, report_id,
        ),
    }


SPELL_CATEGORIES = (
    "enemyCasts",
    "damageAbilities",
    "playerDebuffs",
    "bossAuras",
)


def merge_spell_catalog(evidence, journal):
    journal_by_id = {
        int(row["spellID"]): row
        for row in (journal or {}).get("spells") or []
    }
    catalog = {}
    for category in SPELL_CATEGORIES:
        rows = {}
        for difficulty_name, analysis in evidence.items():
            for item in analysis.get(category) or []:
                spell_id = int(item["spellID"])
                row = rows.setdefault(
                    spell_id,
                    {
                        "spellID": spell_id,
                        "name": item.get("name") or str(spell_id),
                        "observedIn": {},
                    },
                )
                row["observedIn"][difficulty_name] = item
        for spell_id, journal_row in journal_by_id.items():
            if spell_id not in rows:
                continue
            rows[spell_id]["journal"] = {
                "name": journal_row.get("name"),
                "mythicOnly": bool(journal_row.get("mythicOnly")),
                "mythicMentioned": bool(journal_row.get("mythicMentioned")),
            }
        catalog[category] = sorted(
            rows.values(),
            key=lambda row: (
                "heroic" not in row["observedIn"],
                "mythic" not in row["observedIn"],
                row["spellID"],
            ),
        )
    observed_ids = {
        row["spellID"]
        for rows in catalog.values()
        for row in rows
    }
    catalog["journalOnly"] = [
        row for row in (journal or {}).get("spells") or []
        if int(row["spellID"]) not in observed_ids
    ]
    return catalog


def migrate_result(result):
    if int(result.get("schemaVersion") or 1) >= 2:
        result.setdefault("reports", {"heroic": [], "mythic": []})
        return result
    old_reports = result.get("reports") or []
    bosses = {}
    for key, boss in (result.get("bosses") or {}).items():
        analysis = {
            field: boss.get(field)
            for field in (
                "fight",
                "enemyCasts",
                "damageAbilities",
                "playerDebuffs",
                "bossAuras",
                "bossResources",
                "deathClusters",
            )
            if boss.get(field) is not None
        }
        bosses[key] = {
            "encounterID": boss.get("encounterID"),
            "name": boss.get("name"),
            "evidence": {"mythic": analysis},
            "modeDraft": boss.get("modeDraft"),
        }
    return {
        "schemaVersion": 2,
        "zoneID": result.get("zoneID") or ZONE_ID,
        "reports": {"heroic": [], "mythic": old_reports},
        "bosses": bosses,
        "missingEncounterIDs": {},
        "expectedUntested": result.get("expectedUntested") or [],
    }


def render_markdown(document):
    def observed_cell(row, difficulty):
        item = (row.get("observedIn") or {}).get(difficulty)
        if not item:
            return "—"
        events = int(item.get("eventCount") or 0)
        targets = int(item.get("uniqueTargetCount") or 0)
        first_ms = int(item.get("firstMs") or 0)
        return f"{events} 次 / {targets} 人 / 首次 {first_ms / 1000:.1f}s"

    def spell_label(spell_id, english_name):
        zh_name = SPELL_ZH.get(int(spell_id))
        return f"{zh_name}<br><small>{english_name}</small>" if zh_name else english_name

    def mechanic_hint(boss_key, category, row):
        spell_id = int(row["spellID"])
        for phase in PHASE_DRAFTS.get(boss_key, []):
            if spell_id in phase[2]:
                return phase[3]
        if category == "playerDebuffs":
            return "玩家状态事件；结合施加、层数、移除/死亡时间和伤害事件确认结算。"
        if category == "bossAuras":
            return "Boss/add 的强化或阶段状态，可作为阶段切换和机制成立的时间锚点。"
        if category == "damageAbilities":
            return "Boss/add 伤害来源；用于高伤、可规避伤害和死亡归因。"
        return "敌方施法时间轴信号；用于技能轮次、打断和阶段定位。"

    lines = [
        "# 12.1 烈毒之渊：Boss 法术 ID、Debuff 与阶段草案",
        "",
        "> 数据分层：地下城手册列出预期机制，英雄日志覆盖完整流程，史诗日志验证差异。"
        "中文名称和效果摘要是编辑译文；英文名与 spell ID 才是稳定分析键。",
        "",
        "> Bilibili H1–H7 视频用于核对玩家实际流程，但公开视频没有字幕轨；阶段边界以视频观感、"
        "地下城手册的 Stage/Intermission 标题和 WCL cast/aura 信号合并起草。",
        "",
    ]
    for key, boss in document["bosses"].items():
        heroic = (boss.get("evidence") or {}).get("heroic")
        mythic = (boss.get("evidence") or {}).get("mythic")
        lines.extend([
            f"## {BOSS_ZH.get(key, boss['name'])} / {boss['name']} (`{key}`)",
            "",
        ])
        for label, analysis in (("英雄", heroic), ("史诗", mythic)):
            if not analysis:
                lines.append(f"- {label}代表战斗：无")
                continue
            fight = analysis["fight"]
            lines.append(
                f"- {label}代表战斗：`{fight['reportID']}` / Fight {fight['fightID']}，"
                f"{fight['durationMs'] / 1000:.1f}s，kill={fight['kill']}"
            )
        journal = boss.get("journal") or {}
        lines.append(
            f"- 地下城手册收录 {len(journal.get('spells') or [])} 个法术 ID；"
            f"其中日志尚未观察到 {len((boss.get('spellCatalog') or {}).get('journalOnly') or [])} 个。"
        )
        if key == "ulatek":
            lines.append("- 状态：惯例不开放尾王公开测试；以下只有手册证据，不应误标为数据缺失。")

        lines.extend(["", "### 战斗阶段（初稿）", ""])
        lines.append("| 阶段 | 触发/边界 | 核心 spell ID | 大致机制 |")
        lines.append("|---|---|---|---|")
        for phase_name, trigger, spell_ids, note in PHASE_DRAFTS.get(key, []):
            ids = ", ".join(f"`{spell_id}`" for spell_id in spell_ids)
            lines.append(f"| {phase_name} | {trigger} | {ids} | {note} |")

        for category, label in (
            ("damageAbilities", "Boss / add 伤害来源"),
            ("playerDebuffs", "施加到玩家的 Debuff"),
            ("bossAuras", "Boss / add 强化与 Aura"),
            ("enemyCasts", "Boss / add Cast 与阶段信号"),
        ):
            rows = [
                row for row in (boss.get("spellCatalog") or {}).get(category) or []
                if int(row.get("spellID") or 0) >= 1_000_000
            ]
            lines.extend(["", f"### {label}", ""])
            if not rows:
                lines.append("该类别在当前代表日志中没有可用记录。")
                continue
            lines.append("| spell ID | 技能（中文编辑译名 / 英文稳定名） | 英雄证据 | 史诗证据 | 机制/取证用途 |")
            lines.append("|---:|---|---|---|---|")
            for row in rows:
                spell_id = int(row["spellID"])
                name = str(
                    (row.get("journal") or {}).get("name")
                    or row.get("name")
                    or spell_id
                )
                hint = mechanic_hint(key, category, row).replace("|", "／")
                lines.append(
                    f"| `{spell_id}` | {spell_label(spell_id, name)} | "
                    f"{observed_cell(row, 'heroic')} | {observed_cell(row, 'mythic')} | {hint} |"
                )

        journal_only = (boss.get("spellCatalog") or {}).get("journalOnly") or []
        lines.extend(["", "### 手册已列出、当前 WCL 代表战斗未观察到的 ID", ""])
        if journal_only:
            lines.append("| spell ID | 技能 | 难度提示 |")
            lines.append("|---:|---|---|")
            for row in journal_only:
                spell_id = int(row["spellID"])
                difficulty = (
                    "仅史诗" if row.get("mythicOnly")
                    else "手册提及史诗差异" if row.get("mythicMentioned")
                    else "通用/尚未分类"
                )
                lines.append(
                    f"| `{spell_id}` | {spell_label(spell_id, row.get('name') or str(spell_id))} | "
                    f"{difficulty} |"
                )
        else:
            lines.append("无。")

        if journal.get("mythicDifferences"):
            lines.extend(["", "### 地下城手册明确写出的史诗差异（英文原意）", ""])
            for note in journal["mythicDifferences"]:
                lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", help="旧参数：逗号分隔的 Mythic WCL report ID")
    parser.add_argument("--heroic-reports", help="逗号分隔的 Heroic WCL report ID")
    parser.add_argument("--mythic-reports", help="逗号分隔的 Mythic WCL report ID")
    parser.add_argument(
        "--journal",
        default="skills/venomous-abyss-raid-development/references/source-data/journal.json",
    )
    parser.add_argument(
        "--output",
        default="skills/venomous-abyss-raid-development/references/source-data/spell-discovery.json",
    )
    parser.add_argument(
        "--markdown",
        default="zone54_spell_discovery.md",
    )
    parser.add_argument("--resume", action="store_true", help="保留已有 Boss 结果，只补缺失 encounter")
    args = parser.parse_args()

    heroic_report_ids = [
        value.strip() for value in (args.heroic_reports or "").split(",")
        if value.strip()
    ]
    mythic_report_ids = [
        value.strip() for value in (args.mythic_reports or args.reports or "").split(",")
        if value.strip()
    ]
    report_ids = list(dict.fromkeys([*heroic_report_ids, *mythic_report_ids]))
    if not report_ids and not (args.resume and Path(args.output).exists()):
        parser.error("至少提供 --heroic-reports 或 --mythic-reports")
    if report_ids:
        # Keep the WCL HTTP client lazy so offline/static rebuilds do not
        # require the optional requests dependency.
        global fetch_events_all, get_token, graphql
        from boss_plugins.void_spire.crown_of_the_cosmos import (
            fetch_events_all,
            get_token,
            graphql,
        )
    output = Path(args.output)
    markdown = Path(args.markdown)
    token = get_token() if report_ids else None
    documents = {report_id: report_index(token, report_id) for report_id in report_ids}
    selected_by_difficulty = {
        "heroic": choose_representative_fights(
            {key: documents[key] for key in heroic_report_ids}, 4,
        ),
        "mythic": choose_representative_fights(
            {key: documents[key] for key in mythic_report_ids}, 5,
        ),
    }

    if args.resume and output.exists():
        result = migrate_result(json.loads(output.read_text(encoding="utf-8")))
    else:
        result = {
            "schemaVersion": 2,
            "zoneID": ZONE_ID,
            "reports": {"heroic": [], "mythic": []},
            "bosses": {},
            "missingEncounterIDs": {},
        }
    for difficulty_name, ids in (
        ("heroic", heroic_report_ids),
        ("mythic", mythic_report_ids),
    ):
        result["reports"][difficulty_name] = list(dict.fromkeys([
            *(result["reports"].get(difficulty_name) or []),
            *ids,
        ]))
        selected = selected_by_difficulty[difficulty_name]
        for encounter_id, fight in sorted(
            selected.items(),
            key=lambda item: list(ENCOUNTERS).index(item[0]),
        ):
            metadata = ENCOUNTERS[encounter_id]
            boss = result["bosses"].setdefault(metadata["key"], {
                "encounterID": encounter_id,
                "name": metadata["name"],
                "evidence": {},
            })
            if difficulty_name in boss.setdefault("evidence", {}):
                continue
            print(
                f"[zone54] {difficulty_name} {metadata['name']}: "
                f"{fight['reportID']} Fight {fight['id']}",
                flush=True,
            )
            boss["evidence"][difficulty_name] = analyze_fight(
                token,
                fight,
                documents[fight["reportID"]],
            )

    journal_document = {}
    journal_path = Path(args.journal)
    if journal_path.exists():
        journal_document = json.loads(journal_path.read_text(encoding="utf-8"))
    result["sources"] = {
        "journal": journal_document.get("source"),
        "referenceVideos": journal_document.get("referenceVideos") or [],
    }
    # Keep journal-only encounters (notably the traditionally untested final
    # boss Ula'tek) in the same output shape as encounters with WCL evidence.
    for encounter_id, metadata in ENCOUNTERS.items():
        result["bosses"].setdefault(metadata["key"], {
            "encounterID": encounter_id,
            "name": metadata["name"],
            "evidence": {},
        })
    for boss_key, boss in result["bosses"].items():
        boss["modeDraft"] = MODE_DRAFTS.get(boss_key, {
            "confidence": "unknown",
            "summary": "尚无足够日志形成模式草稿。",
            "phaseSignals": [],
            "majorMechanics": [],
        })
        boss["journal"] = (
            (journal_document.get("bosses") or {}).get(boss_key) or {}
        )
        boss["spellCatalog"] = merge_spell_catalog(
            boss.get("evidence") or {},
            boss.get("journal") or {},
        )
    captured_encounters = {
        int(boss.get("encounterID") or 0)
        for boss in result["bosses"].values()
    }
    expected_untested_ids = {
        encounter_id
        for encounter_id, metadata in ENCOUNTERS.items()
        if metadata.get("expectedUntested")
    }
    result["expectedUntested"] = [
        {
            "encounterID": encounter_id,
            "key": ENCOUNTERS[encounter_id]["key"],
            "name": ENCOUNTERS[encounter_id]["name"],
            "note": ENCOUNTERS[encounter_id]["note"],
        }
        for encounter_id in sorted(expected_untested_ids)
        if encounter_id not in captured_encounters
    ]
    captured_by_difficulty = {
        difficulty_name: {
            int(boss.get("encounterID") or 0)
            for boss in result["bosses"].values()
            if difficulty_name in (boss.get("evidence") or {})
        }
        for difficulty_name in DIFFICULTIES.values()
    }
    result["missingEncounterIDs"] = {
        difficulty_name: sorted(
            set(ENCOUNTERS) - captured - expected_untested_ids
        )
        for difficulty_name, captured in captured_by_difficulty.items()
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown.write_text(render_markdown(result), encoding="utf-8")
    print(f"[zone54] wrote {output} and {markdown}", flush=True)
    if any(result["missingEncounterIDs"].values()):
        print(
            f"[zone54] missing encounter IDs: {result['missingEncounterIDs']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
