const state = { payload: null, pulls: [], pull: 0, tab: "survival", sourcePath: "", diagram: 0, fieldOpen: {} };
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => Number(v || 0).toLocaleString("zh-CN");
function current() { return state.pulls[state.pull] || null; }
function boss() { return current()?.coiledaltar || {}; }
function player(row) { return `<span class="player" style="color:${row?.classColor || "#fff"}">${esc(row?.player || row?.name || "—")}</span>`; }
function players(rows) { return (rows || []).map(player).join("、") || "—"; }
function spellLink(id, name) { const spellID = Number(id || 0), label = name || (spellID ? `法术 ${spellID}` : "—"); return !spellID || [1, 3, 4, 5, 6, 7, 8].includes(spellID) ? esc(label) : `<a href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;spell=${spellID}" target="_blank" rel="noreferrer">${esc(label)}</a>`; }
function refreshWowhead() { if (window.WH?.Tooltips?.refreshLinks) window.WH.Tooltips.refreshLinks(); else if (window.$WowheadPower) window.$WowheadPower.refreshLinks(); }
function table(headers, rows) { if (!rows?.length) return '<div class="empty">没有对应记录。</div>'; return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell ?? "—"}</td>`).join("")}</tr>`).join("")}</tbody></table>`; }
function pct(point, arena) { if (!point || !arena) return null; const radius = Number(arena.radius || 1), dx = Number(point.x) - Number(arena.centerX), dy = Number(point.y) - Number(arena.centerY); return { left: 50 + (dx / radius) * Number(arena.plotScaleX || 25.9389), top: 50 - (dy / radius) * Number(arena.plotScaleY || 46.3327) }; }
function pctSize(yards, arena) { if (!arena) return { width: 0, height: 0 }; const units = Number(yards || 0) * Number(arena.unitsPerYard || 100); return { width: units / Number(arena.radius || 1) * Number(arena.plotScaleX || 25.9389), height: units / Number(arena.radius || 1) * Number(arena.plotScaleY || 46.3327) }; }
function rangeCircle(origin, yards, arena, cls, title) { const p = pct(origin, arena), size = pctSize(yards, arena); return p ? `<span class="${cls}" title="${esc(title || "")}" style="left:${p.left}%;top:${p.top}%;width:${size.width * 2}%;height:${size.height * 2}%"></span>` : ""; }
function resolveConeFacing(diagram) {
  // 注意：Number(null)===0，不能把缺失朝向当成正东
  if (diagram.facingRadians != null && Number.isFinite(Number(diagram.facingRadians))) {
    return Number(diagram.facingRadians);
  }
  const origin = diagram.origin, tank = diagram.tankPosition;
  if (!origin || !tank || tank.x == null || tank.y == null) return null;
  return Math.atan2(-(Number(tank.y) - Number(origin.y)), Number(tank.x) - Number(origin.x));
}
/**
 * 在整张示意图百分比坐标系画扇形：尖端 = pct(origin) = Boss 标记，二者共用同一映射。
 * 弧点在游戏坐标按正圆扇区生成，再经 pct() 投影（各向异性图也不会把尖端挪开）。
 */
function buildConePathD(diagram, arena) {
  const origin = diagram.origin;
  const facing = resolveConeFacing(diagram);
  const apex = pct(origin, arena);
  if (!origin || facing == null || !apex) return null;
  const yards = Number(diagram.coneRadiusYards || 35);
  const half = (Number(diagram.coneHalfAngleDeg || 30) * Math.PI) / 180;
  const radius = yards * Number(arena.unitsPerYard || 100);
  const ox = Number(origin.x);
  const oy = Number(origin.y);
  const parts = [`M ${apex.left.toFixed(4)} ${apex.top.toFixed(4)}`];
  for (let i = 0; i <= 32; i += 1) {
    const angle = facing - half + ((2 * half) * i) / 32;
    const point = pct({
      x: ox + Math.cos(angle) * radius,
      y: oy - Math.sin(angle) * radius,
    }, arena);
    if (!point) continue;
    parts.push(`L ${point.left.toFixed(4)} ${point.top.toFixed(4)}`);
  }
  parts.push("Z");
  return parts.join(" ");
}
function renderConeOverlay(diagram, arena) {
  const origin = diagram.origin;
  const apex = pct(origin, arena);
  if (!apex) return "";
  const yards = diagram.coneRadiusYards || 35;
  const circle = rangeCircle(origin, yards, arena, "cone-radius", `${yards} 码撕裂半径`);
  const boss = bossMarker(apex, diagram, posLabel(origin, arena));
  const d = buildConePathD(diagram, arena);
  if (!d) {
    return `${circle}${boss}<p class="legend warn">缺少朝向数据，只显示 Boss 与半径圈。</p>`;
  }
  const svg = `<svg class="cone-map" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"></path></svg>`;
  return `${circle}${svg}${boss}`;
}
function posLabel(position, arena) {
  if (!position) return "无坐标";
  const scale = Number(arena?.wclCoordScale || 100);
  return `${(position.x / scale).toFixed(1)}, ${(position.y / scale).toFixed(1)}`;
}
function renderStats() { const pull = current(), survival = pull?.survival || {}; $("title").textContent = `盘卷祭坛，Fight ${pull?.fightID || "-"}`; $("meta").textContent = `${pull?.difficultyName || "未知难度"}，${pull?.isKill ? "击杀" : `Boss 剩余 ${Number(pull?.bossPercentage || 0).toFixed(2)}%`}，${pull?.date || ""} ${pull?.startClock || ""}`; if(state.payload?.meta?.skippedAnalyses?.length){$("meta").textContent += `，${state.payload.meta.skippedAnalyses.length}项可选复盘未启用`;}if(boss().analysisProfile)$("meta").textContent+="，"+boss().analysisProfile.label;$("wclLink").href = pull?.wclDeepLink || "#"; const items = [["战斗时长", pull?.duration || "—"], ["结果", pull?.isKill ? "KILL" : `${Number(pull?.bossPercentage || 0).toFixed(2)}%`], ["难度", pull?.difficultyName || "未知"], ["阵亡", survival.deathCount || 0], ["战复", survival.combatResCount || 0], ["结束存活", `${survival.survivorCount || 0}/${survival.rosterCount || 0}`]]; $("stats").innerHTML = items.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join(""); }
function renderTabs() { const defs = [...(state.payload?.meta?.tabDefinitions || [{ key: "survival", label: "全场存活情况" }])].filter(d=>!["field","explore","guildTimeline"].includes(d.key) && (d.key!=="p1" || ["toxicDelugeReviewEnabled","severReviewEnabled","guillotineReviewEnabled"].some(k=>state.payload?.meta?.analysisConfig?.[k]!==false)) && (d.key!=="p3" || ["blightedSeverReviewEnabled","grimGuillotineReviewEnabled"].some(k=>state.payload?.meta?.analysisConfig?.[k]!==false))); if(boss().guildTimeline?.enabled)defs.splice(1,0,{key:"guildTimeline",label:boss().guildTimeline.checksEnabled===false?"玩家施法时间轴":"施法与公会战术核对"}); if(boss().combatReplay&&!defs.some(d=>d.key==='replay'))defs.splice(1,0,{key:'replay',label:'战斗回放'}); if (!defs.some((row) => row.key === state.tab)) state.tab = defs[0].key; $("tabs").innerHTML = defs.map((row) => `<button data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join(""); document.querySelectorAll("[data-tab]").forEach((button) => (button.onclick = () => { state.tab = button.dataset.tab; renderContent(); renderTabs(); })); }
function renderSurvival() { const s = current()?.survival || {}; return `<section class="panel"><h2>死亡原因 / 战复时间线</h2>${table(["时间", "类型", "玩家", "原因 / 技能"], (s.timeline || []).map((event) => [esc(event.time), event.kind === "combat_res" ? '<span class="badge good">战复</span>' : '<span class="badge bad">死亡</span>', player(event), event.kind === "combat_res" ? `${esc(event.source)} 使用 ${esc(event.ability)}` : event.deathCause === "fall" ? "跌落" : spellLink(event.abilityID, event.ability)]))}</section><section class="panel"><h2>阶段时间线</h2>${table(["阶段", "时间"], (boss().phaseTimeline || []).map((row) => [esc(row.label), esc(fmtPhase(row.timeMs))]))}</section>`; }
function fmtPhase(ms) { const s = Math.max(0, Number(ms || 0)) / 1000; return `${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`; }
function stillInsideRows(round) { return round?.stillInsideRange || round?.stillInside50 || []; }
function renderGuillotineTable(title, data) {
  const rounds = data?.rounds || [];
  const isGrim = /冷酷/.test(title);
  const evidence = isGrim
    ? "是否离开 40 码圈按死亡低语脉冲时是否吃到死亡之拥判断。"
    : "是否离开 40 码圈按寡妇之触脉冲时是否吃到寡妇之吻判断。";
  const insideCol = isGrim ? "死亡之拥（仍在圈内）" : "寡妇之吻（仍在圈内）";
  return `<section class="panel" data-analysis-option="${title === "冷酷处斩" ? "grimGuillotineReviewEnabled" : "guillotineReviewEnabled"}"><h2>${esc(title)}</h2><p class="muted">${esc(evidence)}</p>${table(["轮次", "时间", "分摊人数", "参与者", insideCol], rounds.map((row) => [`#${row.index}`, esc(row.time), row.participantCount, players(row.participants), players(stillInsideRows(row).map((p) => ({ player: p.player, classColor: p.classColor })))]))}</section>`;
}
function renderGloombomb(data, phase) {
  const rounds = phase ? phaseRows(data?.rounds, phase, "p2") : (data?.rounds || []);
  const splashRows = [];
  const shieldRows = [];
  const missRows = [];
  const showShield = Boolean(data?.hasSoulcoilerShield) || rounds.some((row) => (row.soulcoilers || []).length);
  (rounds || []).forEach((row) => {
    (row.collateralHits || []).forEach((hit) => {
      splashRows.push([
        `#${row.index}`,
        esc(hit.fromPlayer || "—"),
        player(hit),
        hit.distanceYards == null ? "—" : `${hit.distanceYards}码`,
        `<span class="badge bad">墓缚 ${esc(hit.graveboundApplyTime || "")}</span>`,
      ]);
    });
    (row.soulcoilers || []).forEach((coiler) => {
      const hitPlayers = (coiler.hits || []).filter((hit) => hit.hit).map((hit) => hit.player).join("、") || "—";
      shieldRows.push([
        `#${row.index}`,
        esc(coiler.name || "怨毒盘魂者"),
        coiler.sourceInstance ?? "—",
        coiler.shieldStacks == null ? "—" : `${coiler.shieldStacks} / ${coiler.bombsRequired || 2}`,
        `${coiler.bombHits ?? 0}`,
        hitPlayers,
        coiler.interrupted
          ? `<span class="badge warn">${player(coiler.interruptPlayer || { player: "打断" })} ${esc(coiler.interruptTime || "")}${coiler.relocateYards != null ? `，位移 ${coiler.relocateYards}码` : ""}</span>`
          : "—",
        coiler.displacedMiss ? '<span class="badge bad">打断炸空</span>' : (coiler.bombHits >= (coiler.bombsRequired || 2) ? '<span class="badge good">够两枚</span>' : '<span class="badge warn">不足两枚</span>'),
      ]);
    });
    (row.displacedMisses || []).forEach((hit) => {
      missRows.push([
        `#${row.index}`,
        player(hit),
        esc(hit.soulcoilerInstance ?? "—"),
        hit.distanceYards == null ? "—" : `${hit.distanceYards}码`,
        player(hit.interruptPlayer || { player: "—" }),
        esc(hit.interruptTime || "—"),
        hit.relocateYards == null ? "—" : `${hit.relocateYards}码`,
      ]);
    });
  });
  const headers = showShield
    ? ["轮次", "时间", "点名数", "点名过近", "误伤墓缚", "盘魂者", "打断炸空"]
    : ["轮次", "时间", "点名数", "点名过近", "误伤墓缚"];
  const roundTable = table(headers, rounds.map((row) => {
    const base = [`#${row.index}`, esc(row.time), row.targetCount, (row.tooClosePairs || []).map((pair) => `${esc(pair.left)}↔${esc(pair.right)} ${pair.distanceYards}码`).join("；") || "—", row.collateralCount ?? (row.collateralHits || []).length];
    if (!showShield) return base;
    base.push(row.soulcoilerCount ?? (row.soulcoilers || []).length);
    base.push(row.displacedMissCount ? `<span class="badge bad">${row.displacedMissCount}</span>` : "0");
    return base;
  }));
  const shieldTable = showShield && shieldRows.length
    ? `<h3>${spellLink(1309105, "灵魂之盾")} / ${spellLink(1310881, "幽暗炸弹")}</h3><p class="muted">每轮只标两只怨毒盘魂者。拆盾需要两名点名玩家在 15 码内爆炸。</p>${table(["轮次", "盘魂者", "实例", "炸时盾层", "命中炸弹", "命中玩家", "打断", "结果"], shieldRows)}`
    : "";
  const missTable = missRows.length
    ? `<h3>打断导致炸空</h3>${table(["轮次", "炸弹玩家", "盘魂者实例", "爆炸时距离", "打断者", "打断时间", "位移"], missRows)}`
    : "";
  return `<section class="panel" data-analysis-option="gloombombReviewEnabled"><h2>幽暗炸弹${showShield ? "与灵魂之盾" : "分散"}</h2><p class="muted">${esc(data?.evidenceNote || "只列出爆炸时 15 码内、且 2 秒内获得墓缚 1286837 的非点名玩家。")}</p>${roundTable}${shieldTable}${missTable}${splashRows.length ? `<h3>圈内误伤墓缚</h3>${table(["轮次", "点名", "误伤玩家", "距离", "墓缚"], splashRows)}` : '<div class="empty">本场没有圈内误伤墓缚。</div>'}</section>`;
}
function phaseKey(row) { return String(row?.phase || "").toLowerCase(); }
function withPhaseRounds(data, phase, untaggedPhase = "p2") {
  return { ...(data || {}), rounds: phaseRows(data?.rounds, phase, untaggedPhase) };
}
function phaseRows(rows, phase, untaggedPhase = "p2") {
  const list = rows || [];
  const tagged = list.some((row) => row.phase);
  if (!tagged) return phase === untaggedPhase ? list : [];
  return list.filter((row) => phaseKey(row) === phase);
}
function venomRoundsForPhase(rounds, phase) {
  const list = rounds || [];
  const tagged = list.some((row) => row.phase);
  if (!tagged) return phase === "p1" ? list : [];
  return list.flatMap((round) => {
    const roundPhase = phaseKey(round) || "p1";
    const carriers = (round.carriers || []).filter((row) => (phaseKey(row) || roundPhase) === phase);
    if (roundPhase === phase) return [{ ...round, carriers }];
    if (!carriers.length) return [];
    return [{ ...round, index: round.index, time: carriers[0]?.applyTime || carriers[0]?.removeTime || round.time, carriers }];
  });
}
function venomKindBadge(row) {
  if ((row?.venomKind || row?.kind) === "virulent-mutation" || String(row?.kind || "").includes("virulent")) {
    return `<span class="badge warn">${spellLink(1310544, "烈毒变异体")}</span>`;
  }
  return `<span class="badge">${spellLink(1282403, "凝结毒液")}</span>`;
}
function renderToxicDeluge(rounds) {
  const showKind = (rounds || []).some((round) =>
    (round.carriers || []).some((row) => row.venomKind === "virulent-mutation")
    || (round.spawns || []).some((row) => row.venomKind === "virulent-mutation")
    || Number(round.mutationSpawnCount || 0)
  );
  const headers = showKind
    ? ["类型", "玩家", "拾起", "掉落", "持有时长", "落点"]
    : ["玩家", "拾起", "掉落", "持有时长", "落点"];
  const paired = (rounds || []).some((round) => round.mythicSeverClear);
  const rule = paired ? `<p class="muted">史诗下每两轮撕裂处理这一轮剧毒洪流。默认第一下劈场地南侧的凝结毒液和烈毒变异体，第二下劈场地北侧。</p>` : "";
  const clearLine = (round) => {
    const clear = round.mythicSeverClear;
    if (!clear) return "";
    const side = (label, assigned, hit, missed) => `${esc(label || "尚无")}：应清 ${assigned ?? 0}，锥内 ${hit ?? 0}，未覆盖 ${Number(missed || 0) > 0 ? `<span class="badge bad">${missed}</span>` : "0"}`;
    return `<p class="muted">南侧 ${side(clear.southLabel, clear.southAssigned, clear.southInCone, clear.southMissed)}；北侧 ${side(clear.northLabel, clear.northAssigned, clear.northInCone, clear.northMissed)}。</p>`;
  };
  const cards = (rounds || []).map((round) => `<article class="card"><h3>#${round.index}，${esc(round.time)}</h3>${clearLine(round)}<h4>搬运者 / 落点</h4>${table(headers, (round.carriers || []).map((row) => {
    const cells = [player(row), esc(row.applyTime), esc(row.removeTime || "—"), row.carryDurationMs == null ? "—" : `${(row.carryDurationMs / 1000).toFixed(1)}s`, posLabel(row.dropPosition)];
    return showKind ? [venomKindBadge(row), ...cells] : cells;
  }))}</article>`).join("");
  return `<section class="panel" data-analysis-option="toxicDelugeReviewEnabled"><h2>剧毒洪流，凝结毒液与烈毒变异体</h2>${rule}<div class="cards">${cards || '<div class="empty">没有剧毒洪流记录。</div>'}</div></section>`;
}
function mythicSeverCells(row) {
  const pair = row.mythicDelugePair || {};
  const missed = Number(pair.assignedMissed || 0);
  return [
    esc(pair.sideLabel || "—"),
    pair.delugeIndex ? `#${pair.delugeIndex}` : "—",
    pair.assignedCount ?? "—",
    pair.assignedInCone ?? "—",
    missed > 0 ? `<span class="badge bad">${missed}</span>` : (pair.assignedCount == null ? "—" : "0"),
  ];
}
function renderMythicVenomSeverTable(rounds) {
  const paired = (rounds || []).filter((row) => row.mythicDelugePair);
  if (!paired.length) return "";
  const check = row => {const c=row.stackClearCheck;return c ? `实测 ${c.observedCount ?? "—"}，推演 ${c.geometryCount}${c.status === "matched" ? "，一致" : "，待核对"}` : "—";};
  return `<h3>剧毒洪流清场</h3><p class="muted">新增毒液爆裂层数用于核对撕裂清球数量。位置不足以确定清理对象时保留待核对提示。</p>${table(["轮次", "时间", "清场侧", "洪流", "应清", "锥内", "未覆盖", "清球核对"], paired.map((row) => [`#${row.index}`, esc(row.time), ...mythicSeverCells(row), check(row)]))}`;
}
function renderManifestations(fixations) {
  const phases = new Set((fixations || []).map(row => row.phase));
  const collisions = (boss().manifestReplay?.resonanceCollisions || []).filter(row => phases.has(row.phase));
  const collisionTable = collisions.length ? `<h3>恶毒共鸣</h3><p class="muted">按共鸣前的玩家面向推测具象移动；双方都移动或采样不足时，不指定责任玩家。</p>${table(["时间", "受影响玩家", "推测移动方", "共鸣致死"], collisions.map(row => [esc(fmtPhase(row.timeMs)), players(row.players), row.responsiblePlayer ? player(row.responsiblePlayer) : "无法唯一确定", players(row.deaths)]))}` : "";
  return `<section class="panel" data-analysis-option="manifestationsReviewEnabled"><h2>恐惧具象与凝视</h2><p class="muted">生成点来自日志。移动轨迹依据被点名玩家的面向推算，面对具象偏角在 30° 内时停止。</p>${collisionTable}${table(["玩家", "阶段", "开始", "结束", "NPC 实例", "具象坐标", "玩家坐标"], (fixations || []).map((row) => [player(row), esc(row.phase), esc(row.applyTime), esc(row.removeTime || "—"), esc(row.manifest?.sourceInstance ?? "—"), posLabel(row.manifestPosition), posLabel(row.playerPosition)]))}</section>`;
}
function nightfallInterrupt(row) {
  if (!row.interrupted) return '<span class="badge warn">无打断</span>';
  const who = row.interruptPlayer || { player: row.interruptSource };
  const spell = row.interruptSpellID ? ` ${spellLink(row.interruptSpellID, row.interruptSpell)}` : "";
  const when = row.interruptTime ? ` ${esc(row.interruptTime)}` : "";
  return `<span class="badge good">${player(who)}</span>${spell}${when}`;
}
function renderEternalNightfall(data) {
  const rounds = data?.rounds || [];
  return `<section class="panel" data-analysis-option="eternalNightfallReviewEnabled"><h2>永恒夜幕</h2><p class="muted">${esc(data?.evidenceNote || "先破盾再打断。")}</p>${rounds.length ? table(["轮次", "开始", "破盾", "打断", "读条完成"], rounds.map((row) => [`#${row.index}`, esc(row.time), row.shieldRemoved ? `<span class="badge good">${esc(row.shieldRemoveTime)}</span>` : '<span class="badge bad">未破盾</span>', nightfallInterrupt(row), row.castCompleted ? '<span class="badge bad">完成</span>' : '<span class="badge good">未完成</span>'])) : '<div class="empty">没有永恒夜幕记录。</div>'}</section>`;
}
function renderP1() {
  const data = boss();
  const sever = data.sever || {}, guillotine = data.guillotine || {};
  const rounds = sever.rounds || [];
  const paired = rounds.some((row) => row.mythicDelugePair);
  const note = paired ? `<p class="muted">${esc(sever.mythicPairing?.rule || "史诗下每两轮撕裂处理一轮剧毒洪流。默认第一下劈场地南侧，第二下劈场地北侧。")}</p>` : "";
  const headers = paired
    ? ["轮次", "时间", "清场侧", "洪流", "应清", "锥内", "未覆盖", "爆裂层数线索"]
    : ["轮次", "时间", "几何命中", "推断清理", "爆裂层数线索"];
  const body = rounds.map((row) => paired
    ? [`#${row.index}`, esc(row.time), ...mythicSeverCells(row), (row.ruptureEvents || []).length]
    : [`#${row.index}`, esc(row.time), row.clearedByGeometry, row.inferredClearedCount, (row.ruptureEvents || []).length]);
  return `${renderToxicDeluge(venomRoundsForPhase(data.toxicDeluge?.rounds, "p1"))}<section class="panel" data-analysis-option="severReviewEnabled"><h2>撕裂清场</h2>${note}${table(headers, body)}</section>${renderGuillotineTable("处斩分摊", guillotine)}`;
}
function renderP2() {
  const data = boss();
  const showResonance = Boolean(data.dreadmarch?.useMalevolentResonance);
  const collisionBadge = (row) => row.hitManifestation
    ? `<span class="badge bad">撞具象</span>${row.fixationDebuffChanged || row.manifestCollisionDebuff ? ' <span class="badge warn">debuff变化</span>' : ""}`
    : (row.triggerKind === "boss-cast" ? '<span class="badge">Boss点名</span>' : "—");
  const collisionHeaders = showResonance
    ? ["玩家", "时间", "轮次", "凝视变化", "恶毒共鸣"]
    : ["玩家", "时间", "轮次", "凝视变化"];
  const collisionRows = (data.dreadmarch?.manifestCollisions || []).map((row) => {
    const base = [player(row), esc(row.appliedTime), row.roundIndex ?? "—", row.fixationDebuffChanged ? "是" : "否"];
    if (showResonance) base.push(row.manifestCollisionDebuff ? "是" : "否");
    return base;
  });
  return `<section class="panel" data-analysis-option="dreadmarchReviewEnabled"><h2>恐惧行军</h2><p class="muted">救援以被控 debuff（1297445）移除为准。首次救人后至下一轮释放前再次被心控，记为撞到恐惧具象（可结合凝视变化${showResonance ? "；史诗另用恶毒共鸣印证" : ""}）。</p><p class="muted">${esc(data.dreadmarch?.evidenceNote || "")}</p>${table(["轮次", "时间", "点名人数", "成功救人", "失败", "撞具象"], (data.dreadmarch?.rounds || []).map((row) => [`#${row.index}${row.unassigned ? "（未对齐轮次）" : ""}`, esc(row.time), row.targetCount, row.rescuedCount, row.failedCount, row.manifestCollisionCount ?? 0]))}${table(["玩家", "轮次", "拾起", "解除", "来源", "结果"], (data.dreadmarch?.applications || []).map((row) => [player(row), row.roundIndex ?? "—", esc(row.appliedTime), esc(row.removedTime || "—"), collisionBadge(row), row.rescued ? '<span class="badge good">救出</span>' : row.diedWhileControlled ? '<span class="badge bad">控中死亡</span>' : '<span class="badge bad">未解除</span>']))}<h3>撞具象触发的恐惧行军</h3>${(data.dreadmarch?.manifestCollisions || []).length ? table(collisionHeaders, collisionRows) : '<div class="empty">本场没有记录到救人后的二次心控。</div>'}</section>${renderManifestations(phaseRows(data.manifestations?.fixations, "p2"))}<section class="panel" data-analysis-option="soulSeverReviewEnabled"><h2>灵魂撕裂</h2><p class="muted">具象取释放前位置；清掉=释放后短窗口内凝视移除；红线对应未消掉。</p>${table(["轮次", "时间", "释放前具象", "锥内", "debuff 清掉", "未消掉", "add 死亡"], (data.soulSever?.rounds || []).map((row) => [`#${row.index}`, esc(row.time), (row.nearbyPoints || []).length, row.clearedByGeometry, row.clearedByDebuff ?? "—", row.unclearedCount ?? "—", row.addDeathSignals]))}</section>${renderGloombomb(data.gloombomb, "p2")}<section class="panel" data-analysis-option="graveboundReviewEnabled"><h2>墓缚伤害致死</h2><p class="muted">只统计 1297906 直接致死；1286837 / 1308330 以及其他技能致死不计入。死亡时是否仍带墓缚仅作标注。</p>${table(["时间", "玩家", "致死技能", "当时带墓缚"], (data.graveboundFailures?.failures || []).map((row) => [esc(row.time), player(row), spellLink(row.deathAbilityID, row.deathAbility), row.graveboundActive ? '<span class="badge bad">是</span>' : '<span class="badge">否</span>']))}</section>${renderEternalNightfall(withPhaseRounds(data.eternalNightfall, "p2"))}`;
}
function renderIntermission() {
  const data = boss().intermission || {};
  if (!data.enabled) return `<section class="panel"><div class="empty">${esc(data.reason || "本场没有转阶段记录。")}</div></section>`;
  const leakCount = data.leakedSoulCount ?? data.leakCount ?? 0;
  const stepCount = data.spiritErasureStepCount ?? (data.spiritErasureSteps || []).length;
  const stepPlayer = (row) => (row.steppers || []).length ? players(row.steppers) : (row.player ? player(row) : "—");
  const potionBadge = (row) => row.potionUsed
    ? `<span class="badge good">${esc(row.potionName)}</span>`
    : '<span class="badge warn">未使用</span>';
  return `<section class="panel"><h2>被夺取的容器</h2><p class="muted">开始 ${esc(data.startTime)}，持续 ${esc(data.duration)}，漏掉灵魂 <b>${leakCount}</b>（收回精华 1287718），踩片 <b>${stepCount}</b></p><p class="muted">${esc(data.evidenceNote || "漏掉的灵魂=残片抵达祖尔加时的收回精华次数。灵魂抹除按全团脉冲合并，列出触发的友方。")}</p><h3>漏掉的灵魂（收回精华）</h3>${(data.leakedFragments || []).length ? table(["时间", "来源", "治疗量"], (data.leakedFragments || []).map((row) => [esc(row.time), esc(row.source || row.target || "—"), row.amount == null ? "—" : Number(row.amount).toLocaleString()])) : '<div class="empty">本场转阶段没有记录到收回精华，漏片为 0。</div>'}<h3>踩片（灵魂抹除）</h3>${(data.spiritErasureSteps || []).length ? table(["时间", "踩片玩家", "全团命中"], (data.spiritErasureSteps || []).map((row) => [esc(row.time), stepPlayer(row), row.hitCount ?? "—"])) : '<div class="empty">本场转阶段没有灵魂抹除脉冲。</div>'}<h3>爆发药水与对祖尔加伤害</h3><p class="muted">转阶段开始时存活的非治疗（含战复） ${data.survivorCount ?? (data.survivors || []).length} 人，已用爆发药水 ${data.potionUsedCount ?? 0}，对祖尔加合计 ${num(data.zuljanDamageTotal)}</p>${table(["玩家", "爆发药水", "使用时间", "对祖尔加伤害", "占比"], (data.survivors || []).filter((row) => !String(row.role || "").includes("healer")).map((row) => [player(row), potionBadge(row), esc(row.potionTime || "—"), num(row.zuljanDamage), row.zuljanPercent == null ? "—" : `${row.zuljanPercent}%`]))}</section>`;
}
function renderP3() {
  const data = boss();
  const blighted = data.blightedSever || {};
  return `<section class="panel" data-analysis-option="blightedSeverReviewEnabled"><h2>凋零撕裂（P3 组合清场）</h2><p class="muted">具象是否消除以凝视 debuff 在凋零撕裂后短窗口内是否消失为准；红线只连未消掉的玩家。</p>${table(["轮次", "时间", "几何命中", "debuff 清掉", "未消掉", "推断清理"], (blighted.rounds || []).map((row) => [`#${row.index}`, esc(row.time), row.clearedByGeometry, row.clearedByDebuff ?? "—", row.unclearedCount ?? "—", row.inferredClearedCount]))}${renderMythicVenomSeverTable(blighted.rounds)}</section>${renderGuillotineTable("冷酷处斩", data.grimGuillotine)}${renderGloombomb(data.gloombomb, "p3")}${renderToxicDeluge(venomRoundsForPhase(data.toxicDeluge?.rounds, "p3"))}${renderManifestations(phaseRows(data.manifestations?.fixations, "p3"))}${renderEternalNightfall(withPhaseRounds(data.eternalNightfall, "p3"))}`;
}
function diagramHasContent(diagram) {
  if (!diagram) return false;
  if ((diagram.targets || []).some((row) => row.position || row.manifestPosition || row.playerPosition)) return true;
  if ((diagram.nearbyPlayers || []).some((row) => row.position)) return true;
  if ((diagram.links || []).length) return true;
  if (diagram.origin && (Number.isFinite(Number(diagram.facingRadians)) || diagram.tankPosition || (diagram.conePolygon || []).length >= 3)) return true;
  if (diagram.kind === "runout" && diagram.origin) return true;
  return false;
}
function firstDiagramIndex(diagrams) {
  const index = (diagrams || []).findIndex(diagramHasContent);
  return index >= 0 ? index : 0;
}
function renderLinkOverlay(links, arena) {
  const segments = (links || []).map((row) => {
    const from = pct(row.from, arena);
    const to = pct(row.to, arena);
    if (!from || !to) return "";
    return `<line class="${esc(row.kind || "fixation")}" x1="${from.left}" y1="${from.top}" x2="${to.left}" y2="${to.top}"></line>`;
  }).filter(Boolean);
  if (!segments.length) return "";
  return `<svg class="link-map" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${segments.join("")}</svg>`;
}
function rosterPlayer(row) {
  const roster = current()?.players || [];
  const id = row?.playerID;
  const hit = id == null
    ? null
    : roster.find((player) => player.id === id || player.playerID === id);
  if (!hit) return row || {};
  const localization = hit.localization || {};
  return {
    ...hit,
    ...row,
    player: row.player || hit.name || hit.player,
    classColor: row.classColor || hit.classColor,
    icon: row.icon || hit.icon,
    role: row.role || hit.role,
    specID: row.specID || hit.specID,
    specName: row.specName || localization.spec?.zhCN,
    className: row.className || localization.class?.zhCN,
  };
}
function roleLabel(role) {
  const key = String(role || "");
  if (key === "tank") return "坦克";
  if (key.includes("healer")) return "治疗";
  if (key.includes("dps") || key === "Damage") return "输出";
  return "";
}
function specLabel(row) {
  if (row?.specName && row?.className) return `${row.specName}${row.className}`;
  return row?.specName || row?.className || "";
}
function fieldIcons() {
  return boss().fieldAudit?.icons || state.payload?.meta?.fieldIcons || {
    zuljan: "boss_plugins/assets/Zul'jan.png",
    malacrass: "boss_plugins/assets/HexLord_Malacrass.png",
    poisonOrb: "boss_plugins/assets/poison_orb.png",
    manifestation: "boss_plugins/assets/Manifestation_Dread.png",
  };
}
function isP2Phase(phase) {
  const key = String(phase || "").toLowerCase();
  return key.includes("p2") || key.includes("篡");
}
function bossIconUrl(diagram) {
  const icons = fieldIcons();
  return (isP2Phase(diagram?.phase) ? icons.malacrass : icons.zuljan) || "";
}
function bossIconName(diagram) {
  return isP2Phase(diagram?.phase) ? "玛拉卡斯" : "祖尔加";
}
function npcIconUrl(cls) {
  const icons = fieldIcons();
  if (cls === "manifest") return icons.manifestation || "";
  if (["venom", "venom-spawn", "virulent-mutation", "virulent-mutation-spawn", "ground-venom", "dropped-venom"].includes(cls)) {
    return icons.poisonOrb || "";
  }
  return "";
}
function assetFace(url, alt) {
  return url ? `<span class="spec-face"><img src="${encodeURI(url)}" alt="${esc(alt || "")}"></span>` : "";
}
function bossMarker(p, diagram, extraTitle) {
  const name = bossIconName(diagram);
  const title = extraTitle ? `${name}，${extraTitle}` : name;
  const url = bossIconUrl(diagram);
  const img = url ? `<img src="${encodeURI(url)}" alt="${esc(name)}">` : "";
  return `<span class="boss-center" title="${esc(title)}" style="left:${p.left}%;top:${p.top}%">${img}</span>`;
}
function specIconUrl(row) {
  const slug = row?.icon;
  if (!slug) return "";
  const name = String(slug);
  if (name.startsWith("/")) return name;
  if (name.startsWith("assets/")) return `/${name}`;
  return `/assets/specs/${name}.jpg`;
}
function playerHoverCard(row, extra) {
  const color = row?.classColor || "#fff";
  const spec = specLabel(row);
  const role = roleLabel(row?.role);
  const bits = [spec, role].filter(Boolean);
  return `<span class="player-tip"><b style="color:${color}">${esc(row?.player || "未知玩家")}</b>${bits.length ? `<span>${esc(bits.join("，"))}</span>` : ""}${extra ? `<span>${esc(extra)}</span>` : ""}</span>`;
}
function playerTokenExtra(cls, row) {
  if (cls === "manifest-target") {
    return row.uncleared === false ? "被恐惧具象点名" : "被恐惧具象点名，凝视未消掉";
  }
  if (cls === "bomb") return "幽暗炸弹点名";
  if (cls === "bomb-splash" || cls === "bomb-nearby") {
    const dist = row.distanceYards != null ? `，${row.distanceYards} 码` : "";
    return `幽暗炸弹误伤墓缚${dist}`;
  }
  if (cls === "share" || cls === "guillotine-share") return "处斩分摊";
  if (cls === "inside" || cls === "guillotine-inside") return "处斩时仍在圈内";
  if (cls === "tank") return "当前坦克";
  return "";
}
function isPlayerToken(row, cls) {
  if (["manifest", "venom", "venom-spawn", "virulent-mutation", "virulent-mutation-spawn", "ground-venom", "dropped-venom", "soulcoiler", "soulcoiler-prev"].includes(cls)) return false;
  if (cls === "tank" && !row?.playerID && !row?.icon) return false;
  return Boolean(row && (row.playerID || row.icon || ["manifest-target", "bomb", "bomb-splash", "bomb-nearby", "share", "inside"].includes(cls)));
}
function fieldMarker(row, p, cls, label) {
  if (isPlayerToken(row, cls)) {
    const info = rosterPlayer(row);
    const url = specIconUrl(info);
    const extra = playerTokenExtra(cls, row);
    const color = info.classColor || "#fff";
    const face = url
      ? `<span class="spec-face"><img src="${esc(url)}" alt="${esc(info.player || "")}"></span>`
      : "";
    return `<span class="marker spec-token ${cls}" style="left:${p.left}%;top:${p.top}%;--color:${color}">${face}${playerHoverCard(info, extra)}</span>`;
  }
  const npcUrl = npcIconUrl(cls);
  if (npcUrl) {
    return `<span class="marker spec-token ${cls}" title="${esc(label)}" style="left:${p.left}%;top:${p.top}%">${assetFace(npcUrl, label)}</span>`;
  }
  return `<span class="marker ${cls}" title="${esc(label)}" style="left:${p.left}%;top:${p.top}%"></span>`;
}
function fieldMap(data, diagram) {
  const arena = data.arena;
  if (!arena || !diagram) return '<div class="empty">缺少场地示意图数据。</div>';
  const bg = data.arenaImage || state.payload?.meta?.arenaImage;
  const squareW = Number(arena.plotScaleX || 25.9389) * 2, squareH = Number(arena.plotScaleY || 46.3327) * 2;
  const square = `<span class="arena-square" title="${Number(arena.sideYards || 110)} 码正方形场地" style="width:${squareW}%;height:${squareH}%"></span>`;
  const bossDot = diagram.kind === "cone-clear" ? "" : (() => {
    const pos = diagram.bossPosition;
    const p = pct(pos, arena);
    return p ? bossMarker(p, diagram, posLabel(pos, arena)) : "";
  })();
  const markers = (diagram.targets || []).map((row) => {
    const position = row.kind === "manifestation" ? (row.manifestPosition || row.position) : (row.position || row.manifestPosition);
    const p = pct(position, arena);
    if (!p) return "";
    const cls = row.kind === "soulcoiler" || row.kind === "soulcoiler-prev"
      ? row.kind
      : diagram.mechanic?.includes("炸弹")
      ? (row.kind === "bomb-splash" ? "bomb-splash" : row.kind === "bomb-nearby" ? "bomb-nearby" : "bomb")
      : row.kind === "tank"
        ? "tank"
        : row.kind === "guillotine-inside"
          ? "inside"
          : row.kind === "guillotine-share"
            ? "share"
            : row.kind === "manifestation" || row.kind === "manifest"
              ? "manifest"
              : row.kind === "manifest-target"
                ? "manifest-target"
                : row.kind === "venom-spawn"
                  ? "venom-spawn"
                  : row.kind === "virulent-mutation-spawn"
                    ? "virulent-mutation-spawn"
                    : row.kind === "virulent-mutation" || row.venomKind === "virulent-mutation"
                      ? "virulent-mutation"
                      : row.kind === "ground-venom" || row.kind === "dropped-venom"
                        ? "venom"
                        : "venom";
    const markerClass = row.assignedSide && row.inCone === false ? `${cls} miss` : cls;
    const label = row.kind === "manifestation"
      ? `恐惧具象，${row.player || ""}`
      : row.kind === "manifest-target"
        ? `被点名，${row.player || ""}`
        : row.venomKind === "virulent-mutation" || String(row.kind || "").includes("virulent")
          ? `烈毒变异体${row.assignedSideLabel ? `，${row.assignedSideLabel}` : ""}${row.assignedSide && row.inCone === false ? "，未进锥" : ""}，${row.player || ""}`
          : row.kind === "soulcoiler"
            ? `${row.player || "怨毒盘魂者"}，盾 ${row.shieldStacks ?? "?"}，命中 ${row.bombHits ?? 0}${row.displacedMiss ? "，打断炸空" : ""}`
            : row.kind === "soulcoiler-prev"
              ? "怨毒盘魂者打断前位置"
              : `${row.player || row.carrier || row.kind || ""}${row.assignedSideLabel ? `，${row.assignedSideLabel}` : ""}${row.assignedSide && row.inCone === false ? "，未进锥" : ""}`;
    return fieldMarker(row, p, markerClass, label);
  }).join("");
  const links = renderLinkOverlay(diagram.links, arena);
  const spread = diagram.kind === "spread" ? (diagram.targets || []).filter((row) => row.kind !== "soulcoiler" && row.kind !== "soulcoiler-prev").map((row) => {
    const p = pct(row.position, arena);
    const size = pctSize(diagram.spreadRadiusYards || 15, arena);
    return p ? `<span class="spread-target" style="left:${p.left}%;top:${p.top}%;width:${size.width * 2}%;height:${size.height * 2}%"></span>` : "";
  }).join("") : "";
  const nearbyActors = diagram.kind === "spread" ? (diagram.nearbyPlayers || []).filter((row) => row.receivedGravebound !== false).map((row) => {
    const p = pct(row.position, arena);
    if (!p) return "";
    return fieldMarker(row, p, "bomb-splash", `误伤墓缚，${row.player || ""}`);
  }).join("") : "";
  const runout = diagram.kind === "runout" && diagram.origin
    ? rangeCircle(diagram.origin, diagram.dangerRadiusYards || 40, arena, "runout-range", `${diagram.dangerRadiusYards || 40} 码跑离圈`)
    : "";
  const cone = diagram.kind === "cone-clear" && diagram.origin ? renderConeOverlay(diagram, arena) : "";
  const mutationBlast = (diagram.targets || []).map((row) => {
    const yards = Number(row.blastRadiusYards || 0);
    if (!yards) return "";
    const position = row.position || row.manifestPosition;
    return rangeCircle(position, yards, arena, "mutation-blast", `烈毒变异体引爆 ${yards} 码`);
  }).join("");
  const legend = diagram.facingInferred
    ? '<p class="legend warn">锥形朝向为估算值，仅供示意。</p>'
    : diagram.facingRule === "tank-debuff"
      ? '<p class="legend">朝向按坦克获得易伤 debuff 时的位置锁定。</p>'
      : diagram.facingRule === "cast-last-second"
        ? '<p class="legend">朝向按读条最后一秒的坦克位置锁定。</p>'
        : "";
  const linkLegend = (diagram.links || []).length
    ? '<p class="legend">红线：本轮未消掉凝视的玩家 ↔ 恐惧具象（释放前位置）；具象用恐惧具象图标；圆形专精图标=玩家（悬停查看信息）。</p>'
    : (diagram.mechanic === "灵魂撕裂" || diagram.mechanic === "凋零撕裂")
      ? '<p class="legend">本轮凝视均已清掉或缺少坐标，无红线。</p>'
      : "";
  const nearbyLegend = diagram.kind === "spread"
    ? (diagram.targets || []).some((row) => row.kind === "soulcoiler")
      ? '<p class="legend">黄圈=幽暗炸弹 15 码；橙点=本轮两只怨毒盘魂者（爆炸时刻）。</p>'
      : '<p class="legend">黄圈=点名爆炸 15 码；圆形专精图标=点名玩家 / 误伤墓缚（悬停查看信息）。</p>'
    : "";
  const venomLegend = (diagram.targets || []).some((row) => Number(row.blastRadiusYards || 0) || row.venomKind === "virulent-mutation" || String(row.kind || "").includes("virulent"))
    ? '<p class="legend">绿边=凝结毒液；紫边=烈毒变异体；紫圈=最终落点 8 码引爆范围。</p>'
    : "";
  const sideLegend = (diagram.targets || []).some((row) => row.assignedSide)
    ? '<p class="legend">史诗清场：本图只画这一下应劈的一侧。红圈=应清但没有进入锥形。</p>'
    : "";
  const empty = !markers && !spread && !nearbyActors && !cone && !runout && !mutationBlast ? '<p class="legend">该轮次缺少可绘制的坐标样本。</p>' : "";
  return `<div class="replay-map" style="background-image:url('${esc(bg)}')">${square}${bossDot}${cone}${links}${spread}${nearbyActors}${runout}${mutationBlast}${markers}</div>${legend}${linkLegend}${nearbyLegend}${venomLegend}${sideLegend}${empty}<p class="muted">${esc(diagram.annotation || diagram.mechanic || "")}</p>`;
}
function fieldMechanicGroups(diagrams) {
  const groups = [];
  const indexByKey = new Map();
  (diagrams || []).forEach((row, index) => {
    const key = row.mechanic || "其他";
    if (!indexByKey.has(key)) {
      indexByKey.set(key, groups.length);
      groups.push({ key, mechanic: key, items: [] });
    }
    groups[indexByKey.get(key)].items.push({ row, index });
  });
  return groups;
}
function renderField() {
  const data = boss().fieldAudit || {}, diagrams = data.diagrams || [];
  if (!diagrams.length) return `<section class="panel"><div class="empty">本场没有可绘制的位置示意图。</div></section>`;
  if (!diagramHasContent(diagrams[state.diagram])) state.diagram = firstDiagramIndex(diagrams);
  if (state.diagram >= diagrams.length) state.diagram = 0;
  const activeMechanic = diagrams[state.diagram]?.mechanic || "其他";
  if (state.fieldOpen[activeMechanic] == null) state.fieldOpen[activeMechanic] = true;
  const panels = fieldMechanicGroups(diagrams).map((group) => {
    const open = Boolean(state.fieldOpen[group.key]);
    const items = group.items.map(({ row, index }) => {
      const active = index === state.diagram;
      return `<article class="field-diagram-item ${active ? "active" : ""}"><button type="button" class="round-button ${active ? "active" : ""}" data-diagram="${index}"><b>#${row.roundIndex}</b><div>${esc(row.time)}，${esc(row.phase)}${row.assignedSideLabel ? `，${esc(row.assignedSideLabel)}` : ""}</div></button>${active && open ? `<div class="field-diagram-map">${fieldMap(data, row)}</div>` : ""}</article>`;
    }).join("");
    return `<details class="field-mechanic-panel" data-mechanic="${esc(group.key)}"${open ? " open" : ""}><summary><span class="field-mechanic-title">${esc(group.mechanic)}</span><span class="muted">${group.items.length} 轮</span></summary><div class="field-diagram-list">${items}</div></details>`;
  }).join("");
  setTimeout(() => {
    document.querySelectorAll("[data-diagram]").forEach((button) => {
      button.onclick = () => {
        const next = Number(button.dataset.diagram);
        state.fieldOpen[diagrams[next]?.mechanic || "其他"] = true;
        state.diagram = next;
        renderContent();
      };
    });
    document.querySelectorAll(".field-mechanic-panel").forEach((panel) => {
      panel.addEventListener("toggle", () => {
        state.fieldOpen[panel.dataset.mechanic] = panel.open;
      });
    });
  }, 0);
  return `<section class="panel"><h2>场地示意图</h2><p class="muted">${esc(data.evidenceNote || "")}</p><p class="muted">按技能收起或展开；点开某一轮查看该次示意图。</p><div class="field-mechanic-groups">${panels}</div></section>`;
}
function renderHoldEvidence(phase,threshold) {
  if(!phase.healthSampleCount)return '<p class="muted">缺少 Boss 血量采样，无法计算低血量施法，不能视为零次。</p>';
  const sort=state.holdSorts?.[phase.phase]||{key:'damage',direction:'desc'};
  const rows=window.CoiledAltarGuildView.sortHoldRows(phase.thresholds?.[String(threshold)]||[],sort.key,sort.direction);
  const holdWindow=phase.thresholdWindows?.[String(threshold)];
  const range=phase.phase!=='p1'?'':holdWindow?`<p class="muted">统计窗口：${holdWindow.startTimeMs==null?`截至 ${fmtPhase(holdWindow.endTimeMs)} 未见 Boss 低于 ${threshold}%`:`${fmtPhase(holdWindow.startTimeMs)}（首次低于 ${threshold}%）→ ${fmtPhase(holdWindow.endTimeMs)} 之前`}${holdWindow.evidenceEndTimeMs<holdWindow.endTimeMs?`；本场实际取证截至 ${fmtPhase(holdWindow.evidenceEndTimeMs)}`:''}。放行后的施法与伤害不计入。</p>`:'<p class="error">旧报告未按 2:45 截断停手统计，请重新分析或导入更新后的报告。</p>';
  return range+`<div class="hold-sort"><label>排序 <select data-hold-sort="${esc(phase.phase)}" aria-label="${esc(phase.phase.toUpperCase())} 停手排序维度">${[['damage','总伤害（含宠物）'],['playerDamage','玩家本体伤害'],['castCount','Boss 目标施法次数'],['petDamage','宠物伤害'],['player','玩家姓名']].map(([key,label])=>`<option value="${key}" ${sort.key===key?'selected':''}>${label}</option>`).join('')}</select></label><select data-hold-direction="${esc(phase.phase)}" aria-label="${esc(phase.phase.toUpperCase())} 停手排序方向"><option value="desc" ${sort.direction==='desc'?'selected':''}>降序</option><option value="asc" ${sort.direction==='asc'?'selected':''}>升序</option></select></div>`+
    table(['玩家','Boss 目标施法次数','总伤害（含宠物）','玩家本体伤害','其中宠物伤害','施法时间'],rows.map(row=>[player(row),num(row.castCount),num(row.damage),num(Number(row.damage||0)-Number(row.petDamage||0)),num(row.petDamage),(row.casts||[]).length?`<details><summary>${row.casts.length} 条施法</summary>${row.casts.map(c=>`${fmtPhase(c.timeMs)} ${spellLink(c.spellID)}`).join('<br>')}</details>`:'—']));
}
const BURST_COLORS=['#70d9ef','#ffcf6b','#c7a0ff','#8de2a6','#ff9fae','#e9b780'];
function renderBurstChart(data) {
  return data.timelineViewVersion==='icons-v1'?'<div data-icon-timeline></div>':renderLegacyBurstChart(data);
}
function mountGuildIconTimeline(){
  const data=boss().guildTimeline;if(data?.timelineViewVersion!=='icons-v1')return;
  state.iconTimeline??={};
  $('content').querySelectorAll('[data-icon-timeline]').forEach(host=>window.CoiledAltarIconTimeline?.mount(host,data,{pull:current(),pulls:state.pulls,scope:state.burstScope||'dps',state:state.iconTimeline}));
}
function renderLegacyBurstChart(data) {
  const duration=Math.max(data.durationMs||1,1),x=t=>Math.max(0,Math.min(1000,t/duration*1000));
  const phases=window.CoiledAltarGuildView.phaseTimings(data);
  const colors=['#233650','#174b51','#5b4326','#452f58'];
  const bg=phases.map((p,i)=>`<rect x="${x(p.timeMs)}" width="${Math.max(0,x(phases[i+1]?.timeMs??duration)-x(p.timeMs))}" height="30" fill="${colors[i%4]}" opacity=".6"><title>${esc(p.label+'；'+(p.advanceNote||'未确认时间轴提前'))}</title></rect>`).join('');
  const ticks=[];for(let t=0;t<duration;t+=60000)ticks.push(t);ticks.push(duration);
  const grid=ticks.map(t=>`<path d="M ${x(t)} 0 V 30" stroke="#ffffff" opacity=".12"/>`).join('');
  const axis=phases.map((p,i)=>`<rect x="${x(p.timeMs)}" width="${Math.max(0,x(phases[i+1]?.timeMs??duration)-x(p.timeMs))}" height="42" fill="${colors[i%4]}"><title>${esc(p.advanceNote||'未确认时间轴提前')}</title></rect><text x="${x(p.timeMs)+4}" y="10">${esc(({p1:'P1',p2:'P2',intermission:'P2.5',p3:'P3'})[p.key]||p.label)}</text><text class="phase-advance" x="${x(p.timeMs)+4}" y="23"><title>${esc(p.advanceNote)}</title>${esc(x(phases[i+1]?.timeMs??duration)-x(p.timeMs)<120&&p.advanceLabel?'早'+((p.endAdvanceMs||p.firstDreadmarchAdvanceMs||p.startAdvanceMs)/1000).toFixed(1)+'秒':p.advanceLabel)}</text>`).join('')+
    ticks.filter(t=>t===duration||duration-t>20000).map(t=>`<text x="${x(t)}" y="39" text-anchor="${t===0?'start':t===duration?'end':'middle'}">${fmtPhase(t)}</text>`).join('');
  const groups=window.CoiledAltarGuildView.groupBurstRows(data.timelines||[],current()?.players||[],data.unresolved||[],state.burstScope||'dps');
  return `<div class="burst-chart-scroll"><div class="burst-chart"><div class="burst-axis"><span>玩家 / 技能<br><small>阶段提前量见色块</small></span><svg viewBox="0 0 1000 44" preserveAspectRatio="none" role="img" aria-label="阶段时间轴与提前秒数">${axis}</svg></div>${groups.map(row=>{
    const skills=row.skills,step=24/Math.max(1,skills.length);
    const marks=skills.map((skill,i)=>{
      const color=BURST_COLORS[i%BURST_COLORS.length],y=4+i*step,h=Math.min(5,step-1),tip=label=>esc(skill.label+'，'+label);
      const windows=(skill.windows||[]).filter(w=>w.startTimeMs<=duration).map(w=>`<rect x="${x(w.startTimeMs)}" y="${y}" width="${Math.max(1,x(w.endTimeMs)-x(w.startTimeMs))}" height="${h}" fill="${w.counted?'#ff647c':color}" fill-opacity=".15" stroke="${w.counted?'#ff647c':color}" stroke-width=".6" stroke-dasharray="2 2"><title>${tip(`要求 ${fmtPhase(w.startTimeMs)}–${fmtPhase(w.endTimeMs)}；${w.reason||''}`)}</title></rect>`).join('');
      const effectIntervals=!data.evidenceVersion&&['mage.arcane-surge','evoker.breath-of-eons','mage.ray-of-frost'].includes(skill.ability)?[]:skill.intervals||[];
      const intervals=effectIntervals.map(a=>`<rect x="${x(a.startTimeMs)}" y="${y}" width="${Math.max(1,x(a.endTimeMs)-x(a.startTimeMs))}" height="${h}" fill="${color}"><title>${tip(`${fmtPhase(a.startTimeMs)}–${fmtPhase(a.endTimeMs)}，${a.evidence==='configured-estimate'?'配置时长示意':a.evidence?.startsWith('enemy-debuff')?'敌方减益 '+(a.target||'目标'):'自身增益'}${a.evidence?.endsWith('-truncated')?'（战斗结束截断）':''}`)}</title></rect>`).join('');
      const casts=(skill.casts||[]).map(t=>`<path d="M ${x(t)} ${y-1} V ${y+h+1}" stroke="${color}" stroke-width="2"><title>${tip(`${fmtPhase(t)} 实际施法`)}</title></path>`).join('');
      return windows+intervals+casts;
    }).join('');
    const note=row.unresolved.map(r=>r.reason).join('；')||'未配置爆发安排，仅展示本场角色';
    const count=(data.players||[]).find(p=>String(p.playerID)===String(row.playerID))?.count||0;
    return `<div class="burst-player-row" data-burst-player="${esc(row.playerID??row.player)}"><div class="burst-player-label">${player(row)}${count?`<b class="burst-count">${count}</b>`:''}<div class="burst-skill-key" title="${esc(skills.length?skills.map(s=>s.label).join('、'):note)}">${skills.length?skills.map((s,i)=>`<span style="--skill:${BURST_COLORS[i%BURST_COLORS.length]}">${esc(s.label)}</span>`).join(''):`<span>${esc(note)}</span>`}</div></div><svg viewBox="0 0 1000 30" preserveAspectRatio="none" role="img" aria-label="${esc(row.player+' 全部技能爆发时间轴')}">${bg}${grid}${marks}${skills.length?'':`<text x="8" y="19">${esc(note)}</text>`}</svg></div>`;
  }).join('')||'<p class="muted">没有可展示的 DPS 角色。</p>'}</div></div>`;
}
function renderGuildTimeline() {
  const data=boss().guildTimeline;
  if(data?.enabled && data.checksEnabled===false){
    const scopeOptions=`<option value="dps" ${state.burstScope!=='all'?'selected':''}>全部 DPS</option><option value="all" ${state.burstScope==='all'?'selected':''}>全部角色</option>`;
    return `<section class="panel burst-panel"><div class="burst-toolbar"><h2>玩家施法与Boss机制</h2><label>展示 <select data-burst-scope aria-label="施法轴展示角色">${scopeOptions}</select></label><button class="button" type="button" data-burst-focus>专注查看</button></div><p class="muted">${esc(data.evidenceNote)}</p><div data-icon-home><div data-burst-chart>${renderBurstChart(data)}</div></div></section><dialog class="burst-focus" aria-label="施法轴专注查看"><div class="burst-toolbar"><h2>实际施法时间轴</h2><label>展示 <select data-burst-scope>${scopeOptions}</select></label><button class="button" type="button" data-burst-close>关闭专注查看</button></div><div data-icon-focus-target></div></dialog>`;
  }
  if(!data||(data.enabled&&!data.phaseControl?.some(p=>p.phase==='p1'&&p.firstDreadmarchEarliestTimeMs!=null)))return '<section class="panel"><h2>公会战术核对：停手与爆发轴</h2><p>这份报告由旧版分析生成，尚未包含当前规则所需的数据。请使用 1.5 重新分析整晚日志；刷新页面不会补出缺失的取证数据。</p><p>P1 要求至少 2:50，首次恐惧行军至少 3:05 开始读条。重新分析后，在本页 P1 / P2 停手核对中调整 1%–10% 血量滑块；整晚合计位于概览的“机制统计”。</p><a class="button" href="/online">重新分析日志</a></section>';
  if(!data.enabled)return `<section class="panel"><h2>公会战术核对</h2><p>${esc(data.reason||'当前使用基础分析；专属判断仅用于阿瓦隆史诗数据。')}</p><p>${esc(data.analysisProfile?.reason||'')}</p></section>`;
  const status={early:'时间轴提前','on-time':'已满足时间要求','in-progress':'本阶段尚未结束',unreached:'未进入',unknown:'缺少确认事件'};
  const controls=(data.phaseControl||[]).map(phase=>{
    const threshold=state.holdThresholds?.[phase.phase]??data.defaultThreshold??5;
    return `<article class="panel"><h3>${esc(phase.phase.toUpperCase())} 停手核对 <span class="badge ${phase.status==='early'?'bad':'good'}">${esc(status[phase.status]||phase.status)}</span></h3>
      <p>最早结束 ${fmtPhase(phase.earliestEndTimeMs)}；实测末轮刀 ${phase.requiredBladeTimeMs==null?'未确认':fmtPhase(phase.requiredBladeTimeMs)}；Boss 到 1 血/死亡 ${phase.triggerTimeMs==null?'未记录':fmtPhase(phase.triggerTimeMs)}；下一阶段 ${phase.phaseEndTimeMs==null?'未进入':fmtPhase(phase.phaseEndTimeMs)}</p>
      ${phase.phase==='p1'?`<p>首次恐惧行军须在 ${fmtPhase(phase.firstDreadmarchEarliestTimeMs)} 或之后开始读条；实测 ${phase.firstDreadmarchTimeMs==null?'未记录':fmtPhase(phase.firstDreadmarchTimeMs)}</p>`:''}
      ${phase.status==='early'?'':'<p class="muted">本阶段未确认提前，以下仅供取证查看，不归责停手施法。</p>'}
      ${phase.status!=='unreached'?`<label class="hold-slider">Boss 血量低于 <output>${threshold}%</output><input data-hold-phase="${esc(phase.phase)}" type="range" min="1" max="10" step="1" value="${threshold}" aria-label="${phase.phase.toUpperCase()} 停手血量阈值"></label>
      <div data-hold-results="${esc(phase.phase)}">${renderHoldEvidence(phase,threshold)}</div>`:'<p class="muted">进入本阶段后可查看停手血量滑块。</p>'}
      ${phase.reason?`<p class="muted">${esc(phase.reason)}</p>`:''}</article>`;
  }).join('');
  const label={used:'按时使用',early:'提前使用',late:'延后使用',missing:'未使用','not-reached':'未走完窗口'};
  const checks=table(['玩家','技能','要求窗口','实际使用','上一次','下一次','结果','计数原因'],(data.checks||[]).map(row=>[player(row),esc(row.label),`${fmtPhase(row.startTimeMs)}–${fmtPhase(row.endTimeMs)}`,row.castTimeMs==null?'—':fmtPhase(row.castTimeMs),row.previousCastTimeMs==null?'—':fmtPhase(row.previousCastTimeMs),row.nextCastTimeMs==null?'—':fmtPhase(row.nextCastTimeMs),`<span class="badge ${row.counted?'bad':''}">${row.counted?'计 1 次：':''}${esc(label[row.status]||row.status)}</span>`,esc(row.reason)]));
  const potions=boss().intermission;
  const scopeOptions=`<option value="dps" ${state.burstScope!=='all'?'selected':''}>全部 DPS</option><option value="all" ${state.burstScope==='all'?'selected':''}>全部角色</option>`;
  const legend=data.timelineViewVersion==='icons-v1'?'':'<p class="burst-legend">旧版爆发轴，请导入更新后的报告查看图标、预定轴及 Boss 对照。</p>';
  return `<section class="panel burst-panel"><div class="burst-toolbar"><h2>爆发轴 <small>${data.burstSkipped?'已跳过计数':`标记 ${data.count} 次`}</small></h2><label>展示 <select data-burst-scope aria-label="爆发轴展示角色">${scopeOptions}</select></label><button class="button" type="button" data-burst-focus>专注查看</button></div>
    ${data.evidenceVersion?'':'<p class="burst-skip">这份旧报告缺少新版技能效果取证，请重新分析或导入更新后的报告；法师和亘古吐息暂只保留施法点，不显示旧持续条。</p>'}
    ${data.burstSkipped?`<p class="burst-skip">${esc(data.burstSkipReason)}</p>`:''}${legend}<div data-icon-home><div data-burst-chart>${renderBurstChart(data)}</div></div>
    <details class="burst-details"><summary>展开标记次数与逐条核对</summary>${table(['玩家','标记次数'],(data.players||[]).map(r=>[player(r),num(r.count)]))}${checks}</details></section>
    <dialog class="burst-focus" aria-label="全团爆发轴专注查看"><div class="burst-toolbar"><h2>全团爆发轴</h2><label>展示 <select data-burst-scope aria-label="专注查看角色">${scopeOptions}</select></label><button class="button" type="button" data-burst-close>关闭专注查看</button></div>${legend}${data.timelineViewVersion==='icons-v1'?'<div data-icon-focus-target></div>':`<div data-burst-chart>${renderBurstChart(data)}</div>`}</dialog>
    <details class="panel guild-evidence"><summary>阿瓦隆战术核对取证说明</summary><p>${esc(data.evidenceNote)}</p><p class="muted">${esc(data.analysisProfile?.reason)}</p></details>${controls}
    <details class="panel"><summary>当前系统固定轴与待确认项目</summary><p>图标轴的预定标记按原表绝对时间显示。逐条核对沿用按实际阶段平移后的判定窗口与容差，时间轴提前时不计漏爆发。原始固定轴如下。</p>
    ${table(['玩家','技能目录 key','固定秒数'],(data.plan||[]).map(r=>[esc(r.player),esc(r.label||r.ability||(r.spellIDs||[]).join('/')),r.times.map(t=>Array.isArray(t)?t.map(s=>fmtPhase(s*1000)).join('–'):fmtPhase(t*1000)).join('、')]))}
    ${(data.planNotes||[]).map(n=>`<p class="muted">${esc(n)}</p>`).join('')}
    ${table(['玩家','技能','未核对原因'],(data.unresolved||[]).map(r=>[esc(r.player),esc(r.ability),esc(r.reason)]))}</details>
    <section class="panel"><h2>易伤期爆发药水</h2>${potions?.enabled?table(['玩家','使用爆发药','使用时间'],(potions.survivors||[]).map(r=>[player(r),r.potionUsed?esc(r.potionName)+(r.potionPrecast?'（提前预开）':''):'未记录',esc(r.potionTime||'—')])):'<p class="muted">本场未进入易伤期，或未开启转阶段取证。</p>'}</section>`;
}

