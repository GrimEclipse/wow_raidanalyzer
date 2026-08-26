const state = { payload: null, pulls: [], pull: 0, tab: "helical", playerID: null, sourcePath: "" };
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));
const num = value => Number(value || 0).toLocaleString("zh-CN");

function current() { return state.pulls[state.pull] || null; }

function rosterPlayer(playerID, name) {
  const players = current()?.players || [];
  return players.find(player => String(player.id) === String(playerID))
    || players.find(player => player.name === name)
    || {};
}

function coloredPlayer(name, playerID) {
  const player = rosterPlayer(playerID, name);
  return `<span class="player-name" style="color:${player.classColor || "#fff"}">${esc(name)}</span>`;
}

function coloredPlayers(names, playerIDs) {
  return (names || []).map((name, index) => coloredPlayer(name, (playerIDs || [])[index])).join(" + ");
}

function simpleTable(headers, rows) {
  if (!rows.length) return '<div class="empty">没有对应记录。</div>';
  return `<table><thead><tr>${headers.map(item => `<th>${esc(item)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(item => `<td>${item ?? "—"}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderSummary() {
  const pull = current(), sentinels = pull?.sentinels || {};
  const helical = sentinels.helicalToxins || {}, water = sentinels.clingingMurk || {};
  const living = sentinels.livingVenom || {}, droplets = sentinels.toxicDroplets || {};
  const stats = [
    ["战斗", pull?.isKill ? "KILL" : `${Number(pull?.bossPercentage || 0).toFixed(2)}%`],
    ["时长", pull?.duration || "—"], ["静滞轮数", helical.roundCount || 0],
    ["错误碰撞", helical.wrongCollisionCount || 0], ["活体毒液", `${living.totalHits || 0} 次`],
    ["漏绿球 / 分摊", `${droplets.missedRoundCount || 0} / ${water.roundCount || 0}`]
  ];
  $("summary").innerHTML = stats.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  $("wclLink").href = pull?.wclDeepLink || "#";
}

function renderSurvival() {
  const survival = current()?.survival || {};
  $("content").innerHTML = `<section class="panel"><h2>死亡 / 战复时间线</h2><p class="muted">阵亡 ${survival.deathCount || 0} 次 · 战复 ${survival.combatResCount || 0} 次 · 战斗结束存活 ${survival.survivorCount || 0}/${survival.rosterCount || 0}</p>${simpleTable(["时间", "类型", "玩家", "原因 / 技能"], (survival.timeline || []).map(event => [esc(event.time), event.kind === "combat_res" ? '<span class="badge good">战复</span>' : '<span class="badge bad">死亡</span>', coloredPlayer(event.player, event.playerID), event.kind === "combat_res" ? `${esc(event.source)} 使用 ${esc(event.ability)}` : esc(event.ability)]))}</section>`;
}

function spellHeading(spellID, label) {
  return `<span class="spell-heading"><a class="spell-icon-link" href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;dd=15" data-wh-icon-size="small" target="_blank" rel="noreferrer"><span class="spell-icon-fallback">${spellID}</span></a><a href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;dd=15" target="_blank" rel="noreferrer">${esc(label)}</a></span>`;
}

function refreshWowhead() {
  if (window.WH?.Tooltips?.refreshLinks) window.WH.Tooltips.refreshLinks();
}

function enterPull(index) {
  state.pull = Math.max(0, Math.min(index, state.pulls.length - 1));
  state.playerID = null;
  state.tab = "helical";
  $("pullSelect").value = String(state.pull);
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function collisionDetail(collision) {
  const evidence = collision.pairingEvidence === "coordinates"
    ? `<span class="collision-evidence ${collision.positionConfidence === "reference" ? "reference" : ""}">${collision.positionConfidence === "reference" ? "坐标参考配对" : "坐标配对"}${collision.distanceYards == null ? "" : ` · ${collision.distanceYards}码`}</span>`
    : "";
  const header = `<div class="collision-main"><time>${esc(collision.time || "—")}</time><div class="collision-players">${coloredPlayers(collision.players, collision.playerIDs)}</div>`;
  if (collision.kind === "wrong-collision") {
    const movers = (collision.largeMovers || []).map(row => `<div class="movement-warning">${esc(row.player)}在最后一秒进行了大范围的移动（${row.movementYards}码）</div>`).join("");
    const movement = collision.movementEvidence;
    const movementPlayers = (movement?.players || []).map(row => `${coloredPlayer(row.player, row.playerID)} ${row.movementYards}码`).join(" · ");
    const pairDistance = movement?.pairDistanceBeforeYards == null || movement?.pairDistanceAtCollisionYards == null
      ? ""
      : `；两人间距 ${movement.pairDistanceBeforeYards}→${movement.pairDistanceAtCollisionYards}码`;
    const movementLine = movementPlayers ? `<div class="collision-movement">碰撞前 ${Number(movement.windowMs || 1000) / 1000} 秒位移：${movementPlayers}${pairDistance}</div>` : "";
    return `<div class="mechanic-cell wrong-cell ${collision.firstWrongCollision ? "first-wrong" : ""}">${header}<span class="badge bad">错误相撞</span></div><div class="collision-note">${esc(collision.collisionCombination || "组合待定")} → 两人均变为 ${collision.resultStack} 层</div>${movementLine}${collision.firstWrongCollision ? '<div class="first-wrong-label">本轮第一个错误碰撞</div>' : ""}${movers}</div>`;
  }
  if (collision.kind === "recovery-clear") return `<div class="mechanic-cell recovery-cell">${header}<span class="badge good">补救消除</span></div><div class="collision-note">${esc(collision.collisionCombination || "安全组合")} ${evidence}</div></div>`;
  if (collision.kind === "timeout-remove") return `<div class="mechanic-cell timeout-cell">${header}<span class="badge bad">超时移除</span></div></div>`;
  if (collision.kind === "unpaired-remove") return `<div class="mechanic-cell unresolved-cell">${header}<span class="badge warn">无法严谨配对</span></div></div>`;
  return "";
}

function roundMechanicCells(round) {
  const failures = round.failures || [], matchedFailures = new Set(), cells = [];
  for (const collision of round.collisions || []) {
    if (collision.kind === "safe-clear") {
      const evidence = collision.pairingEvidence === "coordinates"
        ? `<span class="collision-evidence ${collision.positionConfidence === "reference" ? "reference" : ""}">${collision.positionConfidence === "reference" ? "坐标参考配对" : "坐标配对"}${collision.distanceYards == null ? "" : ` · ${collision.distanceYards}码`}</span>`
        : "";
      cells.push(`<div class="mechanic-cell safe-cell"><div class="collision-main"><time>${esc(collision.time || "—")}</time><div class="collision-players">${coloredPlayers(collision.players, collision.playerIDs)}</div><span class="badge good">安全消除</span></div>${evidence}</div>`);
      continue;
    }
    if (collision.kind === "timeout-remove") {
      const playerID = (collision.playerIDs || [])[0];
      const failureIndex = failures.findIndex((failure, index) => !matchedFailures.has(index)
        && String(failure.playerID) === String(playerID)
        && Math.abs(Number(failure.timeMs) - Number(collision.timeMs)) <= 100);
      if (failureIndex >= 0) {
        const failure = failures[failureIndex];
        matchedFailures.add(failureIndex);
        cells.push(`<div class="mechanic-cell timeout-cell timeout-burst"><div class="collision-main"><time>${esc(failure.time)}</time><div class="collision-players">${coloredPlayer(failure.player, failure.playerID)}</div><div class="effect-line"><span class="badge bad">超时移除</span><span class="badge bad result-badge">培养爆发 ${num(failure.amount)}</span></div></div></div>`);
        continue;
      }
    }
    cells.push(collisionDetail(collision));
  }
  failures.forEach((failure, index) => {
    if (matchedFailures.has(index)) return;
    cells.push(`<div class="mechanic-cell timeout-cell"><div class="collision-main"><time>${esc(failure.time)}</time><div class="collision-players">${coloredPlayer(failure.player, failure.playerID)}</div><span class="badge bad result-badge">培养爆发 ${num(failure.amount)}</span></div></div>`);
  });
  return cells.join("");
}

function renderHelical() {
  const helical = current()?.sentinels?.helicalToxins || {};
  $("content").innerHTML = `<section class="panel notice"><p>${esc(helical.explanation || "")}</p></section><div class="round-list">${(helical.rounds || []).map(round => `<details class="round panel ${round.success ? "safe" : "fail"}" ${round.success ? "" : "open"}><summary><span class="round-title">第 ${round.index} 轮 <small>${esc(round.startTime)}–${esc(round.deadlineTime)} · ${round.initialPlayerCount} 人</small></span><span class="badge ${round.success ? "good" : "bad"}">${round.success ? "安全处理" : `错误 ${round.wrongCollisionCount}`}</span></summary><div class="round-content-grid">${roundMechanicCells(round)}</div></details>`).join("") || '<div class="empty">没有螺旋毒素轮次。</div>'}</div>`;
}

function specLabel(player) {
  if (player.localization?.spec?.enUS === "Devourer" || Number(player.specID) === 1480) return "噬灭";
  return player.localization?.spec?.zhCN || player.localization?.spec?.enUS || player.specID || "未知专精";
}

function renderMarks() {
  const marks = current()?.sentinels?.marks || {}, players = marks.players || [];
  if (state.playerID == null && players.length) state.playerID = players[0].id;
  const selected = players.find(player => String(player.id) === String(state.playerID)) || players[0];
  $("content").innerHTML = `<section class="panel"><h2>全员印记概览</h2>${simpleTable(["玩家", "专精", "酸液层数最高", "鲜血层数最高", "同时获得buff的次数", "最高总层数"], players.map(player => [`<span style="color:${player.classColor || "#fff"}">${esc(player.name)}</span>`, esc(specLabel(player)), `<span class="acid">${player.maxAcidStack}</span>`, `<span class="blood">${player.maxBloodStack}</span>`, player.simultaneousBuffCount, player.highestTotalStack]))}</section><section class="panel"><h2>单人分场查询</h2><div class="filters"><label>选择玩家 <select id="playerSelect">${players.map(player => `<option value="${player.id}" ${String(player.id) === String(selected?.id) ? "selected" : ""}>${esc(player.name)} · ${esc(specLabel(player))}</option>`).join("")}</select></label></div>${selected ? simpleTable(["分场", "时间", "酸液（入场→峰值 / 增层）", "鲜血（入场→峰值 / 增层）", "同时获得", "最高总层数"], selected.cycles.map(cycle => [`#${cycle.index}`, `${esc(cycle.startTime)}–${esc(cycle.endTime)}`, `<span class="acid">${cycle.acid.startStack}→${cycle.acid.peak} / ${cycle.acid.gainCount}</span>`, `<span class="blood">${cycle.blood.startStack}→${cycle.blood.peak} / ${cycle.blood.gainCount}</span>`, cycle.simultaneousBuffCount, cycle.highestTotalStack])) : ""}</section>`;
  const select = $("playerSelect");
  if (select) select.onchange = event => { state.playerID = event.target.value; renderMarks(); };
}

function playerList(rows, formatter) { return rows.length ? rows.map(formatter).join("、") : "—"; }

function renderField() {
  const water = current()?.sentinels?.clingingMurk || {};
  $("content").innerHTML = `<section class="panel"><h2>分摊参与与附着幽暗离散</h2>${simpleTable(["轮次", "分摊时间", "附着幽暗人数", "鲜血>酸液但未参与分摊", "放水过于离散"], (water.rounds || []).map(round => [`#${round.index}`, esc(round.soakTime), round.carrierCount, playerList(round.missingBloodSidePlayers || [], row => coloredPlayer(row.player, row.playerID)), playerList(round.dispersedPlayers || [], row => `${coloredPlayer(row.player, row.playerID)}（距本轮中位中心${row.distanceFromGroupYards}码）`)]))}</section>`;
}

function noHitText(players) {
  return playerList(players, player => {
    if (!player.immunityCandidate) return coloredPlayer(player.player, player.playerID);
    const spells = (player.immunityEvidence || []).map(item => `${item.spell}@${item.time}`).join("、");
    return `${coloredPlayer(player.player, player.playerID)} <span class="badge good immunity-badge">免疫：${esc(spells)}</span>`;
  });
}

function renderAvoidable() {
  const sentinels = current()?.sentinels || {}, living = sentinels.livingVenom || {}, droplets = sentinels.toxicDroplets || {};
  $("content").innerHTML = `<section class="panel"><h2>${spellHeading(1284209, "活体毒液 · 可躲避伤害")}</h2>${simpleTable(["玩家", "命中", "总伤害", "最大单次", "致死", "时间"], (living.players || []).map(player => [coloredPlayer(player.player, player.playerID), player.hitCount, num(player.totalDamage), num(player.maxHit), player.deathCount, esc((player.events || []).map(event => event.time).join("、"))]))}</section><section class="panel"><h2>${spellHeading(1284434, "剧毒水滴 / 绿球")}</h2>${simpleTable(["轮次", "施法时间", "踩球命中", "不同踩球者", "重复踩球", "本轮未受踩球伤害", "漏球爆炸"], (droplets.rounds || []).map(round => [`#${round.index}`, esc(round.castTime), round.soakHitCount, round.uniqueSoakerCount, playerList(round.repeatSoakers || [], row => `${coloredPlayer(row.player, row.playerID)}×${row.count}`), noHitText(round.noHitPlayers || []), round.missed ? `<span class="badge bad result-badge">${round.blastVictimCount} 人受伤</span>` : '<span class="badge good result-badge">未见爆炸</span>']))}</section>`;
  refreshWowhead();
}

function render() {
  renderSummary();
  $("pageTitle").textContent = `陵寝哨兵${current()?.difficultyName ? `（${current().difficultyName}）` : ""} · Fight ${current()?.fightID || "-"} 技能分析`;
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === state.tab));
  ({ survival: renderSurvival, helical: renderHelical, marks: renderMarks, field: renderField, avoidable: renderAvoidable }[state.tab] || renderHelical)();
}

function load(payload) {
  state.payload = payload; state.pulls = payload.data?.page1_wipeAnalysis || []; state.pull = 0; state.playerID = null;
  const selectedFight = Number(new URLSearchParams(location.search).get("fight"));
  const selectedIndex = selectedFight ? state.pulls.findIndex(pull => Number(pull.fightID) === selectedFight) : -1;
  state.pull = selectedIndex >= 0 ? selectedIndex : 0;
  state.tab = "helical";
  $("pullSelect").innerHTML = state.pulls.map((pull, index) => `<option value="${index}">Fight ${pull.fightID} · ${esc(pull.difficultyName || "未知难度")} · ${pull.isKill ? "KILL" : `${Number(pull.bossPercentage).toFixed(2)}%`} · ${esc(pull.duration)}</option>`).join("");
  $("pullSelect").value = String(state.pull);
  $("error").textContent = state.pulls.length ? "" : "分析结果中没有陵寝哨兵战斗。";
  render();
}

async function loadPath(path) {
  load(await window.MythicReportRuntime.loadPayload(path));
}

$("pullSelect").onchange = event => enterPull(Number(event.target.value));
$("fileInput").onchange = async event => { try { load(JSON.parse(await event.target.files[0].text())); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => { state.tab = button.dataset.tab; render(); });
const path = new URLSearchParams(location.search).get("json");
state.sourcePath = path || "";
if (path) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(path)}`;
if (path) loadPath(path).catch(error => $("error").textContent = error.message); else render();
