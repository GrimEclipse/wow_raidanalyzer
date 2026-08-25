const state = { payload: null, pulls: [], pull: 0, tab: "overview", playerID: null };
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
  if (state.tab === "overview") {
    const pulls = state.pulls;
    const kills = pulls.filter(pull => pull.isKill).length;
    const totalDurationMs = pulls.reduce((total, pull) => total + Number(pull.durationMs || 0), 0);
    const totalRounds = pulls.reduce((total, pull) => total + Number(pull.sentinels?.helicalToxins?.roundCount || 0), 0);
    const totalWrong = pulls.reduce((total, pull) => total + Number(pull.sentinels?.helicalToxins?.wrongCollisionCount || 0), 0);
    const bestWipe = Math.min(...pulls.filter(pull => !pull.isKill).map(pull => Number(pull.bossPercentage || 100)), 100);
    const stats = [
      ["Pull 总数", pulls.length], ["击杀", kills],
      ["累计战斗", formatDuration(totalDurationMs)], ["最好进度", kills ? "KILL" : `${bestWipe.toFixed(2)}%`],
      ["静滞总轮数", totalRounds], ["错误碰撞", totalWrong]
    ];
    $("summary").innerHTML = stats.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
    const reportID = pulls[0]?.reportID;
    $("wclLink").href = reportID ? `https://www.warcraftlogs.com/reports/${encodeURIComponent(reportID)}` : "#";
    return;
  }
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

