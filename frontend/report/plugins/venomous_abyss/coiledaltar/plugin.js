window.MythicReportPlugin = {
  id: "venomous_abyss/coiledaltar",
  renderer: "coiledaltar",
  reportPage: "frontend/report/plugins/venomous_abyss/coiledaltar/report.html",
  sections: ["survival", "guildTimeline", "p1", "p2", "intermission", "p3", "field"],
  analysisModules: [{label:"公会战术核对：停手与爆发轴", detailTab:"guildTimeline", dataPath:"coiledaltar.guildTimeline",
    description:"选择单场查看 P1 / P2 的 1%–10% 停手滑块、玩家施法与伤害、爆发轴及药水。整晚汇总在“机制统计”。"}]
};
