const MANIFEST_URL = "/assets/samples/mythic_dungeon_manifest.json";
const DEFAULT_SAMPLE_KEY = "skyreach";

const state = {
  document: null,
  manifest: null,
  pullIndex: 0,
  filter: "all",
  clock: "auto",
  relatedPlayerId: null,
  loadId: 0,
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const CLASS_COLORS = {
  Warrior: "#c69b6d",
  Paladin: "#f48cba",
  Hunter: "#aad372",
  Rogue: "#fff468",
  Priest: "#ffffff",
  Shaman: "#0070dd",
  Mage: "#3fc7eb",
  Warlock: "#8788ee",
  Druid: "#ff7c0a",
  Monk: "#00ff98",
  DemonHunter: "#a330c9",
  Evoker: "#33937f",
  DeathKnight: "#c41e3a",
};

function actorClass(actor) {
  if (!actor) return null;
  return actor.class || state.document?.team?.find((member) => member.id === actor.id)?.class || null;
}

function actorName(actor, fallback = "未知来源") {
  if (!actor) return escapeHtml(fallback);
  const classColor = CLASS_COLORS[actorClass(actor)];
  const style = classColor ? ` style="--actor-color:${classColor}"` : "";
  const className = classColor ? "actor-name player-actor" : "actor-name";
  const instance = actor.type !== "Player" && actor.instance ? actor.instance : "";
  return `<span class="${className}"${style}>${escapeHtml(`${actor.name || fallback}${instance}`)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 2200);
}

function validateDocument(document) {
  if (!document || document.kind !== "mythic-dungeon-route-timeline" || !Array.isArray(document.pulls)
      || !document.dungeon || !document.source || !Array.isArray(document.team)
      || document.pulls.some(pull => !pull || !Array.isArray(pull.enemies) || !Array.isArray(pull.enemySummary) || !Array.isArray(pull.timeline))) {
    throw new Error("不是受支持的大秘境抄轴 JSON");
  }
  return document;
}

function setLoading(message) {
  $("#empty-state").textContent = message;
  $("#empty-state").hidden = false;
  $("#pull-content").hidden = true;
}

function setDocument(document) {
  state.document = validateDocument(document);
  state.pullIndex = 0;
  state.relatedPlayerId = null;
  renderRun();
  renderPullList();
  if (document.pulls.length) selectPull(0);
  else setLoading("这份日志没有可显示的 Pull，请选择其他样板或导入 JSON。");
}

function renderRun() {
  const { dungeon, team, source, pulls } = state.document;
  $("#season-notice").textContent = state.document.skillSelection?.status === "needs-review"
    ? `S${dungeon.season || 2} 正式服样本，${team.map(member => `${member.spec}${member.className}`).join("、")}。当前展示实际施法候选，Boss 与小怪的关键技能筛选尚待确认。`
    : dungeon.season ? `S${dungeon.season} 样本，已配置技能时间轴。` : "S1 历史样本，已配置技能时间轴。";
  $("#dungeon-name").textContent = dungeon.nameZh || dungeon.name;
  $("#key-level").textContent = `+${dungeon.keystoneLevel}`;
  $("#run-meta").textContent = `${dungeon.completed ? "限时完成" : "未完成"}，${dungeon.keystoneTime || dungeon.duration}，${source.reportCode} / Fight ${source.fightId}`;
  $("#pull-count").textContent = `${pulls.length} 段`;
  $("#wcl-link").href = source.reportUrl;
  $("#team").innerHTML = team.map((member) => `
    <div class="member" style="--class-color:${CLASS_COLORS[member.class] || "#c0b1a0"}">
      <strong>${escapeHtml(member.name)}</strong>
      <span>${escapeHtml(member.spec)} ${escapeHtml(member.className)}，${escapeHtml(member.role)}</span>
    </div>
  `).join("");
  $("#related-player").innerHTML = '<option value="">全部玩家事件</option>' + team.map((member) =>
    `<option value="${member.id}">${escapeHtml(member.name)}，${escapeHtml(member.role)}</option>`
  ).join("");
}

async function fetchJson(url, label) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${label}加载失败：HTTP ${response.status}`);
  return response.json();
}

async function loadSample(sample) {
  const loadId = ++state.loadId;
  setLoading(`正在读取 ${sample.nameZh} +${sample.keystoneLevel} 真实日志样板……`);
  try {
    const document = await fetchJson(sample.file, "样板 JSON ");
    if (loadId !== state.loadId) return;
    setDocument(document);
  } catch (error) {
    if (loadId !== state.loadId) return;
    setLoading(error.message || "样板 JSON 读取失败");
    toast(error.message || "样板 JSON 读取失败");
  }
}

