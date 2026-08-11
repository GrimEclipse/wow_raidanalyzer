const CLASS_OPTIONS = [
  ["death-knight", "死亡骑士", "plate"], ["demon-hunter", "恶魔猎手", "leather"],
  ["druid", "德鲁伊", "leather"], ["evoker", "唤魔师", "mail"],
  ["hunter", "猎人", "mail"], ["mage", "法师", "cloth"], ["monk", "武僧", "leather"],
  ["paladin", "圣骑士", "plate"], ["priest", "牧师", "cloth"], ["rogue", "潜行者", "leather"],
  ["shaman", "萨满祭司", "mail"], ["warlock", "术士", "cloth"], ["warrior", "战士", "plate"]
];
const DIFFICULTY_NAMES = { lfr: "随机团队", normal: "普通", heroic: "英雄", mythic: "史诗" };
const MODE_NAMES = { need: "需求", greed: "贪婪", transmog: "幻化收藏", alt: "小号提升" };
const ARMOR_NAMES = { cloth: "布甲", leather: "皮甲", mail: "锁甲", plate: "板甲", accessory: "首饰", weapon: "武器", token: "套装兑换物", cosmetic: "幻化收藏", mount: "坐骑", pet: "宠物", toy: "玩具", furniture: "家具", other: "其他" };
const CLASS_COLORS = {
  "death-knight": "#C41F3B", "demon-hunter": "#A330C9", druid: "#FF7D0A", evoker: "#33937F",
  hunter: "#ABD473", mage: "#69CCF0", monk: "#00FF96", paladin: "#F58CBA", priest: "#FFFFFF",
  rogue: "#FFF569", shaman: "#0070DE", warlock: "#9482C9", warrior: "#C79C6E"
};

const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const now = new Date();
let selectedDate = localDate(now);
let displayedMonth = new Date(now.getFullYear(), now.getMonth(), 1);
let documentState = null;

function localDate(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `请求失败（${response.status}）`);
    Object.assign(error, payload, { status: response.status });
    throw error;
  }
  return payload;
}

function notify(message, error = false) {
  const box = $("#message");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { box.hidden = true; }, 4800);
}

function roster() { return documentState?.state?.roster || []; }
function raids() { return documentState?.catalog?.raids || []; }
function selectedRaid() { return raids().find(row => row.key === $("#dayRaid").value) || raids()[0]; }
function selectedBoss() { return selectedRaid()?.bosses?.find(row => row.key === $("#bossSelect").value); }
function player(id) { return roster().find(row => row.id === id); }
function playerName(id) { return player(id)?.name || id; }
function playerColor(id) { return CLASS_COLORS[player(id)?.classKey] || "#edf2f7"; }
function classStyle(id) { return `--class-color:${playerColor(id)}`; }
function canModify() { return Boolean(documentState?.permissions?.canModify); }

async function load() {
  documentState = await api(`/api/loot?date=${selectedDate}&difficulty=${$("#difficultySelect").value}`);
  renderAll();
}

function renderAll() {
  renderActions();
  renderCalendar();
  renderRaidOptions();
  renderDay();
  renderRecipientOptions();
  renderClassFilter();
  renderBossOptions();
  renderRequests();
  renderAllocations();
  renderRoster();
}

function renderActions() {
  const manage = $("#manageRoster");
  manage.hidden = !canModify();
  const toggle = $("#mythicToggle");
  const isAdmin = Boolean(documentState?.permissions?.isAdmin);
  const cadence = Number(documentState?.state?.settings?.mythicCadenceWeeks || 2);
  toggle.hidden = !isAdmin;
  toggle.classList.toggle("biweekly", cadence === 2);
  toggle.setAttribute("aria-checked", cadence === 2 ? "true" : "false");
  toggle.title = cadence === 2 ? "当前史诗难度每两周刷新；点击切换为单周" : "当前史诗难度每周刷新；点击切换为双周";
  $("#saveDay").disabled = !canModify();
  $("#addAllocation").disabled = !canModify();
  const source = documentState?.catalog?.source;
  const summary = documentState?.catalog?.summary;
  $("#catalogSource").textContent = source ? `${source.build} · ${source.locale} · ${summary?.itemCount || 0} 条官方客户端掉落` : "";
}

