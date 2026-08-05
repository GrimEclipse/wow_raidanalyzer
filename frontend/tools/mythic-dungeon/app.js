const MANIFEST_URL = "/assets/samples/mythic_dungeon_manifest.json";
const DEFAULT_SAMPLE_KEY = "skyreach";

const state = {
  document: null,
  manifest: null,
  pullIndex: 0,
  filter: "all",
  clock: "auto",
  relatedPlayerId: null,
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const CLASS_COLORS = {
  Druid: "#ff7c0a",
  Monk: "#00ff98",
  DemonHunter: "#a330c9",
  Evoker: "#33937f",
  DeathKnight: "#c41e3a",
};

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
  if (!document || document.kind !== "mythic-dungeon-route-timeline" || !Array.isArray(document.pulls)) {
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
  selectPull(0);
}

function renderRun() {
  const { dungeon, team, source, pulls } = state.document;
  $("#dungeon-name").textContent = dungeon.nameZh || dungeon.name;
  $("#key-level").textContent = `+${dungeon.keystoneLevel}`;
  $("#run-meta").textContent = `${dungeon.completed ? "限时完成" : "未完成"} · ${dungeon.keystoneTime || dungeon.duration} · ${source.reportCode} / Fight ${source.fightId}`;
  $("#pull-count").textContent = `${pulls.length} 段`;
  $("#wcl-link").href = source.reportUrl;
  $("#team").innerHTML = team.map((member) => `
    <div class="member" style="--class-color:${CLASS_COLORS[member.class] || "#94a3b8"}">
      <strong>${escapeHtml(member.name)}</strong>
      <span>${escapeHtml(member.spec)} ${escapeHtml(member.className)} · ${escapeHtml(member.role)}</span>
    </div>
  `).join("");
  $("#related-player").innerHTML = '<option value="">全部玩家事件</option>' + team.map((member) =>
    `<option value="${member.id}">${escapeHtml(member.name)} · ${escapeHtml(member.role)}</option>`
  ).join("");
}

async function fetchJson(url, label) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${label}加载失败：HTTP ${response.status}`);
  return response.json();
}

async function loadSample(sample) {
  setLoading(`正在读取 ${sample.nameZh} +${sample.keystoneLevel} 真实日志样板……`);
  try {
    setDocument(await fetchJson(sample.file, "样板 JSON "));
  } catch (error) {
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
    selector.innerHTML = manifest.samples.map((sample) =>
      `<option value="${escapeHtml(sample.key)}">${escapeHtml(sample.nameZh)} +${sample.keystoneLevel} · ${escapeHtml(sample.duration)}</option>`
    ).join("");
    const selected = manifest.samples.find((sample) => sample.key === DEFAULT_SAMPLE_KEY) || manifest.samples[0];
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
  $("#pull-kicker").textContent = pull.type === "boss" ? `BOSS · Encounter ${pull.encounterId}` : `PULL ${pull.ordinal}`;
  $("#pull-title").textContent = pull.name;
  $("#pull-meta").textContent = `全局 ${pull.dungeonTime} 开始 · 战斗 ${pull.duration} · ${pull.enemies.length} 个敌方实例 · ${pull.timeline.length} 条关键事件`;
  $("#enemy-summary").innerHTML = pull.enemySummary.map((row) => `<span class="enemy-pill">${escapeHtml(row.name)}<strong>×${row.count}</strong></span>`).join("");
  $("#opener-body").innerHTML = pull.enemies.map((enemy) => {
    const opener = enemy.opener;
    return `<tr>
      <td>${escapeHtml(enemy.label)}</td>
      <td class="timecode">${opener ? escapeHtml(opener.pullTime) : "—"}</td>
      <td>${opener?.player ? escapeHtml(opener.player.name) : '<span class="unknown">WCL 无可用交互</span>'}</td>
      <td>${opener ? openerEvidence(opener) : "—"}</td>
    </tr>`;
  }).join("");
  renderTimeline();
}

function openerEvidence(opener) {
  const labels = { cast: "首次施法", damage: "首次伤害", enemyTarget: "敌方首次点名" };
  const spell = opener.abilityId ? ` · ${opener.abilityId}` : "";
  return `<span class="event-badge">${labels[opener.evidence] || opener.evidence}${spell}</span>`;
}

function selectedClock(pull) {
  if (state.clock === "auto") return pull.type === "boss" ? "pull" : "dungeon";
  return state.clock;
}

function renderTimeline() {
  const pull = state.document.pulls[state.pullIndex];
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
    const evidence = event.synthetic
      ? '<span class="event-badge synthetic">Buff remove · 1225789</span>'
      : `<span class="event-badge">${escapeHtml(event.eventType || (event.kind === "enemyBeginCast" ? "begincast" : "cast"))}</span>`;
    return `<tr class="timeline-row ${event.kind}">
      <td class="timecode">${escapeHtml(clock === "pull" ? event.pullTime : event.dungeonTime)}</td>
      <td class="source-name">${escapeHtml(event.source?.name || "未知来源")}</td>
      <td><div class="ability"><span class="ability-name">${escapeHtml(event.ability.name)}</span><span class="spell-id">${event.ability.id}</span></div></td>
      <td>${eventTargets(event)}</td>
      <td>${evidence}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="5" class="unknown">当前筛选下没有事件</td></tr>';
}

function eventTargets(event) {
  if (Array.isArray(event.targets) && event.targets.length) {
    return event.targets.map((target) => escapeHtml(target.name)).join("、");
  }
  return event.target ? escapeHtml(event.target.name) : '<span class="unknown">—</span>';
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
  try {
    setDocument(JSON.parse(await file.text()));
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