async function loadManifest() {
  setLoading("正在读取真实日志样板清单……");
  try {
    const manifest = await fetchJson(MANIFEST_URL, "样板清单");
    if (!Array.isArray(manifest.samples) || !manifest.samples.length) {
      throw new Error("样板清单中没有可用副本");
    }
    state.manifest = manifest;
    const selector = $("#sample-select");
    const seasons = [...new Set(manifest.samples.map(sample => sample.season || 1))].sort((a,b) => b-a);
    selector.innerHTML = seasons.map(season => `<optgroup label="S${season}${season === 1 ? '，历史样本' : '，正式服样本'}">${manifest.samples.filter(sample => (sample.season || 1) === season).map(sample =>
      `<option value="${escapeHtml(sample.key)}">S${season}，${escapeHtml(sample.nameZh)} +${sample.keystoneLevel}，${escapeHtml(sample.duration)}</option>`
    ).join('')}</optgroup>`).join('');
    const selected = manifest.samples.find((sample) => sample.key === manifest.defaultSampleKey)
      || manifest.samples.find((sample) => sample.key === DEFAULT_SAMPLE_KEY) || manifest.samples[0];
    selector.value = selected.key;
    await loadSample(selected);
  } catch (error) {
    setLoading(error.message || "样板清单读取失败");
    toast(error.message || "样板清单读取失败");
  }
}

function renderPullList() {
  $("#pull-list").innerHTML = state.document.pulls.map((pull, index) => `
    <button class="pull-button ${pull.type}" type="button" data-pull="${index}">
      <span class="pull-index">${pull.type === "boss" ? "BOSS" : `P${pull.ordinal}`}</span>
      <span class="pull-name">${escapeHtml(pull.name)}</span>
      <span class="pull-time">${escapeHtml(pull.dungeonTime)}</span>
    </button>
  `).join("");
  $$("[data-pull]").forEach((button) => button.addEventListener("click", () => selectPull(Number(button.dataset.pull))));
}

function selectPull(index) {
  state.pullIndex = index;
  state.filter = "all";
  $$("[data-pull]").forEach((button, buttonIndex) => button.classList.toggle("active", buttonIndex === index));
  $$("[data-filter]").forEach((button) => button.classList.toggle("active", button.dataset.filter === "all"));
  $("#empty-state").hidden = true;
  $("#pull-content").hidden = false;
  renderPull();
}

function renderPull() {
  const pull = state.document.pulls[state.pullIndex];
  $("#pull-kicker").textContent = pull.type === "boss" ? `BOSS，Encounter ${pull.encounterId}` : `PULL ${pull.ordinal}`;
  $("#pull-title").textContent = pull.name;
  const eventLabel = state.document.skillSelection?.status === "needs-review" ? "候选事件" : "关键事件";
  $("#pull-meta").textContent = `全局 ${pull.dungeonTime} 开始，战斗 ${pull.duration}，${pull.enemies.length} 个敌方实例，${pull.timeline.length} 条${eventLabel}`;
  $("#enemy-summary").innerHTML = pull.enemySummary.map((row) => `<span class="enemy-pill">${escapeHtml(row.name)}<strong>×${row.count}</strong></span>`).join("");
  $("#opener-body").innerHTML = pull.enemies.map((enemy) => {
    const opener = enemy.opener;
    const death = enemy.death;
    return `<tr>
      <td>${escapeHtml(enemy.label)}</td>
      <td class="timecode">${opener ? escapeHtml(opener.pullTime) : "—"}</td>
      <td class="timecode"${death?.synthetic ? ' title="根据 Boss 战结束时间复原"' : ""}>${death ? `${escapeHtml(death.pullTime)}${death.synthetic ? '<span class="synthetic-death">复原</span>' : ""}` : '<span class="unknown">未记录</span>'}</td>
      <td class="timecode">${enemy.survival ? escapeHtml(enemy.survival) : '<span class="unknown">—</span>'}</td>
      <td>${opener?.player ? actorName(opener.player) : '<span class="unknown">WCL 无可用交互</span>'}</td>
      <td>${opener ? openerEvidence(opener) : "—"}</td>
    </tr>`;
  }).join("");
  renderTimeline();
}

function openerEvidence(opener) {
  const labels = { cast: "首次施法", damage: "首次伤害", enemyTarget: "敌方首次点名" };
  const spell = opener.abilityName ? `，${escapeHtml(opener.abilityName)}` : "";
  return `<span class="event-badge">${labels[opener.evidence] || opener.evidence}${spell}</span>`;
}