function renderContent() { $("content").querySelectorAll("[data-icon-timeline]").forEach(host=>host._iconTimeline?.destroy()); $("content").querySelectorAll(".mw").forEach(host=>host._workbench?.destroy()); let html = ""; if (state.tab === "guildTimeline") html=renderGuildTimeline(); else if (state.tab === "survival") html = renderSurvival(); else if (state.tab === "p1") html = renderP1(); else if (state.tab === "p2") html = renderP2(); else if (state.tab === "intermission") html = renderIntermission(); else if (state.tab === "p3") html = renderP3(); else if (state.tab === "field") html = renderField(); else if(state.tab==='replay')html='<div id="altarReplay"></div>'; $("content").innerHTML = html || '<div class="empty">该页暂无数据。</div>'; if(state.tab==='replay')window.CoiledAltarReplay?.mount($('altarReplay'),boss(),current()?.durationMs,p=>{const q=pct(p,boss().fieldAudit?.arena);return q&&{x:q.left,y:q.top};}); $("content").querySelectorAll('[data-analysis-option]').forEach(section => {
  if(state.payload?.meta?.analysisConfig?.[section.dataset.analysisOption] !== false) return;
  const heading = section.querySelector('h2')?.cloneNode(true);
  const note = document.createElement('p'); note.className = 'muted'; note.textContent = '本次未分析：已关闭此项目，不代表没有发生该机制。';
  section.replaceChildren(...(heading ? [heading, note] : [note]));
}); if(state.tab==="guildTimeline")mountGuildIconTimeline(); refreshWowhead(); }
$("content").addEventListener("input",event=>{const key=event.target.dataset.holdPhase;if(!key)return;state.holdThresholds??={};const value=Number(event.target.value);state.holdThresholds[key]=value;event.target.closest("label").querySelector("output").textContent=value+"%";const phase=boss().guildTimeline.phaseControl.find(p=>p.phase===key);$("content").querySelector(`[data-hold-results="${key}"]`).innerHTML=renderHoldEvidence(phase,value);refreshWowhead();});
$("content").addEventListener("change",event=>{
  const phaseKey=event.target.dataset.holdSort||event.target.dataset.holdDirection;
  if(phaseKey){
    state.holdSorts??={};const sort=state.holdSorts[phaseKey]??{key:'damage',direction:'desc'};
    if(event.target.dataset.holdSort)sort.key=event.target.value;else sort.direction=event.target.value;
    state.holdSorts[phaseKey]=sort;
    const phase=boss().guildTimeline.phaseControl.find(p=>p.phase===phaseKey),threshold=state.holdThresholds?.[phaseKey]??boss().guildTimeline.defaultThreshold??5;
    $("content").querySelector(`[data-hold-results="${phaseKey}"]`).innerHTML=renderHoldEvidence(phase,threshold);refreshWowhead();
  }
  if(event.target.hasAttribute('data-burst-scope')){
    state.burstScope=event.target.value;
    $("content").querySelectorAll('[data-burst-scope]').forEach(select=>select.value=state.burstScope);
    $("content").querySelectorAll('[data-icon-timeline]').forEach(host=>host._iconTimeline?.destroy());
    $("content").querySelectorAll('[data-burst-chart]').forEach(chart=>chart.innerHTML=renderBurstChart(boss().guildTimeline));
    mountGuildIconTimeline();
  }
});
$("content").addEventListener("click",event=>{
  if(event.target.closest('[data-burst-focus]')){
    const dialog=$('content').querySelector('.burst-focus'),target=dialog.querySelector('[data-icon-focus-target]'),chart=$('content').querySelector('[data-icon-home] [data-burst-chart]');
    if(target&&chart){target.append(chart);dialog.addEventListener('close',()=>{$('content').querySelector('[data-icon-home]')?.append(chart);},{once:true});}
    dialog.showModal();
  }
  if(event.target.closest('[data-burst-close]'))$("content").querySelector('.burst-focus').close();
});
function render() { renderStats(); renderTabs(); renderContent(); }
function load(payload) { state.payload = payload; state.pulls = [...(payload.data?.page1_wipeAnalysis || [])].sort((a, b) => String(b.startTimeIso || `${b.date || ""}${b.fightID || ""}`).localeCompare(String(a.startTimeIso || `${a.date || ""}${a.fightID || ""}`))); const fight = Number(new URLSearchParams(location.search).get("fight")); const index = state.pulls.findIndex((row) => Number(row.fightID) === fight); state.pull = index >= 0 ? index : 0; state.tab = new URLSearchParams(location.search).get("tab") || (payload.meta?.tabDefinitions || [])[0]?.key || "survival"; state.diagram = firstDiagramIndex(boss().fieldAudit?.diagrams || []); $("pullSelect").innerHTML = state.pulls.map((row, index) => `<option value="${index}">Fight ${row.fightID}，${esc(row.date || "")} ${esc(row.startClock || "")}，${esc(row.difficultyName || "未知")}，${row.isKill ? "KILL" : `${Number(row.bossPercentage).toFixed(2)}%`}，${esc(row.duration)}</option>`).join(""); $("pullSelect").value = String(state.pull); $("error").textContent = state.pulls.length ? "" : "分析结果中没有该 Boss 战斗。"; render(); }
$("pullSelect").onchange = (event) => { state.pull = Number(event.target.value); state.holdThresholds={}; state.tab = state.tab==="guildTimeline"?"guildTimeline":(state.payload.meta?.tabDefinitions || [])[0]?.key || "survival"; state.diagram = firstDiagramIndex(boss().fieldAudit?.diagrams || []); render(); };
$("fileInput").onchange = async (event) => { try { load(await window.MythicReportRuntime.readLocalFile(event.target.files[0])); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
const path = new URLSearchParams(location.search).get("json"); state.sourcePath = path || ""; if (path) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(path)}`; if (path) window.MythicReportRuntime.loadPayload(path).then(load).catch((error) => ($("error").textContent = error.message)); else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
