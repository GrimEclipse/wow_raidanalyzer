(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const state = { payload: null, pulls: [], pull: 0, tab: "survival" };
  const current = () => state.pulls[state.pull];
  const boss = () => current()?.kithix || {};
  const spell = (id, name) => `<a class="spell" href="https://www.wowhead.com/cn/spell=${id}" target="_blank" rel="noreferrer">${esc(name || id)}</a>`;
  const player = row => `<span class="player" style="color:${esc(row?.classColor || "#e5e7eb")}">${esc(row?.player || row?.name || "—")}</span>`;
  const yes = flag => flag ? '<span class="badge good">是</span>' : '<span class="badge bad">否</span>';
  const clock = ms => { const seconds = Math.max(0, Number(ms) || 0) / 1000; return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${(seconds % 60).toFixed(1).padStart(4, "0")}`; };
  function table(headers, rows) {
    if (!rows.length) return '<div class="empty">没有记录。</div>';
    return `<div class="table-wrap"><table><thead><tr>${headers.map(header => `<th>${header}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function renderStats() {
    const pull = current(), data = boss(), checks = data.checks || {};
    if (!pull) { $("stats").innerHTML = ""; return; }
    const cards = [
      ["时长", pull.duration],
      ["结果", pull.isKill ? "击杀" : `${Number(pull.bossPercentage || 0).toFixed(1)}%`],
      ["难度", pull.difficultyName || "—"],
      ["卵超时", checks.eggsMissed ?? 0],
      ["攫取未消", checks.graspsMissed ?? 0],
      ["辉光消逝", checks.fragmentLeaks ?? 0],
      ["光耀恩典缺失", checks.finalLightMissing ?? 0],
    ];
    $("stats").innerHTML = cards.map(([label, value]) => `<article class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></article>`).join("");
    $("title").textContent = state.payload?.meta?.bossName || "基希克斯";
    $("meta").textContent = `${pull.date || ""} ${pull.startClock || ""} · ${pull.difficultyName || ""} · Fight ${pull.fightID}`;
    $("wclLink").href = pull.wclDeepLink || "#";
  }
  function renderTabs() {
    const defs = state.payload?.meta?.tabDefinitions || [{ key: "survival", label: "死亡与战复" }];
    if (!defs.some(row => row.key === state.tab)) state.tab = defs[0].key;
    $("tabs").innerHTML = defs.map(row => `<button type="button" data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join("");
    document.querySelectorAll("[data-tab]").forEach(button => { button.onclick = () => { state.tab = button.dataset.tab; render(); }; });
  }
  function renderSurvival() {
    const survival = current()?.survival || {};
    return `<section class="panel"><h2>死亡与战复</h2><p class="hint">死亡 ${survival.deathCount ?? 0}，战复 ${survival.combatResCount ?? 0}，结束时存活 ${survival.survivorCount ?? 0}。</p>${table(["时间", "玩家", "事件", "技能"], (survival.timeline || []).map(row => [esc(row.time), player(row), row.kind === "death" ? '<span class="badge bad">死亡</span>' : '<span class="badge good">战复</span>', spell(row.abilityID, row.ability)]))}</section>`;
  }
  function renderP1() {
    const data = boss();
    return `<section class="panel"><h2>第一阶段</h2><p class="hint">${esc(data.evidenceNote || "")}</p><h3>黑暗毁灭与虚空之痕</h3>${table(["时间", "坦克", "范围"], (data.devastations || []).map(row => [esc(row.time), esc(row.tank || "—"), "15 码"]))}
      <h3>虫群</h3>${table(["出现", "单位", "类型", "死亡", "结果"], (data.adds || []).filter(row => ["bomber", "weaver", "hulk", "egg", "mindstinger"].includes(row.kind)).map(row => {
        const egg = (data.eggs || []).find(item => item.key === row.key);
        return [clock(row.spawnTimeMs), esc(row.name), esc(row.kind), row.deathTimeMs == null ? "—" : clock(row.deathTimeMs), egg ? (egg.cleared ? '<span class="badge good">10 秒内击杀</span>' : egg.missed ? '<span class="badge bad">超时</span>' : "—") : ""];
      }))}
      <h3>烈毒咆哮 / 虚空编织</h3>${table(["时间", "技能", "目标"], [...(data.roars || []).map(row => [esc(row.time), spell(1302884, "烈毒咆哮"), "前方 60 度 / 60 码"]), ...(data.weaves || []).map(row => [esc(row.time), spell(1302333, "虚空编织"), esc(row.target || "—")])])}
      <h3>熄灭与圣光之拥</h3>${table(["时间", "技能"], (data.extinguishes || []).map(row => [esc(row.time), spell(1304424, "熄灭")]))}${table(["玩家", "获得", "移除"], (data.embraces || []).map(row => [player(row), esc(row.applyTime), esc(row.removeTime || "—")]))}
      <h3>窒息黑暗与蚀日碎片</h3><p class="hint">窒息黑暗开始前已经留在场上的虚空之痕会朝莉亚德琳射出蚀日碎片。辉光消逝表示有碎片碰到了她。</p>${table(["开始", "结束", "虚空之痕", "挡住碎片", "辉光消逝"], (data.darkness || []).map(row => [clock(row.startTimeMs), clock(row.endTimeMs), row.scarCount ?? 0, row.soakedCount ?? 0, row.leaked ? '<span class="badge bad">碰到莉亚德琳</span>' : '<span class="badge good">未碰到</span>']))}
      ${table(["出现", "位置", "参与的窒息黑暗"], (data.voidscars || []).map(row => [clock(row.startTimeMs), `${row.x}, ${row.y}`, (row.volleyTimesMs || []).map(clock).join("、") || "—"]))}
      <p class="hint">挡住的碎片按玩家第一次受到伤害的位置，拟合到射向莉亚德琳的那条虚空之痕上。回放里的光点在伤害发生时到达该位置。</p>${table(["命中", "玩家", "偏离"], (data.fragmentPaths || []).map(row => [clock(row.timeMs), player(row), `${row.offsetYards} 码`]))}
      ${table(["时间", "技能"], (data.radiances || []).map(row => [esc(row.time), spell(1303169, "神圣光辉")]))}
      <p class="hint">黑暗狂乱 ${data.checks?.frenziedAdds ?? 0} 个未被提前击杀的小怪。</p>
      <h3>不可名状之怖</h3>${table(["玩家", "获得", "结束"], (data.horrors || []).map(row => [player(row), esc(row.applyTime), esc(row.removeTime || "—")]))}
      <h3>深渊攫取</h3>${table(["玩家", "获得", "移除", "8 秒内"], (data.grasps || []).map(row => [player(row), esc(row.applyTime), esc(row.removeTime || "—"), yes(row.cleared)]))}</section>`;
  }
  function renderP2() {
    const data = boss();
    return `<section class="panel"><h2>第二阶段</h2><h3>虚无之门与湮消</h3>${table(["玩家", "门落下", "清除"], (data.gates || []).map(row => [player(row), clock(row.dropTimeMs), row.clearedTimeMs == null ? '<span class="badge bad">仍在</span>' : clock(row.clearedTimeMs)]))}
      ${table(["玩家", "湮消", "爆炸复稳"], (data.negations || []).map(row => [player(row), esc(row.applyTime), yes(row.restabilized)]))}
      <h3>光耀恩典</h3><p class="hint">只核对第二阶段开始时仍存活的玩家是否获得光耀恩典 debuff。</p>${table(["玩家", "光耀恩典"], (data.finalLights || []).map(row => [player(row), yes(row.radiantGrace)]))}</section>`;
  }
  function renderContent() {
    $("content").querySelectorAll(".mw").forEach(host => host._workbench?.destroy());
    const views = { survival: renderSurvival, p1: renderP1, p2: renderP2, replay: () => '<div id="kithixReplay"></div>' };
    $("content").innerHTML = (views[state.tab] || renderSurvival)();
    if (state.tab === "replay" && window.KithixReplay) window.KithixReplay.mount($("kithixReplay"), boss(), current()?.durationMs);
  }
  function render() { renderStats(); renderTabs(); renderContent(); }
  function load(payload) {
    state.payload = payload;
    state.pulls = [...(payload.data?.page1_wipeAnalysis || [])];
    const fight = Number(new URLSearchParams(location.search).get("fight"));
    const index = state.pulls.findIndex(row => Number(row.fightID) === fight);
    state.pull = index >= 0 ? index : 0;
    state.tab = new URLSearchParams(location.search).get("tab") || "replay";
    $("pullSelect").innerHTML = state.pulls.map((row, rowIndex) => `<option value="${rowIndex}">Fight ${row.fightID}，${esc(row.difficultyName || "")}，${row.isKill ? "KILL" : `${Number(row.bossPercentage).toFixed(1)}%`}</option>`).join("");
    $("pullSelect").value = String(state.pull);
    $("error").textContent = state.pulls.length ? "" : "分析结果中没有基希克斯战斗。";
    render();
  }
  $("pullSelect").onchange = event => { state.pull = Number(event.target.value); render(); };
  $("fileInput").onchange = async event => { try { load(await window.MythicReportRuntime.readLocalFile(event.target.files[0])); } catch (error) { $("error").textContent = error.message; } };
  const path = new URLSearchParams(location.search).get("json");
  if (path) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(path)}`;
  if (path) window.MythicReportRuntime.loadPayload(path).then(load).catch(error => { $("error").textContent = error.message; });
  else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
})();