function renderCalendar() {
  const year = displayedMonth.getFullYear();
  const month = displayedMonth.getMonth();
  $("#monthTitle").textContent = `${year} 年 ${month + 1} 月`;
  const first = new Date(year, month, 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - mondayOffset);
  const progression = new Set(documentState?.calendar?.progressionDates || []);
  const resets = new Set(documentState?.calendar?.mythicResetDates || []);
  const daysByDate = new Map((documentState?.state?.days || []).map(row => [row.date, row]));
  const allocationsByDate = new Map();
  (documentState?.state?.allocations || []).forEach(row => allocationsByDate.set(row.date, (allocationsByDate.get(row.date) || 0) + 1));

  $("#calendar").innerHTML = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
    const key = localDate(date);
    const day = daysByDate.get(key);
    const leaveCount = (day?.attendance || []).filter(row => ["leave", "absent"].includes(row.status)).length;
    const allocationCount = allocationsByDate.get(key) || 0;
    const classes = ["calendar-day"];
    if (date.getMonth() !== month) classes.push("other");
    if (progression.has(key)) classes.push("raid");
    if (key === selectedDate && $("#dayDrawer").classList.contains("open")) classes.push("selected");
    const lines = [];
    if (leaveCount) lines.push(`<span><strong>${leaveCount}</strong> 人请假</span>`);
    if (allocationCount) lines.push(`<span><strong>${allocationCount}</strong> 件分配</span>`);
    return `<button class="${classes.join(" ")}" data-date="${key}">
      <span class="day-number">${date.getDate()}</span>
      ${resets.has(key) ? `<i class="mythic-dot" title="史诗难度刷新"></i>` : ""}
      ${progression.has(key) ? `<span class="day-label">开荒日</span>` : ""}
      ${lines.length ? `<span class="day-summary">${lines.join("")}</span>` : ""}
    </button>`;
  }).join("");
  $("#calendar").querySelectorAll("button").forEach(button => button.addEventListener("click", () => openDay(button.dataset.date)));
}

async function openDay(value) {
  selectedDate = value;
  const parsed = new Date(`${value}T12:00:00`);
  displayedMonth = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  $("#drawerBackdrop").hidden = false;
  $("#dayDrawer").classList.add("open");
  $("#dayDrawer").setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  try { await load(); } catch (error) { notify(error.message, true); }
}

function closeDay() {
  $("#dayDrawer").classList.remove("open");
  $("#dayDrawer").setAttribute("aria-hidden", "true");
  $("#drawerBackdrop").hidden = true;
  document.body.classList.remove("drawer-open");
  renderCalendar();
}

function currentDayRecord(create = true) {
  let day = documentState.state.days.find(row => row.date === selectedDate);
  if (!day && create) {
    const defaultRaid = raids().find(row => row.key === "venomous_abyss") || raids()[0];
    day = { date: selectedDate, raidKey: defaultRaid?.key || "venomous_abyss", notes: "", attendance: [] };
    documentState.state.days.push(day);
  }
  return day;
}

function renderRaidOptions() {
  const currentDay = currentDayRecord(false);
  const desired = currentDay?.raidKey || $("#dayRaid").value || (raids().find(row => row.key === "venomous_abyss") || raids()[0])?.key || "";
  $("#dayRaid").innerHTML = raids().map(raid => `<option value="${escapeHtml(raid.key)}">${escapeHtml(raid.name)}</option>`).join("");
  $("#dayRaid").value = desired;
}

