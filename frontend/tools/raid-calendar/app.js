const CLASS_OPTIONS = [
  ["death-knight", "死亡骑士", "plate"], ["demon-hunter", "恶魔猎手", "leather"],
  ["druid", "德鲁伊", "leather"], ["evoker", "唤魔师", "mail"],
  ["hunter", "猎人", "mail"], ["mage", "法师", "cloth"], ["monk", "武僧", "leather"],
  ["paladin", "圣骑士", "plate"], ["priest", "牧师", "cloth"], ["rogue", "潜行者", "leather"],
  ["shaman", "萨满祭司", "mail"], ["warlock", "术士", "cloth"], ["warrior", "战士", "plate"]
];
const DIFFICULTY_NAMES = { lfr: "随机团队", normal: "普通", heroic: "英雄", mythic: "史诗" };
const VERDICT_NAMES = { black: "拉了", red: "神了", neutral: "行吧" };
const VERDICT_LABELS = { black: "⚫ 拉了", red: "🔴 神了", neutral: "⚪ 行吧" };
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
const BLACK_HISTORY_PAGE_SIZE = 8;
let blackHistoryPage = 1;

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

// ===== 通用确认对话框（替代原生 confirm）=====
function confirmDialog({ title = "请确认", message = "", confirmText = "确定", cancelText = "取消", danger = false } = {}) {
  return new Promise(resolve => {
    $("#confirmDialogTitle").textContent = title;
    const body = $("#confirmDialogBody");
    body.innerHTML = "";
    String(message).split("\n").forEach(line => {
      const div = document.createElement("div");
      div.className = "confirm-line";
      div.textContent = line;
      body.appendChild(div);
    });
    const okButton = $("#confirmDialogOk");
    okButton.textContent = confirmText;
    okButton.classList.toggle("danger", Boolean(danger));
    $("#confirmDialogCancelBtn").textContent = cancelText;
    const close = result => {
      $("#confirmDialogBackdrop").hidden = true;
      $("#confirmDialogOk").onclick = null;
      $("#confirmDialogCancelBtn").onclick = null;
      $("#confirmDialogBackdrop").onclick = null;
      resolve(result);
    };
    $("#confirmDialogOk").onclick = () => close(true);
    $("#confirmDialogCancelBtn").onclick = () => close(false);
    $("#confirmDialogBackdrop").onclick = event => { if (event.target === $("#confirmDialogBackdrop")) close(false); };
    $("#confirmDialogBackdrop").hidden = false;
    okButton.focus();
  });
}

function roster() { return documentState?.state?.roster || []; }
function raids() { return documentState?.catalog?.raids || []; }
function selectedRaid() { return raids().find(row => row.key === $("#dayRaid").value) || raids()[0]; }
// 掉落登记的 Boss 跨团本聚合：所有团本的 Boss 直接进同一个下拉（按团本分组），无需切换
function allBosses() { return raids().flatMap(raid => (raid.bosses || []).map(boss => ({ ...boss, raidName: raid.name }))); }
function selectedBoss() { return allBosses().find(row => row.key === $("#bossSelect").value); }
function player(id) { return roster().find(row => row.id === id); }
// 昵称是主要辨识：显示为「昵称（角色名）」，没有昵称时退回角色名
function displayName(p) {
  if (!p) return "";
  const nickname = String(p.nickname || "").trim();
  return nickname ? `${nickname}（${p.name || "未命名"}）` : (p.name || "未命名");
}
function playerLabel(id) { const p = player(id); return p ? displayName(p) : id; }
// 只取昵称（无昵称退回角色名）：紧凑展示用
function playerNick(id) {
  const p = player(id);
  if (!p) return id;
  return String(p.nickname || "").trim() || p.name || id;
}
function playerName(id) { return playerLabel(id); }
function playerColor(id) { return CLASS_COLORS[player(id)?.classKey] || "#edf2f7"; }
function classStyle(id) { return `--class-color:${playerColor(id)}`; }
function blackmarks() { return documentState?.state?.blackMarks || []; }
// 黑本记录粒度 = 日期 + 副本 + 难度（同一天可黑多个副本）
function markFor(dateValue, difficulty, raidKey) { return blackmarks().find(row => row.date === dateValue && row.difficulty === difficulty && row.raidKey === raidKey); }
function markVerdict(row) { return ["red", "neutral"].includes(row?.verdict) ? row.verdict : "black"; }
function raidName(key) { return raids().find(row => row.key === key)?.name || key; }
function canModify() { return Boolean(documentState?.permissions?.canModify); }