function selectedClock(pull) {
  if (state.clock === "auto") return pull.type === "boss" ? "pull" : "dungeon";
  return state.clock;
}

function renderTimeline() {
  const pull = state.document?.pulls[state.pullIndex];
  if (!pull) return;
  const clock = selectedClock(pull);
  const events = pull.timeline.filter((event) => {
    if (state.filter !== "all" && event.kind !== state.filter) return false;
    if (!state.relatedPlayerId || event.kind === "enemyBeginCast") return true;
    const playerId = state.relatedPlayerId;
    return event.source?.id === playerId
      || event.target?.id === playerId
      || (event.targets || []).some((target) => target.id === playerId)
      || event.scope === "party";
  });
  $("#timeline-body").innerHTML = events.map((event) => {
    const duration = event.duration ? `，持续 ${escapeHtml(event.duration)}` : "";
    const roundEvidence = event.roundIncomplete
      ? `${event.roundLabel}，WCL记录 ${event.roundCastCount}/${event.expectedRoundCastCount}`
      : event.roundLabel;
    const round = roundEvidence ? `，${escapeHtml(roundEvidence)}` : "";
    const evidence = event.synthetic
      ? `<span class="event-badge synthetic">${escapeHtml(event.syntheticEvidence || "日志事件重建")}${duration}</span>`
      : `<span class="event-badge">${escapeHtml(event.eventType || (event.kind === "enemyBeginCast" ? "begincast" : "cast"))}${round}</span>`;
    return `<tr class="timeline-row ${event.kind}">
      <td class="timecode">${escapeHtml(clock === "pull" ? event.pullTime : event.dungeonTime)}</td>
      <td class="source-name">${actorName(event.source)}</td>
      <td><div class="ability"><span class="ability-name">${escapeHtml(event.ability.name)}</span><span class="spell-id">${event.ability.id}</span></div></td>
      <td>${eventTargets(event)}</td>
      <td>${evidence}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="5" class="unknown">当前筛选下没有事件</td></tr>';
}

function eventTargets(event) {
  if (Array.isArray(event.targets) && event.targets.length) {
    return event.targets.map((target) => actorName(target, "未知目标")).join("、");
  }
  return event.target ? actorName(event.target, "未知目标") : '<span class="unknown">—</span>';
}

$$('[data-clock]').forEach((button) => button.addEventListener("click", () => {
  state.clock = button.dataset.clock;
  $$('[data-clock]').forEach((item) => item.classList.toggle("active", item === button));
  renderTimeline();
}));

$$('[data-filter]').forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  $$('[data-filter]').forEach((item) => item.classList.toggle("active", item === button));
  renderTimeline();
}));

$("#json-input").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  const loadId = ++state.loadId;
  try {
    const document = JSON.parse(await file.text());
    if (loadId !== state.loadId) return;
    setDocument(document);
    $("#sample-select").selectedIndex = -1;
    toast(`已导入 ${file.name}`);
  } catch (error) {
    toast(error.message || "JSON 读取失败");
  } finally {
    event.target.value = "";
  }
});

$("#sample-select").addEventListener("change", async (event) => {
  const sample = state.manifest?.samples?.find((row) => row.key === event.target.value);
  if (sample) await loadSample(sample);
});

$("#related-player").addEventListener("change", (event) => {
  state.relatedPlayerId = event.target.value ? Number(event.target.value) : null;
  renderTimeline();
});

loadManifest();

fetch("/api/mythic-dungeon/options", {cache:"no-store"}).then(async response => {
  if (!response.ok) return;
  const data = await response.json();
  $("#dungeon-rule").insertAdjacentHTML("beforeend", (data.dungeons || []).map(row =>
    `<option value="${escapeHtml(row.key)}">${escapeHtml(row.name)} · 已配置规则</option>`).join(""));
}).catch(() => {});

$("#wcl-run-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#analyze-run");
  const message = $("#wcl-run-message");
  button.disabled = true;
  message.textContent = "正在读取 WCL 全程事件，这可能需要几分钟…";
  try {
    const response = await fetch("/api/mythic-dungeon/analyze", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    setDocument(data);
    $("#sample-select").selectedIndex = -1;
    message.textContent = "分析完成，已显示这份大秘境日志。";
  } catch (error) {
    message.innerHTML = responseMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

function responseMessage(message) {
  return escapeHtml(message) + (message.includes("登录") || message.includes("凭据")
    ? ' <a href="/account">前往账号设置</a>' : "");
}