function renderDay() {
  const date = new Date(`${selectedDate}T12:00:00`);
  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][date.getDay()];
  $("#selectedDateTitle").textContent = `${date.getMonth() + 1} 月 ${date.getDate()} 日 · ${weekday}`;
  const day = currentDayRecord(false);
  $("#dayNotes").value = day?.notes || "";
  if (day?.raidKey) $("#dayRaid").value = day.raidKey;
  const attendance = new Map((day?.attendance || []).map(row => [row.playerId, row.status]));
  const players = roster().filter(row => row.active);
  $("#attendance").innerHTML = players.length ? players.map(player => {
    const status = attendance.get(player.id) || "present";
    const isLeave = ["leave", "absent"].includes(status);
    return `<button class="attendance-card ${isLeave ? "leave" : ""}" data-player="${escapeHtml(player.id)}" data-status="${isLeave ? "leave" : "present"}">
      <span><strong>${escapeHtml(player.name)}</strong><small class="class-colored" style="--class-color:${CLASS_COLORS[player.classKey] || "#8d9cab"}">${escapeHtml(player.className || "未设置职业")}</small></span>
      <span class="attendance-state">${isLeave ? "请假" : "出勤"}</span>
    </button>`;
  }).join("") : `<div class="empty">团队名单为空，请先维护成员。</div>`;
  $("#attendance").querySelectorAll(".attendance-card").forEach(card => card.addEventListener("click", async () => {
    if (!canModify()) return;
    const isLeave = card.dataset.status !== "leave";
    card.dataset.status = isLeave ? "leave" : "present";
    card.classList.toggle("leave", isLeave);
    card.querySelector(".attendance-state").textContent = isLeave ? "请假" : "出勤";
    await saveDay(true);
  }));
}

function captureDay() {
  const day = currentDayRecord(true);
  day.raidKey = $("#dayRaid").value || day.raidKey;
  day.notes = $("#dayNotes").value.trim();
  day.attendance = [...$("#attendance").querySelectorAll(".attendance-card")]
    .filter(card => card.dataset.status !== "present")
    .map(card => ({ playerId: card.dataset.player, status: card.dataset.status, note: "" }));
}

