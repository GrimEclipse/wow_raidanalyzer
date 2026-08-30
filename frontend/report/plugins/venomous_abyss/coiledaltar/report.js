const state = { payload: null, pulls: [], pull: 0, tab: "survival", sourcePath: "", diagram: 0 };
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => Number(v || 0).toLocaleString("zh-CN");
function current() { return state.pulls[state.pull] || null; }
function boss() { return current()?.coiledaltar || {}; }
function player(row) { return `<span class="player" style="color:${row?.classColor || "#fff"}">${esc(row?.player || row?.name || "—")}</span>`; }
function players(rows) { return (rows || []).map(player).join("、") || "—"; }
function spellLink(id, name) { return id ? `<a href="https://www.wowhead.com/cn/spell=${id}" data-wowhead="domain=cn&amp;spell=${id}" target="_blank" rel="noreferrer">${esc(name || "未知技能")}</a>` : esc(name || "—"); }
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
  const boss = `<span class="boss-center" title="Boss ${posLabel(origin, arena)}" style="left:${apex.left}%;top:${apex.top}%"></span>`;
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
function renderStats() { const pull = current(), survival = pull?.survival || {}; $("title").textContent = `盘卷祭坛 · Fight ${pull?.fightID || "-"}`; $("meta").textContent = `${pull?.difficultyName || "未知难度"} · ${pull?.isKill ? "击杀" : `Boss 剩余 ${Number(pull?.bossPercentage || 0).toFixed(2)}%`} · ${pull?.date || ""} ${pull?.startClock || ""}`; $("wclLink").href = pull?.wclDeepLink || "#"; const items = [["战斗时长", pull?.duration || "—"], ["结果", pull?.isKill ? "KILL" : `${Number(pull?.bossPercentage || 0).toFixed(2)}%`], ["难度", pull?.difficultyName || "未知"], ["阵亡", survival.deathCount || 0], ["战复", survival.combatResCount || 0], ["结束存活", `${survival.survivorCount || 0}/${survival.rosterCount || 0}`]]; $("stats").innerHTML = items.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join(""); }
function renderTabs() { const defs = state.payload?.meta?.tabDefinitions || [{ key: "survival", label: "全场存活情况" }]; if (!defs.some((row) => row.key === state.tab)) state.tab = defs[0].key; $("tabs").innerHTML = defs.map((row) => `<button data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join(""); document.querySelectorAll("[data-tab]").forEach((button) => (button.onclick = () => { state.tab = button.dataset.tab; renderContent(); renderTabs(); })); }
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
  return `<section class="panel"><h2>${esc(title)}</h2><p class="muted">${esc(evidence)}</p>${table(["轮次", "时间", "分摊人数", "参与者", insideCol], rounds.map((row) => [`#${row.index}`, esc(row.time), row.participantCount, players(row.participants), players(stillInsideRows(row).map((p) => ({ player: p.player, classColor: p.classColor })))]))}</section>`;
}
function renderP1() { const data = boss(); const deluge = data.toxicDeluge || {}, sever = data.sever || {}, guillotine = data.guillotine || {}; return `<section class="panel"><h2>剧毒洪流 · 凝结毒液搬运</h2><div class="cards">${(deluge.rounds || []).map((round) => `<article class="card"><h3>#${round.index} · ${esc(round.time)}</h3><h4>搬运者 / 落点</h4>${table(["玩家", "拾起", "掉落", "持有时长", "落点"], (round.carriers || []).map((row) => [player(row), esc(row.applyTime), esc(row.removeTime || "—"), row.carryDurationMs == null ? "—" : `${(row.carryDurationMs / 1000).toFixed(1)}s`, posLabel(row.dropPosition)]))}</article>`).join("") || '<div class="empty">没有剧毒洪流记录。</div>'}</div></section><section class="panel"><h2>撕裂清场</h2>${table(["轮次", "时间", "几何命中", "推断清理", "爆裂层数线索"], (sever.rounds || []).map((row) => [`#${row.index}`, esc(row.time), row.clearedByGeometry, row.inferredClearedCount, (row.ruptureEvents || []).length]))}</section>${renderGuillotineTable("处斩分摊", guillotine)}`; }
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
  return `<section class="panel"><h2>恐惧行军</h2><p class="muted">救援以被控 debuff（1297445）移除为准。首次救人后至下一轮释放前再次被心控，记为撞到恐惧具象（可结合凝视变化${showResonance ? "；史诗另用恶毒共鸣印证" : ""}）。</p><p class="muted">${esc(data.dreadmarch?.evidenceNote || "")}</p>${table(["轮次", "时间", "点名人数", "成功救人", "失败", "撞具象"], (data.dreadmarch?.rounds || []).map((row) => [`#${row.index}${row.unassigned ? "（未对齐轮次）" : ""}`, esc(row.time), row.targetCount, row.rescuedCount, row.failedCount, row.manifestCollisionCount ?? 0]))}${table(["玩家", "轮次", "拾起", "解除", "来源", "友方命中", "结果"], (data.dreadmarch?.applications || []).map((row) => [player(row), row.roundIndex ?? "—", esc(row.appliedTime), esc(row.removedTime || "—"), collisionBadge(row), row.friendlyHitCount ?? 0, row.rescued ? '<span class="badge good">救出</span>' : row.diedWhileControlled ? '<span class="badge bad">控中死亡</span>' : '<span class="badge bad">未解除</span>']))}<h3>撞具象触发的恐惧行军</h3>${(data.dreadmarch?.manifestCollisions || []).length ? table(collisionHeaders, collisionRows) : '<div class="empty">本场没有记录到救人后的二次心控。</div>'}</section><section class="panel"><h2>恐惧具象 / 凝视</h2><p class="muted">具象坐标为恐惧具象 NPC；玩家坐标为被凝视者。</p>${table(["玩家", "阶段", "开始", "结束", "NPC 实例", "具象坐标", "玩家坐标"], (data.manifestations?.fixations || []).map((row) => [player(row), esc(row.phase), esc(row.applyTime), esc(row.removeTime || "—"), esc(row.manifest?.sourceInstance ?? "—"), posLabel(row.manifestPosition), posLabel(row.playerPosition)]))}</section><section class="panel"><h2>灵魂撕裂</h2><p class="muted">具象取释放前位置；清掉=释放后短窗口内凝视移除；红线对应未消掉。</p>${table(["轮次", "时间", "释放前具象", "锥内", "debuff 清掉", "未消掉", "add 死亡"], (data.soulSever?.rounds || []).map((row) => [`#${row.index}`, esc(row.time), (row.nearbyPoints || []).length, row.clearedByGeometry, row.clearedByDebuff ?? "—", row.unclearedCount ?? "—", row.addDeathSignals]))}</section><section class="panel"><h2>幽暗炸弹分散</h2>${table(["轮次", "时间", "点名数", "过近组合"], (data.gloombomb?.rounds || []).map((row) => [`#${row.index}`, esc(row.time), row.targetCount, (row.tooClosePairs || []).map((pair) => `${esc(pair.left)}↔${esc(pair.right)} ${pair.distanceYards}码`).join("；") || "—"]))}</section><section class="panel"><h2>墓缚伤害致死</h2><p class="muted">仅统计收到墓缚伤害致死（1308330/1297906/1286837）；并标注死亡时是否仍带墓缚。</p>${table(["时间", "玩家", "致死技能", "当时带墓缚"], (data.graveboundFailures?.failures || []).map((row) => [esc(row.time), player(row), spellLink(row.deathAbilityID, row.deathAbility), row.graveboundActive ? '<span class="badge bad">是</span>' : '<span class="badge">否</span>']))}</section><section class="panel"><h2>永恒夜幕</h2>${table(["轮次", "开始", "破盾", "打断", "读条完成"], (data.eternalNightfall?.rounds || []).map((row) => [`#${row.index}`, esc(row.time), row.shieldRemoved ? `<span class="badge good">${esc(row.shieldRemoveTime)}</span>` : '<span class="badge bad">未破盾</span>', row.interrupted ? `<span class="badge good">${esc(row.interruptSource)}</span>` : '<span class="badge warn">无打断</span>', row.castCompleted ? '<span class="badge bad">完成</span>' : '<span class="badge good">未完成</span>']))}</section>`;
}
function renderIntermission() {
  const data = boss().intermission || {};
  if (!data.enabled) return `<section class="panel"><div class="empty">${esc(data.reason || "本场没有转阶段记录。")}</div></section>`;
  const leakCount = data.leakedSoulCount ?? data.leakCount ?? 0;
  return `<section class="panel"><h2>被夺取的容器</h2><p class="muted">开始 ${esc(data.startTime)} · 持续 ${esc(data.duration)} · 漏掉灵魂 <b>${leakCount}</b>（收回精华 1287718）</p><p class="muted">${esc(data.evidenceNote || "漏掉的灵魂=残片抵达祖尔加时的收回精华次数。")}</p><h3>漏掉的灵魂（收回精华）</h3>${(data.leakedFragments || []).length ? table(["时间", "来源", "治疗量"], (data.leakedFragments || []).map((row) => [esc(row.time), esc(row.source || row.target || "—"), row.amount == null ? "—" : Number(row.amount).toLocaleString()])) : '<div class="empty">本场转阶段没有记录到收回精华，漏片为 0。</div>'}<h3>踩片（灵魂抹除）</h3>${table(["时间", "玩家"], (data.spiritErasureSteps || []).map((row) => [esc(row.time), player(row)]))}</section>`;
}
function renderP3() { const data = boss(); return `<section class="panel"><h2>凋零撕裂（P3 组合清场）</h2><p class="muted">具象是否消除以凝视 debuff 在凋零撕裂后短窗口内是否消失为准；红线只连未消掉的玩家。</p>${table(["轮次", "时间", "几何命中", "debuff 清掉", "未消掉", "推断清理"], (data.blightedSever?.rounds || []).map((row) => [`#${row.index}`, esc(row.time), row.clearedByGeometry, row.clearedByDebuff ?? "—", row.unclearedCount ?? "—", row.inferredClearedCount]))}</section>${renderGuillotineTable("冷酷处斩", data.grimGuillotine)}`; }
function diagramHasContent(diagram) {
  if (!diagram) return false;
  if ((diagram.targets || []).some((row) => row.position || row.manifestPosition || row.playerPosition)) return true;
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
    return `<line x1="${from.left}" y1="${from.top}" x2="${to.left}" y2="${to.top}"></line>`;
  }).filter(Boolean);
  if (!segments.length) return "";
  return `<svg class="link-map" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${segments.join("")}</svg>`;
}
function fieldMap(data, diagram) {
  const arena = data.arena;
  if (!arena || !diagram) return '<div class="empty">缺少场地示意图数据。</div>';
  const bg = data.arenaImage || state.payload?.meta?.arenaImage;
  const squareW = Number(arena.plotScaleX || 25.9389) * 2, squareH = Number(arena.plotScaleY || 46.3327) * 2;
  const square = `<span class="arena-square" title="${Number(arena.sideUnits || arena.sideYards || 110)} 单位 / ${Number(arena.sideYards || 86)} 码正方形场地" style="width:${squareW}%;height:${squareH}%"></span>`;
  const bossDot = diagram.kind === "cone-clear" ? "" : (() => {
    const p = pct({ x: arena.centerX, y: arena.centerY }, arena);
    return p ? `<span class="boss-center" title="场地中心 (0, 1158)" style="left:${p.left}%;top:${p.top}%"></span>` : "";
  })();
  const markers = (diagram.targets || []).map((row) => {
    const position = row.kind === "manifestation" ? (row.manifestPosition || row.position) : (row.position || row.manifestPosition);
    const p = pct(position, arena);
    if (!p) return "";
                const cls = diagram.mechanic?.includes("炸弹")
      ? "bomb"
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
                  : row.kind === "ground-venom" || row.kind === "dropped-venom"
                    ? "venom"
                    : "venom";
    const label = row.kind === "manifestation"
      ? `恐惧具象 · ${row.player || ""}`
      : row.kind === "manifest-target"
        ? `被点名 · ${row.player || ""}`
        : (row.player || row.carrier || row.kind || "");
    return `<span class="marker ${cls}" title="${esc(label)}" style="left:${p.left}%;top:${p.top}%"></span>`;
  }).join("");
  const links = renderLinkOverlay(diagram.links, arena);
  const spread = diagram.kind === "spread" ? (diagram.targets || []).map((row) => {
    const p = pct(row.position, arena);
    const size = pctSize(diagram.spreadRadiusYards || 15, arena);
    return p ? `<span class="spread-target" style="left:${p.left}%;top:${p.top}%;width:${size.width * 2}%;height:${size.height * 2}%"></span><span class="actor" style="left:${p.left}%;top:${p.top}%;--color:${row.classColor || "#fff"}"><b>${esc(row.player)}</b></span>` : "";
  }).join("") : "";
  const runout = diagram.kind === "runout" && diagram.origin ? (() => {
    const actors = (diagram.targets || []).map((row) => {
      const p = pct(row.position, arena);
      return p ? `<span class="actor" style="left:${p.left}%;top:${p.top}%;--color:${row.classColor || "#fff"}"><b>${esc(row.player)}</b></span>` : "";
    }).join("");
    return `${rangeCircle(diagram.origin, diagram.dangerRadiusYards || 40, arena, "runout-range", `${diagram.dangerRadiusYards || 40} 码跑离圈`)}${actors}`;
  })() : "";
  const cone = diagram.kind === "cone-clear" && diagram.origin ? renderConeOverlay(diagram, arena) : "";
  const legend = diagram.facingInferred
    ? '<p class="legend warn">锥形朝向为估算值，仅供示意。</p>'
    : diagram.facingRule === "tank-debuff"
      ? '<p class="legend">朝向按坦克获得易伤 debuff 时的位置锁定。</p>'
      : diagram.facingRule === "cast-last-second"
        ? '<p class="legend">朝向按读条最后一秒的坦克位置锁定。</p>'
        : "";
  const linkLegend = (diagram.links || []).length
    ? '<p class="legend">红线：本轮未消掉凝视的玩家 ↔ 恐惧具象（释放前位置）；紫点=具象。</p>'
    : (diagram.mechanic === "灵魂撕裂" || diagram.mechanic === "凋零撕裂")
      ? '<p class="legend">本轮凝视均已清掉或缺少坐标，无红线。</p>'
      : "";
  const empty = !markers && !spread && !cone && !runout ? '<p class="legend">该轮次缺少可绘制的坐标样本。</p>' : "";
  return `<div class="replay-map" style="background-image:url('${esc(bg)}')">${square}${bossDot}${cone}${links}${spread}${runout}${markers}</div>${legend}${linkLegend}${empty}<p class="muted">${esc(diagram.annotation || diagram.mechanic || "")}</p>`;
}
function renderField() {
  const data = boss().fieldAudit || {}, diagrams = data.diagrams || [];
  if (!diagrams.length) return `<section class="panel"><div class="empty">本场没有可绘制的位置示意图。</div></section>`;
  if (!diagramHasContent(diagrams[state.diagram])) state.diagram = firstDiagramIndex(diagrams);
  if (state.diagram >= diagrams.length) state.diagram = 0;
  const items = diagrams.map((row, index) => {
    const active = index === state.diagram;
    return `<article class="field-diagram-item ${active ? "active" : ""}"><button type="button" class="round-button ${active ? "active" : ""}" data-diagram="${index}"><b>${esc(row.mechanic)} #${row.roundIndex}</b><div>${esc(row.time)} · ${esc(row.phase)}</div></button>${active ? `<div class="field-diagram-map">${fieldMap(data, row)}</div>` : ""}</article>`;
  }).join("");
  setTimeout(() => document.querySelectorAll("[data-diagram]").forEach((button) => {
    button.onclick = () => {
      const next = Number(button.dataset.diagram);
      state.diagram = next;
      renderContent();
    };
  }), 0);
  return `<section class="panel"><h2>场地示意图</h2><p class="muted">${esc(data.evidenceNote || "")}</p><div class="field-diagram-list">${items}</div></section>`;
}
function renderContent() { let html = ""; if (state.tab === "survival") html = renderSurvival(); else if (state.tab === "p1") html = renderP1(); else if (state.tab === "p2") html = renderP2(); else if (state.tab === "intermission") html = renderIntermission(); else if (state.tab === "p3") html = renderP3(); else if (state.tab === "field") html = renderField(); $("content").innerHTML = html || '<div class="empty">该页暂无数据。</div>'; refreshWowhead(); }
function render() { renderStats(); renderTabs(); renderContent(); }
function load(payload) { state.payload = payload; state.pulls = [...(payload.data?.page1_wipeAnalysis || [])].sort((a, b) => String(b.startTimeIso || `${b.date || ""}${b.fightID || ""}`).localeCompare(String(a.startTimeIso || `${a.date || ""}${a.fightID || ""}`))); const fight = Number(new URLSearchParams(location.search).get("fight")); const index = state.pulls.findIndex((row) => Number(row.fightID) === fight); state.pull = index >= 0 ? index : 0; state.tab = (payload.meta?.tabDefinitions || [])[0]?.key || "survival"; state.diagram = firstDiagramIndex(boss().fieldAudit?.diagrams || []); $("pullSelect").innerHTML = state.pulls.map((row, index) => `<option value="${index}">Fight ${row.fightID} · ${esc(row.date || "")} ${esc(row.startClock || "")} · ${esc(row.difficultyName || "未知")} · ${row.isKill ? "KILL" : `${Number(row.bossPercentage).toFixed(2)}%`} · ${esc(row.duration)}</option>`).join(""); $("pullSelect").value = String(state.pull); $("error").textContent = state.pulls.length ? "" : "分析结果中没有该 Boss 战斗。"; render(); }
$("pullSelect").onchange = (event) => { state.pull = Number(event.target.value); state.tab = (state.payload.meta?.tabDefinitions || [])[0]?.key || "survival"; state.diagram = firstDiagramIndex(boss().fieldAudit?.diagrams || []); render(); };
$("fileInput").onchange = async (event) => { try { load(JSON.parse(await event.target.files[0].text())); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
const path = new URLSearchParams(location.search).get("json"); state.sourcePath = path || ""; if (path) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(path)}`; if (path) window.MythicReportRuntime.loadPayload(path).then(load).catch((error) => ($("error").textContent = error.message)); else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