function refreshWowheadTooltips() {
  if (window.WH?.Tooltips?.refreshLinks) {
    window.WH.Tooltips.refreshLinks();
  } else if (window.$WowheadPower?.refreshLinks) {
    window.$WowheadPower.refreshLinks();
  }
}

async function load() {
  documentState = await api(`/api/raid-calendar?date=${selectedDate}&difficulty=${$("#difficultySelect").value}`);
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
  renderBlackmarkSection();
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
  $("#progressionToggle").disabled = !canModify();
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
  const dateChanged = value !== selectedDate;
  selectedDate = value;
  if (dateChanged) {
    resetDrawerForms();
    document.dispatchEvent(new CustomEvent("day:selected", { detail: { date: value } }));
  }
  const parsed = new Date(`${value}T12:00:00`);
  displayedMonth = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  $("#drawerBackdrop").hidden = false;
  $("#dayDrawer").classList.add("open");
  $("#dayDrawer").setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  try { await load(); } catch (error) { notify(error.message, true); }
}

// 切换到另一天时，抽屉里的表单恢复初始状态，避免把上一天的输入带到新的一天
// 黑本编辑对话框每次打开都会重新填充，这里只需重置分配区
function resetDrawerForms() {
  $("#recipientSelect").value = "";
  $("#itemSearch").value = "";
  $("#allocationNotes").value = "";
  $("#boeName").value = "";
  const boe = $("#isBoe");
  if (boe.checked) { boe.checked = false; toggleBoe(); }
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
    // 默认团本取掉落目录第一个（当前 CD 的团本），不再写死
    const defaultRaid = raids()[0];
    day = { date: selectedDate, raidKey: defaultRaid?.key || "", notes: "", attendance: [], progressionOverride: null };
    documentState.state.days.push(day);
  }
  return day;
}

function renderRaidOptions() {
  const currentDay = currentDayRecord(false);
  const desired = currentDay?.raidKey || $("#dayRaid").value || raids()[0]?.key || "";
  $("#dayRaid").innerHTML = raids().map(raid => `<option value="${escapeHtml(raid.key)}">${escapeHtml(raid.name)}</option>`).join("");
  $("#dayRaid").value = desired;
}