async function saveDay(silent = false) {
  if (!canModify()) return;
  try {
    captureDay();
    await api("/api/loot/setup", { method: "PUT", body: JSON.stringify({ days: documentState.state.days }) });
    if (!silent) notify("当天出勤与备注已保存。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function renderRecipientOptions() {
  const eligibility = new Map((documentState?.eligibility || []).map(row => [row.playerId, row]));
  const current = $("#recipientSelect").value;
  $("#recipientSelect").innerHTML = roster().filter(row => row.active).map(player => {
    const entry = eligibility.get(player.id);
    return `<option value="${escapeHtml(player.id)}">${entry && !entry.needEligible ? "⚠ " : ""}${escapeHtml(player.name)} · ${escapeHtml(player.className || "未设置职业")}</option>`;
  }).join("") || `<option value="">请先维护团队成员</option>`;
  if ([...$("#recipientSelect").options].some(option => option.value === current)) $("#recipientSelect").value = current;
  applyRecipientColor();
}

function applyRecipientColor() {
  $("#recipientSelect").style.color = playerColor($("#recipientSelect").value);
}

function renderClassFilter() {
  const current = $("#classFilter").value;
  $("#classFilter").innerHTML = `<option value="">全部职业</option>${CLASS_OPTIONS.map(([key, name]) => `<option value="${key}">${name}</option>`).join("")}`;
  $("#classFilter").value = current;
}

function renderBossOptions() {
  const current = $("#bossSelect").value;
  const bosses = [...(selectedRaid()?.bosses || [])].sort((a, b) => (a.order || 0) - (b.order || 0));
  $("#bossSelect").innerHTML = bosses.map(boss => `<option value="${escapeHtml(boss.key)}">${boss.order ? `${boss.order}. ` : ""}${escapeHtml(boss.name)}</option>`).join("");
  if ([...$("#bossSelect").options].some(option => option.value === current)) $("#bossSelect").value = current;
  renderItemOptions();
}

function filteredItems() {
  const query = $("#itemSearch").value.trim().toLowerCase();
  const lootType = $("#lootTypeFilter").value;
  const armor = $("#armorFilter").value;
  const classKey = $("#classFilter").value;
  return (selectedBoss()?.items || []).filter(item => {
    const haystack = [item.nameZh, item.nameEn, item.lootType, item.slot, ...(item.tags || [])].join(" ").toLowerCase();
    return (!query || haystack.includes(query))
      && (!lootType || item.lootType === lootType)
      && (!armor || item.armorType === armor)
      && (!classKey || !(item.classes || []).length || item.classes.includes(classKey));
  });
}

function renderItemOptions() {
  const current = $("#itemSelect").value;
  const items = filteredItems();
  $("#itemSelect").innerHTML = items.length ? items.map(item => `<option value="${item.id}">${escapeHtml(item.nameZh)} · ${escapeHtml(item.lootType)} / ${escapeHtml(item.slot)}</option>`).join("") : `<option value="">没有符合条件的掉落</option>`;
  if (items.some(item => String(item.id) === current)) $("#itemSelect").value = current;
}

function renderRequests() {
  $("#requestRows").innerHTML = roster().filter(row => row.active).map(player => `<div class="request-row" data-player="${escapeHtml(player.id)}"><strong class="class-colored" style="--class-color:${CLASS_COLORS[player.classKey] || "#edf2f7"}">${escapeHtml(player.name)}</strong><select><option value="">未登记</option>${Object.entries(MODE_NAMES).map(([key, name]) => `<option value="${key}">${name}</option>`).join("")}</select><input placeholder="备注（可选）"></div>`).join("");
}

function renderAllocations() {
  const rows = documentState.state.allocations.filter(row => row.date === selectedDate);
  $("#allocationCount").textContent = `${rows.length} 件`;
  const allBosses = raids().flatMap(raid => raid.bosses || []);
  $("#allocationList").classList.toggle("empty", !rows.length);
  $("#allocationList").innerHTML = rows.length ? rows.map(row => {
    const boss = allBosses.find(item => item.key === row.bossKey);
    const requests = (row.requests || []).map(request => `<span class="class-colored" style="${classStyle(request.playerId)}">${escapeHtml(playerName(request.playerId))}</span>：${MODE_NAMES[request.mode]}`).join(" · ");
    const itemName = row.itemNameZh || row.itemName;
    const itemTitle = /^\d+$/.test(String(row.itemId || ""))
      ? `<a class="item-link" href="https://www.wowhead.com/cn/item=${encodeURIComponent(row.itemId)}" target="_blank" rel="noreferrer">${escapeHtml(itemName)}</a>`
      : escapeHtml(itemName);
    return `<article class="allocation-card"><div><h4>${itemTitle}</h4><div class="allocation-meta"><span>${row.sourceType === "boe" ? "装绑物品" : escapeHtml(boss?.name || row.bossKey)}</span><span>${DIFFICULTY_NAMES[row.difficulty]}</span><span><span class="class-colored" style="${classStyle(row.recipientId)}">${escapeHtml(playerName(row.recipientId))}</span> · ${MODE_NAMES[row.awardType]}</span></div>${requests ? `<div class="allocation-note">需求详情：${requests}</div>` : ""}${row.notes ? `<div class="allocation-note">${escapeHtml(row.notes)}</div>` : ""}</div><button class="button danger delete-allocation" data-id="${escapeHtml(row.id)}">删除</button></article>`;
  }).join("") : "当天还没有分配记录";
  $("#allocationList").querySelectorAll(".delete-allocation").forEach(button => button.addEventListener("click", () => deleteAllocation(button.dataset.id)));
}

function toggleBoe() {
  const checked = $("#isBoe").checked;
  $("#itemSelectWrap").hidden = checked;
  $("#boeNameWrap").hidden = !checked;
  $("#itemFilters").hidden = checked;
  $("#bossSelect").disabled = checked;
}

function allocationPayload() {
  const isBoe = $("#isBoe").checked;
  const item = isBoe ? null : (selectedBoss()?.items || []).find(row => String(row.id) === $("#itemSelect").value);
  const requests = [...$("#requestRows").querySelectorAll(".request-row")].map(row => ({ playerId: row.dataset.player, mode: row.querySelector("select").value, note: row.querySelector("input").value.trim() })).filter(row => row.mode);
  return {
    date: selectedDate,
    raidKey: $("#dayRaid").value,
    bossKey: isBoe ? "boe" : $("#bossSelect").value,
    difficulty: $("#difficultySelect").value,
    sourceType: isBoe ? "boe" : "boss",
    itemId: item?.id || "",
    itemName: item?.nameEn || $("#boeName").value.trim(),
    itemNameZh: item?.nameZh || $("#boeName").value.trim(),
    itemTags: item?.tags || ["BOE"],
    recipientId: $("#recipientSelect").value,
    awardType: $("#awardType").value,
    requests,
    notes: $("#allocationNotes").value.trim()
  };
}

async function addAllocation() {
  if (!canModify()) return;
  const payload = allocationPayload();
  try {
    await api("/api/loot/allocations", { method: "POST", body: JSON.stringify(payload) });
  } catch (error) {
    if (!error.requiresConfirmation) return notify(error.message, true);
    const warningText = (error.warnings || []).map(value => `• ${value}`).join("\n");
    if (!confirm(`${warningText}\n\n这是提醒而不是拦截。仍然创建这条分配记录吗？`)) return;
    payload.confirmOverride = true;
    try {
      await api("/api/loot/allocations", { method: "POST", body: JSON.stringify(payload) });
    } catch (secondError) { return notify(secondError.message, true); }
  }
  $("#allocationNotes").value = "";
  $("#boeName").value = "";
  notify("掉落分配已登记。");
  await load();
}

async function deleteAllocation(id) {
  if (!canModify() || !confirm("确定删除这条分配记录吗？")) return;
  try {
    await api(`/api/loot/allocations/${encodeURIComponent(id)}`, { method: "DELETE" });
    notify("分配记录已删除。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function openRoster() {
  renderRoster();
  $("#rosterBackdrop").hidden = false;
}

function closeRoster() { $("#rosterBackdrop").hidden = true; }

function renderRoster() {
  const classOptions = CLASS_OPTIONS.map(([key, name]) => `<option value="${key}">${name}</option>`).join("");
  $("#rosterRows").innerHTML = roster().length ? roster().map(player => `<div class="roster-row" data-id="${escapeHtml(player.id)}">
    <label>角色名<input class="player-name" value="${escapeHtml(player.name)}"></label>
    <label>职业<select class="player-class"><option value="">未设置</option>${classOptions}</select></label>
    <label>护甲<select class="player-armor">${Object.entries(ARMOR_NAMES).filter(([key]) => ["cloth", "leather", "mail", "plate"].includes(key)).map(([key, name]) => `<option value="${key}">${name}</option>`).join("")}</select></label>
    <label class="active"><input type="checkbox" ${player.active ? "checked" : ""}>活动</label>
    <button class="button danger remove-player">移除</button>
  </div>`).join("") : `<div class="empty">还没有团队成员。</div>`;
  $("#rosterRows").querySelectorAll(".roster-row").forEach(row => {
    const player = roster().find(item => item.id === row.dataset.id);
    row.querySelector(".player-class").value = player.classKey || "";
    row.querySelector(".player-armor").value = player.armorType || "plate";
    row.querySelector(".player-class").style.color = CLASS_COLORS[player.classKey] || "#edf2f7";
    row.querySelector(".player-class").addEventListener("change", event => {
      const meta = CLASS_OPTIONS.find(item => item[0] === event.target.value);
      event.target.style.color = CLASS_COLORS[event.target.value] || "#edf2f7";
      if (meta) row.querySelector(".player-armor").value = meta[2];
    });
    row.querySelector(".remove-player").addEventListener("click", () => {
      captureRoster();
      documentState.state.roster = roster().filter(item => item.id !== row.dataset.id);
      renderRoster();
    });
  });
}

function captureRoster() {
  documentState.state.roster = [...$("#rosterRows").querySelectorAll(".roster-row")].map(row => {
    const classKey = row.querySelector(".player-class").value;
    const meta = CLASS_OPTIONS.find(item => item[0] === classKey);
    return { id: row.dataset.id, name: row.querySelector(".player-name").value.trim(), classKey, className: meta?.[1] || "", armorType: row.querySelector(".player-armor").value, active: row.querySelector(".active input").checked, notes: "" };
  }).filter(row => row.name);
}

async function saveRoster() {
  try {
    captureRoster();
    await api("/api/loot/setup", { method: "PUT", body: JSON.stringify({ roster: roster(), days: documentState.state.days }) });
    notify("团队名单已保存，并会自动应用到所有开荒日。");
    closeRoster();
    await load();
  } catch (error) { notify(error.message, true); }
}

async function toggleMythicSchedule() {
  const current = Number(documentState.state.settings.mythicCadenceWeeks || 2);
  const cadence = current === 2 ? 1 : 2;
  try {
    await api("/api/loot/settings", { method: "PUT", body: JSON.stringify({ mythicCadenceWeeks: cadence }) });
    notify(cadence === 2 ? "史诗难度已切换为双周刷新，锚点为 2026-08-20。" : "史诗难度已切换为单周刷新，每周四显示绿点。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function initAmbientCanvas() {
  const canvas = $("#ambientCanvas");
  const context = canvas?.getContext("2d");
  if (!context) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let width = 0;
  let height = 0;
  let particles = [];

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const count = Math.max(18, Math.min(44, Math.round(width / 34)));
    particles = Array.from({ length: count }, (_, index) => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - .5) * .12,
      vy: (Math.random() - .5) * .12,
      radius: 1 + Math.random() * 1.8,
      color: ["121,174,252", "85,214,155", "231,183,92"][index % 3]
    }));
  }

  function draw() {
    context.clearRect(0, 0, width, height);
    particles.forEach((point, index) => {
      if (!reduceMotion) {
        point.x = (point.x + point.vx + width) % width;
        point.y = (point.y + point.vy + height) % height;
      }
      context.beginPath();
      context.fillStyle = `rgba(${point.color},.24)`;
      context.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
      context.fill();
      for (let next = index + 1; next < particles.length; next += 1) {
        const other = particles[next];
        const distance = Math.hypot(point.x - other.x, point.y - other.y);
        if (distance > 125) continue;
        context.beginPath();
        context.strokeStyle = `rgba(121,174,252,${(1 - distance / 125) * .055})`;
        context.moveTo(point.x, point.y);
        context.lineTo(other.x, other.y);
        context.stroke();
      }
    });
    if (!reduceMotion) requestAnimationFrame(draw);
  }

  resize();
  draw();
  window.addEventListener("resize", () => { resize(); if (reduceMotion) draw(); }, { passive: true });
}

$("#prevMonth").addEventListener("click", () => { displayedMonth = new Date(displayedMonth.getFullYear(), displayedMonth.getMonth() - 1, 1); renderCalendar(); });
$("#nextMonth").addEventListener("click", () => { displayedMonth = new Date(displayedMonth.getFullYear(), displayedMonth.getMonth() + 1, 1); renderCalendar(); });
$("#closeDay").addEventListener("click", closeDay);
$("#drawerBackdrop").addEventListener("click", closeDay);
$("#saveDay").addEventListener("click", () => saveDay(false));
$("#dayRaid").addEventListener("change", () => { currentDayRecord(true).raidKey = $("#dayRaid").value; renderBossOptions(); });
$("#bossSelect").addEventListener("change", renderItemOptions);
$("#difficultySelect").addEventListener("change", load);
$("#recipientSelect").addEventListener("change", applyRecipientColor);
$("#itemSearch").addEventListener("input", renderItemOptions);
$("#lootTypeFilter").addEventListener("change", renderItemOptions);
$("#armorFilter").addEventListener("change", renderItemOptions);
$("#classFilter").addEventListener("change", renderItemOptions);
$("#isBoe").addEventListener("change", toggleBoe);
$("#addAllocation").addEventListener("click", addAllocation);
$("#manageRoster").addEventListener("click", openRoster);
$("#closeRoster").addEventListener("click", closeRoster);
$("#rosterBackdrop").addEventListener("click", event => { if (event.target === $("#rosterBackdrop")) closeRoster(); });
$("#saveRoster").addEventListener("click", saveRoster);
$("#mythicToggle").addEventListener("click", toggleMythicSchedule);
$("#addPlayer").addEventListener("click", () => {
  captureRoster();
  documentState.state.roster.push({ id: `p-${Date.now().toString(36)}`, name: "", classKey: "", className: "", armorType: "plate", active: true, notes: "" });
  renderRoster();
  $("#rosterRows .roster-row:last-child .player-name")?.focus();
});

initAmbientCanvas();
load().catch(error => notify(error.message, true));