function formatDuration(milliseconds) {
  const seconds = Math.max(0, Math.round(Number(milliseconds || 0) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : `${minutes}:${String(rest).padStart(2, "0")}`;
}

function phaseTimeline(pull) {
  const duration = Math.max(1, Number(pull.durationMs || 1));
  const rows = pull.phaseTimeline || [];
  return `<div class="phase-track" aria-label="Fight ${pull.fightID} 阶段时间线">${rows.map((phase, index) => {
    const left = Math.max(0, Math.min(100, Number(phase.timeMs || 0) / duration * 100));
    return `<span class="phase-marker ${index === rows.length - 1 ? (pull.isKill ? "kill" : "wipe") : ""}" style="left:${left}%" title="${esc(phase.label)} · ${esc(formatDuration(phase.timeMs))}"></span>`;
  }).join("")}</div><div class="phase-legend">${rows.map(phase => `<span class="phase-chip"><b>${esc(formatDuration(phase.timeMs))}</b> ${esc(phase.label)}</span>`).join("")}</div>`;
}

function renderOverview() {
  $("content").innerHTML = `<section class="overview-head panel"><div><h2>整场 Pull 与阶段概览</h2><p class="muted">选择任意 Pull 进入技能分析；进入后仍可使用页头下拉框切换战斗。</p></div></section><div class="overview-list">${state.pulls.map((pull, index) => `<article class="overview-pull ${pull.isKill ? "kill" : "wipe"}"><div class="overview-pull-head"><div><span class="pull-number">Fight ${pull.fightID}</span><h3>${esc(pull.date || "")} ${esc(pull.startClock || "")}</h3></div><span class="badge ${pull.isKill ? "good" : "bad"}">${pull.isKill ? "击杀" : `${Number(pull.bossPercentage || 0).toFixed(2)}%`} · ${esc(pull.duration)}</span></div><div class="overview-reason"><b>${esc(pull.wipePhase || "阶段待定")}</b><span>${esc(pull.wipeReason || pull.summary || "暂无结论")}</span></div>${phaseTimeline(pull)}<div class="overview-actions"><button class="button primary" data-enter-pull="${index}">进入技能分析</button><a class="button" href="${esc(pull.wclDeepLink || "#")}" target="_blank" rel="noreferrer">打开本场 WCL</a></div></article>`).join("") || '<div class="empty">当前 JSON 没有 Pull。</div>'}</div>`;
  document.querySelectorAll("[data-enter-pull]").forEach(button => button.onclick = () => enterPull(Number(button.dataset.enterPull)));
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
  if (collision.kind === "wrong-collision") {
    const movers = (collision.largeMovers || []).map(row => `<div class="movement-warning">${esc(row.player)}在最后一秒进行了大范围的移动（${row.movementYards}码）</div>`).join("");
    return `<div class="mechanic-cell ${collision.firstWrongCollision ? "first-wrong" : ""}"><b>${esc(collision.time)} · ${coloredPlayers(collision.players, collision.playerIDs)}</b><div><span class="badge bad">错误相撞</span> ${esc(collision.collisionCombination || "组合待定")} → 两人均变为 ${collision.resultStack} 层</div>${collision.firstWrongCollision ? '<div class="first-wrong-label">本轮第一个错误碰撞</div>' : ""}${movers}</div>`;
  }
  if (collision.kind === "recovery-clear") return `<div class="mechanic-cell"><b>${esc(collision.time)} · ${coloredPlayers(collision.players, collision.playerIDs)}</b><div><span class="badge good">补救后安全消除</span> ${esc(collision.collisionCombination || "")}</div></div>`;
  if (collision.kind === "timeout-remove") return `<div class="mechanic-cell compact"><b>${esc(collision.time)} · ${coloredPlayers(collision.players, collision.playerIDs)}</b><div><span class="badge bad">超时移除</span></div></div>`;
  if (collision.kind === "unpaired-remove") return `<div class="mechanic-cell compact"><b>${esc(collision.time)} · ${coloredPlayers(collision.players, collision.playerIDs)}</b><div><span class="badge warn">单条移除</span></div></div>`;
  return "";
}

function roundMechanicCells(round) {
  const failures = round.failures || [], matchedFailures = new Set(), cells = [];
  for (const collision of round.collisions || []) {
    if (collision.kind === "safe-clear") {
      cells.push(`<div class="mechanic-cell safe-cell">${coloredPlayers(collision.players, collision.playerIDs)}</div>`);
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
        cells.push(`<div class="mechanic-cell compact timeout-burst"><b>${esc(failure.time)} · ${coloredPlayer(failure.player, failure.playerID)}</b><div class="effect-line"><span class="badge bad">超时移除</span><span class="badge bad result-badge">培养爆发 ${num(failure.amount)}</span></div></div>`);
        continue;
      }
    }
    cells.push(collisionDetail(collision));
  }
  failures.forEach((failure, index) => {
    if (matchedFailures.has(index)) return;
    cells.push(`<div class="mechanic-cell compact"><b>${esc(failure.time)} · ${coloredPlayer(failure.player, failure.playerID)}</b><div><span class="badge bad result-badge">培养爆发 ${num(failure.amount)}</span></div></div>`);
  });
  return cells.join("");
}

function renderHelical() {
  const helical = current()?.sentinels?.helicalToxins || {};
  $("content").innerHTML = `<section class="panel notice"><p>${esc(helical.explanation || "")}</p></section><div class="round-list">${(helical.rounds || []).map(round => `<details class="round panel ${round.success ? "safe" : "fail"}" ${round.success ? "" : "open"}><summary><span>第 ${round.index} 轮 · ${esc(round.startTime)}</span><span class="badge ${round.success ? "good" : "bad"}">${round.success ? "安全" : `错误 ${round.wrongCollisionCount}`}</span></summary><div class="round-meta">${round.initialPlayerCount} 人 · 截止 ${esc(round.deadlineTime)}</div><div class="round-content-grid">${roundMechanicCells(round)}</div></details>`).join("") || '<div class="empty">没有螺旋毒素轮次。</div>'}</div>`;
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
  $("content").innerHTML = `<section class="panel"><h2>活体毒液（1284209）· 可躲避伤害</h2>${simpleTable(["玩家", "命中", "总伤害", "最大单次", "致死", "时间"], (living.players || []).map(player => [coloredPlayer(player.player, player.playerID), player.hitCount, num(player.totalDamage), num(player.maxHit), player.deathCount, esc((player.events || []).map(event => event.time).join("、"))]))}</section><section class="panel"><h2>剧毒水滴 / 绿球</h2>${simpleTable(["轮次", "施法时间", "踩球命中", "不同踩球者", "重复踩球", "本轮未受踩球伤害", "漏球爆炸"], (droplets.rounds || []).map(round => [`#${round.index}`, esc(round.castTime), round.soakHitCount, round.uniqueSoakerCount, playerList(round.repeatSoakers || [], row => `${coloredPlayer(row.player, row.playerID)}×${row.count}`), noHitText(round.noHitPlayers || []), round.missed ? `<span class="badge bad result-badge">${round.blastVictimCount} 人受伤</span>` : '<span class="badge good result-badge">未见爆炸</span>']))}</section>`;
}

function render() {
  renderSummary();
  $("pageTitle").textContent = state.tab === "overview" ? "陵寝哨兵 · 全场概览" : `陵寝哨兵 · Fight ${current()?.fightID || "-"} 技能分析`;
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === state.tab));
  ({ overview: renderOverview, helical: renderHelical, marks: renderMarks, field: renderField, avoidable: renderAvoidable }[state.tab] || renderOverview)();
}

function load(payload) {
  state.payload = payload; state.pulls = payload.data?.page1_wipeAnalysis || []; state.pull = 0; state.playerID = null;
  state.tab = state.pulls.length > 1 ? "overview" : "helical";
  $("pullSelect").innerHTML = state.pulls.map((pull, index) => `<option value="${index}">Fight ${pull.fightID} · ${pull.isKill ? "KILL" : `${Number(pull.bossPercentage).toFixed(2)}%`} · ${esc(pull.duration)}</option>`).join("");
  $("error").textContent = state.pulls.length ? "" : "分析结果中没有陵寝哨兵战斗。";
  render();
}

async function loadPath(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`读取失败：HTTP ${response.status}`);
  load(await response.json());
}

$("pullSelect").onchange = event => enterPull(Number(event.target.value));
$("overviewLink").onclick = () => { state.tab = "overview"; render(); window.scrollTo({ top: 0, behavior: "smooth" }); };
$("fileInput").onchange = async event => { try { load(JSON.parse(await event.target.files[0].text())); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => { state.tab = button.dataset.tab; render(); });
const path = new URLSearchParams(location.search).get("json");
if (path) loadPath(path).catch(error => $("error").textContent = error.message); else render();