function renderDay() {
  const date = new Date(`${selectedDate}T12:00:00`);
  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][date.getDay()];
  $("#selectedDateTitle").textContent = `${date.getMonth() + 1} 月 ${date.getDate()} 日 · ${weekday}`;
  const day = currentDayRecord(false);
  const isProgression = new Set(documentState?.calendar?.progressionDates || []).has(selectedDate);
  const progressionToggle = $("#progressionToggle");
  progressionToggle.textContent = isProgression ? "取消开荒日" : "设为开荒日";
  progressionToggle.classList.toggle("active", isProgression);
  progressionToggle.setAttribute("aria-pressed", isProgression ? "true" : "false");
  $("#dayNotes").value = day?.notes || "";
  if (day?.raidKey) $("#dayRaid").value = day.raidKey;
  const attendance = new Map((day?.attendance || []).map(row => [row.playerId, row.status]));
  const players = roster().filter(row => row.active);
  $("#attendance").innerHTML = players.length ? players.map(player => {
    const status = attendance.get(player.id) || "present";
    const isLeave = ["leave", "absent"].includes(status);
    const hasBlackMark = blackmarks().some(row => row.date === selectedDate && row.playerId === player.id);
    // 出勤卡只展示昵称，无昵称退回角色名；名字带职业色
    const nick = String(player.nickname || "").trim();
    const cardName = nick || player.name || "未命名";
    return `<button class="attendance-card ${isLeave ? "leave" : ""}" data-player="${escapeHtml(player.id)}" data-status="${isLeave ? "leave" : "present"}">
      <span class="attendance-name"><strong class="class-colored" style="--class-color:${CLASS_COLORS[player.classKey] || "#edf2f7"}">${escapeHtml(cardName)}${hasBlackMark ? ' <i class="black-dot" title="当天黑本"></i>' : ""}</strong></span>
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
    await api("/api/raid-calendar/setup", { method: "PUT", body: JSON.stringify({ days: documentState.state.days }) });
    if (!silent) notify("当天出勤与备注已保存。");
    await load();
  } catch (error) { notify(error.message, true); }
}

async function toggleProgressionDay() {
  if (!canModify()) return;
  const wasProgression = new Set(documentState?.calendar?.progressionDates || []).has(selectedDate);
  try {
    captureDay();
    currentDayRecord(true).progressionOverride = !wasProgression;
    await api("/api/raid-calendar/setup", { method: "PUT", body: JSON.stringify({ days: documentState.state.days }) });
    notify(wasProgression ? "已取消该日期的开荒日标记。" : "已将该日期设为开荒日。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function renderRecipientOptions() {
  const eligibility = new Map((documentState?.eligibility || []).map(row => [row.playerId, row]));
  const current = $("#recipientSelect").value;
  const markedToday = new Set(blackmarks().filter(row => row.date === selectedDate).map(row => row.playerId));
  $("#recipientSelect").innerHTML = roster().filter(row => row.active).map(player => {
    const entry = eligibility.get(player.id);
    const color = CLASS_COLORS[player.classKey] || "#edf2f7";
    const warnParts = [];
    if (markedToday.has(player.id) && player.id !== current) warnParts.push("⚫已黑");
    if (entry && !entry.needEligible) warnParts.push("⚠无需求权");
    return `<option value="${escapeHtml(player.id)}" style="color:${color}">${warnParts.length ? `${warnParts.join("·")} ` : ""}${escapeHtml(displayName(player))} · ${escapeHtml(player.className || "未设置职业")}</option>`;
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
  const bosses = allBosses();
  // 用 optgroup 按团本分组，尼姆瑞莎·唤波者等所有 Boss 直接可见可选
  $("#bossSelect").innerHTML = raids().filter(raid => (raid.bosses || []).length).map(raid => {
    const group = [...raid.bosses].sort((a, b) => (a.order || 0) - (b.order || 0))
      .map(boss => `<option value="${escapeHtml(boss.key)}">${escapeHtml(boss.name)}</option>`).join("");
    return `<optgroup label="${escapeHtml(raid.name)}">${group}</optgroup>`;
  }).join("");
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
  // 装备名带护甲类型，例如「板甲护腕」而不是单纯的「护腕」
  $("#itemSelect").innerHTML = items.length ? items.map(item => {
    const armorLabel = ARMOR_NAMES[item.armorType];
    const armorText = item.lootType === "装备" && armorLabel && !["accessory", "weapon", "other"].includes(item.armorType) ? `${armorLabel}` : "";
    return `<option value="${item.id}">${escapeHtml(item.nameZh)}${armorText ? ` · ${escapeHtml(armorText)}` : ""} · ${escapeHtml(item.lootType)} / ${escapeHtml(item.slot)}</option>`;
  }).join("") : `<option value="">没有符合条件的掉落</option>`;
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
      ? `<a class="item-link" href="https://www.wowhead.com/cn/item=${encodeURIComponent(row.itemId)}" data-wowhead="domain=cn" target="_blank" rel="noreferrer">${escapeHtml(itemName)}</a>`
      : escapeHtml(itemName);
    return `<article class="allocation-card"><div><h4>${itemTitle}</h4><div class="allocation-meta"><span>${row.sourceType === "boe" ? "装绑物品" : escapeHtml(boss?.name || row.bossKey)}</span><span>${DIFFICULTY_NAMES[row.difficulty]}</span><span><span class="class-colored" style="${classStyle(row.recipientId)}">${escapeHtml(playerName(row.recipientId))}</span> · ${MODE_NAMES[row.awardType]}</span></div>${requests ? `<div class="allocation-note">需求详情：${requests}</div>` : ""}${row.notes ? `<div class="allocation-note">${escapeHtml(row.notes)}</div>` : ""}</div><button class="button danger delete-allocation" data-id="${escapeHtml(row.id)}">删除</button></article>`;
  }).join("") : "当天还没有分配记录";
  $("#allocationList").querySelectorAll(".delete-allocation").forEach(button => button.addEventListener("click", () => deleteAllocation(button.dataset.id)));
  refreshWowheadTooltips();
}

function toggleBoe() {
  const checked = $("#isBoe").checked;
  $("#itemSelectWrap").hidden = checked;
  $("#boeNameWrap").hidden = !checked;
  $("#itemFilters").hidden = checked;
  $("#bossSelect").disabled = checked;
}

// ===== 黑本（BLACK LEDGER）=====
// 编辑器状态：null = 新增（干净表单），否则为待编辑记录的 {raidKey, difficulty}
let blackmarkEditing = null;

function populateBlackmarkForm({ raidKey, difficulty, playerId, verdict, notes }) {
  const select = $("#blackPlayer");
  const options = roster().filter(row => row.active).map(row => `<option value="${escapeHtml(row.id)}" style="color:${CLASS_COLORS[row.classKey] || "#edf2f7"}">${escapeHtml(displayName(row))} · ${escapeHtml(row.className || "未设置职业")}</option>`).join("");
  select.innerHTML = `<option value="">未标记（当天不黑）</option>${options}`;
  const raidSelect = $("#blackRaid");
  const dayRaidKey = (currentDayRecord(false) || {}).raidKey || raids()[0]?.key || "";
  raidSelect.innerHTML = raids().map(raid => `<option value="${escapeHtml(raid.key)}">${escapeHtml(raid.name)}</option>`).join("");
  // 新增时默认当日团队副本；编辑/手动切换用传入值
  raidSelect.value = raids().some(raid => raid.key === (raidKey || dayRaidKey)) ? (raidKey || dayRaidKey) : (raids()[0]?.key || "");
  $("#blackDifficulty").value = difficulty || "heroic";
  if ([...select.options].some(option => option.value === (playerId || ""))) select.value = playerId || "";
  else select.value = "";
  applySelectColor(select);
  $("#blackVerdict").value = markVerdict({ verdict: verdict });
  $("#blackNotes").value = notes || "";
}

function renderBlackmarkSection() {
  renderExistingBlackmarks();
}

function openBlackmarkEditor(row) {
  // row 为空 → 新增：干净表单，避免上一次的输入残留
  blackmarkEditing = row ? { raidKey: row.raidKey, difficulty: row.difficulty } : null;
  $("#blackmarkEditorTitle").textContent = row ? "编辑黑本记录" : "添加黑本记录";
  $("#blackmarkEditorCopy").textContent = row
    ? `${selectedDate} · ${raidName(row.raidKey)} · ${DIFFICULTY_NAMES[row.difficulty]}`
    : `日期：${selectedDate} · 默认为当日团队副本`;
  populateBlackmarkForm({
    raidKey: row?.raidKey,
    difficulty: row?.difficulty,
    playerId: row?.playerId,
    verdict: row ? markVerdict(row) : "black",
    notes: row?.notes,
  });
  $("#blackmarkEditorBackdrop").hidden = false;
}

function closeBlackmarkEditor() { $("#blackmarkEditorBackdrop").hidden = true; }

function renderExistingBlackmarks() {
  const rows = blackmarks().filter(row => row.date === selectedDate);
  const box = $("#existingBlackmarks");
  box.innerHTML = rows.length ? rows.map(row => {
    const verdict = markVerdict(row);
    return `<div class="existing-blackmark ${verdict}">
      <span class="bm-who class-colored" style="${classStyle(row.playerId)}">${escapeHtml(playerNick(row.playerId))}</span>
      <span class="bm-tag">${escapeHtml(raidName(row.raidKey))}·${DIFFICULTY_NAMES[row.difficulty]}</span>
      <span class="bm-verdict ${verdict}">${VERDICT_NAMES[verdict]}</span>
      ${row.notes ? `<span class="bm-notes" title="${escapeHtml(row.notes)}">${escapeHtml(row.notes)}</span>` : ""}
      <span class="bm-actions"><button class="button danger bm-edit" data-raid="${escapeHtml(row.raidKey)}" data-diff="${row.difficulty}">编辑</button><button class="button danger bm-delete" data-id="${escapeHtml(row.id)}">删除</button></span>
    </div>`;
  }).join("") : `<div class="empty-bm">当天暂无黑本记录，点右上「＋ 添加」登记。</div>`;
  box.querySelectorAll(".bm-edit").forEach(button => button.addEventListener("click", () => {
    const row = blackmarks().find(item => item.date === selectedDate && item.raidKey === button.dataset.raid && item.difficulty === button.dataset.diff);
    if (row) openBlackmarkEditor(row);
  }));
  box.querySelectorAll(".bm-delete").forEach(button => button.addEventListener("click", () => deleteBlackmark(button.dataset.id)));
}

function applySelectColor(select) {
  select.style.color = playerColor(select.value);
}

async function confirmReBlackmark(playerId, dateValue, raidKey, difficulty) {
  // 玄学规则：该玩家在这个副本+难度下已有「拉了」的黑本记录，再建黑本时抛出提醒
  if (!playerId) return true;
  const prior = blackmarks().filter(row =>
    row.playerId === playerId && row.date < dateValue
    && row.raidKey === raidKey && row.difficulty === difficulty
    && markVerdict(row) === "black");
  if (!prior.length) return true;
  const lines = prior.map(row =>
    `${playerNick(playerId)}于${row.date}让${DIFFICULTY_NAMES[difficulty]}难度的${raidName(raidKey)}掉落拉了库里，备注为${row.notes ? row.notes : "无"}，确定还要让他黑本🐎？`);
  return confirmDialog({
    title: "⚠ 再黑本提醒",
    message: lines.join("\n\n"),
    confirmText: "仍然保存",
    danger: true,
  });
}

async function saveBlackmark() {
  if (!canModify()) return notify("当前账号没有修改权限。", true);
  const playerId = $("#blackPlayer").value;
  const raidKey = $("#blackRaid").value;
  const difficulty = $("#blackDifficulty").value;
  if (!raidKey) return notify("请选择副本。", true);
  if (playerId && !(await confirmReBlackmark(playerId, selectedDate, raidKey, difficulty))) return;
  try {
    await api("/api/raid-calendar/blackmarks", { method: "POST", body: JSON.stringify({
      date: selectedDate,
      difficulty,
      raidKey,
      playerId,
      verdict: markVerdict({ verdict: $("#blackVerdict").value }),
      notes: $("#blackNotes").value.trim(),
    }) });
    const verdictName = VERDICT_NAMES[markVerdict({ verdict: $("#blackVerdict").value })];
    notify(playerId ? `黑本记录已保存（${raidName(raidKey)}·${verdictName}）。` : "该副本该难度的黑本已清空。");
    closeBlackmarkEditor();
    await load();
  } catch (error) { notify(error.message, true); }
}

async function deleteBlackmark(id) {
  if (!canModify()) return;
  if (!(await confirmDialog({ title: "删除黑本标记", message: "确定删除这条黑本标记吗？该操作不可恢复。", confirmText: "删除", danger: true }))) return;
  try {
    await api(`/api/raid-calendar/blackmarks/${encodeURIComponent(id)}`, { method: "DELETE" });
    notify("黑本标记已删除。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function openBlackHistory(playerId = "") {
  const filter = $("#blackHistoryFilter");
  const options = roster().map(row => `<option value="${escapeHtml(row.id)}" style="color:${CLASS_COLORS[row.classKey] || "#edf2f7"}">${escapeHtml(displayName(row))}</option>`).join("");
  filter.innerHTML = `<option value="">全部玩家</option>${options}`;
  filter.value = playerId || "";
  const raidFilter = $("#blackHistoryRaid");
  const currentRaid = raidFilter.value;
  raidFilter.innerHTML = `<option value="">全部副本</option>` + raids().map(raid => `<option value="${escapeHtml(raid.key)}">${escapeHtml(raid.name)}</option>`).join("");
  raidFilter.value = raids().some(raid => raid.key === currentRaid) ? currentRaid : "";
  blackHistoryPage = 1;
  renderBlackHistory();
  $("#blackHistoryBackdrop").hidden = false;
}

function closeBlackHistory() { $("#blackHistoryBackdrop").hidden = true; }

function filteredBlackmarks() {
  const playerFilter = $("#blackHistoryFilter").value;
  const raidFilter = $("#blackHistoryRaid")?.value || "";
  const difficultyFilter = $("#blackHistoryDifficulty")?.value || "";
  const verdictFilter = $("#blackHistoryVerdict")?.value || "";
  return blackmarks()
    .filter(row => (!playerFilter || row.playerId === playerFilter)
      && (!raidFilter || row.raidKey === raidFilter)
      && (!difficultyFilter || row.difficulty === difficultyFilter)
      && (!verdictFilter || markVerdict(row) === verdictFilter))
    .sort((left, right) => `${right.date}|${right.createdAt || ""}`.localeCompare(`${left.date}|${left.createdAt || ""}`));
}

function renderBlackHistory() {
  const rows = filteredBlackmarks();
  const pageCount = Math.max(1, Math.ceil(rows.length / BLACK_HISTORY_PAGE_SIZE));
  blackHistoryPage = Math.min(Math.max(1, blackHistoryPage), pageCount);
  const pageStart = (blackHistoryPage - 1) * BLACK_HISTORY_PAGE_SIZE;
  const pageRows = rows.slice(pageStart, pageStart + BLACK_HISTORY_PAGE_SIZE);
  const list = $("#blackHistoryList");
  list.classList.toggle("empty", !rows.length);
  // 汇总统计：各判定次数
  const statsBox = $("#blackHistoryStats");
  const blackCount = rows.filter(row => markVerdict(row) === "black").length;
  const redCount = rows.filter(row => markVerdict(row) === "red").length;
  const neutralCount = rows.filter(row => markVerdict(row) === "neutral").length;
  statsBox.innerHTML = `<span>共 <strong>${rows.length}</strong> 条</span><span class="stat-black">⚫ 拉了 <strong>${blackCount}</strong> 次</span><span class="stat-red">🔴 神了 <strong>${redCount}</strong> 次</span><span class="stat-neutral">⚪ 行吧 <strong>${neutralCount}</strong> 次</span>`;
  list.innerHTML = rows.length ? pageRows.map((row, index) => {
    const p = player(row.playerId);
    const verdict = markVerdict(row);
    return `<article class="history-card ${verdict}" style="--history-index:${index}">
      <div class="history-main">
        <span class="class-colored history-player" style="${classStyle(row.playerId)}">${escapeHtml(playerNick(row.playerId))}</span>
        <small>${escapeHtml(p?.className || "")}</small>
      </div>
      <div class="history-meta">
        <span>${escapeHtml(row.date)}</span>
        <span>${escapeHtml(raidName(row.raidKey))}·${DIFFICULTY_NAMES[row.difficulty]}</span>
        <span class="bm-verdict ${verdict}">${VERDICT_NAMES[verdict]}</span>
        ${row.notes ? `<span class="bm-notes" title="${escapeHtml(row.notes)}">${escapeHtml(row.notes)}</span>` : ""}
      </div>
      <button class="button danger bm-delete" data-id="${escapeHtml(row.id)}">删除</button>
    </article>`;
  }).join("") : "还没有任何黑本记录";
  const pagination = $("#blackHistoryPagination");
  pagination.hidden = rows.length <= BLACK_HISTORY_PAGE_SIZE;
  $("#blackHistoryPageInfo").textContent = `第 ${blackHistoryPage} / ${pageCount} 页 · ${rows.length} 条`;
  $("#blackHistoryPrev").disabled = blackHistoryPage <= 1;
  $("#blackHistoryNext").disabled = blackHistoryPage >= pageCount;
  list.querySelectorAll(".bm-delete").forEach(button => button.addEventListener("click", async () => {
    if (!(await confirmDialog({ title: "删除黑本标记", message: "确定删除这条黑本标记吗？该操作不可恢复。", confirmText: "删除", danger: true }))) return;
    try {
      await api(`/api/raid-calendar/blackmarks/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
      notify("黑本标记已删除。");
      await load();
      renderBlackHistory();
      const filter = $("#blackHistoryFilter");
      [...filter.options].forEach(option => { if (!option.value || player(option.value)) option.hidden = false; });
    } catch (error) { notify(error.message, true); }
  }));
}

async function confirmContinueIfBlack(playerId, dateValue, difficultyValue = "", raidKey = "") {
  // 玄学规则：该玩家在相同副本+相同难度下被判过「黑」，再想黑本时抛出提示
  const sameDifficultyMarks = blackmarks().filter(row =>
    row.playerId === playerId && row.date < dateValue
    && (!difficultyValue || row.difficulty === difficultyValue)
    && (!raidKey || row.raidKey === raidKey)
    && markVerdict(row) === "black");
  if (!sameDifficultyMarks.length) return true;
  const lines = sameDifficultyMarks.slice(0, 3).map(row => `• 该玩家于 ${row.date} 黑本【${escapeHtml(raidName(row.raidKey))}·${DIFFICULTY_NAMES[row.difficulty]}】且判定为「拉了」${row.notes ? `，备注：${row.notes}` : ""}`);
  return confirmDialog({
    title: "⚠ 该玩家此前黑本掉落「拉了」",
    message: `${raidKey ? raidName(raidKey) : "相同副本"}·${difficultyValue ? DIFFICULTY_NAMES[difficultyValue] : "相同难度"}\n${lines.join("\n")}\n你确定还要让该玩家继续当这次的黑本（第一个进本）吗？`,
    confirmText: "仍然分配",
    danger: true,
  });
}

function allocationPayload() {
  const isBoe = $("#isBoe").checked;
  const item = isBoe ? null : (selectedBoss()?.items || []).find(row => String(row.id) === $("#itemSelect").value);
  const requests = [...$("#requestRows").querySelectorAll(".request-row")].map(row => ({ playerId: row.dataset.player, mode: row.querySelector("select").value, note: row.querySelector("input").value.trim() })).filter(row => row.mode);
  const boss = selectedBoss();
  const bossRaidKey = boss ? raids().find(raid => (raid.bosses || []).some(row => row.key === boss.key))?.key : null;
  return {
    date: selectedDate,
    raidKey: bossRaidKey || $("#dayRaid").value,
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
  if (!(await confirmContinueIfBlack(payload.recipientId, selectedDate, payload.difficulty, payload.raidKey))) return;
  try {
    await api("/api/raid-calendar/allocations", { method: "POST", body: JSON.stringify(payload) });
  } catch (error) {
    if (!error.requiresConfirmation) return notify(error.message, true);
    const warningText = (error.warnings || []).map(value => `• ${value}`).join("\n");
    if (!(await confirmDialog({
      title: "分配提醒",
      message: `${warningText}\n\n这是提醒而不是拦截。仍然创建这条分配记录吗？`,
      confirmText: "仍然创建",
      danger: true,
    }))) return;
    payload.confirmOverride = true;
    try {
      await api("/api/raid-calendar/allocations", { method: "POST", body: JSON.stringify(payload) });
    } catch (secondError) { return notify(secondError.message, true); }
  }
  $("#allocationNotes").value = "";
  $("#boeName").value = "";
  notify("掉落分配已登记。");
  await load();
}

async function deleteAllocation(id) {
  if (!canModify()) return;
  if (!(await confirmDialog({ title: "删除分配记录", message: "确定删除这条分配记录吗？该操作不可恢复。", confirmText: "删除", danger: true }))) return;
  try {
    await api(`/api/raid-calendar/allocations/${encodeURIComponent(id)}`, { method: "DELETE" });
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
  const classOptions = CLASS_OPTIONS.map(([key, name]) => `<option value="${key}" style="color:${CLASS_COLORS[key] || "#edf2f7"}">${name}</option>`).join("");
  // 紧凑表格式：表头行 + 每人一行；列含义由表头说明，单元格内只放控件
  $("#rosterRows").innerHTML = roster().length
    ? `<div class="roster-head"><span>昵称</span><span>角色名</span><span>职业</span><span>活动</span><span></span></div>` + roster().map(player => `<div class="roster-row" data-id="${escapeHtml(player.id)}">
    <input class="player-nickname" value="${escapeHtml(player.nickname || "")}" placeholder="请输入昵称" aria-label="昵称">
    <input class="player-name" value="${escapeHtml(player.name)}" placeholder="请输入角色名" aria-label="角色名">
    <select class="player-class" aria-label="职业"><option value="" style="color:#edf2f7">未设置</option>${classOptions}</select>
    <label class="active"><input type="checkbox" ${player.active ? "checked" : ""}>活动</label>
    <button class="button danger remove-player">删除</button>
  </div>`).join("")
    : `<div class="empty">还没有团队成员。</div>`;
  $("#rosterRows").querySelectorAll(".roster-row").forEach(row => {
    const player = roster().find(item => item.id === row.dataset.id);
    row.querySelector(".player-class").value = player.classKey || "";
    // 护甲类型由职业自动推导，不再单独维护
    row.querySelector(".player-class").style.color = CLASS_COLORS[player.classKey] || "#edf2f7";
    // 职业决定护甲类型：选职业后自动带出对应护甲
    row.querySelector(".player-class").addEventListener("change", event => {
      event.target.style.color = CLASS_COLORS[event.target.value] || "#edf2f7";
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
    // 护甲类型始终由职业表推导，保持旧数据字段兼容
    return { id: row.dataset.id, name: row.querySelector(".player-name").value.trim(), nickname: row.querySelector(".player-nickname").value.trim(), classKey, className: meta?.[1] || "", armorType: meta?.[2] || player(row.dataset.id)?.armorType || "plate", active: row.querySelector(".active input").checked, notes: "" };
  }).filter(row => row.name);
}

async function saveRoster() {
  try {
    captureRoster();
    await api("/api/raid-calendar/setup", { method: "PUT", body: JSON.stringify({ roster: roster(), days: documentState.state.days }) });
    notify("团队名单已保存，并会自动应用到所有开荒日。");
    closeRoster();
    await load();
  } catch (error) { notify(error.message, true); }
}

async function toggleMythicSchedule() {
  const current = Number(documentState.state.settings.mythicCadenceWeeks || 2);
  const cadence = current === 2 ? 1 : 2;
  try {
    await api("/api/raid-calendar/settings", { method: "PUT", body: JSON.stringify({ mythicCadenceWeeks: cadence }) });
    notify(cadence === 2 ? "史诗难度已切换为双周刷新，锚点为 2026-08-27。" : "史诗难度已切换为单周刷新，每周四显示绿点。");
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
$("#progressionToggle").addEventListener("click", toggleProgressionDay);
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
$("#blackHistoryButton").addEventListener("click", () => openBlackHistory());
$("#closeBlackHistory").addEventListener("click", closeBlackHistory);
$("#blackHistoryBackdrop").addEventListener("click", event => { if (event.target === $("#blackHistoryBackdrop")) closeBlackHistory(); });
const resetBlackHistoryPage = () => { blackHistoryPage = 1; renderBlackHistory(); };
$("#blackHistoryFilter").addEventListener("change", resetBlackHistoryPage);
$("#blackHistoryRaid")?.addEventListener("change", resetBlackHistoryPage);
$("#blackHistoryDifficulty")?.addEventListener("change", resetBlackHistoryPage);
$("#blackHistoryVerdict")?.addEventListener("change", resetBlackHistoryPage);
$("#blackHistoryPrev").addEventListener("click", () => { blackHistoryPage -= 1; renderBlackHistory(); });
$("#blackHistoryNext").addEventListener("click", () => { blackHistoryPage += 1; renderBlackHistory(); });
// 黑本编辑对话框：＋添加 = 干净表单；编辑 = 带出该条数据
$("#addBlackmark").addEventListener("click", () => openBlackmarkEditor(null));
$("#closeBlackmarkEditor").addEventListener("click", closeBlackmarkEditor);
$("#blackmarkEditorBackdrop").addEventListener("click", event => { if (event.target === $("#blackmarkEditorBackdrop")) closeBlackmarkEditor(); });
$("#blackRaid").addEventListener("change", () => {
  const raidSelect = $("#blackRaid");
  if (blackmarkEditing) { blackmarkEditing.raidKey = raidSelect.value; }
  const copy = $("#blackmarkEditorCopy");
  copy.textContent = `${selectedDate} · ${raidName(raidSelect.value)} · ${DIFFICULTY_NAMES[$("#blackDifficulty").value]}`;
});
$("#blackDifficulty").addEventListener("change", () => {
  if (blackmarkEditing) { blackmarkEditing.difficulty = $("#blackDifficulty").value; }
  const copy = $("#blackmarkEditorCopy");
  copy.textContent = `${selectedDate} · ${raidName($("#blackRaid").value)} · ${DIFFICULTY_NAMES[$("#blackDifficulty").value]}`;
});
$("#blackPlayer").addEventListener("change", () => applySelectColor($("#blackPlayer")));
$("#saveBlackmark").addEventListener("click", saveBlackmark);
$("#addPlayer").addEventListener("click", () => {
  captureRoster();
  documentState.state.roster.push({ id: `p-${Date.now().toString(36)}`, name: "", classKey: "", className: "", armorType: "plate", active: true, notes: "" });
  renderRoster();
  $("#rosterRows .roster-row:last-child .player-name")?.focus();
});

initAmbientCanvas();
load().catch(error => notify(error.message, true));
